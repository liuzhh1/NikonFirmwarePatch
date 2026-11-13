"""Real NRMT AArch64 execution, frame guards and strict full-input overlays.

Full formatter tests execute all20+13 native callbacks. Audited external
math/calibration/string APIs use bounded fixtures; no codec or file I/O.
"""
from functools import lru_cache
import json
import os
from pathlib import Path
import struct
import unittest
from z8opengate4k.nrmt_lifetime import BASE, FRAME, RING, compile_nrmt
from z8patch.image import branch
import test_opengate4k_frontend as frontend

COOKIE = 0x4F47344B4E524D54
RETURN = 0x40160000
SP = 0xA06100000
REAL_INPUTS = frontend.AVAILABLE and all(os.environ.get(n) for n in ('OG4K_ORIGINAL', 'OG4K_BASELINE'))


@unittest.skipUnless(frontend.AVAILABLE, 'Set OG4K_COMPILER and install Unicorn')
class NrmtScopeExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frontend.FrontendExecution.setUpClass()
        cls.code, cls.meta = compile_nrmt(os.environ['OG4K_COMPILER'])
        profile = json.loads((Path(__file__).resolve().parents[1]/'z8opengate4k/nrmt-lifetime-profile.json').read_text())
        if cls.meta != profile['compiled']: raise AssertionError('NRMT scope profile differs')

    def setUp(self):
        self.f = frontend.FrontendExecution(); self.f.setUp()
        self.u, self.A = self.f.uc, frontend.A
        self.u.mem_map(0x42160000, 0x03000000); self.u.mem_write(BASE, self.code)
        self.source = 0xA06010000
        self.u.mem_write(self.source, bytes(self.u.mem_read(self.f.snapshot, 0x3a4)))
        self.f.w32(self.source+8, 8)
        self.f.w32(0xA0FF6F000, 1); self.u.mem_write(0xA02A979FE, struct.pack('<H', 2756))
        self.u.mem_write(0xA02A979EE, struct.pack('<H', 5520))
        self.f.w32(0x440D0908, 2330); self.f.w32(0x440D0910, 4652)
        self.f.w32(0x440D0AF0, 2322); self.f.w32(0x440D0AF8, 4644)
        self.f.stops.update({0x410A4FC8, 0x410A5910, 0x410A6D10})

    def r(self, i): return self.u.reg_read(getattr(self.A, f'UC_ARM64_REG_X{i}'))
    def reg(self, i, v): self.u.reg_write(getattr(self.A, f'UC_ARM64_REG_X{i}'), v)
    def q(self, a): return struct.unpack('<Q', self.u.mem_read(a, 8))[0]
    def wq(self, a, v): self.u.mem_write(a, struct.pack('<Q', v))
    def run_entry(self, name):
        self.u.emu_start(self.meta['entries'][name], 0, count=5000)
        self.assertIn(self.u.reg_read(self.A.UC_ARM64_REG_PC), self.f.stops)

    def enter(self, request=4, source=None, output=0xA06020000):
        self.u.reg_write(self.A.UC_ARM64_REG_SP, SP); self.reg(30, RETURN)
        for i, v in enumerate((request, self.source if source is None else source, 0xA06021000, output)): self.reg(i, v)
        self.run_entry('og4k_nrmt_scope_hook')
        self.wrapper = SP-48
        return self.f.word(self.wrapper+36)

    def frame(self, crop=False, wrapper=None):
        self.wrapper = SP-48 if wrapper is None else wrapper
        self.wq(self.wrapper+16, self.source); self.wq(self.wrapper+24, COOKIE)
        self.f.w32(self.wrapper+32, 4); self.f.w32(self.wrapper+36, 1); self.f.w32(self.wrapper+40, 4)
        native = self.wrapper-(0x120 if crop else 0xD0)
        self.wq(native+(0x118 if crop else 0xC8), self.meta['entries']['og4k_nrmt_scope_return'])
        if crop:
            self.wq(native+0x38, 0x410A6348); self.wq(native+0x40, 0x410A541C)
        self.u.reg_write(self.A.UC_ARM64_REG_SP, native)
        self.reg(30, 0x410A64C0 if crop else 0x410A541C)
        self.reg(0, self.source); self.reg(1, 0xA06020000)
        if crop: self.reg(8, 4); self.reg(10, 0x440D0AE0)
        else: self.reg(8, 0x440D0900); self.reg(9, 2)
        return native

    def height(self, crop=False):
        self.run_entry('og4k_scoped_nrmt_crop_hook' if crop else 'og4k_scoped_nrmt_height_hook')
        return self.r(8)

    def test_entry_captures_each_low_rate_and_keeps_native_arguments(self):
        for rate in (4, 5, 6):
            self.f.set_mode(rate=rate); self.f.w32(self.source+0x390, rate)
            self.assertEqual(self.enter(), 1)
            self.assertEqual(tuple(self.r(i) for i in range(4)), (4, self.source, 0xA06021000, 0xA06020000))
            self.assertEqual(self.q(self.wrapper+16), self.source)
            self.assertEqual(self.f.word(self.wrapper+32), rate)
            self.assertEqual(self.u.reg_read(self.A.UC_ARM64_REG_SP), self.wrapper-0xD0)

    def test_entry_rejects_wrong_selection_snapshot_and_request(self):
        for a, v in ((0xA03D5C014, 2), (0xA03BB71D8, 6), (0xA03BB71DC, 5),
                      (0xA0FF6F000, 0), (0xA02A979FE, 2344), (self.source, 0),
                      (self.source+8, 4), (self.source+0x388, 5), (self.source+0x38c, 6),
                      (self.source+0x390, 3), (self.source+0x3a0, 3)):
            old = bytes(self.u.mem_read(a, 4)); self.f.w32(a, v)
            self.assertEqual(self.enter(), 0, hex(a)); self.u.mem_write(a, old)
        self.assertEqual(self.enter(request=3), 0)
        self.assertEqual(self.enter(source=0), 0)
        self.assertEqual(self.enter(output=0), 0)

    def test_height_and_nested_crop_ignore_later_current_selection(self):
        for crop, expected in ((False, 2756), (True, 2752)):
            self.frame(crop)
            self.f.set_mode(flag=0, file_type=2, size=6, rate=3)
            self.f.w32(0xA0FF6F000, 0); self.u.mem_write(0xA02A979FE, struct.pack('<H', 2344))
            self.assertEqual(self.height(crop), expected)

    def test_each_saved_return_link_is_required_before_using_stack_identity(self):
        for crop, offsets in ((False, (0xC8,)), (True, (0x38, 0x40, 0x118))):
            for offset in offsets:
                native = self.frame(crop); self.wq(native+offset, 0)
                self.assertEqual(self.height(crop), 2322 if crop else 2330)
            self.frame(crop); self.reg(30, RETURN)
            self.assertEqual(self.height(crop), 2322 if crop else 2330)

    def test_capsule_owner_cookie_target_kind_and_rate_mismatch_use_native_values(self):
        for crop in (False, True):
            for offset, value in ((16, 0), (24, 0), (32, 5), (36, 0), (40, 3)):
                self.frame(crop); self.wq(self.wrapper+offset, value)
                self.assertEqual(self.height(crop), 2322 if crop else 2330)

    def test_guard_preserves_scratch_flags_and_exact_stack_depth(self):
        for crop in (False, True):
            native = self.frame(crop); before = (self.r(16), self.r(17))
            flags = self.u.reg_read(self.A.UC_ARM64_REG_NZCV)
            self.height(crop)
            self.assertEqual((self.r(16), self.r(17)), before)
            self.assertEqual(self.u.reg_read(self.A.UC_ARM64_REG_NZCV), flags)
            self.assertEqual(self.u.reg_read(self.A.UC_ARM64_REG_SP), native)

    def test_return_erases_capsule_and_keeps_original_result_and_parent_frame(self):
        before29 = self.r(29); self.enter()
        self.reg(0, 0x87654321); self.u.reg_write(self.A.UC_ARM64_REG_SP, self.wrapper)
        self.run_entry('og4k_nrmt_scope_return')
        self.assertEqual(self.r(0), 0x87654321); self.assertEqual(self.r(29), before29)
        self.assertEqual(self.u.reg_read(self.A.UC_ARM64_REG_SP), SP)
        self.assertEqual(bytes(self.u.mem_read(SP-48+16, 32)), bytes(32))

    def test_original_eight_k_fallback_remains_and_ordinary_frame_cannot_be_promoted(self):
        for crop in (False, True):
            self.frame(crop); self.f.w32(self.wrapper+36, 0)
            self.f.w32(self.source+8, 4); self.f.w32(self.source+0x38c, 6)
            self.assertEqual(self.height(crop), 5504 if crop else 5512)
            self.f.w32(self.source+8, 8); self.f.w32(self.source+0x38c, 4)
            self.frame(crop); self.f.w32(self.wrapper+36, 0)
            self.assertEqual(self.height(crop), 2322 if crop else 2330)


@lru_cache(maxsize=1)
def complete_inputs():
    from verify import decode
    from z8opengate4k.nrmt_lifetime import make_nrmt_main
    original = Path(os.environ['OG4K_ORIGINAL']).read_bytes(); baseline = Path(os.environ['OG4K_BASELINE']).read_bytes()
    new, report = make_nrmt_main(original, baseline, os.environ['OG4K_COMPILER'], playback=True, nctg_lifetime=True)
    minimal, min_report = make_nrmt_main(original, baseline, os.environ['OG4K_COMPILER'])
    return new, report, minimal, min_report, decode(baseline)[581844:82389553]


class NativeNrmtHarness:
    """Real native generator; external non-geometry APIs are explicit fixtures."""
    def __init__(self, image, report):
        self.A = frontend.A; self.u = frontend.Uc(frontend.UC_ARCH_ARM64, frontend.UC_MODE_ARM)
        self.u.mem_map(0x40160000, 0x05000000); self.u.mem_map(0xA00000000, 0x10000000)
        self.u.mem_write(0x40160000, image); self.u.mem_write(0xA02808000, image[0x4B13000:])
        self.report = report; self.source = 0xA06010000; self.extra = 0xA06020000; self.output = 0xA06021000
        self.zero_lookup = 0xA06030000; self.apis = set(); self.locations = {}; self.events = []
        self.switch_at = None; self.switch_fields = {}; self.switched = False
        self.hook = self.u.hook_add(frontend.UC_HOOK_CODE, self.observe)
        for i in range(RING['slots']): self.qwrite(RING['pointer_table']+8*i, 0xA06200000+i*0x2000)
        for i in range(31): self.reg(i, 0x123000+i)
        self.u.reg_write(self.A.UC_ARM64_REG_D8, 0x123456789ABCDEF0)
        self.u.reg_write(self.A.UC_ARM64_REG_D9, 0xABCDEF0123456789)
        self.prepare()

    def close(self): self.u.hook_del(self.hook)
    def reg(self, i, value=None):
        r = getattr(self.A, f'UC_ARM64_REG_X{i}')
        if value is None: return self.u.reg_read(r)
        self.u.reg_write(r, value)
    def word(self, a, value): self.u.mem_write(a, struct.pack('<I', value))
    def qwrite(self, a, value): self.u.mem_write(a, struct.pack('<Q', value))
    def qread(self, a): return struct.unpack('<Q', self.u.mem_read(a, 8))[0]

    def selection(self, flag=1, size=4, rate=4, file_type=6):
        for a, v in ((0xA03D5C014, file_type), (0xA03BB71D8, size), (0xA03BB71DC, rate),
                      (0xA0FF6F000, int(flag == 1))): self.word(a, v)
        self.u.mem_write(0xA03D5C02B, bytes([flag]))
        self.u.mem_write(0xA02A979FE, struct.pack('<H', 2756 if flag == 1 else 2344))
        self.u.mem_write(0xA02A979EE, struct.pack('<H', 5520 if flag == 1 else 4688))

    def prepare(self, flag=1, size=4, rate=4, actual=8):
        self.selection(flag=flag, size=size, rate=rate)
        self.u.mem_write(self.source, bytes(0x3000))
        for o, v in ((0, 1), (8, actual), (0x388, 4), (0x38c, size), (0x390, rate), (0x3a0, 4)):
            self.word(self.source+o, v)

    def observe(self, u, a, n, data):
        if a == RETURN: u.emu_stop(); return
        if self.switch_at == a and not self.switched:
            self.selection(**self.switch_fields); self.switched = True
        if a in (0x410A58E4, 0x410A6C88): self.locations[a] = self.reg(1)
        if a in [self.report['nrmt_lifetime']['compiled']['entries'][k] for k in
                 ('og4k_scoped_nrmt_height_hook', 'og4k_scoped_nrmt_crop_hook')]:
            self.events.append((a, self.u.reg_read(self.A.UC_ARM64_REG_SP), self.reg(30)))
        if (0x410A4FC4 <= a < 0x410A7260 or BASE <= a < BASE+self.report['nrmt_lifetime']['compiled']['bytes']
                or 0x40960000 <= a < 0x40963000
                or self.report['recorder']['compiled']['base'] <= a < self.report['recorder']['compiled']['base']+self.report['recorder']['compiled']['bytes']): return
        self.apis.add(a)
        if a in (0x4127A900, 0x4127AF38):
            dst, src, count = (self.reg(i) for i in range(3))
            if count > 0x10000: raise AssertionError('Unbounded native copy fixture')
            u.mem_write(dst, bytes(u.mem_read(src, count))); self.reg(0, dst)
        elif a == 0x4127AB40:
            dst, val, count = (self.reg(i) for i in range(3))
            if count > 0x10000: raise AssertionError('Unbounded native clear fixture')
            u.mem_write(dst, bytes([val & 255])*count); self.reg(0, dst)
        elif a in (0x4127B2C0, 0x4127B424): self.reg(0, bytes(u.mem_read(self.reg(0), 0x1000)).index(0))
        elif a == 0x4127D2E0: u.mem_write(self.reg(0), b'000000000000\x00'); self.reg(0, 12)
        elif a == 0x41061928: self.reg(0, self.zero_lookup)
        elif a in (0x40C78570, 0x40C7858C, 0x40C79248, 0x40C79230, 0x40C790DC, 0x40C79038,
                   0x40C784D4, 0x40C784EC, 0x41068C04):
            self.reg(0, 0); u.reg_write(self.A.UC_ARM64_REG_S0, 0)
        elif a == 0x4105ABCC: u.mem_write(self.reg(1), bytes(8)); self.reg(0, 1)
        elif a == 0x41187368: u.mem_write(self.reg(2), bytes(6)); self.reg(0, 1)
        elif a == 0x41059DB4: u.mem_write(self.reg(1), bytes(0xB8)); self.reg(0, 1)
        else: raise AssertionError(f'Unexpected native call {a:#x}, LR={self.reg(30):#x}')
        u.reg_write(self.A.UC_ARM64_REG_PC, self.reg(30))

    def run(self, scoped=True, request=4, null_source=False, null_output=False, switch_at=None, switch_fields=None):
        meta = self.report['nrmt_lifetime']['compiled']; old = self.report['recorder']['compiled']['entries']
        patches = {0x410A4FC4: branch(0x410A4FC4, meta['entries']['og4k_nrmt_scope_hook'], False) if scoped else bytes.fromhex('ff4303d1'),
                   0x410A590C: branch(0x410A590C, meta['entries']['og4k_scoped_nrmt_height_hook'] if scoped else old['og4k_nrmt_hook'], False),
                   0x410A6D0C: branch(0x410A6D0C, meta['entries']['og4k_scoped_nrmt_crop_hook'] if scoped else old['og4k_crop_hook'], False)}
        for a, data in patches.items(): self.u.mem_write(a, data); self.u.ctl_remove_cache(a, a+4)
        self.locations = {}; self.events = []; self.switch_at = switch_at; self.switch_fields = switch_fields or {}; self.switched = False
        self.u.mem_write(self.output, bytes(0x38)); self.u.reg_write(self.A.UC_ARM64_REG_SP, SP)
        for i, v in enumerate((request, 0 if null_source else self.source, self.extra, 0 if null_output else self.output)): self.reg(i, v)
        self.reg(30, RETURN); self.u.emu_start(0x410A4FC4, 0, count=100000)
        if self.u.reg_read(self.A.UC_ARM64_REG_PC) != RETURN: raise AssertionError('Native formatter did not return')
        descriptor = bytes(self.u.mem_read(self.output, 0x38)); pointer = self.qread(self.output+0x18)
        length = struct.unpack_from('<I', descriptor, 0x20)[0]
        if length > 0x2000: raise AssertionError('Unbounded native packet')
        packet = bytes(self.u.mem_read(pointer, length)) if pointer and length else b''
        wire = {a: bytes(self.u.mem_read(ptr, 5 if a == 0x410A58E4 else 16)) for a, ptr in self.locations.items()}
        return dict(descriptor=descriptor, pointer=pointer, packet=packet, wire=wire, result=self.reg(0))


@unittest.skipUnless(REAL_INPUTS, 'Set complete original/baseline and compiler for native NRMT execution')
class NativeNrmtExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.image, cls.report, *_ = complete_inputs()
    def setUp(self): self.h = NativeNrmtHarness(self.image, self.report)
    def tearDown(self): self.h.close()
    def geometry(self, result, coded, active):
        self.assertEqual(int.from_bytes(result['wire'][0x410A58E4], 'big'), coded)
        self.assertEqual(struct.unpack_from('<HH', result['wire'][0x410A6C88], 12), (4128, active))

    def test_native_main_and_nested_callbacks_emit_all_three_candidate_rates(self):
        for rate in (4, 5, 6):
            self.h.prepare(rate=rate); result = self.h.run(); self.geometry(result, 2756, 2752)
            packet = result['packet']; self.assertEqual(packet[4:8], b'NRAW')
            at = 40; tags = []
            for _ in range(20):
                length, tag = struct.unpack_from('>I4xI', packet, at)
                self.assertGreaterEqual(length, 12); self.assertLessEqual(at+length, len(packet))
                tags.append(tag); at += length
            self.assertEqual((tags[1], tags[-1]), (0x01100101, 0x02000001))
            self.assertEqual(len(self.h.events), 2)

    def test_menu_change_before_height_or_between_height_and_crop_keeps_exact_packet(self):
        ideal = self.h.run()['packet']
        for at in (0x410A53B4, 0x410A6334):
            self.h.prepare(); result = self.h.run(switch_at=at, switch_fields=dict(flag=0, size=6, rate=3, file_type=2))
            self.assertTrue(self.h.switched); self.geometry(result, 2756, 2752)
            self.assertEqual(result['packet'], ideal)

    def test_ordinary_invocation_is_not_promoted_when_open_gate_is_enabled_mid_call(self):
        self.h.prepare(flag=0); ideal = self.h.run()['packet']
        self.h.prepare(flag=0); result = self.h.run(switch_at=0x410A53B4, switch_fields=dict(flag=1))
        self.geometry(result, 2330, 2322); self.assertEqual(result['packet'], ideal)

    def test_stable_candidate_ordinary_and_eight_k_packets_match_previous_layer(self):
        for fields in (dict(), dict(flag=0), dict(size=6, actual=4)):
            self.h.prepare(**fields); new = self.h.run()
            self.h.prepare(**fields); old = self.h.run(scoped=False)
            self.assertEqual(new['packet'], old['packet']); self.assertEqual(new['wire'], old['wire'])

    def test_only_geometry_bytes_change_between_ordinary_and_candidate_wire_packets(self):
        self.h.prepare(flag=0); ordinary = self.h.run()
        self.h.prepare(); candidate = self.h.run()
        self.geometry(ordinary, 2330, 2322); self.geometry(candidate, 2756, 2752)
        changed = {i for i, (a, b) in enumerate(zip(ordinary['packet'], candidate['packet'])) if a != b}
        self.assertEqual(len(ordinary['packet']), len(candidate['packet']))
        self.assertEqual(changed, {72, 73, 598, 599})

    def test_real_formatter_early_returns_keep_original_results_and_clear_capsule(self):
        for args in (dict(null_source=True), dict(null_output=True), dict(request=5)):
            self.h.prepare(); new = self.h.run(**args)
            self.assertEqual(bytes(self.h.u.mem_read(SP-48+16, 32)), bytes(32))
            self.h.prepare(); old = self.h.run(scoped=False, **args)
            self.assertEqual((new['descriptor'], new['result']), (old['descriptor'], old['result']))

    def test_native_return_preserves_callee_registers_source_and_serialized_output(self):
        registers = [self.h.reg(i) for i in range(19, 30)]
        floating = [self.h.u.reg_read(getattr(frontend.A, f'UC_ARM64_REG_D{i}')) for i in (8, 9)]
        source = bytes(self.h.u.mem_read(self.h.source, 0x3000)); result = self.h.run()
        self.assertEqual([self.h.reg(i) for i in range(19, 30)], registers)
        self.assertEqual([self.h.u.reg_read(getattr(frontend.A, f'UC_ARM64_REG_D{i}')) for i in (8, 9)], floating)
        self.assertEqual(bytes(self.h.u.mem_read(self.h.source, 0x3000)), source)
        self.assertEqual(self.h.u.reg_read(frontend.A.UC_ARM64_REG_SP), SP)
        self.assertEqual(bytes(self.h.u.mem_read(SP-48+16, 32)), bytes(32))
        self.h.selection(flag=0, size=6, rate=3, file_type=2)
        self.assertEqual(bytes(self.h.u.mem_read(result['pointer'], len(result['packet']))), result['packet'])

    def test_native_sixty_slot_ring_retains_then_reuses_the_packet(self):
        first = self.h.run(); self.h.prepare(flag=0)
        for _ in range(59): self.assertNotEqual(self.h.run()['pointer'], first['pointer'])
        self.assertEqual(bytes(self.h.u.mem_read(first['pointer'], len(first['packet']))), first['packet'])
        wrapped = self.h.run(); self.assertEqual(wrapped['pointer'], first['pointer'])
        self.assertNotEqual(wrapped['packet'], first['packet'])
        self.geometry(wrapped, 2330, 2322)


@unittest.skipUnless(REAL_INPUTS, 'Set original/baseline and compiler for complete-input integration')
class NrmtScopeOverlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.new, cls.report, cls.minimal, cls.min_report, cls.baseline = complete_inputs()

    def test_parent_hashes_and_all_undeclared_bytes_preserved(self):
        self.assertEqual(self.report['nrmt_parent_main_sha256'], '6f5564176d15b682df517ba4c5a7a6557f53cfb695691a19b1736bbde8a62e85')
        self.assertEqual(self.min_report['nrmt_parent_main_sha256'], '9bfa80f4270dc789924a3f717134f35b3adaefb66a881a71808dd361aa71b5b1')
        for raw, report in ((self.new, self.report), (self.minimal, self.min_report)):
            end = 0
            for start, stop in sorted((int(w['address'], 16)-0x40160000, int(w['address'], 16)-0x40160000+w['bytes']) for w in report['writes']):
                self.assertGreaterEqual(start, end); self.assertEqual(raw[end:start], self.baseline[end:start]); end = stop
            self.assertEqual(raw[end:], self.baseline[end:]); self.assertEqual(len(raw), 81807709)

    def test_real_native_saved_link_offsets_callback_tables_and_sixty_slot_ring(self):
        b = 0x40160000
        # Original STP x29,x30,[sp,#C0] and STP x19,x30,[sp,#30].
        self.assertEqual(self.baseline[0x410A4FE0-b:0x410A4FE4-b], bytes.fromhex('fd7b0ca9'))
        self.assertEqual(self.baseline[0x410A647C-b:0x410A6480-b], bytes.fromhex('f37b03a9'))
        self.assertEqual(FRAME['native_saved_lr_offset'], 0xC8)
        self.assertEqual(FRAME['nested_formatter_saved_lr_offset'], 0x38)
        self.assertEqual(struct.unpack_from('<Q', self.baseline, 0x440D0790-b+16)[0], 0x410A58E4)
        self.assertEqual(struct.unpack_from('<Q', self.baseline, 0x440D0990-b+6*8)[0], 0x410A6C88)
        word = struct.unpack_from('<I', self.baseline, 0x410A5060-b)[0]
        self.assertEqual(((word >> 10) & 0xFFF)+1, 60)
        self.assertEqual((RING['index']-RING['pointer_table'])//8, RING['slots'])

    def test_original_d10_nctg_copy_writer_close_and_native_body_retained(self):
        b = 0x40160000
        for a, n in ((0x40960000, 11568), (0x40CEEF10, 0x120), (0x410A4FC8, 0x680),
                     (0x410A6334, 0x24), (0x410A6470, 0x7c), (0x4071E224, 0x28)):
            self.assertEqual(self.new[a-b:a-b+n], self.baseline[a-b:a-b+n])

    def test_no_shared_state_and_close_recording_still_unqualified(self):
        self.assertFalse(self.report['flash_package_generated'])
        self.assertFalse(self.report['recording_4k_open_gate_implemented'])
        self.assertFalse(self.report['recorder']['file_callback_lifetime_qualified'])
        for k in ('shared_state_allocated', 'callback_uses_current_selection', 'ring_buffer_lifetime_qualified',
                  'writer_close_qualified', 'recording_qualified'): self.assertFalse(self.report['nrmt_lifetime'][k])


if __name__ == '__main__': unittest.main()

"""AArch64 NCTG private-copy ownership; native memcpy is a bounded API stub.

The caller's pointer publication is represented explicitly, separately from
the copied ImgInfo. This is not an execution of complete camera task/I/O.
"""
import json
import os
from pathlib import Path
import struct
import unittest
from z8opengate4k.nctg_lifetime import BASE, ATTR, PRIVATE_INFO, STATE_RAM, STATE_BYTES, compile_lifetime
import test_opengate4k_frontend as frontend


@unittest.skipUnless(frontend.AVAILABLE, 'Set OG4K_COMPILER and install Unicorn')
class NctgLifetimeExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frontend.FrontendExecution.setUpClass()
        cls.code, cls.meta = compile_lifetime(os.environ['OG4K_COMPILER'])
        root = Path(__file__).resolve().parents[1]
        if cls.meta != json.loads((root/'z8opengate4k/nctg-lifetime-profile.json').read_text())['compiled']:
            raise AssertionError('NCTG lifetime profile differs')

    def setUp(self):
        self.f = frontend.FrontendExecution(); self.f.setUp()
        self.u, self.A = self.f.uc, frontend.A
        self.u.mem_write(BASE, self.code)
        self.source, self.out = 0xA06010000, 0xA06020000
        self.f.stops.update({0x406D2C90, 0x406D313C, 0x406D3828, 0x41184DEC})
        self.copy_calls = []; self.copy_return = None
        self.u.hook_add(frontend.UC_HOOK_CODE, self.native_copy)
        self.prepare()

    def r(self, i): return self.u.reg_read(getattr(self.A, f'UC_ARM64_REG_X{i}'))
    def reg(self, i, value): self.u.reg_write(getattr(self.A, f'UC_ARM64_REG_X{i}'), value)
    def q(self, addr): return struct.unpack('<Q', self.u.mem_read(addr, 8))[0]
    def wq(self, addr, value): self.u.mem_write(addr, struct.pack('<Q', value))
    def call(self, entry):
        self.u.reg_write(self.A.UC_ARM64_REG_SP, 0xA06100000); self.reg(30, 0x40160000)
        self.u.emu_start(self.meta['entries'][entry], 0x40160000, count=6000)
        self.assertIn(self.u.reg_read(self.A.UC_ARM64_REG_PC), self.f.stops)

    def native_copy(self, u, address, size, data):
        if address != 0x4127A900: return
        dst, src, count = self.r(0), self.r(1), self.r(2)
        self.assertEqual(self.q(STATE_RAM), 0, 'Owner must be invalidated before native copy')
        self.assertLessEqual(count, 0x4490)
        self.copy_calls.append((dst, src, count))
        if count: u.mem_write(dst, bytes(u.mem_read(src, count)))
        for i in range(19): self.reg(i, 0xBAA000+i)
        self.reg(0, dst if self.copy_return is None else self.copy_return)
        u.reg_write(self.A.UC_ARM64_REG_PC, self.r(30))

    def prepare(self, flag=1, size=4, rate=4, file_type=6, actual=8):
        self.f.set_mode(flag=flag, size=size, rate=rate, file_type=file_type)
        self.f.w32(0xA0FF6F000, 1); self.f.w32(0xA02A979FE, 2756)
        self.f.w32(0xA02A979EE, 5520)
        self.u.mem_write(self.source, b'\x59'*0x4490)
        self.u.mem_write(self.source, bytes(self.u.mem_read(self.f.snapshot, 0x3a4)))
        self.f.w32(self.source+8, actual)
        self.u.mem_write(ATTR, bytes(0x100)); self.wq(ATTR, self.source)
        for off, val in ((0x20, file_type), (0xc, size), (0x10, rate)): self.f.w32(ATTR+off, val)
        self.u.mem_write(self.out, b'\xa5'*0x400)

    def clone(self, *, dst=PRIVATE_INFO, src=None, count=0x4490, publish=True):
        self.reg(0, dst); self.reg(1, self.source if src is None else src); self.reg(2, count)
        self.call('og4k_nctg_clone_hook')
        if publish: self.wq(ATTR, PRIVATE_INFO) # native4071E228, after copy hook returns

    def height(self, *, ctx=ATTR, proxy=False):
        self.reg(0, ctx); self.reg(1, self.out)
        self.call('og4k_owned_proxy_main_hook' if proxy else 'og4k_owned_height_hook')
        return self.r(9 if proxy else 8)

    def crop(self, ctx=ATTR):
        self.reg(0, ctx); self.reg(1, self.out); self.call('og4k_owned_crop_hook')

    def test_all_rates_keep_private_dimensions_after_stop_and_source_reuse(self):
        for rate in (4, 5, 6):
            self.prepare(rate=rate); self.clone()
            self.f.set_mode(flag=0, size=6, rate=3, file_type=2)
            self.f.w32(0xA0FF6F000, 0); self.f.w32(0xA02A979FE, 2344)
            self.u.mem_write(self.source, bytes(0x4490))
            self.assertEqual(self.height(), 2752); self.assertEqual(self.height(proxy=True), 2752)
            self.crop()
            self.assertEqual(struct.unpack('<7H', self.u.mem_read(self.out+0x332, 14)),
                             (11, 4140, 2756, 4140, 2756, 0, 0))

    def test_ordinary_copy_is_not_promoted_by_later_menu_selection(self):
        self.prepare(flag=0); self.clone(); self.assertEqual(self.f.word(STATE_RAM+20), 0)
        self.f.set_mode(flag=1); self.assertEqual(self.height(), 2322)
        self.assertEqual(self.height(proxy=True), 2322)
        before = bytes(self.u.mem_read(self.out, 0x400)); self.crop()
        self.assertEqual(bytes(self.u.mem_read(self.out, 0x400)), before)

    def test_replacing_native_working_copy_replaces_old_open_gate_identity(self):
        self.clone(); self.assertEqual(self.height(), 2752)
        self.prepare(flag=0); self.clone(); self.f.set_mode(flag=1)
        self.assertEqual(self.height(), 2322)
        self.prepare(rate=6); self.clone(); self.assertEqual(self.height(), 2752)

    def test_unexpected_copy_arguments_invalidate_previous_owner(self):
        for args in (dict(dst=self.source+0x5000), dict(count=0x4480), dict(src=self.source+0x10)):
            self.prepare(); self.clone(); self.clone(**args)
            self.assertEqual(self.q(STATE_RAM), 0); self.assertEqual(self.height(), 2322)

    def test_clone_requires_copied_attribute_identity_and_capture_time_selection(self):
        for address, value in ((ATTR+0x20, 2), (ATTR+0xc, 6), (ATTR+0x10, 3),
                               (0xA03D5C014, 2), (0xA03BB71D8, 6), (0xA03BB71DC, 5),
                               (0xA0FF6F000, 0), (0xA02A979FE, 2344)):
            self.prepare(); self.f.w32(address, value); self.clone()
            self.assertEqual(self.f.word(STATE_RAM+20), 0)
        self.prepare(flag=2); self.clone(); self.assertEqual(self.f.word(STATE_RAM+20), 0)

    def test_callbacks_revalidate_owner_marker_and_copied_mode_fields(self):
        for address, value in ((STATE_RAM, 0), (STATE_RAM+8, 0), (STATE_RAM+16, 6),
                               (STATE_RAM+20, 0), (STATE_RAM+24, 0), (ATTR, 0),
                               (ATTR+0x20, 2), (ATTR+0xc, 6), (ATTR+0x10, 5)):
            self.prepare(); self.clone(); self.f.w32(address, value)
            self.assertEqual(self.height(), 2322, hex(address))
            self.assertEqual(self.height(proxy=True), 2322, hex(address))
            before = bytes(self.u.mem_read(self.out, 0x400)); self.crop()
            expected = bytearray(before)
            if address == ATTR+0xc: # native8K claim delegates the original8K hook
                struct.pack_into('<7H', expected, 0x332, 11, 8280, 5520, 8280, 5520, 0, 0)
            self.assertEqual(bytes(self.u.mem_read(self.out, 0x400)), bytes(expected))

    def test_opaque_imginfo_is_not_assumed_to_have_nrmt_snapshot_layout(self):
        self.u.mem_write(self.source, b'\x59'*0x4490)
        self.clone(); self.assertEqual(self.height(), 2752)

    def test_unknown_attribute_object_never_uses_current_menu_to_override(self):
        self.clone(); other = self.out+0x500
        self.u.mem_write(other, bytes(self.u.mem_read(ATTR, 0x100)))
        self.assertEqual(self.height(ctx=other), 2322)
        self.assertEqual(self.height(ctx=other, proxy=True), 2322)
        before = bytes(self.u.mem_read(self.out, 0x400)); self.crop(ctx=other)
        self.assertEqual(bytes(self.u.mem_read(self.out, 0x400)), before)

    def test_proxy_keeps_native_raster_and_crop_but_associated_main_height(self):
        self.clone(); self.u.mem_write(ATTR+0xe0, b'\x01')
        self.assertEqual(self.height(), 2322); self.assertEqual(self.height(proxy=True), 2752)
        before = bytes(self.u.mem_read(self.out, 0x400)); self.crop()
        self.assertEqual(bytes(self.u.mem_read(self.out, 0x400)), before)

    def test_native_copy_bytes_return_value_callee_registers_and_stack_preserved(self):
        source = bytes(self.u.mem_read(self.source, 0x4490))
        before = [self.r(i) for i in range(19, 30)]; self.copy_return = 0x76543210
        self.clone(publish=False)
        self.assertEqual(self.r(0), self.copy_return)
        self.assertEqual([self.r(i) for i in range(19, 30)], before)
        self.assertEqual(self.u.reg_read(self.A.UC_ARM64_REG_SP), 0xA06100000)
        self.assertEqual(bytes(self.u.mem_read(PRIVATE_INFO, 0x4490)), source)
        self.assertEqual(bytes(self.u.mem_read(self.source, 0x4490)), source)
        self.assertEqual(self.copy_calls, [(PRIVATE_INFO, self.source, 0x4490)])
        self.assertEqual(self.q(ATTR), self.source, 'No native pointer publication inside hook')

    def test_callbacks_wait_for_original_native_pointer_publication(self):
        self.clone(publish=False); self.assertEqual(self.height(), 2322)
        self.wq(ATTR, PRIVATE_INFO); self.assertEqual(self.height(), 2752)

    def test_metadata_guards_keep_scratch_flags_stack_and_bounded_write_range(self):
        self.clone(); preserved = [self.r(i) for i in (16, 17, 19, 20, 21, 22, 23)]
        flags = self.u.reg_read(self.A.UC_ARM64_REG_NZCV)
        self.height()
        self.assertEqual([self.r(i) for i in (16, 17, 19, 20, 21, 22, 23)], preserved)
        self.assertEqual(self.u.reg_read(self.A.UC_ARM64_REG_NZCV), flags)
        before = bytes(self.u.mem_read(self.out, 0x400)); self.crop()
        expected = bytearray(before); struct.pack_into('<7H', expected, 0x332, 11, 4140, 2756, 4140, 2756, 0, 0)
        self.assertEqual(bytes(self.u.mem_read(self.out, 0x400)), bytes(expected))
        self.assertEqual(self.u.reg_read(self.A.UC_ARM64_REG_SP), 0xA06100000)

    def test_boot_reset_clears_private_state_only_at_native_text_reset(self):
        for reset in (0, 1):
            self.u.mem_write(STATE_RAM, b'\x5a'*STATE_BYTES); self.reg(19, reset)
            before = (self.r(8), self.r(9)); self.call('og4k_nctg_reset_hook')
            self.assertEqual(bytes(self.u.mem_read(STATE_RAM, STATE_BYTES)), bytes(STATE_BYTES) if reset else b'\x5a'*STATE_BYTES)
            self.assertEqual((self.r(8), self.r(9)), before)

    def test_original_eight_k_crop_fallback_still_runs(self):
        self.prepare(size=6, actual=4); self.clone(); self.crop()
        self.assertEqual(struct.unpack('<7H', self.u.mem_read(self.out+0x332, 14)),
                         (11, 8280, 5520, 8280, 5520, 0, 0))


REAL_INPUTS = all(os.environ.get(n) for n in ('OG4K_COMPILER', 'OG4K_ORIGINAL', 'OG4K_BASELINE'))
@unittest.skipUnless(REAL_INPUTS, 'Set original/baseline for complete-input integration')
class NctgLifetimeOverlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from verify import decode
        from z8opengate4k.nctg_lifetime import make_lifetime_main
        original = Path(os.environ['OG4K_ORIGINAL']).read_bytes()
        baseline = Path(os.environ['OG4K_BASELINE']).read_bytes()
        cls.baseline = decode(baseline)[581844:82389553]
        cls.new, cls.report = make_lifetime_main(original, baseline, os.environ['OG4K_COMPILER'], playback=True)
        cls.minimal, cls.min_report = make_lifetime_main(original, baseline, os.environ['OG4K_COMPILER'])

    def test_combined_parent_hashes_and_all_undeclared_bytes_preserved(self):
        self.assertEqual(self.report['nctg_parent_main_sha256'], '65e0a9eb894a8bcaec630952da4cc0e7dddc930b2be1e9453c1b03b92f583c24')
        self.assertEqual(self.min_report['nctg_parent_main_sha256'], '9bfa80f4270dc789924a3f717134f35b3adaefb66a881a71808dd361aa71b5b1')
        for raw, report in ((self.new, self.report), (self.minimal, self.min_report)):
            b = 0x40160000; end = 0
            for start, stop in sorted((int(w['address'], 16)-b, int(w['address'], 16)-b+w['bytes']) for w in report['writes']):
                self.assertGreaterEqual(start, end); self.assertEqual(raw[end:start], self.baseline[end:start]); end = stop
            self.assertEqual(raw[end:], self.baseline[end:]); self.assertEqual(len(raw), 81807709)

    def test_native_copy_sequence_writer_close_and_original_d10_preserved(self):
        b = 0x40160000
        # Primary firmware contract: NCTG's codec selector is not a menu snapshot.
        # LDR w8,[x0,#20h], then native table case6 selects N-RAW's quality leaf.
        word = struct.unpack_from('<I', self.baseline, 0x406D2CC0-b)[0]
        self.assertEqual(word & 0xFFC003FF, 0xB9400008)
        self.assertEqual(((word >> 10) & 0xFFF)*4, 0x20)
        self.assertEqual(struct.unpack_from('<Q', self.baseline, 0x440C7B50-b+5*8)[0], 0x406D2D00)
        for a, n in ((0x4071E1F4, 0x2c), (0x4071E224, 0x28), (0x40CEEF10, 0x120),
                     (0x40960000, 11568), (0x406D2C9C, 4), (0x406D3150, 4)):
            self.assertEqual(self.new[a-b:a-b+n], self.baseline[a-b:a-b+n])
        from z8patch.image import branch
        self.assertEqual(self.new[0x4071E220-b:0x4071E224-b],
                         branch(0x4071E220, self.report['nctg_lifetime']['compiled']['entries']['og4k_nctg_clone_hook'], True))

    def test_private_state_allocation_stays_in_verified_copied_cave_alias(self):
        from z8opengate4k.nctg_lifetime import STATE_ROM
        self.assertEqual(STATE_ROM+0x9CF600000, STATE_RAM)
        self.assertGreaterEqual(STATE_RAM, 0xA0FF6F124)
        self.assertLessEqual(STATE_ROM+STATE_BYTES, 0x40970000)
        self.assertEqual(self.new[STATE_ROM-0x40160000:STATE_ROM-0x40160000+STATE_BYTES], bytes(STATE_BYTES))

    def test_general_lifetime_and_recording_still_unqualified(self):
        self.assertFalse(self.report['flash_package_generated'])
        self.assertFalse(self.report['recording_4k_open_gate_implemented'])
        self.assertFalse(self.report['recorder']['file_callback_lifetime_qualified'])
        for name in ('callback_uses_current_selection', 'nrmt_lifetime_qualified',
                     'writer_close_lifetime_qualified', 'physical_recording_qualified'):
            self.assertFalse(self.report['nctg_lifetime'][name])


if __name__ == '__main__': unittest.main()

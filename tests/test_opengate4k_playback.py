"""Execute playback AArch64 with bounded native file-API/class-leaf stubs.

Native lookup/release, not a filesystem/codec, are represented by fixtures.
The original D10 machine code is executed for fallback/regression comparisons.
"""
import json
import os
from pathlib import Path
import struct
import unittest
from z8opengate4k.playback import BASE, SITES, compile_playback
import test_opengate4k_frontend as frontend


@unittest.skipUnless(frontend.AVAILABLE, 'Set OG4K_COMPILER and install Unicorn')
class PlaybackExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frontend.FrontendExecution.setUpClass()
        cls.code, cls.meta = compile_playback(os.environ['OG4K_COMPILER'])
        root = Path(__file__).resolve().parents[1]
        profile = json.loads((root/'z8opengate4k/playback-profile.json').read_text())
        if cls.meta != profile['compiled']:
            raise AssertionError('Playback profile differs')
        cls.old = {k: int(v['va'], 16) for k, v in json.loads(
            (root/'resources/compiled.json').read_text())['units']['opengate']['symbols'].items()}

    def setUp(self):
        self.f = frontend.FrontendExecution(); self.f.setUp()
        self.u, self.A = self.f.uc, frontend.A
        self.u.mem_write(BASE, self.code)
        self.image, self.info, self.handle = 0xA06003000, 0xA06004000, 0xA06005000
        self.dest, self.source, self.request = 0xA06006000, 0xA06007000, 0xA06008000
        self.f.w32(self.image, 0x1234)
        self.lookup_ok, self.return_info, self.return_handle = 1, self.info, self.handle
        self.stock_class = 1; self.lookups = []; self.releases = []; self.leaves = []
        self.f.stops.update({0x40711534, 0x407D2EAC, 0x407138D4})
        self.u.hook_add(frontend.UC_HOOK_CODE, self.native)
        self.file()

    def r(self, i): return self.u.reg_read(getattr(self.A, f'UC_ARM64_REG_X{i}'))
    def reg(self, i, value): self.u.reg_write(getattr(self.A, f'UC_ARM64_REG_X{i}'), value)
    def word(self, address): return self.f.word(address)
    def tag(self): return struct.unpack('<Q', self.u.mem_read(0xA0FF6F008, 8))[0]
    def file(self, width=4128, height=2752, kind=6, quality=0):
        self.u.mem_write(self.info, bytes(0x20))
        self.f.w32(self.info+4, kind << 20 | quality)
        self.u.mem_write(self.info+0xc, struct.pack('<HH', width, height))

    def native(self, u, address, size, data):
        if address == 0x407CD844:
            self.lookups.append(self.r(0))
            u.mem_write(self.r(1), struct.pack('<Q', self.return_handle))
            u.mem_write(self.r(2), struct.pack('<Q', self.return_info))
            for i in range(1, 19): self.reg(i, 0xBEE000+i)
            self.reg(0, self.lookup_ok)
        elif address == 0x4085AA7C:
            self.releases.append(self.r(0))
            for i in range(19): self.reg(i, 0xDEE000+i)
        elif address in (0x4078E154, 0x4078E1E0):
            self.leaves.append(address)
            for i in range(8, 12): self.reg(i, 0xCEE000+i)
            self.reg(0, self.stock_class)
        else: return
        u.reg_write(self.A.UC_ARM64_REG_PC, self.r(30))

    def call(self, entry, old=False):
        self.u.reg_write(self.A.UC_ARM64_REG_SP, 0xA06100000)
        self.reg(30, 0x40160000)
        self.u.emu_start((self.old if old else self.meta['entries'])[entry], 0x40160000, count=10000)
        self.assertIn(self.u.reg_read(self.A.UC_ARM64_REG_PC), self.f.stops)

    def test_file_identity_ignores_current_selection_and_quality(self):
        for fields in (dict(), dict(flag=0, size=6, rate=3), dict(file_type=2, kind=0), dict(flag=2)):
            self.f.set_mode(**fields)
            for dims, expected in (((4128, 2752), 2), ((8256, 5504), 1),
                                   ((4128, 2322), 0), ((4140, 2756), 0), ((8256, 2752), 0)):
                for quality in (0, 1, 2, 3):
                    self.file(*dims, quality=quality)
                    self.reg(0, 0x1234); self.call('og4k_playback_file')
                    self.assertEqual(self.r(0), expected)
        self.assertEqual(self.lookups, [0x1234]*len(self.lookups))
        self.assertEqual(self.releases, [self.handle]*len(self.lookups))

    def test_other_codecs_and_failed_file_lookups_release_correctly(self):
        for kind in (0, 1, 2, 5, 7):
            self.file(kind=kind); self.reg(0, 0x1234); self.call('og4k_playback_file')
            self.assertEqual(self.r(0), 0)
        for ok, info, handle in ((0, self.info, self.handle), (1, 0, self.handle), (0, 0, 0)):
            self.lookup_ok, self.return_info, self.return_handle = ok, info, handle
            count = len(self.releases)
            self.reg(0, 0x1234); self.call('og4k_playback_file'); self.assertEqual(self.r(0), 0)
            self.assertEqual(len(self.releases)-count, int(bool(handle)))

    def test_native_file_api_clobbers_do_not_escape_classifier(self):
        preserved = list(range(1, 8))+list(range(12, 30))
        before = [self.r(i) for i in preserved]
        self.reg(0, 0x1234); self.call('og4k_playback_file')
        self.assertEqual(self.r(0), 2)
        self.assertEqual([self.r(i) for i in preserved], before)
        self.assertEqual(self.r(30), 0x40160000)
        self.assertEqual(self.u.reg_read(self.A.UC_ARM64_REG_SP), 0xA06100000)

    def test_both_composer_classes_change_only_native_class_one(self):
        for entry, native in (('og4k_aspect_class_hook', 0x4078E154),
                              ('og4k_aspect_class_thumb_hook', 0x4078E1E0)):
            for stock in (0, 1, 2, 3):
                self.stock_class = stock; before = len(self.lookups)
                self.reg(0, self.image); self.call(entry)
                self.assertEqual(self.r(0), 0 if stock == 1 else stock)
                self.assertEqual(self.leaves[-1], native)
                self.assertEqual(len(self.lookups)-before, int(stock == 1))

    def test_original_eight_k_and_ordinary_class_results_match_d10(self):
        preserved = list(range(1, 8))+list(range(12, 30))
        for dims, kind in (((8256, 5504), 6), ((8256, 4640), 6), ((4128, 2322), 6), ((4128, 2752), 2)):
            self.file(*dims, kind=kind)
            for new, old in (('og4k_aspect_class_hook', 'og_aspect_class_hook'),
                             ('og4k_aspect_class_thumb_hook', 'og_aspect_class_thumb_hook')):
                self.reg(0, self.image); before = [self.r(i) for i in preserved]; self.call(new)
                result = self.r(0); self.assertEqual([self.r(i) for i in preserved], before)
                self.reg(0, self.image); self.call(old, old=True); self.assertEqual(self.r(0), result)

    def preview(self, kind='thumb'):
        self.u.mem_write(self.dest, bytes(0x80)); self.u.mem_write(self.source, bytes(0x80))
        self.f.w32(self.dest+0x34, 8 if kind == 'thumb' else 2)
        self.f.w32(self.dest+0x3c, 1024 | 682 << 16)
        self.f.w32(self.dest+0x30, 65 | 47 << 16 if kind == 'overview' else 54 << 16)
        self.f.w32(self.dest+0x40, {'thumb': 408 | 272 << 16, 'overview': 484 | 272 << 16,
                                  'full': 1024 | 576 << 16}[kind])
        self.u.mem_write(self.dest+0x48, b'\x01'); self.u.mem_write(self.dest+0x4a, b'\x08\x00')
        self.f.w32(self.source, 0x1234)
        raster = 640 | 360 << 16 if kind == 'thumb' else 1920 | 1080 << 16
        for offset in (0x64, 0x68): self.f.w32(self.source+offset, raster)
        self.reg(0, self.dest); self.reg(1, self.source); self.reg(2, 0x123456)

    def test_preview_changes_only_bounded_full_overview_or_crop_fields(self):
        for kind in ('thumb', 'overview', 'full'):
            self.f.set_mode(flag=0, file_type=2); self.preview(kind)
            before = bytes(self.u.mem_read(self.dest, 0x80)); source = bytes(self.u.mem_read(self.source, 0x80))
            expected = bytearray(before)
            if kind == 'thumb': expected[0x48] = 0
            else:
                struct.pack_into('<I', expected, 0x30, 0 if kind == 'full' else 103 | 47 << 16)
                struct.pack_into('<I', expected, 0x40, (1024 | 682 << 16) if kind == 'full' else (408 | 272 << 16))
            self.call('og4k_preview_hook')
            self.assertEqual(bytes(self.u.mem_read(self.dest, 0x80)), bytes(expected))
            self.assertEqual(bytes(self.u.mem_read(self.source, 0x80)), source)
            self.assertEqual((self.r(0), self.r(1), self.r(2)), (self.dest, self.source, 0x123456))
            self.assertEqual(self.u.reg_read(self.A.UC_ARM64_REG_SP), 0xA06100000-0x60)
            self.assertEqual(self.releases, [self.handle]*len(self.lookups))

    def test_rotation_raster_and_thumbnail_boundary_guards(self):
        for address, value in ((self.dest+0x50, 1), (self.dest+0x4a, 9),
                               (self.dest+0x40, 408 | 271 << 16), (self.dest+0x40, 408 | 270 << 16),
                               (self.dest+0x40, 0), (self.source+0x58, 1),
                               (self.source+0x60, 1), (self.source+0x64, 0), (self.source+0x68, 0)):
            self.preview(); self.f.w32(address, value)
            before = bytes(self.u.mem_read(self.dest, 0x80)); self.call('og4k_preview_hook')
            # 408x271 has ratio error3, beyond the reviewed +/-2 tolerance.
            self.assertEqual(bytes(self.u.mem_read(self.dest, 0x80)), before)

    def test_eight_k_preview_fallback_matches_original_for_all_three_routes(self):
        self.file(8256, 5504)
        for kind in ('thumb', 'overview', 'full'):
            self.preview(kind); self.call('og4k_preview_hook'); new = bytes(self.u.mem_read(self.dest, 0x80))
            self.preview(kind); self.call('preview_full_page_hook', old=True)
            self.assertEqual(bytes(self.u.mem_read(self.dest, 0x80)), new)

    def capture(self, width=4128, height=2752, kind=0x31, media=0x1234):
        self.u.mem_write(self.request, bytes(0x250))
        for offset, value in ((0, width), (4, height), (0x23c, kind), (0x240, 0x7654)):
            self.f.w32(self.request+offset, value)
        self.f.w32(0xA06100000, media)
        self.reg(19, 0xA045F08F8); self.reg(23, self.request)

    def proxy(self):
        self.capture(1920, 1080, 2)
        self.u.mem_write(0xA0456A820, bytes(0x110))
        for offset, value in ((0xa0, 2), (0xa4, 1920), (0xa6, 1080), (0xfa, 1),
                              (0xfc, 0x31), (0x102, 4128), (0x104, 2752)):
            self.u.mem_write(0xA0456A820+offset, struct.pack('<H', value))

    def test_moving_capture_uses_request_geometry_without_shooting_selection(self):
        for fields in (dict(), dict(flag=0, size=6, file_type=2)):
            self.f.set_mode(**fields)
            for width, height in ((4128, 2752), (4140, 2756), (8256, 5504), (8268, 5512)):
                self.capture(width, height); self.call('og4k_playback_capture_hook')
                self.assertEqual(self.tag(), 0x100001234)
                self.assertEqual(self.r(8), 0x7654)
                self.assertEqual(self.u.reg_read(self.A.UC_ARM64_REG_SP), 0xA06100000)

    def test_next_ordinary_clip_or_missing_media_id_clears_stale_tag(self):
        for values in (dict(width=4128, height=2322), dict(kind=2), dict(media=0),
                       dict(width=4140, height=2752), dict(width=4128, height=2756)):
            self.capture(); self.call('og4k_playback_capture_hook'); self.assertNotEqual(self.tag(), 0)
            self.capture(**values); self.call('og4k_playback_capture_hook'); self.assertEqual(self.tag(), 0)

    def test_proxy_requires_every_original_association_guard(self):
        self.proxy(); self.call('og4k_playback_capture_hook'); self.assertEqual(self.tag(), 0x100001234)
        for offset in (0xa0, 0xa4, 0xa6, 0xfa, 0xfc, 0x102, 0x104):
            self.proxy(); self.u.mem_write(0xA0456A820+offset, b'\x00\x00')
            self.call('og4k_playback_capture_hook'); self.assertEqual(self.tag(), 0)
        self.proxy(); self.u.mem_write(0xA0456A820+0x102, struct.pack('<HH', 8256, 5504))
        self.call('og4k_playback_capture_hook'); self.assertEqual(self.tag(), 0x100001234)

    def test_existing_fit_requires_media_id_and_native_enable(self):
        self.capture(); self.call('og4k_playback_capture_hook')
        for media, enabled, expected in ((0x1234, 1, (3, 2, 1)), (0x9876, 1, (20, 21, 22)),
                                         (0x1234, 0, (20, 21, 22))):
            self.f.w32(0xA045F07D8, media); self.u.mem_write(0xA045F07EC, bytes([enabled]))
            for i in range(3): self.reg(i, 20+i)
            self.call('playback_fit_hook', old=True)
            self.assertEqual(tuple(self.r(i) for i in range(3)), expected)


REAL_INPUTS = all(os.environ.get(n) for n in ('OG4K_COMPILER', 'OG4K_ORIGINAL', 'OG4K_BASELINE'))
@unittest.skipUnless(REAL_INPUTS, 'Set original/baseline for complete-input integration')
class PlaybackOverlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from verify import decode
        from z8opengate4k.playback import make_playback_main
        original = Path(os.environ['OG4K_ORIGINAL']).read_bytes()
        baseline = Path(os.environ['OG4K_BASELINE']).read_bytes()
        cls.baseline = decode(baseline)[581844:82389553]
        cls.new, cls.report = make_playback_main(original, baseline, os.environ['OG4K_COMPILER'])

    def test_combined_build_preserves_d10_recorder_and_all_undeclared_bytes(self):
        b = 0x40160000; end = 0
        for start, stop in sorted((int(w['address'], 16)-b, int(w['address'], 16)-b+w['bytes'])
                                  for w in self.report['writes']):
            self.assertGreaterEqual(start, end)
            self.assertEqual(self.new[end:start], self.baseline[end:start]); end = stop
        self.assertEqual(self.new[end:], self.baseline[end:])
        self.assertEqual(self.new[0x40960000-b:0x40960000-b+11568], self.baseline[0x40960000-b:0x40960000-b+11568])
        self.assertEqual(self.report['recorder_main_sha256'], '9bfa80f4270dc789924a3f717134f35b3adaefb66a881a71808dd361aa71b5b1')
        self.assertEqual(len(self.new), 81807709)

    def test_all_four_playback_sites_point_to_profiled_entries(self):
        from z8patch.image import branch
        for address, (name, _) in SITES.items():
            self.assertEqual(self.new[address-0x40160000:address-0x40160000+4],
                             branch(address, self.report['playback']['compiled']['entries'][name], False))

    def test_decode_recording_and_lifetime_are_still_unqualified(self):
        self.assertFalse(self.report['flash_package_generated'])
        self.assertFalse(self.report['recording_4k_open_gate_implemented'])
        self.assertFalse(self.report['recorder']['file_callback_lifetime_qualified'])
        for name in ('file_identity_uses_shooting_globals', 'actual_clip_decode_qualified',
                     'full_qemu_playback_qualified', 'proxy_stream_qualified'):
            self.assertFalse(self.report['playback'][name])


if __name__ == '__main__': unittest.main()

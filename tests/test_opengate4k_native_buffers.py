"""Real descriptor-demand checks for the restricted camera-candidate work."""
from hashlib import sha256
import json
from pathlib import Path
import struct
import unittest
from z8opengate4k.native_buffers import NativeBufferProbe, raw_layout, STATE
import test_opengate4k_nrmt_lifetime as nrmt


@unittest.skipUnless(nrmt.REAL_INPUTS, 'Set complete inputs and compiler for native buffer execution')
class NativeBufferExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.image, cls.report, *_ = nrmt.complete_inputs()
    def setUp(self): self.p = NativeBufferProbe(self.image)
    def tearDown(self): self.p.close()

    def test_configuration_and_disable_emit_expected_complete_native_descriptors(self):
        result = self.p.run()
        ordinary, candidate, restored = [result[k] for k in ('before_configuration','after_configuration','after_disable')]
        self.assertEqual(ordinary['raw']['outer'], [4140, 2344])
        self.assertEqual(ordinary['coded'], [4140, 2330])
        self.assertEqual(ordinary['raw']['crop'], [0, 6])
        self.assertEqual(candidate['raw']['outer'], [4140, 2756])
        self.assertEqual(candidate['coded'], [4140, 2756])
        self.assertEqual(candidate['raw']['crop'], [0, 0])
        self.assertEqual(candidate['raw']['stride_bytes'], 7264)
        self.assertEqual(candidate['raw']['minimum_raster_bytes'], 20019584)
        self.assertEqual(ordinary['raw']['minimum_raster_bytes'], 17026816)
        self.assertEqual(result['extra_raw_raster_bytes'], 2992768)
        self.assertEqual(restored, ordinary)

    def test_selection_flag_alone_does_not_install_candidate_geometry(self):
        self.p.word(STATE, 0)
        result = self.p.describe()
        self.assertEqual(result['raw']['outer'], [4140, 2344])
        self.assertEqual(result['coded'], [4140, 2330])

    def test_all_three_low_rate_selections_use_same_native_raw_stride_and_extent(self):
        for rate in (4, 5, 6):
            self.p.select(rate=rate); self.p.configure()
            result = self.p.describe()
            self.assertEqual(result['raw']['outer'], [4140, 2756])
            self.assertEqual(result['raw']['minimum_raster_bytes'], 20019584)
            self.assertEqual(result['raw']['coded'], result['coded'])

    def test_valid_disable_high_rate_and_non_raw_configurations_restore_ordinary_extent(self):
        for fields in (dict(flag=0), dict(rate=3), dict(file_type=2)):
            self.p.select(); self.p.configure()
            self.p.select(**fields); self.p.configure()
            result = self.p.describe()
            self.assertEqual(result['raw']['outer'], [4140, 2344])
            self.assertEqual(result['coded'], [4140, 2330])

    def test_invalid_snapshot_does_not_install_geometry_or_clear_an_existing_valid_installation(self):
        self.p.word(STATE, 0); self.p.configure(valid=False)
        self.assertEqual(self.p.describe()['raw']['outer'], [4140, 2344])
        self.p.configure(); self.p.configure(valid=False)
        self.assertEqual(self.p.describe()['raw']['outer'], [4140, 2756])

    def test_switch_from_four_k_to_legacy_eight_k_matches_fresh_eight_k_descriptors(self):
        self.p.configure()
        self.p.select(size=6, actual=4); self.p.configure(); after = self.p.describe()
        fresh = NativeBufferProbe(self.image)
        try:
            fresh.select(size=6, actual=4); fresh.configure()
            self.assertEqual(after, fresh.describe())
        finally: fresh.close()
        self.p.select(flag=0); self.p.configure()
        self.assertEqual(self.p.describe()['raw']['outer'], [4140, 2344])


class NativeBufferInputChecks(unittest.TestCase):
    def test_unreviewed_main_is_refused_before_execution(self):
        with self.assertRaises(ValueError): NativeBufferProbe(bytes(64))

    def test_raw_descriptor_rejects_inconsistent_stride_and_out_of_bounds_coded_height(self):
        original = bytes.fromhex('0500000000000000601c2c10c40a2c10c40a000000000000')
        for offset, value in ((8, 7245), (0x10, 2757), (0x12, 1), (0x14, 1)):
            data = bytearray(original); struct.pack_into('<H', data, offset, value)
            with self.assertRaises(ValueError): raw_layout(bytes(data))


@unittest.skipUnless(nrmt.REAL_INPUTS, 'Set complete inputs for native buffer fingerprints')
class NativeBufferWindows(unittest.TestCase):
    def test_native_query_and_static_record_provenance_windows_match_reviewed_baseline(self):
        image, _, _, _, baseline = nrmt.complete_inputs()
        record = json.loads((Path(__file__).resolve().parents[1]/'docs/data/opengate4k-native-buffer-audit.json').read_text())
        self.assertEqual(sha256(image).hexdigest(), record['main_sha256'])
        for window in record['native_windows']:
            start = int(window['address'], 16)-0x40160000; end = start+window['bytes']
            self.assertEqual(image[start:end], baseline[start:end], window['name'])
            self.assertEqual(sha256(image[start:end]).hexdigest(), window['sha256'], window['name'])


if __name__ == '__main__': unittest.main()

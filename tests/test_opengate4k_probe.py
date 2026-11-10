#!/usr/bin/env python3
"""Stock-table corruption and report-only CLI tests; no firmware fixture needed."""
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.inspect_opengate4k import bounded, initial_offset, parse_menu, parse_rate_pairs


def rate_fixture():
    # Synthetic paired table; deliberately put 4K modes at non-leading indexes.
    modes = [(8268, 4652, 30000, 1001, 0)] * 21
    for index, numerator, denominator in ((7, 24000, 1001), (13, 25000, 1000), (19, 30000, 1001)):
        modes[index] = (4140, 2330, numerator, denominator, 0)
    rows = [(*mode, 900000000) for mode in modes] + [(*mode, 450000000) for mode in modes]
    return bytearray(b''.join(struct.pack('<HHIIIQ', *row) for row in rows))


def menu_fixture():
    rows = [(1000 + i, 1, 1, 2, 0, 0) for i in range(80)]
    for index, rate in zip((53, 54, 55), (4, 5, 6)):
        rows[index] = (12531 + index - 53, 6, rate, 6, 0, 0)
    return bytearray(b''.join(struct.pack('<6I', *row) for row in rows))


class RateTableTests(unittest.TestCase):
    def test_preserves_fractional_rates_and_finds_nonleading_modes(self):
        rows = parse_rate_pairs(rate_fixture())
        found = [r for r in rows if r['coded_width'] == 4140]
        self.assertEqual([r['index'] for r in found], [7, 13, 19])
        self.assertEqual(found[0]['denominator'], 1001)
        self.assertAlmostEqual(found[0]['fps'], 23.976023976)

    def test_truncated_and_extra_records_rejected(self):
        raw = rate_fixture()
        for damaged in (raw[:-1], raw + b'\0'):
            with self.assertRaisesRegex(ValueError, 'length'):
                parse_rate_pairs(damaged)

    def test_mismatched_pair_geometry_rejected(self):
        raw = rate_fixture()
        struct.pack_into('<H', raw, 21 * 24 + 2, 2752)
        with self.assertRaisesRegex(ValueError, 'identity'):
            parse_rate_pairs(raw)

    def test_zero_denominator_rejected(self):
        raw = rate_fixture()
        for index in (0, 21):
            struct.pack_into('<I', raw, index * 24 + 8, 0)
        with self.assertRaisesRegex(ValueError, 'frame rate'):
            parse_rate_pairs(raw)

    def test_zero_budget_is_not_a_new_supported_mode(self):
        raw = rate_fixture()
        for index in (7, 28):
            struct.pack_into('<Q', raw, index * 24 + 16, 0)
        self.assertFalse(parse_rate_pairs(raw)[7]['stock_supported'])
        struct.pack_into('<Q', raw, 7 * 24 + 16, 1)
        with self.assertRaisesRegex(ValueError, 'Half-empty'):
            parse_rate_pairs(raw)


class MenuAndBoundsTests(unittest.TestCase):
    def test_filters_file_type_and_checks_existing_templates(self):
        rows = parse_menu(menu_fixture())
        self.assertEqual([r['rate_code'] for r in rows], [4, 5, 6])
        raw = menu_fixture()
        struct.pack_into('<I', raw, 53 * 24 + 4, 7)
        with self.assertRaisesRegex(ValueError, 'template'):
            parse_menu(raw)

    def test_rejects_short_menu(self):
        with self.assertRaisesRegex(ValueError, 'length'):
            parse_menu(menu_fixture()[:-24])

    def test_reads_cannot_wrap_or_run_past_image(self):
        for offset, length in ((-1, 1), (0, -1), (3, 2)):
            with self.assertRaises(ValueError):
                bounded(b'abcd', offset, length)
        self.assertEqual(bounded(b'abcd', 2, 2), b'cd')

    def test_initialized_ram_translation_rejects_runtime_addresses(self):
        self.assertEqual(initial_offset(0xA02808000), 0x4B13000)
        with self.assertRaisesRegex(ValueError, 'initialized RAM'):
            initial_offset(0xA03D5C02B)


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-B', '-O', str(ROOT / 'tools/inspect_opengate4k.py'), *map(str, args)],
                              capture_output=True, text=True, encoding='utf-8')

    def test_source_report_and_exclusive_output(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / 'research.json'
            result = self.run_cli('--source-only', '--output', report)
            self.assertEqual(result.returncode, 0, result.stderr)
            raw = report.read_bytes()
            data = json.loads(raw)
            self.assertFalse(data['firmware_generated'])
            self.assertFalse(data['recording_4k_open_gate_implemented'])
            self.assertEqual(data['target']['active_width'] * 2, data['target']['active_height'] * 3)
            self.assertNotEqual(self.run_cli('--source-only', '--output', report).returncode, 0)
            self.assertEqual(report.read_bytes(), raw)
            self.assertEqual([p.name for p in Path(folder).iterdir()], ['research.json'])

    def test_wrong_input_produces_no_output_even_under_optimized_python(self):
        with tempfile.TemporaryDirectory() as folder:
            firmware = Path(folder) / 'wrong.bin'
            firmware.write_bytes(b'not firmware')
            output = Path(folder) / 'uncreated' / 'report.json'
            self.assertNotEqual(self.run_cli(firmware, '--output', output).returncode, 0)
            self.assertFalse(output.parent.exists())
            self.assertEqual(firmware.read_bytes(), b'not firmware')

    def test_source_and_firmware_modes_cannot_be_combined(self):
        self.assertNotEqual(self.run_cli('some.bin', '--source-only').returncode, 0)
        self.assertNotEqual(self.run_cli().returncode, 0)

    def test_never_accepts_a_firmware_output_name(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'candidate.bin'
            self.assertNotEqual(self.run_cli('--source-only', '--output', output).returncode, 0)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()

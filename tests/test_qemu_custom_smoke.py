import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    'custom_smoke', Path(__file__).resolve().parents[1] / 'tools/qemu_custom_smoke.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.result = dict(
            checks=[dict(passed=True)], error=None, owned_qemu_stopped=True,
            navigation_inputs=[{}] * 6,
            pipeline_samples=[dict(phase=7, virtual_seconds=42,
                                   raw=dict(frames=120), lcd=dict(frames=200))])

    def test_complete_navigation_passes_with_narrow_scope(self):
        row = smoke.smoke_summary(self.result, '')
        self.assertEqual(row['status'], 'PASS')
        self.assertFalse(row['recording_tested'])
        self.assertFalse(row['open_gate_4k_implemented'])
        self.assertFalse(row['physical_camera_tested'])

    def test_successful_assertions_cannot_hide_incomplete_walk(self):
        for key, value in [('navigation_inputs', [{}] * 5), ('pipeline_samples', [])]:
            candidate = copy.deepcopy(self.result)
            candidate[key] = value
            self.assertEqual(smoke.smoke_summary(candidate, '')['status'], 'FAIL')

    def test_real_frames_and_final_settling_required(self):
        for category in ('raw', 'lcd'):
            candidate = copy.deepcopy(self.result)
            candidate['pipeline_samples'][0][category]['frames'] = 0
            self.assertEqual(smoke.smoke_summary(candidate, '')['status'], 'FAIL')
        candidate = copy.deepcopy(self.result)
        candidate['pipeline_samples'][0]['phase'] = 6
        self.assertEqual(smoke.smoke_summary(candidate, '')['status'], 'FAIL')

    def test_faults_and_orphan_process_fail(self):
        for key, value in [('error', 'failure'), ('owned_qemu_stopped', False),
                           ('checks', []), ('checks', [dict(passed=False)])]:
            candidate = copy.deepcopy(self.result)
            candidate[key] = value
            self.assertEqual(smoke.smoke_summary(candidate, '')['status'], 'FAIL')
        self.assertEqual(smoke.smoke_summary(self.result, 'Z8_UNKNOWN')['status'], 'FAIL')


if __name__ == '__main__':
    unittest.main()

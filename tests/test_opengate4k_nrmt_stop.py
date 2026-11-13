"""Native session configuration and retained-tail completion controls.

The request/attributes, start acknowledgement, ticks and storage completion
are fixtures. Native config construction, parameter generation, last-item
repetition, triple batching, quotas and writer tasks execute. No TICO/file I/O.
"""
from hashlib import sha256
import json
import math
from pathlib import Path
import struct
import unittest
import test_opengate4k_nrmt_pipeline as pipeline

queue = pipeline.queue


class NativeSessionHarness(pipeline.NativeCaptureHarness):
    def __init__(self, image, report):
        self.configuration_waits = []
        super().__init__(image, report)
        self.request = 0xA06070000; self.attributes = 0xA06071000
        self.storage_info = 0xA06072000; self.name_info = 0xA06073000
        self.name = 0xA06074000
        self.u.mem_write(self.request, bytes(0x40))
        self.u.mem_write(self.attributes, bytes(0x100))
        self.u.mem_write(self.storage_info, bytes(0x50))
        self.u.mem_write(self.name_info, bytes(0x10))
        self.u.mem_write(self.name, b'OG4K-SESSION\0'+bytes(32))
        self.qwrite(self.request+8, self.attributes)
        self.qwrite(self.request+0x18, self.storage_info)
        self.qwrite(self.request+0x30, self.name_info)
        self.qwrite(self.name_info+8, self.name)
        self.qwrite(self.storage_info+0x10, 0x10000000)
        self.word(self.storage_info+0x18, 512)
        # File/session template is supplied, not opened by the filesystem.
        self.u.mem_write(0xA04614660, bytes(0x30))
        self.configure()

    def observe(self, u, address, size, data):
        if (0x40727A18 <= address < 0x40727C7C or
                0x40D1CFF4 <= address < 0x40D1D06C or
                0x40D1FF60 <= address < 0x40D1FFA0 or
                0x40D228A8 <= address < 0x40D228E8 or
                address == 0x40D1D4F0): return
        if address == 0x40D2BD04:
            # Config transfer/start acknowledgement only; this fixture never
            # acknowledges a stop, drain, physical write or close.
            args = tuple(self.reg(i) for i in range(3))
            if args != (0xA04614648, 1, 0): raise AssertionError('Unexpected session wait')
            self.configuration_waits.append(args); self.reg(0, 1)
            u.reg_write(self.A.UC_ARM64_REG_PC, self.reg(30)); return
        return super().observe(u, address, size, data)

    def configure(self, request_kind=1, file_type=6, size=4, rate=4):
        self.word(self.request, request_kind)
        for offset, value in ((4, size), (8, rate), (0x20, file_type)):
            self.word(self.attributes+offset, value)
        self.call(0x40727A18, self.request)
        data = bytes(self.u.mem_read(0xA031C13C8, 0x90))
        self.call(0x40D1FF60, 0xA031C13C8)
        self.call(0x40D228A8, 0xA031C13C8)
        return data

    def record_state(self): return struct.unpack('<I', self.u.mem_read(0xA031C1818, 4))[0]

    def stop(self, max_ticks=40):
        # Event bit1 is the native stop request; bit4 is a controlled tick.
        self.call(0x40D1EA48, 1 << 1)
        trace = []
        for i in range(max_ticks):
            self.call(0x40D1EA48, 1 << 4); self.write_ready()
            trace.append(dict(tick=i+1, state=self.record_state(),
                              input=[self.count(lane=j) for j in range(2)],
                              metadata=self.count(queue.METADATA),
                              stored_groups=len(self.storage_batches)))
            if self.record_state() == 2: return trace
        return trace

    def complete_storage(self, count=3):
        self.call(0x40CA1B34, 1, count)
        self.call(0x40D20FD8, 1 << 9)


@unittest.skipUnless(queue.nrmt.REAL_INPUTS, 'Set complete inputs and compiler for native session/stop execution')
class NativeSessionStopExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.image, cls.report, *_ = queue.nrmt.complete_inputs()
    def setUp(self): self.h = NativeSessionHarness(self.image, self.report)
    def tearDown(self): self.h.close()

    def assert_contents(self, packets, expected_chunks=None):
        chunks = [chunk for batch in self.h.storage_batches for chunk in batch['chunks']]
        self.assertEqual(len(chunks), math.ceil(len(packets)/3)*3 if expected_chunks is None else expected_chunks)
        for i, chunk in enumerate(chunks):
            packet = packets[min(i, len(packets)-1)]
            self.assertEqual(chunk[4:1024], packet['packet'][4:])
            self.assertEqual(chunk[1024:], packet['payload'])
        self.assertEqual(self.h.errors, [])
        return chunks

    def test_native_builder_maps_nraw_attributes_to_internal_mode_two(self):
        for file_type, mode in ((6, 2), (5, 1), (4, 0), (2, 0)):
            data = self.h.configure(file_type=file_type)
            self.assertEqual(struct.unpack_from('<I', data, 0x6C)[0], mode)
            self.assertEqual(struct.unpack_from('<I', data, 0x80)[0], int(file_type == 6))
            self.assertEqual(data, bytes(self.h.u.mem_read(queue.CONFIG, 0x90)))
            self.assertEqual(data, bytes(self.h.u.mem_read(0xA031C3138, 0x90)))

    def test_native_request_kind_selects_tail_retention_before_production(self):
        for kind, retain in ((0, 0), (1, 1), (2, 1), (3, 0)):
            data = self.h.configure(request_kind=kind)
            self.assertEqual(struct.unpack_from('<I', data, 0x58)[0], retain)
            self.assertEqual(struct.unpack_from('<I', data, 0x64)[0], 4)
        self.assertEqual(bytes(self.h.u.mem_read(0xA031C1458, 13)), b'OG4K-SESSION\0')
        self.assertTrue(self.h.configuration_waits)

    def test_retained_session_keeps_last_input_available_for_stop_padding(self):
        for _ in range(9): self.h.produce()
        self.h.worker(); self.h.write_ready()
        self.assertEqual([self.h.count(lane=i) for i in range(2)], [1, 5])
        self.assertEqual(self.h.count(queue.METADATA), 5)
        self.assertEqual(self.h.count(), 1)

    def test_native_stop_delivers_nine_supplied_inputs_before_reaching_state_two(self):
        packets = [self.h.produce() for _ in range(9)]
        self.h.worker(); self.h.write_ready()
        ring = bytes(self.h.u.mem_read(queue.nrmt.RING['index'], 4))
        trace = self.h.stop()
        self.assertEqual(trace[-1]['state'], 2)
        self.assertLess(len(trace), 40)
        self.assert_contents(packets)
        self.assertEqual(struct.unpack('<4I', self.h.u.mem_read(0xA02F204A8, 16)), (2, 9, 1, 9))
        self.assertEqual(bytes(self.h.u.mem_read(queue.nrmt.RING['index'], 4)), ring)
        # Remaining task/metadata descriptors are repeated tail padding. They
        # have not been cleared and no physical file close is claimed.
        self.assertGreater(self.h.count()+self.h.count(lane=1), 0)

    def test_native_stop_respects_latched_target_and_repeats_last_for_partial_groups(self):
        for count, target, chunks in ((1, 1, 3), (2, 1, 3), (4, 3, 3), (8, 7, 9), (10, 9, 9)):
            with self.subTest(count=count):
                h = NativeSessionHarness(self.image, self.report)
                previous, self.h = self.h, h
                try:
                    packets = [h.produce() for _ in range(count)]
                    h.worker(); h.write_ready(); trace = h.stop()
                    self.assertEqual(trace[-1]['state'], 2)
                    self.assertEqual(struct.unpack('<I', h.u.mem_read(0xA031C18C8+0x1C, 4))[0], target)
                    self.assert_contents(packets, chunks)
                    # The native target excludes the retained item here. Its
                    # relation to actual capture indices/file duration is not
                    # qualified; do not label this a lost camera frame.
                finally:
                    h.close(); self.h = previous

    def test_stop_after_menu_change_preserves_locked_geometry_and_payload(self):
        packets = [self.h.produce() for _ in range(9)]
        self.h.worker(); self.h.write_ready()
        self.h.selection(flag=0, file_type=2, size=6, rate=3)
        self.assertEqual(self.h.stop()[-1]['state'], 2)
        for chunk in self.assert_contents(packets):
            self.assertEqual(int.from_bytes(chunk[69:74], 'big'), 2756)

    def test_late_retention_cannot_recover_an_already_dispatched_last_input(self):
        self.h.configure(request_kind=0)
        for _ in range(9): self.h.produce()
        self.h.worker(); self.h.write_ready()
        self.h.configure(request_kind=1)
        trace = self.h.stop(max_ticks=12)
        self.assertEqual(trace[-1]['state'], 1)
        self.assertEqual([self.h.count(lane=i) for i in range(2)], [0, 6])
        self.assertEqual(len(self.h.storage_batches), 1)

    def test_raw_output_and_writer_task_stay_pending_until_storage_acknowledgement(self):
        for _ in range(9): self.h.produce()
        self.h.worker()
        self.h.call(0x40D1EA48, 1 << 6)
        self.h.call(0x40D20FD8, 1 << 8)
        self.assertEqual(self.h.count(queue.RAW_OUTPUT, 1), 1)
        self.assertEqual(self.h.count(0xA031C3098, 1), 1)
        self.h.complete_storage()
        self.assertEqual(self.h.count(queue.RAW_OUTPUT, 1), 0)
        self.assertEqual(self.h.count(0xA031C3098, 1), 0)

    def test_cleanup_clears_residual_padding_after_nine_inputs_have_been_delivered(self):
        packets = [self.h.produce() for _ in range(9)]
        self.h.worker(); self.h.write_ready(); self.assertEqual(self.h.stop()[-1]['state'], 2)
        self.assert_contents(packets)
        # Completion notification is supplied; this is native task cleanup,
        # not proof of sensor/TICO stop or physical file close.
        self.h.call(0x40D1EA48, 1 << 7)
        self.assertEqual(self.h.record_state(), 3)
        self.h.call(0x40D1EA48, 1 << 2)
        self.assertEqual(self.h.record_state(), 0)
        for address, lanes in ((queue.TASKS, 2), (queue.RAW_OUTPUT, 2), (queue.METADATA, 1)):
            for lane in range(lanes): self.assertEqual(self.h.count(address, lane), 0)
        self.assert_contents(packets)

    def test_ordinary_four_k_and_legacy_eight_k_keep_native_stop_route(self):
        for fields, height in ((dict(flag=0), 2330), (dict(size=6, actual=4), 5512)):
            with self.subTest(fields=fields):
                h = NativeSessionHarness(self.image, self.report)
                previous, self.h = self.h, h
                try:
                    h.configure(size=fields.get('size', 4))
                    packets = [h.produce(**fields) for _ in range(9)]
                    h.worker(); h.write_ready(); self.assertEqual(h.stop()[-1]['state'], 2)
                    for chunk in self.assert_contents(packets):
                        self.assertEqual(int.from_bytes(chunk[69:74], 'big'), height)
                finally:
                    h.close(); self.h = previous


@unittest.skipUnless(queue.nrmt.REAL_INPUTS, 'Set complete inputs for native session/stop fingerprints')
class NativeSessionStopWindows(unittest.TestCase):
    def test_config_builder_transfer_and_tail_completion_windows_match_baseline(self):
        image, _, _, _, baseline = queue.nrmt.complete_inputs()
        record = json.loads((Path(__file__).resolve().parents[1]/'docs/data/opengate4k-nrmt-session-stop.json').read_text())
        self.assertEqual(sha256(image).hexdigest(), record['main_sha256'])
        for window in record['native_windows']:
            start = int(window['address'], 16)-0x40160000; end = start+window['bytes']
            self.assertEqual(image[start:end], baseline[start:end], window['name'])
            self.assertEqual(sha256(image[start:end]).hexdigest(), window['sha256'], window['name'])


if __name__ == '__main__': unittest.main()

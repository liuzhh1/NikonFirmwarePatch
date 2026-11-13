"""Original capture producer -> native mode-2 batching -> writer staging.

No synthetic codec-completion descriptor is enqueued. Payload buffers,
session/configuration, timing/stop acknowledgements and storage are fixtures;
this is not a sensor, TICO, RTOS or physical file-close test.
"""
from hashlib import sha256
import json
from pathlib import Path
import struct
import unittest
import test_opengate4k_nrmt_queue as queue


class NativeCaptureHarness(queue.NativeWriterHarness):
    def __init__(self, image, report):
        self.produced = 0; self.last_packet = None; self.timing_limit = 60000
        self.control_calls = []
        super().__init__(image, report)
        self.capture = 0xA06060000; self.context = 0xA06061000
        self.buffer_info = 0xA06065000; self.buffer_head = 0xA06065100
        self.u.mem_write(self.capture, bytes(0x30))
        self.u.mem_write(self.context, bytes(0xA00))
        self.u.mem_write(self.context+0x20, b'\1')
        self.qwrite(self.capture+0x10, self.context)
        self.qwrite(self.context+0x9E0, self.source)
        self.qwrite(self.context+0xE0, self.buffer_info)
        self.qwrite(self.buffer_info+8, self.buffer_head)
        self.u.mem_write(0xA03B71784, b'\0')
        self.call(0x40D1F9F4)
        self.call(0x40CA1AC8)
        self.call(0x40CA1AD0, 0); self.call(0x40CA1AD0, 1)
        self.word(0xA031C1818, 1)
        self.word(queue.CONFIG+0x6C, 2)
        self.word(queue.CONFIG+0x64, 4)

    def observe(self, u, address, size, data):
        if (0x40E99CDC <= address < 0x40E99E90 or
                0x40D2042C <= address < 0x40D20E24 or
                0x40D1F9F4 <= address < 0x40D1FA58 or
                0x40D1FE28 <= address < 0x40D1FF18 or
                0x40D22878 <= address < 0x40D22890 or
                0x40CA1AC8 <= address < 0x40CA1B38 or
                0x40CA3464 <= address < 0x40CA3870 or
                address == 0x40D1D504): return
        if address == 0x40CA1A14:
            count = struct.unpack('<i', struct.pack('<I', self.reg(0) & 0xFFFFFFFF))[0]
            if not -4 <= count <= 10000: raise AssertionError('Unbounded timing fixture')
            self.word(self.reg(2), max(count, 0)*33); self.reg(0, 1)
        elif address == 0x40D20EA0: self.reg(0, self.timing_limit)
        elif address in (0x40CA1A6C, 0x40D2D654, 0x40CB46B8):
            self.control_calls.append((address, self.reg(0)))
            self.reg(0, 0)
        else: return super().observe(u, address, size, data)
        u.reg_write(self.A.UC_ARM64_REG_PC, self.reg(30))

    def produce(self, duplicates=0, flag=1, size=4, rate=4, actual=8, payload_bytes=512):
        self.prepare(flag=flag, size=size, rate=rate, actual=actual)
        if not 0 <= duplicates < 60: raise AssertionError('Unbounded capture duplication')
        if not 512 <= payload_bytes <= 4096 or payload_bytes % 512:
            raise AssertionError('Unbounded/unaligned synthetic payload')
        self.u.mem_write(self.source+0x3B9, bytes([duplicates+1]))
        pointer = 0xA06B00000+(self.produced % 60)*0x2000
        payload = bytes([0x80+(self.produced % 64)])*payload_bytes
        self.u.mem_write(pointer, bytes(1024)+payload)
        self.qwrite(self.buffer_head, pointer)
        self.qwrite(self.buffer_info+0x40, pointer+1024)
        self.word(0xA03B83468, len(payload))
        self.call(0x40E99CDC, self.capture)
        self.produced += 1
        # The caller's 0x38-byte output descriptor lives in its original stack.
        descriptor = bytes(self.u.mem_read(queue.nrmt.SP-0xD0+0x70, 0x38))
        packet_pointer = struct.unpack_from('<Q', descriptor, 0x18)[0]
        packet_bytes = struct.unpack_from('<I', descriptor, 0x20)[0]
        packet = bytes(self.u.mem_read(packet_pointer, packet_bytes)) if packet_pointer else b''
        self.last_packet = dict(descriptor=descriptor, pointer=packet_pointer,
                                packet=packet, output_pointer=pointer, payload=payload)
        return self.last_packet

    def worker(self, stop=False):
        self.call(0x40D2042C, int(stop), self.scratch+0x100)
        return bytes(self.u.mem_read(self.scratch+0x100, 1))[0]

    def write_ready(self):
        self.u.mem_write(queue.CONFIG+0x38, struct.pack('<Q', 0x10000000))
        self.call(0x40D1EA48, 1 << 6)
        if self.count(0xA031C3098):
            self.call(0x40D20FD8, 1 << 8)
            # Bounded storage-completion fixture acknowledges three submitted
            # chunks through the original software counter, then its task event.
            if self.storage_result == 0: self.call(0x40CA1B34, 1, 3)
            self.call(0x40D20FD8, 1 << 9)


@unittest.skipUnless(queue.nrmt.REAL_INPUTS, 'Set complete inputs and compiler for native producer pipeline')
class NativeCapturePipelineExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.image, cls.report, *_ = queue.nrmt.complete_inputs()
    def setUp(self): self.h = NativeCaptureHarness(self.image, self.report)
    def tearDown(self): self.h.close()

    def test_native_capture_caller_generates_and_submits_real_parameter_descriptor(self):
        packet = self.h.produce(); block = self.h.peek()
        self.assertEqual(self.h.count(), 1)
        self.assertEqual(block[0x68:0xA0], packet['descriptor'])
        self.assertEqual(struct.unpack_from('<Q', block, 0x48)[0], packet['output_pointer'])
        self.assertEqual(struct.unpack_from('<I', block, 0x50)[0], len(packet['packet']))
        self.assertEqual(struct.unpack_from('<I', block, 0x60)[0], len(packet['payload']))
        self.assertEqual(int.from_bytes(packet['packet'][69:74], 'big'), 2756)

    def test_original_initialization_registers_native_input_and_writer_callbacks(self):
        self.assertIn((0x40CB46B8, 0x40D1FBD4), self.h.control_calls)
        self.assertEqual(self.h.qread(0xA031C3128), 0x40D1FE28)
        self.assertEqual(struct.unpack('<4I', self.h.u.mem_read(0xA02F204A8, 16)), (1, 0, 1, 0))

    def test_capture_busy_inactive_and_stop_gates_do_not_generate_or_enqueue(self):
        ring_before = bytes(self.h.u.mem_read(queue.nrmt.RING['index'], 4))
        for address, value in ((self.h.capture+4, 1), (self.h.context+0x20, 0), (0xA03B71784, 1)):
            old = bytes(self.h.u.mem_read(address, 1)); self.h.u.mem_write(address, bytes([value]))
            packet = self.h.produce()
            self.assertEqual(packet['packet'], b'')
            self.assertEqual(self.h.count(), 0)
            self.assertEqual(bytes(self.h.u.mem_read(queue.nrmt.RING['index'], 4)), ring_before)
            self.h.u.mem_write(address, old)

    def test_native_worker_waits_at_six_and_batches_three_after_seventh_task(self):
        packets = [self.h.produce() for _ in range(6)]
        self.h.worker()
        self.assertEqual((self.h.count(), self.h.count(lane=1), self.h.count(queue.RAW_OUTPUT)), (6, 0, 0))
        packets.append(self.h.produce()); self.h.worker()
        self.assertEqual((self.h.count(), self.h.count(lane=1), self.h.count(queue.RAW_OUTPUT)), (0, 4, 1))
        output = self.h.peek(queue.RAW_OUTPUT)
        self.assertEqual(struct.unpack_from('<3Q', output, 0x18), tuple(p['output_pointer'] for p in packets[:3]))
        self.assertEqual(struct.unpack_from('<3I', output, 8), (1536, 1536, 1536))

    def test_native_batch_reaches_storage_without_injecting_codec_completion(self):
        packets = [self.h.produce() for _ in range(7)]
        self.h.worker(); self.h.selection(flag=0, file_type=2, size=6, rate=3)
        self.h.write_ready()
        self.assertEqual(len(self.h.storage_batches), 1)
        for packet, chunk in zip(packets, self.h.storage_batches[0]['chunks']):
            self.assertEqual(chunk[4:1024], packet['packet'][4:])
            self.assertEqual(chunk[1024:], packet['payload'])
        self.assertEqual(self.h.codec_requests, [])
        self.assertEqual(self.h.count(queue.RAW_OUTPUT, 1), 0)
        self.assertEqual(self.h.errors, [])

    def test_capture_duplicate_byte_expands_tasks_without_regenerating_parameter_packet(self):
        packet = self.h.produce(duplicates=2)
        self.assertEqual(self.h.count(), 3)
        blocks = [self.h.pop() for _ in range(3)]
        self.assertEqual([block[0xA0] for block in blocks], [0, 1, 1])
        self.assertTrue(all(block[0x68:0xA0] == packet['descriptor'] for block in blocks))
        self.assertEqual(struct.unpack('<I', self.h.u.mem_read(queue.nrmt.RING['index'], 4))[0], 1)

    def test_queued_capture_does_not_qualify_buffer_ownership_when_forced_past_capacity(self):
        first = self.h.produce()
        for _ in range(59): self.h.produce()
        rejected = self.h.produce(flag=0)
        self.assertEqual(self.h.count(), 60)
        self.assertEqual(self.h.errors, [(0x3B, 7, 0, 0)])
        self.assertEqual(first['pointer'], rejected['pointer'])
        self.assertNotEqual(first['packet'], rejected['packet'])
        self.assertEqual(struct.unpack_from('<Q', self.h.peek(), 0x80)[0], rejected['pointer'])
        # Calling past capacity deliberately bypasses the real task scheduler
        # and capture-buffer ownership; this is not a stock-firmware defect.

    def test_native_progress_counter_limits_new_output_after_stop_boundary(self):
        for _ in range(7): self.h.produce()
        self.h.worker(); self.h.write_ready()
        self.assertEqual(struct.unpack('<4I', self.h.u.mem_read(0xA02F204A8, 16)), (1, 3, 1, 3))
        self.h.call(0x40CA1AD8, 0)
        self.h.call(0x40CA1AE8, 9)
        self.assertEqual(struct.unpack('<I', self.h.u.mem_read(0xA02F204B8, 4))[0], 9)
        self.assertEqual(self.h.call(0x40CA1B30, 0, 8), 6)
        self.h.call(0x40CA1B34, 0, 6)
        self.assertEqual(self.h.call(0x40CA1B30, 0, 3), 0)
        self.assertEqual(self.h.call(0x40CA1B2C, 0), 1)
        self.assertEqual(self.h.call(0x40CA1B2C, 1), 0)

    def test_stop_request_with_pending_tail_does_not_claim_completion(self):
        for _ in range(9): self.h.produce()
        self.h.worker(); self.h.write_ready()
        self.h.word(queue.CONFIG+0x58, 1); self.h.word(0xA031C2470, 1)
        for _ in range(2): self.h.call(0x40D1EA48, 1 << 4)
        self.assertEqual(struct.unpack('<I', self.h.u.mem_read(0xA031C1818, 4))[0], 1)
        self.assertEqual(self.h.count(lane=1), 6)
        self.assertEqual(self.h.count(queue.METADATA), 6)
        self.assertEqual(len(self.h.storage_batches), 1)

    def test_seventy_native_productions_cross_ring_wrap_with_bounded_pending_work(self):
        packets = []; maximum_pending = 0
        for i in range(70):
            packets.append(self.h.produce(payload_bytes=512+(i % 8)*512))
            maximum_pending = max(maximum_pending, self.h.count()+self.h.count(lane=1))
            self.h.worker(); self.h.write_ready()
        chunks = [chunk for batch in self.h.storage_batches for chunk in batch['chunks']]
        self.assertEqual(len(chunks), 66)
        for packet, chunk in zip(packets, chunks):
            self.assertEqual(chunk[4:1024], packet['packet'][4:])
            self.assertEqual(chunk[1024:], packet['payload'])
            self.assertEqual(int.from_bytes(chunk[:4], 'big'), len(chunk))
        self.assertEqual(packets[0]['pointer'], packets[60]['pointer'])
        self.assertEqual(maximum_pending, 7)
        self.assertEqual(self.h.count()+self.h.count(lane=1), 4)
        self.assertEqual(self.h.count(queue.METADATA), 4)
        self.assertEqual(self.h.count(queue.RAW_OUTPUT)+self.h.count(queue.RAW_OUTPUT, 1), 0)
        self.assertEqual(self.h.errors, [])


@unittest.skipUnless(queue.nrmt.REAL_INPUTS, 'Set complete inputs for native pipeline fingerprints')
class NativeCapturePipelineWindows(unittest.TestCase):
    def test_native_producer_batch_counter_and_registration_windows_are_unchanged(self):
        image, _, _, _, baseline = queue.nrmt.complete_inputs()
        record = json.loads((Path(__file__).resolve().parents[1]/'docs/data/opengate4k-nrmt-capture-pipeline.json').read_text())
        self.assertEqual(sha256(image).hexdigest(), record['main_sha256'])
        for window in record['native_windows']:
            start = int(window['address'], 16)-0x40160000; end = start+window['bytes']
            self.assertEqual(image[start:end], baseline[start:end], window['name'])
            self.assertEqual(sha256(image[start:end]).hexdigest(), window['sha256'], window['name'])


if __name__ == '__main__': unittest.main()

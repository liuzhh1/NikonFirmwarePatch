"""Execute original queue storage and descriptor relay, without an RTOS/codec.

Mutex, heap, timing, codec and writer boundaries are explicit fixtures.
Queue allocation, lists, copies, lane transfer and native consumers execute
from the reviewed MAIN. A queued packet pointer is not packet ownership.
"""
from hashlib import sha256
import json
from pathlib import Path
import struct
import unittest
import test_opengate4k_nrmt_lifetime as nrmt
import test_opengate4k_nrmt_submit as submit

TASKS = 0xA031C1718
OUTPUT = 0xA031C1758
RAW_OUTPUT = 0xA031C1798
METADATA = 0xA031C17D8
CONFIG = 0xA031C1838


class NativeQueueHarness(submit.NativeSubmitHarness):
    def __init__(self, image, report):
        self.heap = 0xA06800000
        self.queue_apis = set(); self.codec_requests = []; self.writer_blocks = []
        super().__init__(image, report)
        self.scratch = 0xA06050000
        # Same lane/capacity/item sizes as original 40D1E9A4..40D1EA24.
        for address, lanes, capacity, size in ((TASKS, 2, 60, 0xA8),
                (OUTPUT, 2, 130, 0x14), (RAW_OUTPUT, 2, 130, 0x88),
                (METADATA, 1, 60, 0x38)):
            self.call(0x40CA1AAC, address, lanes, capacity, size)
            self.call(0x40CA1AB0, address)
        self.u.mem_write(CONFIG, bytes(0x90))
        self.u.mem_write(0xA031C18C8, bytes(0x50))
        self.word(0xA031C1818, 1)

    def observe(self, u, address, size, data):
        if (0x40CA1AAC <= address <= 0x40CA1AC4 or address == 0x40CA1ACC or
                0x40CA2ED0 <= address < 0x40CA3464 or
                0x40CA34D4 <= address < 0x40CA3550 or
                0x40C7A15C <= address < 0x40C7A988 or
                0x40D20770 <= address < 0x40D20CAC or
                0x40D1EA48 <= address < 0x40D1F9F4 or
                0x40D1FA58 <= address < 0x40D1FBD4):
            if 0x40CA1AAC <= address <= 0x40CA1AC4: self.queue_apis.add(address)
            return
        if address == 0x40D2C408:
            count = self.reg(0)
            if not 0 < count <= 0x10000: raise AssertionError('Unbounded native list allocation')
            result = self.heap; self.heap += (count+15) & ~15
            if self.heap > 0xA06900000: raise AssertionError('Fixture heap exhausted')
            u.mem_write(result, bytes(count)); self.reg(0, result)
        elif address in (0x40D2C564, 0x40D2BCC8, 0x40D2BC8C, 0x40CB1034,
                         0x40CA18F0, 0x40CA1940, 0x40CA1B34):
            self.reg(0, 0)
        elif address == 0x40CB46D0:
            self.codec_requests.append(bytes(u.mem_read(self.reg(0), 0x28)))
            self.reg(0, 1)
        elif address == 0x40CA1B30: self.reg(0, 1)
        elif address == 0x40CA1A14:
            self.word(self.reg(2), 0); self.reg(0, 1)
        elif address == 0x40D20EA0: self.reg(0, 0)
        elif address == 0x40D1E898: self.reg(0, 30)
        elif address == 0x40D22AD4:
            self.writer_blocks.append(bytes(u.mem_read(self.reg(0), 0x88)))
            self.reg(0, 1)
        else: return super().observe(u, address, size, data)
        self.submit_apis.add(address)
        u.reg_write(self.A.UC_ARM64_REG_PC, self.reg(30))

    def call(self, entry, *args):
        self.u.reg_write(self.A.UC_ARM64_REG_SP, nrmt.SP)
        for i, value in enumerate(args): self.reg(i, value)
        self.reg(30, nrmt.RETURN)
        saved = [self.reg(i) for i in range(19, 30)]
        self.u.emu_start(entry, 0, count=300000)
        if self.u.reg_read(self.A.UC_ARM64_REG_PC) != nrmt.RETURN:
            raise AssertionError(f'Native queue/consumer did not return: {entry:#x}')
        if self.u.reg_read(self.A.UC_ARM64_REG_SP) != nrmt.SP or saved != [self.reg(i) for i in range(19, 30)]:
            raise AssertionError('Native queue/consumer damaged callee frame')
        return self.reg(0)

    def count(self, address=TASKS, lane=0): return self.call(0x40CA1AC4, address, lane)

    def peek(self, address=TASKS, lane=0):
        if not self.call(0x40CA1AC0, address, lane, self.scratch): return None
        pointer = self.qread(self.scratch)
        size = struct.unpack('<I', self.u.mem_read(address+8, 4))[0]
        return bytes(self.u.mem_read(pointer, size))

    def pop(self, address=TASKS, lane=0):
        if not self.call(0x40CA1AB8, address, lane, self.scratch): return None
        size = struct.unpack('<I', self.u.mem_read(address+8, 4))[0]
        return bytes(self.u.mem_read(self.scratch, size))

    def enqueue(self, address, block, lane=0):
        self.u.mem_write(self.scratch, block)
        return self.call(0x40CA1AB4, address, lane, self.scratch)

    def dispatch(self, mode=2):
        # Internal mode 2 skips the external image-submit API. This is a
        # controlled branch fixture, not proof that a real NRAW session uses it.
        self.word(CONFIG+0x6C, mode)
        return self.call(0x40D20770)


class NativeWriterHarness(NativeQueueHarness):
    """Original writer staging to the storage-submit API, with synthetic payloads."""
    def __init__(self, image, report):
        self.storage_batches = []; self.storage_result = 0
        super().__init__(image, report)
        for address, capacity, size in ((0xA031C3098, 130, 0x88), (0xA031C30D8, 32, 0x10)):
            self.call(0x40CA1AAC, address, 2, capacity, size)
            self.call(0x40CA1AB0, address)
        self.u.mem_write(0xA031C3138, bytes(0x90))
        self.word(0xA031C3138+0x6C, 2)
        self.word(0xA031C3138+0x64, 4)
        self.word(0xA031C3118, 1)
        self.u.mem_write(0xA031C3D40, bytes(0xC8))
        self.word(0xA031C3D40+0x60, 130)

    def observe(self, u, address, size, data):
        if (0x40D20FD8 <= address < 0x40D22444 or
                0x40D22AD4 <= address < 0x40D22F28 or
                0x40D231E0 <= address < 0x40D23374):
            if address == 0x40D22AD4:
                self.writer_blocks.append(bytes(u.mem_read(self.reg(0), 0x88)))
            return
        if address == 0x40D1767C:
            if self.reg(1) != 3: raise AssertionError('Unexpected storage batch size')
            entries = bytes(u.mem_read(self.reg(2), 3*16))
            chunks = []
            for i in range(3):
                pointer, count = struct.unpack_from('<QI', entries, i*16)
                if count > 0x2000: raise AssertionError('Unbounded synthetic storage chunk')
                chunks.append(bytes(u.mem_read(pointer, count)))
            self.storage_batches.append(dict(handle=self.reg(0), entries=entries, chunks=chunks))
            self.reg(0, self.storage_result)
            u.reg_write(self.A.UC_ARM64_REG_PC, self.reg(30)); return
        return super().observe(u, address, size, data)

    def complete_three(self, **selection):
        """Three native metadata jobs plus one synthetic raw completion."""
        packets = []
        for rate in (4, 5, 6):
            self.prepare(rate=rate, **selection); packets.append(self.run()); self.submit()
        self.dispatch(mode=2)
        self.u.mem_write(CONFIG+0x38, struct.pack('<Q', 0x10000000))
        pointers = [0xA06A00000+i*0x2000 for i in range(3)]
        block = bytearray(0x88)
        struct.pack_into('<3I', block, 8, 1536, 1536, 1536)
        struct.pack_into('<3Q', block, 0x18, *pointers)
        for i, pointer in enumerate(pointers): self.u.mem_write(pointer, bytes([0xB0+i])*1536)
        if not self.enqueue(RAW_OUTPUT, bytes(block)): raise AssertionError('Synthetic completion rejected')
        self.call(0x40D1EA48, 1 << 6)
        return packets, pointers


@unittest.skipUnless(nrmt.REAL_INPUTS, 'Set complete inputs and compiler for native queue execution')
class NativeNrmtQueueExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.image, cls.report, *_ = nrmt.complete_inputs()
    def setUp(self):
        self.h = NativeQueueHarness(self.image, self.report)
        self.generated = self.h.run()
    def tearDown(self): self.h.close()

    def test_native_queue_copies_task_and_descriptor_but_retains_original_packet_pointer(self):
        self.h.submit(); block = self.h.peek()
        self.assertEqual(self.h.count(), 1)
        self.assertEqual(block[0x68:0xA0], self.generated['descriptor'])
        self.h.u.mem_write(self.h.output, bytes([0xA5])*0x38)
        self.h.u.mem_write(nrmt.SP-0x400, bytes([0x5A])*0x400)
        self.assertEqual(self.h.peek(), block)
        self.assertEqual(struct.unpack_from('<Q', block, 0x80)[0], self.generated['pointer'])

    def test_native_lane_transfer_retains_slot_until_removal_then_clears_descriptor(self):
        self.h.submit(); block = self.h.peek()
        self.assertEqual(self.h.call(0x40CA1ABC, TASKS, 0, 1), 1)
        self.assertEqual((self.h.count(), self.h.count(lane=1)), (0, 1))
        self.assertEqual(self.h.peek(lane=1), block)
        nodes = self.h.qread(TASKS+0x18); stored = self.h.qread(nodes+8)
        self.assertEqual(self.h.pop(lane=1), block)
        self.assertEqual(bytes(self.h.u.mem_read(nodes, 1)), b'\0')
        self.assertEqual(bytes(self.h.u.mem_read(stored, 0xA8)), bytes(0xA8))
        self.assertEqual(bytes(self.h.u.mem_read(self.generated['pointer'], 1024)), self.generated['packet'])

    def test_native_full_queue_refuses_sixty_first_task_and_reuses_released_slot(self):
        self.h.submit(count=60)
        before = self.h.peek(); self.assertEqual(self.h.count(), 60)
        self.h.submit(); self.assertEqual(self.h.count(), 60)
        self.assertEqual(self.h.errors, [(0x3B, 7, 0, 0)])
        self.assertEqual(self.h.pop(), before)
        self.h.submit(); self.assertEqual(self.h.count(), 60)
        self.assertEqual(self.h.errors, [])

    def test_dispatcher_relays_descriptor_to_metadata_queue_and_task_to_lane_one(self):
        self.h.submit(); self.h.selection(flag=0, file_type=2, size=6, rate=3)
        self.h.dispatch()
        self.assertEqual((self.h.count(), self.h.count(lane=1)), (0, 1))
        self.assertEqual(self.h.peek(METADATA), self.generated['descriptor'])
        self.assertEqual(self.h.codec_requests, [])
        self.assertEqual(self.h.errors, [])
        self.assertEqual(self.h.count(METADATA), 1)

    def test_output_consumer_passes_packet_pointer_and_length_to_writer_boundary(self):
        self.h.submit(); self.h.dispatch(mode=0)
        self.h.u.mem_write(CONFIG+0x38, struct.pack('<Q', 0x10000000))
        # Synthetic codec-completion descriptor, not encoded bytes.
        self.assertEqual(self.h.enqueue(OUTPUT, bytes(0x14)), 1)
        self.h.call(0x40D1EA48, 1 << 6)
        self.assertEqual(len(self.h.codec_requests), 1)
        self.assertEqual(len(self.h.writer_blocks), 1)
        writer = self.h.writer_blocks[0]
        self.assertEqual(struct.unpack_from('<Q', writer, 0x38)[0], self.generated['pointer'])
        self.assertEqual(struct.unpack_from('<I', writer, 0x50)[0], len(self.generated['packet']))
        self.assertEqual(self.h.count(METADATA), 0)
        self.assertEqual(bytes(self.h.u.mem_read(self.generated['pointer'], 1024)), self.generated['packet'])

    def test_native_cleanup_resets_all_queues_without_clearing_packet_or_nrmt_ring(self):
        self.h.submit(); self.h.dispatch()
        ring = bytes(self.h.u.mem_read(nrmt.RING['index'], 4))
        self.h.call(0x40D1FA58)
        for address, lanes in ((TASKS, 2), (OUTPUT, 2), (RAW_OUTPUT, 2), (METADATA, 1)):
            for lane in range(lanes): self.assertEqual(self.h.count(address, lane), 0)
        self.assertEqual(bytes(self.h.u.mem_read(nrmt.RING['index'], 4)), ring)
        self.assertEqual(bytes(self.h.u.mem_read(self.generated['pointer'], 1024)), self.generated['packet'])
        self.assertEqual(self.h.writer_blocks, [])

    def test_raw_mode_output_relays_three_metadata_packets_in_original_order(self):
        packets = [self.generated]; self.h.submit()
        for rate in (5, 6):
            self.h.prepare(rate=rate); packets.append(self.h.run()); self.h.submit()
        self.h.dispatch(mode=2)
        self.assertEqual((self.h.count(lane=1), self.h.count(METADATA)), (3, 3))
        self.h.u.mem_write(CONFIG+0x38, struct.pack('<Q', 0x10000000))
        self.assertEqual(self.h.enqueue(RAW_OUTPUT, bytes(0x88)), 1)
        self.h.call(0x40D1EA48, 1 << 6)
        self.assertEqual(len(self.h.writer_blocks), 1)
        writer = self.h.writer_blocks[0]
        self.assertEqual(struct.unpack_from('<3Q', writer, 0x38), tuple(p['pointer'] for p in packets))
        self.assertEqual(struct.unpack_from('<3I', writer, 0x50), tuple(len(p['packet']) for p in packets))
        self.assertEqual(self.h.count(METADATA), 0)
        self.assertEqual(self.h.codec_requests, [])

    def test_delayed_queue_cannot_protect_packet_from_forced_native_ring_reuse(self):
        self.h.submit(); self.h.dispatch()
        self.h.prepare(flag=0)
        for _ in range(59): self.h.run()
        self.assertEqual(bytes(self.h.u.mem_read(self.generated['pointer'], 1024)), self.generated['packet'])
        wrapped = self.h.run()
        descriptor = self.h.peek(METADATA)
        self.assertEqual(descriptor, self.generated['descriptor'])
        self.assertEqual(wrapped['pointer'], self.generated['pointer'])
        self.assertNotEqual(wrapped['packet'], self.generated['packet'])
        # This deliberately bypasses the caller's scheduling/backpressure;
        # it establishes a lifetime requirement, not a stock-firmware defect.
        self.assertEqual(struct.unpack_from('<Q', descriptor, 0x18)[0], wrapped['pointer'])


@unittest.skipUnless(nrmt.REAL_INPUTS, 'Set complete inputs and compiler for native writer staging')
class NativeNrmtWriterExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.image, cls.report, *_ = nrmt.complete_inputs()
    def setUp(self): self.h = NativeWriterHarness(self.image, self.report)
    def tearDown(self): self.h.close()

    def assert_staged(self, packets, pointers):
        self.assertEqual(len(self.h.storage_batches), 1)
        batch = self.h.storage_batches[0]
        self.assertEqual([len(chunk) for chunk in batch['chunks']], [1536]*3)
        self.assertEqual(struct.unpack_from('<Q', batch['entries'])[0], pointers[0])
        for i, (packet, pointer, chunk) in enumerate(zip(packets, pointers, batch['chunks'])):
            self.assertEqual(struct.unpack_from('<Q', batch['entries'], i*16)[0], pointer)
            # Native writer updates only the top-level size to include payload.
            self.assertEqual(chunk[:4], struct.pack('>I', 1536))
            self.assertEqual(chunk[4:1024], packet['packet'][4:])
            self.assertEqual(chunk[1024:], bytes([0xB0+i])*512)
        self.assertEqual(self.h.errors, [])

    def test_original_writer_copies_three_parameter_packets_into_output_buffers(self):
        packets, pointers = self.h.complete_three()
        self.assertEqual(self.h.count(0xA031C3098), 1)
        self.h.selection(flag=0, file_type=2, size=6, rate=3)
        self.h.call(0x40D20FD8, 1 << 8)
        self.assert_staged(packets, pointers)
        for chunk in self.h.storage_batches[0]['chunks']:
            self.assertEqual(int.from_bytes(chunk[69:74], 'big'), 2756)
            self.assertEqual(struct.unpack_from('<HH', chunk, 596), (4128, 2752))
        self.assertEqual((self.h.count(0xA031C3098), self.h.count(0xA031C3098, 1)), (0, 1))

    def test_copied_writer_buffers_survive_forced_nrmt_ring_reuse(self):
        packets, pointers = self.h.complete_three()
        self.h.call(0x40D20FD8, 1 << 8)
        chunks = self.h.storage_batches[0]['chunks']
        self.h.prepare(flag=0)
        for _ in range(60): self.h.run()
        self.assertNotEqual(bytes(self.h.u.mem_read(packets[0]['pointer'], 1024)), packets[0]['packet'])
        for pointer, chunk in zip(pointers, chunks):
            self.assertEqual(bytes(self.h.u.mem_read(pointer, 1536)), chunk)

    def test_storage_completion_event_releases_writer_task_and_busy_flag(self):
        self.h.complete_three(); self.h.call(0x40D20FD8, 1 << 8)
        self.assertEqual(self.h.count(0xA031C3098, 1), 1)
        self.assertEqual(bytes(self.h.u.mem_read(0xA031C3D40+0x64, 1)), b'\1')
        # This event is injected; no physical write or file close occurs here.
        self.h.call(0x40D20FD8, 1 << 9)
        self.assertEqual(self.h.count(0xA031C3098, 1), 0)
        self.assertEqual(bytes(self.h.u.mem_read(0xA031C3D40+0x64, 1)), b'\0')

    def test_ordinary_four_k_and_legacy_eight_k_use_the_same_unmodified_writer(self):
        for fields in (dict(flag=0), dict(size=6, actual=4)):
            with self.subTest(fields=fields):
                packets, pointers = self.h.complete_three(**fields)
                self.h.call(0x40D20FD8, 1 << 8)
                self.assert_staged(packets, pointers)
                self.h.call(0x40D20FD8, 1 << 9)
                self.h.storage_batches = []

    def test_storage_refusal_signals_error_and_keeps_task_pending(self):
        self.h.complete_three(); self.h.storage_result = 1
        self.h.call(0x40D20FD8, 1 << 8)
        self.assertEqual(self.h.errors, [(0x3B, 0x24, 0, 0)])
        self.assertIn((0xA031C3010, 0x1000), self.h.signals)
        self.assertEqual(self.h.count(0xA031C3098, 1), 1)


@unittest.skipUnless(nrmt.REAL_INPUTS, 'Set complete inputs for native queue/writer fingerprints')
class NativeQueueWindows(unittest.TestCase):
    def test_all_executed_queue_consumer_and_writer_windows_match_reviewed_baseline(self):
        image, _, _, _, baseline = nrmt.complete_inputs()
        path = Path(__file__).resolve().parents[1]/'docs/data/opengate4k-nrmt-queue-writer.json'
        record = json.loads(path.read_text())
        self.assertEqual(sha256(image).hexdigest(), record['main_sha256'])
        for window in record['native_windows']:
            start = int(window['address'], 16)-0x40160000; end = start+window['bytes']
            self.assertEqual(image[start:end], baseline[start:end], window['name'])
            self.assertEqual(sha256(image[start:end]).hexdigest(), window['sha256'], window['name'])


if __name__ == '__main__': unittest.main()

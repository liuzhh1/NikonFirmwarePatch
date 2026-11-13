"""Execute original NRMT submission to its queue API boundary.

Mutex/queue/event APIs are bounded fixtures. The native producer executes;
the operating-system queue, encoder consumer and file writer do not.
"""
import struct
import unittest
import test_opengate4k_nrmt_lifetime as nrmt


class NativeSubmitHarness(nrmt.NativeNrmtHarness):
    def __init__(self, image, report):
        self.queue_blocks = []; self.submit_apis = set(); self.errors = []; self.signals = []
        self.notifications = []; self.queue_accepts = True
        super().__init__(image, report)
        self.job = 0xA06040000

    def observe(self, u, address, size, data):
        if 0x40D200FC <= address < 0x40D2030C: return
        if address not in (0x40D2C674, 0x40D2C660, 0x40CA1AB4, 0x40CA1AC4, 0x40CA1990, 0x40C002A0):
            return super().observe(u, address, size, data)
        self.submit_apis.add(address)
        if address == 0x40CA1AB4:
            if self.reg(0) != 0xA031C1718 or self.reg(1) != 0:
                raise AssertionError('Unexpected native submission queue/selector')
            self.queue_blocks.append(bytes(u.mem_read(self.reg(2), 0xA8)))
            self.reg(0, int(self.queue_accepts))
        elif address == 0x40CA1AC4:
            self.notifications.append((self.reg(0), self.reg(1))); self.reg(0, 1)
        elif address == 0x40CA1990:
            self.errors.append(tuple(self.reg(i) for i in range(4))); self.reg(0, 0)
        elif address == 0x40C002A0:
            self.signals.append((self.reg(0), self.reg(1))); self.reg(0, 0)
        else: self.reg(0, 0)
        u.reg_write(self.A.UC_ARM64_REG_PC, self.reg(30))

    def submit(self, state=1, count=1, duplicates=0, accepts=True):
        self.queue_blocks = []; self.errors = []; self.signals = []; self.notifications = []
        self.queue_accepts = accepts
        self.word(0xA031C1818, state)
        self.u.mem_write(self.job, bytes(0x28))
        self.qwrite(self.job+0x18, self.output)
        self.word(self.job+0x20, count); self.word(self.job+0x24, duplicates)
        self.u.reg_write(self.A.UC_ARM64_REG_SP, nrmt.SP)
        self.reg(0, self.job); self.reg(30, nrmt.RETURN)
        self.u.emu_start(0x40D200FC, 0, count=100000)
        if self.u.reg_read(self.A.UC_ARM64_REG_PC) != nrmt.RETURN:
            raise AssertionError('Original NRMT submitter did not return')
        return self.queue_blocks


@unittest.skipUnless(nrmt.REAL_INPUTS, 'Set complete inputs and compiler for native submit execution')
class NativeNrmtSubmitExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.image, cls.report, *_ = nrmt.complete_inputs()
    def setUp(self):
        self.h = NativeSubmitHarness(self.image, self.report)
        self.generated = self.h.run()
    def tearDown(self): self.h.close()

    def test_prepared_queue_block_owns_descriptor_copy_and_retains_packet_pointer(self):
        blocks = self.h.submit(); self.assertEqual(len(blocks), 1)
        self.assertEqual(len(blocks[0]), 0xA8)
        self.assertEqual(blocks[0][:0x68], bytes(0x68))
        self.assertEqual(blocks[0][0x68:0xA0], self.generated['descriptor'])
        self.assertEqual(struct.unpack_from('<Q', blocks[0], 0x80)[0], self.generated['pointer'])
        self.assertEqual(struct.unpack_from('<I', blocks[0], 0x88)[0], len(self.generated['packet']))
        self.assertEqual(blocks[0][0xA0:], bytes(8))

    def test_native_inactive_states_empty_batch_and_over_limit_do_not_submit(self):
        for fields in (dict(state=0), dict(state=3), dict(count=0), dict(count=61), dict(count=21, duplicates=2)):
            self.assertEqual(self.h.submit(**fields), [])
            self.assertEqual(self.h.errors, [])
        self.assertEqual(len(self.h.submit(count=30, duplicates=1)), 60)

    def test_duplicate_flags_follow_original_native_batch_order(self):
        blocks = self.h.submit(count=2, duplicates=1)
        self.assertEqual([b[0xA0] for b in blocks], [0, 1, 0, 1])
        self.assertTrue(all(b[0x68:0xA0] == self.generated['descriptor'] for b in blocks))

    def test_queue_refusal_uses_original_error_and_event_path_without_packet_damage(self):
        self.h.submit(accepts=False)
        self.assertEqual(self.h.errors, [(0x3B, 7, 0, 0)])
        self.assertEqual(len(self.h.signals), 1)
        self.assertEqual(self.h.signals[0][1], 0x400)
        self.assertEqual(bytes(self.h.u.mem_read(self.generated['pointer'], len(self.generated['packet']))), self.generated['packet'])

    def test_submitter_preserves_native_callee_frame_and_does_not_advance_nrmt_ring(self):
        before = [self.h.reg(i) for i in range(19, 30)]
        ring = bytes(self.h.u.mem_read(nrmt.RING['index'], 4))
        self.h.submit()
        self.assertEqual([self.h.reg(i) for i in range(19, 30)], before)
        self.assertEqual(self.h.u.reg_read(nrmt.frontend.A.UC_ARM64_REG_SP), nrmt.SP)
        self.assertEqual(bytes(self.h.u.mem_read(nrmt.RING['index'], 4)), ring)
        self.assertEqual(bytes(self.h.u.mem_read(self.h.output, 0x38)), self.generated['descriptor'])
        self.assertEqual(bytes(self.h.u.mem_read(self.generated['pointer'], len(self.generated['packet']))), self.generated['packet'])


if __name__ == '__main__': unittest.main()

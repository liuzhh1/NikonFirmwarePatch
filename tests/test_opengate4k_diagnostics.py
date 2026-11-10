"""Keep the original UART fault distinct from a later register-dump stop."""
import unittest
from z8opengate4k.diagnostics import first_uart_exception

REPORT = '''\x1b[31m
**** !! exception !! ****
 Sync error
 cpu no     : 1
 run task   : 0x0000001F(31)
 task       : [CAPTG]
 PC         : 0x041170D84
 SP         : 0xA06C54D00
 X[8](XR)  =000000000000000F, X[9] =0000000A0496F6A0
 X[16](IP0)=00000000000DAF68, X[17](IP1)=00000000000DAF6A
 X[30](LR) =00000000411643B0
 ESR =96000005(ISS:000005)
 FAR =0000002A156B2806
'''


class DiagnosticTests(unittest.TestCase):
    def test_finds_primary_fault_before_later_dump_stop(self):
        result = first_uart_exception(REPORT + 'Z8_UNKNOWN pc=0x40c07c24 read addr=0x15080014')
        self.assertEqual((result['task'], result['cpu'], result['pc']), ('CAPTG', 1, '0x41170d84'))
        self.assertEqual((result['esr'], result['far']), ('0x96000005', '0x2a156b2806'))
        self.assertEqual(result['registers']['x30'], '0x411643b0')
        self.assertEqual(result['registers']['x16'], '0xdaf68')
        self.assertEqual(result['rom_selector_index'], 15)

    def test_dump_stop_alone_is_not_a_native_exception(self):
        self.assertIsNone(first_uart_exception('Z8_UNKNOWN pc=0x40c07c24 read addr=0x15080014'))

    def test_keeps_first_of_multiple_native_exceptions(self):
        second = REPORT.replace('CAPTG', 'OTHER').replace('041170D84', '040000000')
        self.assertEqual(first_uart_exception(REPORT + second)['task'], 'CAPTG')

    def test_accepts_incomplete_uart_without_inventing_fields(self):
        result = first_uart_exception('**** !! exception !! ****\n PC : 0x041170D84\n')
        self.assertEqual(result, {'source': 'native UART exception report', 'pc': '0x41170d84'})

    def test_other_fault_does_not_label_x8_as_rom_selector(self):
        result = first_uart_exception(REPORT.replace('041170D84', '0411643B0'))
        self.assertNotIn('rom_selector_index', result)


if __name__ == '__main__':
    unittest.main()

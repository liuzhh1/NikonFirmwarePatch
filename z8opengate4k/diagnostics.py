"""Read the first native exception, before any later diagnostic MMIO stop."""
import re


def first_uart_exception(text):
    marker = '**** !! exception !! ****'
    if marker not in text:
        return None
    report = text.split(marker, 1)[1].split(marker, 1)[0]
    result = {'source': 'native UART exception report'}
    for key, pattern, numeric in (
        ('task', r'^\s*task\s*:\s*\[([^\]]+)\]', False),
        ('cpu', r'^\s*cpu no\s*:\s*(\d+)', True),
        ('pc', r'^\s*PC\s*:\s*0x([0-9a-fA-F]+)', False),
        ('sp', r'^\s*SP\s*:\s*0x([0-9a-fA-F]+)', False),
        ('esr', r'^\s*ESR\s*=\s*([0-9a-fA-F]+)', False),
        ('far', r'^\s*FAR\s*=\s*([0-9a-fA-F]+)', False),
    ):
        match = re.search(pattern, report, re.MULTILINE)
        if match:
            value = match.group(1)
            result[key] = int(value) if numeric else value if key == 'task' else hex(int(value, 16))
    registers = {f'x{int(n)}': hex(int(value, 16))
                 for n, value in re.findall(r'X\[(\d+)\](?:\([A-Z0-9]+\))?\s*=\s*([0-9a-fA-F]+)', report)}
    if registers:
        result['registers'] = registers
    if result.get('pc') == '0x41170d84' and 'x8' in registers:
        result['rom_selector_index'] = int(registers['x8'], 16)
    return result

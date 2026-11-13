#!/usr/bin/env python3
"""Inspect the stock C3.11 paths needed for 4K open gate; never build firmware."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from z8prores.package import Package, PACKAGE_BYTES, require_official_input

BASE = 0x40160000
INIT_VA, INIT_OFFSET, INIT_END = 0xA02808000, 0x4B13000, 0x4DC0000
RATE_OFFSET, RATE_COUNT = 0x42AB3C90 - BASE, 42
MENU_OFFSET, MENU_COUNT = 43776736, 80
IMENU_HIGH, IMENU_NORMAL, IMENU_COUNT = 0x42B0662C - BASE, 0x42B067F4 - BASE, 19
GEOMETRY = {
    'full_raw_stream_height': 0xA02A979C2,
    'half_raw_stream_height': 0xA02A979D2,
    'full_geometry_height': 0xA02A979EE,
    'half_geometry_height': 0xA02A979FE,
    'full_active_height': 0xA02A97A1A,
    'half_active_height': 0xA02A97A2A,
    'full_route_input_1_height': 0xA02A97CDA,
    'full_route_input_2_height': 0xA02A97CDE,
    'half_route_input_1_height': 0xA02A97D12,
    'half_route_input_2_height': 0xA02A97D16,
}
SOURCE_EVIDENCE = (
    ('z8opengate/src/menu_repair_hooks.S', 'configuration_hook:',
     'The current recording predicate selects size code 6 (8.3K).'),
    ('z8opengate/src/menu_repair_hooks.S', 'driver_hook:',
     'The half-height branch selects driver 14 in the existing view path; recording support is unproven.'),
    ('z8opengate/src/ui_hooks.S', '.global half_size_hook',
     'Existing half-size handling uses active height 2752; this is not a recording acceptance test.'),
    ('z8opengate/src/ui_hooks.S', '.global half_extent_hook',
     'The existing half-extent path mentions width 4140, internal height 2756 and extent 2760.'),
    ('z8opengate/src/d8_hooks.S', 'og_gate_wanted:',
     'The mode-change comparison also checks the 8.3K size code.'),
    ('z8opengate/src/d10_hooks.S', 'og_open_gate_file:',
     'The playback predicate currently recognizes 8256x5504 N-RAW only.'),
    ('z8opengate/patcher.py', 'def og_tier_tables(',
     'The open-gate bitrate records currently extend only the 8.3K low-frame-rate modes.'),
    ('z8opengate/imenu.py', 'def extend(',
     'The current i-menu has three extra 8.3K rows; a 4K mode needs independent selection and rollback.'),
)


def need(ok, message):
    if not ok:
        raise ValueError(message)


def bounded(data, offset, length):
    need(offset >= 0 and length >= 0 and offset <= len(data) - length,
         'Read outside the supplied image')
    return data[offset:offset + length]


def initial_offset(address):
    """Translate initialized RAM only; never pretend a runtime snapshot was read."""
    length = INIT_END - INIT_OFFSET
    need(INIT_VA <= address < INIT_VA + length, 'Address is outside initialized RAM')
    return INIT_OFFSET + address - INIT_VA


def parse_rate_pairs(raw):
    """Read the paired High/Normal stock records without assuming their order."""
    record = struct.Struct('<HHIIIQ')
    need(len(raw) == RATE_COUNT * record.size, 'Wrong rate-table length')
    records = list(record.iter_unpack(raw))
    pairs = []
    half = RATE_COUNT // 2
    for index in range(half):
        high, normal = records[index], records[index + half]
        need(high[:5] == normal[:5], f'Rate-pair identity differs at {index}')
        width, height, numerator, denominator, reserved = high[:5]
        need(width > 0 and height > 0 and numerator > 0 and denominator > 0,
             f'Invalid geometry or frame rate at {index}')
        need(bool(high[5]) == bool(normal[5]), f'Half-empty rate pair at {index}')
        pairs.append(dict(index=index, coded_width=width, coded_height=height,
                          numerator=numerator, denominator=denominator,
                          fps=numerator / denominator, reserved=reserved,
                          high_bps=high[5], normal_bps=normal[5],
                          stock_supported=bool(high[5])))
    return pairs


def parse_menu(raw):
    record = struct.Struct('<6I')
    need(len(raw) == MENU_COUNT * record.size, 'Wrong menu-table length')
    rows = []
    for index, words in enumerate(record.iter_unpack(raw)):
        item, file_type, rate, size, word4, word5 = words
        if file_type == 6:
            rows.append(dict(index=index, item_id=hex(item), file_type=file_type, size_code=size,
                             rate_code=rate, word4=word4, word5=word5))
    # These are the stock templates used by the existing reviewed builder.
    for index, rate in zip((53, 54, 55), (4, 5, 6)):
        words = record.unpack_from(raw, index * record.size)
        need(words[1:4] == (6, rate, 6), 'Unexpected stock 8.3K menu template')
    return rows


def parse_imenu(high_raw, normal_raw):
    """N-RAW's independent native i-menu templates: size, rate, flag, quality, index, resource."""
    record = struct.Struct('<6I')
    need(len(high_raw) == len(normal_raw) == IMENU_COUNT * record.size, 'Wrong i-menu table length')
    rows = []
    for index, (high, normal) in enumerate(zip(record.iter_unpack(high_raw), record.iter_unpack(normal_raw))):
        need(high[:3] == normal[:3] and high[4] == normal[4], 'i-menu quality-pair identity differs')
        need(high[3] == 1 and normal[3] == 0, 'Unexpected i-menu quality values')
        need(high[4] == index, 'Unexpected i-menu selection index')
        rows.append(dict(index=index, size_code=high[0], rate_code=high[1],
                         variant=high[2], high_resource_key=high[5], normal_resource_key=normal[5]))
    return rows


def crosscheck_menus(main_rows, imenu_rows):
    """Match identities across independently read tables, never by row position."""
    matches = []
    for row in imenu_rows:
        found = [m for m in main_rows if (m['size_code'], m['rate_code'], m['word4']) ==
                 (row['size_code'], row['rate_code'], row['variant'])]
        need(len(found) == 1, 'Missing or ambiguous main/i-menu identity')
        matches.append(dict(size_code=row['size_code'], rate_code=row['rate_code'],
                            main_index=found[0]['index'], main_item=found[0]['item_id'],
                            imenu_index=row['index']))
    return matches


def source_evidence():
    result = []
    for path, marker, observation in SOURCE_EVIDENCE:
        raw = (ROOT / path).read_bytes()
        lines = raw.decode('utf-8').splitlines()
        matches = [i + 1 for i, line in enumerate(lines) if marker in line]
        need(len(matches) == 1, f'Source evidence is ambiguous or missing: {path}: {marker}')
        result.append(dict(path=path, line=matches[0], marker=marker,
                           sha256=hashlib.sha256(raw).hexdigest(), observation=observation))
    return result


def research_report():
    return dict(
        schema='z8-opengate4k-research-2',
        stage='source_research',
        recording_4k_open_gate_implemented=False,
        firmware_generated=False,
        target=dict(codec='N-RAW', active_width=4128, active_height=2752,
                    aspect='3:2', initial_menu_rates=['30p', '25p', '24p'],
                    field_of_view='Full-height FX target; must be checked against a still reference',
                    sampling='Unknown: do not assume oversampling, binning or line skipping'),
        source_evidence=source_evidence(),
        unresolved=[
            'Confirm the runtime 4.1K readout/plan identities; its stock menu size code is 4.',
            'Check the sensor driver and frontend buffer extents for full-height recording, not only live view.',
            'Determine actual encoded dimensions, alignment and crop independently of the active dimensions.',
            'Add coherent main/i-menu selection, cancellation, bank and power-cycle handling.',
            'Update recording descriptors, NCTG/NRMT, bitrate/time budgets, proxy and playback geometry together.',
            'Review compiled units and combination recipes, then run bounded execution and camera tests.',
        ],
    )


def inspect_firmware(path):
    need(path.is_file(), 'Input must be a regular firmware file')
    need(path.stat().st_size == PACKAGE_BYTES, 'Expected the complete original Z8 C3.11 input')
    raw = path.read_bytes()
    require_official_input(raw)
    package = Package(raw)
    eg = package.eg
    pairs = parse_rate_pairs(bounded(eg, RATE_OFFSET, RATE_COUNT * 24))
    menu = parse_menu(bounded(eg, MENU_OFFSET, MENU_COUNT * 24))
    imenu = parse_imenu(bounded(eg, IMENU_HIGH, IMENU_COUNT * 24),
                       bounded(eg, IMENU_NORMAL, IMENU_COUNT * 24))
    identities = crosscheck_menus(menu, imenu)
    four_k_menus = [row for row in identities
                   if row['size_code'] == 4 and row['rate_code'] in (4, 5, 6)]
    need(len(menu) == len(identities) == 19 and len(four_k_menus) == 3,
         'Unexpected stock N-RAW mode inventory')
    candidates = [row for row in pairs
                  if (row['coded_width'], row['coded_height']) == (4140, 2330)
                  and 23 <= row['fps'] <= 31 and row['stock_supported']]
    need(len(candidates) == 3, 'Expected three supported low-rate 4.1K stock record pairs')
    report = research_report()
    report.update(
        stage='stock_static_inspection',
        input_sha256=hashlib.sha256(raw).hexdigest(),
        input_bytes=len(raw),
        payload_sha256=hashlib.sha256(eg).hexdigest(),
        stock_rate_pairs=pairs,
        stock_4k_low_rate_candidates=candidates,
        stock_nraw_menu_rows=menu,
        stock_nraw_imenu_rows=imenu,
        stock_menu_identity_matches=identities,
        stock_4k_low_rate_menu_candidates=four_k_menus,
        stock_initial_geometry=[dict(name=name, address=hex(address),
                                     height=struct.unpack('<H', bounded(eg, initial_offset(address), 2))[0])
                                for name, address in GEOMETRY.items()],
        interpretation='Read-only initial tables. No CPU execution, sensor readout or recording was tested.',
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('firmware', nargs='?', type=Path, help='Complete original Z_8_0311.bin')
    parser.add_argument('--source-only', action='store_true', help='Describe source evidence without firmware')
    parser.add_argument('--output', type=Path, help='New JSON report file; existing files are never replaced')
    args = parser.parse_args(argv)
    if bool(args.firmware) == args.source_only:
        parser.error('Supply either a firmware input or --source-only')
    if args.output:
        need(args.output.suffix.lower() == '.json', 'Output must be a JSON report')
        need(not args.output.exists(), 'Report already exists; choose a new path')
    report = research_report() if args.source_only else inspect_firmware(args.firmware)
    text = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as handle:
            handle.write(text)
    else:
        print(text, end='')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        raise SystemExit('ERROR: ' + str(error))

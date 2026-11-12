"""Opt-in recorder descriptors and metadata; no Nikon update package output.

Coded2756 is a candidate, not TICO/physical qualification. Keep D10 intact.
"""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
from z8patch.asm import link_elf
from z8patch.image import branch
from .overlay import make_main

ROOT = Path(__file__).resolve().parents[1]
BASE, CODE_END = 0x40966000, 0x4096B000
TABLES = {'common': 0x4096B000, 'fine': 0x4096B400, 'basic': 0x4096B800}
OLD_TABLES = {'common': 0x408C1000, 'fine': 0x40957000, 'basic': 0x409573F0}
RECORD = struct.Struct('<HHIIIQ')
IMAGE_BASE = 0x40160000
GEOMETRY = dict(coded_width=4140, coded_height_candidate=2756,
                active_width=4128, active_height=2752, physical_height=2756,
                logical_height=2760, encoding_qualified=False)
SITES = {0x40D1E650: 'og4k_record_table_hook', 0x410A590C: 'og4k_nrmt_hook',
         0x410A6D0C: 'og4k_crop_hook', 0x406D2C8C: 'og4k_nctg_height_hook',
         0x406D3138: 'og4k_proxy_main_height_hook', 0x406D3824: 'og4k_nctg_crop_hook'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def project_tables(tables):
    """Project3/2/1.5/1bpp with native fixed overhead and rational frame rates.

    Identity is checked independently then pinned to the machine selector's
    verified9..11/30..32 indexes. These are candidate budgets, not measurements.
    """
    if set(tables) != set(TABLES) or any(len(t) != 42*24 for t in tables.values()):
        raise ValueError('Three native42-record tables required')
    result = {name: bytearray(data) for name, data in tables.items()}
    rows = [RECORD.unpack_from(tables['common'], i*24) for i in range(42)]
    edits = []
    for index, (n, d) in zip((9, 10, 11), ((30000, 1001), (25000, 1000), (24000, 1001))):
        hi, normal = rows[index], rows[index+21]
        if hi[:5] != normal[:5] or hi[:4] != (4140, 2330, n, d) or not min(hi[5], normal[5]):
            raise ValueError('Pinned4K High/Normal record identity differs')
        pixels = Fraction(4140*2330*n, d)
        overhead = max(hi[5]-3*pixels, normal[5]-Fraction(3, 2)*pixels)
        if not 0 < overhead < Fraction(hi[5], 20):
            raise ValueError('Native overhead falls outside the reviewed budget rule')
        full = Fraction(4140*2756*n, d)
        budgets = {}
        for tier, bpp, table, at in (
            ('high', 3, 'common', index), ('normal', Fraction(3, 2), 'common', index+21),
            ('fine', 2, 'fine', index), ('basic', 1, 'basic', index+21)):
            record = RECORD.unpack_from(tables[table], at*24)
            if record[:5] != hi[:5]:
                raise ValueError('Quality table geometry/frame-rate identity differs')
            exact = (bpp*full+overhead)/1000000
            bps = -(-exact.numerator//exact.denominator)*1000000
            struct.pack_into('<H', result[table], at*24+2, 2756)
            struct.pack_into('<Q', result[table], at*24+16, bps)
            budgets[tier] = bps
            edits.append(dict(table=table, index=at, tier=tier, numerator=n,
                              denominator=d, old_bps=record[5], candidate_bps=bps))
        if not budgets['high'] > budgets['fine'] > budgets['normal'] > budgets['basic']:
            raise ValueError('Projected budget ordering differs')
    return {name: bytes(data) for name, data in result.items()}, edits


def compile_recorder(compiler='clang'):
    legacy = json.loads((ROOT/'resources/compiled.json').read_text())['units']['opengate']
    names = ('tier_table_hook', 'nrmt_hook', 'crop_hook', 'nctg_crop_hook')
    flags = ['-target', 'aarch64-none-elf', '-x', 'assembler-with-cpp']
    flags += [f'-Dlegacy_{n}=original_{int(legacy["symbols"][n]["va"], 16):X}' for n in names]
    flags += [f'-DOG4K_{name.upper()}={value:#x}' for name, value in TABLES.items()]
    source = ROOT/'z8opengate4k/src/recorder.S'
    with tempfile.TemporaryDirectory(prefix='z8-og4k-recorder-') as folder:
        obj = Path(folder)/'recorder.o'
        subprocess.run([compiler, *flags, '-c', str(source), '-o', str(obj)],
                       check=True, capture_output=True)
        code, entries, relocations = link_elf(obj.read_bytes(), BASE)
    if BASE+len(code) > CODE_END:
        raise ValueError('Recorder overlaps private candidate tables')
    return code, dict(base=BASE, bytes=len(code), sha256=sha(code),
        source_sha256=sha(source.read_bytes()), entries=entries, relocations=relocations,
        legacy_entries={n: int(legacy['symbols'][n]['va'], 16) for n in names})


def make_recorder_main(original, candidate, compiler='clang'):
    frontend, report = make_main(original, candidate, compiler)
    tables = {name: frontend[address-IMAGE_BASE:address-IMAGE_BASE+42*24]
              for name, address in OLD_TABLES.items()}
    projected, edits = project_tables(tables)
    code, compiled = compile_recorder(compiler)
    profile = json.loads((ROOT/'z8opengate4k/recorder-profile.json').read_text())
    if compiled != profile['compiled'] or GEOMETRY != profile['geometry']:
        raise ValueError('Recorder source/code/geometry differs from staged profile')
    new = bytearray(frontend)
    writes = [(int(w['address'], 16), w['bytes']) for w in report['writes']]
    if 0x40965000+report['compiled']['bytes'] > BASE:
        raise ValueError('Frontend overlaps recorder code')

    def put(address, data, purpose, empty=False):
        offset = address-IMAGE_BASE
        if offset < 0 or offset+len(data) > len(new):
            raise ValueError('Recorder write outside MAIN')
        if empty and any(new[offset:offset+len(data)]):
            raise ValueError('Recorder allocation is not empty')
        if any(address < a+n and a < address+len(data) for a, n in writes):
            raise ValueError('Recorder allocations overlap')
        new[offset:offset+len(data)] = data
        writes.append((address, len(data)))
        report['writes'].append(dict(address=hex(address), bytes=len(data), purpose=purpose))

    put(BASE, code, 'opt-in recorder/metadata companions', empty=True)
    for name, address in TABLES.items():
        put(address, projected[name], 'private4K candidate '+name+' table', empty=True)
    expected_native = {0x406D2C8C: bytes.fromhex('48228152'),
                       0x406D3138: bytes.fromhex('49228152')}
    for address, entry in SITES.items():
        if address in expected_native:
            if frontend[address-IMAGE_BASE:address-IMAGE_BASE+4] != expected_native[address]:
                raise ValueError('Native4K metadata branch differs')
        else:
            legacy_name = {'og4k_record_table_hook': 'tier_table_hook', 'og4k_nrmt_hook': 'nrmt_hook',
                           'og4k_crop_hook': 'crop_hook', 'og4k_nctg_crop_hook': 'nctg_crop_hook'}[entry]
            target = compiled['legacy_entries'][legacy_name]
            if frontend[address-IMAGE_BASE:address-IMAGE_BASE+4] != branch(address, target, False):
                raise ValueError('Reviewed8K hook seam differs')
        put(address, branch(address, compiled['entries'][entry], False), entry)
    report.update(schema='z8-opengate4k-recorder-main-1', main_sha256=sha(new),
        frontend_main_sha256=sha(frontend), recorder=dict(compiled=compiled, geometry=GEOMETRY,
            projected_budget_records=edits, table_sha256={n: sha(t) for n, t in projected.items()},
            file_callback_lifetime_qualified=False, tico_qualified=False),
        scope='Opt-in candidate recording descriptors/NRMT/NCTG/budgets; no i-menu, close-lifetime, playback or TICO acceptance')
    return bytes(new), report

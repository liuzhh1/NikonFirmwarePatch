"""Opt-in ownership of one native NCTG recording-task working copy.

This does not establish NRMT/general writer lifetime or physical recording.
"""
import json
from pathlib import Path
import subprocess
import tempfile
from z8patch.asm import link_elf
from z8patch.image import branch
from .recorder import ROOT, IMAGE_BASE, make_recorder_main, sha

BASE, END = 0x4096D000, 0x4096F000
STATE_ROM, STATE_RAM, STATE_BYTES = 0x4096F200, 0xA0FF6F200, 64
ATTR, PRIVATE_INFO = 0xA0460BE88, 0xA0460EC20
GEOMETRY = dict(active_width=4128, active_height=2752, coded_width=4140,
                coded_height_candidate=2756, encoding_qualified=False)
REPLACED = {0x406D2C8C: ('og4k_owned_height_hook', 'og4k_nctg_height_hook'),
            0x406D3138: ('og4k_owned_proxy_main_hook', 'og4k_proxy_main_height_hook'),
            0x406D3824: ('og4k_owned_crop_hook', 'og4k_nctg_crop_hook')}


def compile_lifetime(compiler='clang'):
    legacy = json.loads((ROOT/'resources/compiled.json').read_text())['units']['opengate']
    names = ('nctg_crop_hook', 'boot_reset_d8_hook')
    flags = ['-target', 'aarch64-none-elf', '-x', 'assembler-with-cpp']
    flags += [f'-Dlegacy_{n}=original_{int(legacy["symbols"][n]["va"], 16):X}' for n in names]
    source = ROOT/'z8opengate4k/src/nctg_lifetime.S'
    with tempfile.TemporaryDirectory(prefix='z8-og4k-nctg-lifetime-') as folder:
        obj = Path(folder)/'nctg-lifetime.o'
        subprocess.run([compiler, *flags, '-c', str(source), '-o', str(obj)],
                       check=True, capture_output=True)
        code, entries, relocations = link_elf(obj.read_bytes(), BASE)
    if BASE+len(code) > END:
        raise ValueError('NCTG lifetime code overlaps original D10 state page')
    return code, dict(base=BASE, bytes=len(code), sha256=sha(code),
        source_sha256=sha(source.read_bytes()), entries=entries, relocations=relocations,
        legacy_entries={n: int(legacy['symbols'][n]['va'], 16) for n in names})


def make_lifetime_main(original, candidate, compiler='clang', *, playback=False):
    if playback:
        from .playback import make_playback_main
        parent, report = make_playback_main(original, candidate, compiler)
    else:
        parent, report = make_recorder_main(original, candidate, compiler)
    parent_hash = sha(parent)
    code, compiled = compile_lifetime(compiler)
    profile = json.loads((Path(__file__).parent/'nctg-lifetime-profile.json').read_text())
    if compiled != profile['compiled'] or GEOMETRY != profile['geometry']:
        raise ValueError('NCTG lifetime source/code/geometry differs from staged profile')
    for window in profile['native_windows']:
        off = int(window['address'], 16)-IMAGE_BASE
        if sha(parent[off:off+window['bytes']]) != window['sha256']:
            raise ValueError('Native NCTG ownership/callback contract differs')
    if STATE_ROM+0x9CF600000 != STATE_RAM or STATE_ROM+STATE_BYTES > 0x40970000:
        raise ValueError('Private state must stay in the original copied code cave alias')
    new = bytearray(parent)

    def put(address, data, purpose, *, empty=False, replace=None):
        off = address-IMAGE_BASE
        if off < 0 or off+len(data) > len(new):
            raise ValueError('NCTG lifetime write outside MAIN')
        if empty and any(new[off:off+len(data)]):
            raise ValueError('NCTG lifetime allocation is not empty')
        overlap = [w for w in report['writes'] if address < int(w['address'], 16)+w['bytes']
                   and int(w['address'], 16) < address+len(data)]
        if replace is None:
            if overlap: raise ValueError('NCTG lifetime allocations overlap')
        else:
            if len(overlap) != 1 or overlap[0] != dict(address=hex(address), bytes=4, purpose=replace):
                raise ValueError('Expected exact recorder seam replacement')
            report['writes'].remove(overlap[0])
        new[off:off+len(data)] = data
        report['writes'].append(dict(address=hex(address), bytes=len(data), purpose=purpose))

    put(BASE, code, 'opt-in native NCTG working-copy identity', empty=True)
    put(STATE_ROM, bytes(STATE_BYTES), 'private NCTG state initialization in copied code cave', empty=True)
    for address, (entry, old) in REPLACED.items():
        target = report['recorder']['compiled']['entries'][old]
        if parent[address-IMAGE_BASE:address-IMAGE_BASE+4] != branch(address, target, False):
            raise ValueError('Expected recorder NCTG seam differs')
        put(address, branch(address, compiled['entries'][entry], False), entry, replace=old)
    for address, target, entry, call in (
        (0x4071E220, 0x4127A900, 'og4k_nctg_clone_hook', True),
        (0x41184DE8, compiled['legacy_entries']['boot_reset_d8_hook'], 'og4k_nctg_reset_hook', False)):
        if parent[address-IMAGE_BASE:address-IMAGE_BASE+4] != branch(address, target, call):
            raise ValueError('Reviewed native clone/reset seam differs')
        put(address, branch(address, compiled['entries'][entry], call), entry)
    report.update(schema='z8-opengate4k-nctg-lifetime-main-1', main_sha256=sha(new),
        nctg_parent_main_sha256=parent_hash,
        nctg_lifetime=dict(compiled=compiled, geometry=GEOMETRY,
            native_windows=profile['native_windows'],
            private_state=dict(rom=hex(STATE_ROM), ram_alias=hex(STATE_RAM), bytes=STATE_BYTES),
            native_attribute_owner=hex(ATTR), native_private_info=hex(PRIVATE_INFO),
            native_copy_bytes=0x4490, identity_capture='native private ImgInfo copy at4071E220',
            callback_uses_current_selection=False, nrmt_lifetime_qualified=False,
            writer_close_lifetime_qualified=False, physical_recording_qualified=False),
        scope='Opt-in private NCTG copy identity; NRMT/general writer lifetime, i-menu and TICO remain unqualified')
    return bytes(new), report

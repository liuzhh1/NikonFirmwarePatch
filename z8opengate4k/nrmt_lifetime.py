"""Opt-in call-scoped NRMT identity; retains native formatter and ring buffers.

This is not a general writer/ring-buffer ownership or final-close solution.
"""
import json
from pathlib import Path
import subprocess
import tempfile
from z8patch.asm import link_elf
from z8patch.image import branch
from .recorder import ROOT, IMAGE_BASE, make_recorder_main, sha

BASE, END = 0x4096E000, 0x4096F000
RING = dict(pointer_table=0xA0460B758, index=0xA0460B938, slots=60)
FRAME = dict(wrapper_bytes=48, native_formatter_bytes=0xD0,
             nested_prefix_bytes=0x10, nested_formatter_bytes=0x40,
             native_saved_lr_offset=0xC8, nested_prefix_saved_lr_offset=0,
             nested_formatter_saved_lr_offset=0x38,
             snapshot_pointer_offset=16, cookie_offset=24, rate_offset=32,
             target_offset=36, request_kind_offset=40)
SITES = {0x410A590C: ('og4k_scoped_nrmt_height_hook', 'og4k_nrmt_hook'),
         0x410A6D0C: ('og4k_scoped_nrmt_crop_hook', 'og4k_crop_hook')}


def compile_nrmt(compiler='clang'):
    legacy = json.loads((ROOT/'resources/compiled.json').read_text())['units']['opengate']
    names = ('nrmt_hook', 'crop_hook')
    flags = ['-target', 'aarch64-none-elf', '-x', 'assembler-with-cpp']
    flags += [f'-Dlegacy_{n}=original_{int(legacy["symbols"][n]["va"], 16):X}' for n in names]
    source = ROOT/'z8opengate4k/src/nrmt_lifetime.S'
    with tempfile.TemporaryDirectory(prefix='z8-og4k-nrmt-scope-') as folder:
        obj = Path(folder)/'nrmt-scope.o'
        subprocess.run([compiler, *flags, '-c', str(source), '-o', str(obj)],
                       check=True, capture_output=True)
        code, entries, relocations = link_elf(obj.read_bytes(), BASE)
    if BASE+len(code) > END:
        raise ValueError('NRMT scope code overlaps original state page')
    return code, dict(base=BASE, bytes=len(code), sha256=sha(code),
        source_sha256=sha(source.read_bytes()), entries=entries, relocations=relocations,
        legacy_entries={n: int(legacy['symbols'][n]['va'], 16) for n in names})


def make_nrmt_main(original, candidate, compiler='clang', *, playback=False, nctg_lifetime=False):
    if nctg_lifetime:
        from .nctg_lifetime import make_lifetime_main
        parent, report = make_lifetime_main(original, candidate, compiler, playback=playback)
    elif playback:
        from .playback import make_playback_main
        parent, report = make_playback_main(original, candidate, compiler)
    else:
        parent, report = make_recorder_main(original, candidate, compiler)
    parent_hash = sha(parent)
    code, compiled = compile_nrmt(compiler)
    profile = json.loads((Path(__file__).parent/'nrmt-lifetime-profile.json').read_text())
    if (compiled != profile['compiled'] or FRAME != profile['stack_frame']
            or RING != profile['native_ring']):
        raise ValueError('NRMT scope source/code/frame differs from staged profile')
    for w in profile['native_windows']:
        off = int(w['address'], 16)-IMAGE_BASE
        if sha(parent[off:off+w['bytes']]) != w['sha256']:
            raise ValueError('Native NRMT frame/callback/ring contract differs')
    new = bytearray(parent)

    def put(address, data, purpose, *, empty=False, replace=None):
        off = address-IMAGE_BASE
        if off < 0 or off+len(data) > len(new):
            raise ValueError('NRMT scope write outside MAIN')
        if empty and any(new[off:off+len(data)]):
            raise ValueError('NRMT scope allocation is not empty')
        overlaps = [w for w in report['writes'] if address < int(w['address'], 16)+w['bytes']
                    and int(w['address'], 16) < address+len(data)]
        if replace is None:
            if overlaps: raise ValueError('NRMT scope allocation overlaps')
        else:
            if len(overlaps) != 1 or overlaps[0] != dict(address=hex(address), bytes=4, purpose=replace):
                raise ValueError('Expected exact recorder NRMT seam replacement')
            report['writes'].remove(overlaps[0])
        new[off:off+len(data)] = data
        report['writes'].append(dict(address=hex(address), bytes=len(data), purpose=purpose))

    put(BASE, code, 'opt-in NRMT call-scoped identity', empty=True)
    for address, (entry, old) in SITES.items():
        expected = branch(address, report['recorder']['compiled']['entries'][old], False)
        if parent[address-IMAGE_BASE:address-IMAGE_BASE+4] != expected:
            raise ValueError('Expected recorder NRMT hook differs')
        put(address, branch(address, compiled['entries'][entry], False), entry, replace=old)
    if parent[0x410A4FC4-IMAGE_BASE:0x410A4FC8-IMAGE_BASE] != bytes.fromhex('ff4303d1'):
        raise ValueError('Native NRMT prologue differs')
    put(0x410A4FC4, branch(0x410A4FC4, compiled['entries']['og4k_nrmt_scope_hook'], False),
        'og4k_nrmt_scope_hook')
    report.update(schema='z8-opengate4k-nrmt-scope-main-1', main_sha256=sha(new),
        nrmt_parent_main_sha256=parent_hash, nrmt_lifetime=dict(compiled=compiled,
            stack_frame=FRAME, native_ring=RING, native_windows=profile['native_windows'],
            capture='native formatter410A4FC4 entry', callback_uses_current_selection=False,
            shared_state_allocated=False, ring_buffer_lifetime_qualified=False,
            writer_close_qualified=False, recording_qualified=False),
        scope='Opt-in call-scoped NRMT and optional NCTG/playback; native ring/writer close and TICO unqualified')
    return bytes(new), report

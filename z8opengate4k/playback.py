"""Opt-in file-owned4K playback projections, layered on recorder MAIN only."""
import json
from pathlib import Path
import subprocess
import tempfile
from z8patch.asm import link_elf
from z8patch.image import branch
from .recorder import ROOT, IMAGE_BASE, make_recorder_main, sha

BASE, END = 0x4096C000, 0x4096E000
SITES = {0x4078E150: ('og4k_aspect_class_hook', 'og_aspect_class_hook'),
         0x4078E1DC: ('og4k_aspect_class_thumb_hook', 'og_aspect_class_thumb_hook'),
         0x407D2EA8: ('og4k_preview_hook', 'preview_full_page_hook'),
         0x40711530: ('og4k_playback_capture_hook', 'playback_capture_hook')}


def compile_playback(compiler='clang'):
    legacy = json.loads((ROOT/'resources/compiled.json').read_text())['units']['opengate']
    names = {old for _, old in SITES.values()}
    flags = ['-target', 'aarch64-none-elf', '-x', 'assembler-with-cpp']
    flags += [f'-Dlegacy_{n}=original_{int(legacy["symbols"][n]["va"], 16):X}' for n in sorted(names)]
    source = ROOT/'z8opengate4k/src/playback.S'
    with tempfile.TemporaryDirectory(prefix='z8-og4k-playback-') as folder:
        obj = Path(folder)/'playback.o'
        subprocess.run([compiler, *flags, '-c', str(source), '-o', str(obj)],
                       check=True, capture_output=True)
        code, entries, relocations = link_elf(obj.read_bytes(), BASE)
    if BASE+len(code) > END:
        raise ValueError('Playback exceeds private allocation')
    return code, dict(base=BASE, bytes=len(code), sha256=sha(code),
        source_sha256=sha(source.read_bytes()), entries=entries, relocations=relocations,
        legacy_entries={n: int(legacy['symbols'][n]['va'], 16) for n in sorted(names)})


def make_playback_main(original, candidate, compiler='clang'):
    recorder, report = make_recorder_main(original, candidate, compiler)
    code, compiled = compile_playback(compiler)
    profile = json.loads((Path(__file__).parent/'playback-profile.json').read_text())
    if compiled != profile['compiled']:
        raise ValueError('Playback source/code differs from staged profile')
    new = bytearray(recorder)
    writes = [(int(w['address'], 16), w['bytes']) for w in report['writes']]

    def put(address, data, purpose, empty=False):
        offset = address-IMAGE_BASE
        if offset < 0 or offset+len(data) > len(new):
            raise ValueError('Playback write outside MAIN')
        if empty and any(new[offset:offset+len(data)]):
            raise ValueError('Playback allocation is not empty')
        if any(address < a+n and a < address+len(data) for a, n in writes):
            raise ValueError('Playback allocations overlap')
        new[offset:offset+len(data)] = data
        writes.append((address, len(data)))
        report['writes'].append(dict(address=hex(address), bytes=len(data), purpose=purpose))

    put(BASE, code, 'opt-in file-owned playback companions', empty=True)
    for address, (entry, legacy) in SITES.items():
        expected = branch(address, compiled['legacy_entries'][legacy], False)
        if recorder[address-IMAGE_BASE:address-IMAGE_BASE+4] != expected:
            raise ValueError('Reviewed D10 playback hook seam differs')
        put(address, branch(address, compiled['entries'][entry], False), entry)
    report.update(schema='z8-opengate4k-playback-main-1', main_sha256=sha(new),
        recorder_main_sha256=sha(recorder), playback=dict(compiled=compiled,
            identity_source='native file record and native playback request/media-ID',
            file_active_dimensions=[[4128, 2752], [8256, 5504]],
            file_identity_uses_shooting_globals=False, actual_clip_decode_qualified=False,
            proxy_stream_qualified=False, full_qemu_playback_qualified=False),
        scope='Opt-in candidate recorder plus file-owned playback geometry; no close-lifetime, i-menu or TICO acceptance')
    return bytes(new), report

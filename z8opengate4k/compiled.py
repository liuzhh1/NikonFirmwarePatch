"""Compile isolated frontend prototypes. No firmware input, image edits or flash output."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from z8patch.asm import link_elf

ROOT=Path(__file__).resolve().parents[1]
BASE,END=0x40965000,0x4096F000

def compile_frontend(compiler='clang'):
    profile=json.loads((ROOT/'resources/compiled.json').read_text())['units']['opengate']
    if 0x40960000+profile['bytes']>BASE:
        raise ValueError('Prototype overlaps the reviewed Open Gate code')
    legacy={name:int(profile['symbols'][name]['va'],16)
            for name in ('configuration_hook','half_plan_hook','menu_summary_match_hook')}
    source=ROOT/'z8opengate4k/src/hooks.S'
    flags=['-target','aarch64-none-elf','-x','assembler-with-cpp']
    flags += [f'-Dlegacy_{name}=original_{address:X}' for name,address in legacy.items()]
    with tempfile.TemporaryDirectory(prefix='z8-og4k-frontend-') as directory:
        obj=Path(directory)/'frontend.o'
        subprocess.run([compiler,*flags,'-c',str(source),'-o',str(obj)],check=True,capture_output=True)
        code,entries,relocations=link_elf(obj.read_bytes(),BASE)
    if BASE+len(code)>END:
        raise ValueError('Prototype reaches reserved runtime state')
    return code,dict(base=BASE,bytes=len(code),sha256=hashlib.sha256(code).hexdigest(),
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        entries={k:v for k,v in entries.items() if k.endswith('_hook')},
        legacy_entries=legacy,relocations=relocations,
        geometry_stage_implemented=True,recording_4k_open_gate_implemented=False,
        firmware_generated=False,production_builder_enabled=False,
        scope='Isolated frontend code; TICO, metadata, i-menu/cancel and physical sensor acceptance remain unqualified')

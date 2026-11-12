#!/usr/bin/env python3
"""Build emulator-only 4K frontend/recorder prototypes, never a flash package."""
import argparse,json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from z8opengate4k.overlay import make_main

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original',required=True,type=Path)
    p.add_argument('--baseline',required=True,type=Path)
    p.add_argument('--compiler',default='clang')
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--experimental-recorder',action='store_true',
                   help='Opt-in record tables and NRMT/NCTG;2756 coded rows are not TICO-qualified')
    a=p.parse_args()
    if a.output.exists():p.error('Output directory must be new')
    for path in (a.original,a.baseline):
        if not path.is_file() or path.stat().st_size!=99051117:p.error('Complete C3.11 packages required')
    if a.experimental_recorder:
        from z8opengate4k.recorder import make_recorder_main
        builder=make_recorder_main
    else:builder=make_main
    raw,report=builder(a.original.read_bytes(),a.baseline.read_bytes(),a.compiler)
    a.output.mkdir(parents=True)
    (a.output/'opengate4k-lab-main.bi').write_bytes(raw)
    (a.output/'opengate4k-lab-main.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Created an emulator-only MAIN payload. No camera update package was generated.')
    print(report['main_sha256'])

if __name__=='__main__':main()

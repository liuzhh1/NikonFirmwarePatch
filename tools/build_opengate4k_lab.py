#!/usr/bin/env python3
"""Build an emulator-only 4K selection/frontend prototype, never a flash package."""
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
    a=p.parse_args()
    if a.output.exists():p.error('Output directory must be new')
    for path in (a.original,a.baseline):
        if not path.is_file() or path.stat().st_size!=99051117:p.error('Complete C3.11 packages required')
    raw,report=make_main(a.original.read_bytes(),a.baseline.read_bytes(),a.compiler)
    a.output.mkdir(parents=True)
    (a.output/'opengate4k-lab-main.bi').write_bytes(raw)
    (a.output/'opengate4k-lab-main.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Created an emulator-only MAIN payload. No camera update package was generated.')
    print(report['main_sha256'])

if __name__=='__main__':main()

#!/usr/bin/env python3
"""Inspect native RAW/coded descriptors in the reviewed laboratory MAIN."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from z8opengate4k.native_buffers import audit_main


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--main', type=Path, required=True)
    parser.add_argument('--output', type=Path, help='New JSON file; existing files are not overwritten')
    args = parser.parse_args()
    if args.output and args.output.exists(): parser.error('Output must be a new file')
    result = audit_main(args.main)
    data = json.dumps(result, indent=2, ensure_ascii=False)+'\n'
    if args.output:
        with args.output.open('x') as stream: stream.write(data)
        print(args.output)
    else: print(data, end='')


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, ImportError) as error: raise SystemExit('ERROR: '+str(error))

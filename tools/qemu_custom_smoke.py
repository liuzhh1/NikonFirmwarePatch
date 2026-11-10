#!/usr/bin/env python3
"""Smoke-test a reviewed custom package using an existing z8-qemu installation.

The original launcher keeps its stock-image admission rules. This adapter first
verifies the complete original/candidate pair against the repository recipes,
then explicitly supplies the candidate MAIN to both QEMU image loaders. Guest
registers, RAM, instruction addresses and hardware models are not rewritten.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verify import decode, verify_pair


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def reviewed_payloads(original, candidate):
    for path in (original, candidate):
        if not path.is_file() or path.stat().st_size != 99051117:
            raise ValueError('Expected complete 99,051,117-byte C3.11 packages')
    old, new = original.read_bytes(), candidate.read_bytes()
    report = verify_pair(old, new)
    # EG includes a final CRC16, which is not part of QEMU's MAIN payload.
    old_main = decode(old)[581844:82389553]
    new_main = decode(new)[581844:82389553]
    if len(old_main) != len(new_main) or len(new_main) != 81807709:
        raise ValueError('Unexpected MAIN payload boundary')
    return old_main, new_main, report


def smoke_summary(result, stderr):
    samples = result.get('pipeline_samples', [])
    last = samples[-1] if samples else {}
    checks = result.get('checks', [])
    checks_pass = bool(checks) and all(row.get('passed') is True for row in checks)
    navigation = result.get('navigation_inputs', [])
    complete = (len(navigation) == 6 and last.get('phase') == 7
                and last.get('raw', {}).get('frames', 0) > 0
                and last.get('lcd', {}).get('frames', 0) > 0)
    passed = (checks_pass and complete and result.get('error') is None
              and result.get('owned_qemu_stopped') is True
              and 'Z8_UNKNOWN' not in stderr)
    return dict(
        status='PASS' if passed else 'FAIL', runtime_assertions=len(checks),
        failed_assertions=sum(row.get('passed') is not True for row in checks),
        navigation_inputs=len(navigation), navigation_completed=complete,
        virtual_seconds=last.get('virtual_seconds'),
        sensor_frames=last.get('raw', {}).get('frames', 0),
        display_frames=last.get('lcd', {}).get('frames', 0),
        unknown_mmio='Z8_UNKNOWN' in stderr,
        owned_qemu_stopped=result.get('owned_qemu_stopped'),
        firmware_sha256=result.get('firmware_sha256'),
        candidate_verification=result.get('reviewed_candidate'),
        scope='Custom MAIN boot, menu/submenu navigation and return to synthetic live view',
        recording_tested=False, open_gate_4k_implemented=False,
        physical_camera_tested=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', required=True, type=Path)
    parser.add_argument('--candidate', required=True, type=Path)
    parser.add_argument('--qemu-repo', required=True, type=Path)
    parser.add_argument('--qemu', required=True, type=Path)
    parser.add_argument('--raw', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--transport-helper', type=Path,
                        help='Optional trusted TCP adapter from the existing QEMU setup')
    parser.add_argument('--seconds', type=int, default=95)
    options = parser.parse_args(argv)
    if not 70 <= options.seconds <= 600:
        parser.error('--seconds must be in 70..600')
    root = options.qemu_repo.resolve()
    for name in ('run.py', 'full_guest.py', 'source-manifest.json'):
        target = root / name if name.endswith('.json') else root / 'tools' / name
        if not target.is_file():
            parser.error('Expected the existing z8-qemu source checkout')
    if options.output.exists():
        parser.error('Output directory must be new')
    stock, custom, report = reviewed_payloads(options.original, options.candidate)
    sys.path.insert(0, str(root / 'tools'))
    import run
    import full_guest
    base_guest = full_guest.Guest
    if options.transport_helper:
        spec = importlib.util.spec_from_file_location('z8_tcp', options.transport_helper.resolve())
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        base_guest = adapter.TCPGuest

    with tempfile.TemporaryDirectory(prefix='z8-reviewed-smoke-') as temporary:
        directory = Path(temporary)
        stock_path, custom_path = directory / 'stock.bi', directory / 'custom.bi'
        stock_path.write_bytes(stock)
        custom_path.write_bytes(custom)
        custom_sha = digest(custom)

        def verify_custom(path):
            if path.resolve() != custom_path or digest(path.read_bytes()) != custom_sha:
                raise ValueError('Candidate MAIN differs from the verified package')
            return custom_path, json.loads((root / 'source-manifest.json').read_text())

        class ReviewedGuest(base_guest):
            def __init__(self, firmware, binary, raw, out):
                # Let the original constructor check its unchanged stock reference.
                super().__init__(stock_path, binary, raw, out)
                if firmware != custom_path:
                    raise ValueError('Unexpected custom firmware path')
                self.command[self.command.index('-kernel') + 1] = str(custom_path)
                self.firmware = custom_path
                self.data.update(
                    firmware_sha256=custom_sha, stock_reference_payload_sha256=digest(stock),
                    reviewed_candidate=report, firmware_image_is_modified=True,
                    custom_smoke_adapter_sha256=digest(Path(__file__).read_bytes()),
                    classification='reviewed_custom_firmware_smoke')

        original_stream = run.run

        def stream_with_budget(guest, seconds, control):
            return original_stream(guest, options.seconds, control)

        run.verify = verify_custom
        run.Guest = ReviewedGuest
        run.run = stream_with_budget
        sys.argv = [str(Path(__file__).resolve()), '--firmware', str(custom_path),
                    '--qemu', str(options.qemu.resolve()), '--raw', str(options.raw.resolve()),
                    '--output', str(options.output.resolve()), '--smoke']
        try:
            run.main()
        finally:
            result_path = options.output / 'result.json'
            if result_path.is_file():
                result = json.loads(result_path.read_text())
                summary = smoke_summary(result, (options.output / 'stderr.log').read_text(errors='replace'))
                (options.output / 'custom-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        if summary['status'] != 'PASS':
            raise RuntimeError('Custom firmware smoke failed; inspect custom-summary.json')
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

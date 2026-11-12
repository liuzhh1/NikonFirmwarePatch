#!/usr/bin/env python3
"""Read-only N-RAW diagnostics with original MAIN/EX and external contacts.

Upstream stock MAIN/EX identity checks remain in force. A .done sibling of
--contact-replay ends through the native runner's normal stop/cleanup path.
This launcher does not accept modified MAIN or host-generated MCU messages.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from z8opengate4k.diagnostics import first_uart_exception


def main():
    parser = argparse.ArgumentParser(description=__doc__, add_help=False, allow_abbrev=False)
    parser.add_argument('--qemu-repo', type=Path, required=True)
    parser.add_argument('--transport-helper', type=Path)
    parser.add_argument('--experimental-movie-selector15', action='store_true')
    parser.add_argument('--experimental-deferred-video-header', action='store_true')
    options, remaining = parser.parse_known_args()
    repo = options.qemu_repo.resolve()
    if not (repo/'tools/run_native.py').is_file():
        parser.error('Existing z8-qemu checkout required')
    # An output controller is needed for the upstream graceful stop event.
    # No interactive buttons are enabled alongside contact replay.
    if not any(item == '--contact-replay' or item.startswith('--contact-replay=') for item in remaining):
        parser.error('An explicit --contact-replay is required')
    if '--native-controls' in remaining:
        parser.error('Native contact replay excludes interactive controls')
    if not any(item == '--port' or item.startswith('--port=') for item in remaining):
        remaining += ['--port', '0']
    sys.path.insert(0, str(repo/'tools'))
    import full_guest
    import control
    import movie_inputs
    import native_contact_replay
    if options.transport_helper:
        spec = importlib.util.spec_from_file_location('og4k_tcp', options.transport_helper.resolve())
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        base_guest = adapter.TCPGuest
    else:
        base_guest = full_guest.Guest
    spec = importlib.util.spec_from_file_location('og4k_native_replay', ROOT/'experiments/qemu/native_replay.py')
    replay_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay_module)
    active = {}
    native_contact_replay.ContactReplay = replay_module.replay_class(native_contact_replay.ContactReplay, active)
    base_control = control.Control

    def sample(g):
        names = ('engine1543-control-state', 'capture-nv16-pipeline-state',
                 'raw-pipeline-state', 'engine150c-state', 'primary-d980-state',
                 'video-secondary-isp-state', 'video-secondary-sensor-state')
        state = {}
        for name in names:
            try:
                state[name] = json.loads(g.qmp.command('qom-get', path='/machine', property=name))
            except (RuntimeError, ValueError) as error:
                state[name] = {'unavailable': str(error)}
        state['file_type'] = int.from_bytes(g.read_bytes(0xa03d5c014, 4), 'little')
        return state

    class NativeGuest(base_guest):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            active['guest'] = self
            self.data['native_observation'] = dict(
                read_only_guest=True, host_mcu_messages=False, recording_verified=False)

        def __exit__(self, kind, error, traceback):
            if self.qmp and self.proc and self.proc.poll() is None:
                try:
                    if active.get('replay'):
                        active['replay'].cancel(self.qmp)
                        self.data['native_contact_progress'] = dict(
                            delivered=active['replay'].next, total=len(active['replay'].actions))
                    self.qmp.command('stop')
                    self.data['og_native_diagnostics'] = sample(self)
                except Exception as diagnostic_error:
                    self.data['og_native_diagnostics_error'] = repr(diagnostic_error)
            try:
                return super().__exit__(kind, error, traceback)
            finally:
                uart = self.out/'uart-tx.log'
                if (self.out/'result.json').is_file() and uart.is_file():
                    self.data['primary_exception'] = first_uart_exception(uart.read_text(errors='replace'))
                    (self.out/'result.json').write_text(json.dumps(self.data, indent=2)+'\n')

    class NativeControl(base_control):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            active['control'] = self

        def publish(self, frame, row, ready):
            # run_native pauses the VM before publishing: sample one coherent
            # configuration without changing guest code, registers or RAM.
            g = active['guest']
            diagnostic = sample(g)
            diagnostic['virtual_seconds'] = row['virtual_seconds']
            diagnostic['contacts_delivered'] = active['replay'].next
            header = diagnostic['engine1543-control-state']
            video_input = header.get('video_input', {})
            state = dict(file_type=diagnostic['file_type'],
                source2_control=video_input['source2'].get('0x30', 0) if 'source2' in video_input else None,
                isp1_config_0x218=video_input['isp1'].get('0x218', 0) if 'isp1' in video_input else None,
                primary_active=diagnostic['engine150c-state'].get('active'),
                early_header=header.get('early_video'),
                d980_submits=diagnostic['primary-d980-state'].get('submits'))
            # Save control transitions, not every frame. This establishes the
            # ordering around a contact without inferring cause from two snapshots.
            if state != active.get('last_state'):
                active['last_state'] = state
                history = g.data.setdefault('og_native_transitions', [])
                if len(history) < 2048:
                    history.append(dict(virtual_seconds=row['virtual_seconds'],
                                        contacts_delivered=active['replay'].next, **state))
                else:
                    g.data['og_native_transitions_dropped'] = g.data.get('og_native_transitions_dropped', 0)+1
            (g.out/'native-observation.json').write_text(json.dumps(diagnostic, indent=2)+'\n')
            super().publish(frame, row, ready)

    full_guest.Guest = NativeGuest
    control.Control = NativeControl
    original_attach = movie_inputs.attach

    def attach(g, args):
        if options.experimental_movie_selector15 or options.experimental_deferred_video_header:
            if not (movie_inputs.native_modes_enabled(args) and args.experimental_movie_selector10):
                raise ValueError('N-RAW observation options require the complete Movie profile and selector10')
        original_attach(g, args)
        if options.experimental_movie_selector15:
            selector = g.out/'experimental-selector15.bin'
            selector.write_bytes(b'\x01')
            g.command += ['-device', f'loader,file={selector},addr=0x47f5af4f,force-raw=on']
            g.data['experimental_movie_selector15'] = dict(address='0x47f5af4f', value=1, factory_calibration=False)
        if options.experimental_deferred_video_header:
            g.command[g.command.index('-M')+1] += ',og4k-header-model=on'
            g.data['experimental_header_latch'] = dict(enabled=True, hardware_model_modified=True, physical_verified=False)
    movie_inputs.attach = attach
    sys.argv = [str(repo/'tools/run_native.py'), *remaining]
    runpy.run_path(str(repo/'tools/run_native.py'), run_name='__main__')


if __name__ == '__main__':
    main()

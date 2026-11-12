# SPDX-License-Identifier: GPL-2.0-or-later
"""Append-only replay adapter for original EX external contacts."""
from pathlib import Path

# Qualified momentary contacts only; Photo/Movie is a retained selector.
MOMENTARY = {'mcu-pins': {'G1'}, 'mcu-contacts': {
    '22.12', '23.5', '23.6', '23.7', '23.8', '23.9',
    '23.11', '23.12', '23.13', '23.14', '23.15', '23.18'}}


def replay_class(base, active):
    class Replay(base):
        def __init__(self, path):
            super().__init__(path)
            self.path = Path(path)
            self.held = set()
            active['replay'] = self

        def refresh(self):
            candidate = base(self.path).actions
            if candidate[:len(self.actions)] != self.actions:
                raise ValueError('Native contact replay is append-only')
            self.actions = candidate

        def dispatch(self, qmp, virtual_seconds):
            self.refresh()
            if self.path.with_suffix('.done').exists():
                self.cancel(qmp)
                active['control'].stop.set()
                active['guest'].data['native_observation_stop'] = {
                    'reason': 'explicit_done_file', 'virtual_seconds': virtual_seconds,
                    'delivered': self.next, 'total': len(self.actions)}
                return []
            sent = super().dispatch(qmp, virtual_seconds)
            for row in sent:
                for value in row['value'].split(':'):
                    contact, level = value.split('=')
                    key = row['property'], contact
                    if contact in MOMENTARY.get(row['property'], ()):
                        if level == '0':
                            self.held.add(key)
                        else:
                            self.held.discard(key)
            active['guest'].data['native_contact_actions'] = self.actions
            return sent

        def cancel(self, qmp):
            for prop, contact in sorted(self.held):
                qmp.command('qom-set', path='/machine', property=prop, value=contact+'=1')
            if self.held:
                active['guest'].data.setdefault('native_contact_cancellations', []).append(
                    {'released': [list(key) for key in sorted(self.held)],
                     'original_ex_acknowledgement_verified': False})
            self.held.clear()
    return Replay

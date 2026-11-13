#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check original-EX contact replay safety using the upstream validator."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--qemu-repo', type=Path, required=True)
args, rest = parser.parse_known_args()
sys.argv = [sys.argv[0], *rest]
sys.path.insert(0, str(args.qemu_repo/'tools'))
from native_contact_replay import ContactReplay
from native_replay import replay_class


class QMP:
    def __init__(self):
        self.writes = []

    def command(self, command, **kwargs):
        assert command == 'qom-set' and kwargs['path'] == '/machine'
        self.writes.append((kwargs['property'], kwargs['value']))


class NativeReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'controls.json'
        self.active = dict(guest=SimpleNamespace(data={}), control=SimpleNamespace(stop=threading.Event()))
        self.qmp = QMP()

    def write(self, rows):
        self.path.write_text(json.dumps(rows))

    def row(self, at, value, prop='mcu-contacts'):
        return dict(at=at, property=prop, value=value)

    def start(self, rows):
        self.write(rows)
        return replay_class(ContactReplay, self.active)(self.path)

    def test_appended_record_contact_uses_only_external_input(self):
        rows = [self.row(1, '23.6=0'), self.row(1.4, '23.6=1')]
        replay = self.start(rows)
        replay.dispatch(self.qmp, 2)
        rows += [self.row(3, '22.12=0'), self.row(3.4, '22.12=1')]
        self.write(rows)
        self.assertEqual(len(replay.dispatch(self.qmp, 4)), 2)
        self.assertEqual(self.qmp.writes[-2:], [('mcu-contacts', '22.12=0'), ('mcu-contacts', '22.12=1')])
        self.assertFalse(replay.held)
        self.assertEqual(self.active['guest'].data['native_contact_actions'], rows)

    def test_changed_consumed_or_future_controls_are_rejected_before_writes(self):
        rows = [self.row(1, '23.6=0'), self.row(4, '23.6=1')]
        replay = self.start(rows)
        replay.dispatch(self.qmp, 2)
        before = list(self.qmp.writes)
        for index in (0, 1):
            changed = [dict(row) for row in rows]
            changed[index]['value'] = '22.12=0'
            self.write(changed)
            with self.assertRaisesRegex(ValueError, 'append-only'):
                replay.dispatch(self.qmp, 5)
            self.assertEqual(self.qmp.writes, before)

    def test_done_releases_momentary_input_without_changing_movie_selector(self):
        replay = self.start([self.row(1, 'G1=0', 'mcu-pins'), self.row(1.1, '23.10=0'), self.row(4, '22.12=0')])
        replay.dispatch(self.qmp, 2)
        self.path.with_suffix('.done').touch()
        self.assertEqual(replay.dispatch(self.qmp, 5), [])
        self.assertTrue(self.active['control'].stop.is_set())
        self.assertEqual(self.qmp.writes[-1], ('mcu-pins', 'G1=1'))
        self.assertEqual(replay.next, 2)
        self.assertNotIn(('mcu-contacts', '23.10=1'), self.qmp.writes)
        before = list(self.qmp.writes)
        replay.cancel(self.qmp)
        self.assertEqual(self.qmp.writes, before)
        self.assertFalse(self.active['guest'].data['native_contact_cancellations'][0]['original_ex_acknowledgement_verified'])

    def test_invalid_appended_batch_is_rejected_atomically(self):
        rows = [self.row(1, '23.6=1')]
        replay = self.start(rows)
        self.write(rows+[self.row(2, '22.12=0:RAM=1')])
        with self.assertRaises(ValueError):
            replay.dispatch(self.qmp, 3)
        self.assertEqual(self.qmp.writes, [])


if __name__ == '__main__':
    unittest.main()

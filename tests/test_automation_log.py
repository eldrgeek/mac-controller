#!/usr/bin/env python3
"""Tests for automation_log.py — no Claude Desktop, no real input, temp log dir only.

Run: python3 tests/test_automation_log.py   (or python3 -m unittest tests.test_automation_log)
"""
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import automation_log as al  # noqa: E402


def _lines(d):
    with open(os.path.join(d, 'actions.jsonl')) as fh:
        return [json.loads(x) for x in fh if x.strip()]


class LoggerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {'SOMA_AUTOMATION_LOG_DIR': self.tmp.name,
                                                'SOMA_AUTOMATION_LOG': '1'})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_record_writes_one_line_with_schema(self):
        with mock.patch.dict(os.environ, {'SOMA_SESSION_ID': 'sess-1'}):
            al.record('ax_press', target='Claude', duration_ms=12.7, actor='cc.py', ok=True)
        (line,) = _lines(self.tmp.name)
        self.assertEqual(line['actor'], 'cc.py')
        self.assertEqual(line['kind'], 'ax_press')
        self.assertEqual(line['target'], 'Claude')
        self.assertEqual(line['duration_ms'], 12)
        self.assertEqual(line['session_id'], 'sess-1')
        self.assertEqual(line['pid'], os.getpid())
        self.assertTrue(line['ts'].endswith('Z'))

    def test_target_url_reduced_to_host_no_query(self):
        al.record('step:navigate', target='https://user:pw@example.com/a/b?token=SECRET#x', actor='t')
        (line,) = _lines(self.tmp.name)
        self.assertEqual(line['target'], 'example.com')
        self.assertNotIn('SECRET', json.dumps(line))

    def test_disabled_writes_nothing(self):
        with mock.patch.dict(os.environ, {'SOMA_AUTOMATION_LOG': '0'}):
            self.assertIsNone(al.record('key'))
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, 'actions.jsonl')))

    def test_failure_is_swallowed(self):
        with mock.patch.object(al.os, 'open', side_effect=OSError('disk full')):
            self.assertIsNone(al.record('key', actor='t'))

    def test_rotates_previous_day(self):
        path = os.path.join(self.tmp.name, 'actions.jsonl')
        with open(path, 'w') as fh:
            fh.write(json.dumps({'ts': '2020-01-01T00:00:00.000Z', 'actor': 'x', 'kind': 'k'}) + '\n')
        al.record('key', actor='t')
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, 'actions-2020-01-01.jsonl')))
        self.assertEqual(len(_lines(self.tmp.name)), 1)

    def test_rotates_on_size_cap(self):
        al.record('key', actor='t')
        with mock.patch.object(al, 'MAX_BYTES', 1):
            al.record('key', actor='t')
        rotated = [f for f in os.listdir(self.tmp.name) if f.startswith('actions-')]
        self.assertEqual(len(rotated), 1)

    def test_selftest_is_dry_run(self):
        with mock.patch('builtins.print'):
            self.assertEqual(al.main(['selftest']), 0)
        (line,) = _lines(self.tmp.name)
        self.assertTrue(line['dry_run'])


class InstallTest(unittest.TestCase):
    """Wrap fake PyObjC modules and prove each primitive logs exactly one line."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {'SOMA_AUTOMATION_LOG_DIR': self.tmp.name,
                                                'SOMA_AUTOMATION_LOG': '1'})
        self.env.start()
        self.AS = types.ModuleType('ApplicationServices')
        self.AS.AXUIElementPerformAction = lambda elem, action: 0
        self.AS.AXUIElementSetAttributeValue = lambda elem, attr, value: 0
        self.AS.AXUIElementGetPid = lambda elem, _: (0, 4242)
        self.Q = types.ModuleType('Quartz')
        self.Q.posted = []
        self.Q.CGEventPost = lambda tap, ev: self.Q.posted.append(ev)
        self.Q.CGEventGetType = lambda ev: ev['type']
        self.AK = types.ModuleType('AppKit')
        app = mock.MagicMock()
        app.localizedName.return_value = 'Claude'
        self.AK.NSRunningApplication = mock.MagicMock()
        self.AK.NSRunningApplication.runningApplicationWithProcessIdentifier_.return_value = app
        self.AK.NSWorkspace = mock.MagicMock()
        self.AK.NSWorkspace.sharedWorkspace.return_value.frontmostApplication.return_value = app
        al._pid_names.clear()
        self.assertTrue(al.install(self.AS, self.Q, self.AK, actor='cc.py'))

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_ax_press_and_set_value(self):
        self.assertEqual(self.AS.AXUIElementPerformAction(object(), 'AXPress'), 0)
        self.AS.AXUIElementSetAttributeValue(object(), 'AXValue', 'typed secret text')
        lines = _lines(self.tmp.name)
        self.assertEqual([l['kind'] for l in lines], ['ax_press', 'ax_set_value'])
        self.assertEqual({l['target'] for l in lines}, {'Claude'})
        self.assertNotIn('typed secret text', json.dumps(lines))

    def test_key_down_up_is_one_line(self):
        self.Q.CGEventPost(0, {'type': 10})
        self.Q.CGEventPost(0, {'type': 11})
        lines = _lines(self.tmp.name)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['kind'], 'key')
        self.assertEqual(len(self.Q.posted), 2)

    def test_install_is_idempotent_and_skips_mocks(self):
        self.assertTrue(al.install(self.AS, self.Q, self.AK))
        self.assertFalse(al.install(mock.MagicMock(), mock.MagicMock(), mock.MagicMock()))

    def test_logging_error_never_breaks_action(self):
        with mock.patch.object(al, 'record', side_effect=RuntimeError('boom')):
            self.assertEqual(self.AS.AXUIElementPerformAction(object(), 'AXPress'), 0)


if __name__ == '__main__':
    unittest.main(verbosity=1)

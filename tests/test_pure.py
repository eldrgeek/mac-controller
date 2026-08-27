#!/usr/bin/env python3
"""Unit tests for pure functions — no Claude Desktop required."""
import inspect
import io
import json
import os
import stat
import sys
import tempfile
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for mod in ['ApplicationServices', 'AppKit', 'Quartz']:
    sys.modules[mod] = mock.MagicMock()

from claude_ax import (
    parse_task_status, TASK_STATUSES, _SECTION_FILTER_LABELS,
    _COMPOSER_PLACEHOLDERS, is_empty_composer_text,
    new_task, new_task_matchers, click_first_match,
    run as ax_run, cowork_safe_inject,
)
import afk_guard
import cc


def check(name, got, expected):
    ok = got == expected
    mark = "OK" if ok else "FAIL"
    print(f"  [{mark}] {name}")
    if not ok:
        print(f"         expected: {expected!r}")
        print(f"         got:      {got!r}")
    return ok


def check_true(name, cond):
    return check(name, bool(cond), True)


class _Args:
    """Minimal argparse-like namespace for cmd_* tests."""
    def __init__(self, **kw):
        self.no_afk_guard = False
        self.session = None
        self.new = False
        self.save_restore = False
        self.cowork_safe = False
        self.clobber = False
        self.no_dispatch = False
        self.list = False
        self.status = None
        self.pick = None
        self.inject = None
        self.timeout = 30
        self.reason = ''
        self.what = 'mode'
        self.mode = 'chat'
        self.message = 'hello'
        self.ax = False
        self.__dict__.update(kw)


def run():
    results = []

    print("\n=== parse_task_status ===")
    cases = [
        ("Running Foo bar",           ("running",        "Foo bar")),
        ("Done LLMs4",                ("done",           "LLMs4")),
        ("Ready Url ingest",          ("ready",          "Url ingest")),
        ("Scheduled Daily report",    ("scheduled",      "Daily report")),
        ("Awaiting input Tab minder", ("awaiting input", "Tab minder")),
        ("Dispatch Build pipeline",   ("dispatch",       "Build pipeline")),
        ("Mac automation scripts",    (None,             "Mac automation scripts")),
        ("New task \u2318N",          (None,             "New task \u2318N")),
        ("Scheduled",                 (None,             "Scheduled")),
        ("",                          (None,             "")),
        ("Waiting for Running task",  (None,             "Waiting for Running task")),
        ("RunningTask",               (None,             "RunningTask")),
    ]
    for title, expected in cases:
        results.append(check(repr(title), parse_task_status(title), expected))

    print("\n=== _SECTION_FILTER_LABELS ===")
    for label in ['Scheduled', 'Live artifacts', 'Dispatch', 'Customize',
                  'Projects', 'Pinned', 'Recents', 'View all', 'New task \u2318N',
                  'New session \u2318N', 'New']:
        results.append(check(f"{label!r} excluded", label in _SECTION_FILTER_LABELS, True))

    print("\n=== TASK_STATUSES completeness ===")
    for s in ('Running', 'Done', 'Ready', 'Scheduled', 'Awaiting input', 'Dispatch'):
        results.append(check(f"{s!r} in TASK_STATUSES", s in TASK_STATUSES, True))

    print("\n=== composer placeholders / is_empty_composer_text ===")
    results.append(check_true("'reply...' in set", 'reply...' in _COMPOSER_PLACEHOLDERS))
    results.append(check_true("'write a message…' in set",
                              'write a message\u2026' in _COMPOSER_PLACEHOLDERS))
    results.append(check("empty string", is_empty_composer_text(''), True))
    results.append(check("Reply...", is_empty_composer_text('Reply...'), True))
    results.append(check("Reply…", is_empty_composer_text('Reply\u2026'), True))
    results.append(check("Write a message…", is_empty_composer_text('Write a message\u2026'), True))
    results.append(check("Write a message...", is_empty_composer_text('Write a message...'), True))
    results.append(check("placeholder match", is_empty_composer_text('Hint', 'Hint'), True))
    results.append(check("real draft", is_empty_composer_text('Ship it tomorrow'), False))
    results.append(check("whitespace draft stripped empty",
                         is_empty_composer_text('   '), True))

    print("\n=== cowork_safe_inject uses shared empty detection ===")
    # Placeholder must NOT notify / pbcopy. Real draft must.
    notify_calls = []
    pb_calls = []

    def fake_notify(title, body):
        notify_calls.append((title, body))

    def fake_run(cmd, **kw):
        pb_calls.append(cmd)
        return mock.MagicMock(returncode=0)

    with mock.patch('claude_ax.get_composer_state',
                    return_value={'draft_text': '', 'has_text_area': True}), \
         mock.patch('claude_ax.set_prompt_text', return_value=True) as set_text, \
         mock.patch('claude_ax.submit_prompt', return_value=True), \
         mock.patch('claude_ax._notify', fake_notify), \
         mock.patch('subprocess.run', fake_run):
        ok = cowork_safe_inject('win', 'new msg', dispatch=True)
    results.append(check("placeholder inject ok", ok, True))
    results.append(check("placeholder does not notify", notify_calls, []))
    results.append(check("placeholder does not pbcopy", pb_calls, []))
    results.append(check("placeholder still sets text", set_text.call_count, 1))

    notify_calls.clear()
    pb_calls.clear()
    with mock.patch('claude_ax.get_composer_state',
                    return_value={'draft_text': 'half-written prompt', 'has_text_area': True}), \
         mock.patch('claude_ax.set_prompt_text', return_value=True), \
         mock.patch('claude_ax.submit_prompt', return_value=True), \
         mock.patch('claude_ax._notify', fake_notify), \
         mock.patch('subprocess.run', fake_run):
        ok = cowork_safe_inject('win', 'new msg', dispatch=False)
    results.append(check("real draft inject ok", ok, True))
    results.append(check_true("real draft notifies", len(notify_calls) == 1))
    results.append(check_true("real draft pbcopy", pb_calls == [['pbcopy']]))

    print("\n=== new_task matchers (New fallback, no ⌘N keystroke) ===")
    cowork_m = new_task_matchers('cowork')
    code_m = new_task_matchers('code')
    chat_m = new_task_matchers('chat')
    results.append(check("cowork first title", cowork_m[0].get('title'), 'New task \u2318N'))
    results.append(check("cowork fallback New", cowork_m[1].get('title'), 'New'))
    results.append(check("code first title", code_m[0].get('title'), 'New session \u2318N'))
    results.append(check("code fallback New", code_m[1].get('title'), 'New'))
    results.append(check("chat first contains", chat_m[0].get('contains'), 'New chat'))
    results.append(check("chat fallback New", chat_m[1].get('title'), 'New'))

    src = inspect.getsource(new_task)
    results.append(check_true("new_task source has no osascript", 'osascript' not in src))
    results.append(check_true("new_task has no System Events ⌘N fallback",
                              'using command down' not in src))
    results.append(check_true("new_task uses click_first_match", 'click_first_match' in src))

    print("\n=== new_task honest bool (click fail → False, no keystroke) ===")
    osascript_calls = []

    def spy_run(*a, **k):
        osascript_calls.append(a)
        return mock.MagicMock(returncode=0)

    with mock.patch('claude_ax.infer_current_mode', return_value='cowork'), \
         mock.patch('claude_ax.click_first_match', return_value=False) as click, \
         mock.patch('claude_ax.find_nav_buttons', return_value=[]), \
         mock.patch('claude_ax.time.sleep'), \
         mock.patch('subprocess.run', spy_run):
        ok = new_task('win')
    results.append(check("click fail returns False", ok, False))
    results.append(check("osascript_calls == 0 on click fail", len(osascript_calls), 0))
    results.append(check_true("click_first_match used New matchers",
                              click.call_args[0][1][1].get('title') == 'New'))

    # Click succeeds, sidebar fingerprint changes → True
    nav_changed = iter([
        [{'title': 'Old', 'selected': True}],
        [{'title': 'Old', 'selected': False}, {'title': 'Untitled', 'selected': True}],
    ])
    with mock.patch('claude_ax.infer_current_mode', return_value='cowork'), \
         mock.patch('claude_ax.click_first_match', return_value=True), \
         mock.patch('claude_ax.find_nav_buttons',
                    side_effect=lambda win: next(nav_changed)), \
         mock.patch('claude_ax.time.sleep'), \
         mock.patch('subprocess.run', spy_run):
        ok = new_task('win')
    results.append(check("sidebar change returns True", ok, True))

    # Click succeeds, sidebar unchanged → False (honest)
    nav_same = iter([
        [{'title': 'Old', 'selected': True}],
        [{'title': 'Old', 'selected': True}],
    ])
    with mock.patch('claude_ax.infer_current_mode', return_value='chat'), \
         mock.patch('claude_ax.click_first_match', return_value=True), \
         mock.patch('claude_ax.find_nav_buttons',
                    side_effect=lambda win: next(nav_same)), \
         mock.patch('claude_ax.time.sleep'), \
         mock.patch('subprocess.run', spy_run):
        ok = new_task('win')
    results.append(check("unchanged sidebar returns False", ok, False))
    results.append(check("still no osascript after success paths", len(osascript_calls), 0))

    print("\n=== click_first_match silent intermediate miss ===")
    pressed = []
    elem = object()

    def fake_find(win, **kw):
        if kw.get('title') == 'New task \u2318N':
            return None
        if kw.get('title') == 'New':
            return {'elem': elem, 'title': 'New', 'role': 'AXButton'}
        return None

    with mock.patch('claude_ax.find_control', side_effect=fake_find), \
         mock.patch('claude_ax.AS.AXUIElementPerformAction',
                    lambda e, a: pressed.append((e, a))):
        buf = io.StringIO()
        with mock.patch('sys.stderr', buf):
            ok = click_first_match('win', new_task_matchers('cowork'))
    results.append(check("first-match New succeeds", ok, True))
    results.append(check("pressed the New elem", pressed, [(elem, 'AXPress')]))
    results.append(check("no ERROR on intermediate miss", buf.getvalue(), ''))

    print("\n=== claude_ax.run() refuses (no silent inject bypass) ===")
    buf = io.StringIO()
    with mock.patch('sys.stderr', buf):
        rc = ax_run(['hello there'])
    results.append(check("run() exit 2", rc, 2))
    results.append(check_true("run() points at cc.py", 'cc.py inject' in buf.getvalue()))

    print("\n=== hud-ask does not call :3334 ===")
    opened = []
    captured_hud = []

    class FakeResp:
        def __init__(self, payload):
            self._payload = json.dumps(payload).encode()
        def read(self):
            return self._payload

    def url_of(req):
        if isinstance(req, str):
            return req
        return getattr(req, 'full_url', None) or getattr(req, 'get_full_url', lambda: '')()

    def fake_urlopen(req, timeout=None):
        url = url_of(req)
        opened.append(url)
        if '/hud/ask' in url:
            return FakeResp({'id': 'ask1'})
        if '/hud/response/' in url:
            return FakeResp({'status': 'pending'})
        raise AssertionError(f'unexpected urlopen {url}')

    with mock.patch('urllib.request.urlopen', fake_urlopen), \
         mock.patch.object(cc, '_print', lambda obj: captured_hud.append(obj)):
        rc = cc.cmd_hud_ask(_Args(message='ping', timeout=0))
    results.append(check("hud-ask timeout exit 3", rc, 3))
    results.append(check("hud-ask timeout payload", captured_hud[-1].get('response'), 'timeout'))
    results.append(check_true("hud-ask POSTed relay /hud/ask",
                              any(':3333/hud/ask' in u for u in opened)))
    results.append(check("hud-ask never touched :3334",
                         any(':3334' in u for u in opened), False))
    hud_src = inspect.getsource(cc.cmd_hud_ask) + inspect.getsource(cc.cmd_status)
    results.append(check_true("no localhost:3334 in hud-ask/status",
                              'localhost:3334' not in hud_src))
    results.append(check_true("no /wv-status in hud-ask/status",
                              '/wv-status' not in hud_src))
    results.append(check_true("no :3334/show in hud-ask/status",
                              '3334/show' not in hud_src))

    # Relay down → error mapping, still no :3334
    opened.clear()
    captured_hud.clear()

    def boom(req, timeout=None):
        opened.append(url_of(req))
        raise OSError('timed out')

    with mock.patch('urllib.request.urlopen', boom):
        def cap(obj):
            captured_hud.append(obj)
        with mock.patch.object(cc, '_print', cap):
            rc = cc.cmd_hud_ask(_Args(message='ping', timeout=1))
    results.append(check("hud-ask relay error exit 3", rc, 3))
    results.append(check_true("hud-ask error mentions HUD not reachable",
                              'HUD not reachable' in captured_hud[-1].get('error', '')))
    results.append(check("error path never touched :3334",
                         any(':3334' in u for u in opened), False))

    # Answered confirm
    opened.clear()
    captured_hud.clear()

    def answered(req, timeout=None):
        url = url_of(req)
        opened.append(url)
        if '/hud/ask' in url:
            return FakeResp({'id': 'ask1'})
        return FakeResp({'status': 'answered', 'response': 'confirm'})

    with mock.patch('urllib.request.urlopen', answered):
        def cap(obj):
            captured_hud.append(obj)
        with mock.patch.object(cc, '_print', cap):
            rc = cc.cmd_hud_ask(_Args(message='ping', timeout=5))
    results.append(check("hud-ask confirm exit 0", rc, 0))
    results.append(check("hud-ask confirm payload", captured_hud[-1], {'response': 'confirm'}))

    print("\n=== cc status shape (relay/pulse, no dead overlay) ===")
    json_calls = []

    def fake_json(url, timeout=1.5):
        json_calls.append(url)
        if url == f'{cc.RELAY_URL}/status':
            return {'ok': True, 'extensionConnected': True}, None
        if url.startswith(f'{cc.RELAY_URL}/jobs/status'):
            return {'jobs': []}, None
        if url == f'{cc.RELAY_URL}/chat/status':
            return {'available': False}, None
        if url == f'{cc.RELAY_URL}/hud/asks':
            return {'asks': [{'id': 'a', 'message': 'x', 'createdAt': 1, 'ageSeconds': 0}]}, None
        if ':3334' in url:
            raise AssertionError('status must not fetch :3334')
        return None, f'unexpected {url}'

    def fake_reach(url, timeout=1.5):
        if url == cc.PULSE_URL:
            return True, None
        return False, 'no'

    captured = []
    with mock.patch.object(cc, 'find_claude_window', return_value=None), \
         mock.patch.object(cc, 'is_claude_frontmost', return_value=False), \
         mock.patch.object(cc, '_http_json', fake_json), \
         mock.patch.object(cc, '_http_reachable', fake_reach), \
         mock.patch.object(cc, '_print', lambda obj: captured.append(obj)):
        rc = cc.cmd_status(_Args())
    data = captured[-1]
    results.append(check("status exit 0", rc, 0))
    results.append(check_true("status has relay", 'relay' in data))
    results.append(check_true("status has pulse", 'pulse' in data))
    results.append(check_true("status has hud", 'hud' in data))
    results.append(check("relay.up True", data['relay']['up'], True))
    results.append(check("pulse.up True", data['pulse']['up'], True))
    results.append(check("hud.up True (ask surface / relay)", data['hud']['up'], True))
    results.append(check("hud.surface is pulse", data['hud']['surface'], 'pulse'))
    results.append(check("hud.pending_asks", data['hud']['pending_asks'], 1))
    results.append(check("hud has no overlay loaded key from :3334",
                         'loaded' in data['hud'], False))
    results.append(check("no :3334 in json fetches",
                         any(':3334' in u for u in json_calls), False))

    # Timeout / connection-refused mapping
    captured.clear()
    json_calls.clear()

    def down_json(url, timeout=1.5):
        json_calls.append(url)
        return None, "timed out"

    def down_reach(url, timeout=1.5):
        return False, "Connection refused"

    with mock.patch.object(cc, 'find_claude_window', return_value=None), \
         mock.patch.object(cc, 'is_claude_frontmost', return_value=False), \
         mock.patch.object(cc, '_http_json', down_json), \
         mock.patch.object(cc, '_http_reachable', down_reach), \
         mock.patch.object(cc, '_print', lambda obj: captured.append(obj)):
        rc = cc.cmd_status(_Args())
    data = captured[-1]
    results.append(check("down relay.up False", data['relay']['up'], False))
    results.append(check("down pulse.up False", data['pulse']['up'], False))
    results.append(check("down hud.up False", data['hud']['up'], False))
    results.append(check_true("down hud.error set", bool(data['hud'].get('error'))))
    results.append(check("down path still no :3334",
                         any(':3334' in u for u in json_calls), False))

    print("\n=== _ask_surface / _http_reachable mapping ===")
    hud = cc._ask_surface({'up': True}, {'up': True}, pending_asks=0, asks_err=None)
    results.append(check("ask surface up when relay up", hud['up'], True))
    hud = cc._ask_surface({'up': False, 'error': 'Connection refused'}, {'up': False},
                          asks_err='Connection refused')
    results.append(check("ask surface down on connection refused", hud['up'], False))
    hud = cc._ask_surface({'up': True}, {'up': False}, pending_asks=None,
                          asks_err='timed out')
    results.append(check("asks timeout flips hud.up False", hud['up'], False))
    results.append(check("asks timeout error recorded", hud.get('error'), 'timed out'))
    # Pixel-only: pulse down must not force hud.up False if asks succeeded
    hud = cc._ask_surface({'up': True}, {'up': False}, pending_asks=0, asks_err=None)
    results.append(check("pulse down does not zero hud.up", hud['up'], True))
    results.append(check("pulse_up reported separately", hud.get('pulse_up'), False))

    results.append(check_true("_http_reachable callable", callable(cc._http_reachable)))

    import urllib.error as _ue

    def raise_404(url, timeout=1.5):
        raise _ue.HTTPError(url, 404, 'no', hdrs=None, fp=None)

    with mock.patch('urllib.request.urlopen', raise_404):
        ok, err = cc._http_reachable('http://localhost:8088/')
    results.append(check("HTTP 404 still counts as reachable", ok, True))

    def raise_timeout(url, timeout=1.5):
        raise TimeoutError('timed out')

    with mock.patch('urllib.request.urlopen', raise_timeout):
        ok, err = cc._http_reachable('http://localhost:8088/')
    results.append(check("timeout is not reachable", ok, False))
    results.append(check_true("timeout error string", 'timed out' in (err or '')))

    print("\n=== AFK gating on mutating commands ===")
    def refuse():
        raise afk_guard.AfkGuardError('refused: user active')

    captured.clear()
    with mock.patch.object(cc.afk_guard, 'require_team_control', refuse), \
         mock.patch.object(cc, 'find_claude_window') as fw, \
         mock.patch.object(cc, '_print', lambda obj: captured.append(obj)):
        rc = cc.cmd_inject(_Args(message='hi'))
    results.append(check("inject refused exit 1", rc, 1))
    results.append(check_true("inject refused error", 'refused' in captured[-1].get('error', '')))
    results.append(check("inject did not open Claude window", fw.called, False))

    captured.clear()
    with mock.patch.object(cc.afk_guard, 'require_team_control', refuse), \
         mock.patch.object(cc, 'find_claude_window') as fw, \
         mock.patch.object(cc, '_print', lambda obj: captured.append(obj)):
        rc = cc.cmd_mode(_Args(mode='cowork'))
    results.append(check("mode refused exit 1", rc, 1))
    results.append(check("mode did not open window", fw.called, False))

    captured.clear()
    with mock.patch.object(cc.afk_guard, 'require_team_control', refuse), \
         mock.patch.object(cc, 'find_claude_window') as fw, \
         mock.patch.object(cc, '_print', lambda obj: captured.append(obj)):
        rc = cc.cmd_new_task(_Args())
    results.append(check("new-task refused exit 1", rc, 1))
    results.append(check("new-task did not open window", fw.called, False))

    # recent --pick is mutating; recent --list is not
    captured.clear()
    fake_tasks = [{'title': 'Running Foo', 'status': 'running',
                   'clean_title': 'Foo', 'selected': False, 'elem': object()}]
    with mock.patch.object(cc.afk_guard, 'require_team_control', refuse), \
         mock.patch.object(cc, '_require_window', return_value='win'), \
         mock.patch.object(cc, 'list_tasks', return_value=fake_tasks), \
         mock.patch.object(cc, '_print', lambda obj: captured.append(obj)):
        rc = cc.cmd_recent(_Args(list=True, pick=None))
    results.append(check("recent --list ungated exit 0", rc, 0))

    captured.clear()
    with mock.patch.object(cc.afk_guard, 'require_team_control', refuse), \
         mock.patch.object(cc, '_require_window', return_value='win'), \
         mock.patch.object(cc, 'list_tasks', return_value=fake_tasks), \
         mock.patch.object(cc.AS, 'AXUIElementPerformAction') as press, \
         mock.patch.object(cc, '_print', lambda obj: captured.append(obj)):
        rc = cc.cmd_recent(_Args(pick='Foo'))
    results.append(check("recent --pick refused exit 1", rc, 1))
    results.append(check("recent --pick did not click", press.called, False))

    # inspect stays ungated
    captured.clear()
    req = mock.MagicMock()
    with mock.patch.object(cc.afk_guard, 'require_team_control', req), \
         mock.patch.object(cc, '_require_window', return_value='win'), \
         mock.patch.object(cc, '_content_root', return_value='root'), \
         mock.patch.object(cc, 'infer_current_mode', return_value='chat'), \
         mock.patch.object(cc, '_print', lambda obj: captured.append(obj)):
        rc = cc.cmd_inspect(_Args(what='mode'))
    results.append(check("inspect ungated exit 0", rc, 0))
    results.append(check("inspect did not call require_team_control", req.called, False))

    # --no-afk-guard opt-out
    captured.clear()
    with mock.patch.object(cc.afk_guard, 'require_team_control', refuse), \
         mock.patch.object(cc, '_notify'), \
         mock.patch.object(cc, '_require_window', return_value='win'), \
         mock.patch.object(cc, '_content_root', return_value='root'), \
         mock.patch.object(cc, 'cowork_safe_inject', return_value=True), \
         mock.patch.object(cc, '_print', lambda obj: captured.append(obj)), \
         mock.patch('sys.stderr', io.StringIO()):
        rc = cc.cmd_inject(_Args(message='hi', no_afk_guard=True))
    results.append(check("--no-afk-guard inject proceeds", rc, 0))

    # CC_SKIP_AFK_GUARD=1 opt-out
    captured.clear()
    with mock.patch.dict(os.environ, {'CC_SKIP_AFK_GUARD': '1'}), \
         mock.patch.object(cc.afk_guard, 'require_team_control', refuse), \
         mock.patch.object(cc, '_notify'), \
         mock.patch.object(cc, '_require_window', return_value='win'), \
         mock.patch.object(cc, '_content_root', return_value='root'), \
         mock.patch.object(cc, 'cowork_safe_inject', return_value=True), \
         mock.patch.object(cc, '_print', lambda obj: captured.append(obj)), \
         mock.patch('sys.stderr', io.StringIO()):
        rc = cc.cmd_inject(_Args(message='hi', no_afk_guard=False))
    results.append(check("CC_SKIP_AFK_GUARD inject proceeds", rc, 0))

    print("\n=== inject --new honors new_task bool ===")
    captured.clear()
    with mock.patch.object(cc, '_require_interactive', return_value=None), \
         mock.patch.object(cc, '_require_window', return_value='win'), \
         mock.patch.object(cc, '_content_root', return_value='root'), \
         mock.patch.object(cc, 'new_task', return_value=False), \
         mock.patch.object(cc, 'cowork_safe_inject') as inj, \
         mock.patch.object(cc, '_print', lambda obj: captured.append(obj)), \
         mock.patch('sys.stderr', io.StringIO()):
        rc = cc.cmd_inject(_Args(message='hi', new=True))
    results.append(check("inject --new fails if pane did not open", rc, 1))
    results.append(check("inject --new error key", captured[-1].get('error'), 'new_task_failed'))
    results.append(check("inject --new did not clobber composer", inj.called, False))

    captured.clear()
    with mock.patch.object(cc, '_require_interactive', return_value=None), \
         mock.patch.object(cc, '_require_window', return_value='win'), \
         mock.patch.object(cc, 'new_task', return_value=False), \
         mock.patch.object(cc, '_print', lambda obj: captured.append(obj)):
        rc = cc.cmd_new_task(_Args())
    results.append(check("cmd_new_task fails honestly", rc, 1))
    results.append(check("cmd_new_task error key", captured[-1].get('error'), 'new_task_failed'))

    print("\n=== inject default is cowork-safe, --clobber opts out ===")
    captured.clear()
    with mock.patch.object(cc, '_require_interactive', return_value=None), \
         mock.patch.object(cc, '_require_window', return_value='win'), \
         mock.patch.object(cc, '_content_root', return_value='root'), \
         mock.patch.object(cc, 'cowork_safe_inject', return_value=True) as csi, \
         mock.patch.object(cc, 'set_prompt_text') as spt, \
         mock.patch.object(cc, '_print', lambda obj: captured.append(obj)):
        rc = cc.cmd_inject(_Args(message='hi', clobber=False))
    results.append(check("default inject uses cowork_safe_inject", csi.called, True))
    results.append(check("default inject does not set_prompt_text directly", spt.called, False))

    captured.clear()
    with mock.patch.object(cc, '_require_interactive', return_value=None), \
         mock.patch.object(cc, '_require_window', return_value='win'), \
         mock.patch.object(cc, '_content_root', return_value='root'), \
         mock.patch.object(cc, 'cowork_safe_inject') as csi, \
         mock.patch.object(cc, 'set_prompt_text', return_value=True), \
         mock.patch.object(cc, 'submit_prompt', return_value=True), \
         mock.patch.object(cc, '_notify'), \
         mock.patch.object(cc, '_print', lambda obj: captured.append(obj)), \
         mock.patch('sys.stderr', io.StringIO()):
        rc = cc.cmd_inject(_Args(message='hi', clobber=True))
    results.append(check("--clobber skips cowork_safe_inject", csi.called, False))
    results.append(check("--clobber exit 0", rc, 0))

    print("\n=== argparse still accepts --cowork-safe (no-op) ===")
    args = cc.build_parser().parse_args(['inject', 'hello', '--cowork-safe'])
    results.append(check("legacy --cowork-safe parses", args.cowork_safe, True))
    results.append(check("legacy --cowork-safe default clobber False", args.clobber, False))
    args = cc.build_parser().parse_args(['inject', '--no-afk-guard', 'hello', '--clobber'])
    results.append(check("inject --no-afk-guard parses", args.no_afk_guard, True))
    results.append(check("inject --clobber parses", args.clobber, True))
    args = cc.build_parser().parse_args(['status'])
    results.append(check("status --ax default False", getattr(args, 'ax', False), False))
    args = cc.build_parser().parse_args(['status', '--ax'])
    results.append(check("status --ax parses", args.ax, True))

    print("\n=== skip/clobber logging hooks (no live relay) ===")
    notify_calls = []

    def rec_notify(title, body):
        notify_calls.append((title, body))

    def refuse():
        raise afk_guard.AfkGuardError('refused: user active')

    buf = io.StringIO()
    notify_calls.clear()
    with mock.patch.object(cc, '_notify', rec_notify), \
         mock.patch.object(cc.afk_guard, 'require_team_control', refuse), \
         mock.patch.object(cc, '_require_window', return_value='win'), \
         mock.patch.object(cc, '_content_root', return_value='root'), \
         mock.patch.object(cc, 'cowork_safe_inject', return_value=True), \
         mock.patch.object(cc, '_print', lambda obj: None), \
         mock.patch('sys.stderr', buf):
        cc.cmd_inject(_Args(message='hi', no_afk_guard=True))
    results.append(check_true("flag skip stderr", '--no-afk-guard' in buf.getvalue()))
    results.append(check_true("flag skip WARNING", 'WARNING' in buf.getvalue()))
    results.append(check("flag skip notify count", len(notify_calls), 1))
    results.append(check_true("flag skip notify body", 'afk-skip' in notify_calls[0][1]))
    results.append(check("flag skip notify title", notify_calls[0][0], 'cc.py'))

    buf = io.StringIO()
    notify_calls.clear()
    with mock.patch.dict(os.environ, {'CC_SKIP_AFK_GUARD': '1'}), \
         mock.patch.object(cc, '_notify', rec_notify), \
         mock.patch.object(cc.afk_guard, 'require_team_control', refuse), \
         mock.patch.object(cc, '_require_window', return_value='win'), \
         mock.patch.object(cc, '_content_root', return_value='root'), \
         mock.patch.object(cc, 'cowork_safe_inject', return_value=True), \
         mock.patch.object(cc, '_print', lambda obj: None), \
         mock.patch('sys.stderr', buf):
        cc.cmd_inject(_Args(message='hi', no_afk_guard=False))
    results.append(check_true("env skip stderr", 'CC_SKIP_AFK_GUARD' in buf.getvalue()))
    results.append(check("env skip notify count", len(notify_calls), 1))
    results.append(check_true("env skip notify body", 'afk-skip' in notify_calls[0][1]))

    buf = io.StringIO()
    notify_calls.clear()
    with mock.patch.object(cc, '_notify', rec_notify), \
         mock.patch.object(cc, '_require_interactive', return_value=None), \
         mock.patch.object(cc, '_require_window', return_value='win'), \
         mock.patch.object(cc, '_content_root', return_value='root'), \
         mock.patch.object(cc, 'cowork_safe_inject') as csi, \
         mock.patch.object(cc, 'set_prompt_text', return_value=True), \
         mock.patch.object(cc, 'submit_prompt', return_value=True), \
         mock.patch.object(cc, '_print', lambda obj: None), \
         mock.patch('sys.stderr', buf):
        cc.cmd_inject(_Args(message='hi', clobber=True))
    results.append(check_true("clobber stderr", '--clobber' in buf.getvalue()))
    results.append(check("clobber notify count", len(notify_calls), 1))
    results.append(check_true("clobber notify body", 'clobber' in notify_calls[0][1]))
    results.append(check("clobber still skips cowork_safe", csi.called, False))

    buf = io.StringIO()
    notify_calls.clear()
    with mock.patch.object(cc, '_notify', rec_notify), \
         mock.patch.object(cc.afk_guard, 'require_team_control'), \
         mock.patch.object(cc, '_require_window', return_value='win'), \
         mock.patch.object(cc, '_content_root', return_value='root'), \
         mock.patch.object(cc, 'cowork_safe_inject', return_value=True), \
         mock.patch.object(cc, '_print', lambda obj: None), \
         mock.patch('sys.stderr', buf):
        cc.cmd_inject(_Args(message='hi', no_afk_guard=False, clobber=False))
    results.append(check("no skip/clobber → no notify", notify_calls, []))
    results.append(check("no skip/clobber → no WARNING", 'WARNING' in buf.getvalue(), False))

    print("\n=== status ask-surface does not require AX/frontmost ===")
    json_calls = []

    def fake_json(url, timeout=1.5):
        json_calls.append(url)
        if url == f'{cc.RELAY_URL}/status':
            return {'ok': True}, None
        if url.startswith(f'{cc.RELAY_URL}/jobs/status'):
            return {'jobs': []}, None
        if url == f'{cc.RELAY_URL}/chat/status':
            return {'available': False}, None
        if url == f'{cc.RELAY_URL}/hud/asks':
            return {'asks': []}, None
        if ':3334' in url:
            raise AssertionError('status must not fetch :3334')
        return None, f'unexpected {url}'

    def fake_reach(url, timeout=1.5):
        return (url == cc.PULSE_URL), None

    captured = []
    gcr = mock.MagicMock(side_effect=AssertionError('get_content_root must not run'))
    cr = mock.MagicMock(side_effect=AssertionError('_content_root must not run'))
    with mock.patch.object(cc, 'is_claude_frontmost', return_value=False), \
         mock.patch.object(cc, 'find_claude_window', return_value='win'), \
         mock.patch.object(cc, 'get_content_root', gcr), \
         mock.patch.object(cc, '_content_root', cr), \
         mock.patch.object(cc, 'activate_claude',
                           side_effect=AssertionError('activate_claude must not run')), \
         mock.patch.object(cc, '_http_json', fake_json), \
         mock.patch.object(cc, '_http_reachable', fake_reach), \
         mock.patch.object(cc, '_print', lambda obj: captured.append(obj)):
        rc = cc.cmd_status(_Args(ax=False))
    data = captured[-1]
    results.append(check("status no-ax exit 0", rc, 0))
    results.append(check("hud.up without AX", data['hud']['up'], True))
    results.append(check("relay.up without AX", data['relay']['up'], True))
    results.append(check("pulse.up without AX", data['pulse']['up'], True))
    results.append(check("ax skipped when not frontmost", data['claude_desktop']['ax'], 'skipped'))
    results.append(check("desktop available without AX walk",
                         data['claude_desktop']['available'], True))
    results.append(check("frontmost false", data['claude_desktop']['frontmost'], False))
    results.append(check("get_content_root not called", gcr.called, False))
    results.append(check("_content_root not called", cr.called, False))

    # --ax forces AX even if not frontmost
    captured.clear()
    with mock.patch.object(cc, 'is_claude_frontmost', return_value=False), \
         mock.patch.object(cc, 'find_claude_window', return_value='win'), \
         mock.patch.object(cc, '_content_root', return_value='root') as cr_ax, \
         mock.patch.object(cc, 'infer_current_mode', return_value='chat'), \
         mock.patch.object(cc, 'get_selected_session', return_value=None), \
         mock.patch.object(cc, 'get_composer_state',
                           return_value={'has_text_area': True, 'send_action': 'Send',
                                         'draft_text': '', 'active_web_title': None}), \
         mock.patch.object(cc, 'list_tasks', return_value=[]), \
         mock.patch.object(cc, '_http_json', fake_json), \
         mock.patch.object(cc, '_http_reachable', fake_reach), \
         mock.patch.object(cc, '_print', lambda obj: captured.append(obj)):
        rc = cc.cmd_status(_Args(ax=True))
    data = captured[-1]
    results.append(check("status --ax exit 0", rc, 0))
    results.append(check("status --ax walks AX", cr_ax.called, True))
    results.append(check("status --ax reports ax ok", data['claude_desktop']['ax'], 'ok'))
    results.append(check("status --ax still has hud.up", data['hud']['up'], True))

    # already frontmost → AX without --ax
    captured.clear()
    with mock.patch.object(cc, 'is_claude_frontmost', return_value=True), \
         mock.patch.object(cc, 'find_claude_window', return_value='win'), \
         mock.patch.object(cc, '_content_root', return_value='root') as cr_front, \
         mock.patch.object(cc, 'infer_current_mode', return_value='cowork'), \
         mock.patch.object(cc, 'get_selected_session', return_value=None), \
         mock.patch.object(cc, 'get_composer_state',
                           return_value={'has_text_area': True, 'send_action': 'Send',
                                         'draft_text': '', 'active_web_title': None}), \
         mock.patch.object(cc, 'list_tasks', return_value=[]), \
         mock.patch.object(cc, '_http_json', fake_json), \
         mock.patch.object(cc, '_http_reachable', fake_reach), \
         mock.patch.object(cc, '_print', lambda obj: captured.append(obj)):
        rc = cc.cmd_status(_Args(ax=False))
    data = captured[-1]
    results.append(check("frontmost status walks AX", cr_front.called, True))
    results.append(check("frontmost status ax ok", data['claude_desktop']['ax'], 'ok'))
    results.append(check("frontmost flag true", data['claude_desktop']['frontmost'], True))

    print("\n=== automation-lock.json is 0600 ===")
    with tempfile.TemporaryDirectory() as tmpd:
        lock_dir = Path(tmpd)
        lock_path = lock_dir / 'automation-lock.json'
        with mock.patch.object(afk_guard, 'LOCK_DIR', lock_dir), \
             mock.patch.object(afk_guard, 'LOCK_PATH', lock_path):
            old_umask = os.umask(0o022)
            try:
                afk_guard._write_state(afk_guard.STATE_USER, 'test')
            finally:
                os.umask(old_umask)
            mode = stat.S_IMODE(lock_path.stat().st_mode)
            results.append(check("fresh lock mode 0600", mode, 0o600))
            # rewrite over a world-readable file
            os.chmod(lock_path, 0o644)
            with mock.patch.object(afk_guard, 'LOCK_DIR', lock_dir), \
                 mock.patch.object(afk_guard, 'LOCK_PATH', lock_path):
                afk_guard._write_state(afk_guard.STATE_TEAM, 'again')
            mode = stat.S_IMODE(lock_path.stat().st_mode)
            results.append(check("rewrite lock mode 0600", mode, 0o600))

    print("\n=== skip is not default-on in plists/scripts/dispatcher ===")
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel in ('com.soma.mac-triage.plist', 'com.mikewolf.afk-guard.plist',
                'start-pulse-dispatcher.sh'):
        text = Path(repo, rel).read_text()
        results.append(check(f"{rel} does not set CC_SKIP_AFK_GUARD",
                             'CC_SKIP_AFK_GUARD' in text, False))
        results.append(check(f"{rel} does not pass --clobber",
                             '--clobber' in text, False))

    pd_path = Path(repo, 'pulse-dispatcher.py')
    pd_src = pd_path.read_text()
    results.append(check_true("dispatcher skip default is empty string",
                              'os.environ.get("CC_SKIP_AFK_GUARD", "")' in pd_src))
    results.append(check_true("dispatcher inject is cowork-safe, not clobber",
                              'inject_args = ["inject", text, "--cowork-safe"]' in pd_src))
    results.append(check("dispatcher does not pass --clobber to cc",
                         '["inject", text, "--clobber"]' in pd_src, False))
    results.append(check("dispatcher does not pass --no-afk-guard to cc",
                         '"--no-afk-guard"' in pd_src or "'--no-afk-guard'" in pd_src, False))
    results.append(check("dispatcher no longer binds 0.0.0.0",
                         'ThreadingHTTPServer(("0.0.0.0"' in pd_src, False))
    results.append(check_true("dispatcher BIND_HOST is loopback",
                              'BIND_HOST    = "127.0.0.1"' in pd_src
                              or 'BIND_HOST = "127.0.0.1"' in pd_src))
    results.append(check_true("verify helper exists in source",
                              'def _verify_chat_cowork' in pd_src))
    results.append(check("verify does not call inspect composer",
                         '_run_cc("inspect", "composer"' in pd_src, False))
    results.append(check_true("verify does not ship draft_text",
                              'draft_text' not in pd_src.split('def _verify_chat_cowork')[1].split('def _dispatch_code')[0]
                              if 'def _verify_chat_cowork' in pd_src else False))

    import importlib.util
    spec = importlib.util.spec_from_file_location('pulse_dispatcher', str(pd_path))
    pd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pd)
    results.append(check("imported BIND_HOST", pd.BIND_HOST, '127.0.0.1'))
    ok, msg = pd._verify_chat_cowork('chat', 0, '{"status":"ok","message":"hi"}')
    results.append(check("verify rc=0 ok", ok, True))
    results.append(check("verify msg is inject-rc only",
                         msg, "inject rc=0 (composer not inspected)"))
    results.append(check("verify msg omits inject payload", 'hi' in msg, False))
    ok, msg = pd._verify_chat_cowork('chat', 1, '{"status":"error"}')
    results.append(check("verify rc=1 fails", ok, False))
    ok, msg = pd._verify_chat_cowork('chat', 0, '{"status":"error","error":"nope"}')
    results.append(check("verify status=error fails", ok, False))
    results.append(check("verify error does not contain draft", 'draft' in msg.lower(), False))

    # token gate
    fake_headers = {'Authorization': 'Bearer secret'}
    with mock.patch.object(pd, 'DISPATCH_TOKEN', ''):
        results.append(check("no token → allowed", pd._token_ok({}), True))
    with mock.patch.object(pd, 'DISPATCH_TOKEN', 'secret'):
        results.append(check("token set, missing → deny", pd._token_ok({}), False))
        results.append(check("token Bearer ok", pd._token_ok(fake_headers), True))
        results.append(check("token header ok",
                             pd._token_ok({'X-Pulse-Token': 'secret'}), True))
        results.append(check("token wrong deny",
                             pd._token_ok({'Authorization': 'Bearer nope'}), False))

    passed = sum(results)
    total = len(results)
    print(f"\n{'PASS' if passed == total else 'FAIL'}  {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(run())

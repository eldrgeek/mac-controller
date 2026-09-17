"""Automation action log: one JSONL line per automated UI action.

Authored 2026-09-17 by a Claude worker (Opus 5) dispatched by the chief-of-staff
session, from Mike Wolf's ruling of 2026-09-16 (human active time must exclude
automation). Step 1 of that ruling: automation logs its own actions, and the
estimator subtracts those windows from Screenpipe activity.

Shared format (also written by the Yeshie relay, packages/relay/automation-log.js):

    ~/Library/Logs/soma-automation/actions.jsonl
    {"ts": "2026-09-17T13:05:01.123Z",   # UTC, ISO 8601, when the action started
     "actor": "cc.py",                   # cc.py | yeshie | claude-in-chrome | computer-use | ...
     "kind": "ax_press",                 # ax_press | ax_set_value | ax_focus | key | mouse | activate | step:<action> ...
     "target": "Claude",                 # app name, or site host for browser steps; never a URL with a query
     "duration_ms": 12,
     "session_id": "...",                # only when known (env)
     "pid": 1234,                        # posting process; step 2 matches this to CGEvent sender pid
     "ok": true,
     "dry_run": true}                    # present only on self-test lines; estimators ignore them

Never logged: typed text, AX values, selectors, URLs with query strings, secrets.

Rotation: when the day (UTC) of the current file's first line differs from today,
or the file exceeds MAX_BYTES, it is renamed to actions-<date>[-n].jsonl.
Only the newest KEEP_ROTATED rotated files are kept.

Failure safety: every public function catches every exception. Logging must never
break automation. Set SOMA_AUTOMATION_LOG=0 to disable; SOMA_AUTOMATION_LOG_DIR
overrides the directory (tests use this).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
import time

MAX_BYTES = 5 * 1024 * 1024
KEEP_ROTATED = 30
SESSION_ENV_VARS = ('SOMA_SESSION_ID', 'CLAUDE_CODE_SESSION_ID', 'CLAUDE_SESSION_ID', 'CC_SESSION_ID')
_SAFE_TOKEN = re.compile(r'[^A-Za-z0-9 ._:/@()+\-]')


def log_dir() -> str:
    return os.environ.get('SOMA_AUTOMATION_LOG_DIR') or os.path.expanduser('~/Library/Logs/soma-automation')


def log_path() -> str:
    return os.path.join(log_dir(), 'actions.jsonl')


def enabled() -> bool:
    return os.environ.get('SOMA_AUTOMATION_LOG', '1').lower() not in ('0', 'false', 'off', 'no')


def default_actor() -> str:
    try:
        base = os.path.basename(sys.argv[0] or '') or 'python'
    except Exception:
        base = 'python'
    return 'cc.py' if base in ('cc', 'cc.py', 'claudectl') else base


def _session_id():
    for name in SESSION_ENV_VARS:
        value = os.environ.get(name)
        if value:
            return _clean(value, 80)
    return None


def _clean(value, limit=80):
    """Keep a short, query-free, printable token. Returns None for empty."""
    if value is None:
        return None
    text = str(value)
    # A URL is reduced to its host; a query string or fragment is always dropped.
    m = re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://([^/?#]+)', text)
    if m:
        text = m.group(1).rsplit('@', 1)[-1]
    text = text.split('?', 1)[0].split('#', 1)[0]
    text = _SAFE_TOKEN.sub('', text).strip()[:limit]
    return text or None


def _now_iso(epoch=None) -> str:
    t = time.time() if epoch is None else epoch
    return _dt.datetime.fromtimestamp(t, _dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def build_line(actor, kind, target=None, duration_ms=None, session_id=None, ok=None,
               dry_run=False, started_at=None) -> dict:
    line = {
        'ts': _now_iso(started_at),
        'actor': _clean(actor, 40) or 'unknown',
        'kind': _clean(kind, 40) or 'unknown',
    }
    target = _clean(target, 80)
    if target:
        line['target'] = target
    if duration_ms is not None:
        try:
            line['duration_ms'] = max(0, int(duration_ms))
        except Exception:
            pass
    sid = _clean(session_id, 80) if session_id else _session_id()
    if sid:
        line['session_id'] = sid
    line['pid'] = os.getpid()
    if ok is not None:
        line['ok'] = bool(ok)
    if dry_run:
        line['dry_run'] = True
    return line


def _rotate_if_needed(path: str) -> None:
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return
    today = _dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%d')
    first_day = None
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            first_day = (json.loads(fh.readline() or '{}').get('ts') or '')[:10] or None
    except Exception:
        first_day = None
    if first_day == today and st.st_size < MAX_BYTES:
        return
    stamp = first_day or _dt.datetime.fromtimestamp(st.st_mtime, _dt.timezone.utc).strftime('%Y-%m-%d')
    directory = os.path.dirname(path)
    target = os.path.join(directory, f'actions-{stamp}.jsonl')
    n = 1
    while os.path.exists(target):
        target = os.path.join(directory, f'actions-{stamp}-{n}.jsonl')
        n += 1
    os.rename(path, target)
    rotated = sorted(f for f in os.listdir(directory) if f.startswith('actions-') and f.endswith('.jsonl'))
    for old in rotated[:-KEEP_ROTATED]:
        try:
            os.remove(os.path.join(directory, old))
        except Exception:
            pass


def record(kind, target=None, duration_ms=None, actor=None, session_id=None, ok=None,
           dry_run=False, started_at=None):
    """Append one action line. Returns the dict written, or None. Never raises."""
    try:
        if not enabled():
            return None
        line = build_line(actor or default_actor(), kind, target, duration_ms, session_id, ok,
                          dry_run, started_at)
        path = log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _rotate_if_needed(path)
        data = (json.dumps(line, separators=(',', ':')) + '\n').encode('utf-8')
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return line
    except Exception:
        return None


# ── PyObjC call-site instrumentation ──────────────────────────────────────────
# The lowest point every cc.py / claude_ax action passes through is the PyObjC
# function objects themselves: AS.AXUIElementPerformAction,
# AS.AXUIElementSetAttributeValue and Quartz.CGEventPost. Both modules look them
# up as module attributes at call time, so wrapping the attribute once covers
# every call site in the process (cc.py imports the same module object).

_pid_names: dict = {}

# CGEventType values (CGEventTypes.h). The "down" half of a key press or click
# is not logged; its time is folded into the "up" line's duration.
_DOWN = {1: 'mouse', 3: 'mouse', 25: 'mouse', 10: 'key'}
_UP = {2: 'mouse', 4: 'mouse', 26: 'mouse', 11: 'key'}
_last_down: dict = {}


def _app_name_for_pid(pid, appkit):
    if not pid:
        return None
    if pid in _pid_names:
        return _pid_names[pid]
    name = None
    try:
        app = appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        name = app.localizedName() if app else None
    except Exception:
        name = None
    if len(_pid_names) < 256:
        _pid_names[pid] = name
    return name


def _ax_target(as_mod, appkit, elem):
    try:
        res = as_mod.AXUIElementGetPid(elem, None)
        pid = res[1] if isinstance(res, tuple) else res
        return _app_name_for_pid(int(pid), appkit)
    except Exception:
        return None


def _frontmost(appkit):
    try:
        app = appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
        return app.localizedName() if app else None
    except Exception:
        return None


def install(as_mod, quartz_mod, appkit_mod, actor=None) -> bool:
    """Wrap the PyObjC action entry points once. Returns True when installed.

    Skips anything that is not a real module (test doubles are MagicMocks), so
    unit tests that mock PyObjC never write to the real log.
    """
    import types
    try:
        if not all(isinstance(m, types.ModuleType) for m in (as_mod, quartz_mod, appkit_mod)):
            return False
        if getattr(as_mod, '_soma_automation_logged', False):
            return True

        orig_press = as_mod.AXUIElementPerformAction
        orig_set = as_mod.AXUIElementSetAttributeValue
        orig_post = quartz_mod.CGEventPost

        def AXUIElementPerformAction(elem, action, *rest):
            t0 = time.time()
            result = orig_press(elem, action, *rest)
            try:
                kind = 'ax_press' if action == 'AXPress' else 'ax_' + str(action).lower().removeprefix('ax')
                record(kind, _ax_target(as_mod, appkit_mod, elem), (time.time() - t0) * 1000,
                       actor=actor, ok=(result == 0), started_at=t0)
            except Exception:
                pass
            return result

        def AXUIElementSetAttributeValue(elem, attr, value, *rest):
            t0 = time.time()
            result = orig_set(elem, attr, value, *rest)
            try:
                names = {'AXValue': 'ax_set_value', 'AXFocused': 'ax_focus', 'AXSelected': 'ax_select'}
                kind = names.get(attr, 'ax_set_' + str(attr).lower().removeprefix('ax'))
                record(kind, _ax_target(as_mod, appkit_mod, elem), (time.time() - t0) * 1000,
                       actor=actor, ok=(result == 0), started_at=t0)
            except Exception:
                pass
            return result

        def CGEventPost(tap, event, *rest):
            t0 = time.time()
            result = orig_post(tap, event, *rest)
            try:
                etype = int(quartz_mod.CGEventGetType(event))
                if etype in _DOWN:
                    _last_down[_DOWN[etype]] = t0
                else:
                    kind = _UP.get(etype, f'cgevent_{etype}')
                    started = _last_down.pop(kind, t0) if etype in _UP else t0
                    record(kind, _frontmost(appkit_mod), (time.time() - started) * 1000,
                           actor=actor, started_at=started)
            except Exception:
                pass
            return result

        as_mod.AXUIElementPerformAction = AXUIElementPerformAction
        as_mod.AXUIElementSetAttributeValue = AXUIElementSetAttributeValue
        quartz_mod.CGEventPost = CGEventPost
        as_mod._soma_automation_logged = True
        return True
    except Exception:
        return False


def main(argv=None) -> int:
    """`python3 automation_log.py selftest` writes one dry_run line and prints it."""
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ['selftest']:
        line = record('selftest', target='none', duration_ms=0, dry_run=True)
        print(json.dumps({'path': log_path(), 'line': line}))
        return 0 if line else 1
    print('usage: automation_log.py selftest', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())

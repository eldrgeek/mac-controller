#!/usr/bin/env python3
"""
afk_guard.py — AFK/idle coordination for mac-controller automation.

Problem this solves: background automation (cc.py AX clicks, keystroke
injection, session switches) can steal focus / click around while Mike is
actively using the Mac. Flagged 2026-07-17 after a debugging agent fired live
AX clicks against Claude Desktop mid-session. This module is the single
source of truth every automation task must check before doing anything
interactive on-screen.

State machine
-------------
Lock file: ~/.mac-controller/automation-lock.json
  {
    "state": "user_active" | "team_active",
    "since": "<ISO8601>",
    "reason": "<free text — what the team is doing, or empty>"
  }

Transitions:
  user_active -> team_active   : only when idle_seconds() >= IDLE_THRESHOLD_S,
                                  via request_team_control(reason). Also
                                  reachable via the overlay badge's "Give team
                                  control" button (acquire_team_control, same
                                  gate — badge only appears once idle anyway,
                                  but the gate is enforced here too, not just
                                  in the UI, so nothing can bypass it).
  team_active -> user_active   : (a) ANY keyboard/mouse input observed by the
                                  idle-watcher loop while state==team_active
                                  (safety backstop — no explicit action
                                  required), or (b) the overlay's "Let me in"
                                  button (release_to_user), or (c) explicit
                                  release_to_user() call.

The idle-watcher loop (run_daemon()) is the only writer that flips
team_active -> user_active on detected input; it polls idle time every
POLL_INTERVAL_S and if idle_seconds() resets to ~0 while state is
team_active, it immediately writes user_active. This is the backstop: Mike
regaining control by touching the keyboard/mouse always works, no explicit
action needed.

Enforcement contract for automation authors
--------------------------------------------
Any script about to do interactive AX/keyboard/mouse work against a
foreground app (Claude Desktop, Chrome, etc.) MUST:

    from afk_guard import require_team_control, ensure_team_control

    # Hard refuse if not already team_active:
    require_team_control()   # raises AfkGuardError if state != team_active

    # OR: request control and block (bounded) until granted:
    ensure_team_control(reason="cdc-review resume click", timeout=310)

`ensure_team_control` will NOT force anything — it can only succeed once
Mike has been idle >= IDLE_THRESHOLD_S (the daemon or the caller itself,
via request_team_control, writes team_active only under that gate) or Mike
explicitly hands off control via the overlay badge. If neither happens
within `timeout`, it raises AfkGuardError.

This supersedes ad-hoc `cc status` checks used in earlier work — `cc status`
tells you what Desktop's AX tree looks like, not whether it's currently safe
to touch it interactively.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────

IDLE_THRESHOLD_S = 300          # 5 minutes — single source of truth, see below
POLL_INTERVAL_S = 1.0           # idle-watcher poll cadence
LOCK_DIR = Path.home() / '.mac-controller'
LOCK_PATH = LOCK_DIR / 'automation-lock.json'

STATE_USER = 'user_active'
STATE_TEAM = 'team_active'

OVERLAY_SCRIPT = Path(__file__).resolve().parent / 'overlay_panel.py'
PYTHON_BIN = '/opt/homebrew/bin/python3'


class AfkGuardError(RuntimeError):
    pass


# ── Idle time (system-wide, via Quartz — standard API, no custom event tap) ─

def idle_seconds() -> float:
    """Seconds since the last keyboard or mouse event, system-wide.
    Uses CGEventSourceSecondsSinceLastEventType against kCGAnyInputEventType
    on the combined (HID) event source — the standard macOS idle-time API
    (same one `pmset`/screensavers use). Not a keylogger: no event content,
    no event tap installed, just a monotonic "how long since last input"
    counter the OS already tracks.
    """
    import Quartz
    return Quartz.CGEventSourceSecondsSinceLastEventType(
        Quartz.kCGEventSourceStateHIDSystemState,
        Quartz.kCGAnyInputEventType,
    )


def is_afk(threshold: float = IDLE_THRESHOLD_S) -> bool:
    return idle_seconds() >= threshold


# ── Lock file I/O ─────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_state() -> dict:
    return {'state': STATE_USER, 'since': _now_iso(), 'reason': ''}


def read_state() -> dict:
    try:
        with open(LOCK_PATH) as f:
            data = json.load(f)
        if data.get('state') not in (STATE_USER, STATE_TEAM):
            return _default_state()
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _default_state()


def _write_state(state: str, reason: str = '') -> dict:
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    data = {'state': state, 'since': _now_iso(), 'reason': reason}
    tmp = LOCK_PATH.with_suffix('.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=2)
    tmp.replace(LOCK_PATH)  # atomic on same filesystem
    return data


def release_to_user() -> dict:
    """Immediately hand control back to Mike. Always allowed — no gate."""
    return _write_state(STATE_USER)


def _launch_overlay():
    """Best-effort: start the overlay UI process if not already running."""
    try:
        # Cheap "already running" check via pgrep on the script path.
        check = subprocess.run(
            ['pgrep', '-f', str(OVERLAY_SCRIPT)],
            capture_output=True, text=True,
        )
        if check.stdout.strip():
            return
        subprocess.Popen(
            [PYTHON_BIN, str(OVERLAY_SCRIPT)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        sys.stderr.write(f'[afk_guard] could not launch overlay: {e}\n')


def request_team_control(reason: str = '') -> dict:
    """Attempt to acquire team_active. Only succeeds if Mike is currently
    idle >= IDLE_THRESHOLD_S. Raises AfkGuardError otherwise. On success,
    also (best-effort) launches the overlay panel so the state is visible.
    """
    idle = idle_seconds()
    if idle < IDLE_THRESHOLD_S:
        raise AfkGuardError(
            f'refused: user active {idle:.0f}s ago (< {IDLE_THRESHOLD_S}s threshold)')
    data = _write_state(STATE_TEAM, reason)
    _launch_overlay()
    return data


def force_team_control(reason: str = '') -> dict:
    """Bypass the idle gate. Only for the overlay badge's explicit
    'Give team control' handoff (Mike consciously choosing this), never
    for automation. Automation must use request_team_control().
    """
    data = _write_state(STATE_TEAM, reason)
    _launch_overlay()
    return data


# ── Enforcement helpers for automation authors ──────────────────────────

def require_team_control():
    """Hard gate. Raises AfkGuardError unless state is already team_active."""
    data = read_state()
    if data['state'] != STATE_TEAM:
        raise AfkGuardError(
            f'refused: automation-lock state is "{data["state"]}", not '
            f'"{STATE_TEAM}". Call ensure_team_control(reason=...) first, '
            f'or wait for Mike to be idle >= {IDLE_THRESHOLD_S}s / hand off '
            f'via the overlay badge.')


def ensure_team_control(reason: str, timeout: float = IDLE_THRESHOLD_S + 10,
                         poll: float = 2.0) -> dict:
    """Request team_active and block (bounded) until granted or timeout.
    Never forces anything itself — relies on request_team_control's idle
    gate (or Mike explicitly using the overlay badge in the meantime, which
    writes team_active directly to the lock file).
    """
    data = read_state()
    if data['state'] == STATE_TEAM:
        return data
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return request_team_control(reason)
        except AfkGuardError:
            pass
        # Maybe Mike hands off via the badge while we wait — check the file.
        data = read_state()
        if data['state'] == STATE_TEAM:
            return data
        time.sleep(poll)
    raise AfkGuardError(
        f'timed out after {timeout:.0f}s waiting for team_active '
        f'(idle={idle_seconds():.0f}s, threshold={IDLE_THRESHOLD_S}s)')


# ── Daemon loop: idle detector + input backstop ─────────────────────────

def run_daemon():
    """Long-running loop: the idle-detector. Its only writing responsibility
    is the safety backstop — flipping team_active back to user_active the
    instant input is detected. It does NOT grant team_active on its own;
    that only happens via request_team_control()/force_team_control() calls
    from automation or the overlay badge.
    """
    sys.stderr.write(
        f'[afk_guard] daemon starting; lock={LOCK_PATH} '
        f'threshold={IDLE_THRESHOLD_S}s poll={POLL_INTERVAL_S}s\n')
    sys.stderr.flush()
    last_state = None
    while True:
        try:
            idle = idle_seconds()
            data = read_state()
            if data['state'] == STATE_TEAM:
                # Belt-and-suspenders: make sure the overlay is actually
                # showing whenever the lock says team_active, even if the
                # lock file was flipped by something other than
                # request_team_control()/force_team_control() (e.g. hand
                # edited, or a future caller that writes the file directly).
                _launch_overlay()
            if data['state'] == STATE_TEAM and idle < 1.0:
                # Fresh input observed while automation held control.
                data = release_to_user()
                sys.stderr.write(
                    f'[afk_guard] input detected — releasing to user_active '
                    f'at {data["since"]}\n')
                sys.stderr.flush()
            if data['state'] != last_state:
                last_state = data['state']
        except Exception as e:
            sys.stderr.write(f'[afk_guard] daemon error: {e}\n')
            sys.stderr.flush()
        time.sleep(POLL_INTERVAL_S)


if __name__ == '__main__':
    run_daemon()

"""
Integration tests for cc.py — use cc status as the oracle.

These tests require:
  1. Claude Desktop running
  2. Relay running on localhost:3333

Run with:
  CLAUDE_LIVE_TESTS=1 /opt/homebrew/bin/python3 -m pytest tests/test_integration.py -v

Without the env var, all tests are skipped.
"""

import json
import os
import subprocess
import sys
import time

import pytest

CC = ['/opt/homebrew/bin/python3', '/Users/mikewolf/Projects/mac-controller/cc.py']
LIVE = os.environ.get('CLAUDE_LIVE_TESTS') == '1'
skip_unless_live = pytest.mark.skipif(not LIVE, reason='Set CLAUDE_LIVE_TESTS=1 to run live tests')


# ─── helpers ────────────────────────────────────────────────────────────────

def run_cc(*args, timeout=10):
    """Run cc.py with given args. Returns (returncode, stdout_str, stderr_str)."""
    result = subprocess.run(
        CC + list(args),
        capture_output=True, text=True, timeout=timeout
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def get_status():
    """Call cc status and return parsed JSON dict."""
    rc, out, err = run_cc('status')
    assert rc == 0, f'cc status failed (rc={rc}): {err}'
    return json.loads(out)


def desktop(status_json):
    return status_json['claude_desktop']


def wait_for_mode(expected_mode, retries=6, delay=0.8):
    """Poll cc status until mode matches, or raise."""
    for _ in range(retries):
        s = get_status()
        if desktop(s).get('mode') == expected_mode:
            return s
        time.sleep(delay)
    raise AssertionError(f'Mode never became {expected_mode!r}; last: {desktop(s).get("mode")!r}')


# ─── sanity ─────────────────────────────────────────────────────────────────

@skip_unless_live
def test_status_returns_valid_json():
    """cc status should return valid JSON with top-level claude_desktop key."""
    rc, out, err = run_cc('status')
    assert rc == 0, f'Non-zero exit: {err}'
    data = json.loads(out)
    assert 'claude_desktop' in data
    assert 'relay' in data
    assert 'hud' in data


@skip_unless_live
def test_status_claude_desktop_available():
    """Claude Desktop should be reachable."""
    s = get_status()
    assert desktop(s)['available'] is True, 'Claude Desktop not available'


@skip_unless_live
def test_status_shows_relay_up():
    """Relay should be running on localhost:3333."""
    s = get_status()
    assert s['relay']['up'] is True, 'Relay is not up'


@skip_unless_live
def test_status_composer_has_text_area():
    """Composer should always report a text area in cowork/chat mode."""
    s = get_status()
    assert desktop(s)['composer']['has_text_area'] is True


@skip_unless_live
def test_status_tasks_is_dict():
    """Tasks should be a dict keyed by status (may be empty if no tasks)."""
    s = get_status()
    assert isinstance(desktop(s)['tasks'], dict)


# ─── mode switching ─────────────────────────────────────────────────────────

@skip_unless_live
def test_mode_switch_to_chat():
    """cc mode chat should result in mode == 'chat'."""
    original_mode = desktop(get_status()).get('mode', 'cowork')
    try:
        rc, out, err = run_cc('mode', 'chat')
        assert rc == 0, f'mode chat failed: {err}'
        s = wait_for_mode('chat')
        assert desktop(s)['mode'] == 'chat'
    finally:
        run_cc('mode', original_mode)
        wait_for_mode(original_mode)


@skip_unless_live
def test_mode_switch_to_cowork():
    """cc mode cowork should result in mode == 'cowork'."""
    rc, out, err = run_cc('mode', 'cowork')
    assert rc == 0, f'mode cowork failed: {err}'
    s = wait_for_mode('cowork')
    assert desktop(s)['mode'] == 'cowork'


@skip_unless_live
def test_mode_switch_to_code():
    """cc mode code should result in mode == 'code'."""
    original_mode = desktop(get_status()).get('mode', 'cowork')
    try:
        rc, out, err = run_cc('mode', 'code')
        assert rc == 0, f'mode code failed: {err}'
        s = wait_for_mode('code')
        assert desktop(s)['mode'] == 'code'
    finally:
        run_cc('mode', original_mode)
        wait_for_mode(original_mode)


# ─── inspect subcommand ──────────────────────────────────────────────────────

@skip_unless_live
def test_inspect_composer():
    """cc inspect composer should return JSON with has_text_area."""
    rc, out, err = run_cc('inspect', 'composer')
    assert rc == 0, f'inspect composer failed: {err}'
    data = json.loads(out)
    assert 'has_text_area' in data


@skip_unless_live
def test_inspect_sessions():
    """cc inspect sessions should return a non-empty list."""
    rc, out, err = run_cc('inspect', 'sessions')
    assert rc == 0, f'inspect sessions failed: {err}'
    data = json.loads(out)
    assert isinstance(data, list)
    assert len(data) > 0, 'Session list was empty'


@skip_unless_live
def test_inspect_tasks():
    """cc inspect tasks should return a list."""
    rc, out, err = run_cc('inspect', 'tasks')
    assert rc == 0, f'inspect tasks failed: {err}'
    data = json.loads(out)
    assert isinstance(data, list)


@skip_unless_live
def test_inspect_mode():
    """cc inspect mode should return a dict with current_mode."""
    rc, out, err = run_cc('inspect', 'mode')
    assert rc == 0, f'inspect mode failed: {err}'
    data = json.loads(out)
    assert 'current_mode' in data
    assert data['current_mode'] in ('chat', 'cowork', 'code')


# ─── new-task ────────────────────────────────────────────────────────────────

@skip_unless_live
def test_new_task_increases_count():
    """cc new-task should create a new session (task_count increases).

    NOTE: This test leaves behind a blank task — close it manually.
    """
    # Must be in cowork mode
    run_cc('mode', 'cowork')
    wait_for_mode('cowork')

    before = desktop(get_status())['task_count']
    rc, out, err = run_cc('new-task')
    assert rc == 0, f'new-task failed: {err}'

    time.sleep(2.0)
    after = desktop(get_status())['task_count']
    # Count should increase by at least 1
    assert after > before, f'task_count did not increase: {before} -> {after}'


# ─── hud-ask (relay must be running; HUD must be open) ───────────────────────

@pytest.mark.skipif(not LIVE, reason='Set CLAUDE_LIVE_TESTS=1 to run live tests')
def test_hud_ask_timeout():
    """cc hud-ask with a very short timeout should return timeout (no human present)."""
    rc, out, _ = run_cc('hud-ask', 'Integration test — ignore this. (auto-timeout)', '--timeout', '2')
    data = json.loads(out)
    # Either timeout (no human) or a valid response if human is watching
    assert data.get('response') in ('timeout', 'confirm', 'failed', 'partial')
    # Exit code 3 = timeout, 0/1/2 = human responded
    assert rc in (0, 1, 2, 3)

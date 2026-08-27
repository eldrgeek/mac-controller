#!/usr/bin/env python3
"""
cc.py — Claude Desktop Control CLI

Commands:
  mode <chat|cowork|code>         Switch mode via ⌘1/2/3
  new-task                        Create a new Cowork/Chat/Code pane (AX New)
  inject MSG                      Inject text into current session
    --session TITLE               Switch to session first
    --new                         Create new task first
    --save-restore                Save/restore draft + session
    --cowork-safe                 No-op (draft preservation is the default)
    --clobber                     Overwrite composer without preserving draft
    --no-dispatch                 Set text but don't submit
  recent                          Work with recent sessions/tasks
    --list                        List recents (default)
    --status STATUS               Filter: running/done/ready/scheduled/dispatch/awaiting input
    --pick TITLE                  Select session by title substring
    --inject MSG                  Inject into selected session
    --no-dispatch                 Set text but don't submit
    --cowork-safe                 No-op (draft preservation is the default)
    --clobber                     Overwrite composer without preserving draft
  inspect <overview|sessions|tasks|composer|mode|buttons>
  afk-status                      Show automation-lock state + live idle seconds
  afk-wait --reason "..."         Block (bounded) until team_active is granted
  afk-set-team --reason "..."     Request team_active now (fails unless idle >= threshold)
  afk-release                     Hand control back to user_active (always allowed)

Examples:
  cc.py mode cowork
  cc.py new-task
  cc.py inject "What is the status?" --session "FrontRow"
  cc.py inject "Run tests" --new
  cc.py inject "overwrite" --clobber
  cc.py recent --list --status running
  cc.py recent --pick "FrontRow" --inject "Deploy to staging"
  cc.py inspect mode
  cc.py inspect sessions
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

import ApplicationServices as AS

import afk_guard
from claude_ax import (
    infer_current_mode,
    activate_claude,
    click_control,
    cowork_safe_inject,
    find_claude_app,
    find_claude_window,
    find_text_area,
    get_attr,
    get_composer_state,
    get_content_root,
    get_selected_session,
    inject_message,
    list_sessions,
    list_tasks,
    new_task,
    parse_task_status,
    press_key,
    set_mode,
    set_prompt_text,
    submit_prompt,
    wait_for_text_area,
    find_roles,
)

# Ask surface: yeshie relay brokers, Pulse (web :8088 / Pixel) renders.
# The native overlay on :3334 (com.yeshie.hud) was retired 2026-07-01 — never
# POST /show or GET /wv-status there. Relay ask fields are a Pulse contract:
# GET /hud/asks → {asks: [{id, message, createdAt, ageSeconds}]}
# POST /hud/response/:id → {response}; do not rename those keys.
RELAY_URL = 'http://localhost:3333'
PULSE_URL = 'http://localhost:8088'


def _print(obj):
    json.dump(obj, sys.stdout, indent=2)
    sys.stdout.write('\n')


def _require_window():
    win = find_claude_window()
    if not win:
        sys.exit(1)
    return win


def _content_root(win):
    """Get AXWebArea content root for text-area / button lookups."""
    app = find_claude_app()
    if app:
        app_elem = AS.AXUIElementCreateApplication(app.processIdentifier())
        root = get_content_root(app_elem)
        if root:
            return root
    return win


def _http_json(url, timeout=1.5):
    """GET url and parse JSON. Returns (data_or_None, error_or_None)."""
    try:
        r = urllib.request.urlopen(url, timeout=timeout)
        return json.loads(r.read()), None
    except Exception as e:
        return None, str(e)


def _http_reachable(url, timeout=1.5):
    """True if anything is listening (HTTP 2xx/4xx/5xx all count as up)."""
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True, None
    except urllib.error.HTTPError:
        return True, None
    except Exception as e:
        return False, str(e)


def _afk_guard_disabled(args) -> bool:
    if getattr(args, 'no_afk_guard', False):
        return True
    v = os.environ.get('CC_SKIP_AFK_GUARD', '')
    return v.strip().lower() in ('1', 'true', 'yes')


def _require_interactive(args, reason: str):
    """Refuse mutating AX work unless team_active. Returns exit code or None."""
    if _afk_guard_disabled(args):
        return None
    try:
        afk_guard.require_team_control()
    except afk_guard.AfkGuardError as e:
        _print({'error': str(e), 'reason': reason})
        return 1
    return None


def _ask_surface(relay: dict, pulse: dict = None, pending_asks=None, asks_err=None):
    """hud.up is ask-surface health (relay + /hud/asks), not the retired :3334 overlay.

    cc-dispatch handoff.py keys hud_up off status['hud']['up']. Mapping that to
    the relay ask broker keeps it True when Pulse+relay are up, instead of
    Connection-refused against a dead overlay. Pulse reachability is reported
    on hud.pulse_up and the top-level `pulse` field; hud.up does not require
    :8088 so a Pixel-only renderer still counts.
    """
    hud = {
        'up': bool(relay.get('up')),
        'surface': 'pulse',
        'broker': 'relay',
    }
    if pulse is not None:
        hud['pulse_up'] = bool(pulse.get('up'))
    if pending_asks is not None:
        hud['pending_asks'] = pending_asks
    if not hud['up']:
        hud['error'] = relay.get('error') or asks_err or 'relay not reachable'
    elif asks_err:
        # Relay /status was up but GET /hud/asks failed — still an ask-surface miss.
        hud['up'] = False
        hud['error'] = asks_err
    return hud


# ── Subcommand handlers ───────────────────────────────────────────────────────

def cmd_mode(args):
    refused = _require_interactive(args, 'mode switch')
    if refused is not None:
        return refused
    win = _require_window()
    ok = set_mode(args.mode)
    if ok:
        time.sleep(0.5)
        current = infer_current_mode(win)
        _print({'mode_set': args.mode, 'detected_mode': current})
    return 0 if ok else 1


def cmd_new_task(args):
    refused = _require_interactive(args, 'new-task')
    if refused is not None:
        return refused
    win = _require_window()
    ok = new_task(win)
    if not ok:
        _print({'status': 'error', 'error': 'new_task_failed'})
        return 1
    _print({'status': 'new_task_opened'})
    return 0


def cmd_inject(args):
    refused = _require_interactive(args, 'inject')
    if refused is not None:
        return refused
    win = _require_window()
    root = _content_root(win)
    msg = args.message

    if args.session:
        ok = click_control(win, contains=args.session, role='AXButton')
        if not ok:
            print(f'ERROR: session "{args.session}" not found', file=sys.stderr)
            return 1
        time.sleep(1.2)

    if args.new:
        if not new_task(win):
            print('ERROR: new task pane did not open', file=sys.stderr)
            _print({'status': 'error', 'error': 'new_task_failed'})
            return 1
        time.sleep(0.5)

    saved_text = ''
    saved_session = None
    if args.save_restore:
        ta = find_text_area(root)
        if ta:
            saved_text = get_attr(ta, 'AXValue') or ''
        saved_session = get_selected_session(win)

    # Draft preservation is the default. --clobber restores the old overwrite
    # path. --cowork-safe is kept as a no-op so documented callers still parse.
    if args.clobber:
        if not set_prompt_text(root, msg):
            return 1
        if args.no_dispatch:
            _print({'status': 'text_set', 'message': msg})
            return 0
        ok = submit_prompt(root)
    else:
        ok = cowork_safe_inject(root, msg, dispatch=not args.no_dispatch)
        if args.no_dispatch and ok:
            _print({'status': 'text_set', 'message': msg})
            return 0

    if args.save_restore and saved_session:
        time.sleep(0.5)
        AS.AXUIElementPerformAction(saved_session['elem'], 'AXPress')
        time.sleep(0.8)
        if saved_text:
            ta2 = wait_for_text_area(root, timeout=3.0)
            if ta2:
                AS.AXUIElementSetAttributeValue(ta2, 'AXValue', saved_text)

    _print({'status': 'ok' if ok else 'error', 'message': msg[:80]})
    return 0 if ok else 1


def cmd_recent(args):
    win = _require_window()

    tasks = list_tasks(win, status_filter=args.status)

    if args.list or not args.pick:
        rows = [{'title': t['title'], 'status': t['status'],
                 'clean_title': t['clean_title'], 'selected': t['selected']}
                for t in tasks]
        _print({'tasks': rows, 'count': len(rows)})
        return 0

    refused = _require_interactive(args, 'recent --pick')
    if refused is not None:
        return refused

    root = _content_root(win)
    needle = args.pick.lower()
    match = None
    for t in tasks:
        if needle in t['clean_title'].lower() or needle in t['title'].lower():
            match = t
            break
    if not match:
        print(f'ERROR: no task matching "{args.pick}"', file=sys.stderr)
        return 1

    AS.AXUIElementPerformAction(match['elem'], 'AXPress')
    time.sleep(1.2)

    if args.inject:
        if args.clobber:
            if not set_prompt_text(root, args.inject):
                return 1
            if args.no_dispatch:
                _print({'status': 'text_set', 'picked': match['title']})
                return 0
            ok = submit_prompt(root)
        else:
            ok = cowork_safe_inject(root, args.inject, dispatch=not args.no_dispatch)
            if args.no_dispatch and ok:
                _print({'status': 'text_set', 'picked': match['title']})
                return 0
        _print({'status': 'ok' if ok else 'error', 'picked': match['title']})
        return 0 if ok else 1

    _print({'status': 'switched', 'picked': match['title']})
    return 0


def cmd_inspect(args):
    win = _require_window()
    root = _content_root(win)
    what = args.what

    if what == 'mode':
        _print({'current_mode': infer_current_mode(win)})

    elif what == 'sessions':
        sessions = [{'title': s['title'], 'selected': s['selected']}
                    for s in list_sessions(win)]
        selected = get_selected_session(win)
        _print({'selected': selected['title'] if selected else None,
                'count': len(sessions), 'sessions': sessions})

    elif what == 'tasks':
        tasks = [{'title': t['title'], 'status': t['status'], 'clean_title': t['clean_title']}
                 for t in list_tasks(win)]
        _print({'tasks': tasks, 'count': len(tasks)})

    elif what == 'composer':
        _print(get_composer_state(root))

    elif what == 'buttons':
        buttons = []
        for _, elem in find_roles(win, ['AXButton'], max_depth=45):
            title = get_attr(elem, 'AXTitle') or ''
            desc = get_attr(elem, 'AXDescription') or ''
            sel = get_attr(elem, 'AXSelected')
            buttons.append({'title': title, 'description': desc, 'selected': sel})
        _print({'buttons': buttons, 'count': len(buttons)})

    else:  # overview
        sessions = [{'title': s['title'], 'selected': s['selected']}
                    for s in list_sessions(win)]
        selected = get_selected_session(win)
        _print({
            'current_mode': infer_current_mode(win),
            'selected_session': selected['title'] if selected else None,
            'composer': get_composer_state(root),
            'session_count': len(sessions),
            'sessions': sessions[:10],
        })

    return 0


def cmd_status(args):
    """Full machine-readable status: Claude Desktop AX + relay + Pulse + jobs.

    `hud.up` is ask-surface health (relay `/hud/asks`), not the retired :3334
    overlay. Pulse (:8088) is a sibling field. Relay ask JSON keys are a Pulse
    contract and are not renamed here.
    """
    # ── Claude Desktop ────────────────────────────────────────────
    win = find_claude_window()
    desktop = {'available': False}
    if win:
        root = _content_root(win)
        mode = infer_current_mode(win)
        selected = get_selected_session(win)
        composer = get_composer_state(root)
        tasks = list_tasks(win)

        # Group tasks by status — only include status-prefixed items
        # Unprefixed items include UI buttons (tool-use, sidebar chrome) — skip them
        by_status = {}
        for t in tasks:
            s = t['status']
            if s is None:
                continue   # skip unprefixed — includes tool-use buttons
            by_status.setdefault(s, []).append(t['clean_title'])
        # Trim done list — usually long
        if 'done' in by_status:
            by_status['done_recent'] = by_status.pop('done')[:5]

        desktop = {
            'available': True,
            'mode': mode,
            'selected_session': selected['title'] if selected else None,
            'active_web_title': composer.get('active_web_title'),
            'composer': {
                'has_text_area': composer.get('has_text_area'),
                'send_action': composer.get('send_action'),
                # get_composer_state already blanks placeholder AXValues
                'has_draft': bool((composer.get('draft_text') or '').strip()),
            },
            'tasks': by_status,
            'task_count': len(tasks),
        }

    # ── Relay (localhost:3333) ────────────────────────────────────
    relay_status, relay_err = _http_json(f'{RELAY_URL}/status')
    relay = {'up': relay_status is not None}
    if relay_status:
        relay.update(relay_status)
    else:
        relay['error'] = relay_err

    # ── Jobs ─────────────────────────────────────────────────────
    jobs_data, _ = _http_json(f'{RELAY_URL}/jobs/status?filter=all')
    raw_jobs = (jobs_data or {}).get('jobs', [])
    # Summarise: active (non-done) first, cap at 10
    active_jobs = [j for j in raw_jobs if j.get('status') not in ('done', 'error')]
    recent_done = [j for j in raw_jobs if j.get('status') in ('done', 'error')][:3]
    jobs = {
        'active': [{'id': j['id'], 'title': j.get('title'), 'status': j.get('status'),
                    'step': j.get('step')} for j in active_jobs[:8]],
        'recent_done': [{'id': j['id'], 'title': j.get('title'), 'status': j.get('status')}
                        for j in recent_done],
        'total': len(raw_jobs),
    }

    # ── Chat channel ─────────────────────────────────────────────
    chat_status, _ = _http_json(f'{RELAY_URL}/chat/status')
    chat = chat_status or {'available': False}

    # ── Pulse renderer (:8088) — HTML is fine; any HTTP response = up ─
    pulse_up, pulse_err = _http_reachable(PULSE_URL)
    pulse = {'up': pulse_up, 'url': PULSE_URL}
    if not pulse_up:
        pulse['error'] = pulse_err

    # ── Ask surface (Pulse polls GET /hud/asks; overlay :3334 is dead) ─
    asks_data, asks_err = _http_json(f'{RELAY_URL}/hud/asks')
    pending = None
    if asks_data is not None:
        pending = len(asks_data.get('asks') or [])
        asks_err = None
    hud = _ask_surface(relay, pulse, pending_asks=pending, asks_err=asks_err)

    _print({
        'claude_desktop': desktop,
        'relay': relay,
        'pulse': pulse,
        'jobs': jobs,
        'chat_channel': chat,
        'hud': hud,
    })
    return 0


# ── Argument parser ───────────────────────────────────────────────────────────

def build_parser():
    guard = argparse.ArgumentParser(add_help=False)
    guard.add_argument(
        '--no-afk-guard', action='store_true',
        help='Bypass team_active lock (tests / emergency only; never the default). '
             'Also honored via CC_SKIP_AFK_GUARD=1.',
    )
    parser = argparse.ArgumentParser(
        prog='cc',
        description='Claude Desktop Control — mode switching, task management, message injection',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    m = sub.add_parser('mode', help='Switch Chat / Cowork / Code mode (⌘1/2/3)',
                       parents=[guard])
    m.add_argument('mode', choices=['chat', 'cowork', 'code'])

    sub.add_parser('new-task', help='Open a new Cowork task (AX New control; no ⌘N keystroke)',
                   parents=[guard])

    inj = sub.add_parser('inject', help='Inject text into a session', parents=[guard])
    inj.add_argument('message', help='Text to inject')
    inj.add_argument('--session', metavar='TITLE', help='Switch to session matching TITLE first')
    inj.add_argument('--new', action='store_true', help='Create a new task first')
    inj.add_argument('--save-restore', action='store_true',
                     help='Save and restore current draft and session')
    inj.add_argument('--cowork-safe', action='store_true',
                     help='No-op: draft preservation is now the default. Kept for documented callers.')
    inj.add_argument('--clobber', action='store_true',
                     help='Overwrite composer without copying an existing draft to clipboard')
    inj.add_argument('--no-dispatch', action='store_true',
                     help='Set text but do not submit')

    rec = sub.add_parser('recent', help='Browse and inject into recent sessions/tasks',
                         parents=[guard])
    rec.add_argument('--list', action='store_true', help='List recent tasks (default action)')
    rec.add_argument('--status', metavar='STATUS',
                     help='Filter by status: running, done, ready, scheduled, dispatch, "awaiting input"')
    rec.add_argument('--pick', metavar='TITLE', help='Select task by title substring')
    rec.add_argument('--inject', metavar='MSG', help='Message to inject after picking')
    rec.add_argument('--cowork-safe', action='store_true',
                     help='No-op: draft preservation is now the default.')
    rec.add_argument('--clobber', action='store_true',
                     help='Overwrite composer without copying an existing draft to clipboard')
    rec.add_argument('--no-dispatch', action='store_true')

    sub.add_parser('status', help='Full machine-readable status: Desktop + relay + Pulse + jobs')

    ins = sub.add_parser('inspect', help='Inspect Claude Desktop AX state')
    ins.add_argument('what',
                     choices=['overview', 'sessions', 'tasks', 'composer', 'mode', 'buttons'],
                     nargs='?', default='overview')


    ha = sub.add_parser('hud-ask', help='Show message in HUD with Confirm/Failed/Partial buttons')
    ha.add_argument('message', help='Message to display in the HUD')
    ha.add_argument('--timeout', type=int, default=30, help='Seconds to wait for response (default 30)')

    sub.add_parser('afk-status', help='Show automation-lock state + live idle seconds')

    aw = sub.add_parser('afk-wait', help='Request team_active and block until granted or timeout')
    aw.add_argument('--reason', default='', help='What the automation is about to do')
    aw.add_argument('--timeout', type=float, default=afk_guard.IDLE_THRESHOLD_S + 10,
                    help='Max seconds to wait (default threshold+10)')

    ast_ = sub.add_parser('afk-set-team',
                          help='Request team_active immediately (fails unless already idle >= threshold)')
    ast_.add_argument('--reason', default='', help='What the automation is about to do')

    sub.add_parser('afk-release', help='Immediately hand control back to user_active (always allowed)')

    return parser




def cmd_hud_ask(args):
    """Show a message in Pulse (via the relay) and wait for Confirm/Failed/Partial.

    CLI contract is unchanged: POST /hud/ask, poll GET /hud/response/:id on :3333.
    Does not touch the retired :3334 overlay.
    """
    message = args.message
    timeout = args.timeout

    body = json.dumps({'message': message, 'timeout': timeout}).encode()
    req = urllib.request.Request(
        f'{RELAY_URL}/hud/ask', data=body,
        headers={'Content-Type': 'application/json'}, method='POST')
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        ask_id = json.loads(resp.read())['id']
    except Exception as e:
        _print({'error': f'HUD not reachable: {e}'}); return 3

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = urllib.request.urlopen(f'{RELAY_URL}/hud/response/{ask_id}', timeout=2)
            data = json.loads(r.read())
            if data.get('status') == 'answered':
                response = data['response']
                _print({'response': response})
                return {'confirm': 0, 'failed': 1, 'partial': 2}.get(response, 3)
        except Exception:
            pass
        time.sleep(0.5)

    _print({'response': 'timeout'})
    return 3

def cmd_afk_status(args):
    """Print current AFK-guard lock state + live idle seconds."""
    data = afk_guard.read_state()
    data['idle_seconds'] = round(afk_guard.idle_seconds(), 1)
    data['idle_threshold_s'] = afk_guard.IDLE_THRESHOLD_S
    data['is_afk'] = afk_guard.is_afk()
    _print(data)
    return 0


def cmd_afk_wait(args):
    """Request team_active and block (bounded) until granted or timeout.
    This is the call automation scripts should make before doing any
    interactive AX/keyboard/mouse work — see afk_guard.py contract."""
    try:
        data = afk_guard.ensure_team_control(
            reason=args.reason or '', timeout=args.timeout)
        _print(data)
        return 0
    except afk_guard.AfkGuardError as e:
        _print({'error': str(e)})
        return 1


def cmd_afk_set_team(args):
    """Request team_active immediately (fails unless already idle >=
    threshold — this does NOT bypass the gate; use the overlay badge for
    an explicit Mike-driven handoff)."""
    try:
        data = afk_guard.request_team_control(reason=args.reason or '')
        _print(data)
        return 0
    except afk_guard.AfkGuardError as e:
        _print({'error': str(e)})
        return 1


def cmd_afk_release(args):
    """Immediately hand control back to user_active. Always allowed."""
    _print(afk_guard.release_to_user())
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    handlers = {
        'mode': cmd_mode,
        'new-task': cmd_new_task,
        'inject': cmd_inject,
        'recent': cmd_recent,
        'inspect': cmd_inspect,
        'status': cmd_status,
        'hud-ask': cmd_hud_ask,
        'afk-status': cmd_afk_status,
        'afk-wait': cmd_afk_wait,
        'afk-set-team': cmd_afk_set_team,
        'afk-release': cmd_afk_release,
    }
    return handlers[args.command](args)


if __name__ == '__main__':
    sys.exit(main())

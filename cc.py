#!/usr/bin/env python3
"""
cc.py — Claude Desktop Control CLI

Commands:
  mode <chat|cowork|code>         Switch mode via ⌘1/2/3
  new-task                        Create a new Cowork task (⌘N)
  inject MSG                      Inject text into current session
    --session TITLE               Switch to session first
    --new                         Create new task first (⌘N)
    --save-restore                Save/restore draft + session
    --cowork-safe                 Notify HUD if draft exists, copy to clipboard
    --no-dispatch                 Set text but don't submit
  recent                          Work with recent sessions/tasks
    --list                        List recents (default)
    --status STATUS               Filter: running/done/ready/scheduled/dispatch/awaiting input
    --pick TITLE                  Select session by title substring
    --inject MSG                  Inject into selected session
    --no-dispatch                 Set text but don't submit
    --cowork-safe                 HUD notify + copy draft if composer has content
  inspect <overview|sessions|tasks|composer|mode|buttons>

Examples:
  cc.py mode cowork
  cc.py new-task
  cc.py inject "What is the status?" --session "FrontRow"
  cc.py inject "Run tests" --new --cowork-safe
  cc.py recent --list --status running
  cc.py recent --pick "FrontRow" --inject "Deploy to staging"
  cc.py inspect mode
  cc.py inspect sessions
"""

import argparse
import json
import sys
import time

import ApplicationServices as AS

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


# ── Subcommand handlers ───────────────────────────────────────────────────────

def cmd_mode(args):
    win = _require_window()
    ok = set_mode(args.mode)
    if ok:
        time.sleep(0.5)
        current = infer_current_mode(win)
        _print({'mode_set': args.mode, 'detected_mode': current})
    return 0 if ok else 1


def cmd_new_task(args):
    win = _require_window()
    new_task(win)
    _print({'status': 'new_task_opened'})
    return 0


def cmd_inject(args):
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
        new_task(win)
        time.sleep(0.5)

    saved_text = ''
    saved_session = None
    if args.save_restore:
        ta = find_text_area(root)
        if ta:
            saved_text = get_attr(ta, 'AXValue') or ''
        saved_session = get_selected_session(win)

    if args.cowork_safe:
        ok = cowork_safe_inject(root, msg, dispatch=not args.no_dispatch)
    else:
        if not set_prompt_text(root, msg):
            return 1
        if args.no_dispatch:
            _print({'status': 'text_set', 'message': msg})
            return 0
        ok = submit_prompt(root)

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
    root = _content_root(win)

    tasks = list_tasks(win, status_filter=args.status)

    if args.list or not args.pick:
        rows = [{'title': t['title'], 'status': t['status'],
                 'clean_title': t['clean_title'], 'selected': t['selected']}
                for t in tasks]
        _print({'tasks': rows, 'count': len(rows)})
        return 0

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
        if args.cowork_safe:
            ok = cowork_safe_inject(root, args.inject, dispatch=not args.no_dispatch)
        else:
            if not set_prompt_text(root, args.inject):
                return 1
            if args.no_dispatch:
                _print({'status': 'text_set', 'picked': match['title']})
                return 0
            ok = submit_prompt(root)
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
    """Full machine-readable status: Claude Desktop AX + relay + jobs + HUD.
    Designed to give an LLM complete situational awareness in one call.
    """
    import urllib.request as _ur

    def _fetch(url, timeout=1.5):
        try:
            r = _ur.urlopen(url, timeout=timeout)
            return json.loads(r.read()), None
        except Exception as e:
            return None, str(e)

    def _post(url, body, timeout=1.5):
        try:
            req = _ur.Request(url,
                data=json.dumps(body).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST')
            r = _ur.urlopen(req, timeout=timeout)
            return json.loads(r.read()), None
        except Exception as e:
            return None, str(e)

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
                'has_draft': bool((composer.get('draft_text') or '').strip()
                                  and composer.get('draft_text', '').strip() != 'Reply...'),
            },
            'tasks': by_status,
            'task_count': len(tasks),
        }

    # ── Relay (localhost:3333) ────────────────────────────────────
    relay_status, relay_err = _fetch('http://localhost:3333/status')
    relay = {'up': relay_status is not None}
    if relay_status:
        relay.update(relay_status)
    else:
        relay['error'] = relay_err

    # ── Jobs ─────────────────────────────────────────────────────
    jobs_data, _ = _fetch('http://localhost:3333/jobs/status?filter=all')
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
    chat_status, _ = _fetch('http://localhost:3333/chat/status')
    chat = chat_status or {'available': False}

    # ── HUD (localhost:3334) ──────────────────────────────────────
    hud_status, hud_err = _fetch('http://localhost:3334/wv-status')
    hud = {'up': hud_status is not None}
    if hud_status:
        hud.update(hud_status)
    else:
        hud['error'] = hud_err

    _print({
        'claude_desktop': desktop,
        'relay': relay,
        'jobs': jobs,
        'chat_channel': chat,
        'hud': hud,
    })
    return 0


# ── Argument parser ───────────────────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        prog='cc',
        description='Claude Desktop Control — mode switching, task management, message injection',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    m = sub.add_parser('mode', help='Switch Chat / Cowork / Code mode (⌘1/2/3)')
    m.add_argument('mode', choices=['chat', 'cowork', 'code'])

    sub.add_parser('new-task', help='Open a new Cowork task (⌘N)')

    inj = sub.add_parser('inject', help='Inject text into a session')
    inj.add_argument('message', help='Text to inject')
    inj.add_argument('--session', metavar='TITLE', help='Switch to session matching TITLE first')
    inj.add_argument('--new', action='store_true', help='Create a new task first (⌘N)')
    inj.add_argument('--save-restore', action='store_true',
                     help='Save and restore current draft and session')
    inj.add_argument('--cowork-safe', action='store_true',
                     help='Notify HUD + copy draft to clipboard if composer has content')
    inj.add_argument('--no-dispatch', action='store_true',
                     help='Set text but do not submit')

    rec = sub.add_parser('recent', help='Browse and inject into recent sessions/tasks')
    rec.add_argument('--list', action='store_true', help='List recent tasks (default action)')
    rec.add_argument('--status', metavar='STATUS',
                     help='Filter by status: running, done, ready, scheduled, dispatch, "awaiting input"')
    rec.add_argument('--pick', metavar='TITLE', help='Select task by title substring')
    rec.add_argument('--inject', metavar='MSG', help='Message to inject after picking')
    rec.add_argument('--cowork-safe', action='store_true')
    rec.add_argument('--no-dispatch', action='store_true')

    sub.add_parser('status', help='Full machine-readable status: Desktop + relay + jobs + HUD')

    ins = sub.add_parser('inspect', help='Inspect Claude Desktop AX state')
    ins.add_argument('what',
                     choices=['overview', 'sessions', 'tasks', 'composer', 'mode', 'buttons'],
                     nargs='?', default='overview')

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    handlers = {
        'mode': cmd_mode,
        'new-task': cmd_new_task,
        'inject': cmd_inject,
        'recent': cmd_recent,
        'inspect': cmd_inspect,
        'status': cmd_status,
    }
    return handlers[args.command](args)


if __name__ == '__main__':
    sys.exit(main())

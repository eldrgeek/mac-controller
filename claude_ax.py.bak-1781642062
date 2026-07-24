"""
Shared Accessibility helpers for Claude Desktop automation.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

try:
    import ApplicationServices as AS
    import AppKit
    import Quartz
except ModuleNotFoundError as exc:
    missing = exc.name or 'PyObjC module'
    raise SystemExit(
        f"ERROR: Missing macOS Python bridge module '{missing}'.\n"
        "Use a Python with PyObjC installed, for example:\n"
        "  /opt/homebrew/bin/python3 /Users/mikewolf/Projects/yeshie/scripts/ax-inject.py --help\n"
        "If needed, install PyObjC into that interpreter:\n"
        "  /opt/homebrew/bin/python3 -m pip install pyobjc-framework-ApplicationServices pyobjc-framework-Cocoa pyobjc-framework-Quartz\n"
    ) from exc


CLAUDE_BUNDLE_ID = 'com.anthropic.claudefordesktop'


def get_attr(elem, attr):
    err, val = AS.AXUIElementCopyAttributeValue(elem, attr, None)
    return val if err == 0 else None


def find_roles(elem, targets, depth=0, max_depth=35, results=None):
    if results is None:
        results = []
    if depth > max_depth:
        return results
    role = get_attr(elem, 'AXRole')
    if role in targets:
        results.append((role, elem))
    children = get_attr(elem, 'AXChildren')
    if children:
        for child in children:
            find_roles(child, targets, depth + 1, max_depth, results)
    return results


def walk_tree(elem, depth=0, max_depth=35, results=None):
    if results is None:
        results = []
    if depth > max_depth:
        return results
    results.append(elem)
    children = get_attr(elem, 'AXChildren')
    if children:
        for child in children:
            walk_tree(child, depth + 1, max_depth, results)
    return results


_UI_BUTTONS = {
    'Queue message', 'Send message', 'New chat', 'Search chats',
    'Close', 'Minimize', 'Zoom', 'New Conversation', 'Settings',
    'Start new chat', 'Menu', 'Back', 'Toggle sidebar', '',
}

_NON_SESSION_LABELS = {
    'Collapse sidebar', 'Search', 'Chat', 'Cowork', 'Code', 'Projects',
    'Customize', 'Artifacts', 'Pinned', 'Recents', 'View all',
    'Get apps and extensions', 'Share chat', 'Retry', 'Edit', 'Copy',
    'Give positive feedback', 'Give negative feedback',
    'Scroll to bottom', 'Press and hold to record',
}


def find_nav_buttons(elem, depth=0, max_depth=35, results=None):
    """Collect likely session/nav buttons and ignore known chrome controls."""
    if results is None:
        results = []
    if depth > max_depth:
        return results
    role = get_attr(elem, 'AXRole')
    if role == 'AXButton':
        title = get_attr(elem, 'AXTitle') or get_attr(elem, 'AXDescription') or ''
        normalized = title.strip()
        if (
            normalized
            and normalized not in _UI_BUTTONS
            and normalized not in _NON_SESSION_LABELS
            and not normalized.startswith('New chat')
            and len(normalized) > 2
        ):
            selected = get_attr(elem, 'AXSelected') or False
            results.append({'title': normalized, 'elem': elem, 'selected': bool(selected)})
    children = get_attr(elem, 'AXChildren')
    if children:
        for child in children:
            find_nav_buttons(child, depth + 1, max_depth, results)
    return results


def find_session_button(win, target_title):
    """Find a sidebar session button — exact match first, then substring."""
    buttons = find_nav_buttons(win)
    tl = target_title.lower()
    for button in buttons:
        if button['title'].lower() == tl:
            return button
    for button in buttons:
        if tl in button['title'].lower():
            return button
    return None


def get_selected_session(win):
    """Return the currently selected/highlighted session button, or None."""
    for button in find_nav_buttons(win):
        if button['selected']:
            return button
    web_title = get_active_web_title(win)
    if web_title:
        match = find_session_button(win, web_title)
        if match:
            return match
    return None


def list_sessions(win):
    """Return sidebar session buttons in display order."""
    return find_nav_buttons(win)


def find_text_area(win):
    found = find_roles(win, ['AXTextArea'])
    for _, elem in found:
        desc = get_attr(elem, 'AXDescription') or ''
        placeholder = get_attr(elem, 'AXPlaceholderValue') or ''
        if (
            'prompt' in desc.lower()
            or 'reply' in placeholder.lower()
            or 'prompt' in placeholder.lower()
            or 'write' in desc.lower()
        ):
            return elem
    return found[0][1] if found else None


def wait_for_text_area(win, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        text_area = find_text_area(win)
        if text_area:
            return text_area
        time.sleep(0.25)
    return None


def find_send_button(win):
    for _, elem in find_roles(win, ['AXButton']):
        desc = get_attr(elem, 'AXDescription') or ''
        if desc in ('Queue message', 'Send message'):
            return (desc, elem)
    return None


def submit_prompt(win):
    """Submit the current composer contents without modifying them."""
    text_area = wait_for_text_area(win, timeout=5.0)
    if not text_area:
        print('ERROR: text area not found', file=sys.stderr)
        return False

    send_btn = find_send_button(win)
    if send_btn:
        desc, button = send_btn
        AS.AXUIElementPerformAction(button, 'AXPress')
        print(f'sent via {desc}')
    else:
        AS.AXUIElementSetAttributeValue(text_area, 'AXFocused', True)
        time.sleep(0.1)
        send_return()
        print('sent via Return (idle mode)')
    return True


def list_controls(win, roles=None, max_depth=35):
    controls = []
    for elem in walk_tree(win, max_depth=max_depth):
        role = get_attr(elem, 'AXRole')
        if roles and role not in roles:
            continue
        title = get_attr(elem, 'AXTitle')
        description = get_attr(elem, 'AXDescription')
        placeholder = get_attr(elem, 'AXPlaceholderValue')
        value = get_attr(elem, 'AXValue')
        selected = get_attr(elem, 'AXSelected')
        if any(x not in (None, '', False) for x in (title, description, placeholder, value, selected)):
            controls.append({
                'role': role,
                'title': title,
                'description': description,
                'placeholder': placeholder,
                'value': value,
                'selected': selected,
                'elem': elem,
            })
    return controls


def get_active_web_title(win):
    for _, elem in find_roles(win, ['AXWebArea']):
        title = get_attr(elem, 'AXTitle') or ''
        if title.endswith(' - Claude'):
            return title[:-9]
    return None


def normalize_key_name(name):
    lowered = name.lower()
    mapping = {
        'return': 0x24,
        'enter': 0x24,
        'escape': 0x35,
        'esc': 0x35,
        'space': 0x31,
        'tab': 0x30,
        'up': 0x7E,
        'down': 0x7D,
        'left': 0x7B,
        'right': 0x7C,
    }
    if lowered in mapping:
        return mapping[lowered]
    if len(name) == 1:
        return ord(name.upper())
    raise ValueError(f'Unsupported key: {name}')


def press_key(key, modifiers=None):
    modifiers = modifiers or []
    src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    keycode = normalize_key_name(key)
    down = Quartz.CGEventCreateKeyboardEvent(src, keycode, True)
    up = Quartz.CGEventCreateKeyboardEvent(src, keycode, False)
    flags = 0
    modifier_flags = {
        'cmd': getattr(Quartz, 'kCGEventFlagMaskCommand', 0),
        'command': getattr(Quartz, 'kCGEventFlagMaskCommand', 0),
        'shift': getattr(Quartz, 'kCGEventFlagMaskShift', 0),
        'alt': getattr(Quartz, 'kCGEventFlagMaskAlternate', 0),
        'option': getattr(Quartz, 'kCGEventFlagMaskAlternate', 0),
        'ctrl': getattr(Quartz, 'kCGEventFlagMaskControl', 0),
        'control': getattr(Quartz, 'kCGEventFlagMaskControl', 0),
    }
    for modifier in modifiers:
        flags |= modifier_flags.get(modifier.lower(), 0)
    if flags:
        setter = getattr(Quartz, 'CGEventSetFlags', None)
        if setter:
            setter(down, flags)
            setter(up, flags)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)


def match_control(control, title=None, contains=None, description=None, role=None):
    if role and control['role'] != role:
        return False
    if title and (control['title'] or '').lower() != title.lower():
        return False
    if contains:
        haystacks = [
            control.get('title') or '',
            control.get('description') or '',
            control.get('placeholder') or '',
        ]
        needle = contains.lower()
        if not any(needle in haystack.lower() for haystack in haystacks):
            return False
    if description and (control.get('description') or '').lower() != description.lower():
        return False
    return True


def find_control(win, title=None, contains=None, description=None, role=None):
    for control in list_controls(win):
        if match_control(control, title=title, contains=contains, description=description, role=role):
            return control
    return None


def click_control(win, title=None, contains=None, description=None, role=None):
    control = find_control(win, title=title, contains=contains, description=description, role=role)
    if not control:
        print('ERROR: control not found', file=sys.stderr)
        return False
    AS.AXUIElementPerformAction(control['elem'], 'AXPress')
    return True


def click_first_match(win, matchers):
    """Try multiple control matchers in order until one succeeds."""
    for matcher in matchers:
        if click_control(
            win,
            title=matcher.get('title'),
            contains=matcher.get('contains'),
            description=matcher.get('description'),
            role=matcher.get('role'),
        ):
            return True
    return False


def set_prompt_text(win, text):
    text_area = wait_for_text_area(win, timeout=5.0)
    if not text_area:
        print('ERROR: text area not found', file=sys.stderr)
        return False
    err = AS.AXUIElementSetAttributeValue(text_area, 'AXValue', text)
    if err != 0:
        print(f'ERROR: could not set AXValue (err={err})', file=sys.stderr)
        return False
    return True


def get_composer_state(win):
    text_area = find_text_area(win)
    send_btn = find_send_button(win)
    return {
        'has_text_area': bool(text_area),
        'draft_text': (get_attr(text_area, 'AXValue') or '') if text_area else '',
        'send_action': send_btn[0] if send_btn else None,
        'active_web_title': get_active_web_title(win),
    }


def serialize_tree(elem, depth=0, max_depth=5):
    node = {
        'role': get_attr(elem, 'AXRole'),
        'title': get_attr(elem, 'AXTitle'),
        'description': get_attr(elem, 'AXDescription'),
        'placeholder': get_attr(elem, 'AXPlaceholderValue'),
        'value': get_attr(elem, 'AXValue'),
        'selected': get_attr(elem, 'AXSelected'),
    }
    if depth >= max_depth:
        return node
    children = get_attr(elem, 'AXChildren') or []
    if children:
        node['children'] = [serialize_tree(child, depth + 1, max_depth) for child in children]
    return node


def print_json(data):
    json.dump(data, sys.stdout, indent=2)
    sys.stdout.write('\n')


def send_return():
    """Post a Return keystroke via CGEvent."""
    src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    down = Quartz.CGEventCreateKeyboardEvent(src, 0x24, True)
    up = Quartz.CGEventCreateKeyboardEvent(src, 0x24, False)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)


def inject_message(win, msg):
    """Set text in the active session's text area and submit."""
    if not set_prompt_text(win, msg):
        return False
    return submit_prompt(win)


def build_parser():
    parser = argparse.ArgumentParser(description='Inject a message into Claude Desktop')
    parser.add_argument(
        '--session',
        default=None,
        metavar='TITLE',
        help='Target session title — switch to that session before injecting',
    )
    parser.add_argument(
        '--save-restore',
        action='store_true',
        help='Save current session text and restore it (plus switch back) after injection',
    )
    parser.add_argument('message', nargs='+')
    return parser


def find_claude_app():
    workspace = AppKit.NSWorkspace.sharedWorkspace()
    for app in workspace.runningApplications():
        if app.bundleIdentifier() == CLAUDE_BUNDLE_ID:
            return app
    print('ERROR: Claude Desktop not running', file=sys.stderr)
    return None


def activate_claude():
    app = find_claude_app()
    if not app:
        return False
    options = getattr(AppKit, 'NSApplicationActivateIgnoringOtherApps', 1)
    activate = getattr(app, 'activateWithOptions_', None)
    if activate:
        activate(options)
    return True



def get_content_root(app_elem, timeout=5.0):
    """Return the AXWebArea root of Claude's UI (works with Claude Desktop 1.3561+).

    Claude Desktop 1.3561+ no longer exposes WKWebView content by walking from
    the native window (only 14 native elements visible).  Instead we must:
      1. Bring Claude to the foreground (activateWithOptions_)
      2. Poll AXFocusedUIElement on the app element — once Claude is front,
         this returns the AXWebArea with the full 700+ element web content tree.

    NOTE: This requires Claude to be the frontmost app.  If running from a
    background script, use osascript to activate first as a belt-and-suspenders.
    """
    import subprocess as _sp

    # Primary: AppKit activation
    ws = AppKit.NSWorkspace.sharedWorkspace()
    activated = False
    for running_app in ws.runningApplications():
        if running_app.bundleIdentifier() == CLAUDE_BUNDLE_ID:
            activated = running_app.activateWithOptions_(
                AppKit.NSApplicationActivateIgnoringOtherApps)
            break

    # Belt-and-suspenders: osascript activation (works even from background scripts)
    _sp.run(
        ['osascript', '-e',
         'tell application "Claude" to activate'],
        capture_output=True, timeout=3,
    )

    # Give the window time to take focus before polling
    time.sleep(0.4)

    deadline = time.time() + timeout
    while time.time() < deadline:
        err, focused = AS.AXUIElementCopyAttributeValue(
            app_elem, 'AXFocusedUIElement', None)
        if err == 0 and focused:
            role = get_attr(focused, 'AXRole')
            kids = get_attr(focused, 'AXChildren') or []
            if role == 'AXWebArea':
                return focused  # accept even if empty — new blank pane has no children yet
        time.sleep(0.25)
    return None


def find_claude_window():
    app = find_claude_app()
    if not app:
        return None

    app_elem = AS.AXUIElementCreateApplication(app.processIdentifier())
    err, windows = AS.AXUIElementCopyAttributeValue(app_elem, 'AXWindows', None)
    if err != 0 or not windows:
        print('ERROR: no Claude Desktop windows found', file=sys.stderr)
        return None

    return windows[0]


def run(argv=None):
    args = build_parser().parse_args(argv)
    msg = ' '.join(args.message)

    win = find_claude_window()
    if not win:
        return 1

    # Claude Desktop 1.3561+ hides WKWebView content from the native window tree.
    # Use AXFocusedUIElement (returns AXWebArea) for text-area / button lookups.
    _app = find_claude_app()
    _app_elem = AS.AXUIElementCreateApplication(_app.processIdentifier()) if _app else None
    content_root = (get_content_root(_app_elem) if _app_elem else None) or win

    if args.session:
        target = find_session_button(win, args.session)
        if not target:
            print(f'ERROR: session "{args.session}" not found in sidebar', file=sys.stderr)
            return 1

        saved_text = ''
        saved_session = None

        if args.save_restore:
            current_ta = find_text_area(content_root)
            if current_ta:
                saved_text = get_attr(current_ta, 'AXValue') or ''
            saved_session = get_selected_session(win)
            if saved_session:
                print(f'saved: session={saved_session["title"]!r}  text={saved_text[:40]!r}')

        print(f'switching to: {target["title"]!r}')
        AS.AXUIElementPerformAction(target['elem'], 'AXPress')
        time.sleep(1.2)

        ok = inject_message(content_root, msg)

        if args.save_restore and saved_session:
            time.sleep(0.5)
            print(f'restoring: {saved_session["title"]!r}')
            AS.AXUIElementPerformAction(saved_session['elem'], 'AXPress')
            time.sleep(0.8)
            if saved_text:
                restored_ta = wait_for_text_area(win, timeout=3.0)
                if restored_ta:
                    AS.AXUIElementSetAttributeValue(restored_ta, 'AXValue', saved_text)
                    print(f'restored text: {saved_text[:40]!r}')

        return 0 if ok else 1

    # ── Save current draft before injecting ──────────────────────────────────
    current_ta = find_text_area(content_root)
    saved_draft = (get_attr(current_ta, 'AXValue') or '') if current_ta else ''

    # ── HUD / system notification ─────────────────────────────────────────────
    import subprocess as _sp2
    import urllib.request as _ur
    import json as _js
    short_msg = msg[:72] + ('…' if len(msg) > 72 else '')
    notif_title = 'SOMA'
    notif_body  = f'Injecting: {short_msg}' + (' (draft preserved)' if saved_draft else '')

    # Try relay HUD first (silent fail if relay isn't running)
    try:
        _ur.urlopen(
            _ur.Request(
                'http://localhost:3333/notify',
                data=_js.dumps({'message': notif_body, 'title': notif_title}).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST',
            ),
            timeout=1,
        )
    except Exception:
        pass  # relay not running — fall through to osascript

    # osascript notification (always-available fallback)
    _sp2.run(
        ['osascript', '-e',
         f'display notification {_js.dumps(notif_body)} with title {_js.dumps(notif_title)}'],
        capture_output=True, timeout=3,
    )

    # ── Inject ────────────────────────────────────────────────────────────────
    ok = inject_message(content_root, msg)

    # ── Restore draft ─────────────────────────────────────────────────────────
    if saved_draft and ok:
        time.sleep(0.8)   # let Claude register the submitted message
        restore_ta = find_text_area(content_root)
        if restore_ta:
            AS.AXUIElementSetAttributeValue(restore_ta, 'AXValue', saved_draft)
            print(f'restored draft ({len(saved_draft)} chars): {saved_draft[:60]!r}')

    return 0 if ok else 1


def main():
    sys.exit(run())


# ── Mode switching ────────────────────────────────────────────────────────────

MODE_KEYS = {'chat': '1', 'cowork': '2', 'code': '3'}
MODE_DESCRIPTIONS = {'chat': 'Chat', 'cowork': 'Cowork', 'code': 'Code'}


def set_mode(mode: str) -> bool:
    """Switch Claude Desktop to Chat (⌘1), Cowork (⌘2), or Code (⌘3).
    Uses osascript System Events for reliable keystroke delivery.
    """
    import subprocess as _sp
    mode = mode.lower()
    key = MODE_KEYS.get(mode)
    if not key:
        print(f'ERROR: unknown mode {mode!r}. Use chat, cowork, or code.', file=sys.stderr)
        return False
    # osascript is more reliable than CGEvent for focus-sensitive keystrokes
    result = _sp.run([
        'osascript',
        '-e', 'tell application "Claude" to activate',
        '-e', 'delay 0.4',
        '-e', f'tell application "System Events" to keystroke "{key}" using command down',
    ], capture_output=True, timeout=5)
    time.sleep(0.6)
    return result.returncode == 0


def get_current_mode(win) -> 'str | None':
    """Return the currently active mode: 'chat', 'cowork', 'code', or None."""
    for mode_name, desc in MODE_DESCRIPTIONS.items():
        ctrl = find_control(win, description=desc)
        if ctrl:
            sel = get_attr(ctrl['elem'], 'AXSelected')
            val = get_attr(ctrl['elem'], 'AXValue')
            if sel or val in (1, '1'):
                return mode_name
    return None


# ── Task management ───────────────────────────────────────────────────────────

TASK_STATUSES = ('Running', 'Done', 'Ready', 'Scheduled', 'Awaiting input', 'Dispatch')


def parse_task_status(title: str) -> 'tuple[str | None, str]':
    """Split 'Running Foo bar' -> ('running', 'Foo bar'). Returns (None, title) if no prefix."""
    for status in TASK_STATUSES:
        if title.startswith(status + ' '):
            return status.lower(), title[len(status) + 1:]
    return None, title


def list_tasks(win, status_filter: 'str | None' = None) -> list:
    """Return sidebar task buttons, optionally filtered by status prefix.
    Skips bare section-filter labels (Scheduled, Live artifacts, Dispatch, etc.)
    Each entry: {'title', 'status', 'clean_title', 'selected', 'elem'}
    """
    results = []
    for btn in find_nav_buttons(win):
        title = btn['title']
        status, clean = parse_task_status(title)
        # Skip bare section-filter labels (no status prefix and matches known label)
        if status is None and title in _SECTION_FILTER_LABELS:
            continue
        if status_filter and status != status_filter.lower():
            continue
        results.append({
            'title': btn['title'],
            'status': status,
            'clean_title': clean,
            'selected': btn['selected'],
            'elem': btn['elem'],
        })
    return results


def new_task(win) -> bool:
    """Open a new session/task appropriate for the current mode.
    - Cowork: clicks 'New task ⌘N'
    - Code:   clicks 'New session ⌘N'
    - Chat:   clicks button containing 'New chat'
    Falls back to ⌘N via osascript in all cases.
    Sleeps 0.8s for UI settle.
    """
    import subprocess as _sp
    mode = infer_current_mode(win)
    if mode == 'cowork':
        ok = click_control(win, title='New task \u2318N', role='AXButton')
    elif mode == 'code':
        ok = click_control(win, title='New session \u2318N', role='AXButton')
    else:
        ok = click_control(win, contains='New chat', role='AXButton')
    if not ok:
        _sp.run([
            'osascript',
            '-e', 'tell application "Claude" to activate',
            '-e', 'delay 0.2',
            '-e', 'tell application "System Events" to keystroke "n" using command down',
        ], capture_output=True, timeout=5)
    time.sleep(0.8)
    return True


# ── Notifications ─────────────────────────────────────────────────────────────

def _notify(title: str, body: str) -> None:
    """Send HUD via relay (localhost:3333/notify) with osascript fallback."""
    import subprocess as _sp
    import urllib.request as _ur
    import json as _js
    try:
        _ur.urlopen(
            _ur.Request(
                'http://localhost:3333/notify',
                data=_js.dumps({'message': body, 'title': title}).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST',
            ),
            timeout=1,
        )
    except Exception:
        pass
    _sp.run(
        ['osascript', '-e',
         f'display notification {_js.dumps(body)} with title {_js.dumps(title)}'],
        capture_output=True, timeout=3,
    )


# ── CoWork-safe injection ─────────────────────────────────────────────────────

def cowork_safe_inject(win, msg: str, dispatch: bool = True) -> bool:
    """CoWork-aware injection:
    1. If composer has a real draft, notify via HUD and copy draft to clipboard.
    2. Inject msg into the composer.
    3. If dispatch=True, submit (Queue or Send).
    """
    import subprocess as _sp
    ta = find_text_area(win)
    draft = (get_attr(ta, 'AXValue') or '') if ta else ''
    real_draft = draft.strip() not in ('', 'Reply...')
    if real_draft:
        _notify('CoWork', f'Draft preserved ({len(draft)} chars). Injecting new message.')
        _sp.run(['pbcopy'], input=draft.encode(), check=True)
        print(f'Draft copied to clipboard: {draft[:80]!r}', file=sys.stderr)
    if not set_prompt_text(win, msg):
        return False
    if dispatch:
        return submit_prompt(win)
    return True


# ── Mode detection (revised) ──────────────────────────────────────────────────
# The Chat/Cowork/Code buttons don't expose AXSelected/AXValue when active —
# React renders selection state only via CSS, invisible to AX.
# We infer mode from what's present in the sidebar instead.

_SECTION_FILTER_LABELS = {
    'Scheduled', 'Live artifacts', 'Dispatch', 'Customize',
    'Projects', 'Pinned', 'Recents', 'View all', 'New task \u2318N',
}


def infer_current_mode(win) -> 'str | None':
    """Infer active mode from sidebar content (React doesn't expose tab state via AX).
    - Cowork: 'New task ⌘N' button present
    - Chat:   no 'New task ⌘N', but sidebar has 'New chat' or regular sessions
    - Code:   neither of the above
    Returns 'cowork', 'chat', 'code', or None.
    """
    buttons_with_titles = set()
    for btn in find_nav_buttons(win):
        buttons_with_titles.add(btn['title'])

    if 'New task \u2318N' in buttons_with_titles:
        return 'cowork'
    # Chat mode has a 'New chat' button (may appear in UI buttons set, bypass that)
    for _, elem in find_roles(win, ['AXButton'], max_depth=20):
        title = get_attr(elem, 'AXTitle') or ''
        if 'New chat' in title or 'New Chat' in title:
            return 'chat'
    return 'code'

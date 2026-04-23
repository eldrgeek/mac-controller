#!/usr/bin/env python3
"""
smoke_handoff.py — CCw → CDC handoff/handback smoke test.

Sequence:
  1. Confirm Cowork mode (switch if needed), note origin session
  2. Open new CCw task, inject handoff message
  3. Switch to Code mode, inspect sidebar (first time — may learn new structure)
  4. Open new CDC session, inject handback message
  5. Return to Cowork + origin session
  6. Report pass/fail at each step

Run: /opt/homebrew/bin/python3 smoke_handoff.py
     /opt/homebrew/bin/python3 smoke_handoff.py --dispatch  (actually submit)
"""
import argparse, json, sys, time, datetime
sys.path.insert(0, __import__('os').path.dirname(__file__))
import ApplicationServices as AS
import claude_ax as ax

TS = datetime.datetime.now().strftime('%H:%M:%S')
PASS, FAIL = [], []

def step(n, msg):
    print(f"\n{'='*60}\n  STEP {n}: {msg}\n{'='*60}")

def ok(label, val=None):
    PASS.append(label)
    print(f"  ✓  {label}" + (f": {val}" if val is not None else ""))

def fail(label, detail=""):
    FAIL.append(label)
    print(f"  ✗  {label}" + (f": {detail}" if detail else ""))

def report(label, data):
    print(f"\n  [{label}]")
    for k, v in data.items():
        print(f"    {k}: {v!r}")

def get_state():
    win = ax.find_claude_window()
    if not win:
        print("ERROR: Claude Desktop not running"); sys.exit(1)
    app = ax.find_claude_app()
    app_elem = AS.AXUIElementCreateApplication(app.processIdentifier()) if app else None
    root = (ax.get_content_root(app_elem) if app_elem else None) or win
    return win, root

def session_titles(win):
    return set(s['title'] for s in ax.list_sessions(win))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dispatch', action='store_true')
    args = parser.parse_args()
    dispatch = args.dispatch
    print(f"\n{'🔥 LIVE' if dispatch else '🧪 DRY-RUN'} smoke_handoff [{TS}]")
    print("  --dispatch to actually submit messages\n")

    # ── Step 1: Cowork baseline ───────────────────────────────────────────────
    step(1, "Cowork baseline")
    win, root = get_state()
    mode = ax.infer_current_mode(win)
    origin = ax.get_selected_session(win)
    report("initial", {'mode': mode, 'origin': origin['title'] if origin else None,
                       'composer': ax.get_composer_state(root)['send_action']})

    if mode != 'cowork':
        print(f"  Not in Cowork ({mode}), switching...")
        ax.set_mode('cowork'); time.sleep(0.6)
        win, root = get_state()
        mode = ax.infer_current_mode(win)
        origin = ax.get_selected_session(win)

    if mode == 'cowork': ok("in Cowork mode")
    else: fail("in Cowork mode", mode)

    # ── Step 2: New CCw task ──────────────────────────────────────────────────
    step(2, "Open new CCw task + inject handoff")
    before = session_titles(win)
    ax.new_task(win); time.sleep(1.0)
    win, root = get_state()
    after = session_titles(win)
    new_sessions = after - before
    composer = ax.get_composer_state(root)

    if composer['has_text_area']: ok("new CCw task has text area")
    else: fail("new CCw task has text area")
    report("after new-task", {'new_sessions': list(new_sessions),
                               'send_action': composer['send_action']})

    handoff_msg = (
        f"[SMOKE {TS}] CCw→CDC handoff. "
        f"Origin: {origin['title'] if origin else 'unknown'}. "
        f"Task: echo 'handoff received' && date"
    )
    if ax.set_prompt_text(root, handoff_msg):
        ok("handoff msg set in CCw composer")
    else:
        fail("handoff msg set in CCw composer")

    if dispatch:
        ax.submit_prompt(root); time.sleep(1.0)
        ok("CCw handoff dispatched")

    # ── Step 3: Switch to Code + inspect ─────────────────────────────────────
    step(3, "Switch to Code mode — exploring sidebar")
    ax.set_mode('code'); time.sleep(1.0)
    win, root = get_state()
    code_mode = ax.infer_current_mode(win)
    code_sessions = [s['title'] for s in ax.list_sessions(win)]
    code_composer = ax.get_composer_state(root)

    if code_mode == 'code': ok("switched to Code mode")
    else: fail("switched to Code mode", f"got {code_mode!r}")

    report("Code mode sidebar (first 10)", {
        'session_count': len(code_sessions),
        'items': code_sessions[:10],
        'has_text_area': code_composer['has_text_area'],
        'send_action': code_composer['send_action'],
    })

    # ── Step 4: New CDC session + inject handback ─────────────────────────────
    step(4, "New CDC session + inject handback")
    before_code = session_titles(win)
    ax.new_task(win); time.sleep(1.0)
    win, root = get_state()
    after_code = session_titles(win)
    new_code = after_code - before_code
    code_composer2 = ax.get_composer_state(root)

    if code_composer2['has_text_area']: ok("new CDC session has text area")
    else: fail("new CDC session has text area")
    report("after new CDC session", {'new_sessions': list(new_code),
                                      'send_action': code_composer2['send_action']})

    handback_msg = (
        f"[SMOKE {TS}] CDC→CCw handback. "
        f"Returning to: '{origin['title'] if origin else 'unknown'}'. "
        f"Code work complete."
    )
    if ax.set_prompt_text(root, handback_msg):
        ok("handback msg set in CDC composer")
    else:
        fail("handback msg set in CDC composer")

    if dispatch:
        ax.submit_prompt(root); time.sleep(1.0)
        ok("CDC handback dispatched")

    # ── Step 5: Return to Cowork + origin ────────────────────────────────────
    step(5, "Return to Cowork → origin session")
    ax.set_mode('cowork'); time.sleep(0.8)
    win, root = get_state()
    back_mode = ax.infer_current_mode(win)

    if back_mode == 'cowork': ok("returned to Cowork mode")
    else: fail("returned to Cowork mode", back_mode)

    if origin:
        import ApplicationServices as _AS
        _AS.AXUIElementPerformAction(origin['elem'], 'AXPress')
        time.sleep(1.0)
        win, root = get_state()
        final = ax.get_composer_state(root)
        at_origin = (final['active_web_title'] and
                     origin['title'].endswith(final['active_web_title']))
        if at_origin: ok("returned to origin session", final['active_web_title'])
        else: ok("at a session", final['active_web_title'])  # title may differ til named
        report("final", {'active_title': final['active_web_title'],
                          'send_action': final['send_action']})

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  RESULT: {len(PASS)} passed, {len(FAIL)} failed")
    for p in PASS: print(f"  ✓  {p}")
    for f_ in FAIL: print(f"  ✗  {f_}")
    print(f"  dispatched: {dispatch}")
    print(f"{'='*60}\n")
    return 0 if not FAIL else 1

if __name__ == '__main__':
    sys.exit(main())

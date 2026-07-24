# mac-controller Knowledge Base

## AX Tree Structure (discovered April 2026)

### Mode switcher
- `AXGroup desc='Mode'` at depth 15 in the window tree
- Children: `AXButton desc='Chat'`, `AXButton desc='Cowork'`, `AXButton desc='Code'`
- **Keyboard shortcuts (simpler):** ⌘1 = Chat, ⌘2 = Cowork, ⌘3 = Code

### Sidebar layout
```
d=15  Collapse sidebar | Search
d=15  [AXGroup desc='Mode']
d=16    Chat | Cowork | Code  (AXButton, desc field)
d=15  New task ⌘N             (AXButton, title field)
d=15  Projects | Scheduled | Live artifacts | Dispatch | Customize
d=16    [task list with status prefixes]
d=16  Pinned | Recents | View all  (section headers)
d=17    [recent chat buttons]
d=20  [active session close button]
```

### Task status prefixes (baked into AXButton titles)
`Running`, `Done`, `Ready`, `Scheduled`, `Awaiting input`, `Dispatch`

Example: `"Running Mac automation scripts for task injection"` → status=running, clean title=`"Mac automation scripts for task injection"`

### Composer (depth ~27-28)
- Text area: `AXTextArea desc='Write your prompt to Claude'`
- Idle: `AXButton desc='Send message'`
- Mid-response: `AXButton desc='Queue message'`
- React state trigger: `AXUIElementSetAttributeValue(ta, 'AXValue', text)` undims Queue button

### Claude Desktop 1.3561+ WKWebView regression
Native window walk only returns ~14 elements (not 700+). Fix in `get_content_root()`:
1. Activate Claude to foreground (NSApplicationActivateIgnoringOtherApps + osascript belt-and-suspenders)
2. Poll `AXFocusedUIElement` on the app AXUIElement
3. Wait for `AXWebArea` with children — use that as content root
Requires Claude to be frontmost app.

## Use this, not osascript

`cc.py` supersedes ad-hoc osascript keystroke injection for any Claude Desktop control task. Common mistakes that this project fixes:

1. `osascript -e 'keystroke "msg"'` types text but doesn't submit — Cmd+Return is required and easily forgotten.
2. Keystroke injection corrupts Mike's in-flight draft. The `cc inject --cowork-safe` flow notifies the HUD and copies any existing draft to clipboard before replacing.
3. Notifications via `display notification` are easy to miss; `cc hud-ask` surfaces them with explicit Confirm/Failed/Partial buttons.

> **HUD retired (2026-07-01, Mike's call — for real this time):** the Mac HUD overlay (`com.yeshie.hud` / `yeshie/scripts/hud.py` on :3334) is disabled. A prior false claim (2026-06-10) stated this was already done; it wasn't — the launchd job (`com.yeshie.hud`, `KeepAlive=true`) was still running (verified PID 777, uptime since prior login) and still force-popping an empty panel, because its WKWebView never successfully loaded `localhost:3333/hud` (`GET :3334/wv-status` → `{"loaded": false}` at time of retirement). That's the "box that pops up and shows no information" Mike flagged 2026-07-01. Root cause was never fixed after the 2026-04-30 investigation (see `yeshie/HUD-INVESTIGATION-RESULTS.md`) — top suspects were a WKWebView load failure and a `jobMap`/`hud_update` vs `jobs`/`job_update` bookkeeping split; nobody circled back. Disabled properly this time via `launchctl bootout` + renaming the plist to `.disabled` (backup at `.bak`) — see `~/Projects/yeshie/CLAUDE.md` for the re-enable steps. `cc hud-ask` keeps the exact same CLI contract, but asks now display in **Pulse** (Pixel app + web at :8088), which polls the relay's `GET /hud/asks` and answers via `POST /hud/response/:id`. The relay (:3333) remains the broker; nothing about cc.py's interface changed. Confirmed unaffected: `com.yeshie.relay`, `com.yeshie.listener`, `com.yeshie.watcher`, and the ⌃⌥R recording toggle (dio-phase-a) — none depend on `com.yeshie.hud`.

If you find yourself reaching for `osascript -e 'tell application "System Events" to keystroke ...'`, stop and use `cc.py` instead. The osascript belt-and-suspenders activation in `set_mode()` (below) is intentional and different — it uses System Events to send Cmd+1/2/3 because raw CGEvent has focus-timing issues. That's the only place osascript belongs.

## Python environment
Use `/opt/homebrew/bin/python3` (has PyObjC installed).
```bash
/opt/homebrew/bin/python3 -m pip install \
  pyobjc-framework-ApplicationServices \
  pyobjc-framework-Cocoa \
  pyobjc-framework-Quartz
```

## Origins
Extracted from `~/Projects/yeshie/scripts/` (April 2026).
Core library `claude_ax.py` first committed 2026-04-21 (`yeshie` commit c90012b4,
verified 2026-07-04 WQ-124 — mac-controller's own git history only starts at the
2026-04-23 extraction, so check `yeshie`'s log for pre-extraction dates). Precursor
work (`ax-inject.py`) started 2026-04-16.
1.3561 regression fix: commit c90012b4, April 21, 2026.

## Related projects
- `yeshie/` — parent project (browser RPA + recipes); `yeshie/scripts/claude_ax.py` is a
  regular file copy (drifted from source since Jun 16, 2026 — not a symlink, verified
  2026-07-04 WQ-124; consider restoring the symlink to stop the two copies diverging)
- `cc-bridge-mcp/` — MCP server for remote shell/git access from Claude Desktop
- `claude-collab-bridge/` — multi-agent A2A bridge (Claude + Codex + OpenAI)

## External references
- [AXorcist](https://github.com/steipete/AXorcist) — Swift wrapper, MIT, async/await, fuzzy matching (potential future rewrite target)
- [AXSwift](https://github.com/tmandry/AXSwift) — lighter Swift wrapper
- Apple AXUIElement docs: https://developer.apple.com/documentation/applicationservices/axuielement

## AFK/team-control contract (added 2026-07-18) — read before any interactive automation

**Every automation script that does interactive AX/keyboard/mouse work against a
foreground app (Claude Desktop, Chrome, anything) must go through `afk_guard.py`
first.** This supersedes ad-hoc `cc status` checks — `cc status` describes AX
tree state, not whether it's currently *safe* to click around on Mike's screen.
Triggered by a 2026-07-17 incident: a debugging agent fired live AX clicks
against Claude Desktop while Mike may have been mid-typing.

### State machine
Single source of truth: `~/.mac-controller/automation-lock.json`
```json
{"state": "user_active" | "team_active", "since": "<ISO8601>", "reason": "<free text>"}
```
- `user_active → team_active`: only when system-wide idle time
  (`Quartz.CGEventSourceSecondsSinceLastEventType`, the standard macOS idle-time
  API — no custom keylogger/event tap) is **≥ 300s** (`afk_guard.IDLE_THRESHOLD_S`,
  the single config constant — don't hardcode 300 anywhere else), via
  `afk_guard.request_team_control(reason)`. Or explicitly via the overlay
  badge's "Give team control" button (`force_team_control`, bypasses the idle
  gate — that's fine, it's Mike consciously choosing it).
- `team_active → user_active`: (a) **safety backstop** — the `afk-guard` daemon
  polls idle time every 1s and the instant fresh input is detected while
  `team_active`, it flips back immediately, no explicit action required; or
  (b) the overlay's "Let me in" button; or (c) `afk_guard.release_to_user()`.

### For automation authors
```python
import afk_guard
afk_guard.require_team_control()                     # hard refuse if not already team_active
afk_guard.ensure_team_control(reason="...", timeout=310)  # request + bounded wait
```
Or from the shell: `cc afk-status` / `cc afk-wait --reason "..."` /
`cc afk-set-team --reason "..."` / `cc afk-release`. `afk-set-team` and
`ensure_team_control`/`request_team_control` only ever succeed once Mike has
actually been idle ≥ threshold (or hands off via the badge) — there is no
programmatic bypass from an automation script's side.

### Visible signal
When `team_active`, a floating non-activating `NSPanel` (`overlay_panel.py`,
all-Spaces, `NSApplicationActivationPolicyAccessory` so it never steals focus
or Cmd-Tab) shows "Team at work — `<reason>`" + a "Let me in" button.
Clicking it releases control and shrinks to a small draggable badge ("●
team ready") rather than fully closing; clicking the badge re-arms a "Give
team control" confirm. When `user_active`, nothing shows unless Mike created
a badge himself — no unsolicited pop-ups.

### Daemon
`afk_guard.py`'s `run_daemon()` is installed as `launchd` agent
`com.mikewolf.afk-guard` (`~/Library/LaunchAgents/com.mikewolf.afk-guard.plist`,
`KeepAlive`, mirrors `cdc-review-bridge`'s plist shape). It owns the idle-time
backstop and (belt-and-suspenders) launches `overlay_panel.py` whenever it
sees `team_active`, even if the lock file was set some other way. The overlay
process itself is otherwise launched on-demand by
`request_team_control`/`force_team_control` (checked via `pgrep` for an
existing instance first — don't double-launch).

### Known consumer
`second-brain/cdc-review/local-bridge/server.py`'s `/resume` endpoint (which
shells out to `cc.py recent --pick`, a live AX click) calls
`afk_guard.require_team_control()` / `request_team_control()` before invoking
`cc.py` — refuses fast with HTTP 423 rather than blocking, since it's serving
a web click. Model any new interactive-automation entrypoint on this.

## Code mode sidebar (discovered April 2026)

### Structure
- `New session ⌘N` — opens new Claude Code session (or folder picker if no workspace)
- `Routines` — saved automations
- Project names (e.g. `agreed-vision`) — with nested `New session in <project>`
- `New session in Projects` — create session in Projects root

### Task status prefixes in Code mode
`Idle`, `Pull request merged` — more may exist, not fully surveyed

### Inference rule
`infer_current_mode()` returns `'code'` when neither `'New task ⌘N'` nor any `'New chat'`
button is present in the sidebar. This is the correct inference since Code mode
has `'New session ⌘N'` instead.

### ⌘N behavior in Code mode
Clicking `'New session ⌘N'` may open a folder-picker dialog ("Add another folder")
if no workspace is loaded. In that case the session diff picks up the dialog title
as a new session — benign for injection tests, but worth guarding in production.

## Smoke test findings (smoke_handoff.py)

### get_content_root() — blank pane fix
Original code: `if role == 'AXWebArea' and kids:` — fails on new blank task/session panes
which have an empty AXWebArea (no children until text is typed).
Fix: `if role == 'AXWebArea':` — accept empty pane, then use `wait_for_text_area()` separately.

### New task pane — suggestion chips in session list
After opening a new CCw task, `find_nav_buttons()` picks up suggestion chip buttons
('Clear active', 'Hide suggestions', 'Build an interactive dashboard', etc.)
as "sessions". These have no status prefix and are not real tasks — filter if needed.

### set_mode() — osascript vs CGEvent
Raw CGEvent (`press_key`) is unreliable for mode switching — keystroke goes to
wrong app if focus hasn't settled. Fix: use osascript System Events:
  `tell application "System Events" to keystroke "2" using command down`
This is now the default in `set_mode()`.

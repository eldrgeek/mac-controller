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
3. Notifications via `display notification` are easy to miss; `cc hud-ask` puts them in the HUD with explicit Confirm/Failed/Partial buttons.

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
Core library `claude_ax.py` written April 16-21, 2026.
1.3561 regression fix: commit c90012b4, April 21, 2026.

## Related projects
- `yeshie/` — parent project (browser RPA + recipes); scripts still symlinked there
- `cc-bridge-mcp/` — MCP server for remote shell/git access from Claude Desktop
- `claude-collab-bridge/` — multi-agent A2A bridge (Claude + Codex + OpenAI)

## External references
- [AXorcist](https://github.com/steipete/AXorcist) — Swift wrapper, MIT, async/await, fuzzy matching (potential future rewrite target)
- [AXSwift](https://github.com/tmandry/AXSwift) — lighter Swift wrapper
- Apple AXUIElement docs: https://developer.apple.com/documentation/applicationservices/axuielement

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

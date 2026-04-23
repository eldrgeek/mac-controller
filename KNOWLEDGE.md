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

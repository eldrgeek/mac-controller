---
name: control-claude-desktop
description: Drive Claude Desktop (CDC) from the Mac via cc.py — switch mode, open/inject into Cowork tasks, inspect AX state, and notify Mike. Use whenever a task involves controlling Claude Desktop, injecting a prompt into a session or task, switching Chat/Cowork/Code mode, reading Claude Desktop's on-screen state, or surfacing a notification/ask to Mike. Triggers: "control Claude Desktop", "inject into Claude", "switch to Cowork", "new task", "notify Mike", "cc hud-ask", "CDC control", "dispatch to a session".
---

# Controlling Claude Desktop with cc.py

`cc.py` (in this repo, mac-controller) is the **canonical** way to inspect and control Claude
Desktop through macOS Accessibility APIs. It supersedes ad-hoc osascript. Run it with the repo's
Python (`requirements.txt`).

## The rule that matters most
**To notify or ask Mike, use `cc hud-ask` — never osascript keystroke injection.** Keystrokes
corrupt his in-flight draft and `display notification` is easy to miss. `cc hud-ask` shows an
explicit Confirm / Failed / Partial prompt (now in Pulse on `:8088`, brokered by the yeshie
relay on `:3333`; the old `:3334` HUD overlay is retired but the CLI contract is unchanged).

## Command surface
- `cc.py mode <chat|cowork|code>` — switch mode (⌘1/2/3)
- `cc.py new-task` — open a new Cowork/Chat/Code pane (AX `New` control; no ⌘N keystroke). Fails if the sidebar does not change.
- `cc.py inject "MSG"` — inject text into the current session. Draft preservation is the **default** (clipboard + relay notify if the composer has a real draft, not a placeholder). Flags:
  - `--session TITLE` switch to that session first · `--new` create a task first (fails if the pane does not open)
  - `--clobber` overwrite without preserving a draft · `--cowork-safe` no-op, kept for documented callers
  - `--no-dispatch` set the text but don't submit · `--save-restore` save/restore draft + session
  - `--no-afk-guard` bypass `team_active` (tests / emergency only)
- `cc.py recent [--list|--status STATUS|--pick TITLE|--inject MSG]` — work with recent
  sessions/tasks; `--status` filters running/done/ready/scheduled/dispatch/"awaiting input". `--pick` is AFK-gated.
- `cc.py inspect <overview|sessions|tasks|composer|mode|buttons>` — read AX state (ungated)
- `cc.py status` — machine-readable: Desktop + `relay` + `pulse` + `hud` (ask-surface, not `:3334`) + jobs
- `cc.py hud-ask "MSG"` — ask Mike with Confirm/Failed/Partial buttons (relay `:3333`; Pulse renders)

## Gotcha — WKWebView regression (Claude Desktop 1.3561+)
The AX walk returns only ~14 elements unless Claude is the frontmost app. `get_content_root()`
activates Claude, polls `AXFocusedUIElement`, and waits for an `AXWebArea` with children. If an
inspect/inject comes back nearly empty, Claude wasn't frontmost.

## Before editing AX code
Read [KNOWLEDGE.md](../../../KNOWLEDGE.md) — it maps the AX tree (mode switcher at depth 15,
composer at ~27, task-status prefixes baked into button titles). The tree depths drift between
Claude Desktop versions; verify against a live `cc.py inspect overview` before trusting them.

Mutating commands require `team_active` (`cc afk-wait` / overlay badge). Do not invoke
`claude_ax.py` directly.

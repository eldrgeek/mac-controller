---
district: agent-plumbing
status: active
depends_on: [yeshie]
capabilities: [macos-accessibility, claude-desktop-control]
last_reviewed: 2026-06-23
---

# mac-controller — `cc.py`, the canonical tool for controlling Claude Desktop via macOS Accessibility

**Where work happens:** `cc.py` (CLI surface) · `claude_ax.py` (AX tree access) · `pulse-dispatcher.py` (+ `com.soma.mac-triage.plist`, the dispatch daemon) · `mac-triage.py`

**Key docs**
- [KNOWLEDGE.md](KNOWLEDGE.md) — AX tree structure, the WKWebView regression fix, and the "use this, not osascript" rules. Read it before touching any AX code.

**Skills**
- local: `.claude/skills/control-claude-desktop` — the `cc.py` operating procedure
- gap: `pulse-dispatcher` operation (daemon lifecycle, relay polling) should become its own local skill

**Depends on / used by:** talks to the **yeshie relay on `:3333`** (the broker) and surfaces asks in **Pulse on `:8088`**. Siblings `cc-bridge-mcp` and `cc-dispatch` drive Claude Code through this control layer.

**Gotchas**
- Notify Mike with `cc hud-ask` — **never** osascript keystroke injection (it corrupts his in-flight draft and is easy to miss).
- The Mac HUD overlay on `:3334` was **retired 2026-07-01** (2026-06-10 was a false claim that it was already done — the launchd job was still running; see `KNOWLEDGE.md:49` for the full story). Asks now display in Pulse via the relay. The `cc hud-ask` contract is unchanged. (Verified 2026-07-04, WQ-124 sweep — root `~/Projects/CLAUDE.md` and `~/.claude/CLAUDE.md` corrected in the same pass; this file's own date was also wrong until now.)
- Claude Desktop 1.3561+ WKWebView regression: the AX walk returns ~14 elements unless Claude is frontmost; `get_content_root()` handles it by polling `AXFocusedUIElement` for an `AXWebArea`.
- Loose `*.bak-*` files and `__pycache__/` here are cruft, not reference material.

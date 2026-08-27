---
district: agent-plumbing
status: active
depends_on: [yeshie]
capabilities: [macos-accessibility, claude-desktop-control]
last_reviewed: 2026-08-27
---

# mac-controller — `cc.py`, the canonical tool for controlling Claude Desktop via macOS Accessibility

**Where work happens:** `cc.py` (CLI surface) · `claude_ax.py` (AX tree access) · `pulse-dispatcher.py` (+ `com.soma.mac-triage.plist`, the dispatch daemon) · `mac-triage.py`

**Key docs**
- [KNOWLEDGE.md](KNOWLEDGE.md) — AX tree structure, the WKWebView regression fix, and the "use this, not osascript" rules. Read it before touching any AX code.

**Skills**
- local: `.claude/skills/control-claude-desktop` — the `cc.py` operating procedure
- gap: `pulse-dispatcher` operation (daemon lifecycle, relay polling) should become its own local skill

**Depends on / used by:** talks to the **yeshie relay on `:3333`** (the broker) and surfaces asks in **Pulse on `:8088`**. Siblings `cc-bridge-mcp` and `cc-dispatch` drive Claude Code through this control layer.

**`cc status` ask-surface contract (2026-08-26, focus-safe 2026-08-27):**
- `relay` — yeshie broker on `:3333` (`GET /status`).
- `pulse` — renderer on `:8088` (any HTTP response = up; HTML is fine).
- `hud.up` — **ask-surface health**, not the retired `:3334` overlay. True when the relay is up and `GET /hud/asks` succeeds. Pulse reachability is `hud.pulse_up` plus the top-level `pulse` field. `hud.up` does **not** require `:8088`, so a Pixel-only renderer still counts.
- Relay ask JSON is a Pulse contract — do not rename: `GET /hud/asks` → `{asks: [{id, message, createdAt, ageSeconds}]}`; answers via `POST /hud/response/:id` `{response}`. `cc hud-ask` is still `POST /hud/ask` + poll `GET /hud/response/:id` on `:3333`.
- cc-dispatch `handoff.py` keys `hud_up` off `status.hud.up`. That field no longer means “overlay process on :3334”. **Poll `cc status` (not `inspect`) for ask-surface health — default `cc status` does not activate Claude.**
- Claude Desktop AX (`mode` / `composer` / `tasks`) is included only when Claude is already frontmost, or with explicit `cc status --ax` (that flag activates if needed; WKWebView 1.3561+). `inspect` remains the dedicated AX path and may still front Claude.

**Gotchas**
- Notify Mike with `cc hud-ask` — **never** osascript keystroke injection (it corrupts his in-flight draft and is easy to miss).
- The Mac HUD overlay on `:3334` was **retired 2026-07-01** (2026-06-10 was a false claim that it was already done — the launchd job was still running; see `KNOWLEDGE.md:49` for the full story). Asks now display in Pulse via the relay. `cc hud-ask` does **not** POST `:3334/show`. The CLI verb is unchanged.
- Mutating AX commands (`mode`, `new-task`, `inject`, `recent --pick`) refuse unless `team_active`. `inspect` / `status` / `hud-ask` / `afk-*` stay ungated. Opt-out: `--no-afk-guard` or `CC_SKIP_AFK_GUARD=1` (tests / emergency only) — **every skip and every `--clobber` logs to stderr and the yeshie relay notify path**. Skip is not default-on.
- Default `cc inject` preserves a real composer draft (clipboard + relay notify). `--clobber` restores overwrite (loud). `--cowork-safe` is a no-op kept for documented callers.
- `cc status` reports relay+Pulse+`hud.up` without `get_content_root()` / activating Claude. Pass `--ax` to force an AX snapshot (activates if Claude is not already frontmost).
- `claude_ax.py` is a library. `python3 claude_ax.py …` refuses and points at `cc.py`.
- Claude Desktop 1.3561+ WKWebView regression: the AX walk returns ~14 elements unless Claude is frontmost; `get_content_root()` handles it by polling `AXFocusedUIElement` for an `AXWebArea`. `inspect` still uses that path.
- `pulse-dispatcher` binds `127.0.0.1` (not `0.0.0.0`). Optional `PULSE_DISPATCHER_TOKEN` gates POST/data GET. It AFK-checks, never passes `--clobber`, and does not verify via `inspect composer`.
- Loose `*.bak-*` files and `__pycache__/` here are cruft, not reference material.

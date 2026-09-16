---
name: claudectl
description: Control the Claude Desktop app on this Mac with the claudectl command — switch Chat/Cowork/Code mode, open a new task, send a prompt into a session or task, list tasks by status, and read what the app is showing. Use when the user asks to drive, inject into, check on, or hand work to Claude Desktop or a Cowork task from the command line. Triggers: "claudectl", "control Claude Desktop", "send this to a Cowork task", "open a new task in Claude", "switch Claude to Cowork", "which Cowork tasks are running", "nudge that task".
---

# Controlling Claude Desktop with claudectl

`claudectl` drives Claude Desktop through the macOS Accessibility API.
Every command prints JSON and exits 0 on success, 1 on failure. Check both before reporting success.

## Before the first command in a session

Run `claudectl doctor`. If any required line fails, tell the user the printed fix and stop.
The two common failures are a missing Accessibility permission (the user must grant it and relaunch their terminal app) and Claude Desktop not running.

## Rules

1. **Never use osascript keystrokes or System Events to type text into Claude.** Keystrokes land in whatever window is in front and can corrupt the user's half-typed draft. `claudectl inject` sets the prompt box directly instead. (`claudectl mode` does send ⌘1/⌘2/⌘3, after bringing Claude to the front; that is the one sanctioned keystroke path.)
2. **Read before you write.** Run `claudectl inspect composer` before `inject`. If the user has a draft, keep the default behaviour (the draft is copied to the clipboard). Pass `--clobber` only when the user asked to overwrite.
3. **Prefer `--no-dispatch` when the prompt is consequential** (it spends money, sends messages, deletes things). It fills in the prompt box and lets the user press Send.
4. **Respect the AFK guard.** If a command returns `refused: automation-lock state is "user_active"`, the user is at the Mac. Pass `--no-afk-guard` only when the user asked you to run the command now. Do not set `CLAUDECTL_AFK_GUARD=off` yourself; that is the user's setup choice.
5. **`recent --pick` can select the session you are running in.** When you run inside Claude Desktop, pick by a title specific enough to avoid your own session.
6. **Verify, then report.** After `new-task` or `inject`, check the exit code and the JSON `status`. `new-task` exits 1 if the sidebar did not change; say so rather than claiming it opened.

## Commands

- `claudectl inspect [overview|mode|sessions|tasks|composer|buttons]` — read state.
- `claudectl mode chat|cowork|code` — switch mode.
- `claudectl new-task` — open a new chat, task or session, verified.
- `claudectl inject "MSG" [--new] [--session TITLE] [--no-dispatch] [--clobber]` — send a prompt.
- `claudectl recent [--status STATUS] [--pick TITLE] [--inject MSG] [--no-dispatch]` — list tasks, select one, send to it. STATUS is one of running, done, ready, scheduled, dispatch, "awaiting input".
- `claudectl status [--ax]` — machine-readable status without stealing focus.

`hud-ask` needs a relay service that exists only in Mike Wolf's SOMA setup. Do not use it elsewhere.

## When something breaks after a Claude Desktop update

Run `claudectl inspect buttons` and compare the button titles with what the failing command expects (for example "New task", "New session", "New chat"). Report the output to the user; see https://github.com/eldrgeek/mac-controller/issues.

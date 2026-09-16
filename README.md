# claudectl

`claudectl` controls the Claude Desktop app on a Mac from the command line or from Python.
It can switch between Chat, Cowork and Code, open a new task, type a prompt into a session and send it, and report what the app is showing.
It works through the macOS Accessibility API, which is the interface screen readers use.
It presses buttons and fills in the prompt box directly, rather than simulating typing.
Two actions do send a keystroke, and both first bring Claude Desktop to the front:
`mode` sends ⌘1, ⌘2 or ⌘3, and sending a prompt presses Return only when the Send button cannot be found.

This is an unofficial tool. It is not made or supported by Anthropic.
It reads Claude Desktop's on-screen controls, so a Claude Desktop update can break it.
When that happens, `claudectl doctor` and `claudectl inspect buttons` show what changed.

_Maintained by Mike Wolf with Claude (Anthropic). Packaged for outside users 2026-09-16 by Claude Opus 5 at Mike's request._

---

## Requirements

- A Mac. Tested on macOS 26.3 with Claude Desktop 1.52386.6 (September 2026).
- Claude Desktop, installed from <https://claude.ai/download> and signed in.
- Python 3.10 or later. The installer below fetches one for you if needed.

## Install (about 5 minutes)

### 1. Install `uv`, the Python tool installer

Skip this step if `uv --version` already prints a version.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Close and reopen your terminal afterwards, so the `uv` command is on your PATH.

### 2. Install claudectl

```bash
uv tool install git+https://github.com/eldrgeek/mac-controller@v0.1.0
```

This puts a `claudectl` command on your PATH, in its own isolated environment.
If you prefer `pipx`, `pipx install git+https://github.com/eldrgeek/mac-controller@v0.1.0` does the same thing.

### 3. Grant Accessibility permission

macOS only lets an app control other apps after you allow it.
The permission belongs to the app you run `claudectl` from, not to `claudectl` itself.
That app is Terminal, iTerm, VS Code, or Claude Desktop if you run it from Claude Code inside the Desktop app.

1. Open **System Settings → Privacy & Security → Accessibility**.
2. Turn on the app you run commands from. If it is not listed, click **+** and add it.
3. Quit that app completely and reopen it. macOS applies the permission only to a fresh launch.

### 4. Check the setup

```bash
claudectl doctor
```

Every line should say `ok`. Each failed line prints the fix.
A line marked `info` is optional and does not block anything.

### 5. Decide how the idle guard should behave

`claudectl` has a safety gate called the AFK guard ("away from keyboard").
By default, the commands that change the app (`inject`, `mode`, `new-task`) run only after the Mac has been idle for 5 minutes.
The gate exists so that unattended automation never types into Claude while a person is using the Mac.

A person running commands by hand is never idle, so the gate refuses them. You have two ways through it:

- **For one command:** add `--no-afk-guard`. It prints a warning and shows a notification each time, on purpose.
- **For a Mac where you run every command yourself:** add this line to `~/.zshrc`, then open a new terminal:

  ```bash
  export CLAUDECTL_AFK_GUARD=off
  ```

  Use the standing setting only if no scheduled job or background agent drives Claude on this Mac.

---

## Commands

Every command except `doctor` prints JSON (`doctor --json` does too) and exits `0` on success or `1` on failure, so scripts and AI agents can check the result.

| Command | What it does |
|---|---|
| `claudectl doctor` | Checks permissions and setup, and prints the fix for each failure. |
| `claudectl inspect` | Summary: current mode, selected session, composer state, recent sessions. |
| `claudectl inspect mode` | Which mode is showing: `chat`, `cowork` or `code`. |
| `claudectl inspect sessions` | Sidebar sessions and which one is selected. |
| `claudectl inspect tasks` | Cowork tasks with their status (running, done, awaiting input, and so on). |
| `claudectl inspect composer` | Whether the prompt box has a draft in it. |
| `claudectl inspect buttons` | Every button the app exposes. Use this when an update breaks something. |
| `claudectl mode cowork` | Switches to Chat, Cowork or Code. |
| `claudectl new-task` | Opens a new chat, task or session for the current mode, and checks that it opened. |
| `claudectl inject "prompt"` | Fills in the prompt box of the current session and sends it. |
| `claudectl recent --status running` | Lists recent tasks, filtered by status. |
| `claudectl recent --pick "Title" --inject "prompt"` | Selects the task whose title contains "Title", then sends the prompt there. |
| `claudectl status` | Machine-readable status. Adds the app's state only with `--ax` or when Claude is in front. |

Useful `inject` options:

- `--new` opens a new task first, then sends the prompt there.
- `--session "Title"` switches to that session first.
- `--no-dispatch` fills in the prompt box but does not send, so a person can review and press Send.
- `--clobber` overwrites a half-typed draft. Without it, `claudectl` keeps your draft safe: it copies the draft to the clipboard before replacing it.

### Examples

```bash
# Start a new Cowork task and give it work
claudectl mode cowork
claudectl new-task
claudectl inject "Summarize the PDFs in ~/Downloads into one page"

# Leave a prompt ready for a person to review, without sending it
claudectl inject "Draft a reply to Greg's email" --new --no-dispatch

# Nudge a task that is waiting for input
claudectl recent --status "awaiting input"
claudectl recent --pick "Quarterly report" --inject "Yes, use the March numbers"
```

## Use it from Claude Code

Claude Code can run `claudectl` for you.
Install the skill so Claude knows the commands and the safety rules:

```bash
mkdir -p ~/.claude/skills/claudectl
curl -fsSL https://raw.githubusercontent.com/eldrgeek/mac-controller/v0.1.0/skills/claudectl/SKILL.md \
  -o ~/.claude/skills/claudectl/SKILL.md
```

Then ask Claude, for example: "Use claudectl to open a new Cowork task and ask it to tidy my Downloads folder."

## Use it from Python

Run your script with the package available (no separate install needed):

```bash
uv run --with "claudectl @ git+https://github.com/eldrgeek/mac-controller@v0.1.0" python my_script.py
```

where `my_script.py` contains, for example:

```python
from claude_ax import find_claude_window, infer_current_mode, list_tasks

win = find_claude_window()
print(infer_current_mode(win))
for task in list_tasks(win, status_filter="running"):
    print(task["clean_title"])
```

The functions in `claude_ax.py` are the stable surface. Read [KNOWLEDGE.md](KNOWLEDGE.md) before changing them; it maps the app's accessibility tree.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `doctor` says Accessibility is not granted, but you turned it on | The permission applies to a fresh launch. Quit the terminal app completely (⌘Q) and reopen it. |
| `no Claude Desktop window` | Claude Desktop is closed or minimised. Open it and un-minimise the window. |
| `inspect` returns almost nothing | Claude Desktop builds its accessibility tree only while it is the front app. `claudectl` brings it forward and waits; if that is interrupted, run the command again. |
| `refused: automation-lock state is "user_active"` | The AFK guard is on. See step 5 of Install. |
| A command that used to work fails after a Claude Desktop update | The app renamed or moved a control. Run `claudectl inspect buttons`, then open an issue with the output. |
| `hud-ask` says `HUD not reachable` | `hud-ask` needs a separate relay service that only exists in Mike's SOMA setup. Outside it, `hud-ask` is not usable. |

## Update or remove

```bash
uv tool install --force git+https://github.com/eldrgeek/mac-controller@<new-tag>
uv tool uninstall claudectl
```

## What else is in this repository

The installable package is four modules: `cc.py` (the `claudectl` command), `claude_ax.py`, `afk_guard.py` and `overlay_panel.py`.
The other files run Mike Wolf's own automation setup (SOMA) and are not part of the package: `pulse-dispatcher.py`, `mac-triage.py`, `mac-steward.py`, the `com.*.plist` launchd files, and the `test-*`/`smoke_*` scripts.
They are public for reference and may assume services that do not exist on your Mac.

## Development

```bash
git clone https://github.com/eldrgeek/mac-controller
cd mac-controller
uv venv && uv pip install -e .
.venv/bin/python tests/test_pure.py      # unit tests; no Claude Desktop needed
```

## License

MIT. See [LICENSE](LICENSE).

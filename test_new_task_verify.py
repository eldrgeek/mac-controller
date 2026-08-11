#!/usr/bin/env python3
"""test_new_task_verify.py — prove new_task() can no longer lie.

Runs against fakes, never the real Accessibility tree, so it is safe to run at
any hour and cannot open a task in Mike's Claude Desktop.

The regression under test: new_task() used to `return True` unconditionally and
cc.py printed {"status": "new_task_opened"} regardless. turn-gate's module
docstring cites that exact line as its live WQ-243 fabricated-completion example,
and it is why the tower-watchdog card could be pushed and retired on eight
consecutive nights while learning nothing.

Author: Dee (Opus 5) for Mike Wolf, 2026-08-11.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_ax  # noqa: E402

PASS = 0
FAIL = 0


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print("PASS  %s" % name)
    else:
        FAIL += 1
        print("FAIL  %s\n      got %r, want %r" % (name, got, want))


class Scenario:
    """Swap out every AX touchpoint new_task() uses."""

    def __init__(self, click_ok, before, after, mode="cowork"):
        self.click_ok = click_ok
        self.states = [before, after]
        self.mode = mode
        self.osascript_calls = 0

    def __enter__(self):
        self._saved = {
            "click_control": claude_ax.click_control,
            "infer_current_mode": claude_ax.infer_current_mode,
            "list_tasks": claude_ax.list_tasks,
            "time": claude_ax.time,
        }
        claude_ax.click_control = lambda *a, **k: self.click_ok
        claude_ax.infer_current_mode = lambda win: self.mode
        claude_ax.list_tasks = lambda win, **k: self.states.pop(0) if self.states else []

        class _NoSleep:
            @staticmethod
            def sleep(_s):
                return None
        claude_ax.time = _NoSleep()

        import subprocess
        self._saved_run = subprocess.run
        outer = self

        def fake_run(*a, **k):
            outer.osascript_calls += 1
            class R:
                returncode = 0
            return R()
        subprocess.run = fake_run
        self._subprocess = subprocess
        return self

    def __exit__(self, *exc):
        for k, v in self._saved.items():
            setattr(claude_ax, k, v)
        self._subprocess.run = self._saved_run
        return False


def tasks(titles, selected=None):
    return [{"title": t, "selected": (t == selected)} for t in titles]


# 1. Click works and a task really appears -> True
with Scenario(True, tasks(["a", "b"], "a"), tasks(["new", "a", "b"], "new")) as s:
    check("click succeeds + sidebar grows -> True", claude_ax.new_task(object()), True)

# 2. THE OLD BUG: click reports success but nothing changed -> must be False
with Scenario(True, tasks(["a", "b"], "a"), tasks(["a", "b"], "a")) as s:
    check("click 'succeeds' but sidebar is identical -> False (was True)",
          claude_ax.new_task(object()), False)

# 3. Click fails, osascript fallback works -> True, and the fallback was tried
with Scenario(False, tasks(["a"], "a"), tasks(["new", "a"], "new")) as s:
    got = claude_ax.new_task(object())
    check("click fails, ⌘N fallback opens a task -> True", got, True)
    check("  fallback was actually attempted", s.osascript_calls, 1)

# 4. Click fails AND fallback does nothing -> False (the tower-respawn case)
with Scenario(False, tasks(["a"], "a"), tasks(["a"], "a")) as s:
    check("click fails and fallback does nothing -> False", claude_ax.new_task(object()), False)

# 5. Selection moved without a count change (⌘N reusing an empty task) -> True
with Scenario(True, tasks(["a", "b"], "a"), tasks(["a", "b"], "b")) as s:
    check("selection moved, count unchanged -> True", claude_ax.new_task(object()), True)

# 6. AX blows up while reading the sidebar -> False. Never claim what you couldn't see.
class Boom(Scenario):
    def __enter__(self):
        super().__enter__()
        def explode(win, **k):
            raise RuntimeError("AX tree unavailable")
        claude_ax.list_tasks = explode
        return self

with Boom(True, tasks(["a"], "a"), tasks(["a"], "a")) as s:
    check("AX read raises -> False (cannot observe, cannot claim)",
          claude_ax.new_task(object()), False)

# 7. verify=False keeps the old best-effort contract for callers that opt out
with Scenario(True, tasks(["a"], "a"), tasks(["a"], "a")) as s:
    check("verify=False -> True on a successful click (opt-out preserved)",
          claude_ax.new_task(object(), verify=False), True)

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)

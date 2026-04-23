#!/usr/bin/env python3
"""Unit tests for pure functions — no Claude Desktop required."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import unittest.mock as mock
for mod in ['ApplicationServices', 'AppKit', 'Quartz']:
    sys.modules[mod] = mock.MagicMock()

from claude_ax import parse_task_status, TASK_STATUSES, _SECTION_FILTER_LABELS

def check(name, got, expected):
    ok = got == expected
    mark = "OK" if ok else "FAIL"
    print(f"  [{mark}] {name}")
    if not ok:
        print(f"         expected: {expected!r}")
        print(f"         got:      {got!r}")
    return ok

def run():
    results = []
    print("\n=== parse_task_status ===")
    cases = [
        ("Running Foo bar",           ("running",        "Foo bar")),
        ("Done LLMs4",                ("done",           "LLMs4")),
        ("Ready Url ingest",          ("ready",          "Url ingest")),
        ("Scheduled Daily report",    ("scheduled",      "Daily report")),
        ("Awaiting input Tab minder", ("awaiting input", "Tab minder")),
        ("Dispatch Build pipeline",   ("dispatch",       "Build pipeline")),
        ("Mac automation scripts",    (None,             "Mac automation scripts")),
        ("New task \u2318N",          (None,             "New task \u2318N")),
        ("Scheduled",                 (None,             "Scheduled")),
        ("",                          (None,             "")),
        ("Waiting for Running task",  (None,             "Waiting for Running task")),
        ("RunningTask",               (None,             "RunningTask")),
    ]
    for title, expected in cases:
        results.append(check(repr(title), parse_task_status(title), expected))

    print("\n=== _SECTION_FILTER_LABELS ===")
    for label in ['Scheduled', 'Live artifacts', 'Dispatch', 'Customize',
                  'Projects', 'Pinned', 'Recents', 'View all', 'New task \u2318N']:
        results.append(check(f"{label!r} excluded", label in _SECTION_FILTER_LABELS, True))

    print("\n=== TASK_STATUSES completeness ===")
    for s in ('Running', 'Done', 'Ready', 'Scheduled', 'Awaiting input', 'Dispatch'):
        results.append(check(f"{s!r} in TASK_STATUSES", s in TASK_STATUSES, True))

    passed = sum(results)
    total = len(results)
    print(f"\n{'PASS' if passed == total else 'FAIL'}  {passed}/{total}")
    return 0 if passed == total else 1

if __name__ == '__main__':
    sys.exit(run())

#!/usr/bin/env python3
"""
overlay_panel.py — the visible "Team at work" signal for afk_guard.

A floating, always-on-top, all-spaces NSPanel that appears whenever
~/.mac-controller/automation-lock.json says state == "team_active", and
disappears (down to a small draggable badge, or fully hidden if it was
never shown) the moment state flips back to "user_active".

Design notes (see mac-controller/KNOWLEDGE.md's AX conventions this
follows the same PyObjC-on-macOS-Accessibility style as claude_ax.py, but
this module builds UI, not AX tree access):

- NSNonactivatingPanelMask so the panel never steals keyboard focus or
  brings the app frontmost just by existing — Mike's current app stays
  frontmost/focused. Buttons still receive clicks.
- NSWindowCollectionBehaviorCanJoinAllSpaces + FullScreenAuxiliary so it's
  visible regardless of Space/fullscreen app.
- NSApplicationActivationPolicyAccessory — no Dock icon, doesn't steal
  Cmd-Tab focus.
- Polls the lock file every 1s on a main-thread NSTimer (no extra thread
  needed; this process is otherwise idle).

UI modes (local to this process, not written back to the lock file except
via explicit button actions):
  hidden — nothing on screen. Initial state if lock is user_active at
           startup, and also the state if the process starts fresh with
           no history of ever showing team_active. Satisfies "no
           overlay/badge should intrude" when user_active.
  panel  — full "Team at work — <reason>" + "Let me in" button. Shown
           whenever lock state == team_active.
  badge  — small draggable pill. Shown after Mike clicks "Let me in" (or
           after the safety backstop auto-releases control) — an explicit,
           Mike-visible signal that stays around until he dismisses or
           re-expands it. Clicking it re-expands to a "Give team control"
           confirmation, which calls afk_guard.force_team_control().

Run standalone for manual testing:
    /opt/homebrew/bin/python3 overlay_panel.py
Or force team_active first to see it appear immediately:
    /opt/homebrew/bin/python3 -c "import afk_guard; afk_guard.force_team_control('manual test')"
    /opt/homebrew/bin/python3 overlay_panel.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import objc
from AppKit import (
    NSApp, NSApplication, NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered, NSButton, NSColor, NSFloatingWindowLevel,
    NSFont, NSMakeRect, NSPanel, NSTextField, NSScreen,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
)
from Foundation import NSObject, NSTimer

import afk_guard

PANEL_W, PANEL_H = 320, 110
BADGE_W, BADGE_H = 150, 34
POLL_S = 1.0

NONACTIVATING_PANEL_MASK = 1 << 7  # NSWindowStyleMaskNonactivatingPanel
TITLED = 1 << 0
CLOSABLE = 1 << 1
UTILITY = 1 << 4


def _top_right_origin(w, h, margin=24):
    screen = NSScreen.mainScreen().frame()
    x = screen.size.width - w - margin
    y = screen.size.height - h - margin - 30  # clear of menu bar
    return x, y


class OverlayController(NSObject):

    def init(self):
        self = objc.super(OverlayController, self).init()
        if self is None:
            return None
        self.mode = 'hidden'
        self.panel = self._build_panel()
        self.badge = self._build_badge()
        return self

    # ── window builders ────────────────────────────────────────────────

    def _make_window(self, w, h, style):
        x, y = _top_right_origin(w, h)
        win = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, w, h), style, NSBackingStoreBuffered, False)
        win.setLevel_(NSFloatingWindowLevel)
        win.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
            | NSWindowCollectionBehaviorStationary)
        win.setHidesOnDeactivate_(False)
        win.setReleasedWhenClosed_(False)
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.12, 0.94))
        return win

    def _build_panel(self):
        win = self._make_window(
            PANEL_W, PANEL_H, NONACTIVATING_PANEL_MASK | TITLED | UTILITY)
        win.setTitle_('mac-controller')
        win.setMovableByWindowBackground_(True)

        content = win.contentView()

        self.label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(16, 56, PANEL_W - 32, 40))
        self.label.setBezeled_(False)
        self.label.setDrawsBackground_(False)
        self.label.setEditable_(False)
        self.label.setSelectable_(False)
        self.label.setTextColor_(NSColor.whiteColor())
        self.label.setFont_(NSFont.systemFontOfSize_(13))
        self.label.setStringValue_('Team at work')
        content.addSubview_(self.label)

        btn = NSButton.alloc().initWithFrame_(NSMakeRect(16, 16, 120, 28))
        btn.setTitle_('Let me in')
        btn.setBezelStyle_(1)  # NSBezelStyleRounded
        btn.setTarget_(self)
        btn.setAction_(objc.selector(self.letMeIn_, signature=b'v@:@'))
        content.addSubview_(btn)

        return win

    def _build_badge(self):
        win = self._make_window(
            BADGE_W, BADGE_H, NONACTIVATING_PANEL_MASK)
        win.setMovableByWindowBackground_(True)

        content = win.contentView()
        btn = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, BADGE_W, BADGE_H))
        btn.setTitle_('● team ready')  # ● team ready
        btn.setBezelStyle_(1)
        btn.setTarget_(self)
        btn.setAction_(objc.selector(self.badgeClicked_, signature=b'v@:@'))
        content.addSubview_(btn)
        self.badge_button = btn

        return win

    # ── actions ─────────────────────────────────────────────────────────

    def letMeIn_(self, sender):
        afk_guard.release_to_user()
        self._show_badge()

    def badgeClicked_(self, sender):
        # Re-expand: repurpose the badge window into a confirm prompt by
        # relabeling the button; a second click actually hands control back.
        if self.badge_button.title() == '● team ready':
            self.badge_button.setTitle_('Give team control?')
        else:
            data = afk_guard.force_team_control(
                afk_guard.read_state().get('reason', '') or 'handed off via badge')
            self._apply_lock_state(data)

    # ── mode transitions ──────────────────────────────────────────────

    def _show_panel(self, reason):
        text = 'Team at work'
        if reason:
            text += f'\n— {reason}'
        self.label.setStringValue_(text)
        self.badge.orderOut_(None)
        self.panel.orderFrontRegardless()
        self.mode = 'panel'

    def _show_badge(self):
        self.badge_button.setTitle_('● team ready')
        self.panel.orderOut_(None)
        self.badge.orderFrontRegardless()
        self.mode = 'badge'

    def _hide_all(self):
        self.panel.orderOut_(None)
        self.badge.orderOut_(None)
        self.mode = 'hidden'

    def _apply_lock_state(self, data):
        state = data.get('state')
        reason = data.get('reason', '')
        if state == afk_guard.STATE_TEAM:
            if self.mode != 'panel':
                self._show_panel(reason)
        else:  # user_active
            if self.mode == 'panel':
                # Dropped out of team_active without going through our own
                # "Let me in" handler — e.g. the daemon's input backstop
                # fired. Same UX as clicking the button: leave a badge.
                self._show_badge()
            # if mode is already 'hidden' or 'badge', leave it alone —
            # don't force anything onto the screen the user didn't ask for.

    # ── poll loop ───────────────────────────────────────────────────────

    def tick_(self, timer):
        try:
            data = afk_guard.read_state()
            self._apply_lock_state(data)
        except Exception as e:
            sys.stderr.write(f'[overlay_panel] tick error: {e}\n')


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    controller = OverlayController.alloc().init()

    # Prime with current state at startup (covers the case where
    # team_active was already set before this process launched).
    controller._apply_lock_state(afk_guard.read_state())

    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        POLL_S, controller, 'tick:', None, True)

    app.run()


if __name__ == '__main__':
    main()

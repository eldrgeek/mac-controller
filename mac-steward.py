#!/usr/bin/env python3
"""
mac-steward — the seat that keeps Mike's Mac tidy: tabs, idle apps, login items.

Design under review: _estate/MAC-STEWARD-2026-09-03.md (marked document). Runs
every 5 minutes via launchd (com.soma.mac-steward). Each run SAMPLES (frontmost
app, running apps, every Chrome tab and which ones are active, login items,
idle time, swap) and DECIDES what it would do; it only ACTS when
~/.config/mac-steward/config.json says "armed": true, and even then never
touches a protected app, never closes an active or skip-listed tab, and never
removes a login item by itself (those are proposed on the board with an
execute button).

Why this exists (2026-09-03): the earlier attempts lapsed — tab-minder (April)
was never installed as a job, the 07-08 startup-programs cleanup was a one-off
review whose calls crept back (Google Drive is a login item again), and
mac-maintenance has run in dry-run since birth. A standing seat with a
liveness proof is what survives.

Tab idle time: Chrome exposes neither lastAccessed nor pinned/group state to
AppleScript, and the Yeshie relay's /tabs/list carries only id/url/title today,
so the steward measures idleness itself: a tab is "touched" whenever it is the
active tab of some window at a sample; every other tab ages from the first
sample that saw it. After a day of sampling this is a faithful picture.

Outputs: ~/.local/share/mac-steward/LATEST.md (human), steward.jsonl (one row
per run), state.json (memory), login-items-ledger.json (Mike's rulings).
"""
import json, re, subprocess, time, urllib.request
from datetime import datetime
from pathlib import Path

HOME = Path.home()
DIR = HOME / ".local" / "share" / "mac-steward"
DIR.mkdir(parents=True, exist_ok=True)
STATE = DIR / "state.json"
LOG = DIR / "steward.jsonl"
LATEST = DIR / "LATEST.md"
LEDGER = DIR / "login-items-ledger.json"
CONFIG = HOME / ".config" / "mac-steward" / "config.json"
SKIP_DOMAINS = HOME / ".tab-minder" / "skip-domains.json"
HARVEST_DIR = HOME / "Vault" / "Resources" / "Tab Captures" / "Harvested"
RELAY = "http://localhost:3333"

DEFAULT_CONFIG = {
    "armed": False,                 # False = watch only. Flip only on Mike's ratification.
    "act_tabs": False,              # separately armable: harvest + close idle tabs
    "act_apps": False,              # separately armable: quit idle apps while Mike is away
    "tab_idle_hours": 48,           # a tab untouched this long is harvested + closed
    "tab_pass_every_min": 60,       # how often the tab pass may act
    "app_idle_hours": 24,           # an app with no foreground use this long may be quit
    "app_pass_every_min": 120,      # how often the app pass may act
    "away_min": 30,                 # only quit apps once Mike has been away this long
    "protected_apps": [
        "Google Chrome", "Claude", "zoom.us", "screenpipe-app", "Fathom", "Tailscale",
        "Hermes", "Wispr Flow", "Finder", "Omi Computer", "Omi", "Fieldy", "mouseover",
        "Activity Monitor", "Terminal", "WezTerm", "wezterm-gui", "iTerm2", "System Settings",
    ],
}


def sh(cmd, timeout=20):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""


def osa(script, timeout=15):
    return sh(["osascript", "-e", script], timeout=timeout)


def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def config():
    c = dict(DEFAULT_CONFIG)
    c.update(load_json(CONFIG, {}))
    if not CONFIG.exists():
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n")
    return c


def frontmost():
    return osa('tell application "System Events" to get name of first application process whose frontmost is true')


def gui_apps():
    out = osa('tell application "System Events" to get name of every application process whose background only is false')
    return [a.strip() for a in out.split(",") if a.strip()]


def login_items():
    out = osa('tell application "System Events" to get the name of every login item')
    return sorted(a.strip() for a in out.split(",") if a.strip())


def hid_idle_min():
    out = sh(["ioreg", "-c", "IOHIDSystem"])
    m = re.search(r'"HIDIdleTime" = (\d+)', out)
    return int(m.group(1)) / 1e9 / 60 if m else 0.0


def swap_frac():
    out = sh(["sysctl", "-n", "vm.swapusage"])
    t = re.search(r"total\s*=\s*([\d.]+)M", out)
    u = re.search(r"used\s*=\s*([\d.]+)M", out)
    return round(float(u.group(1)) / float(t.group(1)), 3) if t and u and float(t.group(1)) > 0 else 0.0


def chrome_tabs():
    """All Chrome tabs (url, title) from the DevTools port, and the set of active
    tab URLs derived from each Chrome window's title (System Events). No Chrome
    AppleScript: it needs a per-app Automation grant and can hang for minutes."""
    if "Google Chrome" not in gui_apps():
        return [], set(), "chrome not running"
    try:
        with urllib.request.urlopen("http://localhost:9222/json", timeout=5) as r:
            targets = json.loads(r.read().decode())
    except Exception as e:
        return [], set(), f"devtools port: {e}"
    tabs = [{"url": t.get("url") or "", "title": (t.get("title") or "")[:90]}
            for t in targets if t.get("type") == "page" and (t.get("url") or "").startswith(("http", "file", "chrome://"))]
    names = osa('tell application "System Events" to get name of every window of process "Google Chrome"', timeout=15)
    active_titles = set()
    for n in names.split(", "):
        n = re.sub(r"\s+-\s+Google Chrome(\s+-\s+.*)?$", "", n.strip())
        n = re.sub(r"\s+-\s+(High memory usage|Memory usage|Inactive tab|Audio playing|Camera and microphone recording)[^-]*$", "", n)
        if n:
            active_titles.add(n)
    active = {t["url"] for t in tabs if t["title"] and any(t["title"].startswith(a[:40]) or a.startswith(t["title"][:40]) for a in active_titles)}
    return tabs, active, None


def relay_close(url):
    """Close a tab by URL through the Yeshie relay (tab-minder's proven path)."""
    try:
        with urllib.request.urlopen(RELAY + "/tabs/list", timeout=5) as r:
            d = json.loads(r.read().decode())
        tabs = d if isinstance(d, list) else (d.get("tabs") or [])
        for t in tabs:
            if t.get("url") == url and t.get("tabId") is not None:
                req = urllib.request.Request(RELAY + "/tabs/close", data=json.dumps({"tabId": t["tabId"]}).encode(),
                                             headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5).read()
                return True
    except Exception:
        pass
    return False


def skip_config():
    d = load_json(SKIP_DOMAINS, {})
    return [x.lower() for x in d.get("domains", [])], [x.lower() for x in d.get("exact_urls", [])]


def tab_host(url):
    m = re.match(r"^[a-z]+://([^/]+)", url or "", re.I)
    return (m.group(1) if m else "").lower()


def app_rss_mb(name):
    total = 0
    for line in sh(["ps", "-eo", "rss,comm"]).splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and name in parts[1]:
            try:
                total += int(parts[0])
            except ValueError:
                pass
    return round(total / 1024)


def main():
    cfg = config()
    now = time.time()
    state = load_json(STATE, {})
    state.setdefault("last_fg", {}); state.setdefault("first_seen", {})
    state.setdefault("tab_first_seen", {}); state.setdefault("tab_last_active", {})
    state.setdefault("last_tab_act", 0); state.setdefault("last_app_act", 0)

    fg = frontmost()
    apps = gui_apps()
    idle_min = hid_idle_min()
    away = idle_min >= cfg["away_min"]
    if fg:
        state["last_fg"][fg] = now
    for a in apps:
        state["first_seen"].setdefault(a, now)
    for a in list(state["first_seen"]):
        if a not in apps:
            state["first_seen"].pop(a, None)

    # ---- tabs ------------------------------------------------------------------
    tabs, active_urls, tab_err = chrome_tabs()
    domains, exact = skip_config()
    seen_urls = {t["url"] for t in tabs}
    for u in seen_urls:
        state["tab_first_seen"].setdefault(u, now)
    for u in active_urls:
        state["tab_last_active"][u] = now
    for u in list(state["tab_first_seen"]):
        if u not in seen_urls:
            state["tab_first_seen"].pop(u, None); state["tab_last_active"].pop(u, None)
    hist = {"<1h": 0, "1-6h": 0, "6-48h": 0, ">48h": 0}
    tab_cands = []
    for t in tabs:
        u = t["url"]
        last = state["tab_last_active"].get(u, state["tab_first_seen"].get(u, now))
        h = (now - last) / 3600
        hist["<1h" if h < 1 else "1-6h" if h < 6 else "6-48h" if h < 48 else ">48h"] += 1
        host = tab_host(u)
        skipped = (u in active_urls or any(u.lower().startswith(x) for x in exact)
                   or any(host == d or host.endswith("." + d) for d in domains))
        if h >= cfg["tab_idle_hours"] and not skipped:
            tab_cands.append({"title": t["title"][:70], "url": u[:140], "idle_h": round(h, 1)})

    # ---- apps ------------------------------------------------------------------
    app_cands = []
    for a in apps:
        if a in cfg["protected_apps"]:
            continue
        last = state["last_fg"].get(a)
        since = (now - last) / 3600 if last else (now - state["first_seen"].get(a, now)) / 3600
        if since >= cfg["app_idle_hours"]:
            app_cands.append({"app": a, "idle_h": round(since, 1), "rss_mb": app_rss_mb(a), "fg_seen": bool(last)})

    # ---- login items -----------------------------------------------------------
    items = login_items()
    ledger = load_json(LEDGER, None)
    if ledger is None:
        ledger = {"baseline_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                  "items": {i: "unruled" for i in items}}
        LEDGER.write_text(json.dumps(ledger, indent=2) + "\n")
    new_items = [i for i in items if i not in ledger["items"]]
    gone_items = [i for i in ledger["items"] if i not in items]
    flagged = [i for i in items if ledger["items"].get(i) == "remove"]

    # ---- act (only when armed; never login items) --------------------------------
    acted = {"tabs_closed": [], "apps_quit": []}
    if cfg["armed"] and cfg["act_tabs"] and tab_cands and now - state["last_tab_act"] >= cfg["tab_pass_every_min"] * 60:
        state["last_tab_act"] = now
        HARVEST_DIR.mkdir(parents=True, exist_ok=True)
        for c in tab_cands:
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            (HARVEST_DIR / f"{stamp}-{re.sub(r'[^A-Za-z0-9]+', '-', c['title'])[:50]}.json").write_text(json.dumps(c, indent=2) + "\n")
            if relay_close(c["url"]):
                acted["tabs_closed"].append(c["url"][:80])
    if cfg["armed"] and cfg["act_apps"] and app_cands and away and now - state["last_app_act"] >= cfg["app_pass_every_min"] * 60:
        state["last_app_act"] = now
        for c in app_cands:
            osa(f'tell application "{c["app"]}" to quit')
            acted["apps_quit"].append(c["app"])

    STATE.write_text(json.dumps(state))
    row = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"), "armed": cfg["armed"],
           "frontmost": fg, "idle_min": round(idle_min, 1), "away": away, "swap_frac": swap_frac(),
           "gui_apps": len(apps), "tabs": len(tabs), "tab_hist": hist, "tab_err": tab_err,
           "tab_candidates": tab_cands, "app_candidates": app_cands,
           "login_items": items, "login_new": new_items, "login_gone": gone_items, "login_flagged": flagged,
           "acted": acted}
    with LOG.open("a") as f:
        f.write(json.dumps(row) + "\n")

    lines = [f"# mac-steward — {row['ts']}  ({'ARMED' if cfg['armed'] else 'watch only'})",
             f"- frontmost: {fg or '?'} · idle {idle_min:.0f} min · {'away' if away else 'at desk'} · swap {row['swap_frac']*100:.0f}% · {len(apps)} apps",
             f"- Chrome tabs: {len(tabs)} · idle histogram {hist}" + (f" · {tab_err}" if tab_err else ""),
             f"- tabs it would harvest+close (idle ≥ {cfg['tab_idle_hours']} h, not active or skip-listed): {len(tab_cands)}"]
    for c in tab_cands[:8]:
        lines.append(f"    - {c['idle_h']} h  {c['title']}  {c['url']}")
    lines.append(f"- apps it would quit once you are away ≥ {cfg['away_min']} min (no foreground use ≥ {cfg['app_idle_hours']} h, not protected): {len(app_cands)}")
    for c in app_cands:
        lines.append(f"    - {c['app']}  idle {c['idle_h']} h  {c['rss_mb']} MB" + ("" if c['fg_seen'] else "  (not seen in front since the steward started)"))
    lines.append(f"- login items ({len(items)}): {', '.join(items)}")
    if new_items or gone_items or flagged:
        lines.append(f"    - new since ledger: {new_items} · gone: {gone_items} · ruled remove but present: {flagged}")
    if any(acted.values()):
        lines.append(f"- ACTED: {acted}")
    LATEST.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

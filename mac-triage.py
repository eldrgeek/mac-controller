#!/usr/bin/env python3
"""
mac-triage — memory/CPU pressure triage daemon for SOMA.

Runs periodically (via launchd, every 5 min). When the Mac is under real
memory/CPU pressure it terminates a NARROW allowlist of safe targets that
Mike pre-approved:

  1. Busy Google Chrome *renderer* processes (a single tab) — REPORT ONLY
     since 2026-09-02. This rule used to SIGTERM them and was the cause of
     Mike's recurring "Aw, Snap! Error code: 15" tabs (15 = SIGTERM): 373
     renderer kills between 2026-06-17 and 2026-09-02, while Chrome itself
     recorded 0 renderer crashes. A renderer at 100% CPU is almost always the
     FOREGROUND tab doing real work (Playmaker's editor, a PDF import), not a
     runaway; Chrome's Memory Saver already discards idle tabs. Targets are
     still logged so the would-be kills stay visible. See CHROME_RENDERER_ACTION.
  2. Stale / orphaned `claude` and `node` CLI processes — not MCP servers,
     not the Cowork/cc-bridge, not launchd-managed services.
  3. Our own launchd daemons (com.soma.*, com.mikewolf.*, com.mike-wolf.*,
     com.yeshie.*) that are burning CPU or leaking memory — restarted via
     `launchctl kickstart -k` so a fresh, low-footprint instance replaces
     the bloated one (KeepAlive handles respawn).

Everything else is left alone. Zoom, Screenpipe/ffmpeg, Omi, Claude Desktop,
the cc-bridge, and all GUI apps are explicitly PROTECTED.

CPU-runaway targets are acted on whenever detected (a pegged core is always
bad). Memory-based kills only fire when the system is actually under memory
pressure, so a normal idle machine is never disturbed.

Usage:
  mac-triage.py             # one pass, apply actions (launchd default)
  mac-triage.py --dry-run   # report what it WOULD do, kill nothing
  mac-triage.py --relief    # user-triggered cleanup of resumable hog apps
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# launchd hands us a minimal PATH; sysctl/memory_pressure live in /usr/sbin.
# Guarantee the binaries we shell out to are always findable.
for _p in ("/usr/sbin", "/sbin", "/usr/bin", "/bin", "/opt/homebrew/bin"):
    if _p not in os.environ.get("PATH", "").split(":"):
        os.environ["PATH"] = os.environ.get("PATH", "") + ":" + _p

HOME = Path.home()
LOG_DIR = HOME / ".local" / "share" / "mac-triage"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG = LOG_DIR / "triage.log"
MAX_LOG_BYTES = 2_000_000  # rotate at ~2 MB

UID = os.getuid()

# ---- pressure thresholds (only act when the machine is actually hurting) --
SWAP_USED_FRAC_TRIGGER = 0.80   # >80% of swap in use
FREE_MEM_PCT_TRIGGER = 12       # ...or free memory below 12%
LOAD_PER_CORE_TRIGGER = 2.5     # ...or 1-min load above 2.5x core count

# ---- per-target thresholds ------------------------------------------------
CHROME_RENDERER_ACTION = "report"  # "term" until 2026-09-02 — killed Mike's live tabs (see docstring §1).
                                   # Re-enable only with a foreground-tab check + a sustained multi-sample CPU test.
CHROME_RENDERER_CPU = 80.0      # %CPU for a renderer to count as busy (report threshold)
CHROME_RENDERER_RSS_MB = 1200   # ...or RSS above this (mem-pressure only)
STALE_CLI_AGE_HOURS = 4         # orphaned claude/node older than this
STALE_CLI_CPU_MAX = 5.0         # ...and effectively idle (mem-pressure only)
OURDAEMON_CPU = 60.0            # our daemon burning more than this %CPU
OURDAEMON_RSS_MB = 600          # ...or leaking past this RSS (mem-pressure only)
RELIEF_CPU = 20.0               # user-triggered relief: resumable app CPU floor
RELIEF_RSS_MB = 800             # user-triggered relief: resumable app memory floor

# Never terminate anything whose command line matches these.
PROTECT = re.compile(
    r"cc-bridge|[-_]mcp|mcp[-_]|Claude\.app|Cowork|claude-desktop|"
    r"WindowServer|loginwindow|/Finder|/Dock|SystemUIServer|"
    r"zoom|screenpipe|ffmpeg|/Omi|omi\.app|mac-triage",
    re.I,
)

OUR_LABEL = re.compile(r"com\.(soma|mikewolf|mike-wolf|yeshie)\.", re.I)

# --relief is opt-in and more aggressive than launchd mode. Keep the list tiny:
# resumable apps that commonly eat CPU/RAM while a VM needs headroom.
RELIEF_TARGETS = (
    {
        "name": "Omi Computer",
        "patterns": (r"/Omi Computer\.app/", r"\bOmi Computer\b"),
        "quit_app": "Omi Computer",
        "min_cpu": 15.0,
        "min_rss_mb": 400,
    },
    {
        "name": "screenpipe",
        "patterns": (r"\bscreenpipe-app\b", r"\bscreenpipe\b", r"\bffmpeg\b.*screenpipe"),
        "quit_app": "screenpipe",
        "min_cpu": 12.0,
        "min_rss_mb": 500,
    },
    {
        "name": "Activity Monitor",
        "patterns": (r"/Activity Monitor\.app/", r"\bActivity Monitor\b"),
        "quit_app": "Activity Monitor",
        "min_cpu": 20.0,
        "min_rss_mb": 250,
    },
)

RELIEF_PROTECT = re.compile(
    r"UTM|Virtualization\.VirtualMachine|Virtualization\.Installation|"
    r"Codex|Claude|Google Chrome|WindowServer|loginwindow|Finder|Dock|"
    r"SystemUIServer|SkyComputerUseService|mac-triage|launchd|kernel_task",
    re.I,
)


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def log(event: dict):
    event["ts"] = now()
    line = json.dumps(event)
    try:
        if LOG.exists() and LOG.stat().st_size > MAX_LOG_BYTES:
            LOG.rename(LOG.with_suffix(".log.1"))
        with LOG.open("a") as f:
            f.write(line + "\n")
    except OSError:
        pass
    print(line, flush=True)


def sh(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
    except (subprocess.SubprocessError, OSError):
        return ""


# ---------------------------------------------------------------------------
# system pressure
# ---------------------------------------------------------------------------
def read_pressure() -> dict:
    ncpu = int(sh(["sysctl", "-n", "hw.ncpu"]).strip() or "1")

    swap = sh(["sysctl", "-n", "vm.swapusage"])
    m_tot = re.search(r"total\s*=\s*([\d.]+)M", swap)
    m_used = re.search(r"used\s*=\s*([\d.]+)M", swap)
    swap_tot = float(m_tot.group(1)) if m_tot else 0.0
    swap_used = float(m_used.group(1)) if m_used else 0.0
    swap_frac = (swap_used / swap_tot) if swap_tot else 0.0

    free_pct = 100
    mp = sh(["memory_pressure"])
    m_free = re.search(r"free percentage:\s*(\d+)%", mp)
    if m_free:
        free_pct = int(m_free.group(1))

    load1 = 0.0
    la = sh(["sysctl", "-n", "vm.loadavg"])  # like: { 37.35 27.63 20.38 }
    m_la = re.search(r"([\d.]+)", la)
    if m_la:
        load1 = float(m_la.group(1))

    mem_pressure = (
        swap_frac >= SWAP_USED_FRAC_TRIGGER
        or free_pct < FREE_MEM_PCT_TRIGGER
        or load1 > LOAD_PER_CORE_TRIGGER * ncpu
    )
    return {
        "ncpu": ncpu,
        "swap_used_mb": round(swap_used, 1),
        "swap_total_mb": round(swap_tot, 1),
        "swap_frac": round(swap_frac, 3),
        "free_mem_pct": free_pct,
        "load1": load1,
        "mem_pressure": mem_pressure,
    }


# ---------------------------------------------------------------------------
# process inventory
# ---------------------------------------------------------------------------
def etime_to_hours(etime: str) -> float:
    # [[dd-]hh:]mm:ss
    days = 0
    if "-" in etime:
        d, etime = etime.split("-", 1)
        days = int(d)
    parts = [int(p) for p in etime.split(":")]
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m, s = 0, parts[0], parts[1]
    else:
        h, m, s = 0, 0, parts[0]
    return days * 24 + h + m / 60 + s / 3600


def list_procs() -> list[dict]:
    out = sh(["ps", "-axo", "pid=,ppid=,pcpu=,rss=,etime=,command="])
    procs = []
    for line in out.splitlines():
        line = line.rstrip("\n")
        m = re.match(r"\s*(\d+)\s+(\d+)\s+([\d.]+)\s+(\d+)\s+(\S+)\s+(.*)", line)
        if not m:
            continue
        pid, ppid, pcpu, rss, etime, cmd = m.groups()
        procs.append({
            "pid": int(pid),
            "ppid": int(ppid),
            "cpu": float(pcpu),
            "rss_mb": int(rss) / 1024,
            "age_h": etime_to_hours(etime),
            "cmd": cmd,
        })
    return procs


def launchd_pid_labels() -> dict[int, str]:
    """Map live PID -> our launchd label (only com.soma/mikewolf/yeshie.*)."""
    out = sh(["launchctl", "list"])
    mapping = {}
    for line in out.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 3:
            continue
        pid_s, _status, label = cols[0], cols[1], cols[2].strip()
        if pid_s.isdigit() and OUR_LABEL.search(label):
            mapping[int(pid_s)] = label
    return mapping


# ---------------------------------------------------------------------------
# decide + act
# ---------------------------------------------------------------------------
def basename(cmd: str) -> str:
    first = cmd.split()[0] if cmd.split() else cmd
    return os.path.basename(first)


def find_targets(procs, ld_pids, mem_pressure):
    targets = []  # (category, action, proc, reason)
    self_pid = os.getpid()
    ppid_self = os.getppid()

    for p in procs:
        cmd = p["cmd"]
        if p["pid"] in (self_pid, ppid_self):
            continue
        if PROTECT.search(cmd):
            continue

        # --- 1. busy Chrome renderer (single tab) — report only ---------------
        # 2026-09-02: was "term". Evidence that this rule was killing the tab
        # Mike was working in: ~/.local/share/mac-triage/launchd.out.log lines
        # up minute-for-minute with Playmaker's crash telemetry, and Chrome's
        # chrome://histograms/BrowserRenderProcessHost showed 28 ChildKills / 0
        # ChildCrashes for the same session. Never terminate a renderer here
        # without (a) proving it is not the foreground tab and (b) sustained
        # CPU across several samples; `ps pcpu` is a recent-window average and
        # any tab doing real work hits 100% for a few seconds.
        if "--type=renderer" in cmd and "Google Chrome" in cmd:
            if p["cpu"] >= CHROME_RENDERER_CPU:
                targets.append(("chrome_renderer", CHROME_RENDERER_ACTION, p,
                                f"renderer CPU {p['cpu']:.0f}%"))
            elif mem_pressure and p["rss_mb"] >= CHROME_RENDERER_RSS_MB:
                targets.append(("chrome_renderer", CHROME_RENDERER_ACTION, p,
                                f"renderer RSS {p['rss_mb']:.0f}MB under pressure"))
            continue

        # --- 3. our launchd daemon eating compute --------------------------
        if p["pid"] in ld_pids:
            label = ld_pids[p["pid"]]
            if p["cpu"] >= OURDAEMON_CPU:
                targets.append(("our_daemon", "kickstart", p,
                                f"{label} CPU {p['cpu']:.0f}%"))
            elif mem_pressure and p["rss_mb"] >= OURDAEMON_RSS_MB:
                targets.append(("our_daemon", "kickstart", p,
                                f"{label} RSS {p['rss_mb']:.0f}MB under pressure"))
            continue

        # --- 2. stale / orphaned claude or node CLI ------------------------
        name = basename(cmd)
        if name in ("claude", "node") and p["ppid"] == 1:
            if (mem_pressure
                    and p["age_h"] >= STALE_CLI_AGE_HOURS
                    and p["cpu"] <= STALE_CLI_CPU_MAX):
                targets.append(("stale_cli", "term", p,
                                f"orphaned {name} idle {p['age_h']:.1f}h"))
    return targets


def apply_action(category, action, p, label_map, dry_run) -> dict:
    rec = {"action": action, "category": category, "pid": p["pid"],
           "cmd": p["cmd"][:120], "applied": False}
    if action == "report":      # observe-only category: never signal it
        rec["note"] = "report-only"
        return rec
    if dry_run:
        return rec
    try:
        if action == "kickstart":
            label = label_map.get(p["pid"])
            if label:
                subprocess.run(
                    ["launchctl", "kickstart", "-k", f"gui/{UID}/{label}"],
                    capture_output=True, timeout=15)
                rec["applied"] = True
        else:  # term
            os.kill(p["pid"], signal.SIGTERM)
            rec["applied"] = True
    except (ProcessLookupError, PermissionError, OSError, subprocess.SubprocessError) as e:
        rec["error"] = str(e)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="report targets, terminate nothing")
    args = ap.parse_args()

    pressure = read_pressure()
    procs = list_procs()
    ld_pids = launchd_pid_labels()
    targets = find_targets(procs, ld_pids, pressure["mem_pressure"])

    actions = [apply_action(c, a, p, ld_pids, args.dry_run)
               for (c, a, p, _r) in targets]

    log({
        "mode": "dry-run" if args.dry_run else "apply",
        "pressure": pressure,
        "n_targets": len(targets),
        "targets": [{"category": c, "action": a, "pid": p["pid"],
                     "cpu": p["cpu"], "rss_mb": round(p["rss_mb"], 0),
                     "reason": r} for (c, a, p, r) in targets],
        "actions": actions,
    })


if __name__ == "__main__":
    main()

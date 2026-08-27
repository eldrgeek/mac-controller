#!/opt/homebrew/bin/python3
"""
pulse-dispatcher.py — Pulse multi-target dispatcher, HTTP on port 3335.

POST /dispatch          {target: "code"|"chat"|"cowork"|"auto", text, source?, id?}
GET  /dispatch/:id      status of one dispatch
GET  /dispatches        list all; ?state=queued|injected|verified|failed
POST /dispatch/:id/replay  re-queue a dispatch (any state)
GET  /health
"""

import json, os, sys, uuid, time, subprocess, threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path

PORT         = int(os.environ.get("PULSE_DISPATCHER_PORT", "3340"))
_CC_PY_DEFAULT = ["/opt/homebrew/bin/python3",
                   os.path.expanduser("~/Projects/mac-controller/cc.py")]
CC_DISPATCH  = os.path.expanduser("~/.local/bin/cc-dispatch")
LEDGER       = os.path.expanduser("~/Projects/SOMA/dispatch-ledger.jsonl")
FAILURES_DIR = os.path.expanduser("~/Projects/SOMA/audits/dispatch-failures")
RELAY        = "http://localhost:3333"

# Same directory as afk_guard.py / cc.py
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Allow test harness to swap in a bogus cc binary via env var
_CC_PY_OVERRIDE = os.environ.get("PULSE_DISPATCHER_CC_PY_OVERRIDE")

def _cc_cmd() -> list[str]:
    if _CC_PY_OVERRIDE:
        return [_CC_PY_OVERRIDE]
    return _CC_PY_DEFAULT

# keyword sets for auto-routing
CODE_KW   = {"file","git","build","deploy","test","code","compile","run","script",
             "bash","shell","debug","fix","install","repo","branch","commit","diff",
             "grep","lint","format","refactor","migration","database","sql","api"}
COWORK_KW = {"document","report","spreadsheet","drive","write","draft","notes",
             "slides","doc","email","compose","presentation","summary","brief",
             "research","outline","template","letter","memo","proposal"}

# ── in-memory store ──────────────────────────────────────────────────────────
_store: dict = {}
_store_lock = threading.Lock()
_queue: list = []
_queue_cv   = threading.Condition(threading.Lock())

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ledger(entry: dict):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a") as f:
        f.write(json.dumps(entry) + "\n")

def _store_set(did: str, patch: dict):
    """Update in-memory state and append to ledger (append-only)."""
    with _store_lock:
        rec = _store.setdefault(did, {})
        rec.update(patch)
        rec["updated_at"] = _now()
    _ledger({"id": did, "ts": _now(), **patch})

def _store_get(did: str) -> dict | None:
    with _store_lock:
        return dict(_store[did]) if did in _store else None

def _store_all() -> list:
    with _store_lock:
        return [dict(v) for v in _store.values()]

def _load_ledger():
    """Replay ledger into in-memory state at startup."""
    if not os.path.exists(LEDGER):
        return
    seen = 0
    with open(LEDGER) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                did = e.get("id")
                if did:
                    with _store_lock:
                        _store.setdefault(did, {}).update(e)
                    seen += 1
            except Exception:
                pass
    print(f"[pulse-dispatcher] ledger: replayed {seen} entries → {len(_store)} dispatches",
          flush=True)

# ── routing ──────────────────────────────────────────────────────────────────
def _auto_route(text: str) -> str:
    words = set(text.lower().split())
    if words & CODE_KW:
        return "code"
    if words & COWORK_KW:
        return "cowork"
    return "chat"

# ── execution helpers ────────────────────────────────────────────────────────
def _run_cc(*args, timeout=30) -> tuple:
    cmd = _cc_cmd() + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()

def _notify_relay(did: str, text: str, target: str, err: str):
    """Post failure notification to relay HUD."""
    import urllib.request
    payload = json.dumps({
        "id":     f"pd-{did[:12]}",
        "title":  f"[PULSE DISPATCH FAILED] {target}: {text[:60]}",
        "status": "error",
        "step":   "verify",
        "error":  err,
    }).encode()
    try:
        req = urllib.request.Request(
            f"{RELAY}/jobs/update", data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
        print(f"[pulse-dispatcher] HUD notified of failure {did}", flush=True)
    except Exception as ex:
        print(f"[pulse-dispatcher] WARNING: HUD notify failed ({ex}) — "
              f"DISPATCH FAILED id={did} target={target} err={err}", flush=True)

def _screenshot(did: str) -> str:
    os.makedirs(FAILURES_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    path = os.path.join(FAILURES_DIR, f"{ts}-{did[:8]}.png")
    try:
        subprocess.run(["screencapture", "-x", path], timeout=10)
    except Exception as ex:
        print(f"[pulse-dispatcher] screencapture failed: {ex}", flush=True)
    return path

def _verify_chat_cowork(target: str) -> tuple:
    """Check that composer draft_text is empty → message was consumed."""
    try:
        rc, out, err = _run_cc("inspect", "composer", timeout=15)
        if rc != 0:
            return False, f"inspect exit {rc}: {err or out}"
        try:
            data = json.loads(out)
            draft = data.get("draft_text", None)
            if draft is None:
                # unexpected shape — trust inject exit code, warn
                return True, f"composer shape unexpected; trusting inject rc=0"
            if draft == "":
                return True, "composer empty — message consumed"
            return False, f"composer still has text ({len(draft)} chars)"
        except json.JSONDecodeError:
            # If output is not JSON we can't verify; trust the inject exit code
            return True, f"composer output unparseable; trusting inject rc=0"
    except subprocess.TimeoutExpired:
        return False, "inspect composer timed out"
    except Exception as ex:
        return False, str(ex)

def _dispatch_code(did: str, text: str) -> tuple:
    """Run cc-dispatch for code target."""
    task_name = f"pulse-{did[:8]}"
    try:
        r = subprocess.run(
            [CC_DISPATCH, task_name, text],
            capture_output=True, text=True, timeout=20
        )
        if r.returncode == 0:
            return True, r.stdout.strip() or "dispatched via cc-dispatch"
        return False, (r.stderr.strip() or r.stdout.strip() or f"exit {r.returncode}")
    except subprocess.TimeoutExpired:
        return False, "cc-dispatch timed out"
    except FileNotFoundError:
        return False, f"cc-dispatch not found at {CC_DISPATCH}"
    except Exception as ex:
        return False, str(ex)

def _dispatch_chat_cowork(did: str, text: str, target: str) -> tuple:
    """Inject into Chat or Cowork with one retry and post-inject verification.

    Always passes --cowork-safe (cc.py now defaults to draft preservation;
    the flag is explicit so a revert of that default cannot re-clobber Chat).
    Requires team_active unless CC_SKIP_AFK_GUARD is set — cc.py also gates
    inject, but failing here keeps the ledger error readable.
    """
    import afk_guard
    skip = os.environ.get("CC_SKIP_AFK_GUARD", "").strip().lower() in ("1", "true", "yes")
    if not skip:
        try:
            afk_guard.require_team_control()
        except afk_guard.AfkGuardError as e:
            return False, f"afk-guard: {e}"

    inject_args = ["inject", text, "--cowork-safe"]

    last_err = "no attempt made"
    for attempt in range(2):
        try:
            rc, out, err = _run_cc(*inject_args, timeout=35)
            if rc != 0:
                last_err = err or out or f"exit {rc}"
                if attempt == 0:
                    print(f"[pulse-dispatcher] inject attempt 1 failed ({last_err}), retrying",
                          flush=True)
                    time.sleep(2.5)
                    continue
                return False, last_err

            # Give Claude Desktop a moment to consume the text
            time.sleep(1.5)
            ok, msg = _verify_chat_cowork(target)
            if ok:
                return True, msg
            last_err = f"verification failed: {msg}"
            if attempt == 0:
                print(f"[pulse-dispatcher] verify attempt 1 failed ({last_err}), retrying",
                      flush=True)
                time.sleep(3.0)
                continue
            return False, last_err
        except subprocess.TimeoutExpired:
            last_err = "cc.py timed out"
            if attempt == 0:
                time.sleep(2.0)
                continue
            return False, last_err
        except Exception as ex:
            last_err = str(ex)
            if attempt == 0:
                time.sleep(2.0)
                continue
            return False, last_err

    return False, last_err

# ── dispatch worker ──────────────────────────────────────────────────────────
def _execute_dispatch(did: str):
    rec = _store_get(did)
    if not rec:
        return

    target   = rec.get("resolved_target") or rec.get("target", "chat")
    text     = rec.get("text", "")

    _store_set(did, {"state": "injected", "attempt_at": _now()})

    if target == "code":
        ok, msg = _dispatch_code(did, text)
    elif target in ("chat", "cowork"):
        ok, msg = _dispatch_chat_cowork(did, text, target)
    else:
        ok, msg = False, f"unknown target: {target}"

    if ok:
        _store_set(did, {"state": "verified", "result": msg, "completed_at": _now()})
        print(f"[pulse-dispatcher] {did} → verified ({target}: {msg})", flush=True)
    else:
        shot = _screenshot(did)
        _notify_relay(did, text, target, msg)
        _store_set(did, {
            "state":      "failed",
            "error":      msg,
            "screenshot": shot,
            "failed_at":  _now(),
        })
        print(f"[pulse-dispatcher] {did} → FAILED ({target}): {msg}", flush=True)

def _worker():
    while True:
        with _queue_cv:
            while not _queue:
                _queue_cv.wait()
            did = _queue.pop(0)
        try:
            _execute_dispatch(did)
        except Exception as ex:
            print(f"[pulse-dispatcher] worker unhandled exception for {did}: {ex}",
                  flush=True)

# ── HTTP handler ─────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[pulse-dispatcher] {self.address_string()} {fmt % args}", flush=True)

    def _send(self, code: int, body):
        data = json.dumps(body, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw)

    def do_GET(self):
        p     = urlparse(self.path)
        parts = [x for x in p.path.split("/") if x]
        qs    = parse_qs(p.query)

        # GET /health
        if parts == ["health"]:
            self._send(200, {
                "ok": True,
                "port": PORT,
                "dispatches": len(_store),
                "queued": len([v for v in _store.values() if v.get("state") == "queued"]),
            })

        # GET /dispatch/:id
        elif len(parts) == 2 and parts[0] == "dispatch":
            rec = _store_get(parts[1])
            self._send(200 if rec else 404,
                       rec if rec else {"error": "not found"})

        # GET /dispatches?state=...
        elif len(parts) == 1 and parts[0] == "dispatches":
            state_filter = qs.get("state", [None])[0]
            recs = _store_all()
            if state_filter:
                recs = [r for r in recs if r.get("state") == state_filter]
            recs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
            self._send(200, recs)

        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        p     = urlparse(self.path)
        parts = [x for x in p.path.split("/") if x]

        # POST /dispatch
        if parts == ["dispatch"]:
            try:
                body = self._body()
            except Exception:
                self._send(400, {"error": "invalid JSON"}); return

            text = (body.get("text") or "").strip()
            if not text:
                self._send(400, {"error": "text is required"}); return

            raw_target = (body.get("target") or "auto").lower()
            if raw_target not in ("code", "chat", "cowork", "auto"):
                self._send(400, {"error": "target must be code|chat|cowork|auto"}); return

            did      = (body.get("id") or "").strip() or str(uuid.uuid4())
            source   = (body.get("source") or "pulse").strip()
            resolved = raw_target if raw_target != "auto" else _auto_route(text)

            rec = {
                "id":              did,
                "state":           "queued",
                "target":          raw_target,
                "resolved_target": resolved,
                "text":            text,
                "source":          source,
                "created_at":      _now(),
            }
            # Write queued to ledger BEFORE attempting anything
            _store_set(did, rec)

            with _queue_cv:
                _queue.append(did)
                _queue_cv.notify()

            self._send(202, {
                "id":              did,
                "state":           "queued",
                "resolved_target": resolved,
            })

        # POST /dispatch/:id/replay
        elif len(parts) == 3 and parts[0] == "dispatch" and parts[2] == "replay":
            did = parts[1]
            rec = _store_get(did)
            if not rec:
                self._send(404, {"error": "not found"}); return

            _store_set(did, {
                "state":       "queued",
                "replayed_at": _now(),
                "error":       None,
                "screenshot":  None,
                "result":      None,
            })
            with _queue_cv:
                _queue.append(did)
                _queue_cv.notify()

            self._send(202, {"id": did, "state": "queued", "replayed": True})

        else:
            self._send(404, {"error": "not found"})

# ── main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    os.makedirs(FAILURES_DIR, exist_ok=True)
    _load_ledger()

    worker = threading.Thread(target=_worker, daemon=True, name="dispatch-worker")
    worker.start()

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[pulse-dispatcher] listening on :{PORT}  ledger={LEDGER}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[pulse-dispatcher] shutting down", flush=True)

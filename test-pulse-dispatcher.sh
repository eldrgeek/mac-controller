#!/bin/bash
# test-pulse-dispatcher.sh — integration tests for pulse-dispatcher.
#
# Requires:
#   - pulse-dispatcher running on :3335 (started by this script if not running)
#   - Claude Desktop running (for chat/cowork tests)
#   - cc-dispatch available at ~/.local/bin/cc-dispatch (for code test)
#
# Usage:
#   ./test-pulse-dispatcher.sh [--skip-live]
#   --skip-live  skip chat/cowork inject (AX tests) — only run routing/ledger/failure tests

set -euo pipefail

BASE="http://localhost:3335"
LEDGER="$HOME/Projects/SOMA/dispatch-ledger.jsonl"
PASS=0; FAIL=0
SKIP_LIVE=false
[[ "${1:-}" == "--skip-live" ]] && SKIP_LIVE=true

RED=$'\e[31m'; GRN=$'\e[32m'; YLW=$'\e[33m'; RST=$'\e[0m'

pass() { echo "${GRN}[PASS]${RST} $1"; ((PASS++)); }
fail() { echo "${RED}[FAIL]${RST} $1"; ((FAIL++)); }
info() { echo "${YLW}[INFO]${RST} $1"; }

# ── helpers ──────────────────────────────────────────────────────────────────
wait_state() {
    local id="$1" want="$2" max="${3:-15}"
    local n=0
    while (( n < max )); do
        state=$(curl -sf "$BASE/dispatch/$id" | python3 -c "import json,sys; print(json.load(sys.stdin).get('state',''))" 2>/dev/null || echo "?")
        [[ "$state" == "$want" ]] && return 0
        sleep 1; ((n++))
    done
    return 1
}

dispatch() {
    curl -sf -X POST "$BASE/dispatch" \
        -H "Content-Type: application/json" \
        -d "$1"
}

# ── ensure service is running ─────────────────────────────────────────────────
info "Checking pulse-dispatcher on :3335..."
if ! curl -sf "$BASE/health" > /dev/null 2>&1; then
    info "Service not running — starting in background..."
    nohup /opt/homebrew/bin/python3 \
        "$HOME/Projects/mac-controller/pulse-dispatcher.py" \
        >> "$HOME/Projects/mac-controller/logs/pulse-dispatcher.log" 2>&1 &
    sleep 2
fi
HEALTH=$(curl -sf "$BASE/health")
echo "Health: $HEALTH"

# ── test 1: health endpoint ───────────────────────────────────────────────────
info "Test 1: health"
if echo "$HEALTH" | grep -q '"ok": true'; then
    pass "health returns ok"
else
    fail "health check failed: $HEALTH"
fi

# ── test 2: auto-routing — code keyword ──────────────────────────────────────
info "Test 2: auto-routing (code keyword)"
RESP=$(dispatch '{"target":"auto","text":"git status and show me the diff","source":"test"}')
ID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
RESOLVED=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['resolved_target'])")
if [[ "$RESOLVED" == "code" ]]; then
    pass "auto routed 'git status' → code (id=$ID)"
else
    fail "expected code, got $RESOLVED"
fi

# ── test 3: auto-routing — cowork keyword ────────────────────────────────────
info "Test 3: auto-routing (cowork keyword)"
RESP=$(dispatch '{"target":"auto","text":"write a report on recent activity","source":"test"}')
RESOLVED=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['resolved_target'])")
if [[ "$RESOLVED" == "cowork" ]]; then
    pass "auto routed 'write a report' → cowork"
else
    fail "expected cowork, got $RESOLVED"
fi

# ── test 4: auto-routing — chat fallback ─────────────────────────────────────
info "Test 4: auto-routing (chat fallback)"
RESP=$(dispatch '{"target":"auto","text":"what is 2 plus 2","source":"test"}')
RESOLVED=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['resolved_target'])")
if [[ "$RESOLVED" == "chat" ]]; then
    pass "auto routed 'what is 2 plus 2' → chat"
else
    fail "expected chat, got $RESOLVED"
fi

# ── test 5: ledger has queued entry immediately ───────────────────────────────
info "Test 5: ledger write-before-attempt"
RESP=$(dispatch '{"target":"chat","text":"LEDGER_TEST_MARKER","source":"test"}')
LID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
sleep 0.3
if grep -q "LEDGER_TEST_MARKER" "$LEDGER" 2>/dev/null; then
    pass "ledger has queued entry before execution"
else
    fail "queued entry missing from ledger (id=$LID)"
fi

# ── test 6: GET /dispatch/:id ─────────────────────────────────────────────────
info "Test 6: GET /dispatch/:id"
REC=$(curl -sf "$BASE/dispatch/$LID")
STATE=$(echo "$REC" | python3 -c "import json,sys; print(json.load(sys.stdin)['state'])")
if [[ "$STATE" != "" ]]; then
    pass "GET /dispatch/$LID returned state=$STATE"
else
    fail "GET /dispatch/$LID failed or missing state"
fi

# ── test 7: GET /dispatches?state=... ────────────────────────────────────────
info "Test 7: GET /dispatches filter"
COUNT=$(curl -sf "$BASE/dispatches" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")
if (( COUNT > 0 )); then
    pass "GET /dispatches returned $COUNT entries"
else
    fail "GET /dispatches returned empty"
fi

# ── test 8: code dispatch (real cc-dispatch) ──────────────────────────────────
if $SKIP_LIVE; then
    info "Test 8: SKIPPED (--skip-live)"
else
    info "Test 8: code dispatch (cc-dispatch)"
    RESP=$(dispatch '{"target":"code","text":"Reply with the single word PING and nothing else.","source":"test"}')
    CID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
    if wait_state "$CID" "verified" 20; then
        pass "code dispatch → verified (id=$CID)"
    else
        STATE=$(curl -sf "$BASE/dispatch/$CID" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('state'), d.get('error',''))")
        fail "code dispatch not verified after 20s: $STATE"
    fi
fi

# ── test 9: chat dispatch ─────────────────────────────────────────────────────
if $SKIP_LIVE; then
    info "Test 9: SKIPPED (--skip-live)"
else
    info "Test 9: chat dispatch"
    RESP=$(dispatch '{"target":"chat","text":"Reply with the single word PING and nothing else.","source":"test"}')
    CID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
    if wait_state "$CID" "verified" 20; then
        pass "chat dispatch → verified (id=$CID)"
    else
        STATE=$(curl -sf "$BASE/dispatch/$CID" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('state'), d.get('error',''))")
        fail "chat dispatch not verified after 20s: $STATE"
    fi
fi

# ── test 10: cowork dispatch ──────────────────────────────────────────────────
if $SKIP_LIVE; then
    info "Test 10: SKIPPED (--skip-live)"
else
    info "Test 10: cowork dispatch"
    RESP=$(dispatch '{"target":"cowork","text":"Reply with the single word PING and nothing else.","source":"test"}')
    CID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
    if wait_state "$CID" "verified" 20; then
        pass "cowork dispatch → verified (id=$CID)"
    else
        STATE=$(curl -sf "$BASE/dispatch/$CID" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('state'), d.get('error',''))")
        fail "cowork dispatch not verified after 20s: $STATE"
    fi
fi

# ── test 11: failure path (bogus cc binary) ───────────────────────────────────
info "Test 11: failure path — bogus cc binary"
# Temporarily start a second dispatcher instance pointed at a non-existent binary
BOGUS_PORT=3336
BOGUS_PID=""
cleanup_bogus() {
    [[ -n "$BOGUS_PID" ]] && kill "$BOGUS_PID" 2>/dev/null || true
}
trap cleanup_bogus EXIT

PULSE_DISPATCHER_CC_PY_OVERRIDE="/usr/bin/false" \
    /opt/homebrew/bin/python3 \
    "$HOME/Projects/mac-controller/pulse-dispatcher.py" \
    2>/dev/null &
BOGUS_PID=$!
# Override port for this test by modifying PORT at runtime is not easily done,
# so we test failure via the main service with a known-bad target override.
# Instead: dispatch to chat, but kill Claude Desktop temporarily? No — too destructive.
# Better approach: use the PULSE_DISPATCHER_CC_PY_OVERRIDE env var with main service
# by spawning a one-shot test server.
kill "$BOGUS_PID" 2>/dev/null; BOGUS_PID=""

# Spawn a test instance on port 3336 with bogus cc
PULSE_DISPATCHER_CC_PY_OVERRIDE="/nonexistent/bogus-cc" \
  python3 - <<'PYEOF' &
import sys, os
sys.path.insert(0, os.path.expanduser("~/Projects/mac-controller"))
os.environ["PULSE_DISPATCHER_CC_PY_OVERRIDE"] = "/nonexistent/bogus-cc"
# Patch port before importing
import pulse_dispatcher as pd
pd.PORT = 3336
from http.server import ThreadingHTTPServer
import threading
pd._load_ledger()
t = threading.Thread(target=pd._worker, daemon=True)
t.start()
srv = ThreadingHTTPServer(("127.0.0.1", 3336), pd.Handler)
srv.serve_forever()
PYEOF
BOGUS_PID=$!
sleep 1.5

FAIL_RESP=$(curl -sf -X POST "http://localhost:3336/dispatch" \
    -H "Content-Type: application/json" \
    -d '{"target":"chat","text":"failure path test","source":"test"}' 2>/dev/null || echo "{}")
FID=$(echo "$FAIL_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null || echo "")

if [[ -n "$FID" ]]; then
    # Wait up to 30s for failed state (two attempts + retries)
    n=0
    while (( n < 30 )); do
        FSTATE=$(curl -sf "http://localhost:3336/dispatch/$FID" | \
            python3 -c "import json,sys; print(json.load(sys.stdin).get('state',''))" 2>/dev/null || echo "?")
        [[ "$FSTATE" == "failed" ]] && break
        sleep 1; ((n++))
    done
    if [[ "$FSTATE" == "failed" ]]; then
        pass "failure path → state=failed after bogus cc binary"
        # check screenshot was taken
        SHOT=$(curl -sf "http://localhost:3336/dispatch/$FID" | \
            python3 -c "import json,sys; print(json.load(sys.stdin).get('screenshot',''))" 2>/dev/null || echo "")
        if [[ -n "$SHOT" ]] && [[ -f "$SHOT" ]]; then
            pass "screenshot captured: $SHOT"
        else
            fail "screenshot missing or not captured: '$SHOT'"
        fi
        # test replay
        REPLAY=$(curl -sf -X POST "http://localhost:3336/dispatch/$FID/replay" | \
            python3 -c "import json,sys; print(json.load(sys.stdin).get('replayed',''))" 2>/dev/null || echo "")
        if [[ "$REPLAY" == "True" ]]; then
            pass "replay endpoint works"
        else
            fail "replay failed: $REPLAY"
        fi
    else
        fail "expected failed state, got $FSTATE after 30s"
    fi
else
    fail "could not get dispatch id from bogus server (port 3336 may not have started)"
fi

kill "$BOGUS_PID" 2>/dev/null; BOGUS_PID=""

# ── test 12: ledger has all expected states for a dispatch ────────────────────
info "Test 12: ledger state progression"
if [[ -n "${CID:-}" ]]; then
    LEDGER_STATES=$(grep "$CID" "$LEDGER" | python3 -c "
import json, sys
states = [json.loads(l).get('state') for l in sys.stdin if l.strip()]
print(' → '.join(s for s in states if s))
" 2>/dev/null || echo "")
    if [[ -n "$LEDGER_STATES" ]]; then
        pass "ledger progression for $CID: $LEDGER_STATES"
    else
        fail "no ledger entries for $CID"
    fi
fi

# ── summary ───────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Results: ${GRN}$PASS passed${RST}  ${RED}$FAIL failed${RST}"
if (( FAIL > 0 )); then
    exit 1
fi

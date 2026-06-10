#!/bin/bash
# start-pulse-dispatcher.sh — start (or restart) the Pulse dispatcher service.
# Usage:
#   ./start-pulse-dispatcher.sh            # foreground (ctrl-c to stop)
#   ./start-pulse-dispatcher.sh --daemon   # background via nohup

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=/opt/homebrew/bin/python3
DISPATCHER="$SCRIPT_DIR/pulse-dispatcher.py"
LOG="$SCRIPT_DIR/logs/pulse-dispatcher.log"
PIDFILE="$SCRIPT_DIR/logs/pulse-dispatcher.pid"

mkdir -p "$SCRIPT_DIR/logs"

if [[ "$1" == "--daemon" ]]; then
    if [[ -f "$PIDFILE" ]]; then
        OLD_PID=$(cat "$PIDFILE")
        if kill -0 "$OLD_PID" 2>/dev/null; then
            echo "[pulse-dispatcher] already running as PID $OLD_PID"
            exit 0
        fi
    fi
    nohup "$PY" "$DISPATCHER" >> "$LOG" 2>&1 &
    echo $! > "$PIDFILE"
    echo "[pulse-dispatcher] started as PID $(cat "$PIDFILE"), log: $LOG"
else
    echo "[pulse-dispatcher] starting in foreground (^C to stop)"
    exec "$PY" "$DISPATCHER"
fi

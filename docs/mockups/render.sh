#!/bin/sh
# Render each mockup HTML to docs/img/<name>.png at 2x with headless Chrome.
# Uses a throwaway profile directory, so it never touches your own Chrome profile.
# Headless Chrome can keep running after it writes the screenshot, so each
# render waits for the file and then stops only the processes using that profile.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
out="$here/../img"
chrome="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
mkdir -p "$out"
for f in "$here"/[0-9]*.html; do
  name=$(basename "$f" .html)
  png="$out/$name.png"
  profile=$(mktemp -d)
  rm -f "$png"
  "$chrome" --headless=new --disable-gpu --hide-scrollbars --user-data-dir="$profile" \
    --force-device-scale-factor=2 --window-size=900,560 \
    --screenshot="$png" "file://$f" >/dev/null 2>&1 &
  i=0
  while [ ! -s "$png" ] && [ $i -lt 60 ]; do sleep 0.5; i=$((i+1)); done
  sleep 0.5
  pkill -f "user-data-dir=$profile" 2>/dev/null || true
  [ -s "$png" ] && echo "rendered $png" || echo "FAILED $png"
done

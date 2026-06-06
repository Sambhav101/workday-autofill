#!/usr/bin/env bash
# Launch a dedicated "job applications" Chrome with remote debugging so the tool
# can attach over CDP.
#
# Chrome 136+ REFUSES to open the debug port on your default profile (security
# change), so we use a separate --user-data-dir. Upside: this runs as its own
# instance, so you DON'T need to quit your normal Chrome. You just log into
# Workday once in this profile (logins persist in the data dir across runs).
set -euo pipefail

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT="${1:-9222}"
DATA_DIR="$HOME/Library/Application Support/workday-autofill-chrome"

if [ ! -x "$CHROME" ]; then
  echo "Chrome not found at: $CHROME" >&2
  exit 1
fi

mkdir -p "$DATA_DIR"

echo "Launching dedicated applications Chrome (CDP port $PORT)..."
echo "Profile dir: $DATA_DIR"
echo "(Your normal Chrome can stay open — this is a separate instance.)"
exec "$CHROME" \
  --remote-debugging-port="$PORT" \
  --user-data-dir="$DATA_DIR" \
  --no-first-run \
  --no-default-browser-check

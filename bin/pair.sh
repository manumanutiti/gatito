#!/bin/bash
# Shows a QR code to pair the phone with the coordinator.
# gatitod serves the page on the local port (this machine only) and draws the QR
# itself: nothing is downloaded and the token never sits in a loose file.
set -e
if ! curl -fsS -o /dev/null http://127.0.0.1:8778/manifest.webmanifest 2>/dev/null; then
  echo "Start the coordinator (gatitod) first."; exit 1
fi
URL="$(cat "$HOME/gatito/state/pair-url" 2>/dev/null || true)"
if [ -z "$URL" ]; then
  echo "gatito only listens on this machine: set \"listen_lan\": true in config.json and restart it."
fi
[ -n "$URL" ] && echo "URL:   $URL"
echo "QR at: http://127.0.0.1:8778/pair"
"$(dirname "$0")/open-url.sh" "http://127.0.0.1:8778/pair" &

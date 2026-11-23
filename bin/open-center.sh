#!/bin/bash
# Opens the command center in a browser tab (Brave if you have it).
# Local port (HTTP, this machine only). ?t= sets the token cookie and the web app redirects to / so it doesn't stay in the address bar.
GATITO="$(cd "$(dirname "$0")/.." && pwd)"
TOKEN="$GATITO/state/token"
if [ ! -f "$TOKEN" ]; then
  echo "gatito has not started yet (no $TOKEN): is the service running?" >&2
  echo "  Linux: systemctl --user status gatitod     macOS: launchctl print gui/\$(id -u)/local.gatito.gatitod" >&2
  exit 1
fi
exec "$GATITO/bin/open-url.sh" "http://127.0.0.1:8778/?t=$(cat "$TOKEN")"

#!/bin/bash
# Opens a URL in this machine's browser: Brave if present, otherwise the default one.
# Usage: bin/open-url.sh URL   (used by open-center.sh and pair.sh; works on Linux and macOS)
# With no desktop (a server, SSH, a Lima/WSL VM) it prints the URL to open by hand: the
# local port is forwarded to the host by Lima, so it works in the Mac's browser.
URL="$1"
by_hand() {
  echo "No browser here: open this in your browser (on the Mac, if gatito runs in a Lima VM):"
  echo "  $URL"
  exit 0
}
case "$(uname -s)" in
  Darwin)
    if [ -d "/Applications/Brave Browser.app" ] || [ -d "$HOME/Applications/Brave Browser.app" ]; then
      exec open -a "Brave Browser" "$URL"
    fi
    open "$URL" || by_hand ;;
  *)
    [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] || by_hand
    if command -v brave >/dev/null 2>&1; then
      exec brave "$URL" >/dev/null 2>&1
    fi
    command -v xdg-open >/dev/null 2>&1 || by_hand
    xdg-open "$URL" >/dev/null 2>&1 || by_hand ;;
esac

#!/bin/bash
# Installs gatito on this machine (Linux or macOS). Safe to repeat: each step checks
# first whether it is already done. Written for macOS's bash 3.2.
#
#   bin/install.sh [--simulate] [--no-service] [--no-diagrams] [--venv | --system-python]
#
#   --simulate       doesn't touch systemd/launchd, Homebrew or apt: says what it would do
#                    (writes the unit/plist in your HOME so you can review it;
#                    with GATITO_OS=Darwin it walks the macOS branch on Linux)
#   --no-service     doesn't install or restart the service
#   --no-diagrams    no graphviz, icon catalog or skills
#   --venv           gatito's Python in ~/.local/share/gatito/venv (the default on
#                    macOS, and on Linux if no service is installed yet)
#   --system-python  Linux: /usr/bin/python3 with apt's python3-cryptography (the default
#                    if a gatitod.service already exists: it isn't migrated automatically)
#
# The network is only used here (pip with the versions and hashes from requirements.lock;
# Homebrew or apt for graphviz). Once installed, gatito downloads nothing.
set -euo pipefail

GATITO="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${GATITO_DATA:-$HOME/.local/share/gatito}"
VENV="$DATA/venv"
LABEL="local.gatito.gatitod"
OS="$(uname -s)"
SIMULATE=0; SERVICE=1; DIAGRAMS=1; MODE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --simulate) SIMULATE=1 ;;
    --no-service) SERVICE=0 ;;
    --no-diagrams) DIAGRAMS=0 ;;
    --venv) MODE=venv ;;
    --system-python) MODE=system ;;
    -h|--help) sed -n '/^set -euo/q;2,$p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

step() { printf '\n== %s\n' "$*"; }
warning() { printf '   ! %s\n' "$*" >&2; }
# Anything that changes the system (services, Homebrew, apt): with --simulate it's only shown.
system() {
  if [ "$SIMULATE" = 1 ]; then printf '   (simulated) %s\n' "$*"; else "$@"; fi
}

# Only for testing the macOS branch on Linux: --simulate with GATITO_OS=Darwin
if [ "$SIMULATE" = 1 ] && [ -n "${GATITO_OS:-}" ]; then OS="$GATITO_OS"; fi
UNIT="$HOME/.config/systemd/user/gatitod.service"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
if [ -z "$MODE" ]; then
  if [ "$OS" = Linux ] && [ -f "$UNIT" ]; then MODE=system; else MODE=venv; fi
fi
if [ "$OS" = Darwin ] && [ "$MODE" = system ]; then
  echo "--system-python only works on Linux" >&2; exit 2
fi

# ---------------------------------------------------------------- 1. requirements
step "Requirements ($OS)"
if [ "$GATITO" != "$HOME/gatito" ]; then
  warning "gatito is in $GATITO; the mod and skills look for it in ~/gatito (or GATITO_SOCK)."
fi
if [ "$OS" = Darwin ]; then
  if ! xcode-select -p >/dev/null 2>&1; then
    echo "   The Xcode command line tools (git, python3) are missing."
    system xcode-select --install
    echo "   When their installation finishes, run this script again."
    [ "$SIMULATE" = 1 ] || exit 1
  fi
fi
for c in git curl; do
  command -v "$c" >/dev/null 2>&1 || { warning "$c is missing"; [ "$OS" = Linux ] && warning "sudo apt install $c"; exit 1; }
done
CLAUDE=""
for c in "${GATITO_CLAUDE:-}" "$(command -v claude 2>/dev/null || true)" "$HOME/.local/bin/claude" \
         /opt/homebrew/bin/claude /usr/local/bin/claude; do
  if [ -n "$c" ] && [ -x "$c" ]; then CLAUDE="$c"; break; fi
done
if [ -n "$CLAUDE" ]; then echo "   claude: $CLAUDE"; else warning "cannot find claude: install it the way your company says and repeat"; fi

# ---------------------------------------------------------------- 2. Python
step "Python ($MODE)"
# versions covered by requirements.lock (its header: "# Python: 3.9, 3.10, …")
COVERED="$(sed -n 's/^# Python: \([0-9., ]*\)\..*/\1/p' "$GATITO/requirements.lock" | tr -d ' ' | tr ',' ' ')"
version_de() { "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true; }
covered() { case " $COVERED " in *" $1 "*) return 0 ;; esac; return 1; }

if [ "$MODE" = system ]; then
  PY=/usr/bin/python3
  [ -x "$PY" ] || { warning "$PY does not exist"; exit 1; }
  if ! "$PY" -c 'import cryptography' 2>/dev/null; then
    warning "without python3-cryptography gatito will run over HTTP with no notifications: sudo apt install python3-cryptography"
  fi
else
  BASE=""; BASEV=""
  for n in python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
    for d in "" /opt/homebrew/bin/ /usr/local/bin/; do
      if [ -z "$d" ]; then c="$(command -v "$n" 2>/dev/null || true)"; else c="$d$n"; fi
      [ -n "$c" ] && [ -x "$c" ] || continue
      v="$(version_de "$c")"
      [ -n "$v" ] && covered "$v" || continue
      # the newest: compare major and minor as numbers
      if [ -z "$BASEV" ] || [ "${v#*.}" -gt "${BASEV#*.}" ]; then BASE="$c"; BASEV="$v"; fi
    done
  done
  if [ -z "$BASE" ]; then
    warning "there is no python3 among those covered by requirements.lock ($COVERED)"
    exit 1
  fi
  echo "   base: $BASE ($BASEV)"
  if [ -x "$VENV/bin/python" ] && [ "$(version_de "$VENV/bin/python")" != "$BASEV" ]; then
    echo "   the environment is Python $(version_de "$VENV/bin/python"): rebuilding it with $BASEV"
    rm -rf "$VENV"
  fi
  if [ ! -x "$VENV/bin/python" ]; then
    mkdir -p "$DATA"
    if ! "$BASE" -m venv "$VENV"; then
      [ "$OS" = Linux ] && warning "on Ubuntu: sudo apt install python3-venv (or python$BASEV-venv)"
      exit 1
    fi
  fi
  PY="$VENV/bin/python"
  if ! "$PY" -m pip install -q --disable-pip-version-check --require-hashes --only-binary=:all: \
       -r "$GATITO/requirements.lock"; then
    warning "pip could not install requirements.lock (network? uncovered platform? see its header)"
    exit 1
  fi
  "$PY" -c 'import cryptography; print("   cryptography", cryptography.__version__)'
fi

# ---------------------------------------------------------------- 3. folders
step "Folders"
mkdir -p "$GATITO/state" "$DATA/chats"
chmod 700 "$GATITO/state"
[ "$OS" = Darwin ] && mkdir -p "$HOME/Library/Logs/gatito"
echo "   $GATITO/state (your user only), $DATA/chats"
# notebooks/ (its own git repo and the Claude Code settings its agents need) now, not on
# gatitod's first start: step 6 asks you to accept the folder trust there.
NOTEBOOKS="$("$PY" -c 'import sys; sys.path.insert(0, sys.argv[1]); import notebooks
notebooks.ensure_root(); print(notebooks.BASE)' "$GATITO/gatitod")"
echo "   $NOTEBOOKS (notebooks, their own git repo)"

# ---------------------------------------------------------------- 4. diagrams
if [ "$DIAGRAMS" = 1 ]; then
  step "Infra diagrams (graphviz, icons and skills)"
  if ! command -v dot >/dev/null 2>&1; then
    if [ "$OS" = Darwin ]; then
      if command -v brew >/dev/null 2>&1; then
        system brew install graphviz
      else
        warning "without Homebrew there is no graphviz: infra diagrams stay off (everything else works)"
      fi
    else
      warning "graphviz is missing: sudo apt install graphviz"
    fi
  fi
  if command -v dot >/dev/null 2>&1; then
    echo "   $(dot -V 2>&1)"
    GATITO_DIAGRAMS_VENV="${GATITO_DIAGRAMS_VENV:-$([ "$MODE" = venv ] && echo "$VENV" || true)}" \
      bash "$GATITO/bin/setup-diagrams.sh"
  fi
fi

# ---------------------------------------------------------------- 5. service
# PATH for claude and its agents: your login shell's, with the venv in front
path_de_shell() {
  "${SHELL:-/bin/bash}" -ilc 'printf "__GATITO__%s__GATITO__" "$PATH"' 2>/dev/null \
    | sed -n 's/.*__GATITO__\(.*\)__GATITO__.*/\1/p'
}
# fills in a template with python (escapes for XML if it's a .plist) and checks the plist
fill() {
  "$PY" - "$1" "$2" "$PY" "$GATITO" "$HOME" "$3" "${LANG:-es_ES.UTF-8}" <<'PYEOF'
import plistlib, sys
from xml.sax.saxutils import escape
template, output, py, root, home, path, lang = sys.argv[1:]
xml = output.endswith('.plist')
e = escape if xml else (lambda s: s)
text = open(template, encoding='utf-8').read()
for k, v in (('@PY@', py), ('@ROOT@', root), ('@HOME@', home), ('@PATH@', path), ('@LANG@', lang)):
    text = text.replace(k, e(v))
if xml:
    plistlib.loads(text.encode())   # well-formed XML and a valid plist, or it fails here
open(output, 'w', encoding='utf-8').write(text)
PYEOF
}

if [ "$SERVICE" = 1 ]; then
  step "Service"
  if [ "$OS" = Darwin ]; then
    P="$(path_de_shell)"
    [ -n "$P" ] || P="/usr/bin:/bin:/usr/sbin:/sbin"
    P="$VENV/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$P"
    P="$(printf '%s' "$P" | awk -v RS=: -v ORS=: '$0 != "" && !seen[$0]++' | sed 's/:$//')"   # no duplicates
    mkdir -p "$(dirname "$PLIST")"
    fill "$GATITO/packaging/$LABEL.plist.in" "$PLIST.new" "$P"
    if command -v plutil >/dev/null 2>&1; then plutil -lint "$PLIST.new" >/dev/null; fi
    mv "$PLIST.new" "$PLIST"
    echo "   $PLIST"
    U="gui/$(id -u)"
    system launchctl bootout "$U/$LABEL" 2>/dev/null || true
    system launchctl bootstrap "$U" "$PLIST"
    system launchctl kickstart -k "$U/$LABEL"
  elif [ "$MODE" = system ] && [ -f "$UNIT" ]; then
    echo "   $UNIT already exists: left alone (to switch to gatito's environment: bin/install.sh --venv)"
  else
    mkdir -p "$(dirname "$UNIT")"
    fill "$GATITO/packaging/gatitod.service.in" "$UNIT.new" ""
    mv "$UNIT.new" "$UNIT"
    echo "   $UNIT"
    system systemctl --user daemon-reload
    system systemctl --user enable gatitod
    system systemctl --user restart gatitod
  fi
  if [ "$SIMULATE" = 0 ]; then
    n=0
    until curl -fsS -o /dev/null http://127.0.0.1:8778/manifest.webmanifest 2>/dev/null; do
      n=$((n + 1))
      if [ "$n" -ge 20 ]; then
        warning "gatito is not responding at http://127.0.0.1:8778"
        if [ "$OS" = Darwin ]; then tail -20 "$HOME/Library/Logs/gatito/gatitod.log" >&2 || true
        else journalctl --user -u gatitod -n 20 --no-pager >&2 || true; fi
        exit 1
      fi
      sleep 1
    done
    echo "   gatito responds at http://127.0.0.1:8778"
  fi
fi

# ---------------------------------------------------------------- 6. what you do yourself
step "What is left (do it yourself, not an agent)"
cat <<EOF
   1. claude and its login, if you haven't yet:  claude
   2. Claude Code trust for the folders where agents work (once each):
        cd $NOTEBOOKS && claude      cd $DATA/chats && claude
      and in each project you are going to use.
   3. The mod (permissions from your phone, live status):
        claude plugin marketplace add $GATITO/mod
        claude plugin install gatito@gatito
   4. Open gatito:  bash $GATITO/bin/open-center.sh
EOF
if [ "$OS" = Darwin ]; then
  cat <<EOF
   5. It only listens on this Mac. For the phone: "listen_lan": true in config.json,
      restart (launchctl kickstart -k gui/\$(id -u)/$LABEL) and, if the macOS firewall
      is on, allow gatito's Python:
        sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add $PY --unblockapp $PY
   6. Shell variables Claude needs (proxy, Bedrock/Vertex, corporate CA)
      don't reach the service: put them in ~/.claude/settings.json → "env".
EOF
fi

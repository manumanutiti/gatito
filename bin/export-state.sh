#!/bin/bash
# Packs the parts of gatito worth moving to another machine and leaves out the rest.
# Written for macOS's bash 3.2. Touches nothing: it only reads and creates the .tar.gz.
#
#   bin/export-state.sh [file.tar.gz]
#
# Includes: notebooks/ (git bundle, with its history), state/artifacts,
#           state/diagrams, config.json
# Excludes: token, CA and certificates (tls/), VAPID keys and subscriptions (push/),
#           history and permissions (*.jsonl), backlog, projects.json, summaries,
#           pasted images, temporary conversation folders.
set -euo pipefail
GATITO="${GATITO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
NB="${GATITO_NOTEBOOKS:-$GATITO/notebooks}"
OUTPUT="${1:-$PWD/gatito-status-$(date +%Y%m%d-%H%M).tar.gz}"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/gatito-export.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/gatito/state"
TAKES=""; SKIPS=""
takes() { TAKES="$TAKES
   + $*"; }
skips() { SKIPS="$SKIPS
   - $*"; }

# notebooks: git bundle (history included; .trash is not in git)
if [ -d "$NB/.git" ]; then
  if [ -n "$(git -C "$NB" status --porcelain 2>/dev/null)" ]; then
    echo "Warning: notebooks/ has unsaved changes; the bundle only includes up to the last commit." >&2
    echo "       Wait for the autosave (every 10 min) or commit in notebooks/, then run this again if you want them." >&2
  fi
  if git -C "$NB" rev-parse -q --verify HEAD >/dev/null; then
    git -C "$NB" bundle create "$TMP/gatito/notebooks.bundle" --all 2>/dev/null
    takes "notebooks.bundle ($(git -C "$NB" rev-list --all --count) commits): on the other machine, git clone notebooks.bundle ~/gatito/notebooks"
  else
    skips "notebooks/ (its repo has no commits yet)"
  fi
else
  skips "notebooks/ (there is no $NB/.git)"
fi

for d in artifacts diagrams; do
  if [ -d "$GATITO/state/$d" ]; then
    tar -C "$GATITO/state" --exclude '.trash' --exclude '.tmp' -cf - "$d" | tar -C "$TMP/gatito/state" -xf -
    takes "state/$d ($(find "$TMP/gatito/state/$d" -type f | wc -l | tr -d ' ') files)"
  fi
done
if [ -f "$GATITO/config.json" ]; then
  cp "$GATITO/config.json" "$TMP/gatito/config.json"
  takes "config.json"
fi

skips "state/token: a new one is created; pair again (the cookie is tied to the IP or name)"
skips "state/tls (CA and certificate): each machine creates its own CA, limited to the local network; install it on the phone"
skips "state/push (VAPID keys and subscriptions): tied to the origin; enable notifications again"
skips "state/history.jsonl and state/permissions.jsonl: logs of this machine"
skips "state/backlog.json: scheduled tasks that would fire on both machines"
skips "projects.json: start from scratch on the other machine (your personal projects may not belong there)"
skips "state/summaries, state/uploads, hidden.json, status.json, pair-url: belong to the conversations and sessions here"
skips "~/.claude (credentials, conversations) and ~/.local/share/gatito (environments and temporary folders)"

cat > "$TMP/gatito/LEEME.txt" <<EOF
gatito state exported on $(date '+%Y-%m-%d %H:%M') from $(hostname).

Includes:$TAKES

Excludes:$SKIPS

On the other machine, with gatito already installed (bin/install.sh) and STOPPED:
  tar -xzf $(basename "$OUTPUT") -C /tmp
  git clone /tmp/gatito/notebooks.bundle ~/gatito/notebooks      (if it doesn't exist yet)
  cp -R /tmp/gatito/state/artifacts /tmp/gatito/state/diagrams ~/gatito/state/
  cp /tmp/gatito/config.json ~/gatito/config.json                 (review it first)
EOF

tar -C "$TMP" -czf "$OUTPUT" gatito
chmod 600 "$OUTPUT"
echo "Exported: $OUTPUT ($(du -h "$OUTPUT" | cut -f1))"
printf 'Includes:%s\n\nExcludes:%s\n' "$TAKES" "$SKIPS"

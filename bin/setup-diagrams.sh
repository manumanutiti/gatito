#!/usr/bin/env bash
# Sets up the infra diagrams and gatito artifacts. Safe to repeat.
#   - graphviz (apt on Linux, Homebrew on macOS) — if missing, says how to install it
#   - the `diagrams` library in gatito's environment (~/.local/share/gatito/venv, the one
#     from bin/install.sh) or, if that doesn't exist yet, in venv-diagrams. It's the ONLY
#     thing that uses the network, and only if missing or the version changed (with
#     requirements.lock: pinned versions and hashes): drawing never downloads anything
# Written for macOS's bash 3.2.
#   - icons/library + icons/catalog.csv: the icons, local
#   - the Claude Code skills "diagram", "artifact" and "notebook", linked to the repo's
#   - any diagrams you already had in state/diagrams, imported as artifacts
set -euo pipefail
GATITO="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${GATITO_DATA:-$HOME/.local/share/gatito}"
if [ -n "${GATITO_DIAGRAMS_VENV:-}" ]; then
  VENV="$GATITO_DIAGRAMS_VENV"
elif [ -x "$DATA/venv/bin/python" ]; then
  VENV="$DATA/venv"
else
  VENV="$DATA/venv-diagrams"
fi
VERSION="0.25.1"
BACKUPS="$DATA/skills-previous"   # outside skills/: otherwise they get loaded

if ! command -v dot >/dev/null; then
  if [ "$(uname -s)" = Darwin ]; then
    echo "graphviz is missing:  brew install graphviz" >&2
  else
    echo "graphviz is missing:  sudo apt install graphviz" >&2
  fi
  exit 1
fi

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
if [ "$("$VENV/bin/python" -I -c 'import importlib.metadata as m; print(m.version("diagrams"))' 2>/dev/null)" != "$VERSION" ]; then
  if [ -f "$GATITO/requirements.lock" ]; then
    "$VENV/bin/python" -m pip install -q --require-hashes --only-binary=:all: -r "$GATITO/requirements.lock"
  else
    "$VENV/bin/python" -m pip install -q "diagrams==$VERSION"
  fi
fi
echo "diagrams library $VERSION in $VENV"

# iconos/ from older versions: your own icons go to icons/custom, the generated rest is removed
OLD="$GATITO/iconos"
if [ -d "$OLD" ]; then
  mkdir -p "$GATITO/icons/custom"
  for f in "$OLD"/propios/*; do
    [ -f "$f" ] && [ ! -e "$GATITO/icons/custom/$(basename "$f")" ] && mv "$f" "$GATITO/icons/custom/"
  done
  rm -rf "$OLD/libreria" "$OLD/catalogo.csv" "$OLD/catalogo.tmp"
  rm -f "$OLD/propios/.gitkeep"
  rmdir "$OLD/propios" "$OLD" 2>/dev/null && echo "Moved the old iconos/ to icons/" \
    || echo "iconos/ still has files you added: move them to icons/custom by hand" >&2
fi

"$GATITO/bin/diagram" catalog

mkdir -p "$HOME/.claude/skills" "$BACKUPS"
# copies left inside skills/ by an earlier version of this script
for old in "$HOME"/.claude/skills/diagram.bak-*; do
  [ -e "$old" ] && mv "$old" "$BACKUPS/" && echo "Moved $(basename "$old") to $BACKUPS"
done
# links with the names of older versions (diagrama, artefacto, cuaderno) that point into this repo
for old in diagrama artefacto cuaderno; do
  L="$HOME/.claude/skills/$old"
  case "$(readlink "$L" 2>/dev/null || true)" in
    "$GATITO"/skills/*) rm "$L" && echo "Removed the old $old skill link" ;;
  esac
done
for s in diagram artifact notebook; do
  SKILL="$HOME/.claude/skills/$s"
  if [ -L "$SKILL" ]; then
    rm "$SKILL"
  elif [ -d "$SKILL" ]; then
    mv "$SKILL" "$BACKUPS/$s-$(date +%Y%m%d%H%M%S)"
    echo "The previous "$s" skill is kept in $BACKUPS"
  fi
  ln -s "$GATITO/skills/$s" "$SKILL"
  echo "Skill "$s" linked to $GATITO/skills/$s"
done

# loose diagrams from before → artifacts (repeating doesn't duplicate)
shopt -s nullglob
for svg in "$GATITO"/state/diagrams/*.svg; do
  base="${svg%.svg}"; extra=()
  [ -f "$base.png" ] && extra+=("$base.png")
  [ -f "$base.py" ] && extra+=("$base.py")
  # ${extra[@]+…}: with set -u, macOS bash 3.2 says "unbound variable" if it is empty
  "$GATITO/bin/artifact" save "$svg" ${extra[@]+"${extra[@]}"} --title "$(basename "$base")" \
    --kind diagram --desc "Imported from state/diagrams" >/dev/null && echo "Imported $(basename "$svg")"
done

echo "Done: try  $GATITO/bin/diagram icons aws eks"

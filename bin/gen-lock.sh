#!/bin/bash
# Regenerates requirements.lock from requirements.in, using only pip: it resolves with
# `pip download --only-binary=:all:` for each Python (3.9-3.14) and each system
# (Linux x86_64 and aarch64 (ARM) with old and new glibc; macOS arm64 and x86_64, from 12 to 26) and
# records the SHA-256 of each wheel. If a version resolves differently depending on the
# Python or the system, the line carries its marker. Uses the network (PyPI): it's for
# development, never at runtime. Installs nothing; downloads to a temporary directory.
#
# Usage: bin/gen-lock.sh [--pythons "3.9.6 3.12.3"]   (default: 3.9 to 3.14)
set -euo pipefail
GATITO="$(cd "$(dirname "$0")/.." && pwd)"
PYTHONS="3.9.6 3.10.11 3.11.9 3.12.3 3.13.1 3.14.0"
if [ "${1:-}" = "--pythons" ]; then PYTHONS="$2"; fi
TMP="$(mktemp -d "${TMPDIR:-/tmp}/gatito-lock.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
export PIP_CONFIG_FILE=/dev/null PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_CACHE_DIR="$TMP/cache"

# family:platform tags (comma-separated). On macOS pip infers the earlier versions of
# each one; on Linux it doesn't (manylinux_2_39 doesn't include 2_17), so all are
# given: old glibc (2014) and Ubuntu 24.04's (2_39) with the intermediate ones.
ML="manylinux_2_28_x86_64,manylinux_2_17_x86_64,manylinux2014_x86_64"
MLA="manylinux_2_28_aarch64,manylinux_2_17_aarch64,manylinux2014_aarch64"
PLATS="linux_x86_64:manylinux2014_x86_64 linux_x86_64:manylinux_2_39_x86_64,manylinux_2_34_x86_64,$ML
linux_aarch64:manylinux2014_aarch64 linux_aarch64:manylinux_2_39_aarch64,manylinux_2_34_aarch64,$MLA
mac_arm64:macosx_12_0_arm64 mac_arm64:macosx_15_0_arm64 mac_arm64:macosx_26_0_arm64
mac_x86_64:macosx_12_0_x86_64 mac_x86_64:macosx_15_0_x86_64 mac_x86_64:macosx_26_0_x86_64"

failures=""
for py in $PYTHONS; do
  for fp in $PLATS; do
    fam="${fp%%:*}"; plats="${fp#*:}"; plat="${plats%%,*}"
    args=""
    for t in $(echo "$plats" | tr ',' ' '); do args="$args --platform $t"; done
    dir="$TMP/dl/$py/$fam/$plat"
    mkdir -p "$dir"
    echo "· Python $py, $plat" >&2
    if ! python3 -m pip download --quiet --only-binary=:all: --implementation cp \
        --python-version "$py" $args -d "$dir" -r "$GATITO/requirements.in" \
        >"$dir.log" 2>&1; then
      failures="$failures $py/$plat"
      tail -3 "$dir.log" >&2
      rm -rf "$dir"
    fi
  done
done

python3 - "$TMP/dl" "$GATITO/requirements.lock" "$PYTHONS" "$failures" <<'PY'
import hashlib, re, sys
from collections import defaultdict
from pathlib import Path

dl, output, pythons, failures = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3].split(), sys.argv[4].split()
MARK = {'linux_x86_64': 'sys_platform == "linux" and platform_machine == "x86_64"',
         'linux_aarch64': 'sys_platform == "linux" and platform_machine == "aarch64"',
         'mac_arm64': 'sys_platform == "darwin" and platform_machine == "arm64"',
         'mac_x86_64': 'sys_platform == "darwin" and platform_machine == "x86_64"'}
def norm(n): return re.sub(r'[-_.]+', '-', n).lower()
def short(py): return '.'.join(py.split('.')[:2])

where = defaultdict(set)      # (package, version) -> {(python, family)}
hashes = defaultdict(set)
porfam = defaultdict(lambda: defaultdict(set))   # (python, family) -> package -> versions
for f in sorted(dl.glob('*/*/*/*.whl')):
    py, fam = f.parts[-4], f.parts[-3]
    name, version = f.name.split('-')[:2]
    key = (norm(name), version)
    where[key].add((short(py), fam))
    porfam[(short(py), fam)][key[0]].add(version)
    hashes[key].add(hashlib.sha256(f.read_bytes()).hexdigest())

errors = [f'{py} {fam}: {p} resolves to several versions {sorted(v)} depending on the macOS/glibc version'
           for (py, fam), ps in porfam.items() for p, v in ps.items() if len(v) > 1]
if errors:
    sys.exit('Cannot pin with markers:\n' + '\n'.join(errors))

def order(v): return tuple(map(int, v.split('.')))
todos = {c for d in where.values() for c in d}            # combinations that were resolved
todos_py = sorted({p for p, _ in todos}, key=order)
todas_fam = sorted({f for _, f in todos})
lines = []
for (name, version), combos in sorted(where.items()):
    porfam_py = {fam: sorted({p for p, f in combos if f == fam}, key=order) for fam in todas_fam}
    if combos == todos:
        mark = ''
    elif len(set(map(tuple, porfam_py.values()))) == 1 and all(porfam_py.values()) \
            and all({(p, f) for p in porfam_py[f]} <= todos for f in todas_fam):
        # same Pythons on all systems: the Python version is enough
        mark = ' ; ' + ' or '.join(f'python_version == "{p}"' for p in porfam_py[todas_fam[0]])
    else:   # per system, the Pythons where this version applies
        parts = []
        for fam in todas_fam:
            pys = sorted({p for p, f in combos if f == fam}, key=order)
            todos_fam = sorted({p for p, f in todos if f == fam}, key=order)
            if not pys:
                continue
            m = MARK[fam]
            if pys != todos_fam:
                m += ' and (' + ' or '.join(f'python_version == "{p}"' for p in pys) + ')'
            parts.append(f'({m})')
        mark = ' ; ' + ' or '.join(parts)
    cab = f'{name}=={version}{mark}'
    lines.append(' \\\n'.join([cab] + [f'    --hash=sha256:{h}' for h in sorted(hashes[(name, version)])]))

covered = ', '.join(f'{p}' for p in todos_py)
text = ('# Generated by bin/gen-lock.sh from requirements.in. Do not edit by hand.\n'
         f'# Python: {covered}. Systems: {", ".join(todas_fam)}.\n'
         + (f'# NOT covered (pip found no wheels): {" ".join(failures)}\n' if failures else '')
         + '# Install: python -m pip install --require-hashes --only-binary=:all: -r requirements.lock\n\n'
         + '\n'.join(lines) + '\n')
output.write_text(text)
print(f'{output}: {len(lines)} packages; Python {covered}' + (f'; not covered: {" ".join(failures)}' if failures else ''))
PY

#!/usr/bin/env python3
"""Refreshes ~/gatito/projects.json WITHOUT discovering anything new.

The project list is manual: add and remove projects from the web UI (⚙
"Projects" button) or by editing projects.json by hand. This script only:

  - drops entries whose folder no longer exists,
  - fills in the description of those that have none (from README/CLAUDE.md),

keeping id, path and alias. It never adds projects on its own. Usage: gen-projects.py
"""
import json
import sys
from pathlib import Path

if sys.version_info < (3, 9):
    sys.exit('gatito needs Python 3.9 or newer')

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'gatitod'))
import hostinfo  # noqa: E402
from core import describe_project  # noqa: E402

ROOT = hostinfo.ROOT
OUT = ROOT / 'projects.json'


def main():
    if not OUT.exists():
        print(f'{OUT} does not exist (nothing to refresh)')
        return
    projs = json.loads(OUT.read_text())
    kept, dropped = [], []
    for p in projs:
        path = Path(p.get('path', ''))
        if not path.is_dir():
            dropped.append(p.get('id', str(path)))
            continue
        if not p.get('desc'):
            p['desc'] = describe_project(path)
        kept.append(p)
    OUT.write_text(json.dumps(kept, indent=2, ensure_ascii=False) + '\n')
    msg = f'{len(kept)} projects → {OUT}'
    if dropped:
        msg += f' (removed, no longer exist: {", ".join(dropped)})'
    print(msg)


if __name__ == '__main__':
    main()

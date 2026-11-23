"""Artifacts: what agents generate (diagrams, HTML pages, images), saved so it can be
viewed again, downloaded or shared.

    state/artifacts/<id>/meta.json     title, type, current version…
    state/artifacts/<id>/v1/…          each version in its own folder: never overwritten,
    state/artifacts/<id>/v2/…          so an old chat keeps showing what it saw

Stdlib only and does not import core: used by web.py, bin/artifact and bin/diagram
(the latter from another Python environment).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path

import hostinfo

BASE = hostinfo.ROOT / 'state' / 'artifacts'
TRASH = BASE / '.trash'
ID_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,79}$')
VER_RE = re.compile(r'^v[0-9]{1,5}$')

# extension → artifact type (that of the main file)
KINDS = {'.html': 'page', '.htm': 'page', '.svg': 'image', '.png': 'image',
         '.jpg': 'image', '.jpeg': 'image', '.webp': 'image', '.gif': 'image',
         '.md': 'text', '.txt': 'text', '.csv': 'text', '.json': 'text',
         '.py': 'text', '.yaml': 'text', '.yml': 'text', '.tf': 'text'}
MAX_FILE = 20_000_000


def slug(s: str) -> str:
    s = s.strip().lower()
    for a, b in zip('áéíóúüñ', 'aeiouun'):
        s = s.replace(a, b)
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')[:80].strip('-')
    return s or 'artifact'


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def _dir(aid: str) -> Path | None:
    if not ID_RE.match(aid or ''):
        return None
    return BASE / aid


def _meta(d: Path) -> dict | None:
    try:
        return json.loads((d / 'meta.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _write_meta(d: Path, meta: dict):
    tmp = d / '.meta.json.tmp'
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(d / 'meta.json')


def _fingerprint(files: list[Path]) -> str:
    h = hashlib.sha256()
    for f in sorted(files, key=lambda p: p.name):
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def save(files: list, title: str, *, aid: str | None = None, principal: str | None = None,
            kind: str | None = None, description: str = '', origin: str = '') -> dict:
    """Saves (copies) the files as a new version of artifact `aid` (by default, the
    title's slug). If identical to the latest, it does not create another.
    Returns the meta, with `relpath` = the version's main file."""
    files = [Path(f).resolve() for f in files]
    for f in files:
        if not f.is_file():
            raise ValueError(f'{f} does not exist')
        if f.stat().st_size > MAX_FILE:
            raise ValueError(f'{f.name} is over 20 MB')
    if not files:
        raise ValueError('no files')
    principal = principal or files[0].name
    if principal not in {f.name for f in files}:
        raise ValueError(f'the main file {principal} is not among the files')
    aid = aid or slug(title)
    d = _dir(aid)
    if d is None:
        raise ValueError(f'invalid id: {aid}')
    d.mkdir(parents=True, exist_ok=True)
    meta = _meta(d) or {'id': aid, 'created': _now(), 'version': 0, 'versions': []}
    fingerprint = _fingerprint(files)
    if meta['versions'] and meta['versions'][-1].get('fingerprint') == fingerprint:
        actual = meta['versions'][-1]
    else:
        n = meta['version'] + 1
        vd = d / f'v{n}'
        vd.mkdir()
        for f in files:
            shutil.copy2(f, vd / f.name)
        actual = {'v': n, 'date': _now(), 'fingerprint': fingerprint,
                  'files': sorted(f.name for f in files), 'principal': principal}
        meta['versions'].append(actual)
        meta['version'] = n
    meta.update({
        'title': title or meta.get('title') or aid,
        'kind': kind or KINDS.get(Path(principal).suffix.lower(), 'other'),
        'description': description or meta.get('description', ''),
        'origin': origin or meta.get('origin', ''),
        'updated': _now(),
    })
    _write_meta(d, meta)
    return {**meta, 'relpath': str(d / f'v{actual["v"]}' / actual['principal'])}


def list_all() -> list[dict]:
    if not BASE.is_dir():
        return []
    out = []
    for d in BASE.iterdir():
        if d.is_dir() and ID_RE.match(d.name):
            m = _meta(d)
            if m and m.get('versions'):
                ult = m['versions'][-1]
                out.append({k: m.get(k) for k in ('id', 'title', 'kind', 'description', 'origin',
                                                  'created', 'updated', 'version')}
                           | {'principal': ult['principal'], 'files': ult['files']})
    out.sort(key=lambda m: m.get('updated') or '', reverse=True)
    return out


def read(aid: str) -> dict | None:
    d = _dir(aid)
    return _meta(d) if d and d.is_dir() else None


def file(aid: str, version: str, name: str) -> Path | None:
    """Safe path to a file of a version (nothing outside its folder)."""
    d = _dir(aid)
    if d is None or not VER_RE.match(version or '') or not name or '/' in name or name.startswith('.'):
        return None
    p = (d / version / name).resolve()
    if not p.is_relative_to(d.resolve()) or not p.is_file():
        return None
    return p


def of_relpath(relpath: str) -> tuple[str, str, str] | None:
    """/…/state/artifacts/<id>/v3/x.svg → (id, 'v3', 'x.svg'), o None."""
    try:
        rel = Path(relpath).expanduser().resolve().relative_to(BASE.resolve())
    except (ValueError, OSError):
        return None
    parts = rel.parts
    if len(parts) == 3 and ID_RE.match(parts[0]) and VER_RE.match(parts[1]):
        return parts[0], parts[1], parts[2]
    return None


def rename(aid: str, title: str) -> dict | None:
    d = _dir(aid)
    m = _meta(d) if d else None
    if not m or not title.strip():
        return None
    m['title'] = title.strip()[:200]
    _write_meta(d, m)
    return m


def delete(aid: str) -> bool:
    """To the trash (state/artifacts/.trash), not really deleted."""
    d = _dir(aid)
    if d is None or not d.is_dir():
        return False
    TRASH.mkdir(parents=True, exist_ok=True)
    d.rename(TRASH / f'{aid}-{time.strftime("%Y%m%d-%H%M%S")}')
    return True

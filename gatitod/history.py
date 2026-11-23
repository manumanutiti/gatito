#!/usr/bin/python3
"""History: all your Claude Code conversations (~/.claude/projects), including
terminal ones you already closed. From the web UI they can be read and continued in
the background (claude --bg --resume).

There are hundreds of MB of .jsonl: each file is read once and cached by
(mtime, size). The title comes from `customTitle` (the one you set) or from
`aiTitle` (the one Claude generated); if there is none, from the first message.
"""
from __future__ import annotations

import json
import threading
import unicodedata
from pathlib import Path

import core

_cache: dict[str, tuple[float, int, dict | None]] = {}
_lock = threading.Lock()
_dec = json.JSONDecoder()


def _last_str(data: bytes, key: bytes) -> str | None:
    """Last text value of `key` in the file (without decoding everything)."""
    i = data.rfind(b'"' + key + b'":"')
    if i < 0:
        return None
    start = i + len(key) + 3
    try:
        return _dec.raw_decode(data[start:start + 4000].decode('utf-8', 'ignore'))[0]
    except ValueError:
        return None


def _first_prompt(data: bytes) -> str | None:
    """First message you wrote (not commands or tool results)."""
    pos = 0
    for _ in range(40):
        i = data.find(b'"type":"user"', pos)
        if i < 0:
            return None
        a, b = data.rfind(b'\n', 0, i) + 1, data.find(b'\n', i)
        pos = b if b > 0 else len(data)
        try:
            d = json.loads(data[a:pos])
        except ValueError:
            continue
        c = (d.get('message') or {}).get('content')
        if d.get('isMeta') or not isinstance(c, str) or c.lstrip().startswith('<'):
            continue
        return c.strip()
    return None


def _meta(f: Path) -> dict | None:
    try:
        data = f.read_bytes()
    except OSError:
        return None
    title = _last_str(data, b'customTitle') or _last_str(data, b'aiTitle')
    prompt = _first_prompt(data)
    if not (title or prompt):
        return None  # empty or system-only sessions
    cwd = _last_str(data[:200_000], b'cwd') or ''
    return {'sid': f.stem, 'transcript': str(f), 'cwd': cwd,
            'title': (title or prompt.split('\n')[0])[:140], 'prompt': (prompt or '')[:300]}


def _norm(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', s.lower()) if unicodedata.category(c) != 'Mn')


def all_sessions() -> list[dict]:
    out = []
    with _lock:
        seen = set()
        # a machine where claude has not run yet has no ~/.claude/projects
        for d in (core.PROJECTS_DIR.iterdir() if core.PROJECTS_DIR.is_dir() else ()):
            try:
                files = list(d.glob('*.jsonl'))
            except OSError:  # folders of other users (containers)
                continue
            for f in files:
                try:
                    st = f.stat()
                except OSError:
                    continue
                key = str(f)
                seen.add(key)
                c = _cache.get(key)
                if not c or c[0] != st.st_mtime or c[1] != st.st_size:
                    c = (st.st_mtime, st.st_size, _meta(f))
                    _cache[key] = c
                if c[2]:
                    out.append({**c[2], 'updatedAt': int(st.st_mtime * 1000), 'size': st.st_size})
        for k in set(_cache) - seen:
            del _cache[k]
    return out


def search(q: str = '', limit: int = 40, offset: int = 0) -> dict:
    """Conversations not already in the session list, from most recent to oldest."""
    live = {a.get('sessionId') for a in core.list_agents()}
    items = [s for s in all_sessions() if s['sid'] not in live]
    if q.strip():
        words = _norm(q).split()
        items = [s for s in items if all(w in _norm(f"{s['title']} {s['prompt']} {s['cwd']}") for w in words)]
    items.sort(key=lambda s: -s['updatedAt'])
    return {'total': len(items), 'items': items[offset:offset + limit]}


def get(sid: str) -> dict | None:
    return next((s for s in all_sessions() if s['sid'] == sid), None)

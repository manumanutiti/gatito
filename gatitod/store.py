#!/usr/bin/python3
"""JSON state files: tolerant reading and atomic writing.

Several threads (the web UI, the status loop, the backlog) touch the same files.
`edit` serializes them per file and writes with rename, so one is never left half-written.
"""
from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path

_locks: dict[Path, threading.RLock] = {}
_locks_guard = threading.Lock()


def _lock(path: Path) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(Path(path), threading.RLock())


def read(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return default


def write(path: Path, data):
    path = Path(path)
    tmp = path.with_name(f'.{path.name}.tmp')
    with _lock(path):
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
        os.replace(tmp, path)


@contextmanager
def edit(path: Path, default):
    """Read, let the caller modify, and save, without another thread sneaking in between."""
    with _lock(path):
        data = read(path, default)
        yield data
        write(path, data)

"""Debugging whiteboard ("debug" profile): a small JSON per session that the web UI draws.

The agent never rewrites it: it sends one-line changes with `bin/whiteboard` (a test, a state,
the next step) and the web UI repaints. Pieces are of two kinds, in this order on the board:

- `usual`: phase 1, the usual causes of this symptom (cheapest to check first).
- `modules`: phase 2, the path the problem goes through (link, IP, DNS, ports, app,
  ingress, pods…), in path order. Where it fails decides where to look; with no clue,
  bottom-up.

Each test hangs from a piece: command or question, where it ran (agent@host or you@host),
result and the fragment of output that mattered. That is what the web UI shows when a piece
is clicked, and what a postmortem will be built from later.

A board is identified by the first session id of the conversation. Resuming with flags opens
a new session: `core.resume_session` records the root under `whiteboard` in the session's profile
info, and if the CLI still cannot find it, it adopts the open board updated most recently.
"""
from __future__ import annotations

import os
import re
import socket
import time
from contextlib import contextmanager
from pathlib import Path

import store

ROOT = Path(__file__).resolve().parent.parent
STATE = Path(os.environ.get('GATITO_STATE') or ROOT / 'state')
DIR = STATE / 'debug'
ALIAS = DIR / 'alias.json'                       # session id → board id (adopted on resume)
PROFILES_SESSION = STATE / 'profiles-session.json'  # core.PROFILE_SESSIONS

STATUSES = ('ok', 'fails', 'suspect', 'unchecked', 'deduced')
RESULTS = ('ok', 'fails', 'suspect', 'info')
ID_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,31}$')
SID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9-]{3,63}$')
ADOPT_S = 12 * 3600      # a resumed session only adopts a board touched within this window
MAX_PROBES = 200
LIM = {'text': 200, 'note': 300, 'cmd': 400, 'summary': 240, 'output': 2000, 'where': 60}


class Error(Exception):
    pass


def _cut(s, n) -> str:
    s = str(s or '').strip()
    return s if len(s) <= n else s[:n - 1] + '…'


def _now() -> str:
    return time.strftime('%Y-%m-%d %H:%M')


def relpath(pid: str) -> Path:
    if not SID_RE.match(pid or ''):
        raise Error(f'invalid whiteboard id "{pid}"')
    return DIR / f'{pid}.json'


def new(pid: str) -> dict:
    return {'v': 1, 'id': pid, 'symptom': '', 'wait': '', 'status': 'in-progress',
            'created': _now(), 'updated': _now(), 'usual': [], 'modules': [],
            'probes': [], 'next_step': None, 'conclusion': None}


def read(pid: str) -> dict | None:
    try:
        f = relpath(pid)
    except Error:
        return None
    d = store.read(f)
    if not isinstance(d, dict):
        return None
    try:
        d['mtime'] = f.stat().st_mtime
    except OSError:
        d['mtime'] = 0
    return d


def root(*ids: str | None) -> str | None:
    """The board of a session, by any of its ids (job short id or sessionId)."""
    ids = [i for i in ids if i and SID_RE.match(i)]
    perf = store.read(PROFILES_SESSION, {}) or {}
    for i in ids:
        info = perf.get(i)
        if isinstance(info, dict) and SID_RE.match(str(info.get('whiteboard') or '')):
            return info['whiteboard']
    alias = store.read(ALIAS, {}) or {}
    for i in ids:
        if SID_RE.match(str(alias.get(i) or '')):
            return alias[i]
    return next((i for i in ids if relpath(i).is_file()), None)


def adopt(sid: str) -> str | None:
    """A resumed session that lost the link: the open board touched most recently."""
    best, t = None, time.time() - ADOPT_S
    for f in DIR.glob('*.json') if DIR.is_dir() else []:
        if f.name == ALIAS.name:
            continue
        try:
            m = f.stat().st_mtime
        except OSError:
            continue
        if m > t and (store.read(f, {}) or {}).get('status') == 'in-progress':
            best, t = f.stem, m
    if best:
        with _lock():
            with store.edit(ALIAS, {}) as a:
                a[sid] = best
    return best


@contextmanager
def _lock():
    """Between processes: the agent may run several `whiteboard` at once."""
    DIR.mkdir(parents=True, exist_ok=True)
    with open(DIR / '.lock', 'w') as fh:
        try:
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_EX)
        except ImportError:   # Windows: no agents there anyway
            pass
        yield


@contextmanager
def changes(pid: str, create: bool = False):
    f = relpath(pid)
    with _lock():
        d = store.read(f)
        if not isinstance(d, dict):
            if not create:
                raise Error('no whiteboard yet: start with `whiteboard symptom "…"`')
            d = new(pid)
        d.pop('mtime', None)
        yield d
        d['updated'] = _now()
        store.write(f, d)


# ------------------------------------------------------------------ operations

def _piece(d: dict, pid: str) -> dict | None:
    return next((p for p in d['usual'] + d['modules'] if p['id'] == pid), None)


def _id(x: str) -> str:
    x = str(x or '').strip().lower()
    if not ID_RE.match(x):
        raise Error(f'invalid piece id "{x}": lowercase letters, digits and hyphens (dns, l3-ip, ingress)')
    return x


def _status(e: str) -> str:
    if e not in STATUSES:
        raise Error(f'invalid state "{e}": {", ".join(STATUSES)}')
    return e


def symptom(d: dict, text: str, wait: str = ''):
    d['symptom'] = _cut(text, LIM['text'])
    if wait:
        d['wait'] = _cut(wait, LIM['text'])


def piece(d: dict, kind: str, pid: str, name: str = '', status: str | None = None,
          note: str | None = None, layer: str | None = None, before: str | None = None) -> dict:
    """Adds or updates a usual cause (`usual`) or a module of the path (`modules`)."""
    pid = _id(pid)
    if status:
        _status(status)
    p = _piece(d, pid)
    if p and p['kind'] != kind:
        raise Error(f'"{pid}" already exists as a {"usual cause" if p["kind"] == "usual" else "module"}')
    if not p:
        p = {'id': pid, 'kind': kind, 'name': pid, 'status': 'unchecked', 'note': '', 'layer': ''}
        listing = d[kind]
        i = next((k for k, x in enumerate(listing) if before and x['id'] == before), len(listing))
        listing.insert(i, p)
    if name:
        p['name'] = _cut(name, LIM['text'])
    if status:
        p['status'] = status
    if note is not None:
        p['note'] = _cut(note, LIM['note'])
    if layer is not None:
        p['layer'] = _cut(layer, 12)
    return p


def status(d: dict, pid: str, e: str, note: str | None = None) -> dict:
    p = _piece(d, _id(pid))
    if not p:
        raise Error(f'no piece "{pid}": add it with `whiteboard cause` or `whiteboard module`')
    p['status'] = _status(e)
    if note is not None:
        p['note'] = _cut(note, LIM['note'])
    return p


def probe(d: dict, pid: str, res: str, cmd: str, summary: str, where: str | None = None,
           output: str = '') -> dict:
    if res not in RESULTS:
        raise Error(f'invalid result "{res}": {", ".join(RESULTS)}')
    pid = _id(pid)
    p = _piece(d, pid) or piece(d, 'modules', pid)   # unknown piece: a module named like its id
    if res != 'info':
        p['status'] = res
    n = (d['probes'][-1]['n'] if d['probes'] else 0) + 1
    t = {'n': n, 'piece': pid, 'res': res, 'cmd': _cut(cmd, LIM['cmd']),
         'summary': _cut(summary, LIM['summary']), 'output': _cut(output, LIM['output']),
         'where': _cut(where or f'agent@{socket.gethostname()}', LIM['where']), 'ts': _now()}
    d['probes'] = (d['probes'] + [t])[-MAX_PROBES:]
    sig = d.get('next_step')
    if sig and (sig.get('cmd') == t['cmd'] or (sig.get('piece') == pid and not sig.get('cmd'))):
        d['next_step'] = None   # it was the step that was pending
    return t


def next_step(d: dict, cmd: str | None, why: str = '', piece_id: str | None = None,
              who: str = 'agent'):
    if not cmd:
        d['next_step'] = None
        return
    if who not in ('agent', 'user'):
        raise Error('--who must be agent or user')
    d['next_step'] = {'cmd': _cut(cmd, LIM['cmd']), 'why': _cut(why, LIM['note']),
                      'piece': _id(piece_id) if piece_id else None, 'who': who}


def close(d: dict, cause: str, fix: str = ''):
    d['status'] = 'solved'
    d['next_step'] = None
    d['conclusion'] = {'cause': _cut(cause, LIM['note']), 'fix': _cut(fix, LIM['output']),
                       'ts': _now()}


def reopen(d: dict):
    d['status'] = 'in-progress'
    d['conclusion'] = None


MARK = {'ok': '✓', 'fails': '✗', 'suspect': '?', 'unchecked': '·', 'deduced': '≈', 'info': 'i'}


def text(d: dict) -> str:
    """Compact view for the agent (`whiteboard show`): a few hundred characters."""
    out = [f'Whiteboard {d["id"][:8]} · {d["status"]} · symptom: {d["symptom"] or "—"}']
    for kind, tit in (('usual', 'Usual causes'), ('modules', 'Path')):
        if d[kind]:
            out.append(f'{tit}: ' + '  '.join(f'{MARK[p["status"]]}{p["id"]}' for p in d[kind]))
    for t in d['probes'][-6:]:
        out.append(f'#{t["n"]} {MARK[t["res"]]} {t["piece"]}: {t["cmd"]} → {t["summary"]}')
    if d.get('next_step'):
        out.append(f'Next: {d["next_step"]["cmd"]}')
    return '\n'.join(out)

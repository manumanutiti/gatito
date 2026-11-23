#!/usr/bin/python3
"""Link with the "gatito" mod that runs inside every Claude Code session.

The mod (in ~/gatito/mod) talks to gatitod over a Unix socket, state/gatito.sock,
which only your user can open: no token needed and nothing is exposed to the network.

- Live state: the mod reports when each session and each turn starts and ends.
- Permissions: when Claude was about to ask you for permission, the mod registers it here and
  asks every few seconds whether you have decided yet (on the web or on your phone).
  The terminal dialog stays up at the same time: whoever answers first wins.
- Mailbox: what you write to a live session is delivered to it without resuming it.

If gatitod is not running, the mod does nothing and Claude works as usual.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import socketserver
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import hostinfo

STATE = hostinfo.ROOT / 'state'
SOCK = STATE / 'gatito.sock'
AUDIT = STATE / 'permissions.jsonl'   # every permission request and how it ended
LIVE_S = 15         # the mod polls the mailbox every 3 s: no news in 15 s means it is not alive
POLL_GONE_S = 40    # a permission whose mod stopped polling was resolved elsewhere
WAIT_S = 20         # each mod poll waits at most this long (fetch cuts off at 30 s)

_lock = threading.Condition()
_live: dict[str, dict] = {}     # session_id -> {cwd, state, seen, ...}
_perms: dict[str, dict] = {}    # id -> permission request
_inbox: dict[str, list[str]] = {}


def _now() -> float:
    return time.time()


def _audit(entry: dict):
    with open(AUDIT, 'a') as f:
        f.write(json.dumps({'ts': round(_now(), 1), **entry}, ensure_ascii=False) + '\n')


def _wait_limit() -> float:
    try:
        import core
        return float(core.config().get('perm_wait_min', 30)) * 60
    except (ImportError, TypeError, ValueError):
        return 1800.0


def _changed():
    """Something changed: the agent list should not wait for its cache."""
    try:
        import core
        core.invalidate()
    except ImportError:
        pass


# ------------------------------------------------------------ what gatito sees

def live(sid: str | None) -> dict | None:
    """The live state of a session, if its mod has given signs of life recently."""
    with _lock:
        s = _live.get(sid or '')
        if s and s['state'] != 'ended' and _now() - s['seen'] < LIVE_S:
            return dict(s)
    return None


def pending_perm(sid: str | None) -> dict | None:
    """The permission request awaiting your decision in that session, if any."""
    with _lock:
        ps = [p for p in _perms.values() if p['sid'] == sid and p['status'] == 'pending']
        return dict(max(ps, key=lambda p: p['created'])) if ps else None


def decide(perm_id: str, behavior: str, always: bool = False, message: str = '') -> dict:
    """Your decision from the web UI or the phone. The mod picks it up on its next poll."""
    if behavior not in ('allow', 'deny'):
        return {'ok': False, 'err': 'invalid decision'}
    with _lock:
        p = _perms.get(perm_id)
        if not p or p.get('kind') == 'ask':
            return {'ok': False, 'err': 'that request no longer exists'}
        if p['status'] != 'pending':
            return {'ok': False, 'err': 'it was already decided elsewhere'}
        if behavior == 'allow':
            d = {'behavior': 'allow'}
            if always and p.get('suggestions'):
                d['updatedPermissions'] = p['suggestions']
        else:
            d = {'behavior': 'deny', 'message': message.strip() or 'The user denied it from gatito.'}
        p.update(status=behavior, decision=d, decided=_now())
        _lock.notify_all()
    _audit({'id': perm_id, 'sid': p['sid'], 'tool': p['tool'], 'mode': p.get('mode'),
            'result': behavior, 'always': bool(always and p.get('suggestions')),
            'secs': round(p['decided'] - p['created'])})
    _changed()
    return {'ok': True}


def answer(perm_id: str, answers: dict) -> dict:
    """Your answer to a question with options: {question text: answer}."""
    answers = {str(k): str(v).strip() for k, v in (answers or {}).items() if str(v).strip()}
    if not answers:
        return {'ok': False, 'err': 'choose at least one answer'}
    with _lock:
        p = _perms.get(perm_id)
        if not p or p.get('kind') != 'ask':
            return {'ok': False, 'err': 'that question no longer exists'}
        if p['status'] != 'pending':
            return {'ok': False, 'err': 'it was already answered elsewhere'}
        p.update(status='answered', answers=answers, decided=_now())
        _lock.notify_all()
    _audit({'id': perm_id, 'sid': p['sid'], 'tool': p['tool'], 'result': 'answered',
            'secs': round(p['decided'] - p['created'])})
    _changed()
    return {'ok': True}


def send(sid: str, text: str) -> dict:
    """Leave a message for a live session: the mod delivers it when the session is free."""
    if not live(sid):
        return {'ok': False, 'err': 'the session does not have the mod active'}
    with _lock:
        _inbox.setdefault(sid, []).append(text)
    return {'ok': True, 'via': 'mod'}


# ------------------------------------------------------------ what the mod says

def _event(b: dict) -> dict:
    sid, ev = b.get('sid'), b.get('ev')
    if not sid:
        return {}
    with _lock:
        s = _live.setdefault(sid, {'sid': sid, 'state': 'idle', 'since': _now()})
        s['seen'] = _now()
        if ev == 'start':
            s.update(cwd=b.get('cwd'), version=b.get('version'))
        elif ev == 'turn':
            s.update(state='working', since=_now())
        elif ev == 'idle':
            s.update(state='idle', since=_now())
        elif ev == 'end':
            s.update(state='ended', since=_now())
            # whatever was left pending will not be picked up by anyone anymore
            for p in _perms.values():
                if p['sid'] == sid and p['status'] == 'pending':
                    p.update(status='gone', decided=_now())
            _inbox.pop(sid, None)
    _changed()
    return {}


def _perm_new(b: dict) -> dict:
    p = {'id': secrets.token_hex(6), 'sid': b.get('sid'), 'tool': str(b.get('tool') or '?'),
         'kind': 'ask' if b.get('kind') == 'ask' else 'perm',
         'input': b.get('input'), 'mode': b.get('mode'), 'agent': b.get('agent'),
         'suggestions': b.get('suggestions') or None, 'status': 'pending',
         'created': _now(), 'polled': _now()}
    with _lock:
        # a new request from the same session supersedes the previous ones
        for q in _perms.values():
            if q['sid'] == p['sid'] and q['status'] == 'pending':
                q.update(status='gone', decided=_now())
        _perms[p['id']] = p
        s = _live.get(p['sid'])
        if s:
            s['seen'] = _now()
    _audit({'id': p['id'], 'sid': p['sid'], 'tool': p['tool'], 'mode': p['mode'], 'result': 'asked'})
    _changed()
    return {'id': p['id']}


def _perm_wait(q: dict) -> dict:
    """The mod's poll: waits up to WAIT_S for you to decide."""
    pid = q.get('id', '')
    end = _now() + WAIT_S
    limit = _wait_limit()
    with _lock:
        while True:
            p = _perms.get(pid)
            if not p:
                return {'status': 'gone'}
            p['polled'] = _now()
            if p['status'] == 'pending' and _now() - p['created'] > limit:
                # nobody answered in time: the mod steps aside and the usual dialog remains
                p.update(status='expired', decided=_now())
                _audit({'id': pid, 'sid': p['sid'], 'tool': p['tool'], 'mode': p.get('mode'), 'result': 'expired'})
                threading.Thread(target=_changed, daemon=True).start()
            if p['status'] != 'pending':
                return {'status': p['status'], 'decision': p.get('decision'), 'answers': p.get('answers')}
            left = end - _now()
            if left <= 0:
                return {'status': 'pending'}
            _lock.wait(left)


def _perm_end(b: dict) -> dict:
    """The mod stopped waiting: it was answered in the terminal or it got tired of waiting."""
    with _lock:
        p = _perms.get(b.get('id', ''))
        if not p or p['status'] != 'pending':
            return {}
        p.update(status='gone', decided=_now())
    _audit({'id': p['id'], 'sid': p['sid'], 'tool': p['tool'], 'mode': p.get('mode'),
            'result': b.get('why') or 'gone', 'secs': round(p['decided'] - p['created'])})
    _changed()
    return {}


def _inbox_take(q: dict) -> dict:
    sid = q.get('sid', '')
    with _lock:
        s = _live.get(sid)
        if s:
            s['seen'] = _now()
        return {'texts': _inbox.pop(sid, [])}


ROUTES = {('POST', '/mod/event'): _event, ('POST', '/mod/perm'): _perm_new,
          ('GET', '/mod/perm'): _perm_wait, ('POST', '/mod/perm/end'): _perm_end,
          ('GET', '/mod/inbox'): _inbox_take}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _go(self, method: str):
        u = urllib.parse.urlparse(self.path)
        if method == 'GET':
            arg = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        else:
            n = int(self.headers.get('Content-Length', 0))
            try:
                arg = json.loads(self.rfile.read(n)) if n else {}
            except json.JSONDecodeError:
                arg = {}
        fn = ROUTES.get((method, u.path))
        body = json.dumps(fn(arg) if fn else {'error': 'not found'}, ensure_ascii=False).encode()
        self.send_response(200 if fn else 404)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._go('GET')

    def do_POST(self):
        self._go('POST')


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def get_request(self):
        req, _ = super().get_request()
        return req, ('mod', 0)   # BaseHTTPRequestHandler expects (host, port)

    def handle_error(self, request, client_address):
        # the mod cuts its poll short if it is answered in the terminal or the session closes
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, client_address)


def _sweep():
    """Every 5 s: forget old stuff and mark as resolved the permissions nobody polls anymore."""
    while True:
        time.sleep(5)
        now, gone = _now(), []
        with _lock:
            for p in _perms.values():
                if p['status'] == 'pending' and now - p['polled'] > POLL_GONE_S:
                    p.update(status='gone', decided=now)
                    gone.append(p)
            for k in [k for k, p in _perms.items() if p['status'] != 'pending' and now - p['decided'] > 3600]:
                del _perms[k]
            for k in [k for k, s in _live.items() if now - s['seen'] > 86400]:
                del _live[k]
                _inbox.pop(k, None)
        for p in gone:
            _audit({'id': p['id'], 'sid': p['sid'], 'tool': p['tool'], 'mode': p.get('mode'), 'result': 'gone'})
        if gone:
            _changed()


def start():
    """Open the socket (your user only) and the sweep, in background threads."""
    hostinfo.sock_path(SOCK)
    SOCK.unlink(missing_ok=True)
    old = os.umask(0o177)
    try:
        srv = _Server(str(SOCK), _Handler)
    finally:
        os.umask(old)
    threading.Thread(target=srv.serve_forever, name='modlink', daemon=True).start()
    threading.Thread(target=_sweep, name='modlink-sweep', daemon=True).start()
    return srv

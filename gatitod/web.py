#!/usr/bin/python3
"""Web server of the gatito coordinator.

Stdlib only. Listens on the local network. Token authentication: the first time you
pair by scanning a QR (or opening the link with ?t=TOKEN) and the browser stores the
token. Launches, replies, summarizes and runs actions.

Usage:  python3 web.py [--port 8777] [--host 0.0.0.0]
"""
from __future__ import annotations

import html
import http.server
import json
import os
import secrets
import socket
import ssl
import sys
import time
import traceback
import threading
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import artifacts
import backlog
import notebooks
import core
import debug
import convo
import history
import mask
import modlink
import profiles
import hostinfo
import qr
import router
try:  # notifications and HTTPS need python3-cryptography; without it, gatito stays on HTTP
    import push
    import tls
except ImportError:
    push = tls = None

PORT = 8777          # home network (HTTPS if there is a certificate)
HOST = '0.0.0.0'
LOCAL_PORT = 8778    # this PC only, HTTP: localhost already counts as secure
UPLOADS = core.UPLOADS
UPLOAD_TYPES = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp', 'image/gif': '.gif'}
TOKEN_FILE = core.STATE / 'token'


def get_token() -> str:
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    tok = secrets.token_urlsafe(18)
    TOKEN_FILE.write_text(tok)
    TOKEN_FILE.chmod(0o600)
    return tok


def lan_ip() -> str:
    """This machine's IP on the local network (config.json: lan_ip pins it; see hostinfo)."""
    return hostinfo.lan_ip(core.config().get('lan_ip'))


def listen_lan() -> bool:
    """Local-network port for the phone? config.json: listen_lan (off by default on macOS)."""
    v = core.config().get('listen_lan')
    return hostinfo.listen_lan_default() if v is None else bool(v)


def page_pair() -> bytes:
    """Phone pairing: QR with the URL and the token, drawn here (nothing from the internet)."""
    if not LAN['url']:
        body = ('<h2>The phone cannot connect</h2><p>gatito only listens on this machine. To use it '
                  'from your phone, set <code>"listen_lan": true</code> in <code>config.json</code> and '
                  'restart gatito.</p>')
    else:
        url = html.escape(LAN['url'])
        body = (f'<h2>Scan with your phone</h2><div id=q>{qr.svg(LAN["url"])}</div>'
                  f'<p>or open on your phone:<br><a href="{url}">{url}</a></p>'
                  '<p class=f><b>The first time</b>, your phone\'s browser will say the connection is not '
                  'private: it does not know gatito yet. Continue anyway (Advanced, Proceed), '
                  'tap <b>Notifications</b> and follow the steps to install its certificate. From then on '
                  'it connects without warnings and can receive notifications.</p>')
    return ('<!doctype html><meta charset=utf-8><title>Pair gatito</title><style>body{background:#1e1e2e;'
            'color:#cdd6f4;font-family:system-ui;text-align:center;padding:40px}#q{background:#fff;padding:16px;'
            'border-radius:12px;display:inline-block;line-height:0}a{color:#cba6f7;word-break:break-all}'
            'code{color:#f9e2af}.f{max-width:560px;margin:24px auto;color:#a6adc8;text-align:left;'
            f'line-height:1.5}}</style>{body}').encode()


TOKEN = get_token()
HERE = Path(__file__).parent
# UI: index.html + static/ (css and js per view) + vendor/ (mermaid, fonts).
# They are read on every request: editing the web UI does not require restarting gatito.
STATIC_TYPES = {'.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2',
                '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json'}
# at the root: the service worker only controls what hangs under its folder
ROOT_FILES = {'/sw.js': 'sw.js', '/manifest.webmanifest': 'manifest.webmanifest', '/icon.svg': 'icon.svg',
              '/icon-192.png': 'icon-192.png', '/icon-512.png': 'icon-512.png', '/badge-96.png': 'badge-96.png'}


def static_file(url_path: str) -> Path | None:
    """/static/... and /vendor/... without escaping their folder."""
    for prefix in ('static', 'vendor'):
        if url_path.startswith(f'/{prefix}/'):
            base = (HERE / prefix).resolve()
            p = (base / url_path[len(prefix) + 2:]).resolve()
            if p.is_relative_to(base) and p.is_file() and p.suffix in STATIC_TYPES:
                return p
    return None
IMG_TYPES = {'.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
             '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp'}


def image_path(raw: str) -> Path | None:
    """Only images inside your home: what agents draw for you."""
    try:
        p = Path(raw).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if p.suffix.lower() not in IMG_TYPES or not p.is_file():
        return None
    if not p.is_relative_to(core.HOME) or p.stat().st_size > 20_000_000:
        return None
    return p


# ------------------------------------------------------------------ routes
# Each API endpoint is a function registered with @api. GET receives the query (one
# value per key), POST the JSON body. They return something serializable.
# To add a new one, just write the function here, next to the others.
ROUTES: dict[tuple[str, str], callable] = {}


def api(method: str, path: str):
    def deco(fn):
        ROUTES[(method, path)] = fn
        return fn
    return deco


# Anonymization (mask.py): with `anon` in the body, what you type leaves for Claude with
# placeholders; what comes back (conversation, summaries, list, router) is always shown
# with the real values, except /api/convo?raw=1 (exactly what the AI saw).
def _out(b: dict, text: str | None) -> str | None:
    """A message for an agent: masked if the chat has anonymization on."""
    return mask.mask_message(text) if b.get('anon') and text else text


def _plain_out(b: dict, text: str | None) -> str | None:
    """Same, without the note for the AI (names, the router)."""
    return mask.mask(text)['text'] if b.get('anon') and text else text


AGENT_TEXT = ('name', 'result', 'needs', 'detail', 'suggestedReply')


def _agent_view(a: dict) -> dict:
    a = {**a, **{k: mask.unmask(a[k]) for k in AGENT_TEXT if isinstance(a.get(k), str)}}
    p = a.get('perm')
    if p:
        qs = (p.get('input') or {}).get('questions') if isinstance(p.get('input'), dict) else None
        # the answer goes back keyed by the question exactly as the AI wrote it
        a['perm'] = {**p, 'input': mask.unmask_obj(p.get('input')),
                     'qkeys': [q.get('question', '') for q in qs or []]}
    return a


@api('GET', '/api/agents')
def _agents(q):
    return [_agent_view(a) for a in core.list_agents()]


@api('GET', '/api/convo')
def _convo(q):
    msgs = convo.read_messages(q.get('transcript', ''), 120)
    if q.get('raw') == '1':
        return msgs
    return [m if m.get('kind') == 'image' else mask.unmask_obj(m) for m in msgs]


@api('GET', '/api/summary')
def _summary(q):
    # Haiku only when you ask: with cached=1 it returns what is already saved
    s = convo.summarize(q.get('transcript', ''), q.get('sid', ''), q.get('cached') == '1')
    return {**s, 'summary': mask.unmask(s.get('summary'))}


@api('GET', '/api/mask')
def _mask_get(q):
    return mask.public()


@api('POST', '/api/mask/save')
def _mask_save(b):
    return mask.save(b)


@api('POST', '/api/mask/preview')
def _mask_preview(b):
    """What would leave for Claude (without remembering what the detectors find)."""
    return mask.mask(b.get('text') or '', learn=False, entries=b.get('entries'))


@api('POST', '/api/mask/unmask')
def _mask_unmask(b):
    return {'text': mask.unmask(b.get('text') or '')}


@api('POST', '/api/mask/forget')
def _mask_forget(b):
    return mask.forget(b.get('real'))


@api('GET', '/api/meta')
def _meta(q):
    projects = [{**p, 'git': core.is_git_repo(p['path'])} for p in core.load_projects()]
    nb_projects = [{'id': core.NB_PREFIX + c['id'], 'path': c['relpath'], 'label': c['title'], 'git': False}
                 for c in notebooks.list_all()]
    return {'projects': projects, 'notebooks': nb_projects, 'actions': core.load_actions(),
            'models': core.MODELS, 'modes': core.MODES, 'efforts': core.EFFORTS,
            'profiles': [profiles.public(p) for p in profiles.list_all()],
            'defaults': {'model': core.DEFAULT_MODEL, 'mode': core.DEFAULT_MODE},
            'config': core.config(), 'push': bool(push), 'chats': str(core.CHATS),
            'lan_url': f'{SCHEME}://{lan_ip()}:{PORT}/'}


@api('GET', '/api/profiles')
def _profiles(q):
    """The Profiles view: all files, including the ones that are ignored, and why."""
    out = []
    for r in profiles.review_all():
        p = r['profile']
        out.append({'id': r['id'], 'file': r['file'], 'valid': bool(p), 'warnings': r['warnings'],
                    **(profiles.public(p) if p else {'title': r['id']}),
                    **({'n_allow': len(p['allow']), 'n_deny': len(p['deny'])} if p else {})})
    return {'root': str(profiles.BASE), 'profiles': out}


@api('GET', '/api/profile')
def _profile(q):
    """A profile from the inside: its file, what is left after validating it and what the
    agent really receives (prompt and effective rules, with the read-only ones and the permanent ones)."""
    r = profiles.card(q.get('id', ''))
    if not r:
        return {'ok': False, 'err': 'no such profile'}
    p, ef = r['profile'], None
    if p:
        ap = core.profile_contribution(p)
        ef = {'mode': ap['mode'], 'allow': ap['allow'], 'deny': ap['deny'],
              'always': core.DENY_TOOLS, 'prompt': ap['prompt'],
              'notebooks': [nb for nb in p['notebooks'] if notebooks.notebook_dir(nb)]}
    return {'ok': True, 'id': r['id'], 'file': r['file'], 'relpath': str(profiles.BASE / r['file']),
            'warnings': r['warnings'], 'text': r['text'], 'profile': p, 'effective': ef}


@api('POST', '/api/route')
def _route(b):
    # what the router answers or rewrites comes back with the real values
    return mask.unmask_obj(router.route(_plain_out(b, b.get('text', '')), b.get('project_id') or None,
                                        b.get('images')))


@api('POST', '/api/launch')
def _launch(b):
    # without `path`: no project, in a new folder. Without `worktree`, the profile's
    return core.launch_agent(b.get('path') or None, _out(b, b['task']), b.get('model'),
                             _plain_out(b, b.get('name')), b.get('mode'), b.get('effort'),
                             bool(b['worktree']) if 'worktree' in b else None, b.get('profile') or None)


@api('POST', '/api/ask/continue')
def _ask_continue(b):
    """A question the router answered becomes a session to continue it."""
    q, a = b['question'].strip(), (b.get('answer') or '').strip()
    task = ('We are continuing a conversation that started in gatito.\n\n'
            f'My question: {q}\n\nYour answer: {a}\n\nNow: {b["text"].strip()}')
    return core.launch_agent(None, _out(b, task), b.get('model'), _plain_out(b, f'chat: {q[:40]}'),
                             b.get('mode'), b.get('effort'), profile=b.get('profile') or None)


@api('POST', '/api/reply')
def _reply(b):
    return core.reply_agent(b.get('id') or '', b['session_id'], _out(b, b['text']), b.get('model') or None,
                            b.get('mode') or None, b.get('effort') or None)


@api('POST', '/api/attach-project')
def _attach_project(b):
    return core.attach_project(b.get('id') or '', b['session_id'], b['project_id'],
                               _plain_out(b, b.get('text') or ''))


@api('POST', '/api/perm/answer')
def _perm_answer(b):
    return modlink.answer(b['id'], {k: _plain_out(b, str(v)) for k, v in (b.get('answers') or {}).items()})


@api('POST', '/api/perm/decide')
def _perm_decide(b):
    return modlink.decide(b['id'], b['behavior'], bool(b.get('always')), _plain_out(b, b.get('message') or ''))


@api('POST', '/api/hide')
def _hide(b):
    return core.set_hidden(b['key'], bool(b.get('hide', True)))


@api('POST', '/api/stop')
def _stop(b):
    return core.stop_agent(b['id'])


@api('POST', '/api/remove')
def _remove(b):
    res = core.remove_agent(b['id'])
    if res['ok'] and b.get('session_id'):
        (convo.SUMM / f"{b['session_id']}.json").unlink(missing_ok=True)
    return res


@api('POST', '/api/project-add')
def _project_add(b):
    return core.add_project(b.get('path', ''))


@api('POST', '/api/project-remove')
def _project_remove(b):
    return core.remove_project(b['id'])


@api('POST', '/api/action')
def _action(b):
    return core.run_action(b['action_id'], b.get('desired'))


# history
@api('GET', '/api/history')
def _hist(q):
    r = history.search(q.get('q', ''), int(q.get('limit', 40)), int(q.get('offset', 0)))
    return {**r, 'items': [mask.unmask_obj(s, skip=('sid', 'transcript', 'cwd')) for s in r['items']]}


@api('POST', '/api/history/resume')
def _hist_resume(b):
    s = history.get(b['sid'])
    if not s:
        return {'ok': False, 'err': 'that conversation is gone'}
    return core.resume_session(s['sid'], s['cwd'], _out(b, b['text']), b.get('model') or None,
                               b.get('mode') or None, b.get('effort') or None)


# notifications
@api('GET', '/api/push/key')
def _push_key(q):
    return {'ok': bool(push), 'key': push.public_key() if push else None}


@api('POST', '/api/push/subscribe')
def _push_sub(b):
    return push.subscribe(b['subscription'], b.get('prefs'), b.get('label', '')) if push else {'ok': False}


@api('POST', '/api/push/unsubscribe')
def _push_unsub(b):
    return push.unsubscribe(b['endpoint']) if push else {'ok': False}


@api('POST', '/api/push/get')
def _push_get(b):
    s = push.get_sub(b['endpoint']) if push else None
    return {'ok': bool(s), 'prefs': (s or {}).get('prefs')}


@api('POST', '/api/push/test')
def _push_test(b):
    if not push:
        return {'ok': False, 'err': 'python3-cryptography is missing'}
    return push.notify('test', 'Gatito', 'This is how notifications will reach you.', '/', only=b['endpoint'])


# backlog
@api('GET', '/api/backlog')
def _bl_list(q):
    return backlog.list_items(include_launched=q.get('all') == '1')


@api('POST', '/api/backlog/add')
def _bl_add(b):
    return backlog.add(b)


@api('POST', '/api/backlog/update')
def _bl_update(b):
    return backlog.update(b['id'], b)


@api('POST', '/api/backlog/remove')
def _bl_remove(b):
    return backlog.remove(b['id'])


@api('POST', '/api/backlog/run')
def _bl_run(b):
    return backlog.run_now(b['id'])


# ------------------------------------------------------------------ artifacts
@api('GET', '/api/artifacts')
def _art_list(q):
    return artifacts.list_all()


@api('GET', '/api/artifact')
def _art_get(q):
    return artifacts.read(q.get('id', '')) or {'ok': False, 'err': 'not found'}


@api('POST', '/api/artifact/rename')
def _art_rename(b):
    return {'ok': bool(artifacts.rename(b['id'], b['title']))}


@api('POST', '/api/artifact/remove')
def _art_remove(b):
    return {'ok': artifacts.delete(b['id'])}


# ------------------------------------------------------------------ notebooks
@api('GET', '/api/notebooks')
def _nb_list(q):
    return {'notebooks': notebooks.list_all(), 'kinds': notebooks.KINDS, 'statuses': notebooks.STATUSES,
            'root': str(notebooks.BASE)}


def _nb_sessions(nb: str) -> list[dict]:
    """Notebook conversations: the ones that worked in its folder and the ones its notes cite."""
    d = notebooks.notebook_dir(nb)
    cited = notebooks.sessions_cited(nb)
    live = {a.get('sessionId'): a for a in core.list_agents()}
    out = {}
    for s in history.all_sessions():
        inside = notebooks.of_relpath(s['cwd']) == nb
        if inside or s['sid'] in cited:
            a = live.get(s['sid'])
            out[s['sid']] = {**s, 'inside': inside, 'notes': cited.get(s['sid'], []),
                             'agent': a and a.get('key'), 'ui': a and a.get('ui')}
    for sid, a in live.items():   # just launched: they may not have a .jsonl with a title yet
        if sid and sid not in out and notebooks.of_relpath(a.get('cwd')) == nb:
            out[sid] = {'sid': sid, 'title': a.get('name') or 'Session', 'cwd': a.get('cwd'), 'inside': True,
                        'updatedAt': a.get('updatedAt') or 0, 'notes': [], 'agent': a.get('key'), 'ui': a.get('ui')}
    return sorted(out.values(), key=lambda s: -(s.get('updatedAt') or 0)) if d else []


@api('GET', '/api/notebook')
def _nb_get(q):
    c = notebooks.notebook(q.get('id', ''))
    if not c:
        return {'ok': False, 'err': 'not found'}
    return {**c, 'sessions': _nb_sessions(c['id']), 'repos_dir': notebooks.repos(c['id'])}


@api('GET', '/api/notebook/note')
def _nb_note(q):
    n = notebooks.read(q.get('id', ''), q.get('relpath', ''))
    if n and q.get('v'):
        old = notebooks.version(q['id'], q['relpath'], q['v'])
        if old is None:
            return {'ok': False, 'err': 'that version does not exist'}
        meta, body = notebooks.split(old)
        n = {**n, 'text': old, 'body': body, 'meta': meta, 'version': q['v']}
    return n or {'ok': False, 'err': 'not found'}


@api('GET', '/api/session/notes')
def _ses_notes(q):
    """Notebook notes that cite a session (a debugging whiteboard goes first).
    All the session ids, comma-separated: on resume, the sessionId may change."""
    vistas, out = set(), []
    for sid in (q.get('sid') or '').split(',')[:8]:
        for n in notebooks.session_notes(sid.strip()):
            if (n['notebook'], n['relpath']) not in vistas:
                vistas.add((n['notebook'], n['relpath']))
                out.append(n)
    return sorted(out, key=lambda n: (not n['whiteboard'], -n['mtime']))


@api('GET', '/api/debug')
def _debug(q):
    """The debugging whiteboard of a session, by any of its ids (job and sessionId, comma-separated).
    With `m` (the mtime the web UI already has) and no change, just {'same': True}: it is asked every 2 s."""
    ids = [i.strip() for i in (q.get('ids') or '').split(',')[:8]]
    pid = debug.root(*ids)
    d = debug.read(pid) if pid else None
    if not d:
        return {'ok': True, 'whiteboard': None}
    if q.get('m') and str(d['mtime']) == q['m']:
        return {'ok': True, 'same': True}
    return {'ok': True, 'whiteboard': d}


@api('GET', '/api/notebook/history')
def _nb_hist(q):
    return notebooks.history(q.get('id', ''), q.get('relpath', ''))


@api('GET', '/api/notebooks/search')
def _nb_search(q):
    return notebooks.search(q.get('q', ''), q.get('id') or None)


def _nb_try(fn, *a, **k):
    try:
        return fn(*a, **k)
    except ValueError as e:
        return {'ok': False, 'err': str(e)}


@api('POST', '/api/notebook/create')
def _nb_create(b):
    return _nb_try(notebooks.create, b['title'].strip(), b.get('summary', '').strip(),
                   b.get('repos') or [], b.get('tags') or [])


@api('POST', '/api/notebook/folder')
def _nb_folder(b):
    return _nb_try(notebooks.create_folder, b['id'], b['relpath'], b.get('title', ''), b.get('summary', ''))


@api('POST', '/api/notebook/note/new')
def _nb_new_note(b):
    return _nb_try(notebooks.create_note, b['id'], b.get('folder', ''), b['title'].strip(),
                   b.get('kind') or 'note', b.get('summary', ''), b.get('tags') or [])


@api('POST', '/api/notebook/note/save')
def _nb_save(b):
    text = b.get('text')
    if text is None:   # the block editor: metadata on one side, body on the other
        meta = notebooks.clean_meta(b.get('meta'))
        text = notebooks.join(meta, b['body']) if meta else b['body']
    return notebooks.save(b['id'], b['relpath'], text, b.get('mtime'))


@api('POST', '/api/notebook/task')
def _nb_task(b):
    return notebooks.mark_task(b['id'], b['relpath'], int(b['line']), bool(b['done']), b.get('mtime'))


@api('POST', '/api/notebook/delete')
def _nb_remove(b):
    return notebooks.delete(b['id'], b.get('relpath', ''))


@api('POST', '/api/notebooks/autosave')
def _nb_autosave(b):
    return {'ok': True, 'commit': notebooks.autosave()}


# What is served of an artifact and how. All with a network-less CSP: what an agent
# generated cannot call the internet or gatito's API. HTML pages also run in a sandbox
# without "allow-same-origin" (opaque origin: no cookies, no gatito).
ART_TYPES = {'.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
             '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp',
             '.html': 'text/html; charset=utf-8', '.htm': 'text/html; charset=utf-8',
             '.pdf': 'application/pdf'}
CSP_IMAGE = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:"
CSP_PAGE = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
              "img-src data: blob:; font-src data:; media-src data: blob:; "
              "form-action 'none'; base-uri 'none'; frame-ancestors 'self'; sandbox allow-scripts")


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    # -------------------------------------------------- auth
    def _authed(self) -> bool:
        if self._this_pc():
            return True
        # token via header (fetch) or cookie (navigation)
        h = self.headers.get('X-Gatito-Token')
        if h and secrets.compare_digest(h, TOKEN):
            return True
        cookie = self.headers.get('Cookie', '')
        for part in cookie.split(';'):
            if part.strip().startswith('gatito='):
                return secrets.compare_digest(part.strip()[7:], TOKEN)
        return False

    def _this_pc(self) -> bool:
        """The browser on this PC, on a gatito page: it does not need pairing.

        Only on the local port (listens on 127.0.0.1). Host rules out "DNS rebinding"
        (a website whose domain points to 127.0.0.1) and Sec-Fetch-Site rules out another
        website sending orders to gatito: only the page itself or opening it by hand counts.
        Anything that is not a browser (curl, scripts) still needs the token.
        """
        if not getattr(self.server, 'is_local', False):
            return False
        if self.headers.get('Host') not in (f'127.0.0.1:{LOCAL_PORT}', f'localhost:{LOCAL_PORT}'):
            return False
        return self.headers.get('Sec-Fetch-Site') in ('same-origin', 'none')

    def _send(self, code, body=b'', ctype='application/json', extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self) -> dict:
        n = int(self.headers.get('Content-Length', 0))
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except json.JSONDecodeError:
            return {}

    def _dispatch(self, method: str, path: str, arg):
        fn = ROUTES.get((method, path))
        if not fn:
            return self._send(404, '{"error":"not found"}')
        try:
            return self._send(200, json.dumps(fn(arg), ensure_ascii=False))
        except KeyError as e:
            return self._send(400, json.dumps({'ok': False, 'err': f'missing {e}'}))
        except Exception as e:
            # without this the connection drops and the browser only sees "Failed to fetch"
            traceback.print_exc()
            return self._send(500, json.dumps({'ok': False, 'err': f'{type(e).__name__}: {e}'},
                                              ensure_ascii=False))

    # -------------------------------------------------- GET
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}

        if u.path == '/':
            # paired: ?t=TOKEN sets the cookie and redirects cleanly
            if q.get('t') and secrets.compare_digest(q['t'], TOKEN):
                sec = '; Secure' if isinstance(self.connection, ssl.SSLSocket) else ''
                self._send(302, b'', 'text/html', {
                    'Location': '/',
                    'Set-Cookie': f'gatito={TOKEN}; Max-Age=31536000; Path=/; SameSite=Lax{sec}'})
                return
            return self._send(200, (HERE / 'index.html').read_bytes(), 'text/html; charset=utf-8',
                              {'Cache-Control': 'no-cache'})

        if u.path in ROOT_FILES:
            f = HERE / 'static' / ROOT_FILES[u.path]
            return self._send(200, f.read_bytes(), STATIC_TYPES[f.suffix], {'Cache-Control': 'no-cache'})

        if u.path == '/ca.crt' and tls and tls.CA_CRT.exists():
            # the CA is public (it only serves to verify); needed before pairing
            return self._send(200, tls.ca_der(), 'application/x-x509-ca-cert', {
                'Content-Disposition': 'attachment; filename="gatito-ca.crt"'})

        sf = static_file(u.path)
        if sf:
            # vendor does not change; our own files are revalidated to see changes on reload
            cache = 'max-age=604800' if u.path.startswith('/vendor/') else 'no-cache'
            return self._send(200, sf.read_bytes(), STATIC_TYPES[sf.suffix], {'Cache-Control': cache})

        if not self._authed():
            return self._send(401, '{"error":"unauthorized"}')

        if u.path == '/api/file':
            p = image_path(q.get('path', ''))
            if not p:
                return self._send(404, '{"error":"not an accessible image"}')
            # img-src data: the SVGs from bin/diagram carry their icons inline as data:
            return self._send(200, p.read_bytes(), IMG_TYPES[p.suffix.lower()], {
                'Cache-Control': 'no-cache', 'Content-Security-Policy': CSP_IMAGE})

        if u.path == '/api/artifact/raw':
            return self._art_raw(q)

        if u.path == '/api/notebook/raw':
            return self._raw(notebooks.file(q.get('id', ''), q.get('relpath', '')), q)

        if u.path == '/pair' and getattr(self.server, 'is_local', False):
            # only on the local port: it carries the token (bin/pair.sh opens this page)
            return self._send(200, page_pair(), 'text/html; charset=utf-8', {'Cache-Control': 'no-store'})

        return self._dispatch('GET', u.path, q)

    def _art_raw(self, q):
        """A file of an artifact version. ?dl=1 downloads it."""
        return self._raw(artifacts.file(q.get('id', ''), q.get('v', ''), q.get('f', '')), q)

    def _raw(self, p, q):
        """A file of an artifact or a notebook, with its network-less CSP. ?dl=1 downloads it."""
        if not p:
            return self._send(404, '{"error":"not found"}')
        ext = p.suffix.lower()
        ctype = ART_TYPES.get(ext, 'text/plain; charset=utf-8')   # .py, .md, .csv…: text
        extra = {'Cache-Control': 'no-cache', 'X-Content-Type-Options': 'nosniff',
                 'Content-Security-Policy': CSP_PAGE if ext in ('.html', '.htm') else CSP_IMAGE}
        if q.get('dl'):
            name = urllib.parse.quote(p.name)
            extra['Content-Disposition'] = f"attachment; filename*=UTF-8''{name}"
        return self._send(200, p.read_bytes(), ctype, extra)

    # -------------------------------------------------- POST
    def do_POST(self):
        if not self._authed():
            return self._send(401, '{"error":"unauthorized"}')
        u = urllib.parse.urlparse(self.path)
        if u.path == '/api/upload':
            return self._upload()
        if u.path == '/api/notebook/image':
            return self._nb_image(u)
        return self._dispatch('POST', u.path, self._json_body())

    def _upload(self):
        """Pasted or attached image: saved to state/uploads and the agent reads it from there."""
        ext = UPLOAD_TYPES.get(self.headers.get('Content-Type', '').split(';')[0])
        n = int(self.headers.get('Content-Length', 0))
        if not ext or not 0 < n <= 20_000_000:
            self.rfile.read(n)
            return self._send(400, json.dumps({'ok': False, 'err': 'images only, up to 20 MB'}))
        f = UPLOADS / f'{time.strftime("%Y%m%d-%H%M%S")}-{secrets.token_hex(3)}{ext}'
        f.write_bytes(self.rfile.read(n))
        return self._send(200, json.dumps({'ok': True, 'path': str(f)}))


    def _nb_image(self, u):
        """An image for a note (block editor): to <note folder>/attachments/ inside the notebook."""
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        n = int(self.headers.get('Content-Length', 0))
        if not 0 < n <= notebooks.MAX_FILE:
            self.rfile.read(n)
            return self._send(400, json.dumps({'ok': False, 'err': 'up to 20 MB'}))
        r = notebooks.save_image(q.get('id', ''), q.get('relpath', ''), self.rfile.read(n),
                                     self.headers.get('Content-Type', '').split(';')[0],
                                     urllib.parse.unquote(self.headers.get('X-Filename', '')))
        return self._send(200 if r['ok'] else 400, json.dumps(r, ensure_ascii=False))


class ThreadingServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # clients speaking HTTP to the HTTPS port, rejected certificates, disconnects…
        if not isinstance(sys.exc_info()[1], (ssl.SSLError, ConnectionError, TimeoutError)):
            super().handle_error(request, client_address)
    allow_reuse_address = True


# The local network: certificate and pairing URL for the current IP. On a laptop the IP
# changes (home, office): status_loop checks every minute and redoes it without restarting.
LAN = {'ip': None, 'url': None, 'ctx': None}


def _pon_lan(ip: str):
    """Certificate for `ip` (the TLS context serves the new one to new connections) and pair-url."""
    if LAN['ctx'] is not None:
        LAN['ctx'].load_cert_chain(*tls.ensure([ip]))
    LAN['ip'], LAN['url'] = ip, f'{SCHEME}://{ip}:{PORT}/?t={TOKEN}'
    f = core.STATE / 'pair-url'
    f.write_text(LAN['url'])
    hostinfo.private(f)


def status_loop():
    """Every 5 s: status.json for the GNOME menu and notifications of agent changes."""
    f = core.STATE / 'status.json'
    backs = 0
    while True:
        backs += 1
        if LAN['ip'] and backs % 12 == 0:
            try:
                ip = lan_ip()
                if ip != LAN['ip']:
                    print(f'gatito: IP changed from {LAN["ip"]} to {ip}; certificate and pairing updated', flush=True)
                    _pon_lan(ip)
            except Exception:
                traceback.print_exc()
        try:
            ags = core.list_agents()
            if push:
                push.watch(ags)
            core.store.write(f, {
                'blocked': sum(1 for a in ags if a['group'] == 'waiting'),
                'working': sum(1 for a in ags if a['group'] == 'working'),
                **backlog.counts(),
                'ts': time.time()})
        except Exception:
            pass
        time.sleep(5)


SCHEME = 'http'


def main():
    global PORT, HOST, LOCAL_PORT, SCHEME
    args = sys.argv[1:]
    if '--port' in args:
        PORT = int(args[args.index('--port') + 1])
    if '--host' in args:
        HOST = args[args.index('--host') + 1]
    if '--local-port' in args:
        LOCAL_PORT = int(args[args.index('--local-port') + 1])
    local = ThreadingServer(('127.0.0.1', LOCAL_PORT), Handler)
    local.is_local = True
    srv = None
    if listen_lan() and HOST not in ('127.0.0.1', 'localhost'):
        srv = ThreadingServer((HOST, PORT), Handler)
        if tls:
            LAN['ctx'] = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            # the TLS handshake happens in each connection's thread, not in the accepting one
            srv.socket = LAN['ctx'].wrap_socket(srv.socket, server_side=True, do_handshake_on_connect=False)
            SCHEME = 'https'
        _pon_lan(lan_ip())
        print(f'gatito listening on {SCHEME}://{HOST}:{PORT} (network) and http://127.0.0.1:{LOCAL_PORT} (this PC)')
        print(f'   Pair a device by opening:\n   {LAN["url"]}')
    else:
        (core.STATE / 'pair-url').unlink(missing_ok=True)
        print(f'gatito listening only on http://127.0.0.1:{LOCAL_PORT} (this machine; '
              'config.json: "listen_lan": true for the phone)')
    # background threads: new services hook in here
    threading.Thread(target=status_loop, name='status', daemon=True).start()
    backlog.start()
    modlink.start()
    notebooks.start(core.config().get('notebooks_autosave_min', 10))
    if srv is None:
        return local.serve_forever()
    threading.Thread(target=local.serve_forever, name='local', daemon=True).start()
    srv.serve_forever()


if __name__ == '__main__':
    main()

"""Notebooks: gatito's durable state. Plain Markdown folders (they open as-is in
Obsidian) holding the notes, explanations, diagrams and workflows of a long job, which
agents read at the start and update at the end.

    notebooks/<notebook>/notebook.md        cover: title, goal, repos, tags
    notebooks/<notebook>/status.md          living memory: what is clear, decisions,
                                            open questions and next steps
    notebooks/<notebook>/<folder>/…         each folder is a project or topic (README.md
                                            with its metadata); they can be nested
    notebooks/<notebook>/**/diagrams/      SVG/PNG with their .py source
    notebooks/<notebook>/sessions/          summary of each important conversation

Every note starts with YAML metadata (frontmatter), see FIELDS. Conversations are not
copied: they are linked by id (the ones launched inside a notebook are associated
automatically by their folder).

`notebooks/` is its own git repo, outside gatito's: autosave makes a commit every few
minutes if anything changed, so any edit (yours or an agent's) can be undone.

Stdlib only and does not import core: used by web.py, core.py and bin/notebook.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import hostinfo

ROOT = hostinfo.ROOT
# GATITO_NOTEBOOKS: another folder (tests). To use your Obsidian vault, better a
# link: `ln -s ~/Obsidian/Gatito ~/gatito/notebooks`.
BASE = Path(os.environ.get('GATITO_NOTEBOOKS') or ROOT / 'notebooks')
TRASH = BASE / '.trash'
ID_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,79}$')
COVER = 'notebook.md'
STATUS = 'status.md'
INDEX = 'README.md'          # metadata of a folder (project or topic)

# Metadata of each note, in this order. `tags` and `aliases` are in English because
# those are the ones Obsidian understands (tag pane, links by alias).
FIELDS = ['title', 'kind', 'status', 'tags', 'summary', 'created', 'updated',
          'repos', 'sessions', 'sources', 'aliases']
KINDS = {
    'notebook': 'Notebook cover',
    'status': 'Living memory of the notebook or of a folder',
    'folder': 'Index of a project or topic',
    'note': 'Loose note',
    'explanation': 'Explanation to understand something',
    'decision': 'Decision made and why (ADR)',
    'runbook': 'Steps to operate or fix something',
    'flow': 'Process or workflow to follow, with its steps',
    'journal': 'Dated log',
    'reference': 'Data, commands or links for lookup',
    'session': 'Summary of a conversation with an agent',
    'debugging': 'Debugging whiteboard: symptom, diagram, hypotheses and tests',
}
STATUSES = ['draft', 'in-progress', 'review', 'done', 'archived']
PROCEDURES = {'runbook', 'flow'}   # their checkboxes are steps, not pending tasks
LISTS = {'tags', 'repos', 'sessions', 'sources', 'aliases'}
TEXT = {'.md', '.txt', '.py', '.yaml', '.yml', '.json', '.csv', '.tf', '.sh', '.mmd'}
MAX_FILE = 20_000_000
TASK_RE = re.compile(r'^(\s*(?:[-*+]|\d+[.)])\s+\[)([ xX])(\]\s)')

_cache: dict[str, tuple[float, int, dict]] = {}
_lock = threading.Lock()


# ------------------------------------------------------------------ utilities
def now(date_only: bool = False) -> str:
    return time.strftime('%Y-%m-%d' if date_only else '%Y-%m-%d %H:%M')


def slug(s: str, default: str = 'note') -> str:
    s = s.strip().lower()
    for a, b in zip('áéíóúüñàèìòùç', 'aeiouunaeiouc'):
        s = s.replace(a, b)
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')[:70].strip('-')
    return s or default


def notebook_dir(nb: str) -> Path | None:
    if not ID_RE.match(nb or ''):
        return None
    d = BASE / nb
    return d.resolve() if d.is_dir() else None   # resolved: notebooks may be a link (to your vault)


def safe_relpath(nb: str, relpath: str, exists: bool = True) -> Path | None:
    """A path inside the notebook: no escaping it, no hidden files (.git, .obsidian)."""
    d = notebook_dir(nb)
    if not d:
        return None
    relpath = (relpath or '').strip().strip('/')
    if any(p.startswith('.') for p in Path(relpath).parts):
        return None
    try:
        p = (d / relpath).resolve(strict=exists)
    except (OSError, RuntimeError):
        return None
    return p if p == d or p.is_relative_to(d) else None


def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f'.{p.name}.tmp')
    tmp.write_text(text, encoding='utf-8')
    tmp.replace(p)


# ------------------------------------------------------------------ frontmatter
# Minimal YAML, the kind gatito, agents and Obsidian write: `key: value`,
# lists `[a, b]` or in block form (`- a`). Whatever it does not understand stays as text.
def _valor(v: str):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
        return v[1:-1].replace('\\"', '"').replace('\\\\', '\\') if v[0] == '"' else v[1:-1].replace("''", "'")
    if v.startswith('[') and v.endswith(']'):
        inside = v[1:-1].strip()
        if not inside:
            return []
        return [_valor(x) for x in re.findall(r'"(?:[^"\\]|\\.)*"|\'[^\']*\'|[^,]+', inside) if x.strip()]
    return v


def split(text: str) -> tuple[dict, str]:
    """(metadata, body). Without frontmatter: ({}, text)."""
    if not text.startswith('---'):
        return {}, text
    m = re.match(r'---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)', text, re.S)
    if not m:
        return {}, text
    meta: dict = {}
    key = None
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        item = re.match(r'^\s+-\s*(.*)$', line) or re.match(r'^-\s+(.*)$', line)
        if item and key:
            if not isinstance(meta.get(key), list):
                meta[key] = []
            meta[key].append(_valor(item.group(1)))
            continue
        kv = re.match(r'^([A-Za-z_][\w-]*)\s*:\s*(.*)$', line)
        if kv:
            key = kv.group(1)
            meta[key] = _valor(kv.group(2)) if kv.group(2).strip() else ''
    for k in LISTS:
        if k in meta and not isinstance(meta[k], list):
            meta[k] = [x.strip() for x in str(meta[k]).split(',') if x.strip()]
    return meta, text[m.end():]


def _yaml(v) -> str:
    if isinstance(v, list):
        return '[' + ', '.join(_yaml(x) for x in v) + ']'
    s = str(v)
    if s == '' or re.search(r'[:#\[\]{},&*!|>\'"%@`]|^\s|\s$|^[-?]', s) or s.lower() in ('true', 'false', 'null', 'yes', 'no'):
        return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return s


def join(meta: dict, body: str) -> str:
    keys = [k for k in FIELDS if k in meta] + [k for k in meta if k not in FIELDS]
    lines = [f'{k}: {_yaml(meta[k])}' for k in keys if meta[k] is not None]
    return '---\n' + '\n'.join(lines) + '\n---\n' + (body if body.startswith('\n') else '\n' + body)


def _tasks(body: str) -> tuple[int, int]:
    open_count = done_count = 0
    in_code = False
    for line in body.splitlines():
        if line.lstrip().startswith('```'):
            in_code = not in_code
            continue
        m = not in_code and TASK_RE.match(line)
        if m and line[m.end():].strip():   # empty checkboxes from templates do not count
            if m.group(2) == ' ':
                open_count += 1
            else:
                done_count += 1
    return open_count, done_count


def _title(meta: dict, body: str, p: Path) -> str:
    if meta.get('title'):
        return str(meta['title'])
    m = re.search(r'^#\s+(.+)$', body, re.M)
    if m:
        return m.group(1).strip()
    name = p.parent.name if p.name in (INDEX, COVER) else p.stem
    return name.replace('-', ' ').replace('_', ' ').strip().capitalize()


def info(p: Path) -> dict:
    """Metadata of a note (cached by date and size)."""
    st = p.stat()
    with _lock:
        c = _cache.get(str(p))
        if c and c[0] == st.st_mtime and c[1] == st.st_size:
            return c[2]
    try:
        text = p.read_text(encoding='utf-8', errors='replace')
    except OSError:
        text = ''
    meta, body = split(text)
    open_count, done_count = _tasks(body)
    kind = str(meta.get('kind') or ('notebook' if p.name == COVER else 'status' if p.name == STATUS
                                    else 'folder' if p.name == INDEX else 'note'))
    d = {'title': _title(meta, body, p), 'kind': kind, 'status': str(meta.get('status') or ''),
         'tags': [str(t).lstrip('#') for t in meta.get('tags') or []],
         'summary': str(meta.get('summary') or ''), 'created': str(meta.get('created') or ''),
         'updated': str(meta.get('updated') or time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))),
         'sessions': [str(s) for s in meta.get('sessions') or []],
         'repos': [str(s) for s in meta.get('repos') or []],
         'tasks': [open_count, done_count], 'mtime': st.st_mtime, 'bytes': st.st_size,
         # the checkboxes of a runbook or flow are the procedure's steps, not pending
         # work: they do not count as "to do"
         'pending': 0 if kind in PROCEDURES else open_count,
         'frontmatter': bool(meta)}
    with _lock:
        _cache[str(p)] = (st.st_mtime, st.st_size, d)
    return d


# ------------------------------------------------------------------ reading
def _visible(d: Path):
    try:
        children = sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
    except OSError:
        return []
    return [h for h in children if not h.name.startswith('.') and not h.is_symlink()]


def tree(nb: str, max_nodes: int = 3000) -> dict | None:
    """The notebook as a tree: folders (with their README) and files (notes with metadata)."""
    d = notebook_dir(nb)
    if not d:
        return None
    count = [0]

    def node(c: Path, prof: int) -> dict:
        n = {'name': c.name, 'relpath': str(c.relative_to(d)) if c != d else '', 'children': []}
        if (c / INDEX).is_file():
            n['index'] = info(c / INDEX)
        for h in _visible(c):
            if count[0] >= max_nodes:
                n['cut'] = True
                break
            count[0] += 1
            if h.is_dir():
                if prof < 8:
                    n['children'].append(node(h, prof + 1))
            elif h.suffix.lower() == '.md':
                n['children'].append({'name': h.name, 'relpath': str(h.relative_to(d)), 'note': info(h)})
            else:
                n['children'].append({'name': h.name, 'relpath': str(h.relative_to(d)),
                                   'ext': h.suffix.lower().lstrip('.'), 'bytes': h.stat().st_size})
        return n
    return node(d, 0)


def _summary(nb: str, d: Path) -> dict:
    cover = info(d / COVER) if (d / COVER).is_file() else {}
    notes = folders = open_count = 0
    last = 0.0
    for p in d.rglob('*'):
        if any(x.startswith('.') for x in p.relative_to(d).parts):
            continue
        if p.is_dir():
            folders += 1
        elif p.suffix.lower() == '.md':
            i = info(p)
            notes += 1
            open_count += i['pending']
            last = max(last, i['mtime'])
    return {'id': nb, 'title': cover.get('title') or nb.replace('-', ' ').capitalize(),
            'summary': cover.get('summary', ''), 'status': cover.get('status', ''),
            'tags': cover.get('tags', []), 'repos': cover.get('repos', []),
            'notes': notes, 'folders': folders, 'tasks_open': open_count,
            'updated': time.strftime('%Y-%m-%d %H:%M', time.localtime(last)) if last else '',
            'mtime': last, 'relpath': str(d)}


def list_all() -> list[dict]:
    if not BASE.is_dir():
        return []
    out = [_summary(d.name, d) for d in _visible(BASE) if d.is_dir() and ID_RE.match(d.name)]
    return sorted(out, key=lambda c: -c['mtime'])


def notebook(nb: str) -> dict | None:
    d = notebook_dir(nb)
    if not d:
        return None
    return {**_summary(nb, d), 'tree': tree(nb)}


def read(nb: str, relpath: str) -> dict | None:
    p = safe_relpath(nb, relpath)
    if not p or not p.is_file() or p.suffix.lower() not in TEXT or p.stat().st_size > MAX_FILE:
        return None
    text = p.read_text(encoding='utf-8', errors='replace')
    meta, body = split(text) if p.suffix.lower() == '.md' else ({}, text)
    return {'relpath': str(p.relative_to(notebook_dir(nb))), 'text': text, 'body': body, 'meta': meta,
            'info': info(p) if p.suffix.lower() == '.md' else None, 'mtime': p.stat().st_mtime}


def file(nb: str, relpath: str) -> Path | None:
    p = safe_relpath(nb, relpath)
    if not p or not p.is_file() or p.stat().st_size > MAX_FILE:
        return None
    return p


def repos(nb: str) -> list[str]:
    """Folders of the notebook's repos (projects.json ids or paths), those that exist."""
    d = notebook_dir(nb)
    if not d or not (d / COVER).is_file():
        return []
    try:
        projects = {p['id']: p['path'] for p in json.loads((ROOT / 'projects.json').read_text())}
    except (OSError, ValueError, KeyError, TypeError):
        projects = {}
    out = []
    for r in info(d / COVER)['repos']:
        p = Path(projects.get(r, r)).expanduser()
        if p.is_absolute() and p.is_dir():
            out.append(str(p))
    return out


def of_relpath(path: str | None) -> str | None:
    """The notebook a working folder belongs to (or None)."""
    if not path:
        return None
    try:
        rel = Path(path).resolve().relative_to(BASE.resolve())
    except (ValueError, OSError):
        return None
    return rel.parts[0] if rel.parts and ID_RE.match(rel.parts[0]) else None


def sessions_cited(nb: str) -> dict[str, list[str]]:
    """Conversation ids found in the notes' metadata → notes that cite them."""
    d = notebook_dir(nb)
    out: dict[str, list[str]] = {}
    if not d:
        return out
    for p in d.rglob('*.md'):
        if any(x.startswith('.') for x in p.relative_to(d).parts):
            continue
        for s in info(p)['sessions']:
            out.setdefault(s, []).append(str(p.relative_to(d)))
    return out


# Index session → notes that cite it, for the session panel in the web UI (a debugging
# whiteboard). Refreshed at most every few seconds: walking the notebooks costs one stat
# per note (info() caches the rest by date and size), and the web UI asks often.
SESSION_INDEX_S = 4
_index = {'ts': 0.0, 'by_session': {}}


def is_whiteboard(relpath: str, kind: str) -> bool:
    return kind == 'debugging' or relpath.startswith('debugging/') or '/debugging/' in relpath


def session_notes(sid: str) -> list[dict]:
    """Notes from any notebook whose `sessions` includes this id, most recent first."""
    if not sid or not BASE.is_dir():
        return []
    with _lock:
        fresco = time.time() - _index['ts'] < SESSION_INDEX_S
    if not fresco:
        by_session: dict[str, list[tuple[str, str]]] = {}
        for d in _visible(BASE):
            if not (d.is_dir() and ID_RE.match(d.name)):
                continue
            for p in d.rglob('*.md'):
                if any(x.startswith('.') for x in p.relative_to(d).parts):
                    continue
                try:
                    for s in info(p)['sessions']:
                        by_session.setdefault(s, []).append((d.name, str(p.relative_to(d))))
                except OSError:
                    continue
        with _lock:
            _index.update(ts=time.time(), by_session=by_session)
    out = []
    for nb, relpath in _index['by_session'].get(sid, []):
        p = BASE / nb / relpath
        try:
            i = info(p)
        except OSError:
            continue
        out.append({'notebook': nb, 'relpath': relpath, 'title': i['title'], 'kind': i['kind'],
                    'status': i['status'], 'mtime': i['mtime'], 'whiteboard': is_whiteboard(relpath, i['kind'])})
    return sorted(out, key=lambda n: (not n['whiteboard'], -n['mtime']))


def search(q: str, nb: str | None = None, limit: int = 60) -> list[dict]:
    """Notes containing all the words (the web UI asks for 60; `notebook search`, 15)."""
    words = [w for w in _norm(q).split() if w]
    if not words:
        return []
    out = []
    for c in ([nb] if nb else [x['id'] for x in list_all()]):
        d = notebook_dir(c)
        if not d:
            continue
        for p in d.rglob('*.md'):
            rel = p.relative_to(d)
            if any(x.startswith('.') for x in rel.parts):
                continue
            i = info(p)
            cab = _norm(' '.join([i['title'], i['summary'], ' '.join(i['tags']), i['kind'], str(rel)]))
            try:
                body = _norm(p.read_text(encoding='utf-8', errors='replace'))
            except OSError:
                continue
            if all(w in cab or w in body for w in words):
                k = body.find(words[0])
                frag = body[max(0, k - 60):k + 120].replace('\n', ' ') if k >= 0 and words[0] not in cab else i['summary']
                out.append({'notebook': c, 'relpath': str(rel), 'title': i['title'], 'kind': i['kind'],
                            'status': i['status'], 'snippet': frag, 'peso': sum(w in cab for w in words),
                            'mtime': i['mtime']})
    out.sort(key=lambda r: (-r['peso'], -r['mtime']))
    return out[:limit]


# ------------------------------------------------------------------ context
# A big notebook must not eat the agent's context. Instead of reading whole files, the
# agent starts with `context`: a summary with a fixed budget (cover, trimmed state,
# index of folders and notes with their one-line summary) and then opens only the notes
# it needs. Never the SVGs: they carry the icons in base64.
CONTEXT_MAX = 8000        # characters (~2,000 tokens) of `notebook context`
NOTE_MAX = 12_000          # body characters: beyond that, split the note
STATUS_MAX = 5000          # status.md: living memory, not an archive
HISTORY_MAX = 8          # lines of the "History" section in status.md
HEAVY = {'.svg', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.pdf', '.html', '.htm'}
FOLDED_FOLDERS = {'diagrams', 'sessions', 'attachments'}


def _sections(body: str) -> list[tuple[str, list[str]]]:
    """[(title of the ## section or '', lines)] without the leading "# Title"."""
    out: list[tuple[str, list[str]]] = [('', [])]
    for line in body.splitlines():
        if re.match(r'^#\s', line) and len(out) == 1 and not any(l.strip() for l in out[0][1]):
            continue
        m = re.match(r'^##\s+(.*)$', line)
        if m:
            out.append((m.group(1).strip(), []))
        else:
            out[-1][1].append(line)
    return out


def status_compact(body: str, max_chars: int = STATUS_MAX // 2) -> str:
    """status.md for the context: no empty sections or done checkboxes, each section
    capped (a huge section does not crowd out the others) and the actionable parts
    (next steps and open questions) first."""
    priority = ('next', 'open question', 'decision', 'what is clear')
    secs = []
    for title, lines in _sections(body):
        lines = [l for l in lines if l.strip() and not re.match(r'^\s*[-*+]\s+\[[xX]\]\s', l)
                  and not re.fullmatch(r'\s*[-*+]\s+\[ \]\s*', l)]
        if not lines:
            continue
        cap = 5 if title.lower().startswith('history') else 12
        if len(lines) > cap:
            lines = lines[:cap] + [f'- … {len(lines) - cap} more in status.md']
        text = '\n'.join(lines)
        if len(text) > 900:
            text = text[:900].rsplit('\n', 1)[0] + '\n- … (continues in status.md)'
        order = next((k for k, p in enumerate(priority) if title.lower().startswith(p)), len(priority))
        secs.append((order, (f'### {title}\n' if title else '') + text))
    out = '\n'.join(t for _, t in sorted(secs, key=lambda s: s[0]))
    return out if len(out) <= max_chars else out[:max_chars].rsplit('\n', 1)[0] + '\n… (trimmed: the rest is in status.md)'


def context(nb: str, folder: str = '', max_chars: int = CONTEXT_MAX, max_notes: int | None = None) -> str | None:
    """What an agent needs to pick the notebook back up, with a fixed budget."""
    d = notebook_dir(nb)
    if not d:
        return None
    base = safe_relpath(nb, folder) if folder else d
    if not base or not base.is_dir():
        return None
    cover = info(d / COVER) if (d / COVER).is_file() else {}
    lines = [f'# Notebook "{cover.get("title") or nb}" ({nb}) — {d}']
    if cover.get('summary'):
        lines.append(f'Goal: {cover["summary"]}')
    extra = [f'repos: {", ".join(cover["repos"])}' if cover.get('repos') else '',
             f'tags: {", ".join(cover["tags"])}' if cover.get('tags') else '']
    if any(extra):
        lines.append(' · '.join(x for x in extra if x))

    def status_for(dd: Path, name: str, cap: int):
        e = dd / STATUS
        if e.is_file():
            _, body = split(e.read_text(encoding='utf-8', errors='replace'))
            txt = status_compact(body, cap)
            if txt:
                lines.extend(['', f'## State {name}(updated {info(e)["updated"]})', txt])

    # with a folder, the general state yields room to the folder's
    status_for(d, '', STATUS_MAX // 2 if base == d else 1200)
    if max_notes is None:
        max_notes = 20 if base == d else 40
    if base != d:
        idx = info(base / INDEX) if (base / INDEX).is_file() else {}
        rel = str(base.relative_to(d))
        lines += ['', f'## Folder {rel}/' + (f' — {idx["title"]}: {idx["summary"]}' if idx.get('summary') else '')]
        status_for(base, f'of {rel}/ ', STATUS_MAX // 2)

    # folders (one level under the base) with their counts
    folders, notes, heavy = [], [], 0
    for p in base.rglob('*'):
        rel = p.relative_to(d)
        parts = rel.relative_to(base.relative_to(d)).parts if base != d else rel.parts
        if any(x.startswith('.') for x in rel.parts):
            continue
        if p.is_file() and p.suffix.lower() in HEAVY:
            heavy += 1
        if p.is_file() and p.suffix.lower() == '.md' and p.name not in (COVER, STATUS, INDEX):
            if not any(x in FOLDED_FOLDERS for x in parts[:-1]):
                notes.append((p, info(p)))
    for h in _visible(base):
        if h.is_dir() and h.name not in FOLDED_FOLDERS:
            i = info(h / INDEX) if (h / INDEX).is_file() else {}
            mds = [p for p in h.rglob('*.md') if not any(x.startswith('.') for x in p.relative_to(h).parts)]
            open_count = sum(info(p)['pending'] for p in mds)
            folders.append(f'- {h.relative_to(d)}/ — {i.get("title", h.name)}'
                            + (f' [{i["status"]}]' if i.get('status') else '')
                            + (f': {i["summary"]}' if i.get('summary') else '')
                            + f' ({len(mds)} notes' + (f', {open_count} open tasks' if open_count else '') + ')')
    if folders:
        lines += ['', '## Folders'] + folders

    notes.sort(key=lambda x: -x[1]['mtime'])
    if notes:
        lines += ['', f'## Notes ({len(notes)}; most recent first; open them only if you need them)']
        for p, i in notes[:max_notes]:
            t = f' ☐{i["pending"]}' if i['pending'] else ''
            res = i['summary'] if len(i['summary']) <= 120 else i['summary'][:117].rsplit(' ', 1)[0] + '…'
            lines.append(f'- {p.relative_to(d)} [{i["kind"]}·{i["status"] or "?"}] {i["title"]}'
                          + (f' — {res}' if res else '') + t
                          + (' (large: read only the section you need)' if i['bytes'] > NOTE_MAX else ''))
        if len(notes) > max_notes:
            lines.append(f'- … and {len(notes) - max_notes} more: `notebook search "…" --in {nb}` or '
                          f'`notebook context {nb} <folder>`')
    sessions = (sorted((d / 'sessions').glob('*.md'), key=lambda p: -p.stat().st_mtime)
                if (d / 'sessions').is_dir() and base == d else [])
    if sessions:
        lines += ['', f'## Latest sessions ({len(sessions)})']
        lines += [f'- {p.relative_to(d)} — {info(p)["summary"] or info(p)["title"]}' for p in sessions[:3]]
    if heavy:
        lines += ['', f'({heavy} diagrams/images/pages. Do not read them: an SVG carries its icons in '
                       'base64 and weighs tens of thousands of tokens. Its source is the .py next to it.)']
    out = '\n'.join(lines)
    if len(out) > max_chars:
        out = out[:max_chars].rsplit('\n', 1)[0] + f'\n… (trimmed to {max_chars} characters: narrow it with a folder)'
    return out


def size_problems(p: Path) -> list[str]:
    """Size warnings for a note (for `notebook review`)."""
    i = info(p)
    out = []
    if p.name == STATUS:
        _, body = split(p.read_text(encoding='utf-8', errors='replace'))
        if len(body) > STATUS_MAX:
            out.append(f'status.md has {len(body)} characters (max {STATUS_MAX}): rewrite it shorter '
                       'and move the old material to a note in sessions/')
        hist = next((l for t, l in _sections(body) if t.lower().startswith('history')), [])
        n = sum(1 for l in hist if l.strip().startswith(('-', '*')))
        if n > HISTORY_MAX:
            out.append(f'history has {n} lines (max {HISTORY_MAX}): keep only the latest')
    elif i['bytes'] > NOTE_MAX:
        out.append(f'note of {i["bytes"] // 1000} KB (max {NOTE_MAX // 1000}): split it into several linked notes')
    return out


def _norm(s: str) -> str:
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFD', s.lower()) if unicodedata.category(c) != 'Mn')


# ------------------------------------------------------------------ writing
def template(title: str, kind: str = 'note', summary: str = '', tags=None, body: str = '',
              session: str | None = None, **extra) -> str:
    meta = {'title': title, 'kind': kind, 'status': extra.pop('status', 'draft'),
            'tags': list(tags or []), 'summary': summary, 'created': now(), 'updated': now()}
    if session:
        meta['sessions'] = [session]
    meta.update({k: v for k, v in extra.items() if v is not None})
    if not body:
        body = BODIES.get(kind, '').format(title=title)
    return join(meta, body)


# The whiteboard of a debugging session ("debug" profile): fixed sections in this order.
# The diagram is rewritten whole at each step; the classes paint the state of each piece.
WHITEBOARD_SECTIONS = ['Symptom', 'Context', 'Diagram', 'Hypotheses', 'Probes', 'Next step', 'Conclusion']
WHITEBOARD = '''
# {title}

## Symptom

What fails, in one sentence. What you would expect to see if everything were fine.

## Context

- Cluster / account / namespace:
- What changed:

## Diagram

```mermaid
flowchart TD
  client["Client"] --> service["Service"]
  classDef ok fill:#a6e3a1,stroke:#40a02b,color:#11111b
  classDef fails fill:#f38ba8,stroke:#d20f39,color:#11111b
  classDef suspect fill:#f9e2af,stroke:#df8e1d,color:#11111b
  classDef unchecked fill:#585b70,stroke:#9399b2,color:#cdd6f4
  class client,service unchecked
```

Legend: green, checked and fine · red, fails · yellow, suspect · grey, not checked yet.

## Hypotheses

| id | hypothesis | how it is checked | result | status |
|---|---|---|---|---|

## Probes

1. (command or question) → (what matters in the result) → (which hypothesis it touches)

## Next step

## Conclusion

'''

BODIES = {
    'note': '\n# {title}\n\n',
    'explanation': '\n# {title}\n\n## The idea in one sentence\n\n## What is underneath\n\n## What it looks like\n\n'
                   '## Common mistakes\n\n## To check I understand it\n\n',
    'decision': '\n# {title}\n\n## Context\n\n## Options\n\n## Decision\n\n## Consequences\n\n',
    'runbook': '\n# {title}\n\n## When to use it\n\n## Steps\n\n- [ ] \n\n## Check\n\n## If something fails\n\n',
    'flow': '\n# {title}\n\n## Goal\n\n## Steps\n\n- [ ] \n\n## Notes\n\n',
    'journal': '\n# {title}\n\n',
    'reference': '\n# {title}\n\n',
    'session': '\n# {title}\n\n## What was done\n\n## What was decided\n\n## What is left\n\n',
    'folder': '\n# {title}\n\n## Goal\n\n## Notes\n\n',
    'status': '\n# Status\n\n## What is clear\n\n## Decisions\n\n## Open questions\n\n'
              '## Next steps\n\n- [ ] \n\n## History\n\n',
    'notebook': '\n# {title}\n\n## Goal\n\n## Map\n\n## Folders\n\n',
    'debugging': WHITEBOARD,
}


def create(title: str, summary: str = '', repos_=None, tags=None, nb: str | None = None) -> dict:
    nb = nb or slug(title, 'notebook')
    if not ID_RE.match(nb):
        raise ValueError('invalid notebook name')
    d = BASE / nb
    if d.exists():
        raise ValueError(f'notebook "{nb}" already exists')
    ensure_root()
    d.mkdir(parents=True)
    _write(d / COVER, template(title, 'notebook', summary, tags, status='in-progress',
                                     repos=list(repos_ or [])))
    _write(d / STATUS, template(f'Status of {title}', 'status', 'Living memory: what is clear, '
                                    'what was decided, what is pending.', tags, status='in-progress'))
    return {'ok': True, 'id': nb, 'relpath': str(d)}


def create_folder(nb: str, relpath: str, title: str = '', summary: str = '') -> dict:
    p = safe_relpath(nb, '/'.join(slug(x, 'folder') for x in relpath.split('/') if x.strip()), exists=False)
    if not p or p == notebook_dir(nb):
        raise ValueError('invalid path')
    p.mkdir(parents=True, exist_ok=True)
    if not (p / INDEX).exists():
        _write(p / INDEX, template(title or p.name.replace('-', ' ').capitalize(), 'folder',
                                        summary, status='in-progress'))
    return {'ok': True, 'relpath': str(p.relative_to(notebook_dir(nb)))}


def create_note(nb: str, folder: str, title: str, kind: str = 'note', summary: str = '',
               tags=None, body: str = '', session: str | None = None) -> dict:
    base = safe_relpath(nb, folder or '', exists=False)
    if not base:
        raise ValueError('invalid folder')
    if kind not in KINDS:
        raise ValueError(f'unknown type: {kind} (valid: {", ".join(KINDS)})')
    base.mkdir(parents=True, exist_ok=True)
    name = slug(title)
    if kind in ('journal', 'session', 'debugging') and not re.match(r'\d{4}-\d{2}-\d{2}', name):
        name = f'{now(True)}-{name}'   # date first, unless the title already has one
    p, n = base / f'{name}.md', 2
    while p.exists():
        p, n = base / f'{name}-{n}.md', n + 1
    _write(p, template(title, kind, summary, tags, body, session))
    return {'ok': True, 'relpath': str(p.relative_to(notebook_dir(nb))), 'path': str(p)}


def save(nb: str, relpath: str, text: str, mtime: float | None = None, session: str | None = None) -> dict:
    """Saves a note. With `mtime`, refuses if someone changed it while you were editing."""
    p = safe_relpath(nb, relpath, exists=False)
    if not p or p.suffix.lower() not in TEXT:
        return {'ok': False, 'err': 'invalid path'}
    if mtime is not None and p.exists() and abs(p.stat().st_mtime - float(mtime)) > 1e-3:
        return {'ok': False, 'conflict': True, 'err': 'the note changed while you were editing it',
                'actual': p.read_text(encoding='utf-8', errors='replace'), 'mtime': p.stat().st_mtime}
    if p.suffix.lower() == '.md':
        meta, body = split(text)
        if meta:
            meta['updated'] = now()
            if session and session not in meta.get('sessions', []):
                meta['sessions'] = [*meta.get('sessions', []), session]
            text = join(meta, body)
    _write(p, text)
    return {'ok': True, 'mtime': p.stat().st_mtime, 'relpath': str(p.relative_to(notebook_dir(nb)))}


def mark_task(nb: str, relpath: str, line: int, done: bool, mtime: float | None = None) -> dict:
    """Checks or unchecks the `- [ ]` box on line `line` (counting from 0, whole file)."""
    p = safe_relpath(nb, relpath)
    if not p or p.suffix.lower() != '.md':
        return {'ok': False, 'err': 'invalid path'}
    if mtime is not None and abs(p.stat().st_mtime - float(mtime)) > 1e-3:
        return {'ok': False, 'conflict': True, 'err': 'the note has changed: reload it'}
    lines = p.read_text(encoding='utf-8').split('\n')
    if not 0 <= line < len(lines) or not TASK_RE.match(lines[line]):
        return {'ok': False, 'err': 'there is no checkbox on that line'}
    lines[line] = TASK_RE.sub(lambda m: m.group(1) + ('x' if done else ' ') + m.group(3), lines[line], 1)
    return save(nb, relpath, '\n'.join(lines))


def adjuntar(nb: str, folder: str, files: list[Path], sub: str = 'diagrams') -> list[str]:
    """Copies files (a diagram with its PNG and .py, a screenshot…) to <folder>/<sub>/.
    Returns their paths relative to the folder, to link them from a note there."""
    base = safe_relpath(nb, '/'.join(x for x in [folder.strip('/'), sub] if x), exists=False)
    if not base:
        raise ValueError('invalid folder')
    base.mkdir(parents=True, exist_ok=True)
    out = []
    for f in files:
        if not f.is_file() or f.stat().st_size > MAX_FILE:
            raise ValueError(f'cannot attach {f}')
        shutil.copy2(f, base / f.name)
        out.append(f'{sub}/{f.name}' if sub else f.name)
    return out


IMAGES = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp', 'image/gif': '.gif'}


def save_image(nb: str, note_relpath: str, data: bytes, kind: str, name: str = '') -> dict:
    """An image added from the block editor (pasted, dropped or picked): to <note folder>/attachments/.
    Returns its path relative to the note, the one the Markdown links."""
    ext = IMAGES.get(kind)
    if not ext or not 0 < len(data) <= MAX_FILE:
        return {'ok': False, 'err': 'images only (png, jpg, webp, gif), up to 20 MB'}
    folder = str(Path(note_relpath or '').parent).strip('.').strip('/')
    base = safe_relpath(nb, '/'.join(x for x in [folder, 'attachments'] if x), exists=False)
    if not base:
        return {'ok': False, 'err': 'invalid path'}
    base.mkdir(parents=True, exist_ok=True)
    stem = slug(Path(name).stem, 'image')[:40]
    f = base / f'{time.strftime("%Y%m%d-%H%M%S")}-{stem}{ext}'
    n = 2
    while f.exists():
        f, n = f.with_name(f'{f.stem.rsplit("~", 1)[0]}~{n}{ext}'), n + 1
    f.write_bytes(data)
    return {'ok': True, 'rel': f'attachments/{f.name}', 'relpath': str(f.relative_to(notebook_dir(nb)))}


def clean_meta(meta) -> dict:
    """Metadata coming from the web editor: keys and strings (or lists of strings) on one line only."""
    out = {}
    for k, v in (meta or {}).items() if isinstance(meta, dict) else []:
        if not isinstance(k, str) or not re.match(r'^[A-Za-z_][\w-]*$', k):
            continue
        if isinstance(v, list):
            out[k] = [' '.join(str(x).split()) for x in v if str(x).strip()]
        elif v is not None:
            out[k] = ' '.join(str(v).split())
    return out


def delete(nb: str, relpath: str) -> dict:
    """To the trash (notebooks/.trash), never really deleted. Empty path: the whole notebook."""
    p = safe_relpath(nb, relpath)
    if not p:
        return {'ok': False, 'err': 'invalid path'}
    dest = TRASH / nb / f'{time.strftime("%Y%m%d-%H%M%S")}-{p.name}'
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p), dest)
    return {'ok': True, 'trash': str(dest)}


# ------------------------------------------------------------------ autosave
def _git(*args, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(['git', '-C', str(BASE), *args], capture_output=True, text=True, timeout=timeout)


# Claude Code background sessions (the ones gatito launches) cannot use Edit/Write in a
# repo without first isolating in a worktree. That makes no sense for notebooks (notes
# must show up at once and autosave already gives history), so the notebooks/ repo turns
# it off. Only here: gatito's code repo stays protected.
CLAUDE_SETTINGS = {'worktree': {'bgIsolation': 'none'}}


def ensure_root():
    """notebooks/ as its own git repo, with its .gitignore and its Claude Code settings."""
    BASE.mkdir(parents=True, exist_ok=True)
    if hostinfo.git_ok() and not (BASE / '.git').exists():
        _git('init', '-q')
    if not (BASE / '.gitignore').exists():
        (BASE / '.gitignore').write_text('.trash/\n.obsidian/workspace*.json\n*.tmp\n')
    settings = BASE / '.claude' / 'settings.json'
    if not settings.exists():
        _write(settings, json.dumps(CLAUDE_SETTINGS, indent=2) + '\n')


def autosave() -> str | None:
    """Commit of everything changed in notebooks/ (own repo, local). Returns the hash or None."""
    if not BASE.is_dir() or not hostinfo.git_ok():
        return None
    ensure_root()
    _git('add', '-A')
    if _git('diff', '--cached', '--quiet').returncode == 0:
        return None
    n = len(_git('diff', '--cached', '--name-only').stdout.split())
    r = _git('-c', 'user.name=gatito', '-c', 'user.email=gatito@localhost',
             'commit', '-q', '-m', f'Autosave {now()}: {n} file{"s" if n != 1 else ""}')
    return _git('rev-parse', '--short', 'HEAD').stdout.strip() if r.returncode == 0 else None


def history(nb: str, relpath: str, limit: int = 30) -> list[dict]:
    """Saved versions of a note (from autosave)."""
    p = safe_relpath(nb, relpath, exists=False)
    if not p or not (BASE / '.git').exists():
        return []
    try:
        rel = str(p.relative_to(BASE.resolve()))
    except ValueError:
        return []
    r = _git('log', f'-{limit}', '--follow', '--format=%h%x09%ci%x09%s', '--', rel)
    out = []
    for line in r.stdout.splitlines():
        h, date, msg = (line.split('\t') + ['', ''])[:3]
        out.append({'hash': h, 'date': date[:16], 'message': msg})
    return out


def version(nb: str, relpath: str, h: str) -> str | None:
    p = safe_relpath(nb, relpath, exists=False)
    if not p or not re.fullmatch(r'[0-9a-f]{4,40}', h or ''):
        return None
    try:
        r = _git('show', f'{h}:{p.relative_to(BASE.resolve())}')
    except ValueError:
        return None
    return r.stdout if r.returncode == 0 else None


def start(cada_min: float = 10):
    """Autosave thread. With 0, off."""
    if not cada_min:
        return

    def loop():
        while True:
            time.sleep(max(60, cada_min * 60))
            try:
                autosave()
            except Exception:
                pass
    threading.Thread(target=loop, name='notebooks', daemon=True).start()

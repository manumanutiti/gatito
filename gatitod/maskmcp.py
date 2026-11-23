#!/usr/bin/python3
"""MCP server of the anonymous sessions: the agent's file and shell tools, masked.

An anonymous session (core.launch_agent with anon) has no built-in Read, Write, Edit,
Grep, Glob or Bash: it works with these tools instead, and each one
  - puts the real values back in what the agent sends (paths, contents, commands),
    so what reaches your disk and your shell is correct;
  - masks what comes back (file contents, search results, command output) with the
    same dictionary and vault as the chat (mask.py), so the AI only sees placeholders.

The project is presented as /workspace: the real path (with your user and the client's
folder) never reaches the AI. The session itself runs in an empty folder, so Claude Code
does not put the project's git status, CLAUDE.md or memory in its context either.

Usage (Claude Code starts it, see core._anon_flags):
    maskmcp.py --root <project> [--extra <dir>]... [--read-only]
Protocol: MCP over stdio (JSON-RPC 2.0, one message per line). Stdlib only.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import mask  # noqa: E402

VROOT = '/workspace'
MAX_OUT = 30_000          # characters of command output / search results
MAX_LINES = 2000
MAX_LINE = 2000
IMG = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif',
       '.webp': 'image/webp'}
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.terraform', '.mypy_cache'}
# the same barrier as core.DENY_TOOLS for the built-in Bash: nothing gets published from here
DENY_CMD = re.compile(r'\b(git\s+(?:-C\s+\S+\s+)?push|gh\s+(?:pr\s+(?:create|merge)|release|repo\s+create))\b')

ROOT: Path = Path.cwd()
EXTRA: list[Path] = []
READ_ONLY = False


class ToolError(Exception):
    pass


# ------------------------------------------------------------------ paths and masking

def to_real_text(s: str) -> str:
    """What the agent sends: placeholders -> real values, /workspace -> the project."""
    s = mask.unmask(s or '')
    return re.sub(rf'(?<![\w/.-]){re.escape(VROOT)}(?![\w-])', lambda m: str(ROOT), s)


def to_ai(s: str) -> str:
    """What goes back to the agent: the project as /workspace, then masked."""
    s = s or ''
    for real in sorted({str(ROOT), str(ROOT.resolve())}, key=len, reverse=True):
        s = s.replace(real, VROOT)
    s = s.replace(str(Path.home()), '~')
    return mask.mask(s)['text']


def real_path(p: str, write: bool = False) -> Path:
    if not p:
        raise ToolError('file_path is required')
    p = to_real_text(p.strip())
    path = Path(p).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    path = Path(os.path.normpath(path))
    allowed = [ROOT] + ([] if write else EXTRA)
    if not any(path == a or path.is_relative_to(a) for a in allowed):
        raise ToolError(f'{to_ai(str(path))} is outside {VROOT}' + ('' if write else ' and the shared folders'))
    return path


def vpath(path: Path) -> str:
    return to_ai(str(path))


# ------------------------------------------------------------------ tools

def t_read(a: dict):
    path = real_path(a.get('file_path', ''))
    if path.is_dir():
        raise ToolError(f'{vpath(path)} is a folder: use glob')
    if not path.is_file():
        raise ToolError(f'{vpath(path)} does not exist')
    if path.suffix.lower() in IMG:   # pasted images: they cannot be masked, they go as they are
        if path.stat().st_size > 5_000_000:
            raise ToolError('image too large')
        return [{'type': 'image', 'data': base64.b64encode(path.read_bytes()).decode(),
                 'mimeType': IMG[path.suffix.lower()]}]
    raw = path.read_bytes()
    if b'\0' in raw[:8000]:
        raise ToolError(f'{vpath(path)} is a binary file')
    lines = raw.decode('utf-8', 'replace').splitlines()
    off = max(int(a.get('offset') or 1), 1)
    lim = min(int(a.get('limit') or MAX_LINES), MAX_LINES)
    chunk = lines[off - 1:off - 1 + lim]
    out = '\n'.join(f'{i:>6}\t{ln[:MAX_LINE]}' for i, ln in enumerate(chunk, off))
    more = len(lines) - (off - 1 + len(chunk))
    if more > 0:
        out += f'\n… {more} more lines (use offset/limit)'
    return to_ai(out) if out else '(empty file)'


def _guard_write():
    if READ_ONLY:
        raise ToolError('this session is read-only')


def t_write(a: dict):
    _guard_write()
    path = real_path(a.get('file_path', ''), write=True)
    content = to_real_text(a.get('content') or '')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return f'Wrote {vpath(path)} ({len(content.splitlines())} lines)'


def t_edit(a: dict):
    _guard_write()
    path = real_path(a.get('file_path', ''), write=True)
    if not path.is_file():
        raise ToolError(f'{vpath(path)} does not exist')
    text = path.read_text()
    old, new = to_real_text(a.get('old_string') or ''), to_real_text(a.get('new_string') or '')
    if not old:
        raise ToolError('old_string is empty')
    n = text.count(old)
    if n == 0:
        raise ToolError('old_string is not in the file (read it again: it must match exactly)')
    if n > 1 and not a.get('replace_all'):
        raise ToolError(f'old_string appears {n} times: add context or use replace_all')
    k = n if a.get('replace_all') else 1
    path.write_text(text.replace(old, new, k))
    return f'Edited {vpath(path)} ({k} {"change" if k == 1 else "changes"})'


def t_glob(a: dict):
    base = real_path(a.get('path') or VROOT)
    pat = to_real_text(a.get('pattern') or '**/*')
    hits = []
    for p in base.glob(pat):
        if any(part in SKIP_DIRS for part in p.relative_to(base).parts) or not p.is_file():
            continue
        hits.append(p)
        if len(hits) > 2000:
            break
    hits.sort(key=lambda p: -p.stat().st_mtime)
    out = '\n'.join(str(p) for p in hits[:300])
    if len(hits) > 300:
        out += f'\n… {len(hits) - 300} more'
    return to_ai(out) if out else 'No files found'


def _run(cmd: list[str] | str, cwd: Path, timeout: int, shell: bool = False) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, shell=shell, capture_output=True, text=True,
                           timeout=timeout, executable='/bin/bash' if shell else None,
                           stdin=subprocess.DEVNULL, errors='replace')
        out = r.stdout + (('\n' if r.stdout and r.stderr else '') + r.stderr if r.stderr else '')
        return r.returncode, out
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or '') if isinstance(e.stdout, str) else (e.stdout or b'').decode(errors='replace')
        return 124, out + f'\n(stopped after {timeout} s)'


def _cap(s: str) -> str:
    return s if len(s) <= MAX_OUT else s[:MAX_OUT] + f'\n… output cut ({len(s) - MAX_OUT} more characters)'


def t_grep(a: dict):
    base = real_path(a.get('path') or VROOT)
    pattern = to_real_text(a.get('pattern') or '')
    if not pattern:
        raise ToolError('pattern is required')
    mode = a.get('output_mode') or 'files_with_matches'
    rg = shutil.which('rg')
    if rg:
        cmd = [rg, '--no-heading', '--color', 'never', '-g', '!.git']
        cmd += {'files_with_matches': ['-l'], 'count': ['-c']}.get(mode, ['-n'])
        if a.get('-i'):
            cmd.append('-i')
        if a.get('glob'):
            cmd += ['-g', to_real_text(a['glob'])]
        if mode == 'content' and a.get('context'):
            cmd += ['-C', str(int(a['context']))]
        cmd += ['--', pattern, str(base)]
    else:
        cmd = ['grep', '-rIE', '--exclude-dir=.git', '--exclude-dir=node_modules']
        cmd += {'files_with_matches': ['-l'], 'count': ['-c']}.get(mode, ['-n'])
        if a.get('-i'):
            cmd.append('-i')
        if a.get('glob'):
            cmd.append(f'--include={to_real_text(a["glob"])}')
        if mode == 'content' and a.get('context'):
            cmd += ['-C', str(int(a['context']))]
        cmd += ['--', pattern, str(base)]
    code, out = _run(cmd, ROOT, 60)
    if code == 1 and not out.strip():
        return 'No matches'
    lines = out.splitlines()
    head = int(a.get('head_limit') or 0)
    if head:
        lines = lines[:head]
    return to_ai(_cap('\n'.join(lines)))


def t_bash(a: dict):
    cmd = to_real_text(a.get('command') or '')
    if not cmd.strip():
        raise ToolError('command is required')
    if DENY_CMD.search(cmd):
        raise ToolError('publishing (git push, PRs, releases) is not allowed from an anonymous session')
    if READ_ONLY and re.search(r'(^|[;&|]\s*)(rm|mv|cp|tee|sed\s+-i|git\s+(commit|reset|checkout|merge|rebase))\b|>', cmd):
        raise ToolError('this session is read-only')
    timeout = min(max(int(a.get('timeout') or 120_000) // 1000, 1), 600)
    code, out = _run(cmd, ROOT, timeout, shell=True)
    out = _cap(out.rstrip()) or '(no output)'
    return to_ai(out + (f'\n(exit code {code})' if code else ''))


S = {'type': 'string'}
TOOLS = [
    {'name': 'read', 'fn': t_read, 'ro': True,
     'description': f'Read a file of the project ({VROOT}/...) with line numbers. offset/limit for large files. '
                    'Also opens pasted images.',
     'inputSchema': {'type': 'object', 'required': ['file_path'], 'properties': {
         'file_path': S, 'offset': {'type': 'integer'}, 'limit': {'type': 'integer'}}}},
    {'name': 'glob', 'fn': t_glob, 'ro': True,
     'description': f'Find files by pattern (e.g. "**/*.tf"), newest first. path defaults to {VROOT}.',
     'inputSchema': {'type': 'object', 'required': ['pattern'], 'properties': {'pattern': S, 'path': S}}},
    {'name': 'grep', 'fn': t_grep, 'ro': True,
     'description': 'Search file contents with a regex (ripgrep). output_mode: files_with_matches (default), '
                    'content (with line numbers) or count. glob filters files, -i ignores case.',
     'inputSchema': {'type': 'object', 'required': ['pattern'], 'properties': {
         'pattern': S, 'path': S, 'glob': S, 'output_mode': {'type': 'string', 'enum': ['files_with_matches', 'content', 'count']},
         '-i': {'type': 'boolean'}, 'context': {'type': 'integer'}, 'head_limit': {'type': 'integer'}}}},
    {'name': 'edit', 'fn': t_edit, 'ro': False,
     'description': 'Replace old_string with new_string in a file. old_string must match exactly what read showed '
                    '(without the line numbers) and be unique, or use replace_all.',
     'inputSchema': {'type': 'object', 'required': ['file_path', 'old_string', 'new_string'], 'properties': {
         'file_path': S, 'old_string': S, 'new_string': S, 'replace_all': {'type': 'boolean'}}}},
    {'name': 'write', 'fn': t_write, 'ro': False,
     'description': 'Create or overwrite a file with content. Prefer edit for changes to existing files.',
     'inputSchema': {'type': 'object', 'required': ['file_path', 'content'], 'properties': {'file_path': S, 'content': S}}},
    {'name': 'bash', 'fn': t_bash, 'ro': False,
     'description': f'Run a bash command in {VROOT} (each call starts there: use "cd dir && ..."). '
                    'Output is limited; timeout in ms (default 120000, max 600000). No interactive commands.',
     'inputSchema': {'type': 'object', 'required': ['command'], 'properties': {
         'command': S, 'description': S, 'timeout': {'type': 'integer'}}}},
]
BY_NAME = {t['name']: t for t in TOOLS}
INSTRUCTIONS = (
    f'The project lives at {VROOT}. Use these tools for every file and shell operation. Names, ids, '
    'IPs and secrets you see are consistent pseudonyms: write them exactly as they appear, the tools '
    'translate them to the real values and back.')


# ------------------------------------------------------------------ protocol

def handle(msg: dict) -> dict | None:
    mid, method, params = msg.get('id'), msg.get('method'), msg.get('params') or {}
    if mid is None:          # notifications (initialized, cancelled...)
        return None
    if method == 'initialize':
        res = {'protocolVersion': params.get('protocolVersion') or '2025-06-18',
               'capabilities': {'tools': {}},
               'serverInfo': {'name': 'gatito-anon', 'version': '1.0'},
               'instructions': INSTRUCTIONS}
    elif method == 'ping':
        res = {}
    elif method == 'tools/list':
        res = {'tools': [{k: t[k] for k in ('name', 'description', 'inputSchema')}
                         | {'annotations': {'readOnlyHint': t['ro']}}
                         for t in TOOLS if t['ro'] or not READ_ONLY]}
    elif method == 'tools/call':
        t = BY_NAME.get(params.get('name'))
        if not t:
            return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32602, 'message': 'unknown tool'}}
        try:
            out = t['fn'](params.get('arguments') or {})
            content = out if isinstance(out, list) else [{'type': 'text', 'text': out}]
            res = {'content': content}
        except ToolError as e:
            res = {'content': [{'type': 'text', 'text': str(e)}], 'isError': True}
        except Exception as e:   # never the real values in an error either
            res = {'content': [{'type': 'text', 'text': to_ai(f'{type(e).__name__}: {e}')}], 'isError': True}
    else:
        return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': f'method not found: {method}'}}
    return {'jsonrpc': '2.0', 'id': mid, 'result': res}


def main():
    global ROOT, READ_ONLY
    args = sys.argv[1:]
    if '--root' in args:
        ROOT = Path(os.path.normpath(Path(args[args.index('--root') + 1]).expanduser()))
    EXTRA.extend(Path(args[i + 1]) for i, x in enumerate(args) if x == '--extra' and i + 1 < len(args))
    READ_ONLY = '--read-only' in args
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        for m in (msg if isinstance(msg, list) else [msg]):
            out = handle(m)
            if out is not None:
                sys.stdout.write(json.dumps(out, ensure_ascii=False) + '\n')
                sys.stdout.flush()


if __name__ == '__main__':
    main()

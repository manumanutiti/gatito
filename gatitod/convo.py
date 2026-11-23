#!/usr/bin/python3
"""Reads the agents' conversations (.jsonl) and summarizes them with Haiku.

The summary is incremental and cheap: Haiku is only given what is new since the
last time, and it is stored in ~/gatito/state/summaries/<sid>.json.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from core import HOME, STATE, CLAUDE

SUMM = STATE / 'summaries'
IMG_EXT = ('.svg', '.png', '.jpg', '.jpeg', '.gif', '.webp')
SUMM.mkdir(parents=True, exist_ok=True)

_SYS = ('You are the assistant of an agent coordinator. In 2-4 clear sentences, '
        'summarize where a programming agent stands: what it was asked, what it '
        'has done and, if it is waiting, what it needs from the user. '
        'Write the summary in the language the user writes in. '
        'No fluff and no markdown.')


def _tool_what(i) -> str:
    """A readable line of what a tool does: the command, the file, the search..."""
    if not isinstance(i, dict):
        return ''
    for k in ('description', 'command', 'file_path', 'notebook_path', 'url', 'pattern', 'query',
              'prompt', 'path', 'skill'):
        if isinstance(i.get(k), str) and i[k].strip():
            v = i[k].strip()
            # for Bash, show the description and also the command
            if k == 'description' and isinstance(i.get('command'), str):
                v = f"{v} · {i['command'].strip()}"
            return v.replace('\n', ' ')[:240]
    return ''


def read_messages(transcript: str, limit: int | None = None) -> list[dict]:
    """Return the conversation in chat format: role, kind, text."""
    msgs, asked = [], set()
    try:
        lines = Path(transcript).read_text(errors='ignore').splitlines()
    except OSError:
        return msgs
    for line in lines:
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get('type') not in ('user', 'assistant') or d.get('isMeta'):
            continue
        content = d['message']['content']
        role = d['type']
        # your answer to a question with options: it goes in the chat, not hidden as a tool
        tur = d.get('toolUseResult')
        if isinstance(tur, dict) and isinstance(tur.get('answers'), dict) and tur['answers']:
            msgs.append({'role': 'user', 'kind': 'answer', 'answers': tur['answers'],
                         'text': '\n'.join(f'{q} → {a}' for q, a in tur['answers'].items())})
            asked.update(b.get('tool_use_id') for b in content if isinstance(b, dict))
            continue
        if isinstance(content, str):
            if content.strip():
                msgs.append({'role': role, 'kind': 'text', 'text': content})
            continue
        for b in content:
            t = b.get('type')
            if t == 'text' and b.get('text', '').strip():
                msgs.append({'role': role, 'kind': 'text', 'text': b['text']})
            elif t == 'thinking' and b.get('thinking', '').strip():
                msgs.append({'role': role, 'kind': 'thinking', 'text': b['thinking']})
            elif t == 'tool_use' and b.get('name') == 'AskUserQuestion':
                qs = (b.get('input') or {}).get('questions') or []
                msgs.append({'role': role, 'kind': 'ask', 'id': b.get('id'), 'tool': b.get('name'),
                             'what': '; '.join(q.get('question', '') for q in qs),
                             'questions': [{'question': q.get('question', ''), 'header': q.get('header'),
                                            'options': [o.get('label', '') for o in q.get('options') or []]}
                                           for q in qs],
                             'text': '\n'.join(q.get('question', '') for q in qs)})
            elif t == 'tool_use':
                msgs.append({'role': role, 'kind': 'tool', 'tool': b.get('name'),
                             'what': _tool_what(b.get('input')),
                             'text': f"{b.get('name')} {json.dumps(b.get('input', {}), ensure_ascii=False)[:200]}"})
                fp = (b.get('input') or {}).get('file_path', '')
                if b.get('name') == 'Write' and fp.lower().endswith(IMG_EXT):
                    msgs.append({'role': role, 'kind': 'image', 'text': fp})
            elif t == 'tool_result':
                c = b.get('content')
                txt = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)[:300]
                msgs.append({'role': 'tool', 'kind': 'result', 'text': txt[:300]})
    # an unanswered (or cancelled) question is just another tool:
    # if it is pending, the card below already shows it with its buttons
    for m in msgs:
        if m['kind'] == 'ask' and m.pop('id', None) not in asked:
            m['kind'] = 'tool'
    return msgs[-limit:] if limit else msgs


def _plain(msgs: list[dict]) -> str:
    out = []
    for m in msgs:
        if m['kind'] in ('text',):
            who = 'USER' if m['role'] == 'user' else 'AGENT'
            out.append(f"{who}: {m['text']}")
        elif m['kind'] == 'tool':
            out.append(f"[uses {m['text']}]")
        elif m['kind'] == 'ask':
            out.append(f"AGENT (question): {m['text']}")
        elif m['kind'] == 'answer':
            out.append(f"USER (answers): {m['text']}")
    return '\n'.join(out)


def summarize(transcript: str, session_id: str, cached_only: bool = False) -> dict:
    """Incremental summary. Returns {summary, msg_count, cached}.

    With `cached_only` it does not call Haiku: it returns the last saved summary (or
    summary None) and `stale` if the conversation has continued since then.
    """
    cache = SUMM / f'{session_id}.json'
    prev = {}
    try:
        prev = json.loads(cache.read_text())
    except (OSError, json.JSONDecodeError):
        pass

    msgs = [m for m in read_messages(transcript) if m['kind'] in ('text', 'tool', 'ask', 'answer')]
    n = len(msgs)
    if cached_only:
        return {'summary': prev.get('summary'), 'msg_count': prev.get('msg_count', 0),
                'cached': True, 'stale': bool(prev.get('summary')) and prev.get('msg_count') != n}
    if prev.get('msg_count') == n and prev.get('summary'):
        return {**prev, 'cached': True}

    new = msgs[prev.get('msg_count', 0):]
    if not new and prev.get('summary'):
        return {**prev, 'cached': True}

    prompt = ''
    if prev.get('summary'):
        prompt += f"Summary so far:\n{prev['summary']}\n\nWhat is new since then:\n"
    prompt += _plain(new or msgs)[-8000:]

    r = subprocess.run(
        [CLAUDE, '-p', '--model', 'haiku', '--no-session-persistence',
         '--tools', '', '--setting-sources', '', '--strict-mcp-config',
         '--disable-slash-commands', '--system-prompt', _SYS, prompt],
        capture_output=True, text=True, timeout=90)
    summary = r.stdout.strip() or prev.get('summary', '(no summary)')
    res = {'summary': summary, 'msg_count': n, 'cached': False}
    cache.write_text(json.dumps(res, ensure_ascii=False))
    return res

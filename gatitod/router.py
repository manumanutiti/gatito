#!/usr/bin/python3
"""Router: understands what you type and decides what to do with Haiku.

Returns one of three intents:
  - action:   run something on the system (pin the screen, etc.)
  - question: a quick question -> text answer
  - task:     launch an agent on a project
If it is not sure about the project, it leaves it null and the UI asks.

For tasks it also understands when ("tomorrow at 9", "every day at 8",
"put it in the queue", "leave it for later"; the user may write in Spanish or English)
and returns it as `when`/`at_ms`/`repeat`, ready for the backlog.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timedelta

from pathlib import Path

import notebooks
from core import load_projects, load_actions, CLAUDE, UPLOADS, NB_PREFIX

_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["action", "question", "task"]},
        "action_id": {"type": ["string", "null"]},
        "project_id": {"type": ["string", "null"]},
        "task": {"type": ["string", "null"]},
        "model": {"type": "string", "enum": ["fable", "opus", "sonnet", "haiku"]},
        "answer": {"type": ["string", "null"]},
        "when": {"type": "string", "enum": ["now", "queue", "at", "manual"]},
        "at": {"type": ["string", "null"]},
        "repeat": {"type": ["string", "null"], "enum": ["daily", "weekdays", "weekly", None]},
        "worktree": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["high", "low"]},
    },
    "required": ["intent", "confidence"],
})


_DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
_MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
          'September', 'October', 'November', 'December']


def _now() -> str:
    n = datetime.now()
    return (f"{_DAYS[n.weekday()]} {n.day} {_MONTHS[n.month - 1]} {n.year}, "
            f"{n:%H:%M} (local time; ISO {n:%Y-%m-%dT%H:%M})")


def _sys(project_id: str | None = None) -> str:
    projs = '\n'.join(f"- {p['id']}: {p['desc'][:90]}" + (
        f" (alias: {', '.join(p['aliases'])})" if p.get('aliases') else '')
        for p in load_projects())
    # notebooks are also a destination: notes, state and repos of a long-running piece of work
    projs += ''.join(f"\n- {NB_PREFIX}{c['id']}: notebook '{c['title']}' ({c['summary'][:80]}); "
                     "to resume, note down, document or explain something about that topic"
                     for c in notebooks.list_all()[:15])   # the most recent ones: the prompt does not grow without bound
    acts ='\n'.join(f"- {a['id']}: {a['label']} ({', '.join(a.get('keywords', []))})"
                     for a in load_actions())
    return f"""You are the router of a coordinator of programming agents. The user writes in Spanish or English (or any other language); understand any of them.
Classify their message into an intent and return JSON.

intent=action: they ask for a system setting. Set action_id from the list.
ACTIONS:
{acts}

intent=task: they ask for work on code in a project. Pick project_id from the list and
rewrite the task clearly in `task`, in the same language the user wrote it. Pick model: sonnet by default, opus if
they ask for something hard, fable if it is very complex or long, haiku if it is trivial. If they name a
model explicitly, use that one. If you are not sure about the
project, leave project_id null and confidence=low.
If the work does not belong to any project in the list (researching, comparing, writing,
a loose script, trying something out, an open question that needs searching, reading or running
things), set project_id=free: it is launched without a project, in a new folder.
Set worktree=true only if they ask to work isolated, in a worktree or on a separate branch.

WHEN (only for task), in `when`:
- now: the default, if they say nothing about when.
- at: if they give a date or time ("tomorrow at 9", "on Monday", "tonight", "in 2 hours";
  Spanish: "mañana a las 9", "el lunes", "esta noche", "en 2 horas").
  Put `at` in local ISO "YYYY-MM-DDTHH:MM", always in the future relative to now.
  Without a specific time: "tomorrow"/"on Monday" (mañana/el lunes) -> 09:00; "this afternoon" (esta tarde) -> 17:00; "tonight" (esta noche) -> 22:00.
  If they say "every day", "daily" (cada día, todos los días) -> repeat=daily; "on weekdays", "Monday to Friday"
  (entre semana, de lunes a viernes) -> weekdays; "every Monday", "every week" (cada lunes, todas las semanas) -> weekly. Otherwise repeat=null.
- queue: if they say "to the queue", "when there is room", "after what is running" (a la cola, cuando haya hueco, después de lo que está corriendo).
- manual: if they say "save it", "note it down", "for later" or "I'll tell you when" (guárdalo, apúntalo, para más tarde, ya te diré cuándo).
Remove the words about when from `task`; leave only the work.
NOW IT IS: {_now()}
PROJECTS:
{projs}

intent=question: a question you can answer yourself in a few sentences, without touching
files or launching agents. Put the answer in `answer`, in the language the user wrote.
If the question is about IT and is better understood with a diagram, include in `answer` a
diagram in a ```mermaid block (flowchart LR or sequenceDiagram, short labels;
quotes only on flowchart nodes, never in sequenceDiagram). The interface draws it.

confidence=low if you doubt the intent or the project; high if it is clear.""" + (
        f"\n\nThe user has already chosen the project \"{project_id}\": intent=task and "
        f"project_id={project_id}; only interpret the task and the when." if project_id else '')


def _iso(s: str) -> datetime:
    """Python 3.9 fromisoformat: no "Z" and with 0, 3 or 6 decimals in the seconds."""
    s = s.strip()
    if s.endswith(('Z', 'z')):
        s = s[:-1] + '+00:00'
    m = re.match(r'^(.*T\d\d:\d\d:\d\d)\.(\d+)(.*)$', s)
    if m:
        s = f'{m[1]}.{(m[2] + "000000")[:6]}{m[3]}'
    return datetime.fromisoformat(s)


def _when(out: dict) -> dict:
    """Convert `at` to epoch ms and validate it; if it is not understood, the task waits (manual)."""
    w = out.get('when') or 'now'
    if w != 'at':
        out.update(at_ms=None, repeat=None)
        return out
    try:
        dt = _iso(out.get('at') or '')
    except ValueError:
        out.update(when='manual', at_ms=None, repeat=None, confidence='low')
        return out
    if dt.tzinfo:
        dt = dt.astimezone().replace(tzinfo=None)
    now = datetime.now()
    # "at 9" said at 10 means tomorrow at 9
    if dt <= now and now - dt < timedelta(days=1):
        dt += timedelta(days=1)
    if dt <= now:
        out.update(when='manual', at_ms=None, repeat=None, confidence='low')
        return out
    out['at_ms'] = int(dt.timestamp() * 1000)
    return out


def route(text: str, project_id: str | None = None, images: list[str] | None = None) -> dict:
    # with images: it may open them (Read only, only in state/uploads) and uses Sonnet to see them
    images = [i for i in images or [] if Path(i).resolve().parent == UPLOADS]
    tools = ['--tools', 'Read', '--allowedTools', 'Read', '--add-dir', str(UPLOADS)] if images else ['--tools', '']
    if images:
        text += ('\n\nAttached images (open them with Read before deciding; if it is a question, '
                 'answer it by looking at them):\n' + '\n'.join(images))
    r = subprocess.run(
        [CLAUDE, '-p', '--model', 'sonnet' if images else 'haiku', '--no-session-persistence',
         *tools, '--setting-sources', '', '--strict-mcp-config',
         '--disable-slash-commands', '--system-prompt', _sys(project_id),
         '--output-format', 'json', '--json-schema', _SCHEMA, '--', text],
        capture_output=True, text=True, timeout=120 if images else 60)
    try:
        d = json.loads(r.stdout)
        out = d.get('structured_output') or json.loads(d['result'])
        out['_cost'] = d.get('total_cost_usd')
        if project_id:  # you chose the project: it overrides the router
            out.update(intent='task', project_id=project_id, confidence='high')
        return _when(out) if out.get('intent') == 'task' else out
    except (json.JSONDecodeError, KeyError, TypeError):
        return {'intent': 'question', 'answer': "(I didn't understand you, try again)",
                'confidence': 'low', '_error': r.stderr.strip()[:200]}

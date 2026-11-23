#!/usr/bin/python3
"""Core of the gatito coordinator.

No external libraries: only the stdlib and the `claude` binary.
Exposes functions reused by the web UI (gatitod/web.py) and the GNOME menu.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import notebooks
import debug
import modlink
import profiles
import hostinfo
import store

HOME = Path.home()
ROOT = hostinfo.ROOT
# GATITO_STATE: another state directory (tests, a test server)
STATE = Path(os.environ.get('GATITO_STATE') or ROOT / 'state')
JOBS = hostinfo.CLAUDE_DIR / 'jobs'
PROJECTS_DIR = hostinfo.CLAUDE_DIR / 'projects'
# claude and its agents inherit this PATH (under launchd it arrives almost empty): one place only
os.environ['PATH'] = hostinfo.agents_path()
CLAUDE = hostinfo.claude_bin()

STATE.mkdir(parents=True, exist_ok=True)
hostinfo.private(STATE, folder=True)   # token, keys and the mod socket
DIAGRAMS = STATE / 'diagrams'
DIAGRAMS.mkdir(exist_ok=True)
# the agents' tools: the ones from this copy of gatito (ROOT comes from __file__)
BIN_DIAGRAM = ROOT / 'bin' / 'diagram'   # infra diagrams with official icons
BIN_ARTIFACT = ROOT / 'bin' / 'artifact'  # save pages and reports
BIN_WHITEBOARD = ROOT / 'bin' / 'whiteboard'      # debugging whiteboard (debug.py)
ARTIFACTS = STATE / 'artifacts'                      # what has been saved (Artifacts view)
ARTIFACTS.mkdir(exist_ok=True)
UPLOADS = STATE / 'uploads'   # images you paste in the web UI so the agent can see them
UPLOADS.mkdir(exist_ok=True)
NOTEBOOKS = notebooks.BASE    # notebooks: persistent notes for projects and topics (Notebooks view)
NOTEBOOKS.mkdir(exist_ok=True)
BIN_NOTEBOOK = ROOT / 'bin' / 'notebook'
NB_PREFIX = 'nb:'             # in the project selector, a notebook is "nb:<id>"
# where the questions answered by the router continue: outside state/ (the token lives there)
CHATS = hostinfo.DATA / 'chats'
CHATS.mkdir(parents=True, exist_ok=True)
# "no project": each task works in its own new folder inside CHATS
FREE_ID = 'free'

# Appended to the system prompt of the agents gatito launches. The web UI renders the
# mermaid blocks and images they write, so they show up in the chat.
DIAGRAM_PROMPT = (
    'The user follows this conversation in a web interface that draws diagrams. '
    'When you explain architecture, networking, flows, infrastructure, security or any '
    'other IT concept that is easier to understand visually, accompany the explanation '
    'with a diagram in a ```mermaid block (flowchart, sequenceDiagram, etc.; short '
    'labels; in flowchart put node labels containing symbols in quotes, in '
    'sequenceDiagram do not use quotes). For serious infrastructure architecture '
    '(AWS, Azure, GCP, Kubernetes, on-prem networks, CI/CD) use the "diagram" skill: '
    f'official icons with `{BIN_DIAGRAM}` (look up icons with `icons`, draw with '
    '`draw`; each diagram is saved as an artifact). If mermaid falls short '
    f'for something else, write an SVG with the Write tool into {DIAGRAMS}/ and it will be shown '
    'in the chat. When what you deliver is meant to be kept or shared (an interactive '
    'HTML page, a report, a comparison, a runbook), save it as an artifact with '
    f'the "artifact" skill (`{BIN_ARTIFACT} save`): it shows in the chat and in gatito\'s '
    'Artifacts view. '
    'Do not add diagrams to trivial changes; use them when they help understanding. '
    f'If the user\'s message includes images (paths in {UPLOADS}/), open them with the '
    'Read tool before answering: they are screenshots or photos the user pasted. '
    f'gatito\'s notebooks ({NOTEBOOKS}/) hold the state of long-running work '
    '(notes, explanations, decisions, flows and diagrams in Markdown with metadata): if '
    'the user asks to note down or save something in a notebook, use the "notebook" skill.')


def notebook_prompt(nb: str) -> str:
    """What gets added to an agent that works inside a notebook."""
    d = NOTEBOOKS / nb
    cover = notebooks.info(d / notebooks.COVER) if (d / notebooks.COVER).is_file() else {}
    title = cover.get('title') or nb
    repos = notebooks.repos(nb)
    return (
        f'You are working inside the gatito notebook "{title}" ({d}). The notebook is the '
        'persistent state of this work: Markdown notes with metadata (YAML frontmatter) that '
        'the user reads in gatito\'s Notebooks view and in Obsidian. Before answering, run '
        f'`{BIN_NOTEBOOK} context {nb}` (or `... context {nb} <folder>` if the work belongs to a '
        'folder): it gives the cover, the state and the note index with their summaries, at a '
        'bounded size, so you do not start from scratch. Take care of the context: do not read the whole notebook or '
        'notes "just in case"; open only the ones you need (if they are large, just the relevant section, '
        f'with offset/limit) and use `{BIN_NOTEBOOK} search` before reading blindly. Never read the '
        '.svg, .png or .html files in diagrams/: they weigh tens of thousands of tokens; their source is the .py. '
        'Follow the "notebook" skill: '
        f'create notes with `{BIN_NOTEBOOK} note ...` (correct metadata from the start), '
        'put infra diagrams in the note\'s `diagrams/` folder with '
        f'`{BIN_DIAGRAM} draw x.py --png --output <folder>/diagrams` and link them with a '
        'relative path. When you finish something worth keeping, update status.md (what is clear, '
        'decisions, open questions, next steps) and the notes that change: summarize, do not copy '
        'the conversation. Write notes in the language of the notebook they go into. '
        + (f'Repos of this notebook (you have access): {", ".join(repos)}.' if repos else ''))

# Agents run in auto mode: nothing gets published without permission. The prompt rule
# is the first barrier; the denied tools are the one that cannot be bypassed.
SAFETY_PROMPT = (
    'Never publish anything outside this machine unless the user explicitly asks for it '
    'in this turn: no git push, no PRs, no releases, no deployments. '
    'Make local commits if needed and let the user decide whether anything gets pushed. '
    'Reply in the language the user writes in.')
DENY_TOOLS = [
    'Bash(git push:*)', 'Bash(git -C * push*)',
    'Bash(gh pr create:*)', 'Bash(gh pr merge:*)', 'Bash(gh release:*)',
    'Bash(gh repo create:*)',
    # diagram SVGs embed the icons in base64 (50-300 KB): reading them eats the
    # context and is useless (the source is the .py). They are viewed in the web UI, not by the agent.
    f'Read(/{NOTEBOOKS}/**/*.svg)', f'Read(/{ARTIFACTS}/**/*.svg)', f'Read(/{DIAGRAMS}/**/*.svg)',
]


# What the web UI lets you choose. The aliases always point to the latest model of each
# family; a full id (claude-...) is also accepted.
MODELS = [
    {'id': 'fable', 'label': 'Fable', 'hint': 'the most capable, for the hardest work'},
    {'id': 'opus', 'label': 'Opus', 'hint': 'hard tasks'},
    {'id': 'sonnet', 'label': 'Sonnet', 'hint': 'balanced (default)'},
    {'id': 'haiku', 'label': 'Haiku', 'hint': 'fast and cheap, trivial things'},
]
# bypassPermissions is not offered: in the background and from a phone it is too much.
MODES = [
    {'id': 'auto', 'label': 'Auto', 'hint': 'decides on its own and asks about risky things'},
    {'id': 'manual', 'label': 'Manual', 'hint': 'asks permission for every action'},
    {'id': 'acceptEdits', 'label': 'Accept edits', 'hint': 'edits files without asking'},
    {'id': 'plan', 'label': 'Plan', 'hint': 'only investigates and proposes a plan'},
    {'id': 'dontAsk', 'label': 'Don\'t ask', 'hint': 'denies whatever is not allowed'},
]
EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max']
DEFAULT_MODEL = 'sonnet'
DEFAULT_MODE = 'auto'
MODE_IDS = {m['id'] for m in MODES}


def valid_model(m: str | None) -> str | None:
    """Known alias or full id; nothing that could sneak in as a flag."""
    import re
    m = (m or '').strip()
    if any(m == x['id'] for x in MODELS):
        return m
    return m if re.fullmatch(r'claude-[a-z0-9.\-]+(\[1m\])?', m) else None


def profile_contribution(profile: dict) -> dict:
    """What a profile adds to an agent (prompt, rules, mode): used by the flags and the web UI."""
    return profiles.contribution(profile, [str(DIAGRAMS), str(ARTIFACTS), str(NOTEBOOKS)], str(BIN_NOTEBOOK),
                           str(BIN_ARTIFACT), str(BIN_DIAGRAM), str(BIN_WHITEBOARD))


# ------------------------------------------------------- anonymous sessions
# With "Anonymize" on, a task does not run in the project folder with the built-in tools:
# it runs in an empty folder and works on the project through gatitod/maskmcp.py, which
# masks what the agent reads and puts the real values back in what it writes and runs.
# So neither the files nor the git status, CLAUDE.md or path of the project reach the AI.
MASK_MCP = ROOT / 'gatitod' / 'maskmcp.py'
ANON_SESSIONS = STATE / 'anon-sessions.json'   # session -> {'root': real project folder}
ANON_MCP = 'gatito-anon'
# built-in tools left: none touches files or the shell
ANON_BUILTINS = 'AskUserQuestion,WebSearch,WebFetch,TaskCreate,TaskUpdate,TaskList,TaskGet'
ANON_PROMPT = (
    'This is an anonymized session. The project is at /workspace and you work on it only with '
    f'the {ANON_MCP} tools (read, glob, grep, edit, write, bash): there are no other file or shell tools. '
    'Many names, ids, IPs, e-mails and secrets are consistent pseudonyms (tenant-alpha, rg-bravo, '
    '00000000-0000-4000-a000-…, masked-secret-3…). Treat them as the real values, write them exactly as '
    'they appear (same case) in code, commands and answers, and never ask for or guess the real ones: '
    'the tools translate them. If the gatito-anon tools are not in your tool list yet, they are '
    'still starting: do not use any other tool to make up for them, just say in one line that '
    'they are starting and stop (the user will send the message again). '
    'The user follows this conversation in a web interface that draws diagrams: when a concept is easier '
    'to understand visually, add a ```mermaid block (short labels; in flowchart put node labels with '
    'symbols in quotes, in sequenceDiagram do not use quotes).')


# In a session (not with -p), MCP servers connect in parallel with the first turn: without
# this the first message can arrive before the anonymized tools. Not a documented variable
# of Claude Code: if it stops working, the prompt above tells the agent to stop and wait.
ANON_ENV = {**os.environ, 'CLAUDE_CODE_MCP_PREWAIT_SERVERS': ANON_MCP}


def anon_for(*keys: str | None) -> dict | None:
    m = store.read(ANON_SESSIONS, {}) or {}
    return next((m[k] for k in keys if k and isinstance(m.get(k), dict)), None)


def remember_anon(info: dict | None, *keys: str | None):
    if info and any(keys):
        with store.edit(ANON_SESSIONS, {}) as m:
            for k in keys:
                if k:
                    m[k] = info


def _anon_flags(root: str, read_only: bool) -> list[str]:
    srv = {'command': sys.executable, 'args': [str(MASK_MCP), '--root', root, '--extra', str(UPLOADS),
                                               *(['--read-only'] if read_only else [])],
           'env': {'GATITO_STATE': str(STATE), 'GATITO_ROOT': str(ROOT)}}
    ro = [f'mcp__{ANON_MCP}__{t}' for t in ('read', 'glob', 'grep')]
    rw = [f'mcp__{ANON_MCP}__{t}' for t in ('edit', 'write', 'bash')]
    return ['--tools', ANON_BUILTINS, '--strict-mcp-config',
            '--mcp-config', json.dumps({'mcpServers': {ANON_MCP: srv}}),
            '--allowedTools', *ro, *(['--disallowedTools', *rw] if read_only else [])]


def _agent_flags(mode: str | None = None, effort: str | None = None,
                 cwd: str | None = None, profile: dict | None = None,
                 anon_root: str | None = None) -> list[str]:
    """Flags common to launching and resuming (resuming does not reliably inherit).
    Inside a notebook, also its prompt and access to its repos. With a profile
    (profiles.py), its prompt, its rules and its mode; DENY_TOOLS and SAFETY_PROMPT are
    always included, and in a read-only profile the mode is dontAsk whatever you choose.
    With `anon_root`, an anonymous session on that folder (see ANON_PROMPT)."""
    ap = profile_contribution(profile) if profile else None
    if ap and ap['read_only']:
        mode = 'dontAsk'
    elif mode not in MODE_IDS:
        mode = (ap and ap['mode']) or DEFAULT_MODE
    if mode not in MODE_IDS:   # never bypassPermissions, wherever it comes from
        mode = DEFAULT_MODE
    flags = ['--permission-mode', mode]
    if effort not in EFFORTS:
        effort = profile and profile.get('effort')
    if effort in EFFORTS:
        flags += ['--effort', effort]
    if anon_root:
        # the profile's rules talk about the built-in tools: here only its prompt and read-only apply
        prompt = f'{ANON_PROMPT}\n\n{SAFETY_PROMPT}' + (f"\n\n{ap['prompt']}" if ap else '')
        return flags + ['--append-system-prompt', prompt,
                        *_anon_flags(anon_root, bool(ap and ap['read_only']))]
    prompt, dirs = f'{DIAGRAM_PROMPT}\n\n{SAFETY_PROMPT}', [str(DIAGRAMS), str(UPLOADS), str(ARTIFACTS), str(NOTEBOOKS)]
    nb = notebooks.of_relpath(cwd)
    if nb:
        prompt += '\n\n' + notebook_prompt(nb)
        dirs += notebooks.repos(nb)
        # also via flag, in case Claude does not read the notebooks/ settings from the
        # notebook folder: without this, the background session could not write notes
        flags += ['--settings', json.dumps(notebooks.CLAUDE_SETTINGS)]
    if ap:
        prompt += '\n\n' + ap['prompt']
    # the profile rules arrive already validated (they start with a letter: they cannot pass as a
    # flag); they are filtered again here, which is where they end up on the command line
    allow = [r for r in (ap['allow'] if ap else []) if profiles.is_rule(r)]
    deny = DENY_TOOLS + [r for r in (ap['deny'] if ap else []) if profiles.is_rule(r)]
    flags += ['--append-system-prompt', prompt, '--add-dir', *dirs]
    if allow:
        flags += ['--allowedTools', *allow]
    return flags + ['--disallowedTools', *deny]


# ------------------------------------------------------- profile of each session
# Resuming or replying passes the flags again: we need to know which profile the session was
# born with, or a read-only one would stop being read-only when answered. It is recorded by the
# job's short id (the one `claude --bg` prints) and by the sessionId as soon as it is known: when
# resuming with flags Claude opens another job, and from History only the sessionId is available.
PROFILE_SESSIONS = STATE / 'profiles-session.json'


def profile_for(*keys: str | None) -> dict | None:
    """{'profile', 'title', 'read_only'} of the session, by any of its ids."""
    m = store.read(PROFILE_SESSIONS, {}) or {}
    return next((m[k] for k in keys if k and isinstance(m.get(k), dict)), None)


def remember_profile(info: dict | None, *keys: str | None):
    if info and any(keys):
        with store.edit(PROFILE_SESSIONS, {}) as m:
            for k in keys:
                if k:
                    m[k] = info


def profile_info(p: dict) -> dict:
    return {'profile': p['id'], 'title': p['title'], 'read_only': p['read_only']}


def live_profile(info: dict | None) -> dict | None:
    """The profile applied on resume. If its file is gone (or stopped being read-only)
    and the session was born read-only, it stays read-only without its text:
    losing or editing the file must never free the hands of an agent that is already running."""
    if not info:
        return None
    p = profiles.get(info.get('profile'))
    if info.get('read_only') and not (p and p['read_only']):
        return profiles.read_only_minimal(info.get('profile'), info.get('title'))
    return p


# ---------------------------------------------------------------- utilities

_read_json = store.read

# Settings in ~/gatito/config.json; whatever is not there takes these values.
CONFIG_DEFAULTS = {
    'max_parallel': 2,   # agents working at once before the queue waits
    'perm_wait_min': 30,  # minutes the mod waits for your decision before leaving it to the terminal
    'notebooks_autosave_min': 10,  # local commit of notebooks/ every so many minutes if it changed (0: off)
}


def config() -> dict:
    return {**CONFIG_DEFAULTS, **(store.read(ROOT / 'config.json', {}) or {})}


def load_projects() -> list[dict]:
    return _read_json(ROOT / 'projects.json', []) or []


def get_project(pid: str) -> dict | None:
    if pid == FREE_ID:  # the folder is created on launch (path None)
        return {'id': FREE_ID, 'path': None, 'desc': 'no project, temporary folder', 'aliases': []}
    if pid.startswith(NB_PREFIX):  # a notebook: the agent works in its folder
        d = notebooks.notebook_dir(pid[len(NB_PREFIX):])
        return {'id': pid, 'path': str(d), 'desc': 'notebook', 'aliases': []} if d else None
    return next((p for p in load_projects() if p.get('id') == pid), None)


def remove_project(pid: str) -> dict:
    """Remove a project from projects.json by its id (does not touch the folder)."""
    f = ROOT / 'projects.json'
    projs = _read_json(f, []) or []
    kept = [p for p in projs if p.get('id') != pid]
    if len(kept) == len(projs):
        return {'ok': False, 'err': f'there is no project with id "{pid}"'}
    store.write(f, kept)
    return {'ok': True, 'id': pid}


def describe_project(p: Path) -> str:
    """First useful lines of README/CLAUDE.md, to fill in the description."""
    import re
    for name in ('README.md', 'readme.md', 'CLAUDE.md'):
        f = p / name
        if f.is_file():
            lines: list[str] = []
            for line in f.read_text(errors='ignore').splitlines():
                line = line.strip()
                if not line or line.startswith(('![', '<', '[!', '---')):
                    continue
                lines.append(re.sub(r'[#*`>]', '', line).strip())
                if len(' '.join(lines)) > 180:
                    break
            return ' '.join(lines)[:220]
    return ''


def add_project(raw_path: str) -> dict:
    """Add a folder to projects.json. Only inside your home and it must exist."""
    raw = (raw_path or '').strip()
    if not raw:
        return {'ok': False, 'err': 'provide a path'}
    try:
        p = Path(raw).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return {'ok': False, 'err': f'folder {raw} does not exist'}
    if not p.is_dir():
        return {'ok': False, 'err': f'{p} is not a folder'}
    if not p.is_relative_to(HOME) or p == HOME:
        return {'ok': False, 'err': 'must be a folder inside your home'}

    f = ROOT / 'projects.json'
    projs = _read_json(f, []) or []
    if any(Path(x['path']).resolve() == p for x in projs if x.get('path')):
        return {'ok': False, 'err': 'that project is already in the list'}
    ids = {x.get('id') for x in projs}
    pid = p.name.lower()
    if pid in ids:
        pid = f'{p.parent.name}-{p.name}'.lower()
    proj = {'id': pid, 'path': str(p), 'desc': describe_project(p), 'aliases': []}
    projs.append(proj)
    store.write(f, projs)
    return {'ok': True, 'project': proj}


def load_actions() -> list[dict]:
    """The ones in actions.json that apply on this system (`platforms` field)."""
    return hostinfo.actions(_read_json(ROOT / 'actions.json', []) or [])


# ------------------------------------------------------------------- agents

# A blocked session older than this no longer "waits" for you: it goes to the archive.
STALE_BLOCKED_H = 72
# Finished ones stay in "Recent" for this long and then go to the archive.
RECENT_DONE_H = 24
HIDDEN_FILE = STATE / 'hidden.json'

_cache = {'ts': 0.0, 'data': []}
_lock = threading.Lock()


def _hidden() -> set[str]:
    return set(_read_json(HIDDEN_FILE, []) or [])


def _save_hidden(h: set[str]):
    store.write(HIDDEN_FILE, sorted(h))


def _flag_of(job: dict, flag: str) -> str | None:
    """Value of a flag the session was (re)launched with."""
    flags = job.get('respawnFlags')
    if not isinstance(flags, list):
        return None
    try:
        return flags[flags.index(flag) + 1]
    except (ValueError, IndexError):
        return None


def _model_of(job: dict) -> str | None:
    """Current model of the session, as an alias if it belongs to a known family."""
    raw = _flag_of(job, '--model')
    if not raw:
        return None
    low = raw.lower()
    for m in MODELS:
        if m['id'] in low:
            return m['id']
    return raw


_branches: dict[str, str | None] = {}


def _branch_of(path: str | None) -> str | None:
    """Branch of a worktree (cached: it does not change while it exists)."""
    if not path:
        return None
    if path not in _branches:
        r = subprocess.run(['git', '-C', path, 'branch', '--show-current'],
                           capture_output=True, text=True, timeout=10)
        _branches[path] = r.stdout.strip() or None if r.returncode == 0 else None
    return _branches[path]


def _iso_ms(s: str | None) -> int | None:
    if not s:
        return None
    try:
        return int(datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp() * 1000)
    except ValueError:
        return None


def _group(a: dict, now_ms: int, hidden: set[str]) -> str:
    """Which UI section each session goes in."""
    if a['key'] in hidden:
        return 'archive'
    age_h = (now_ms - (a['updatedAt'] or now_ms)) / 3_600_000
    if a['ui'] == 'interactive':
        return 'terminal'
    if a['ui'] == 'blocked':
        return 'waiting' if age_h < STALE_BLOCKED_H else 'archive'
    if a['ui'] == 'done':
        return 'recent' if age_h < RECENT_DONE_H else 'archive'
    return 'working'


def list_agents(include_done: bool = True, max_age: float = 2.0) -> list[dict]:
    """Background agents and interactive sessions, with their job state.

    Cached for a few seconds: the web UI and the status loop ask for it at the same time.
    """
    with _lock:
        if time.time() - _cache['ts'] < max_age:
            return _cache['data']
        data = _list_agents(include_done)
        _cache.update(ts=time.time(), data=data)
        return data


def _list_agents(include_done: bool) -> list[dict]:
    cmd = [CLAUDE, 'agents', '--json'] + (['--all'] if include_done else [])
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
        agents = json.loads(out)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        agents = []

    now_ms = int(time.time() * 1000)
    hidden = _hidden()
    for a in agents:
        job = _read_json(JOBS / a['id'] / 'state.json', {}) if a.get('id') else {}
        a['key'] = a.get('id') or a.get('sessionId')
        a['model'] = _model_of(job)
        a['mode'] = _flag_of(job, '--permission-mode')
        a['effort'] = _flag_of(job, '--effort')
        pf = profile_for(a.get('id'), a.get('sessionId'))
        if pf and a.get('sessionId') and not profile_for(a['sessionId']):
            remember_profile(pf, a['sessionId'])   # to resume it later from History
        a['profile'] = pf and pf['profile']
        a['profileTitle'] = pf and pf['title']
        a['readOnly'] = bool(pf and pf['read_only'])
        a['needs'] = job.get('needs')
        a['detail'] = job.get('detail')
        a['suggestedReply'] = job.get('suggestedReply')
        a['intent'] = job.get('intent')
        a['tokens'] = job.get('tokens')
        # launched with --worktree: works in its own copy and branch, not in the project folder
        # (on resume the new job no longer records it: it is deduced from its folder)
        a['worktreePath'] = job.get('worktreePath') or (
            a.get('cwd') if '/.claude/worktrees/' in (a.get('cwd') or '') else None)
        a['worktreeBranch'] = job.get('worktreeBranch') or _branch_of(a['worktreePath'])
        an = anon_for(a.get('id'), a.get('sessionId'))
        if an and a.get('sessionId') and not anon_for(a['sessionId']):
            remember_anon(an, a['sessionId'])   # to resume it later from History
        a['anon'] = an and an['root']           # anonymous session: the project it works on
        if an and '/.claude/worktrees/' in an['root']:
            a['worktreeBranch'] = a['worktreeBranch'] or _branch_of(an['root'])
        a['result'] = (job.get('output') or {}).get('result') if isinstance(job.get('output'), dict) else None
        a['updatedAt'] = _iso_ms(job.get('updatedAt')) or a.get('startedAt')
        a['transcript'] = job.get('linkScanPath') or _transcript_path(a)
        if a['transcript'] and a.get('kind') == 'interactive':
            try:
                a['updatedAt'] = int(Path(a['transcript']).stat().st_mtime * 1000)
            except OSError:
                pass
        # normalized state for the UI
        st = a.get('state') or a.get('status')
        if st == 'blocked':
            a['ui'] = 'blocked'
        elif st in ('done', 'completed', 'failed', 'stopped'):
            a['ui'] = 'done'
        elif a.get('kind') == 'interactive':
            a['ui'] = 'interactive'
        else:
            a['ui'] = 'working'
        _merge_live(a)
        a['group'] = _group(a, now_ms, hidden)
    agents.sort(key=lambda x: -(x['updatedAt'] or 0))
    return agents


def _merge_live(a: dict):
    """What the gatito mod reports from inside the session, if it has one."""
    sid = a.get('sessionId')
    lv = modlink.live(sid)
    a['live'] = lv['state'] if lv else None   # working / idle; None without the mod
    p = modlink.pending_perm(sid)
    a['perm'] = p and {k: p.get(k) for k in ('id', 'kind', 'tool', 'input', 'suggestions', 'created', 'agent')}
    if p:
        a['ui'] = 'blocked'
        if p.get('kind') == 'ask':
            qs = (p.get('input') or {}).get('questions') or [{}]
            a['needs'] = 'Asks you: ' + ' · '.join(q.get('question', '') for q in qs)
        else:
            a['needs'] = f"Permission: {p['tool']} {perm_summary(p)}".strip()
        a['updatedAt'] = max(a.get('updatedAt') or 0, int(p['created'] * 1000))


def perm_summary(p: dict) -> str:
    """One line with what it asks for: the command, the file or the URL."""
    i = p.get('input') if isinstance(p.get('input'), dict) else {}
    for k in ('command', 'file_path', 'notebook_path', 'url', 'path', 'pattern', 'query'):
        if i.get(k):
            return str(i[k]).replace('\n', ' ')[:160]
    return ''


def invalidate():
    with _lock:
        _cache['ts'] = 0.0


def _transcript_path(agent: dict) -> str | None:
    sid = agent.get('sessionId')
    cwd = agent.get('cwd')
    if not sid or not cwd:
        return None
    p = hostinfo.transcript(sid, cwd)
    return str(p) if p else None


def blocked_count() -> int:
    """How many background agents are waiting for your reply (for the menu)."""
    return sum(1 for a in list_agents() if a['group'] == 'waiting')


def set_hidden(key: str, hide: bool) -> dict:
    h = _hidden()
    (h.add if hide else h.discard)(key)
    _save_hidden(h)
    invalidate()
    return {'ok': True}


def _daemon_up() -> bool:
    r = subprocess.run([CLAUDE, 'daemon', 'status'], capture_output=True, text=True, timeout=15)
    return 'control.sock: reachable' in r.stdout


def _bg_cmd(args: list[str]) -> subprocess.CompletedProcess:
    """Run `claude stop/rm`. Claude's background service only lives while
    someone is using it; if it is off, those commands fail. In that case we
    start it for a moment, retry and shut it down again."""
    r = subprocess.run([CLAUDE, *args], capture_output=True, text=True, timeout=30)
    if r.returncode == 0 or 'background service' not in (r.stdout + r.stderr):
        return r
    proc = subprocess.Popen([CLAUDE, 'daemon', 'run'], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        for _ in range(20):
            if _daemon_up():
                break
            time.sleep(0.5)
        return subprocess.run([CLAUDE, *args], capture_output=True, text=True, timeout=30)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def stop_agent(agent_id: str) -> dict:
    r = _bg_cmd(['stop', agent_id])
    invalidate()
    return {'ok': r.returncode == 0, 'err': (r.stderr or r.stdout).strip()}


def remove_agent(agent_id: str) -> dict:
    """Delete a background session (claude rm). Does not touch the .jsonl history."""
    r = _bg_cmd(['rm', agent_id])
    ok = r.returncode == 0
    if ok:
        h = _hidden()
        if agent_id in h:
            h.discard(agent_id)
            _save_hidden(h)
    invalidate()
    return {'ok': ok, 'out': r.stdout.strip(), 'err': (r.stderr or r.stdout).strip()}


def reply_agent(agent_id: str, session_id: str, text: str, model: str | None = None,
                mode: str | None = None, effort: str | None = None) -> dict:
    """Stop the agent (if needed) and resume it with your reply.

    Model, permission mode and effort apply from this turn on.
    If the session has the gatito mod and you change none of that, the message
    reaches it through the mailbox: without stopping it, as soon as it finishes what it is doing.
    """
    ag = next((a for a in list_agents() if a.get('sessionId') == session_id), None) \
        or next((a for a in list_agents() if agent_id and a.get('id') == agent_id), {})
    same = ((not model or model == ag.get('model')) and (not mode or mode == (ag.get('mode') or DEFAULT_MODE))
            and (effort or None) == (ag.get('effort') or None))
    # the mailbox only delivers when the session is free: one waiting for your reply
    # (a question with options, a plan to approve) is not, so those get resumed
    if same and ag.get('live') and ag.get('ui') != 'blocked':
        return modlink.send(session_id, text)
    if not agent_id:
        return {'ok': False, 'err': 'this session can only be answered through the mod, and it is not responding right now'}
    subprocess.run([CLAUDE, 'stop', agent_id], capture_output=True, text=True, timeout=20)
    # a background session keeps its options: resumed without flags it keeps the same id.
    # With any flag Claude opens a copy; that one keeps the name and the old one is archived,
    # so the list still shows a single thread (archive, don't delete: the worktree is shared).
    # It is resumed from its own folder (the worktree's if it has one), not from gatito's.
    res = resume_session(session_id, ag.get('worktreePath') or ag.get('cwd'), text, model, mode,
                         effort, ag.get('name'), keep=same, keys=(agent_id, ag.get('key')))
    if res['ok'] and res.get('id') and res['id'] != agent_id and ag.get('key'):
        set_hidden(ag['key'], True)
    return res


def attach_project(agent_id: str, session_id: str, project_id: str, text: str = '') -> dict:
    """A session without a project gains access to a project, without losing the conversation.

    The project folder is recorded in the local settings of the temporary folder
    (`permissions.additionalDirectories`): it applies to this resume and the following ones,
    also from the terminal. It is always resumed: settings are read at startup.
    """
    proj = get_project(project_id)
    if not proj or not proj['path']:
        return {'ok': False, 'err': f'there is no project with id "{project_id}"'}
    ag = next((a for a in list_agents() if a.get('sessionId') == session_id), None) \
        or next((a for a in list_agents() if agent_id and a.get('id') == agent_id), {})
    cwd = ag.get('cwd')
    if not is_scratch(cwd):
        return {'ok': False, 'err': 'only sessions without a project can open one'}
    if not agent_id:
        return {'ok': False, 'err': 'this session is in a terminal: add the folder there with /add-dir'}
    anon = anon_for(session_id, agent_id, ag.get('key'))
    if anon:
        # anonymous: /workspace now points to the project (its real path is not told to the AI)
        remember_anon({'root': proj['path']}, session_id, agent_id, ag.get('key'))
        msg = ('/workspace now points to the project you have to work on (it may have a CLAUDE.md: '
               'read it if it does). From here on, code work goes there.')
        subprocess.run([CLAUDE, 'stop', agent_id], capture_output=True, text=True, timeout=20)
        res = resume_session(session_id, cwd, msg + (f'\n\n{text.strip()}' if text.strip() else ''),
                             ag.get('model'), ag.get('mode'), ag.get('effort'), ag.get('name'),
                             keys=(agent_id, ag.get('key')))
        if res['ok'] and res.get('id') and res['id'] != agent_id and ag.get('key'):
            set_hidden(ag['key'], True)
        return res
    f = Path(cwd) / '.claude' / 'settings.local.json'
    f.parent.mkdir(exist_ok=True)
    cfg = _read_json(f, {}) or {}
    dirs = cfg.setdefault('permissions', {}).setdefault('additionalDirectories', [])
    if proj['path'] not in dirs:
        dirs.append(proj['path'])
    store.write(f, cfg)
    msg = (f'You now have access to the project "{proj["id"]}" at {proj["path"]}. Read its CLAUDE.md '
           f'(if it has one) and, from here on, code work goes in that folder.')
    subprocess.run([CLAUDE, 'stop', agent_id], capture_output=True, text=True, timeout=20)
    res = resume_session(session_id, cwd, msg + (f'\n\n{text.strip()}' if text.strip() else ''),
                         ag.get('model'), ag.get('mode'), ag.get('effort'), ag.get('name'),
                         keys=(agent_id, ag.get('key')))
    if res['ok'] and res.get('id') and res['id'] != agent_id and ag.get('key'):
        set_hidden(ag['key'], True)
    return res


def resume_session(session_id: str, cwd: str | None, text: str, model: str | None = None,
                   mode: str | None = None, effort: str | None = None, name: str | None = None,
                   keep: bool = False, keys: tuple = ()) -> dict:
    """Resume any conversation in the background (terminal ones too).

    With `keep` (a stopped background session, nothing changed) no flags are passed and
    Claude continues it with the same id and its saved options. Otherwise it continues
    in a new session. Returns the short id like launch_agent. Re-applies the
    profile the session was born with (`keys`: other ids it may have been recorded under).
    """
    cwd = cwd if cwd and Path(cwd).is_dir() else None
    info = profile_for(session_id, *keys)
    if info and info.get('profile') == 'debug' and not info.get('whiteboard'):
        # the new session keeps drawing on the same whiteboard (debug.root)
        info = {**info, 'whiteboard': debug.root(session_id, *keys) or session_id}
    anon = anon_for(session_id, *keys)
    if anon:
        keep = False   # the flags are what keeps the built-in tools out: always passed again
    cmd = [CLAUDE, '--bg', '--resume', session_id]
    if not keep:
        cmd += _agent_flags(mode, effort, cwd, live_profile(info), anon_root=anon and anon['root'])
        model = valid_model(model)
        if model:
            cmd += ['--model', model]
        if name:
            cmd += ['--name', name]
    # `--disallowedTools` is variadic: `--` keeps it from swallowing the message.
    cmd += ['--', text]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=cwd,
                       env=ANON_ENV if anon else None)
    invalidate()
    short = _short_id(r.stdout)
    if r.returncode == 0:
        remember_profile(info, short, session_id)
        remember_anon(anon, short, session_id)
    return {'ok': r.returncode == 0, 'id': short, 'out': r.stdout.strip(),
            'err': r.stderr.strip()}


def _short_id(out: str) -> str | None:
    """The short id (8 hex) that `claude --bg` prints."""
    return next((t for t in out.split() if len(t) == 8 and all(c in '0123456789abcdef' for c in t)), None)


def is_git_repo(path: str) -> bool:
    r = subprocess.run(['git', '-C', path, 'rev-parse', '--is-inside-work-tree'],
                       capture_output=True, text=True, timeout=10)
    return r.returncode == 0 and r.stdout.strip() == 'true'


def new_scratch(task: str) -> str:
    """New folder for a task without a project: CHATS/<date>-<first words>."""
    slug = re.sub(r'[^a-z0-9]+', '-', task.lower())[:30].strip('-') or 'task'
    p = CHATS / f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}"
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def is_scratch(path: str | None) -> bool:
    return bool(path) and Path(path).resolve().is_relative_to(CHATS)


def launch_agent(path: str | None, task: str, model: str | None = None,
                 name: str | None = None, mode: str | None = None,
                 effort: str | None = None, worktree: bool | None = None,
                 profile: str | None = None, anon: bool = False) -> dict:
    """Launch a worker in `path`. Returns the short id if all goes well.

    With `worktree`, the agent works in an isolated copy of the repo
    (<repo>/.claude/worktrees/<name>, branch worktree-<name>): several agents
    can touch the same project without stepping on each other. `claude rm` deletes it if there
    are no unmerged changes. Without `path`, it works in a new folder (no project).
    With `profile` (an id from profiles/), whatever you do not choose takes the profile's value.
    With `anon`, an anonymous session (see ANON_PROMPT): `task` arrives already masked.
    """
    p = None
    if profile:
        p = profiles.get(profile)
        if not p:   # better not to launch than to launch without the requested guardrails
            return {'ok': False, 'id': None, 'err': f'profile "{profile}" does not exist (or is not valid)'}
    if worktree is None:
        worktree = bool(p and p['worktree'])
    if anon:
        return _launch_anon(path, task, model, name, mode, effort, worktree, p)
    if not path:
        path, worktree = new_scratch(task), False
    if notebooks.of_relpath(path):   # notebooks/ is the autosave repo: no worktrees there
        worktree = False
    if not Path(path).is_dir():
        return {'ok': False, 'err': f'folder {path} does not exist'}
    if worktree and not is_git_repo(path):
        return {'ok': False, 'err': f'{path} is not a git repo: cannot isolate it in a worktree'}
    model = valid_model(model) or (p and p['model']) or DEFAULT_MODEL
    cmd = [CLAUDE, '--bg', *(['--worktree'] if worktree else []),
           '--model', model, *_agent_flags(mode, effort, path, p)]
    if name:
        cmd += ['--name', name]
    cmd += ['--', task]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=path, timeout=90)
    short = _short_id(r.stdout)
    ok = r.returncode == 0 and short is not None
    invalidate()
    if not ok and 'not trusted' in (r.stdout + r.stderr):
        # claude --bg does not start in a folder without accepted trust, and only
        # a person can do that (by opening claude there once)
        where = str(NOTEBOOKS) if notebooks.of_relpath(path) else path
        return {'ok': False, 'id': None, 'out': r.stdout.strip(),
                'err': f'Claude Code does not trust {where} yet. In a terminal: '
                       f'cd {where} && claude, accept the trust prompt and exit; then try again.'}
    if ok:
        if p:
            remember_profile(profile_info(p), short)
        _log({'ts': time.time(), 'kind': 'launch', 'path': path,
              'task': task, 'model': model, 'mode': mode, 'effort': effort,
              'worktree': worktree, 'profile': p and p['id'], 'id': short})
    return {'ok': ok, 'id': short, 'out': r.stdout.strip(), 'err': r.stderr.strip()}


def _anon_worktree(repo: str) -> tuple[str | None, str | None]:
    """Isolated copy for an anonymous session (claude --worktree needs the session to run in
    the repo, and an anonymous one runs in an empty folder): same place and branch naming."""
    name = 'anon-' + time.strftime('%Y%m%d-%H%M%S')
    wt = Path(repo) / '.claude' / 'worktrees' / name
    r = subprocess.run(['git', '-C', repo, 'worktree', 'add', '-b', f'worktree-{name}', str(wt)],
                       capture_output=True, text=True, timeout=60)
    return (str(wt), None) if r.returncode == 0 else (None, (r.stderr or r.stdout).strip())


ANON_WARMUP = ('Anonymized session starting: your task arrives in the next message. '
               'Do not use any tool now; reply only "ready".')


def _answered(transcript: str | None) -> bool:
    """The warm-up turn is over: the transcript already has an answer from the assistant."""
    try:
        return bool(transcript) and '"type":"assistant"' in Path(transcript).read_text(errors='ignore').replace(' ', '')
    except OSError:
        return False


def _deliver_anon(short: str, task: str, wait_s: float = 180):
    """The real task of an anonymous session, once its warm-up turn is over: through the
    gatito mod if the session has it (same session, no restart). Without the mod it is
    resumed with the anonymous flags (Claude opens a copy, the original is archived): never
    without them, a copy without flags could come back with the built-in tools."""
    end = time.time() + wait_s
    while time.time() < end:
        time.sleep(2)
        a = next((x for x in list_agents(max_age=0) if x.get('id') == short), None)
        if not a or not a.get('sessionId') or not _answered(a.get('transcript')):
            continue
        if a.get('live') == 'idle' and modlink.send(a['sessionId'], task).get('ok'):
            return
        if not a.get('live') and a.get('ui') in ('done', 'blocked') and not a.get('perm'):
            subprocess.run([CLAUDE, 'stop', short], capture_output=True, text=True, timeout=20)
            res = resume_session(a['sessionId'], a.get('cwd'), task, a.get('model'), a.get('mode'),
                                 a.get('effort'), a.get('name'), keys=(short, a.get('key')))
            if res['ok'] and res.get('id') and res['id'] != short:
                set_hidden(a['key'], True)
            return
    _log({'ts': time.time(), 'kind': 'anon-deliver-failed', 'id': short})


def _launch_anon(path: str | None, task: str, model: str | None, name: str | None, mode: str | None,
                 effort: str | None, worktree: bool, p: dict | None) -> dict:
    """The session runs in a new empty folder (no git status, CLAUDE.md or real path in its
    context) and reaches the project, presented as /workspace, only through maskmcp.py."""
    if path and not Path(path).is_dir():
        return {'ok': False, 'err': f'folder {path} does not exist'}
    if path and worktree and not notebooks.of_relpath(path):
        if not is_git_repo(path):
            return {'ok': False, 'err': f'{path} is not a git repo: cannot isolate it in a worktree'}
        path, err = _anon_worktree(path)
        if err:
            return {'ok': False, 'err': f'could not create the worktree: {err}'}
    # the folder's name comes from the task, which is already masked
    cwd = new_scratch(task)
    root = path or cwd
    model = valid_model(model) or (p and p['model']) or DEFAULT_MODEL
    cmd = [CLAUDE, '--bg', '--model', model, *_agent_flags(mode, effort, cwd, p, anon_root=root)]
    if name:
        cmd += ['--name', name]
    # the first turn can start before the MCP server is connected: it is a warm-up, and the
    # task goes as the second message (_deliver_anon), when the tools are already there
    cmd += ['--', ANON_WARMUP]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=90, env=ANON_ENV)
    short = _short_id(r.stdout)
    ok = r.returncode == 0 and short is not None
    invalidate()
    if ok:
        threading.Thread(target=_deliver_anon, args=(short, task), daemon=True).start()
        remember_anon({'root': root}, short)
        if p:
            remember_profile(profile_info(p), short)
        _log({'ts': time.time(), 'kind': 'launch', 'path': root, 'anon': True, 'model': model,
              'mode': mode, 'effort': effort, 'profile': p and p['id'], 'id': short})
    elif 'not trusted' in (r.stdout + r.stderr):
        return {'ok': False, 'id': None, 'out': r.stdout.strip(),
                'err': f'Claude Code does not trust {CHATS} yet. In a terminal: cd {CHATS} && claude, '
                       'accept the trust prompt and exit; then try again.'}
    return {'ok': ok, 'id': short, 'out': r.stdout.strip(), 'err': r.stderr.strip()}


def _log(entry: dict):
    with open(STATE / 'history.jsonl', 'a') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


# ------------------------------------------------------- system actions

def run_action(action_id: str, desired: bool | None = None) -> dict:
    act = next((a for a in load_actions() if a['id'] == action_id), None)
    if not act:
        return {'ok': False, 'err': 'unknown action'}
    if act['type'] == 'gsettings-toggle':
        cur = subprocess.run(['gsettings', 'get', act['schema'], act['key']],
                             capture_output=True, text=True).stdout.strip()
        cur_b = cur == 'true'
        new = (not cur_b) if desired is None else desired
        subprocess.run(['gsettings', 'set', act['schema'], act['key'],
                        'true' if new else 'false'])
        return {'ok': True, 'state': new}
    return {'ok': False, 'err': 'unsupported action type'}

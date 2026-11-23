#!/usr/bin/python3
"""Backlog: tasks waiting for their moment to be launched as agents.

Each task says when it starts (`trigger`):
  - queue:  as soon as there is room, in order of arrival. At most
            `max_parallel` background agents working at once (config.json).
  - at:     at a specific time (`at`, epoch ms). With `repeat` it reschedules
            itself after launching. It ignores the limit: you asked for that time.
  - manual: waits for you to launch it ("Run now").
If the PC was off at that time, it launches as soon as gatito starts.

States: pending -> launching -> launched (or failed). Repeating ones go back to
pending with the next time. Stored in state/backlog.json.
"""
from __future__ import annotations

import secrets
import threading
import time
from datetime import datetime, timedelta

import core
import profiles
import store

FILE = core.STATE / 'backlog.json'
TRIGGERS = ('queue', 'at', 'manual')
REPEATS = ('daily', 'weekdays', 'weekly')
TICK_S = 20
# Launched ones stay for a while (to see which session came out) and are then deleted.
KEEP_LAUNCHED_H = 24 * 7
EDITABLE = ('task', 'project_id', 'model', 'mode', 'effort', 'worktree', 'trigger', 'at', 'repeat',
            'rank', 'profile', 'anon')

_wake = threading.Event()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clean(f: dict, base: dict | None = None) -> tuple[dict | None, str | None]:
    """Validate the fields coming from the web UI. Returns (fields, error)."""
    d = {**(base or {}), **{k: f[k] for k in EDITABLE if k in f}}
    d['task'] = (d.get('task') or '').strip()
    if not d['task']:
        return None, 'the task is missing'
    if not core.get_project(d.get('project_id') or ''):
        return None, 'choose a project'
    # task profile: whatever is not chosen takes its value (and in read-only, the mode is its own)
    p = None
    if d.get('profile'):
        p = profiles.get(d['profile'])
        if not p:
            return None, f'profile "{d["profile"]}" does not exist'
    d['profile'] = p and p['id']
    d['model'] = core.valid_model(d.get('model')) or (p and p['model']) or core.DEFAULT_MODEL
    if p and p['read_only']:
        d['mode'] = 'dontAsk'
    elif d.get('mode') not in core.MODE_IDS:
        d['mode'] = (p and p['mode']) or core.DEFAULT_MODE
    if d.get('effort') not in core.EFFORTS:
        d['effort'] = p and p['effort']
    d['worktree'] = bool(d.get('worktree') if 'worktree' in f or base else p and p['worktree'])
    # anonymized: it is stored with the real values and masked when it is launched (mask.py)
    d['anon'] = bool(d.get('anon'))
    # position in the queue (the web UI changes it on drag); by default, order of arrival
    d['rank'] = d['rank'] if isinstance(d.get('rank'), (int, float)) else None
    if d.get('trigger') not in TRIGGERS:
        return None, 'when: queue, at or manual'
    if d['trigger'] == 'at':
        try:
            d['at'] = int(d.get('at'))
        except (TypeError, ValueError):
            return None, 'provide the time'
        if d.get('repeat') not in REPEATS:
            d['repeat'] = None
    else:
        d['at'] = d['repeat'] = None
    return d, None


def _order(i: dict):
    # scheduled by time, then the queue by arrival, then the manual ones
    rank = {'at': 0, 'queue': 1, 'manual': 2}[i['trigger']]
    return (rank, i.get('at') or i.get('rank') or i['created'])


def list_items(include_launched: bool = False) -> list[dict]:
    items = store.read(FILE, []) or []
    if not include_launched:
        items = [i for i in items if i['status'] != 'launched']
    items.sort(key=_order)
    pos = 0
    for i in items:  # position in the queue, for the UI
        if i['trigger'] == 'queue' and i['status'] == 'pending':
            pos += 1
            i['queue_pos'] = pos
    return items


def add(fields: dict) -> dict:
    d, err = _clean(fields)
    if err:
        return {'ok': False, 'err': err}
    item = {**d, 'id': secrets.token_hex(4), 'status': 'pending',
            'created': _now_ms(), 'runs': []}
    with store.edit(FILE, []) as items:
        items.append(item)
    _wake.set()
    return {'ok': True, 'item': item}


def update(item_id: str, fields: dict) -> dict:
    with store.edit(FILE, []) as items:
        it = next((i for i in items if i['id'] == item_id), None)
        if not it:
            return {'ok': False, 'err': 'does not exist'}
        if it['status'] == 'launching':
            return {'ok': False, 'err': 'it is being launched right now'}
        d, err = _clean(fields, {k: it.get(k) for k in EDITABLE})
        if err:
            return {'ok': False, 'err': err}
        it.update(d, status='pending', err=None)
    _wake.set()
    return {'ok': True, 'item': it}


def remove(item_id: str) -> dict:
    with store.edit(FILE, []) as items:
        n = len(items)
        items[:] = [i for i in items if i['id'] != item_id]
    return {'ok': len(items) < n}


def run_now(item_id: str) -> dict:
    """Launch now, ignoring the limit and the time."""
    return _launch(item_id)


# ----------------------------------------------------------------- launching

def _next_at(at_ms: int, repeat: str) -> int:
    """Next future time (in local time, so it does not shift with DST changes)."""
    dt = datetime.fromtimestamp(at_ms / 1000)
    now = datetime.now()
    while dt <= now:
        dt += timedelta(days=7 if repeat == 'weekly' else 1)
        while repeat == 'weekdays' and dt.weekday() >= 5:
            dt += timedelta(days=1)
    return int(dt.timestamp() * 1000)


def _launch(item_id: str) -> dict:
    # It is marked before launching (it takes a while) so it is not launched twice or edited halfway.
    with store.edit(FILE, []) as items:
        it = next((i for i in items if i['id'] == item_id), None)
        if not it or it['status'] in ('launching', 'launched'):
            return {'ok': False, 'err': 'it is not pending'}
        it['status'] = 'launching'
        job = dict(it)

    proj = core.get_project(job['project_id'])
    if proj:
        task, name = job['task'], f"{proj['id']}: {job['task'][:40]}"
        if job.get('anon'):
            import mask
            task, name = mask.mask_message(task), mask.mask(name)['text']
        res = core.launch_agent(proj['path'], task, job['model'], name,
                                job['mode'], job['effort'], job.get('worktree', False),
                                job.get('profile'))
    else:
        res = {'ok': False, 'err': f"project {job['project_id']} no longer exists"}

    with store.edit(FILE, []) as items:
        it = next((i for i in items if i['id'] == item_id), None)
        if it:
            it['runs'] = (it.get('runs') or [])[-9:] + [{
                'ts': _now_ms(), 'agent_id': res.get('id'), 'ok': res['ok'],
                'err': None if res['ok'] else (res.get('err') or res.get('out') or '')[:300]}]
            if it['trigger'] == 'at' and it.get('repeat'):
                it['status'] = 'pending'
                it['at'] = _next_at(it['at'], it['repeat'])
            else:
                it['status'] = 'launched' if res['ok'] else 'failed'
            it['err'] = it['runs'][-1]['err']
    _notify(job, res)
    return res


def _notify(job: dict, res: dict):
    try:
        import push
    except ImportError:
        return
    name = job['task'].split('\n')[0][:80]
    if not res['ok']:
        push.notify_bg('failed', f'Could not launch: {name}', res.get('err') or res.get('out') or '',
                       f"/#bl-{job['id']}", tag=f"bl-{job['id']}")
    elif job['trigger'] == 'at':
        push.notify_bg('launched', f'Started: {name}', f"Scheduled in {job['project_id']}.",
                       f"/#{res.get('id')}", tag=f"bl-{job['id']}")


def tick():
    now = _now_ms()
    items = list_items(include_launched=True)

    with store.edit(FILE, []) as stored:  # cleanup of the ones launched a while ago
        stored[:] = [i for i in stored if i['status'] != 'launched' or
                     now - (i['runs'][-1]['ts'] if i.get('runs') else i['created'])
                     < KEEP_LAUNCHED_H * 3_600_000]

    pending = [i for i in items if i['status'] == 'pending']
    for i in pending:
        if i['trigger'] == 'at' and i['at'] <= now:
            _launch(i['id'])

    queue = [i for i in pending if i['trigger'] == 'queue']
    if not queue:
        return
    working = sum(1 for a in core.list_agents(max_age=0)
                  if a['group'] == 'working' and a.get('kind') == 'background')
    for i in queue[:max(0, core.config()['max_parallel'] - working)]:
        _launch(i['id'])


def counts() -> dict:
    items = list_items()
    return {'queued': sum(1 for i in items if i['status'] == 'pending'),
            'failed': sum(1 for i in items if i['status'] == 'failed')}


def _loop():
    while True:
        try:
            tick()
        except Exception as e:  # the loop cannot die because of a weird task
            print(f'backlog: {e!r}', flush=True)
        _wake.wait(TICK_S)
        _wake.clear()


def start():
    # If gatito was cut off halfway through a launch, it goes back to pending.
    with store.edit(FILE, []) as items:
        for i in items:
            if i['status'] == 'launching':
                i['status'] = 'pending'
    threading.Thread(target=_loop, name='backlog', daemon=True).start()

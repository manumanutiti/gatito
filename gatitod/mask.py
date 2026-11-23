#!/usr/bin/python3
"""Pseudo-anonymization of what is sent to Claude (inspired by maskit).

Before a message leaves for Claude, the real values are swapped for consistent
placeholders; what Claude answers is shown with the real values again.

- Dictionary (editable in the web UI): real term -> placeholder, with a kind (tenant,
  subscription, resource group, cluster, domain, person...). Matches ignore case and
  keep it ("ACME" -> "TENANT-ALPHA"), and only whole pieces of a name count: in
  `rg-acme-prod` or `api.acme.com` it is replaced, in `acmeprod` it is not.
- Detectors (automatic): IPv4 (prefix-preserving: two IPs in the same /8, /16 or /24
  stay in the same fake subnet, so the AI's answers about networks remain true),
  e-mails, GUIDs (tenant, subscription, client ids), Azure resource ids
  (/subscriptions/../resourceGroups/<rg>/providers/../<name>), AWS ARNs and account
  ids, and secrets (keys, tokens, passwords, connection strings, JWT, private keys).
- What the detectors find is remembered in a vault (state/mask/vault.json): the same
  real value always gets the same placeholder, in this chat and in the next ones,
  and every conversation can be shown with the real values again.

The placeholders keep the shape of the original (a GUID is still a GUID, an IP an IP,
a storage account name only lowercase letters and digits) so the code and commands
the AI writes are still valid once the real values are put back.

Limit: only what you type goes masked. If the agent reads files or runs commands on
your machine, it sees their real contents.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import secrets
import threading
from pathlib import Path

import store
from core import STATE

DIR = STATE / 'mask'
DIR.mkdir(exist_ok=True)
CONFIG = DIR / 'config.json'
VAULT = DIR / 'vault.json'

# Kinds of dictionary entries: label and placeholder pattern ({w}: alpha, bravo...).
# The patterns respect the naming rules of each resource so the AI's code stays valid.
KINDS = [
    {'id': 'tenant', 'label': 'Tenant (name)', 'fake': 'tenant-{w}'},
    {'id': 'tenant_id', 'label': 'Tenant ID', 'fake': '{guid}'},
    {'id': 'subscription', 'label': 'Subscription (name)', 'fake': 'sub-{w}'},
    {'id': 'subscription_id', 'label': 'Subscription ID', 'fake': '{guid}'},
    {'id': 'client', 'label': 'Client / company', 'fake': 'client-{w}'},
    {'id': 'domain', 'label': 'Domain', 'fake': '{w}.example.com'},
    {'id': 'host', 'label': 'Hostname / server', 'fake': 'host-{w}'},
    {'id': 'rg', 'label': 'Resource group', 'fake': 'rg-{w}'},
    {'id': 'cluster', 'label': 'Cluster (AKS/EKS/GKE)', 'fake': 'aks-{w}'},
    {'id': 'namespace', 'label': 'K8s namespace', 'fake': 'ns-{w}'},
    {'id': 'keyvault', 'label': 'Key Vault', 'fake': 'kv-{w}'},
    {'id': 'storage', 'label': 'Storage account', 'fake': 'st{w}01'},
    {'id': 'registry', 'label': 'Container registry', 'fake': 'acr{w}01'},
    {'id': 'vnet', 'label': 'VNet / VPC', 'fake': 'vnet-{w}'},
    {'id': 'app', 'label': 'App / service principal', 'fake': 'app-{w}'},
    {'id': 'app_id', 'label': 'Client / app ID', 'fake': '{guid}'},
    {'id': 'aws_account', 'label': 'AWS account', 'fake': '{aws}'},
    {'id': 'gcp_project', 'label': 'GCP project', 'fake': 'proj-{w}-001'},
    {'id': 'devops_org', 'label': 'DevOps / GitHub org', 'fake': 'org-{w}'},
    {'id': 'devops_project', 'label': 'DevOps project', 'fake': 'project-{w}'},
    {'id': 'repo', 'label': 'Repository', 'fake': 'repo-{w}'},
    {'id': 'pipeline', 'label': 'Pipeline', 'fake': 'pipeline-{w}'},
    {'id': 'person', 'label': 'Person', 'fake': 'person-{w}'},
    {'id': 'secret', 'label': 'Secret', 'fake': 'masked-secret-{w}'},
    {'id': 'other', 'label': 'Other', 'fake': 'term-{w}'},
]
KIND_IDS = {k['id'] for k in KINDS}

DETECTORS = [
    {'id': 'secret', 'label': 'Secrets (keys, tokens, passwords, connection strings)'},
    {'id': 'azure', 'label': 'Azure resource ids (resource group and resource names)'},
    {'id': 'arn', 'label': 'AWS ARNs and account ids'},
    {'id': 'guid', 'label': 'GUIDs (tenant, subscription, client ids)'},
    {'id': 'email', 'label': 'E-mails'},
    {'id': 'ip', 'label': 'IPv4 (keeps subnets)'},
]

# Never masked: they mean the same for everybody and the AI needs them as they are.
KEEP = [
    '8.8.8.8', '8.8.4.4', '1.1.1.1', '1.0.0.1', '9.9.9.9', '168.63.129.16', '169.254.169.254',
    '00000000-0000-0000-0000-000000000000',
    '00000003-0000-0000-c000-000000000000',   # Microsoft Graph
    '797f4846-ba00-4fd7-ba43-dac1f8f63013',   # Azure Resource Manager
    '8e3af657-a8ff-443c-a75c-2fe8c4bcb635',   # Owner
    'b24988ac-6180-42a0-ab88-20f7382dd24c',   # Contributor
    'acdd72a7-3385-48ef-bd42-f606fba81ae7',   # Reader
    '18d7d88d-d35e-4fb5-a5c3-7773c20a72d9',   # User Access Administrator
    'example.com', 'localhost',
]

NATO = ('alpha bravo charlie delta echo foxtrot golf hotel india juliett kilo lima mike november '
        'oscar papa quebec romeo sierra tango uniform victor whiskey xray yankee zulu').split()

# The first line of a masked message: the AI knows the names are consistent pseudonyms.
NOTE = ('[gatito: some names, ids, IPs and secrets in this conversation are consistent pseudonyms. '
        'Treat them as the real values and write them exactly as they appear.]')

_lock = threading.RLock()
_cache: dict = {}


# ------------------------------------------------------------------ state

def _default_config() -> dict:
    return {'entries': [], 'detect': {d['id']: True for d in DETECTORS}, 'keep': [],
            'seed': secrets.token_hex(16)}


def _read(path: Path):
    """store.read with a cache by mtime: the agent list is unmasked every few seconds."""
    try:
        st = path.stat()
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        return None
    hit = _files.get(path)
    if hit and hit[0] == stamp:
        return json.loads(hit[1])
    data = store.read(path, None)
    _files[path] = (stamp, json.dumps(data))
    return data


_files: dict = {}


def config() -> dict:
    c = _read(CONFIG)
    if not isinstance(c, dict):
        c = _default_config()
        store.write(CONFIG, c)
    c.setdefault('entries', [])
    c.setdefault('keep', [])
    c['detect'] = {d['id']: bool((c.get('detect') or {}).get(d['id'], True)) for d in DETECTORS}
    if not c.get('seed'):
        c['seed'] = secrets.token_hex(16)
        store.write(CONFIG, c)
    return c


def vault() -> dict:
    v = _read(VAULT)
    if not isinstance(v, dict):
        v = {}
    v.setdefault('map', {})       # real -> {fake, kind}
    v.setdefault('n', {})         # counters per kind
    return v


def _clean_entries(entries) -> tuple[list[dict], list[str]]:
    out, errs, reals, fakes = [], [], {}, {}
    for e in entries or []:
        real, fake = str(e.get('real') or '').strip(), str(e.get('fake') or '').strip()
        if not real and not fake:
            continue
        kind = e.get('kind') if e.get('kind') in KIND_IDS else 'other'
        if not real or not fake:
            errs.append(f'"{real or fake}": real value and placeholder are both needed')
            continue
        if len(real) < 3:
            errs.append(f'"{real}": too short, it would match inside other words')
            continue
        if real.lower() == fake.lower():
            errs.append(f'"{real}": the placeholder must differ from the real value')
            continue
        if real.lower() in reals:
            errs.append(f'"{real}" is repeated')
            continue
        if fake.lower() in fakes:
            errs.append(f'placeholder "{fake}" is used by "{fakes[fake.lower()]}" and "{real}": '
                        'it could not be undone')
            continue
        reals[real.lower()], fakes[fake.lower()] = fake, real
        out.append({'real': real, 'fake': fake, 'kind': kind, 'on': e.get('on', True) is not False})
    return out, errs


def save(fields: dict) -> dict:
    with _lock:
        c = config()
        if 'entries' in fields:
            entries, errs = _clean_entries(fields['entries'])
            if errs:
                return {'ok': False, 'err': '; '.join(errs[:5])}
            c['entries'] = entries
        if isinstance(fields.get('detect'), dict):
            c['detect'] = {d['id']: bool(fields['detect'].get(d['id'], True)) for d in DETECTORS}
        if 'keep' in fields:
            c['keep'] = sorted({str(k).strip() for k in fields['keep'] or [] if str(k).strip()})
        store.write(CONFIG, c)
        _cache.clear()
        return {'ok': True}


def forget(real: str | None = None) -> dict:
    """Forget what the detectors learned (one value, or all). Chats that used it can no
    longer be shown with the real value."""
    with _lock:
        v = vault()
        if real is None:
            v = {'map': {}, 'n': {}}
        else:
            v['map'].pop(real, None)
        store.write(VAULT, v)
        _cache.clear()
        return {'ok': True}


def public() -> dict:
    c = config()
    v = vault()
    learned = sorted(({'real': r, **x} for r, x in v['map'].items()), key=lambda x: (x['kind'], x['fake']))
    return {'entries': c['entries'], 'detect': c['detect'], 'keep': c['keep'], 'kinds': KINDS,
            'detectors': DETECTORS, 'builtin_keep': KEEP, 'learned': learned, 'nato': NATO}


# ------------------------------------------------------------------ fakes

def _fake_guid(n: int) -> str:
    # valid v4 GUID and easy to recognize as a fake
    return f'00000000-0000-4000-a000-{n:012x}'


def _new_fake(v: dict, kind: str, real: str, c: dict) -> str:
    n = v['n'][kind] = v['n'].get(kind, 0) + 1
    if kind == 'guid':
        return _fake_guid(n)
    if kind == 'email':
        return f'user{n}@example.com'
    if kind == 'aws_account':
        return f'9999{n:08d}'
    if kind == 'aws_key':
        return f'AKIAMASKED{n:010d}'
    if kind == 'secret':
        return f'masked-secret-{n}'
    if kind == 'rg':
        return f'rg-masked-{n}'
    if kind == 'resource':
        # lowercase letters and digits: valid even for storage accounts and registries
        return f'resmasked{n}'
    if kind == 'ip':
        return _fake_ip(real, c['seed'])
    return f'masked-{kind}-{n}'


def _perm(seed: str, prefix: str, pool: list[int]) -> dict[int, int]:
    rnd = random.Random(hashlib.sha256(f'{seed}|{prefix}'.encode()).digest())
    shuffled = pool[:]
    rnd.shuffle(shuffled)
    return dict(zip(pool, shuffled))


_PUBLIC_FIRST = [i for i in range(1, 224) if i not in (10, 100, 127, 169, 172, 192)]
_HOST = list(range(1, 255))     # 0 and 255 stay: network, broadcast and masks keep their meaning


def _fake_ip(ip: str, seed: str) -> str:
    """Prefix-preserving: each octet is shuffled with a permutation that depends on the
    real octets before it. Private ranges stay private (10/8, 172.16/12, 192.168/16)."""
    o = [int(x) for x in ip.split('.')]
    out = []
    for i, x in enumerate(o):
        pre = '.'.join(map(str, o[:i]))
        if i == 0:
            pool = _PUBLIC_FIRST if x in _PUBLIC_FIRST else None
        elif o[0] == 192 and o[1] == 168 and i == 1:
            pool = None
        elif o[0] == 172 and i == 1:
            pool = list(range(16, 32)) if 16 <= x <= 31 else [p for p in _HOST if not 16 <= p <= 31]
        else:
            pool = _HOST
        out.append(_perm(seed, pre, pool)[x] if pool and x in pool else x)
    return '.'.join(map(str, out))


# ------------------------------------------------------------------ detectors

_IP = re.compile(r'(?<![\w.])((?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3})(?![\w]|\.\d)')
_MASK_OCTETS = {0, 128, 192, 224, 240, 248, 252, 254, 255}
_EMAIL = re.compile(r'(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])')
_GUID = re.compile(r'(?<![0-9A-Fa-f-])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f-])')
_AZ_RG = re.compile(r'/resourceGroups/([^/\s"\'`,;)]+)', re.I)
_AZ_RES = re.compile(r'/providers/[\w.]+/[\w]+/([^/\s"\'`,;)]+)((?:/[\w]+/[^/\s"\'`,;)]+)*)', re.I)
_ARN = re.compile(r'arn:aws[\w-]*:[\w-]*:[\w-]*:(\d{12}):')
_AWS_ACCT = re.compile(r'(?i)(?:account[\s_-]*(?:id)?|owner[\s_-]*id)["\']?\s*[:=]?\s*["\']?(\d{12})(?!\d)')
_AWS_KEY = re.compile(r'(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])')
_SECRETS = [
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----'),
    re.compile(r'(?<![\w-])eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}'),                      # JWT
    re.compile(r'(?<![\w])(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})'),  # GitHub
    re.compile(r'(?<![\w])xox[abprs]-[A-Za-z0-9-]{10,}'),                                # Slack
    re.compile(r'(?<![\w])sk-(?:ant-)?[A-Za-z0-9_-]{20,}'),                              # API keys
    re.compile(r'(?<![\w])glpat-[A-Za-z0-9_-]{20,}'),                                    # GitLab
]
# key=value: only the value is masked
_SECRET_KV = re.compile(
    r'(?i)\b(?:password|passwd|pwd|secret|client[_-]?secret|api[_-]?key|apikey|access[_-]?key|'
    r'secret[_-]?key|token|auth[_-]?token|accountkey|sharedaccesskey|sig)\b["\']?\s*[:=]\s*["\']?'
    r'([^\s"\';,&]{6,})')


def _keep_set(c: dict) -> set[str]:
    return {k.lower() for k in KEEP + c['keep']}


def _detect(text: str, c: dict, v: dict) -> list[tuple[str, str]]:
    """(real, kind) found in the text, in order of priority."""
    d, found = c['detect'], []
    if d['secret']:
        for rx in _SECRETS:
            found += [(m.group(0), 'secret') for m in rx.finditer(text)]
        found += [(m.group(0), 'aws_key') for m in _AWS_KEY.finditer(text)]
        found += [(m.group(1), 'secret') for m in _SECRET_KV.finditer(text)]
    if d['azure']:
        found += [(m.group(1), 'rg') for m in _AZ_RG.finditer(text)]
        for m in _AZ_RES.finditer(text):
            found.append((m.group(1), 'resource'))
            found += [(x, 'resource') for x in re.findall(r'/[\w]+/([^/\s"\'`,;)]+)', m.group(2) or '')]
    if d['arn']:
        found += [(m.group(1), 'aws_account') for m in _ARN.finditer(text)]
        found += [(m.group(1), 'aws_account') for m in _AWS_ACCT.finditer(text)]
    if d['guid']:
        found += [(m.group(0), 'guid') for m in _GUID.finditer(text)]
    if d['email']:
        found += [(m.group(0), 'email') for m in _EMAIL.finditer(text)]
    if d['ip']:
        for m in _IP.finditer(text):
            ip = m.group(1)
            oc = [int(x) for x in ip.split('.')]
            if oc[0] in (0, 127, 255) or all(x in _MASK_OCTETS for x in oc):
                continue     # loopback, "any" and netmasks: the AI needs them as they are
            found.append((ip, 'ip'))
    return found


# ------------------------------------------------------------------ matching

def _style(s: str) -> str:
    letters = [ch for ch in s if ch.isalpha()]
    if not letters:
        return 'none'
    if all(ch.isupper() for ch in letters):
        return 'upper'
    if all(ch.islower() for ch in letters):
        return 'lower'
    if letters[0].isupper() and all(ch.islower() for ch in letters[1:]):
        return 'cap'
    return 'mixed'


def _cap(s: str) -> str:
    for i, ch in enumerate(s):
        if ch.isalpha():
            return s[:i] + ch.upper() + s[i + 1:].lower()
    return s


def _mixed(s: str) -> str:
    """A form of `s` whose style is 'mixed' (if it can have one): it goes back as the canonical."""
    if _style(s) == 'mixed':
        return s
    t = s.title()
    return t if _style(t) == 'mixed' else s


def _shape(src: str, target: str) -> str:
    """Carry the case style of `src` over to `target`, so it can be undone exactly:
    ACME <-> TENANT-ALPHA, acme <-> tenant-alpha, Acme <-> Tenant-alpha, and a
    mixed-case value (AcmeCorp) <-> the target in mixed case (Tenant-Alpha)."""
    st = _style(src)
    if st == 'upper':
        return target.upper()
    if st == 'lower':
        return target.lower()
    if st == 'cap':
        return _cap(target)
    if st == 'mixed':
        return _mixed(target)
    return target


def _alt(terms: list[str]) -> str:
    return '|'.join(re.escape(t) for t in sorted(terms, key=len, reverse=True))


def _tables(c: dict, v: dict) -> dict:
    """Compiled regexes for both directions. Cached until config or vault change."""
    key = (json.dumps(c['entries'], sort_keys=True), json.dumps(v['map'], sort_keys=True))
    if _cache.get('key') == key:
        return _cache['t']
    dict_fwd = {e['real'].lower(): e for e in c['entries'] if e['on']}
    dict_back = {e['fake'].lower(): e for e in c['entries'] if e['on']}
    auto_fwd = {r: x['fake'] for r, x in v['map'].items()}
    # IPs come back in their own pass (_unfake_ip), the rest with the regex
    auto_back = {x['fake']: r for r, x in v['map'].items() if x['kind'] != 'ip'}
    ip_back = {x['fake']: r for r, x in v['map'].items() if x['kind'] == 'ip'}
    # a piece of a name: not glued to letters or digits on either side
    B, E = r'(?<![A-Za-z0-9])', r'(?![A-Za-z0-9])'

    def build(ci: list[str], exact: list[str]):
        parts = []
        if exact:
            parts.append(f'(?:{_alt(exact)})')
        if ci:
            parts.append(f'(?i:{_alt(ci)})')
        return re.compile(f'{B}(?:{"|".join(parts)}){E}') if parts else None

    t = {'dict_fwd': dict_fwd, 'dict_back': dict_back, 'auto_fwd': auto_fwd, 'auto_back': auto_back,
         'ip_back': ip_back,
         'fwd': build([e['real'] for e in dict_fwd.values()], list(auto_fwd)),
         'back': build([e['fake'] for e in dict_back.values()], list(auto_back)),
         # fake /24s that were handed out: new IPs the AI invents there go back too
         'nets': {f.rsplit('.', 1)[0]: r.rsplit('.', 1)[0] for f, r in ip_back.items()}}
    _cache.update(key=key, t=t)
    return t


# ------------------------------------------------------------------ API

def mask(text: str, learn: bool = True, entries: list | None = None) -> dict:
    """Swap real values for placeholders. Returns {text, found: [{real, fake, kind}]}.
    Without `learn` (a preview) what the detectors find is not saved in the vault;
    `entries` replaces the saved list (a preview of the list being edited)."""
    if not text:
        return {'text': text, 'found': []}
    with _lock:
        c, v = config(), vault()
        if entries is not None:
            entries, errs = _clean_entries(entries)
            if errs:
                return {'text': text, 'found': [], 'err': '; '.join(errs[:5])}
            c['entries'] = entries
        keep = _keep_set(c)
        t0 = _tables(c, v)
        known_fakes = {f.lower() for f in [*t0['auto_back'], *t0['ip_back']]} | set(t0['dict_back'])
        changed = False
        for real, kind in _detect(text, c, v):
            low = real.lower()
            if low in keep or low in known_fakes or real in v['map'] or low in t0['dict_fwd']:
                continue
            if kind == 'secret' and (len(real) < 6 or low.startswith('masked-secret')):
                continue
            fake = _new_fake(v, kind, real, c)
            v['map'][real] = {'fake': fake, 'kind': kind}
            known_fakes.add(fake.lower())
            changed = True
        if changed and learn:
            store.write(VAULT, v)
        t = _tables(c, v)
        found: dict[str, dict] = {}

        def rep(m):
            s = m.group(0)
            if s in t['auto_fwd']:
                f = t['auto_fwd'][s]
                found[s] = {'real': s, 'fake': f, 'kind': v['map'][s]['kind']}
                return f
            e = t['dict_fwd'].get(s.lower())
            if not e:
                return s
            f = _shape(s, e['fake'])
            found[s] = {'real': s, 'fake': f, 'kind': e['kind']}
            return f

        out = t['fwd'].sub(rep, text) if t['fwd'] else text
        return {'text': out, 'found': list(found.values())}


def mask_message(text: str) -> str:
    """mask() for a message to an agent: with the note at the end if something was masked
    (at the end: the first line is the session title and the folder name)."""
    r = mask(text)
    if not r['found'] or NOTE in text:
        return r['text']
    return f"{r['text']}\n\n{NOTE}"


def _unfake_ip(ip: str, t: dict, seed: str) -> str | None:
    """A fake IP we handed out, or one the AI wrote inside a fake /24 of ours: undo the
    permutation. Any other IP (one the agent read on your machine) is left alone."""
    if ip in t['ip_back']:
        return t['ip_back'][ip]
    net, last = ip.rsplit('.', 1)
    real_net = t['nets'].get(net)
    if not real_net:
        return None
    x = int(last)
    if x not in _HOST:
        return f'{real_net}.{x}'
    inv = {b: a for a, b in _perm(seed, real_net, _HOST).items()}
    return f'{real_net}.{inv[x]}'


def unmask(text: str) -> str:
    """Put the real values back (in what the AI answers, summaries, titles...)."""
    if not text or not isinstance(text, str):
        return text
    with _lock:
        c, v = config(), vault()
        t = _tables(c, v)
    if NOTE in text:
        text = text.replace('\n\n' + NOTE, '').replace(NOTE, '')

    def rep(m):
        s = m.group(0)
        if s in t['auto_back']:
            return t['auto_back'][s]
        e = t['dict_back'].get(s.lower())
        return _shape(s, e['real']) if e else s

    # IPs first: the regex pass could otherwise give back an IP that looks like one of ours
    if t['nets']:
        text = _IP.sub(lambda m: _unfake_ip(m.group(1), t, c['seed']) or m.group(0), text)
    if t['back']:
        text = t['back'].sub(rep, text)
    return text


def unmask_obj(o, skip: tuple = ()):
    """unmask() on every string of a JSON structure (copy), except the keys in `skip`."""
    if isinstance(o, str):
        return unmask(o)
    if isinstance(o, list):
        return [unmask_obj(x, skip) for x in o]
    if isinstance(o, dict):
        return {k: (x if k in skip else unmask_obj(x, skip)) for k, x in o.items()}
    return o

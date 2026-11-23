"""Task profiles: how an agent behaves and, above all, what it can touch.

A profile is a file `profiles/<id>.md`: YAML metadata at the top (the same kind
notebooks.split understands) and a body that is appended to the agent's system prompt.

    ---
    title: Review
    description: Reviews a change without touching anything        (one line, shown in the web UI)
    model: opus              # default; whatever you pick by hand in the web UI wins
    mode: auto                # same (ignored with read_only: always dontAsk)
    effort: high            # same
    read_only: true        # allowlist: read-only commands only (see READ_ALLOW)
    allow:                 # extra tool rules (Claude Code syntax)
      - Bash(stern *)
    deny:                  # extra rules to deny
      - Bash(kubectl delete *)
    notebooks: [infra]        # starts with `notebook context <id>` for each one
    worktree: false           # default value of the worktree button
    ---
    Text for the agent…

The fields are untrusted data (they end up on a command line): everything is validated
and whatever does not fit is dropped with a warning in the log. A badly written profile is
ignored entirely; it never takes gatito down. They are read from disk on every use (cached
by date and size): editing a profile does not require a restart.

Stdlib only and does not import core at load time (core imports this module).
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path

import notebooks

BASE = Path(os.environ.get('GATITO_PROFILES') or Path(__file__).resolve().parent.parent / 'profiles')
ID_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,39}$')
FIELDS = ('title', 'description', 'model', 'mode', 'effort', 'read_only', 'allow',
          'deny', 'notebooks', 'worktree')
MAX_BODY = 8000
MAX_RULES = 80

# A tool rule: name (Bash, Read, mcp__x__y…) and, optionally, its content in parentheses.
# It starts with a letter, so it can never pass as a flag (`--something`) on the command
# line, and has no control characters (a newline would split the argument).
RULE_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,63}(\([^\x00-\x1f\x7f]{1,300}\))?$')
# Tools that write: a read-only profile cannot allow them on its own.
WRITE = {'Edit', 'Write', 'MultiEdit', 'NotebookEdit'}
# Programs that run something else or write files by trade: allowing them in read-only
# would open the whole door, so such a `allow` is dropped.
EJECUTAN = {'bash', 'sh', 'zsh', 'dash', 'fish', 'env', 'xargs', 'sudo', 'su', 'doas', 'eval', 'exec',
            'python', 'python3', 'node', 'perl', 'ruby', 'php', 'lua', 'awk', 'gawk', 'sed', 'tee',
            'dd', 'cp', 'mv', 'rm', 'ln', 'install', 'make', 'nohup', 'timeout', 'nice', 'watch',
            'ssh', 'scp', 'rsync', 'curl', 'wget', 'npm', 'npx', 'pip', 'uv', 'go', 'cargo', 'touch',
            'mkdir', 'chmod', 'chown', 'truncate', 'source', 'command', 'builtin', 'find'}

# ------------------------------------------------------------- read-only
# Allowlist for read-only profiles: they run in dontAsk mode, which denies everything not
# listed here. Claude Code checks each part of a compound line (`a && b`, `a | b`, `a; b`)
# and does not accept a `$(…)` substitution, so chaining does not slip through (tested
# with real agents: see README, "Profiles"). The most basic read commands (ls, cat, grep,
# find without -exec…) are already allowed by Claude Code on its own.
READ_ALLOW = [
    # git: look, never change branches or the index
    'Bash(git status*)', 'Bash(git log*)', 'Bash(git diff*)', 'Bash(git show*)', 'Bash(git blame *)',
    'Bash(git ls-files*)', 'Bash(git rev-parse *)', 'Bash(git branch --show-current)',
    'Bash(git branch -a)', 'Bash(git branch -r)', 'Bash(git branch -v)', 'Bash(git branch -vv)',
    'Bash(git remote -v)', 'Bash(git describe*)', 'Bash(git shortlog *)',
    # Kubernetes
    'Bash(kubectl get *)', 'Bash(kubectl describe *)', 'Bash(kubectl logs *)', 'Bash(kubectl top *)',
    'Bash(kubectl explain *)', 'Bash(kubectl api-resources*)', 'Bash(kubectl api-versions*)',
    'Bash(kubectl version*)', 'Bash(kubectl config get-contexts*)', 'Bash(kubectl config current-context*)',
    'Bash(kubectl diff *)', 'Bash(kubectl auth can-i *)', 'Bash(kubectl events*)',
    'Bash(kubectl rollout history *)', 'Bash(kubectl rollout status *)',
    # Helm
    'Bash(helm list*)', 'Bash(helm ls*)', 'Bash(helm get *)', 'Bash(helm status *)',
    'Bash(helm template *)', 'Bash(helm diff *)', 'Bash(helm show *)', 'Bash(helm history *)',
    'Bash(helm lint *)', 'Bash(helm version*)',
    # Terraform / OpenTofu. `plan` only with -lock=false first: without it, it takes the
    # remote state lock (writes to the backend and can block whoever is about to apply)
    'Bash(terraform plan -lock=false*)', 'Bash(terraform show*)', 'Bash(terraform validate*)',
    'Bash(terraform fmt -check*)', 'Bash(terraform state list*)', 'Bash(terraform state show *)',
    'Bash(terraform providers*)', 'Bash(terraform output)', 'Bash(terraform version*)',
    'Bash(tofu plan -lock=false*)', 'Bash(tofu show*)', 'Bash(tofu validate*)', 'Bash(tofu fmt -check*)',
    'Bash(tofu state list*)', 'Bash(tofu state show *)', 'Bash(tofu providers*)', 'Bash(tofu output)',
    # GitOps
    'Bash(argocd app get *)', 'Bash(argocd app list*)', 'Bash(argocd app diff *)',
    'Bash(argocd app history *)', 'Bash(argocd app manifests *)', 'Bash(argocd version*)',
    'Bash(flux get *)', 'Bash(flux diff *)', 'Bash(flux tree *)', 'Bash(flux stats*)',
    'Bash(flux logs*)', 'Bash(flux check --pre*)', 'Bash(flux version*)',
    # clouds (read verbs; the ones that give secrets are denied below)
    'Bash(aws * describe-*)', 'Bash(aws * list-*)', 'Bash(aws * get-*)', 'Bash(aws s3 ls*)',
    'Bash(aws sts get-caller-identity*)',
    'Bash(az * show*)', 'Bash(az * list*)', 'Bash(az account show*)', 'Bash(az version*)',
    # containers
    'Bash(docker ps*)', 'Bash(docker images*)', 'Bash(docker inspect *)', 'Bash(docker logs *)',
    'Bash(docker version*)',
    # GitHub (look only: `gh api` can write, so it is out)
    'Bash(gh pr view*)', 'Bash(gh pr diff*)', 'Bash(gh pr list*)', 'Bash(gh pr checks*)',
    'Bash(gh run view*)', 'Bash(gh run list*)', 'Bash(gh issue view*)', 'Bash(gh issue list*)',
    'Bash(gh repo view*)',
    # read utilities that Claude Code does not allow by itself in every version
    'Bash(jq *)', 'Bash(rg *)', 'Bash(which *)',
]
# Network diagnostics for read-only profiles that debug (`@net-read`, used by "debug"):
# they look at the link, the routes, DNS and ports without changing anything. `ping` only
# with a count (it never ends otherwise), `nc` only in scan mode (-z: connects and closes
# without sending data), `ip` in its show forms. `curl`/`wget` stay out (they upload and
# write files): those tests are proposed to the user. Their write holes go in READ_DENY.
NET_READ = [
    'Bash(ping -c *)', 'Bash(ping -n -c *)', 'Bash(ping6 -c *)', 'Bash(traceroute *)', 'Bash(tracepath *)',
    'Bash(mtr -r*)', 'Bash(mtr --report*)',
    'Bash(dig *)', 'Bash(nslookup *)', 'Bash(host *)', 'Bash(getent hosts *)', 'Bash(getent ahosts *)',
    'Bash(resolvectl status*)', 'Bash(resolvectl query *)', 'Bash(resolvectl dns)',
    'Bash(ip addr*)', 'Bash(ip a)', 'Bash(ip -br *)', 'Bash(ip route*)', 'Bash(ip r)', 'Bash(ip -6 route*)',
    'Bash(ip link*)', 'Bash(ip neigh*)', 'Bash(ip rule*)',
    'Bash(ss -*)', 'Bash(nc -z*)', 'Bash(nc -vz*)', 'Bash(nc -zv*)', 'Bash(nc -w * -z*)',
    'Bash(openssl s_client *)', 'Bash(openssl x509 -noout *)',
    'Bash(systemctl status *)', 'Bash(systemctl is-active *)', 'Bash(journalctl -u *)', 'Bash(journalctl -n *)',
]
# Verbs that change something in each infra tool. They build the `@infra-writes` set
# (denied by change-infra and document; read-only always denies it).
# Each verb comes in two forms, `prog verb…` and `prog * verb…`, so it cannot slip through
# with a flag first (`kubectl -n prod delete …`), and also with a path (`/usr/bin/kubectl …`).
# In aws/az, moreover, the allowlist's `aws * describe-*` and `az * show*` carry the
# wildcard in the middle, and that wildcard swallows spaces: `az vm delete --name show1`
# matched (tested). It gives some false positives (a filter with "start-" in the value);
# better that than a deletion.
WRITE_VERBS = {
    'kubectl': ['apply', 'create', 'delete', 'edit', 'patch', 'replace', 'scale', 'rollout restart',
                'rollout undo', 'rollout pause', 'rollout resume', 'label', 'annotate', 'taint', 'cordon',
                'uncordon', 'drain', 'set', 'expose', 'run', 'exec', 'cp', 'port-forward', 'proxy',
                'attach', 'debug', 'autoscale', 'certificate', 'config use-context', 'config set',
                'config delete', 'config rename-context', 'config unset', 'plugin'],
    'helm': ['install', 'upgrade', 'uninstall', 'delete', 'rollback', 'push', 'plugin install',
             'registry login'],
    'terraform': ['apply', 'destroy', 'import', 'state rm', 'state mv', 'state push',
                  'state replace-provider', 'taint', 'untaint', 'force-unlock', 'workspace new',
                  'workspace select', 'workspace delete', 'login', 'init -migrate-state', 'init -force-copy'],
    'argocd': ['app sync', 'app delete', 'app set', 'app unset', 'app rollback', 'app create', 'app patch',
               'app terminate-op', 'app actions run', 'app edit', 'proj', 'cluster', 'repo add', 'repo rm',
               'login', 'logout', 'account', 'context'],
    'flux': ['reconcile', 'suspend', 'resume', 'delete', 'create', 'bootstrap', 'install', 'uninstall',
             'push', 'tag'],
    'aws': [f'{v}-' for v in ('delete', 'create', 'put', 'update', 'modify', 'terminate', 'start', 'stop',
                              'reboot', 'run', 'invoke', 'attach', 'detach', 'associate', 'disassociate',
                              'authorize', 'revoke', 'register', 'deregister', 'enable', 'disable', 'tag',
                              'untag', 'add', 'remove', 'set', 'reset', 'restore', 'copy', 'import', 'export',
                              'send', 'publish', 'execute', 'cancel', 'release', 'allocate', 'replace',
                              'upload', 'apply', 'change', 'rotate', 'assume', 'accept', 'reject',
                              'purchase', 'request', 'deploy', 'promote', 'reload', 'restart')]
           + ['invoke', 'configure', 's3 cp', 's3 mv', 's3 rm', 's3 sync', 's3 rb', 's3 mb', 's3 website',
              'deploy', 'ssm start-session', 'ecs execute-command'],
    'az': ['delete', 'create', 'update', 'set', 'add', 'remove', 'start', 'stop', 'restart', 'deallocate',
           'run', 'invoke', 'deploy', 'import', 'export', 'purge', 'reset', 'assign', 'login', 'logout',
           'upload', 'download', 'scale', 'swap', 'attach', 'detach', 'grant', 'revoke', 'regenerate', 'renew',
           'rotate', 'enable', 'disable', 'register', 'unregister', 'cancel', 'approve', 'reject', 'sync',
           'restore', 'failover', 'resize', 'redeploy', 'reimage', 'generalize', 'capture', 'apply',
           'install', 'uninstall', 'upgrade', 'copy', 'move', 'lock', 'unlock', 'tag', 'connect', 'ssh'],
    'docker': ['push', 'rm', 'rmi', 'kill', 'stop', 'system prune', 'volume rm', 'network rm', 'login',
               'exec', 'compose down', 'compose up', 'swarm', 'service', 'stack'],
    'gh': ['workflow run', 'run rerun', 'run cancel', 'secret', 'variable', 'pr close', 'pr comment',
           'pr review', 'pr edit', 'pr ready', 'issue create', 'issue close', 'issue comment', 'issue edit',
           'api', 'repo delete', 'repo edit'],
}
WRITE_VERBS['tofu'] = WRITE_VERBS['terraform']
INFRA_WRITES = [f'Bash({pre}{prog} {sep}{v}*)' for prog, vs in WRITE_VERBS.items() for v in vs
                 for pre in ('', '*/') for sep in ('', '* ')] + [
    'Bash(kubectx*)', 'Bash(kubens*)', 'Bash(*/kubectx*)', 'Bash(*/kubens*)',
    # in auto mode, `sh -c "terraform apply"` and `eval "kubectl delete …"` got through
    # (tested): the rule does not see inside the string. This also blocks wrapping in another shell.
    *[f'Bash({pre}{sh} -c*)' for sh in ('sh', 'bash', 'zsh', 'dash', 'ksh') for pre in ('', '*/')],
    'Bash(eval *)', 'Bash(exec *)']
# What is additionally denied in read-only (deny wins over allow). These are known holes
# in the allowlisted commands: they write a file, run a program or show a secret in
# clear (which would end up in the conversation and in the summaries).
READ_DENY = [
    'Bash(git *--output*)', 'Bash(git *--ext-diff*)', 'Bash(git *-c *)',
    'Bash(kubectl *secret*)', 'Bash(kubectl *--raw*)',
    'Bash(helm *--post-renderer*)', 'Bash(helm *--output-dir*)', 'Bash(helm *--show-secrets*)',
    'Bash(terraform *-lock=true*)', 'Bash(tofu *-lock=true*)', 'Bash(terraform *-out*)', 'Bash(tofu *-out*)', 'Bash(terraform *-json*)', 'Bash(tofu *-json*)',
    'Bash(aws secretsmanager get-secret-value*)', 'Bash(aws * --with-decryption*)',
    'Bash(aws ecr get-login*)', 'Bash(aws eks get-token*)', 'Bash(aws sts get-session-token*)',
    'Bash(aws sts get-federation-token*)', 'Bash(aws * get-*credentials*)', 'Bash(aws * get-*password*)',
    'Bash(aws s3api get-object*)', 'Bash(aws s3 presign*)', 'Bash(aws *--endpoint-url*)',
    'Bash(az keyvault secret show*)', 'Bash(az * keys list*)', 'Bash(az * list-keys*)',
    'Bash(az * get-access-token*)', 'Bash(az aks get-credentials*)', 'Bash(az * list-connection-strings*)',
    'Bash(az * show-connection-string*)', 'Bash(az * credential*)', 'Bash(az * appsettings*)',
    'Bash(az * connection-string*)',
    'Bash(argocd *refresh*)', 'Bash(rg *--pre*)',
    # write holes in @net-read: `ip route add…`, `nc -z -e`, openssl writing files, journald upkeep
    *[f'Bash(ip *{v}*)' for v in (' add ', ' del', ' flush', ' set ', ' change ', ' replace ', ' append ',
                                  ' prepend ', ' exec', ' save', ' restore', ' monitor')],
    'Bash(nc * -e*)', 'Bash(nc * -c *)', 'Bash(nc * -l*)', 'Bash(openssl * -out*)', 'Bash(openssl * -sess_out*)',
    'Bash(openssl * -keylogfile*)', 'Bash(openssl * -msgfile*)', 'Bash(journalctl *--vacuum*)',
    'Bash(journalctl *--rotate*)', 'Bash(journalctl *--flush*)', 'Bash(journalctl *--setup-keys*)',
    'Bash(journalctl *--sync*)', 'Bash(journalctl *--relinquish*)', 'Bash(journalctl * -f*)',
    'Bash(journalctl * --follow*)',
    *INFRA_WRITES,
    # credentials on this PC: neither with Read nor with cat
    'Read(~/.aws/**)', 'Read(~/.azure/**)', 'Read(~/.kube/**)', 'Read(~/.ssh/**)',
    'Read(~/.config/gh/**)', 'Read(~/.docker/config.json)', 'Read(~/.gnupg/**)',
]
# Named sets a profile can use in `allow`/`deny` (e.g. `@infra-writes`): this way
# each profile does not copy the whole list and, if it is tuned here, it is tuned everywhere.
SETS = {'@read': READ_ALLOW, '@net-read': NET_READ, '@infra-writes': INFRA_WRITES}
# The sets a read-only profile may allow
READ_SETS = ('@read', '@net-read')
READ_PROMPT = (
    'This profile is READ-ONLY: you change nothing in the project, the cluster or the cloud. '
    'Only commands that look are allowed (gatito\'s allowlist); everything else is denied '
    'without asking, so do not try workarounds (another shell, variables, xargs, scripts, redirections): '
    'if something needs to write, propose it as a command for the user to run. '
    'Put the verb right after the program (`kubectl get pods -n x`, not `kubectl -n x get pods`) '
    'and, in Terraform, `terraform plan -lock=false …`: it is the only plan form allowed. '
    'Never show secrets in clear (Secret values, tokens, passwords, keys): say where '
    'they are and what kind they are, not their value. You may write your deliverable: in the notebooks, '
    'in artifacts (`{artifact} save`) or in {diagrams}/.')

_cache: dict[Path, tuple[tuple[float, int], dict | None]] = {}
_warned: set[tuple[Path, float, str]] = set()
_lock = threading.Lock()


def _warning(f: Path, mtime: float, msg: str):
    """To the gatitod log, once per file version."""
    if (f, mtime, msg) not in _warned:
        _warned.add((f, mtime, msg))
        print(f'profiles: {f.name}: {msg}', flush=True)


def _bool(v) -> bool | None:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return True if s in ('true', 'yes', 'sí', 'si', '1') else False if s in ('false', 'no', '0', '') else None


def _listing(v) -> list:
    if isinstance(v, list):
        return v
    return [v] if str(v).strip() else []


def _line(v, n: int) -> str:
    return ' '.join(str(v or '').split())[:n]


def is_rule(r: str) -> bool:
    return isinstance(r, str) and bool(RULE_RE.match(r))


def _read_rule_ok(r: str) -> bool:
    """Can a read-only profile allow this? Only a specific `Bash(program …)` or a read tool."""
    m = re.match(r'^(\w+)(?:\((.*)\))?$', r)
    tool, inside = m.group(1), (m.group(2) or '').strip()
    if tool in WRITE:
        return False
    if tool != 'Bash':   # no MCP: an MCP server can write whatever it wants
        return tool in ('Read', 'Grep', 'Glob')
    if not inside or not re.match(r'[A-Za-z/~.]', inside):   # `Bash`, `Bash(*)`…
        return False
    prog = Path(re.split(r'[\s:*]', inside, 1)[0]).name
    return prog not in EJECUTAN


def valid(pid: str, meta: dict, body: str, warn=lambda m: None) -> dict | None:
    """The clean profile, or None if unusable. Doubtful parts are dropped field by field."""
    import core   # here and not at the top: core imports this module
    if not ID_RE.match(pid):
        warn('invalid file name (lowercase letters, numbers and hyphens)')
        return None
    for k in meta:
        if k not in FIELDS:
            warn(f'unknown field "{k}" (ignored)')
    title = _line(meta.get('title'), 60)
    if not title:
        warn('missing "title": profile ignored')
        return None
    only = _bool(meta.get('read_only', False))
    if only is None:
        warn('"read_only" must be true or false: profile ignored (to be safe)')
        return None
    p = {'id': pid, 'title': title, 'description': _line(meta.get('description'), 160),
         'read_only': only, 'model': None, 'mode': None, 'effort': None, 'worktree': False,
         'allow': [], 'deny': [], 'notebooks': [], 'body': body.strip()[:MAX_BODY]}
    if meta.get('model'):
        p['model'] = core.valid_model(str(meta['model']))
        if not p['model']:
            warn(f'invalid model "{meta["model"]}" (ignored)')
    if meta.get('mode'):
        mode = str(meta['mode']).strip()
        if mode in core.MODE_IDS:
            p['mode'] = mode
        else:   # bypassPermissions and anything odd stay out
            warn(f'mode "{mode}" not allowed (ignored)')
    if only:
        p['mode'] = 'dontAsk'
    if meta.get('effort'):
        if meta['effort'] in core.EFFORTS:
            p['effort'] = meta['effort']
        else:
            warn(f'invalid effort "{meta["effort"]}" (ignored)')
    wt = _bool(meta.get('worktree', False))
    p['worktree'] = bool(wt) and not only   # whoever does not write does not need its own copy
    for field in ('allow', 'deny'):
        for r in _listing(meta.get(field, []))[:MAX_RULES]:
            r = str(r).strip()
            if r in SETS:
                if field == 'allow' and only and r not in READ_SETS:
                    warn(f'"{r}" does not fit in a read-only profile (ignored)')
                else:
                    p[field] += [x for x in SETS[r] if x not in p[field]]
            elif not is_rule(r):
                warn(f'invalid rule "{r[:60]}" in "{field}" (ignored)')
            elif field == 'allow' and only and not _read_rule_ok(r):
                warn(f'"{r}" does not fit in a read-only profile (ignored)')
            else:
                p[field].append(r)
    for nb in _listing(meta.get('notebooks', [])):
        if notebooks.ID_RE.match(str(nb)):
            p['notebooks'].append(str(nb))
        else:
            warn(f'invalid notebook "{nb}" (ignored)')
    return p


def _lee(f: Path) -> dict | None:
    st = f.stat()
    signature = (st.st_mtime, st.st_size)
    with _lock:
        hit = _cache.get(f)
        if hit and hit[0] == signature:
            return hit[1]
    p = None
    try:
        meta, body = notebooks.split(f.read_text(encoding='utf-8'))
        if meta:
            p = valid(f.stem, meta, body, lambda m: _warning(f, st.st_mtime, m))
        else:
            _warning(f, st.st_mtime, 'no metadata (frontmatter): profile ignored')
    except Exception as e:   # a broken profile cannot take gatito down
        _warning(f, st.st_mtime, f'cannot read ({type(e).__name__}: {e}): profile ignored')
    with _lock:
        _cache[f] = (signature, p)
    return p


def list_all() -> list[dict]:
    """The valid profiles, by title."""
    if not BASE.is_dir():
        return []
    out = []
    for f in sorted(BASE.glob('*.md')):
        try:
            p = _lee(f)
        except OSError:
            continue
        if p:
            out.append(p)
    return sorted(out, key=lambda p: p['title'].lower())


def get(pid: str | None) -> dict | None:
    if not pid or not ID_RE.match(str(pid)):
        return None
    f = BASE / f'{pid}.md'
    try:
        return _lee(f) if f.is_file() else None
    except OSError:
        return None


def review(f: Path) -> dict:
    """A profile file for the Profiles view: what comes out of validating it, and why.

    No cache and no log: the web UI also shows the profiles that are ignored,
    which would otherwise vanish without anyone knowing why.
    """
    warnings: list[str] = []
    out = {'id': f.stem, 'file': f.name, 'profile': None, 'warnings': warnings, 'text': ''}
    try:
        out['text'] = f.read_text(encoding='utf-8')[:40000]
        meta, body = notebooks.split(out['text'])
        if meta:
            out['profile'] = valid(f.stem, meta, body, warnings.append)
        else:
            warnings.append('no metadata (frontmatter): profile ignored')
    except Exception as e:
        warnings.append(f'cannot read ({type(e).__name__}: {e}): profile ignored')
    return out


def review_all() -> list[dict]:
    """All files in profiles/, valid or not; valid ones first, by title."""
    if not BASE.is_dir():
        return []
    todos = [review(f) for f in sorted(BASE.glob('*.md')) if f.is_file()]
    return sorted(todos, key=lambda r: (r['profile'] is None, (r['profile'] or {}).get('title', r['id']).lower()))


def card(pid: str) -> dict | None:
    """A profile by its id (an invalid one too), or None if there is no file."""
    if not pid or not re.match(r'^[\w.-]{1,80}$', str(pid)):
        return None
    f = BASE / f'{pid}.md'
    return review(f) if f.is_file() and f.resolve().parent == BASE.resolve() else None


def read_only_minimal(pid: str | None = None, title: str | None = None) -> dict:
    """A read-only profile with no text of its own: to continue a session that started
    read-only when its file is gone or is no longer read-only."""
    return {'id': pid or 'read-only', 'title': title or 'Read-only', 'description': '',
            'read_only': True, 'model': None, 'mode': 'dontAsk', 'effort': None,
            'worktree': False, 'allow': [], 'deny': [], 'notebooks': [], 'body': ''}


def public(p: dict) -> dict:
    """What the web UI sees (without the body or the full rules)."""
    return {k: p[k] for k in ('id', 'title', 'description', 'model', 'mode', 'effort',
                              'read_only', 'worktree', 'notebooks')}


def contribution(p: dict, writable: list[str], bin_notebook: str, bin_artifact: str,
           bin_diagram: str, bin_whiteboard: str = '') -> dict:
    """What the profile adds to the agent's flags.

    `writable`: gatito folders where a read-only agent may leave its deliverable
    (notebooks, artifacts, diagrams). Returns the prompt, rules to allow and to deny,
    and the mode (None: whichever is chosen).
    """
    prompt = f'Task profile "{p["title"]}".'
    if p['body']:
        prompt += '\n\n' + p['body']
    allow, deny = list(p['allow']), list(p['deny'])
    if p['read_only']:
        diag = next((d for d in writable if d.rstrip('/').endswith('diagrams')), writable[0] if writable else '')
        prompt += '\n\n' + READ_PROMPT.format(artifact=bin_artifact, diagrams=diag)
        # `//path` is an absolute path in Claude Code rules
        write = [f'{t}(/{d}/**)' for d in writable for t in ('Edit', 'Write')]
        # …but never their .git (a hook would be run by gatitod's autosave) nor their
        # .claude (settings there would grant permissions to the next session in that folder)
        protected = [f'{t}(/{d}/{sub}/**)' for d in writable for t in ('Edit', 'Write')
                     for sub in ('.git', '**/.git', '.claude', '**/.claude')]
        # gatito's tools write only in their folders; `diagram draw` does not:
        # it runs a .py, and that would be a way around to write anywhere
        tools = [f'Bash({bin_notebook} *)', f'Bash({bin_artifact} *)', f'Bash({bin_diagram} icons *)']
        if bin_whiteboard:   # writes only its JSON in state/debug/
            tools.append(f'Bash({bin_whiteboard} *)')
        # a notebook's `repos:` gives the notebook's next session access to those folders:
        # a read-only profile cannot widen it (neither by creating a notebook with --repo nor by editing the cover)
        covers = [f'Bash({bin_notebook} create *)', *[f'{t}(/{d}/*/notebook.md)' for d in writable
                                                      for t in ('Edit', 'Write')]]
        allow = READ_ALLOW + write + tools + allow
        deny = READ_DENY + protected + covers + deny
    nbs = [nb for nb in p['notebooks'] if notebooks.notebook_dir(nb)]
    for nb in nbs:
        prompt += (f'\n\nFirst of all run `{bin_notebook} context {nb}`: the notebook "{nb}" '
                   'holds the standards and decisions of this environment. Search it for what applies '
                   f'(`{bin_notebook} search <topic> --in {nb}`) and check against those notes before '
                   'giving an opinion; if what you see contradicts them, say so and cite the note.')
    return {'prompt': prompt, 'allow': allow, 'deny': deny, 'mode': p['mode'],
            'read_only': p['read_only']}

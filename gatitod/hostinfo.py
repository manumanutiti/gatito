"""What differs between Linux and macOS, in one place.

Stdlib only and valid on Python 3.9 (the one from Xcode's tools on macOS). It is
imported by core, web, push, tls, modlink, notebooks and artifacts; also by the
tools in bin/, sometimes from another Python environment (the diagrams one).

The functions look at `OS` every time they are called: tests change it to simulate
macOS on Linux, and `_sh` is the only place that runs system commands.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
from pathlib import Path

if sys.version_info < (3, 9):
    sys.exit('gatito needs Python 3.9 or newer')

OS = 'mac' if sys.platform == 'darwin' else 'linux'
HOME = Path.home()
# The root is that of the code itself; GATITO_ROOT overrides it (tests with separate state).
ROOT = Path(os.environ.get('GATITO_ROOT') or Path(__file__).resolve().parent.parent)
# Data outside the repo: the same on both systems (short path without spaces; with
# "Application Support" the folder name Claude gives each project would break).
DATA = Path(os.environ.get('GATITO_DATA') or HOME / '.local' / 'share' / 'gatito')
CLAUDE_DIR = Path(os.environ.get('CLAUDE_CONFIG_DIR') or HOME / '.claude')
SOCK_MAX = 100   # sun_path: 104 bytes on macOS, 108 on Linux (with the trailing \0)


def _sh(*cmd: str, timeout: float = 5) -> tuple[int, str]:
    """Run a system command: (code, output). Never raises."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 127, ''


def agents_path(actual: str | None = None) -> str:
    """The PATH claude and its agents run with. Under launchd it arrives almost empty
    (/usr/bin:/bin:/usr/sbin:/sbin): we add where claude, Homebrew and
    gatito's venv usually live, without duplicates and keeping any existing order."""
    parts = (os.environ.get('PATH', '') if actual is None else actual).split(os.pathsep)
    extra = [str(DATA / 'venv' / 'bin'), str(HOME / '.local' / 'bin')]
    if OS == 'mac':
        extra += ['/opt/homebrew/bin', '/opt/homebrew/sbin', '/usr/local/bin']
    extra += ['/usr/local/bin', '/usr/bin', '/bin', '/usr/sbin', '/sbin']
    return os.pathsep.join(dict.fromkeys(p for p in parts + extra if p))


def claude_bin() -> str:
    """The Claude Code executable: GATITO_CLAUDE, the one on PATH or the usual places."""
    candidates = [os.environ.get('GATITO_CLAUDE'), shutil.which('claude', path=agents_path()),
                  str(HOME / '.local' / 'bin' / 'claude'), '/opt/homebrew/bin/claude',
                  '/usr/local/bin/claude']
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return str(HOME / '.local' / 'bin' / 'claude')   # so the error says where it looked


def project_slug(cwd: str) -> str:
    """Name of the ~/.claude/projects folder for a cwd: Claude replaces with "-"
    everything that is not a letter or digit (also spaces and "_", common on macOS)."""
    return re.sub(r'[^A-Za-z0-9]', '-', cwd)


def transcript(sid: str, cwd: str) -> Path | None:
    """The .jsonl of a conversation: in its cwd's folder or, failing that, wherever it is."""
    p = CLAUDE_DIR / 'projects' / project_slug(cwd) / f'{sid}.jsonl'
    if p.exists():
        return p
    try:
        return next((CLAUDE_DIR / 'projects').glob(f'*/{sid}.jsonl'), None)
    except OSError:
        return None


_VPN = ('utun', 'ipsec', 'ppp', 'tun', 'wg', 'tailscale')


def lan_ip(fixed: str | None = None) -> str:
    """This machine's IP on the local network. `fixed` (config.json: lan_ip) takes precedence.

    The UDP socket trick sends nothing: it asks which IP the system would use. With a
    full-tunnel VPN that is the tunnel's, which the phone cannot reach; on macOS the
    wifi or cable one is then looked up (en0, en1)."""
    if fixed:
        return fixed
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('192.168.0.1', 80))
            ip = s.getsockname()[0]
    except OSError:
        ip = '127.0.0.1'
    if OS == 'mac':
        _, relpath = _sh('route', '-n', 'get', '192.168.0.1')
        m = re.search(r'interface:\s*(\S+)', relpath)
        if ip == '127.0.0.1' or (m and m.group(1).startswith(_VPN)):
            for iface in ('en0', 'en1'):
                code, alt = _sh('ipconfig', 'getifaddr', iface)
                if code == 0 and alt:
                    return alt
    return ip


def local_name() -> str:
    """.local name (Bonjour/mDNS) of this machine: it does not change when switching networks."""
    if OS == 'mac':
        code, n = _sh('scutil', '--get', 'LocalHostName')
        if code == 0 and n:
            return f'{n}.local'
    return f'{socket.gethostname().split(".")[0]}.local'


def listen_lan_default() -> bool:
    """Open the local network port (phone) if config.json says nothing?
    Not on macOS: it will probably be a work machine; enable it with "listen_lan": true."""
    return OS != 'mac'


def ssl_ctx(extra: str | None = None) -> ssl.SSLContext:
    """TLS context for reaching the internet (Web Push). Some macOS Pythons do not
    find the system CAs: then /etc/ssl/cert.pem, which macOS ships.
    `extra` (config.json: ca_extra): one more PEM, e.g. a corporate proxy's CA."""
    ctx = ssl.create_default_context()
    relpaths = ssl.get_default_verify_paths()
    if OS == 'mac' and not any(r and os.path.exists(r) for r in (relpaths.cafile, relpaths.capath)) \
            and os.path.exists('/etc/ssl/cert.pem'):
        ctx.load_verify_locations('/etc/ssl/cert.pem')
    if extra:
        ctx.load_verify_locations(os.path.expanduser(extra))
    return ctx


def git_ok() -> bool:
    """Is there a real git? On macOS /usr/bin/git always exists, but without the
    command line tools it is a decoy that opens a dialog."""
    if OS == 'mac' and _sh('xcode-select', '-p')[0] != 0:
        return False
    return bool(shutil.which('git'))


def actions(listing: list[dict]) -> list[dict]:
    """The actions in actions.json that apply on this system (`platforms` field)."""
    return [a for a in listing if OS in (a.get('platforms') or ['linux', 'mac'])]


def sock_path(p: Path) -> Path:
    """Check that a Unix socket path fits in sun_path."""
    if len(str(p).encode()) > SOCK_MAX:
        raise SystemExit(f'The socket path is too long ({len(str(p).encode())} bytes, '
                         f'maximum {SOCK_MAX}): {p}. Install gatito in a shorter path.')
    return p


def private(p: Path, folder: bool = False):
    """Your user only: 0700 for a folder, 0600 for a file."""
    try:
        os.chmod(p, 0o700 if folder else 0o600)
    except OSError:
        pass

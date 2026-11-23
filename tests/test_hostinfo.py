"""hostinfo.py with a simulated macOS (OS forced and fake system commands).

    python3 -m unittest discover -s tests -p 'test_hostinfo.py'
"""
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import env_portability  # noqa: F401  (before que gatitod)
import hostinfo as P

REPO = env_portability.REPO


def fake_sh(answers):
    """_sh that answers by command: {'route': (0, '...'), ...}."""
    def sh(*cmd, timeout=5):
        for key, r in answers.items():
            if ' '.join(cmd).startswith(key):
                return r
        return 127, ''
    return sh


class EnMac(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(P, 'OS', 'mac')
        p.start()
        self.addCleanup(p.stop)


class TestPathYClaude(EnMac):
    def test_path_launchd(self):
        path = P.agents_path('/usr/bin:/bin:/usr/sbin:/sbin').split(os.pathsep)
        self.assertEqual(path[:4], ['/usr/bin', '/bin', '/usr/sbin', '/sbin'])   # keeps what was there
        for d in ('/opt/homebrew/bin', '/usr/local/bin', str(P.DATA / 'venv' / 'bin'),
                  str(P.HOME / '.local' / 'bin')):
            self.assertIn(d, path)
        self.assertEqual(len(path), len(set(path)))

    def test_path_linux_sin_homebrew(self):
        with mock.patch.object(P, 'OS', 'linux'):
            self.assertNotIn('/opt/homebrew/bin', P.agents_path('/usr/bin'))

    def test_claude_por_variable(self):
        with tempfile.TemporaryDirectory() as d:
            c = Path(d) / 'claude'
            c.write_text('#!/bin/sh\n')
            c.chmod(0o755)
            with mock.patch.dict(os.environ, {'GATITO_CLAUDE': str(c)}):
                self.assertEqual(P.claude_bin(), str(c))


class TestConversations(unittest.TestCase):
    def test_slug_como_claude(self):
        # the real names in ~/.claude/projects on Linux
        self.assertEqual(P.project_slug('/home/user/.local/share/gatito/chats'),
                         '-home-user--local-share-gatito-chats')
        self.assertEqual(P.project_slug('/home/user/src/my-project'), '-home-user-src-my-project')
        # macOS: spaces and "_" also become "-"
        self.assertEqual(P.project_slug('/Users/user/Library/Application Support/mi_repo'),
                         '-Users-user-Library-Application-Support-mi-repo')

    def test_transcript_with_fallback(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(P, 'CLAUDE_DIR', Path(d)):
            (Path(d) / 'projects' / 'other-name').mkdir(parents=True)
            f = Path(d) / 'projects' / 'other-name' / 'abc.jsonl'
            f.write_text('{}\n')
            self.assertEqual(P.transcript('abc', '/Users/user/x'), f)
            self.assertIsNone(P.transcript('zzz', '/Users/user/x'))


class FakeSocket:
    def __init__(self, ip):
        self.ip = ip

    def __call__(self, *a):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def connect(self, _):
        pass

    def getsockname(self):
        return self.ip, 0


class TestRed(EnMac):
    def test_fixed_ip_wins(self):
        self.assertEqual(P.lan_ip('10.1.2.3'), '10.1.2.3')

    def test_with_vpn_looks_up_the_wifi(self):
        sh = fake_sh({'route': (0, '   route to: 192.168.0.1\n  interface: utun4\n'),
                       'ipconfig getifaddr en0': (0, '192.168.1.20')})
        with mock.patch.object(P, '_sh', sh), mock.patch.object(socket, 'socket', FakeSocket('10.8.0.2')):
            self.assertEqual(P.lan_ip(), '192.168.1.20')

    def test_without_vpn_the_socket_one(self):
        sh = fake_sh({'route': (0, '  interface: en0\n'), 'ipconfig getifaddr en0': (0, '1.1.1.1')})
        with mock.patch.object(P, '_sh', sh), mock.patch.object(socket, 'socket', FakeSocket('192.168.1.7')):
            self.assertEqual(P.lan_ip(), '192.168.1.7')

    def test_name_bonjour(self):
        with mock.patch.object(P, '_sh', fake_sh({'scutil': (0, 'MacBook-de-Ana')})):
            self.assertEqual(P.local_name(), 'MacBook-de-Ana.local')
        with mock.patch.object(P, '_sh', fake_sh({})), \
                mock.patch.object(socket, 'gethostname', return_value='mbp.corp.example'):
            self.assertEqual(P.local_name(), 'mbp.local')

    def test_lan_off_on_mac(self):
        self.assertFalse(P.listen_lan_default())
        with mock.patch.object(P, 'OS', 'linux'):
            self.assertTrue(P.listen_lan_default())


class TestSystem(EnMac):
    def test_git_sin_xcode(self):
        with mock.patch.object(P, '_sh', fake_sh({'xcode-select': (2, '')})):
            self.assertFalse(P.git_ok())
        with mock.patch.object(P, '_sh', fake_sh({'xcode-select': (0, '/Library/Developer/CommandLineTools')})), \
                mock.patch('shutil.which', return_value='/usr/bin/git'):
            self.assertTrue(P.git_ok())

    def test_actions_by_system(self):
        acts = [{'id': 'a', 'platforms': ['linux']}, {'id': 'b'}, {'id': 'c', 'platforms': ['mac']}]
        self.assertEqual([a['id'] for a in P.actions(acts)], ['b', 'c'])
        with mock.patch.object(P, 'OS', 'linux'):
            self.assertEqual([a['id'] for a in P.actions(acts)], ['a', 'b'])

    def test_socket_long(self):
        self.assertEqual(P.sock_path(Path('/Users/user/gatito/state/gatito.sock')).name, 'gatito.sock')
        with self.assertRaises(SystemExit):
            P.sock_path(Path('/Users/user/' + 'x' * 100 + '/gatito.sock'))

    def test_tls_output_with_macos_cert_pem(self):
        ctx = mock.Mock()
        relpaths = mock.Mock(cafile='/no/exists', capath=None)
        real_exists = os.path.exists
        with mock.patch('ssl.create_default_context', return_value=ctx), \
                mock.patch('ssl.get_default_verify_paths', return_value=relpaths), \
                mock.patch('os.path.exists', side_effect=lambda p: p == '/etc/ssl/cert.pem' or real_exists(p) and p != '/no/exists'):
            self.assertIs(P.ssl_ctx(), ctx)
        ctx.load_verify_locations.assert_called_once_with('/etc/ssl/cert.pem')


class TestTemplates(unittest.TestCase):
    def test_plist_valid(self):
        import plistlib
        from xml.sax.saxutils import escape
        text = (REPO / 'packaging' / 'local.gatito.gatitod.plist.in').read_text()
        values = {'@PY@': '/Users/m/.local/share/gatito/venv/bin/python', '@ROOT@': '/Users/m/gatito',
                   '@HOME@': '/Users/m', '@PATH@': '/Users/m/a&b:/usr/bin', '@LANG@': 'es_ES.UTF-8'}
        for k, v in values.items():
            text = text.replace(k, escape(v))
        d = plistlib.loads(text.encode())
        self.assertEqual(d['Label'], 'local.gatito.gatitod')
        self.assertEqual(d['ProgramArguments'][:2], ['/Users/m/.local/share/gatito/venv/bin/python',
                                                     '/Users/m/gatito/gatitod/web.py'])
        self.assertEqual(d['EnvironmentVariables']['PATH'], '/Users/m/a&b:/usr/bin')
        self.assertEqual(d['SoftResourceLimits']['NumberOfFiles'], 4096)
        self.assertEqual(d['KeepAlive'], {'SuccessfulExit': False})
        self.assertEqual(d['LimitLoadToSessionType'], 'Aqua')
        self.assertNotIn('@', text)

    def test_unit_systemd(self):
        text = (REPO / 'packaging' / 'gatitod.service.in').read_text()
        self.assertIn('ExecStart=@PY@ @ROOT@/gatitod/web.py', text)
        self.assertIn('Environment=PYTHONUTF8=1', text)


class TestWebYRouter(unittest.TestCase):
    def test_listen_lan(self):
        import core
        import web
        with mock.patch.object(P, 'OS', 'mac'), mock.patch.object(core, 'config', return_value={}):
            self.assertFalse(web.listen_lan())
        with mock.patch.object(P, 'OS', 'mac'), mock.patch.object(core, 'config', return_value={'listen_lan': True}):
            self.assertTrue(web.listen_lan())
        with mock.patch.object(P, 'OS', 'linux'), mock.patch.object(core, 'config', return_value={}):
            self.assertTrue(web.listen_lan())

    def test_gsettings_actions_only_on_linux(self):
        import core
        with mock.patch.object(P, 'OS', 'linux'):
            self.assertIn('pin-secondary', [a['id'] for a in core.load_actions()])
        with mock.patch.object(P, 'OS', 'mac'):
            self.assertEqual(core.load_actions(), [])

    def test_dates_like_python39(self):
        import router
        self.assertEqual(router._iso('2026-11-12T09:00:00Z').utcoffset().total_seconds(), 0)
        self.assertEqual(router._iso('2026-11-12T09:00:00.1234567+01:00').microsecond, 123456)
        self.assertEqual(router._iso('2026-11-12T09:00').hour, 9)


try:
    import tls as _tls  # necesita cryptography
except ImportError:
    _tls = None


@unittest.skipIf(_tls is None, 'sin cryptography')
class TestCA(unittest.TestCase):
    def test_ca_new_limited(self):
        from cryptography import x509
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.multiple(_tls, DIR=Path(d), CA_KEY=Path(d) / 'ca.key', CA_CRT=Path(d) / 'ca.crt',
                                    KEY=Path(d) / 's.key', CRT=Path(d) / 's.crt'), \
                mock.patch.object(socket, 'gethostname', return_value='laptop'), \
                mock.patch.object(P, 'local_name', return_value='MacBook.local'):
            _tls.ensure(['192.168.1.20', '8.8.8.8'])
            ca = x509.load_pem_x509_certificate((Path(d) / 'ca.crt').read_bytes())
            ext = ca.extensions.get_extension_for_class(x509.NameConstraints)
            self.assertTrue(ext.critical)
            srv = x509.load_pem_x509_certificate((Path(d) / 's.crt').read_bytes())
            san = srv.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            self.assertEqual(sorted(san.get_values_for_type(x509.DNSName)),
                             ['MacBook.local', 'laptop.local', 'localhost'])   # bare "laptop" is left out
            self.assertEqual(sorted(str(i) for i in san.get_values_for_type(x509.IPAddress)),
                             ['127.0.0.1', '192.168.1.20'])                       # the public one is left out

    def test_old_ca_without_limits_does_not_filter(self):
        ca = mock.Mock()
        ca.extensions.get_extension_for_class.side_effect = __import__('cryptography').x509.ExtensionNotFound('x', None)
        self.assertEqual(_tls._inside(ca, ['8.8.8.8'], ['pc']), (['8.8.8.8'], ['pc']))


@unittest.skipIf(_tls is None, 'sin cryptography')
class TestLaptopNetwork(unittest.TestCase):
    def test_push_sub_configurable(self):
        import base64
        import json
        import core
        import push
        with tempfile.TemporaryDirectory() as d, mock.patch.object(push, 'VAPID', Path(d) / 'v.pem'), \
                mock.patch.object(push, 'DIR', Path(d)), \
                mock.patch.object(core, 'config', return_value={'push_sub': 'mailto:yo@example.org'}):
            jwt = push._vapid_header('https://web.push.apple.com/abc').split()[1][2:].rstrip(',')
            body = jwt.split('.')[1]
            claims = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
            self.assertEqual(claims['sub'], 'mailto:yo@example.org')
            self.assertEqual(claims['aud'], 'https://web.push.apple.com')

    def test_ip_change_remakes_certificate(self):
        import ssl
        import core
        import web
        from cryptography import x509
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.multiple(_tls, DIR=Path(d), CA_KEY=Path(d) / 'ca.key', CA_CRT=Path(d) / 'ca.crt',
                                    KEY=Path(d) / 's.key', CRT=Path(d) / 's.crt'), \
                mock.patch.dict(web.LAN, {'ip': None, 'url': None, 'ctx': ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)}):
            for ip in ('192.168.1.20', '10.0.5.7'):   # home and office
                web._pon_lan(ip)
                crt = x509.load_pem_x509_certificate((Path(d) / 's.crt').read_bytes())
                san = crt.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
                self.assertIn(ip, [str(i) for i in san.get_values_for_type(x509.IPAddress)])
                self.assertIn(f'://{ip}:', web.LAN['url'])
                f = core.STATE / 'pair-url'
                self.assertEqual(f.read_text(), web.LAN['url'])
                self.assertEqual(f.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()

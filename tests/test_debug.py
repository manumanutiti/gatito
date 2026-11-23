"""Debug mode: the profile, the whiteboard template and the notes a session cites."""
import shutil
import unittest
from unittest import mock

import env
import core
import notebooks
import debug
import profiles
import web


class Debug(unittest.TestCase):
    def setUp(self):
        self.d = env.TMP / 'notebooks' / 'infra'
        shutil.rmtree(self.d, ignore_errors=True)
        notebooks.create('Infra', nb='infra')
        notebooks._index['ts'] = 0

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_profile_valid_and_read_only(self):
        p = profiles.get('debug')
        self.assertIsNotNone(p)
        self.assertTrue(p['read_only'])
        self.assertEqual((p['mode'], p['model'], p['effort'], p['notebooks']), ('dontAsk', 'opus', 'medium', []))
        f = core._agent_flags('auto', None, None, p)
        self.assertEqual(f[f.index('--permission-mode') + 1], 'dontAsk')
        allowed = f[f.index('--allowedTools') + 1:f.index('--disallowedTools')]
        denied = f[f.index('--disallowedTools') + 1:]
        # draws the whiteboard and runs network diagnostics on its own…
        self.assertIn(f'Bash({core.BIN_WHITEBOARD} *)', allowed)
        for r in ('Bash(ping -c *)', 'Bash(dig *)', 'Bash(ip route*)', 'Bash(nc -zv*)', 'Bash(resolvectl status*)'):
            self.assertIn(r, allowed)
        # …without being able to change paths or open ports, and without curl
        for r in ('Bash(ip * add *)', 'Bash(ip * del*)', 'Bash(nc * -l*)', 'Bash(nc * -e*)'):
            self.assertIn(r, denied)
        self.assertFalse(any('curl' in r for r in allowed))
        # no lee notebooks al start: gasta tokens
        self.assertNotIn('notebook context', f[f.index('--append-system-prompt') + 1])
        self.assertIn('whiteboard symptom', f[f.index('--append-system-prompt') + 1])

    def test_net_read_only_in_read_only_profiles_or_with_set(self):
        p = profiles.valid('x', {'title': 'X', 'read_only': True, 'allow': ['@net-read']}, '')
        self.assertIn('Bash(traceroute *)', p['allow'])
        self.assertEqual(profiles.NET_READ, [r for r in profiles.NET_READ if profiles._read_rule_ok(r)])

    def test_template_has_the_sections_in_order(self):
        r = notebooks.create_note('infra', 'debugging', '2026-11-12 · pod en CrashLoop', 'debugging',
                                 session='sid-a')
        text = (self.d / r['relpath']).read_text()
        pos = [text.index(f'\n## {s}\n') for s in notebooks.WHITEBOARD_SECTIONS]
        self.assertEqual(pos, sorted(pos))
        self.assertEqual(text.count('\n## '), len(notebooks.WHITEBOARD_SECTIONS))
        for c in ('ok', 'fails', 'suspect', 'unchecked'):
            self.assertIn(f'classDef {c} ', text)
        self.assertIn('```mermaid\nflowchart', text)
        self.assertTrue(r['relpath'].startswith('debugging/2026-'), 'dated, like a journal')
        self.assertEqual(notebooks.info(self.d / r['relpath'])['kind'], 'debugging')

    def test_notes_of_the_session_and_no_others(self):
        pz = notebooks.create_note('infra', 'debugging', 'Whiteboard', 'debugging', session='sid-a')['relpath']
        note = notebooks.create_note('infra', 'runbooks', 'Runbook', 'runbook', session='sid-a')['relpath']
        notebooks.create_note('infra', 'debugging', 'Other', 'debugging', session='sid-b')
        notebooks.create_note('infra', '', 'Sin session', 'note')
        notebooks._index['ts'] = 0
        r = web._ses_notes({'sid': 'sid-a'})
        self.assertEqual([n['relpath'] for n in r], [pz, note], 'the whiteboard first; nothing from other sessions')
        self.assertEqual([n['whiteboard'] for n in r], [True, False])
        self.assertEqual(web._ses_notes({'sid': 'no-exists'}), [])
        self.assertEqual(web._ses_notes({}), [])
        # several ids of the same session (resuming may change it), without repeating notes
        r = web._ses_notes({'sid': 'sid-a,sid-b,sid-a'})
        self.assertEqual(len(r), 3)

    def test_index_sees_new_notes(self):
        self.assertEqual(notebooks.session_notes('sid-c'), [])
        notebooks.create_note('infra', 'debugging', 'New', 'debugging', session='sid-c')
        notebooks._index['ts'] = 0   # skip the index cache window
        self.assertEqual(len(notebooks.session_notes('sid-c')), 1)



class Whiteboard(unittest.TestCase):
    """The live whiteboard: one JSON per session that changes line by line."""
    def setUp(self):
        shutil.rmtree(debug.DIR, ignore_errors=True)
        core.store.write(core.PROFILE_SESSIONS, {})

    def new(self, pid='sid-1'):
        with debug.changes(pid, create=True) as d:
            debug.symptom(d, 'api.internal does not resolve', 'the ingress IP')
        return pid

    def test_symptom_comes_first(self):
        with self.assertRaises(debug.Error):
            with debug.changes('sid-x') as d:
                debug.probe(d, 'dns', 'ok', 'dig x', 'ok')

    def test_probes_paint_their_piece_and_record_where(self):
        pid = self.new()
        with debug.changes(pid) as d:
            debug.piece(d, 'usual', 'vpn', 'VPN con split-DNS')
            debug.piece(d, 'modules', 'l3', 'IP', layer='L3')
            debug.next_step(d, 'dig api.internal', 'see what it returns', 'dns')
            debug.probe(d, 'l3', 'ok', 'ping -c3 8.8.8.8', '0% loss')
            debug.probe(d, 'dns', 'fails', 'dig api.internal', 'NXDOMAIN', where='you@bastion', output='status: NXDOMAIN')
            debug.probe(d, 'vpn', 'info', 'Are you on the VPN?', 'yes')
        d = debug.read(pid)
        est = {p['id']: p['status'] for p in d['usual'] + d['modules']}
        self.assertEqual(est, {'vpn': 'unchecked', 'l3': 'ok', 'dns': 'fails'}, 'info no changes el status')
        self.assertEqual([m['id'] for m in d['modules']], ['l3', 'dns'], 'a new piece joins the path')
        self.assertEqual([t['n'] for t in d['probes']], [1, 2, 3])
        self.assertTrue(d['probes'][0]['where'].startswith('agent@'))
        self.assertEqual(d['probes'][1]['where'], 'you@bastion')
        self.assertIsNone(d['next_step'], 'the pending step was done')
        with debug.changes(pid) as d:
            with self.assertRaises(debug.Error):
                debug.piece(d, 'modules', 'vpn', 'other')   # already a cause
            with self.assertRaises(debug.Error):
                debug.status(d, 'l3', 'verde')
            debug.piece(d, 'modules', 'l2', 'Link', before='l3')
            debug.close(d, 'The VPN does not push the internal DNS', 'reconnect the VPN')
        d = debug.read(pid)
        self.assertEqual([m['id'] for m in d['modules']], ['l2', 'l3', 'dns'])
        self.assertEqual(d['status'], 'solved')
        self.assertIn('✗dns', debug.text(d))

    def test_resume_keeps_the_same_whiteboard(self):
        pid = self.new('sid-1')
        core.remember_profile({'profile': 'debug', 'title': 'Debug', 'read_only': True}, 'job1', 'sid-1')
        calls = []
        with mock.patch.object(core.subprocess, 'run', lambda cmd, **k: calls.append(cmd) or env.Process('abcd1234')):
            core.resume_session('sid-1', None, 'stays')
        self.assertEqual(core.profile_for('abcd1234')['whiteboard'], pid)
        self.assertEqual(debug.root('abcd1234', 'sid-2'), pid)
        # the web asks for it with the ids of the new session
        r = web._debug({'ids': 'abcd1234,sid-2'})
        self.assertEqual(r['whiteboard']['symptom'], 'api.internal does not resolve')
        self.assertEqual(web._debug({'ids': 'abcd1234', 'm': str(r['whiteboard']['mtime'])}), {'ok': True, 'same': True})
        self.assertEqual(web._debug({'ids': 'nothing'}), {'ok': True, 'whiteboard': None})
        self.assertEqual(web._debug({}), {'ok': True, 'whiteboard': None})

    def test_unlinked_session_adopts_the_open_whiteboard(self):
        self.new('sid-1')
        self.assertIsNone(debug.root('sid-9'))
        self.assertEqual(debug.adopt('sid-9'), 'sid-1')
        self.assertEqual(debug.root('sid-9'), 'sid-1')
        with debug.changes('sid-1') as d:
            debug.close(d, 'x')
        self.assertIsNone(debug.adopt('sid-8'), 'a closed one is not adopted')

    def test_odd_ids_stay_in_the_folder(self):
        for mal in ('../x', 'a/b', '', '.alias'):
            with self.assertRaises(debug.Error):
                debug.relpath(mal)
        self.assertIsNone(debug.read('../../etc'))


if __name__ == '__main__':
    unittest.main()

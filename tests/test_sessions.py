"""The profile is remembered per session and applied again on resume or reply."""
import json
import tempfile
import unittest
from unittest import mock

import env
from env import Process
import core
import profiles


def mode(cmd):
    return cmd[cmd.index('--permission-mode') + 1]


class Sessions(unittest.TestCase):
    def setUp(self):
        core.PROFILE_SESSIONS.unlink(missing_ok=True)
        self.dir = tempfile.mkdtemp(dir=env.TMP)
        self.cmds = []

    def run_fake(self, output='launched abcd1234\n'):
        def run(cmd, **kw):
            self.cmds.append(cmd)
            return Process(output if '--bg' in cmd else '')
        return mock.patch.object(core.subprocess, 'run', side_effect=run)

    def test_launch_records_the_profile(self):
        with self.run_fake():
            r = core.launch_agent(self.dir, 'mira esto', None, 'n', 'auto', None, None, 'review')
        self.assertTrue(r['ok'])
        cmd = self.cmds[-1]
        self.assertEqual(mode(cmd), 'dontAsk', 'the chosen mode does not lift a read-only profile')
        self.assertEqual(cmd[cmd.index('--model') + 1], 'opus', 'no chosen model: the profile one')
        self.assertNotIn('--worktree', cmd)
        self.assertEqual(cmd[-2:], ['--', 'mira esto'])
        self.assertEqual(core.profile_for('abcd1234'),
                         {'profile': 'review', 'title': 'Review', 'read_only': True})

    def test_missing_profile_does_not_launch(self):
        with self.run_fake():
            r = core.launch_agent(self.dir, 'x', profile='no-exists')
        self.assertFalse(r['ok'])
        self.assertEqual(self.cmds, [])

    def test_resume_keeps_the_profile(self):
        core.remember_profile(core.profile_info(profiles.get('review')), 'abcd1234')
        with self.run_fake('ok ef012345\n'):
            r = core.resume_session('sid-1', self.dir, 'stays', 'sonnet', 'auto', None, 'n',
                                    keys=('abcd1234',))
        self.assertTrue(r['ok'])
        cmd = self.cmds[-1]
        self.assertEqual(mode(cmd), 'dontAsk')
        self.assertIn('Bash(kubectl get *)', cmd)
        # the new job and the sessionId are recorded: next time too
        self.assertEqual(core.profile_for('ef012345')['profile'], 'review')
        self.assertEqual(core.profile_for('sid-1')['profile'], 'review')

    def test_answer_keeps_the_profile(self):
        core.remember_profile(core.profile_info(profiles.get('security')), 'abcd1234')
        ag = {'id': 'abcd1234', 'key': 'abcd1234', 'sessionId': 'sid-2', 'cwd': self.dir, 'model': 'opus',
              'mode': 'dontAsk', 'effort': 'high', 'name': 'n', 'live': None, 'ui': 'done'}
        with mock.patch.object(core, 'list_agents', return_value=[ag]), self.run_fake('ok 99998888\n'), \
                mock.patch.object(core, 'set_hidden'):
            r = core.reply_agent('abcd1234', 'sid-2', 'now delete everything', None, 'acceptEdits', None)
        self.assertTrue(r['ok'])
        resume = next(c for c in self.cmds if '--resume' in c)
        self.assertEqual(mode(resume), 'dontAsk', 'asking for another mode does not take the session out of read-only')
        self.assertIn('Task profile "Security"', resume[resume.index('--append-system-prompt') + 1])

    def test_history_by_session_id(self):
        # list_agents links the sessionId as soon as it sees it; from History only that one is known
        core.remember_profile(core.profile_info(profiles.get('diagnosis')), 'abcd1234')
        agents = [{'id': 'abcd1234', 'sessionId': 'sid-3', 'kind': 'background', 'state': 'done'}]
        with mock.patch.object(core.subprocess, 'run', return_value=Process(json.dumps(agents))):
            a = core._list_agents(True)[0]
        self.assertEqual((a['profile'], a['profileTitle'], a['readOnly']), ('diagnosis', 'Diagnosis', True))
        with self.run_fake('ok 11112222\n'):
            core.resume_session('sid-3', self.dir, 'stays')
        self.assertEqual(mode(self.cmds[-1]), 'dontAsk')

    def test_deleted_profile_stays_read_only(self):
        f = env.profile('t-temporal', '---\ntitle: Temporal\nread_only: true\n---\nText.\n')
        p = profiles.get('t-temporal')
        core.remember_profile(core.profile_info(p), 'abcd1234')
        f.unlink()
        with self.run_fake('ok 33334444\n'):
            core.resume_session('sid-4', self.dir, 'stays', mode='auto', keys=('abcd1234',))
        cmd = self.cmds[-1]
        self.assertEqual(mode(cmd), 'dontAsk')
        self.assertIn('Bash(git log*)', cmd)

    def test_without_profile_nothing_changes(self):
        with self.run_fake():
            core.launch_agent(self.dir, 'x', 'haiku', mode='plan')
        self.assertEqual(mode(self.cmds[-1]), 'plan')
        self.assertNotIn('--allowedTools', self.cmds[-1])
        self.assertIsNone(core.profile_for('abcd1234'))


if __name__ == '__main__':
    unittest.main()

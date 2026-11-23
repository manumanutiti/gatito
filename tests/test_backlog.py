"""The backlog saves each task's profile and launches it with it."""
import tempfile
import unittest
from unittest import mock

import env
from env import Process
import backlog
import core


class Backlog(unittest.TestCase):
    def setUp(self):
        backlog.FILE.unlink(missing_ok=True)
        self.dir = tempfile.mkdtemp(dir=env.TMP)
        proj = {'id': 'infra', 'path': self.dir, 'desc': '', 'aliases': []}
        self.parches = [mock.patch.object(core, 'get_project', return_value=proj),
                        mock.patch.object(backlog, '_notify')]
        for p in self.parches:
            p.start()

    def tearDown(self):
        for p in self.parches:
            p.stop()

    def test_save_with_profile(self):
        r = backlog.add({'task': 'review la rama', 'project_id': 'infra', 'trigger': 'manual',
                         'profile': 'review', 'mode': 'auto'})
        self.assertTrue(r['ok'], r)
        i = r['item']
        self.assertEqual((i['profile'], i['mode'], i['model'], i['effort'], i['worktree']),
                         ('review', 'dontAsk', 'opus', 'high', False))
        self.assertEqual(backlog.list_items()[0]['profile'], 'review')

    def test_choice_wins_except_mode_when_read_only(self):
        i = backlog.add({'task': 'x', 'project_id': 'infra', 'trigger': 'manual', 'profile': 'change-infra',
                         'model': 'haiku', 'mode': 'plan', 'worktree': False})['item']
        self.assertEqual((i['model'], i['mode'], i['worktree']), ('haiku', 'plan', False))
        i = backlog.add({'task': 'x', 'project_id': 'infra', 'trigger': 'manual', 'profile': 'change-infra'})['item']
        self.assertTrue(i['worktree'], 'without saying anything, the profile worktree')

    def test_unknown_profile(self):
        r = backlog.add({'task': 'x', 'project_id': 'infra', 'trigger': 'manual', 'profile': 'no-exists'})
        self.assertFalse(r['ok'])
        self.assertIn('profile', r['err'])

    def test_edit_removes_or_changes_the_profile(self):
        i = backlog.add({'task': 'x', 'project_id': 'infra', 'trigger': 'manual', 'profile': 'review'})['item']
        r = backlog.update(i['id'], {'profile': None, 'mode': 'auto'})
        self.assertTrue(r['ok'])
        self.assertEqual((r['item']['profile'], r['item']['mode']), (None, 'auto'))

    def test_launch_with_its_profile(self):
        i = backlog.add({'task': 'check the cluster', 'project_id': 'infra', 'trigger': 'manual',
                         'profile': 'diagnosis'})['item']
        cmds = []

        def run(cmd, **kw):
            cmds.append(cmd)
            return Process('launched 5555aaaa\n')
        with mock.patch.object(core.subprocess, 'run', side_effect=run):
            r = backlog.run_now(i['id'])
        self.assertTrue(r['ok'], r)
        cmd = cmds[-1]
        self.assertEqual(cmd[cmd.index('--permission-mode') + 1], 'dontAsk')
        self.assertIn('Task profile "Diagnosis"', cmd[cmd.index('--append-system-prompt') + 1])
        self.assertEqual(core.profile_for('5555aaaa')['profile'], 'diagnosis')
        self.assertEqual(backlog.list_items(include_launched=True)[0]['status'], 'launched')

    def test_scheduled_whose_profile_disappears_fails(self):
        f = env.profile('t-ephemeral', '---\ntitle: Ephemeral\nread_only: true\n---\n')
        i = backlog.add({'task': 'x', 'project_id': 'infra', 'trigger': 'manual', 'profile': 't-ephemeral'})['item']
        f.unlink()
        with mock.patch.object(core.subprocess, 'run') as run:
            r = backlog.run_now(i['id'])
        run.assert_not_called()
        self.assertFalse(r['ok'])
        self.assertEqual(backlog.list_items()[0]['status'], 'failed')


if __name__ == '__main__':
    unittest.main()

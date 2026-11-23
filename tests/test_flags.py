"""What a profile adds to the agent command line (core._agent_flags)."""
import shutil
import unittest

import env
import core
import profiles


def options(flags, name):
    """The values of a variadic flag: up to the next one starting with --."""
    if name not in flags:
        return []
    out = []
    for x in flags[flags.index(name) + 1:]:
        if x.startswith('--'):
            break
        out.append(x)
    return out


def prompt(flags):
    return flags[flags.index('--append-system-prompt') + 1]


MALICIOUS = {   # a profile that skips validation: the fields are untrusted data
    'id': 'bad', 'title': 'Bad', 'description': '', 'read_only': False, 'model': '--x',
    'mode': 'bypassPermissions', 'effort': '--dangerously-skip-permissions', 'worktree': False,
    'allow': ['--dangerously-skip-permissions', 'Bash(ls)', '-p', 'Bash(x)\n--y'],
    'deny': ['--permission-mode', 'bypassPermissions'], 'notebooks': ['../../etc'], 'body': 'hello'}


class Flags(unittest.TestCase):
    def todos(self):
        return [None, *profiles.list_all(), MALICIOUS, profiles.read_only_minimal()]

    def test_always_deny_tools_and_safety(self):
        for p in self.todos():
            for mode in (None, 'auto', 'bypassPermissions', 'plan'):
                f = core._agent_flags(mode, None, None, p)
                denied = options(f, '--disallowedTools')
                for r in core.DENY_TOOLS:
                    self.assertIn(r, denied, (p and p['id'], mode))
                self.assertIn(core.SAFETY_PROMPT, prompt(f))

    def test_never_bypass_nor_smuggled_flags(self):
        for p in self.todos():
            for mode in (None, 'auto', 'bypassPermissions', '--dangerously-skip-permissions'):
                f = core._agent_flags(mode, '--x', None, p)
                # (a `bypassPermissions` in deny is just a rule denying a tool
                # that does not exist: harmless; what matters is that it is never the mode)
                self.assertNotIn('--dangerously-skip-permissions', f)
                self.assertNotIn('--allow-dangerously-skip-permissions', f)
                self.assertIn(f[f.index('--permission-mode') + 1], core.MODE_IDS)
                self.assertEqual(f.count('--permission-mode'), 1)
                for flag in ('--allowedTools', '--disallowedTools'):
                    for r in options(f, flag):
                        self.assertTrue(profiles.is_rule(r), r)
                        self.assertFalse(r.startswith('-'), r)
                # the message goes after `--`, added by the caller: no loose `--` here
                self.assertNotIn('--', f)

    def test_malicious_filtered(self):
        f = core._agent_flags(None, None, None, MALICIOUS)
        self.assertEqual(f[f.index('--permission-mode') + 1], core.DEFAULT_MODE)
        self.assertEqual(options(f, '--allowedTools'), ['Bash(ls)'])
        self.assertNotIn('--effort', f)

    def test_read_only_imposes_dontask(self):
        rev = profiles.get('review')
        for mode in (None, 'auto', 'acceptEdits', 'manual', 'bypassPermissions'):
            f = core._agent_flags(mode, None, None, rev)
            self.assertEqual(f[f.index('--permission-mode') + 1], 'dontAsk', mode)
        allowed = options(f, '--allowedTools')
        self.assertIn('Bash(kubectl get *)', allowed)
        self.assertIn(f'Write(/{core.ARTIFACTS}/**)', allowed, 'can leave su report')
        self.assertFalse(any(r in ('Bash', 'Edit', 'Write') for r in allowed))
        self.assertFalse(any(r.startswith(('Edit(', 'Write(')) and str(core.NOTEBOOKS) not in r
                             and str(core.ARTIFACTS) not in r and str(core.DIAGRAMS) not in r for r in allowed),
                         'only writes in the gatito folders')
        denied = options(f, '--disallowedTools')
        self.assertIn('Bash(terraform apply*)', denied)
        # plan only without taking the state lock; and another session cannot widen its access
        self.assertIn('Bash(terraform plan -lock=false*)', allowed)
        self.assertFalse([r for r in allowed if r.startswith('Bash(terraform plan') and 'lock=false' not in r])
        self.assertIn('Bash(terraform *-lock=true*)', denied)
        self.assertIn(f'Bash({core.BIN_NOTEBOOK} create *)', denied)
        self.assertIn(f'Write(/{core.NOTEBOOKS}/*/notebook.md)', denied)
        self.assertIn(f'Edit(/{core.NOTEBOOKS}/.git/**)', denied)
        self.assertIn('Task profile "Review"', prompt(f))
        self.assertIn('READ-ONLY', prompt(f))

    def test_profile_mode_and_effort_and_choice_wins(self):
        change = profiles.get('change-infra')
        f = core._agent_flags(None, None, None, change)
        self.assertEqual(f[f.index('--permission-mode') + 1], 'acceptEdits')
        self.assertEqual(f[f.index('--effort') + 1], 'high')
        f = core._agent_flags('auto', 'low', None, change)
        self.assertEqual(f[f.index('--permission-mode') + 1], 'auto')
        self.assertEqual(f[f.index('--effort') + 1], 'low')
        self.assertIn('Bash(helm * upgrade*)', options(f, '--disallowedTools'))

    def test_without_profile_as_before(self):
        f = core._agent_flags('plan', 'max', None)
        self.assertEqual(f[:4], ['--permission-mode', 'plan', '--effort', 'max'])
        self.assertNotIn('--allowedTools', f)
        self.assertEqual(options(f, '--disallowedTools'), core.DENY_TOOLS)

    def test_notebooks_only_if_exist(self):
        rev = profiles.get('review')
        self.assertNotIn('context infra', prompt(core._agent_flags(None, None, None, rev)))
        d = env.TMP / 'notebooks' / 'infra'
        d.mkdir()
        try:
            self.assertIn(f'{core.BIN_NOTEBOOK} context infra', prompt(core._agent_flags(None, None, None, rev)))
        finally:
            shutil.rmtree(d)
        self.assertNotIn('etc', prompt(core._agent_flags(None, None, None, MALICIOUS)).split('hello')[-1])


if __name__ == '__main__':
    unittest.main()

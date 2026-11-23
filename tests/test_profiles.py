"""Read y validation de profiles (profiles/*.md)."""
import os
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

import env  # noqa: F401  (relpaths temporales before de import_line gatitod)
import profiles


def lee(name, text):
    env.profile(name, text)
    with redirect_stdout(StringIO()) as log:
        p = profiles.get(name)
    return p, log.getvalue()


class RepoProfiles(unittest.TestCase):
    def test_all_valid(self):
        with mock.patch.object(profiles, 'BASE', env.REPO / 'profiles'), redirect_stdout(StringIO()) as log:
            ps = {p['id']: p for p in profiles.list_all()}
        self.assertEqual(set(ps), {'review', 'security', 'diagnosis', 'change-infra', 'document', 'debug'})
        self.assertEqual(log.getvalue(), '', 'no warning when reading the repo profiles')
        for pid in ('review', 'security', 'diagnosis', 'debug'):
            self.assertTrue(ps[pid]['read_only'], pid)
            self.assertEqual(ps[pid]['mode'], 'dontAsk')
        self.assertFalse(ps['change-infra']['read_only'])
        self.assertTrue(ps['change-infra']['worktree'])
        for p in ps.values():
            n = len(p['body'].splitlines())
            self.assertTrue(15 <= n <= 40, f'{p["id"]}: {n} lines de body')
            self.assertTrue(p['description'])


class Validation(unittest.TestCase):
    def test_fields(self):
        p, log = lee('t-ok', '---\ntitle: Probe\ndescription: Una  line\nmodel: haiku\nmode: plan\n'
                             'effort: low\nread_only: false\nworktree: true\nnotebooks: [infra, other]\n'
                             'allow:\n  - Bash(stern *)\ndeny: [Bash(kubectl delete *)]\n---\nHaz things.\n')
        self.assertEqual(log, '')
        self.assertEqual((p['title'], p['description'], p['model'], p['mode'], p['effort']),
                         ('Probe', 'Una line', 'haiku', 'plan', 'low'))
        self.assertEqual(p['allow'], ['Bash(stern *)'])
        self.assertEqual(p['deny'], ['Bash(kubectl delete *)'])
        self.assertEqual(p['notebooks'], ['infra', 'other'])
        self.assertTrue(p['worktree'])
        self.assertEqual(p['body'], 'Haz things.')

    def test_without_title_or_without_frontmatter_is_ignored(self):
        p, log = lee('t-untitled', '---\ndescription: x\n---\nbody')
        self.assertIsNone(p)
        self.assertIn('title', log)
        p, log = lee('t-nometa', 'only text')
        self.assertIsNone(p)
        self.assertNotIn('t-nometa', [x['id'] for x in profiles.list_all()])

    def test_broken_file_breaks_nothing(self):
        f = env.TMP / 'profiles' / 't-binary.md'
        f.write_bytes(b'---\ntitle: \xff\xfe\x00\n---\n')
        with redirect_stdout(StringIO()):
            self.assertIsNone(profiles.get('t-binary'))
            profiles.list_all()   # no launch

    def test_read_only_doubtful_is_ignored(self):
        p, _ = lee('t-doubtful', '---\ntitle: X\nread_only: maybe\n---\n')
        self.assertIsNone(p, 'when in doubt, better not to offer a profile that could write')

    def test_bypass_and_odd_modes_out(self):
        for mode in ('bypassPermissions', '--dangerously-skip-permissions', 'auto --x'):
            p, log = lee('t-mode', f'---\ntitle: X\nmode: "{mode}"\n---\n')
            self.assertIsNone(p['mode'], mode)
            self.assertIn('not allowed', log)

    def test_invalid_model_and_effort(self):
        p, _ = lee('t-model', '---\ntitle: X\nmodel: "--model x"\neffort: infinite\n---\n')
        self.assertIsNone(p['model'])
        self.assertIsNone(p['effort'])

    def test_rules_that_look_like_flags_out(self):
        p, log = lee('t-rules', '---\ntitle: X\nallow:\n  - "--dangerously-skip-permissions"\n'
                                 '  - "-p"\n  - "Bash(ls) --x"\n  - "(something)"\n  - Bash(stern *)\n'
                                 'deny: ["--allowedTools", "Bash(rm *)"]\n---\n')
        self.assertEqual(p['allow'], ['Bash(stern *)'])
        self.assertEqual(p['deny'], ['Bash(rm *)'])
        self.assertIn('invalid rule', log)

    def test_rule_with_line_break(self):
        self.assertFalse(profiles.is_rule('Bash(ls)\n--dangerously-skip-permissions'))
        self.assertFalse(profiles.is_rule('Bash(ls\x00)'))
        self.assertTrue(profiles.is_rule('Bash(git log *)'))

    def test_read_only_cannot_allow_write(self):
        p, log = lee('t-ro', '---\ntitle: X\nread_only: true\nworktree: true\nmode: auto\nallow:\n'
                             '  - Bash\n  - Bash(*)\n  - Edit\n  - Write(/tmp/**)\n  - Bash(python3 *)\n'
                             '  - Bash(sh -c *)\n  - mcp__github__create_pr\n  - "@infra-writes"\n'
                             '  - Bash(stern *)\n  - Read\n---\n')
        self.assertEqual(p['allow'], ['Bash(stern *)', 'Read'])
        self.assertEqual(p['mode'], 'dontAsk', 'read-only means mode is always dontAsk')
        self.assertFalse(p['worktree'])
        self.assertIn('read-only', log)

    def test_sets(self):
        p, _ = lee('t-conj', '---\ntitle: X\nallow: ["@read"]\ndeny: ["@infra-writes", "@no-exists"]\n---\n')
        self.assertIn('Bash(kubectl get *)', p['allow'])
        self.assertIn('Bash(terraform apply*)', p['deny'])
        self.assertIn('Bash(kubectl * delete*)', p['deny'])
        self.assertTrue(all(profiles.is_rule(r) for r in p['allow'] + p['deny']))

    def test_id_from_file(self):
        self.assertIsNone(profiles.get('../etc/passwd'))
        self.assertIsNone(profiles.get('Mayus'))
        env.profile('Bad_Name', '---\ntitle: X\n---\n')
        with redirect_stdout(StringIO()):
            self.assertNotIn('Bad_Name', [p['id'] for p in profiles.list_all()])

    def test_edit_without_restart(self):
        f = env.profile('t-changes', '---\ntitle: Before\n---\n')
        self.assertEqual(profiles.get('t-changes')['title'], 'Before')
        f.write_text('---\ntitle: After del change\n---\n')
        os.utime(f, (time.time() + 5, time.time() + 5))   # in case the disk clock is coarse
        self.assertEqual(profiles.get('t-changes')['title'], 'After del change')
        f.unlink()
        self.assertIsNone(profiles.get('t-changes'))


class ViewProfiles(unittest.TestCase):
    """What the Profiles view shows: also the ignored files, with the reason."""

    def test_invalid_comes_with_reason(self):
        env.profile('t-broken', '---\ndescription: no title\n---\nText')
        with redirect_stdout(StringIO()) as log:
            r = profiles.card('t-broken')
            todos = {x['id']: x for x in profiles.review_all()}
        self.assertIsNone(r['profile'])
        self.assertTrue(any('title' in a for a in r['warnings']))
        self.assertIn('t-broken', todos)
        self.assertIsNone(todos['t-broken']['profile'])
        self.assertEqual(log.getvalue(), '', 'the view does not pollute the log')
        os.remove(env.TMP / 'profiles' / 't-broken.md')

    def test_valid_with_warnings(self):
        env.profile('t-warning', '---\ntitle: Warning\nread_only: true\nallow: [Bash(rm *)]\n---\nHello')
        r = profiles.card('t-warning')
        self.assertEqual(r['profile']['title'], 'Warning')
        self.assertEqual(r['profile']['allow'], [])
        self.assertTrue(any('rm' in a for a in r['warnings']))
        self.assertIn('Hello', r['text'])
        os.remove(env.TMP / 'profiles' / 't-warning.md')

    def test_odd_ids(self):
        for pid in ('', '../core', '../../etc/passwd', 'no-exists', 'a/b'):
            self.assertIsNone(profiles.card(pid), pid)


if __name__ == '__main__':
    unittest.main()

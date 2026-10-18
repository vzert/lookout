"""0.13.25: the findings of round 2 of the adversarial review of 0.13.23 (Sonnet and codex break, 2026-10-18).

- `xargs -I{} pkill {}` passed: the subshell scanner turns `{}` into a separator, so xargs and pkill fell apart.
- `env -S "pkill -f claude"`, `env -P /usr/bin pkill …` and `coproc pkill …` passed; so did the less common wrappers of
  the notes (setsid, ionice, chrt, doas, watch, find -exec).
- A falsy command that is not text (None, [], 0, False) passed as an empty command.
- ramas_destino returned nothing when origin/HEAD points at a branch that is gone, though origin/main exists.
Run: python3 -m unittest tests/test_lookout_01325.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_lookout_01318 import FrenoProcesosTest  # noqa: E402
from test_lookout_01322 import YaArribaTest  # noqa: E402
import test_lookout_f3 as f3  # noqa: E402

import retiro  # noqa: E402


class Ronda2Test(FrenoProcesosTest):
    def test_round_2_forms_are_denied(self):
        for cmd in ('cat l | xargs -I{} pkill {}', 'cat l | xargs -I {} pkill {}', 'cat l | xargs -I{} pkill -f {}',
                    'env -S "pkill -f claude"', 'env --split-string="pkill -f claude"', 'env -P /usr/bin pkill -f claude',
                    'coproc pkill -f claude', 'setsid pkill -f claude', 'ionice -c 3 pkill -f claude',
                    'chrt -f 99 pkill -f claude', 'doas -u root pkill claude', 'watch -n 1 pkill -f claude',
                    'find . -name x -exec pkill -f claude \\;', 'find . -execdir kill -9 -1 +'):
            self.assertEqual(self.handle(cmd)[0], "deny", cmd)

    def test_narrow_forms_still_pass(self):
        for cmd in ('cat l | xargs -I{} echo {}', 'find . -name "*.pyc" -exec rm {} \\;', 'env -S "make test"',
                    'setsid pkill -f run-tests', 'watch -n 5 git status', 'pgrep -f mutation-check | xargs kill',
                    'git log --format="%(refname)" {} ', 'ls {a,b}'):
            self.assertEqual(self.handle(cmd)[0], None, cmd)

    def test_a_falsy_command_that_is_not_text_is_denied(self):
        for valor in (None, [], 0, False, {}):
            self.assertEqual(self.handle(valor)[0], "deny", repr(valor))
        self.assertEqual(self.handle("")[0], None)


class CabezaColgadaTest(YaArribaTest):
    def test_a_stale_remote_head_falls_back_to_main(self):
        rama = self.rama()
        f3.git(self.repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/ya-no-existe")
        f3.git(self.repo, "branch", "--unset-upstream")  # only the remote's main branch can name origin/<rama>
        self.assertIn("origin/" + rama, retiro.ramas_destino(self.repo))


def load_tests(loader, tests, pattern):
    out = unittest.TestSuite()
    for cls in (Ronda2Test, CabezaColgadaTest):
        out.addTests(cls(n) for n in cls.__dict__ if n.startswith("test_"))
    return out


if __name__ == "__main__":
    unittest.main()

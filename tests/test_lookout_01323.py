"""0.13.23: the findings of the adversarial review of 0.13.18 and 0.13.22 (codex, 2026-10-18).

- The pkill brake missed a kill behind a wrapper (`timeout 5 pkill -f claude`, `nice -n 10 …`, `env -i …`) or a shell
  keyword (`then`, `do`), `xargs` and `eval` (the last ones from the Sonnet review). Now it looks through them.
- A command the brake cannot read (not text, or an error inside it) passed, because main() turns any exception into
  "no output". Now the brake denies it.
- 0.13.22 took a patch on ANY remote ref as upstream: the same patch on an unrelated branch let a tab close with the
  commit only on that branch. Now only the remote's main branch and the agent's upstream count.
- The «copia rebasada» block told the supervisor to ask the user, and the supervisa skill did not say how. Now it does.
Run: python3 -m unittest tests/test_lookout_01323.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_lookout_01318 import FrenoProcesosTest  # noqa: E402
from test_lookout_01322 import YaArribaTest, git_out  # noqa: E402

import permisos  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class EnvoltoriosTest(FrenoProcesosTest):
    def test_wrappers_and_keywords_are_looked_through(self):
        for cmd in ('timeout 5 pkill -f claude', 'timeout -s KILL 5 pkill claude', 'timeout --foreground 5s pkill claude',
                    'nice -n 10 pkill -f claude', 'nice -5 pkill claude', 'nohup nice pkill claude',
                    'env -i pkill -f claude', 'env -u HOME pkill claude', 'env -i A=1 pkill -f claude',
                    'if true; then pkill -f claude; fi', 'for i in 1; do pkill -f claude; done',
                    'while true; do pkill -f "x" -n; done', 'xargs -a lista pkill claude',
                    'echo claude | xargs pkill -f', 'echo x | xargs -I{} pkill -f claude', 'eval "pkill -f claude"',
                    'eval pkill -f claude', 'timeout 5 kill -9 -1', 'stdbuf -oL pkill -f claude',
                    'cat pids | xargs kill -9'):
            self.assertEqual(self.handle(cmd)[0], "deny", cmd)

    def test_narrow_kills_behind_wrappers_still_pass(self):
        for cmd in ('timeout 5 pkill -f run-tests', 'nice -n 5 make test', 'env -i pkill -f mutation-check',
                    'if true; then echo pkill; fi', 'xargs -a lista echo'):
            self.assertEqual(self.handle(cmd)[0], None, cmd)

    def test_a_command_it_cannot_read_is_denied(self):
        decision, why = self.handle(["pkill", "-f", "claude"])
        self.assertEqual(decision, "deny")
        self.assertIn("no pude leer", why)
        saved = permisos.mata_procesos
        permisos.mata_procesos = lambda c: 1 / 0
        try:
            self.assertEqual(self.handle("pkill -f run-tests")[0], "deny")
        finally:
            permisos.mata_procesos = saved


class RamaAjenaTest(YaArribaTest):
    def test_the_same_patch_on_an_unrelated_branch_still_blocks(self):
        self.commit_de("s1")
        self.sube_copia(git_out(self.repo, "rev-parse", "HEAD"), mismo_parche=True, destino="otra")
        ok, msg = self.cierra()
        self.assertFalse(ok, msg)
        self.assertIn("suyo(s) sin subir", msg)


class SkillCopiaRebasadaTest(unittest.TestCase):
    def test_the_skill_says_what_to_do_with_a_rebased_copy(self):
        with open(os.path.join(ROOT, "plugins", "lookout", "skills", "supervisa", "SKILL.md"), encoding="utf-8") as fh:
            skill = fh.read()
        self.assertIn("copia rebasada", skill)
        i = skill.index("copia rebasada")
        cerca = skill[i - 200:i + 900]
        self.assertIn("lookout decision", cerca)
        self.assertIn("--si-es", cerca)
        self.assertIn("git range-diff", cerca)


def load_tests(loader, tests, pattern):
    # only this file's cases: the inherited ones already run in their own files
    out = unittest.TestSuite()
    for cls in (EnvoltoriosTest, RamaAjenaTest, SkillCopiaRebasadaTest):
        out.addTests(cls(n) for n in cls.__dict__ if n.startswith("test_"))
    return out


if __name__ == "__main__":
    unittest.main()

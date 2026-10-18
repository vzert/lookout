"""0.13.22: `cierra-pestana` does not blame an agent for commits that are already upstream, and names where the ones it
blocks on come from.

Live case (3-tier, 2026-10-17 17:05): `cierra-pestana pendientes-sin-id` said «6 commit(s) suyo(s) sin subir» in the
shared checkout. They were the 2.58.1 commits that the agent's first session (900f49bf, 2026-10-14, before its current
task) left on the old branch reopen-replay-ts; their content had reached main through a rebased PR (#24): `git cherry`
marks 3 as already upstream and the other 3 have a rebased copy with the same subject and author. Now a commit whose
patch is in any remote ref does not count; one with a rebased copy is named as such with both hashes, not as the
agent's; and a commit of an earlier session of its chain says which session and when.
Run: python3 -m unittest tests/test_lookout_01322.py
"""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f3 as f3  # noqa: E402
from test_lookout_0130 import CierraPestanaTest  # noqa: E402

import registry  # noqa: E402


def git_out(repo, *args, env=None):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True, check=True,
                          env=dict(os.environ, **(env or {}))).stdout.strip()


class YaArribaTest(CierraPestanaTest):
    def rama(self):
        return git_out(self.repo, "rev-parse", "--abbrev-ref", "HEAD")

    def sube_copia(self, local, mismo_parche, destino=None):
        """Push to origin's branch (0.13.23: its main branch unless `destino`), by another route, a copy of `local`: same
        patch (cherry-pick) or same subject and author with another patch (a rebase that resolved a conflict)."""
        rama = self.rama()
        f3.git(self.repo, "checkout", "-q", "-b", "tmp", "origin/" + rama)
        env = {"GIT_COMMITTER_DATE": "2030-01-01T00:00:00"}
        if mismo_parche:
            git_out(self.repo, "cherry-pick", local, env=env)
        else:
            with open(os.path.join(self.repo, "b.txt"), "w") as fh:
                fh.write("b rebasado\n")
            f3.git(self.repo, "add", "b.txt")
            git_out(self.repo, "commit", "-q", "-m", "b", env=env)
        destino = destino or rama
        f3.git(self.repo, "push", "-q", "origin", "tmp:refs/heads/" + destino)
        f3.git(self.repo, "checkout", "-q", rama)
        f3.git(self.repo, "branch", "-q", "-D", "tmp")
        return git_out(self.repo, "rev-parse", "origin/" + destino)

    def test_a_commit_whose_patch_is_upstream_does_not_block(self):
        self.commit_de("s1")
        self.sube_copia(git_out(self.repo, "rev-parse", "HEAD"), mismo_parche=True)
        ok, msg = self.cierra()
        self.assertTrue(ok, msg)

    def test_a_rebased_copy_is_named_and_not_called_its_own(self):
        self.commit_de("s1")
        local = git_out(self.repo, "rev-parse", "--short", "HEAD")
        remoto = self.sube_copia(local, mismo_parche=False)
        ok, msg = self.cierra()
        self.assertFalse(ok, msg)
        self.assertNotIn("suyo(s)", msg)
        self.assertIn("copia rebasada", msg)
        self.assertIn(local, msg)
        self.assertIn(remoto[:7], msg)
        self.assertIn("git range-diff", msg)

    def test_an_earlier_session_of_its_chain_is_named_with_its_date(self):
        self.agent("s0", nombre="sidebar~s0", tarea="", cwd=self.repo, worktree=self.repo, tarea_estado="relevada",
                   relevada_por="s1")
        reg = registry.load(self.pid)
        reg["agents"]["s1"]["relevo_de"] = "s0"
        registry.save(self.pid, reg)
        self.commit_de("s0")
        ok, msg = self.cierra()
        self.assertFalse(ok, msg)
        self.assertIn("1 commit(s) suyo(s) sin subir", msg)  # its chain's work to push (0.13.2)
        self.assertIn("hechos por su sesión anterior s0", msg)
        self.assertRegex(msg, r"\d{4}-\d{2}-\d{2}")

    def test_its_own_commit_still_says_its_own(self):
        self.commit_de("s1")
        ok, msg = self.cierra()
        self.assertFalse(ok, msg)
        self.assertIn("suyo(s) sin subir", msg)


def load_tests(loader, tests, pattern):
    # only this file's cases: the inherited ones already run in test_lookout_0130
    return unittest.TestSuite(YaArribaTest(n) for n in YaArribaTest.__dict__ if n.startswith("test_"))


if __name__ == "__main__":
    unittest.main()

"""0.13.38 (p-588bbc52e4): a publication checked again does not keep the reason of its earlier refusal or expiry.
Run: python3 -m unittest tests/test_lookout_01338.py

3-tier-memory, 2026-10-18: PR #40 sat in publicaciones.json as `pr-abierto` with «su HEAD cambió después de
verificarla», although its head c684302 was the PR's. `pide` reuses the agent's caducada or rechazada entry and never
dropped its `motivo`; `--hecho` carried it into pr-abierto or publicada.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f3 as f3  # noqa: E402
import test_lookout_01327 as t27  # noqa: E402

import publica  # noqa: E402

git = f3.git


def commit(e, nombre):
    with open(os.path.join(e["worktree"], nombre), "w") as fh:
        fh.write("x\n")
    git(e["worktree"], "add", "-A")
    git(e["worktree"], "commit", "-qm", nombre)


class PrMotivoTest(t27.PrModeCase):
    def test_a_pr_checked_again_after_expiring_opens_without_the_old_reason(self):
        a = self.worktree("uno", "sa")
        ok, code, lines = self.ask(a)
        self.assertEqual(code, "LISTA", lines)
        commit(a, "fix.txt")                                     # the agent commits after the check
        publica.concilia(self.pid)
        self.assertEqual(self.me(a)["estado"], "caducada")
        self.assertIn("HEAD cambió", self.me(a)["motivo"])
        ok, code, lines = self.ask(a)
        self.assertEqual(code, "LISTA", lines)
        self.assertNotIn("HEAD cambió", self.me(a).get("motivo") or "")
        self.push_rama(a)
        self.gh.pr(40, a["branch"], self.head(a))
        ok, lines = publica.hecho(self.pid, a, pr=40)
        self.assertTrue(ok, lines)
        p = self.me(a)
        self.assertEqual((p["estado"], p["head"]), (publica.ABIERTO, self.head(a)))
        self.assertNotIn("HEAD cambió", p.get("motivo") or "")


class DirectoMotivoTest(f3.GitCase):
    def me(self, e):
        return next(p for p in publica.load(self.pid)["cola"] if p["session_id"] == e["session_id"])

    def test_a_refused_check_then_a_good_one_is_lista_and_publicada_without_the_refusal(self):
        a = self.worktree("uno", "sa")
        with open(os.path.join(a["worktree"], "uno.txt"), "a") as fh:
            fh.write("sin commit\n")
        ok, code, _ = self.ask(a)
        self.assertEqual((self.me(a)["estado"], self.me(a)["motivo"]), ("rechazada", "SUCIO"))
        git(a["worktree"], "checkout", "--", "uno.txt")
        ok, code, lines = self.ask(a)
        self.assertEqual(code, "LISTA", lines)
        self.assertNotIn("motivo", self.me(a))
        git(a["worktree"], "push", "-q", "origin", "HEAD:main")
        ok, lines = publica.hecho(self.pid, a)
        self.assertTrue(ok, lines)
        self.assertEqual(self.me(a)["estado"], "publicada")
        self.assertNotIn("motivo", self.me(a))

    def test_an_expired_lista_asked_again_keeps_no_expiry_reason(self):
        a = self.worktree("uno", "sa")
        self.assertEqual(self.ask(a)[1], "LISTA")
        commit(a, "fix.txt")
        publica.concilia(self.pid)
        self.assertEqual(self.me(a)["estado"], "caducada")
        ok, code, lines = self.ask(a)
        self.assertEqual(code, "LISTA", lines)
        self.assertNotIn("motivo", self.me(a))


if __name__ == "__main__":
    unittest.main()

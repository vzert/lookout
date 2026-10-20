"""0.13.41 (p-0da4c4704f): a PR opened outside lookout gets its place in the queue.
Run: python3 -m unittest tests/test_lookout_01341_pr.py

3-tier-memory, 2026-10-19: «Prompts repetidos» pushed and opened PR #50 from its pane, outside lookout; `--hecho --pr 50`
answered «no tiene una publicación lista en la cola», so the merge order, the out-of-order warning, `--fusiona` and the
merged/closed reading never saw it. Now `--hecho --pr N` with no lista publication reads the PR with gh and queues it
as pr-abierto, last in the merge order, marked as not verified by lookout; what lookout can read of its head (the
version, private paths) goes in as a warning, never as a block.
"""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f3 as f3  # noqa: E402
import test_lookout_01327 as t27  # noqa: E402

import decisiones  # noqa: E402
import publica  # noqa: E402

git = f3.git


class PrExternoCase(t27.PrModeCase):
    def externo(self, e, n, state="OPEN"):
        """The agent pushed its branch and opened PR n by itself; lookout never checked it."""
        self.push_rama(e)
        self.gh.pr(n, e["branch"], self.head(e), state=state)

    def cola(self):
        return publica.load(self.pid)["cola"]

    def de_pr(self, n):
        return [p for p in self.cola() if p.get("pr") == n]


class RegistraTest(PrExternoCase):
    def test_hecho_pr_with_no_lista_queues_the_pr_last_and_unverified(self):
        a = self.worktree("uno", "sa", version="0.2.0")
        b = self.worktree("dos", "sb", version="0.3.0")
        self.abierto(a, 7)
        self.externo(b, 8)
        ok, lines = publica.hecho(self.pid, b, pr=8)
        self.assertTrue(ok, lines)
        text = "\n".join(lines)
        self.assertIn("#8", text)
        self.assertIn("fuera de lookout", text)
        self.assertIn("2º", text)
        p, = self.de_pr(8)
        self.assertEqual((p["estado"], p["rama_remota"], p["head"], p["rama_base"]),
                         (publica.ABIERTO, b["branch"], self.head(b), "main"))
        self.assertTrue(p["fuera_de_lookout"])
        self.assertEqual(p["version"], "0.3.0")
        self.assertEqual([q["pr"] for q in publica.abiertos(publica.load(self.pid))], [7, 8])
        self.assertIn("fuera de lookout", publica.render_cola(self.pid))

    def test_it_is_conciled_merged_and_closed_like_any_open_pr(self):
        a = self.worktree("uno", "sa")
        self.externo(a, 9)
        self.assertTrue(publica.hecho(self.pid, a, pr=9)[0])
        self.gh.prs[9]["state"] = "MERGED"
        publica.concilia(self.pid, ahora=10 ** 10)
        self.assertEqual(self.de_pr(9)[0]["estado"], "publicada")
        b = self.worktree("dos", "sb", version="0.3.0")
        self.externo(b, 10)
        self.assertTrue(publica.hecho(self.pid, b, pr=10)[0])
        self.gh.prs[10]["state"] = "CLOSED"
        publica.concilia(self.pid, ahora=10 ** 10)
        self.assertEqual(self.de_pr(10)[0]["estado"], "caducada")

    def test_fusiona_with_the_users_yes_says_lookout_never_checked_it(self):
        a = self.worktree("uno", "sa")
        self.externo(a, 11)
        self.assertTrue(publica.hecho(self.pid, a, pr=11)[0])
        d = decisiones.abre(self.pid, "¿Fusiono el PR #11?", si_es="Fusionar", notificar=False)
        q = "¿Fusiono el PR #11? (%s)" % d["id"]
        decisiones.registra_pregunta(self.pid, "toolu_f", [q])
        decisiones.registra_respuesta(self.pid, "toolu_f", "Fusionar", por_pregunta={q: "Fusionar"})
        ok, code, lines = publica.fusiona(self.pid, 11, d["id"])
        self.assertEqual(code, "FUSIONADA", lines)
        self.assertIn("fuera de lookout", "\n".join(lines))

    def test_an_already_merged_pr_is_publicada(self):
        a = self.worktree("uno", "sa")
        self.externo(a, 12, state="MERGED")
        ok, lines = publica.hecho(self.pid, a, pr=12)
        self.assertTrue(ok, lines)
        self.assertEqual(self.de_pr(12)[0]["estado"], "publicada")

    def test_a_head_lookout_cannot_read_has_no_version_and_says_so(self):
        a = self.worktree("uno", "sa")
        self.externo(a, 13)
        self.gh.prs[13]["headRefOid"] = "e" * 40
        ok, lines = publica.hecho(self.pid, a, pr=13)
        self.assertTrue(ok, lines)
        self.assertEqual(self.de_pr(13)[0]["version"], "")
        self.assertIn("no está en el árbol", "\n".join(lines))


class WorktreeTest(PrExternoCase):
    """Opus r3: the real PR #50 came from an agent registered on the main checkout that worked in a worktree of its
    own (`publica --worktree`, as SKILL.md describes); `--hecho --pr N --worktree <ruta>` names that tree."""
    def agente_en_main(self):
        e = self.agent("sm", nombre="tres", tarea="p-tres", worktree=self.repo, cwd=self.repo, base="origin/main",
                       branch="main")
        wt = self.repo + "-wt-propio"
        git(self.repo, "worktree", "add", "-q", "-b", "guard-propio", wt, "origin/main")
        with open(os.path.join(wt, "tres.txt"), "w") as fh:
            fh.write("x\n")
        git(wt, "add", "-A")
        git(wt, "commit", "-qm", "tres")
        git(wt, "push", "-q", "origin", "HEAD:refs/heads/guard-propio")
        _, head = publica.git(wt, "rev-parse", "HEAD")
        self.gh.pr(50, "guard-propio", head.strip())
        return e, wt

    def test_without_worktree_the_no_names_the_flag(self):
        e, wt = self.agente_en_main()
        ok, lines = publica.hecho(self.pid, e, pr=50)
        self.assertFalse(ok)
        self.assertIn("--worktree", lines[0])

    def test_with_its_worktree_the_pr_is_queued(self):
        e, wt = self.agente_en_main()
        ok, lines = publica.hecho(self.pid, e, pr=50, worktree=wt)
        self.assertTrue(ok, lines)
        p, = self.de_pr(50)
        self.assertEqual((p["estado"], p["worktree"], p["rama_remota"]), (publica.ABIERTO, wt, "guard-propio"))

    def test_the_cli_validates_and_passes_the_worktree(self):
        import argparse
        import io
        from contextlib import redirect_stdout
        import test_lookout_f10 as f10
        e, wt = self.agente_en_main()
        cli = f10.load_cli("lookout_cli_01341_pr")
        cli.project = lambda _p: (self.pid, os.path.join(self.repo, ".git"))
        ns = dict(proyecto="/x", agente="tres", cola=False, hecho=True, retira=False, worktree=wt, modo="", pr=50,
                  fusiona=0, decision="", fuera_de_orden=False)
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.cmd_publica(argparse.Namespace(**ns))
        self.assertEqual(rc, 0, out.getvalue())
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.cmd_publica(argparse.Namespace(**dict(ns, pr=51, worktree="/no/existe")))
        self.assertEqual(rc, 5, out.getvalue())


class AvisaTest(PrExternoCase):
    def test_private_paths_are_a_warning_not_a_block(self):
        a = self.worktree("uno", "sa", extra="/Users/alguien/x")
        self.externo(a, 14)
        ok, lines = publica.hecho(self.pid, a, pr=14)
        self.assertTrue(ok, lines)
        self.assertIn("rutas privadas", "\n".join(lines))

    def test_a_version_out_of_order_is_a_warning(self):
        a = self.worktree("uno", "sa", version="0.3.0")
        b = self.worktree("dos", "sb", version="0.2.0")
        self.abierto(a, 15)
        self.externo(b, 16)
        ok, lines = publica.hecho(self.pid, b, pr=16)
        self.assertTrue(ok, lines)
        self.assertIn("0.3.0", "\n".join(lines))
        self.assertIn("orden", "\n".join(lines))


    def test_a_version_not_above_main_is_a_warning(self):
        a = self.worktree("uno", "sa", version="0.1.0")
        with open(os.path.join(a["worktree"], "CHANGELOG.md"), "a") as fh:
            fh.write("- más\n")
        git(a["worktree"], "commit", "-qam", "changelog")
        self.externo(a, 22)
        ok, lines = publica.hecho(self.pid, a, pr=22)
        self.assertTrue(ok, lines)
        self.assertIn("por encima de la de origin", "\n".join(lines))


class NoRegistraTest(PrExternoCase):
    def test_direct_mode_is_still_a_no(self):
        publica.pon_modo(self.pid, "directo")
        a = self.worktree("uno", "sa")
        self.externo(a, 17)
        self.assertFalse(publica.hecho(self.pid, a, pr=17)[0])

    def test_without_a_pr_number_is_still_a_no(self):
        a = self.worktree("uno", "sa")
        ok, lines = publica.hecho(self.pid, a)
        self.assertFalse(ok)
        self.assertIn("lista", lines[0])

    def test_a_closed_pr_is_not_queued(self):
        a = self.worktree("uno", "sa")
        self.externo(a, 18, state="CLOSED")
        self.assertFalse(publica.hecho(self.pid, a, pr=18)[0])
        self.assertEqual(self.de_pr(18), [])

    def test_gh_failing_is_a_no(self):
        a = self.worktree("uno", "sa")
        self.externo(a, 19)
        self.gh.falla = True
        self.assertFalse(publica.hecho(self.pid, a, pr=19)[0])
        self.assertEqual(self.de_pr(19), [])

    def test_a_pr_already_in_the_queue_is_not_queued_twice(self):
        a = self.worktree("uno", "sa")
        self.abierto(a, 20)
        b = self.worktree("dos", "sb", version="0.3.0")
        ok, lines = publica.hecho(self.pid, b, pr=20)
        self.assertFalse(ok)
        self.assertEqual(len(self.de_pr(20)), 1)

    def test_another_agents_pr_is_a_no(self):
        # Sonnet r1: worktrees share one object store, so «the head is in the tree» does not say whose PR it is
        a = self.worktree("uno", "sa")
        b = self.worktree("dos", "sb", version="0.3.0")
        self.externo(b, 23)
        ok, lines = publica.hecho(self.pid, a, pr=23)
        self.assertFalse(ok, lines)
        self.assertIn("no es de uno", lines[0])
        self.assertEqual(self.de_pr(23), [])

    def test_another_agents_merged_pr_is_a_no_even_when_main_has_it(self):
        # Sonnet r2: a merged PR's head is in main, and an agent in sync with main has it in its history
        a = self.worktree("uno", "sa", version=None)
        b = self.worktree("dos", "sb", version="0.3.0")
        self.externo(b, 25, state="MERGED")
        git(b["worktree"], "push", "-q", "origin", "HEAD:main")
        git(a["worktree"], "fetch", "-q", "origin")
        git(a["worktree"], "-c", "user.name=a", "-c", "user.email=a@a", "merge", "-q", "--no-edit", "origin/main")
        ok, lines = publica.hecho(self.pid, a, pr=25)
        self.assertFalse(ok, lines)
        self.assertEqual(self.de_pr(25), [])

    def test_another_agents_merged_pr_is_a_no_when_main_was_not_fetched(self):
        # Opus r3: with origin's tip unknown here the history test failed open
        a = self.worktree("uno", "sa", version=None)
        b = self.worktree("dos", "sb", version="0.3.0")
        self.externo(b, 26, state="MERGED")
        git(b["worktree"], "push", "-q", "origin", "HEAD:main")
        git(a["worktree"], "fetch", "-q", "origin")
        git(a["worktree"], "-c", "user.name=a", "-c", "user.email=a@a", "merge", "-q", "--no-edit", "origin/main")
        otro = os.path.join(self.tmp.name, "clon-sin-fetch")             # origin moves on; nobody here fetches it
        subprocess.run(["git", "clone", "-q", self.origin, otro], check=True)
        git(otro, "-c", "user.name=o", "-c", "user.email=o@o", "commit", "-q", "--allow-empty", "-m", "mas")
        git(otro, "push", "-q", "origin", "HEAD:main")
        self.assertFalse(publica.hecho(self.pid, a, pr=26)[0])
        self.assertEqual(self.de_pr(26), [])

    def test_a_pr_pushed_under_another_branch_name_is_a_no_that_says_why(self):
        a = self.worktree("uno", "sa")
        git(a["worktree"], "push", "-q", "origin", "HEAD:refs/heads/otro-nombre")
        self.gh.pr(27, "otro-nombre", self.head(a))
        ok, lines = publica.hecho(self.pid, a, pr=27)
        self.assertFalse(ok)
        self.assertIn("--worktree", lines[0])

    def test_a_pr_of_an_older_commit_of_the_agents_branch_is_its_own(self):
        a = self.worktree("uno", "sa")
        self.externo(a, 24)
        git(a["worktree"], "commit", "-q", "--allow-empty", "-m", "después")
        self.assertTrue(publica.hecho(self.pid, a, pr=24)[0])

    def test_a_pr_to_another_base_is_a_no(self):
        a = self.worktree("uno", "sa")
        self.externo(a, 21)
        self.gh.prs[21]["baseRefName"] = "release"
        self.assertFalse(publica.hecho(self.pid, a, pr=21)[0])
        self.assertEqual(self.de_pr(21), [])


if __name__ == "__main__":
    unittest.main()

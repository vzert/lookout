"""0.13.27: `lookout publica` in PR mode (p-ca286da56c) and the merge the user authorizes in the supervisor's window.
Run: python3 -m unittest tests/test_lookout_01327.py

3-tier-memory, 2026-10-17/18: the project works with a branch and a PR per agent and the user merges. `publica` said
LISTA with `git push origin HEAD:main`, `--hecho` said NO after a branch push + PR (#39, #42), the publications expired
before the merge and supervisor.md said «cola: vacía» with 5 PRs open.
"""
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f3 as f3  # noqa: E402
import test_lookout_f10 as f10  # noqa: E402

import decisiones  # noqa: E402
import gobierno  # noqa: E402
import lote  # noqa: E402
import publica  # noqa: E402
import registry  # noqa: E402
import supervisor_md  # noqa: E402

git = f3.git


class FakeGh:
    """`gh` with PRs in memory: view/merge read and change them; every call is recorded."""

    def __init__(self):
        self.prs = {}
        self.calls = []
        self.falla = False

    def pr(self, n, rama, head, state="OPEN", checks=("SUCCESS",), mergeable="MERGEABLE", status="CLEAN"):
        self.prs[n] = {"number": n, "state": state, "headRefName": rama, "headRefOid": head, "baseRefName": "main",
                       "mergeable": mergeable, "mergeStateStatus": status,
                       "statusCheckRollup": [{"name": "ci", "status": "COMPLETED", "conclusion": c} for c in checks],
                       "mergeCommit": None, "url": "https://example.invalid/pull/%d" % n}

    def __call__(self, args, cwd):
        self.calls.append(list(args))
        if self.falla:
            return 1, ""
        if args[:2] == ["pr", "view"]:
            p = self.prs.get(int(args[2]))
            return (0, json.dumps(p)) if p else (1, "")
        if args[:2] == ["pr", "merge"]:
            p = self.prs[int(args[2])]
            p.update(state="MERGED", mergeCommit={"oid": "f" * 40})
            return 0, ""
        return 1, ""

    def merges(self):
        return [c for c in self.calls if c[:2] == ["pr", "merge"]]


class PrModeCase(f3.GitCase):
    def setUp(self):
        super().setUp()
        self.gh = FakeGh()
        real = publica.gh
        self.addCleanup(setattr, publica, "gh", real)
        publica.gh = self.gh
        publica.pon_modo(self.pid, "pr")

    def avanza_main(self, version="", nombre="otro"):
        """origin/main moves on (another PR merged); the agents' worktrees fetch it."""
        otro = os.path.join(self.tmp.name, "clon-" + nombre)
        subprocess.run(["git", "clone", "-q", self.origin, otro], check=True)
        with open(os.path.join(otro, nombre + ".txt"), "w") as fh:
            fh.write("x\n")
        if version:
            with open(os.path.join(otro, "VERSION"), "w") as fh:
                fh.write(version + "\n")
        git(otro, "add", "-A")
        git(otro, "-c", "user.name=o", "-c", "user.email=o@o", "commit", "-qm", nombre)
        git(otro, "push", "-q", "origin", "HEAD:main")
        git(self.repo, "fetch", "-q", "origin")

    def head(self, e):
        return subprocess.run(["git", "-C", e["worktree"], "rev-parse", "HEAD"], capture_output=True,
                              text=True).stdout.strip()

    def push_rama(self, e):
        git(e["worktree"], "push", "-q", "origin", "HEAD:refs/heads/" + e["branch"])

    def abierto(self, e, n):
        """LISTA, branch push and --hecho --pr n: a pr-abierto publication."""
        ok, code, lines = self.ask(e)
        self.assertEqual(code, "LISTA", lines)
        self.push_rama(e)
        self.gh.pr(n, e["branch"], self.head(e))
        ok, lines = publica.hecho(self.pid, e, pr=n)
        self.assertTrue(ok, lines)
        return publica.load(self.pid)["cola"][-1]

    def me(self, e):
        return next(p for p in publica.load(self.pid)["cola"] if p["session_id"] == e["session_id"])


class ListaTest(PrModeCase):
    def test_lista_orders_the_push_to_the_agents_branch_and_does_not_need_a_fast_forward(self):
        a = self.worktree("uno", "sa")
        self.avanza_main()                                       # main moved on: in direct mode this is BASE-MOVIDA
        ok, code, lines = self.ask(a)
        self.assertEqual((ok, code), (True, "LISTA"), lines)
        self.assertIn("git push origin HEAD:refs/heads/lookout/uno", lines[-1])
        self.assertNotIn("HEAD:main", "\n".join(lines))
        self.assertIn("detrás por 1", "\n".join(lines))
        self.assertIn("Commits (1)", "\n".join(lines))          # only its own commit, not main's

    def test_a_tip_this_tree_has_never_fetched_is_a_no(self):
        a = self.worktree("uno", "sa")
        otro = os.path.join(self.tmp.name, "otro")
        subprocess.run(["git", "clone", "-q", self.origin, otro], check=True)
        with open(os.path.join(otro, "o.txt"), "w") as fh:
            fh.write("o\n")
        git(otro, "add", "-A")
        git(otro, "-c", "user.name=o", "-c", "user.email=o@o", "commit", "-qm", "o")
        git(otro, "push", "-q", "origin", "HEAD:main")         # not fetched
        ok, code, lines = self.ask(a)
        self.assertEqual((ok, code), (False, "BASE-DESCONOCIDA"), lines)
        self.assertIn("git fetch origin", "\n".join(lines))

    def test_a_version_not_above_origins_is_a_no(self):
        a = self.worktree("uno", "sa", version="0.2.0")
        self.avanza_main(version="0.3.0")
        ok, code, lines = self.ask(a)
        self.assertEqual((ok, code), (False, "VERSION-VIEJA"), lines)

    def test_a_branch_that_touches_no_version_file_claims_no_version(self):
        # as in direct mode (2026-10-02): a docs-only change has no version to put above origin's
        a = self.worktree("uno", "sa", version="")
        ok, code, lines = self.ask(a)
        self.assertEqual(code, "LISTA", lines)
        self.assertIn("Versión: no la cambia", "\n".join(lines))
        self.assertEqual(self.me(a)["version"], "")

    def test_the_main_branch_itself_is_not_a_pr_branch(self):
        e = self.agent("sm", nombre="enmain", tarea="p-m", worktree=self.repo, cwd=self.repo, base="origin/main",
                       branch="main")
        self.transcript("sm", [f3.EXT, f3.a_text(f3.M_EXT + "\n" + f3.HOLD)])
        with open(os.path.join(self.repo, "VERSION"), "w") as fh:
            fh.write("0.2.0\n")
        git(self.repo, "commit", "-qam", "0.2.0")
        ok, code, lines = self.ask(e)
        self.assertEqual((ok, code), (False, "SIN-RAMA"), lines)

    def test_a_remote_branch_the_push_cannot_fast_forward_is_a_no(self):
        a = self.worktree("uno", "sa")
        self.push_rama(a)
        git(a["worktree"], "commit", "-q", "--amend", "-m", "uno reescrito")
        ok, code, lines = self.ask(a)
        self.assertEqual((ok, code), (False, "RAMA-DIVERGE"), lines)

    def test_direct_mode_is_the_default_and_unchanged(self):
        publica.pon_modo(self.pid, "directo")
        a = self.worktree("uno", "sa")
        ok, code, lines = self.ask(a)
        self.assertEqual(code, "LISTA", lines)
        self.assertIn("git push origin HEAD:main", lines[-1])
        led = publica.load(self.pid)
        led.pop("modo")
        publica.save(self.pid, led)
        self.assertEqual(publica.modo(self.pid), "directo")


class HechoTest(PrModeCase):
    def test_hecho_with_the_pr_number_accepts_an_open_pr(self):
        a = self.worktree("uno", "sa")
        self.ask(a)
        ok, lines = publica.hecho(self.pid, a, pr=7)
        self.assertFalse(ok)                                     # branch not pushed yet
        self.push_rama(a)
        self.gh.pr(7, "lookout/uno", self.head(a))
        ok, lines = publica.hecho(self.pid, a, pr=7)
        self.assertTrue(ok, lines)
        me = self.me(a)
        self.assertEqual((me["estado"], me["pr"]), ("pr-abierto", 7))

    def test_a_pr_of_another_branch_or_head_or_unreadable_is_a_no(self):
        a = self.worktree("uno", "sa")
        self.ask(a)
        self.push_rama(a)
        self.gh.pr(7, "otra-rama", self.head(a))
        self.assertFalse(publica.hecho(self.pid, a, pr=7)[0])
        self.gh.pr(7, "lookout/uno", "0" * 40)
        self.assertFalse(publica.hecho(self.pid, a, pr=7)[0])
        self.assertFalse(publica.hecho(self.pid, a, pr=8)[0])   # no such PR
        self.gh.pr(7, "lookout/uno", self.head(a))
        self.gh.falla = True
        ok, lines = publica.hecho(self.pid, a, pr=7)             # gh missing or failing: a NO, no traceback
        self.assertFalse(ok)
        self.assertIn("gh", "\n".join(lines))
        self.assertEqual(self.me(a)["estado"], "lista")

    def test_hecho_without_pr_in_pr_mode_and_with_pr_in_direct_mode_say_what_to_do(self):
        a = self.worktree("uno", "sa")
        self.ask(a)
        self.push_rama(a)
        ok, lines = publica.hecho(self.pid, a)
        self.assertFalse(ok)
        self.assertIn("--pr", "\n".join(lines))
        publica.pon_modo(self.pid, "directo")
        ok, lines = publica.hecho(self.pid, a, pr=7)
        self.assertFalse(ok)
        self.assertIn("modo directo", "\n".join(lines))

    def test_a_merged_pr_at_hecho_time_is_published(self):
        a = self.worktree("uno", "sa")
        self.ask(a)
        self.push_rama(a)
        self.gh.pr(7, "lookout/uno", self.head(a), state="MERGED")
        ok, lines = publica.hecho(self.pid, a, pr=7)
        self.assertTrue(ok, lines)
        self.assertEqual(self.me(a)["estado"], "publicada")


class ColaTest(PrModeCase):
    def test_an_open_pr_does_not_hold_the_next_agent_but_its_version_counts(self):
        a = self.worktree("uno", "sa", version="0.2.0")
        b = self.worktree("dos", "sb", version="0.2.0")
        self.abierto(a, 7)
        ok, code, lines = self.ask(b)
        self.assertEqual(code, "VERSION-USADA", lines)          # not ESPERA: the queue moves to the merge
        with open(os.path.join(b["worktree"], "VERSION"), "w") as fh:
            fh.write("0.3.0\n")
        git(b["worktree"], "commit", "-qam", "0.3.0")
        ok, code, lines = self.ask(b)
        self.assertEqual(code, "LISTA", lines)

    def test_a_lista_whose_branch_is_pushed_is_not_published_by_concilia(self):
        a = self.worktree("uno", "sa")
        self.ask(a)
        self.push_rama(a)
        self.assertEqual(publica.concilia(self.pid), [])
        self.assertEqual(self.me(a)["estado"], "lista")

    def test_an_open_pr_survives_session_end_relief_and_closing(self):
        a = self.worktree("uno", "sa")
        self.abierto(a, 7)
        lote.set_estado(self.pid, "sa", "relevada")
        publica.retira_sesion(self.pid, "sa", "relevada")
        self.assertEqual(publica.caducada(self.pid, self.me(a)), "")
        publica.concilia(self.pid)
        self.assertEqual(self.me(a)["estado"], "pr-abierto")
        self.gh.falla = True                                     # a network error never expires it
        publica.concilia(self.pid, ahora=10 ** 10)
        self.assertEqual(self.me(a)["estado"], "pr-abierto")

    def test_concilia_publishes_on_merge_expires_on_close_and_warns_out_of_order(self):
        a = self.worktree("uno", "sa", version="0.2.0")
        b = self.worktree("dos", "sb", version="0.3.0")
        c = self.worktree("tres", "sc", version="0.4.0")
        self.abierto(a, 7)
        self.abierto(b, 8)
        self.abierto(c, 9)
        self.gh.prs[8]["state"] = "MERGED"
        self.gh.prs[9]["state"] = "CLOSED"
        out = "\n".join(publica.concilia(self.pid, ahora=10 ** 10))
        self.assertEqual(self.me(b)["estado"], "publicada")
        self.assertEqual(self.me(c)["estado"], "caducada")
        self.assertEqual(self.me(a)["estado"], "pr-abierto")
        self.assertIn("fuera de orden", out)
        self.assertIn("#7", out)

    def test_the_queue_and_supervisor_md_show_the_open_prs_in_merge_order(self):
        a = self.worktree("uno", "sa", version="0.2.0")
        b = self.worktree("dos", "sb", version="0.3.0")
        self.abierto(a, 7)
        self.abierto(b, 8)
        cola = publica.render_cola(self.pid)
        self.assertIn("#7", cola)
        self.assertIn("#8", cola)
        self.assertLess(cola.index("#7"), cola.index("#8"))
        self.assertIn("fusionar", cola)
        md = supervisor_md.render(self.pid)
        self.assertNotIn("cola de publicación: vacía", md)
        self.assertIn("#7", md)


class FusionaTest(PrModeCase):
    def setUp(self):
        super().setUp()
        self.a = self.worktree("uno", "sa", version="0.2.0")
        self.b = self.worktree("dos", "sb", version="0.3.0")
        self.pa = self.abierto(self.a, 7)
        self.pb = self.abierto(self.b, 8)

    def si(self, texto, eleccion="Fusionar", **kw):
        """The user's choice in the supervisor's modal, the way its hook records it."""
        d = decisiones.abre(self.pid, texto, si_es="Fusionar", notificar=False, **kw)
        q = "%s (%s)" % (texto, d["id"])
        tid = "toolu_" + d["id"]
        decisiones.registra_pregunta(self.pid, tid, [q])
        decisiones.registra_respuesta(self.pid, tid, eleccion, por_pregunta={q: eleccion})
        return d["id"]

    def test_a_yes_the_supervisor_typed_is_not_the_users(self):
        # codex r1: `decision --cierra dK --si` is the supervisor's word, not the user's choice in its modal
        d = decisiones.abre(self.pid, "¿Fusiono el PR #7?", si_es="Fusionar", notificar=False)
        decisiones.cierra(self.pid, d["id"], "Fusionar", True)
        self.assertEqual(publica.fusiona(self.pid, 7, d["id"])[1], "SIN-SI")
        self.assertEqual(publica.fusiona(self.pid, 7, self.si("¿Fusiono el PR #7?", eleccion="No"))[1], "SIN-SI")
        self.assertEqual(publica.fusiona(self.pid, 7, self.si("¿Cierro la pestaña? #7", tipo="cierre"))[1], "SIN-SI")
        self.assertEqual(self.gh.merges(), [])

    def test_a_pr_retargeted_or_waiting_on_hooks_is_not_merged(self):
        # sonnet r1: the base branch was not checked; codex r1: HAS_HOOKS passed although the rule is CLEAN
        self.gh.prs[7]["baseRefName"] = "release/9"
        self.assertEqual(publica.fusiona(self.pid, 7, self.si("PR #7"))[1], "PR-CAMBIO")
        self.gh.pr(7, "lookout/uno", self.pa["head"], status="HAS_HOOKS")
        self.assertEqual(publica.fusiona(self.pid, 7, self.si("PR #7"))[1], "PR-NO-FUSIONABLE")
        self.assertEqual(self.gh.merges(), [])

    def test_new_commits_on_an_open_pr_are_verified_again_and_merged(self):
        # sonnet r1: after a review fix the agent could not ask again (its own PR counted as a rival version) and a
        # second --hecho left two entries for #7, the stale one first, so --fusiona said PR-CAMBIO forever
        with open(os.path.join(self.a["worktree"], "fix.txt"), "w") as fh:
            fh.write("fix\n")
        git(self.a["worktree"], "add", "-A")
        git(self.a["worktree"], "commit", "-qm", "fix")
        self.push_rama(self.a)
        self.gh.pr(7, "lookout/uno", self.head(self.a))
        self.assertEqual(publica.fusiona(self.pid, 7, self.si("PR #7"))[1], "PR-CAMBIO")
        ok, code, lines = self.ask(self.a)
        self.assertEqual(code, "LISTA", lines)                    # same version: it is the same PR
        ok, lines = publica.hecho(self.pid, self.a, pr=7)
        self.assertTrue(ok, lines)
        siete = [p for p in publica.load(self.pid)["cola"] if p.get("pr") == 7 and p["estado"] == publica.ABIERTO]
        self.assertEqual(len(siete), 1)
        self.assertEqual(siete[0]["head"], self.head(self.a))
        self.assertIn("#7, 1º", publica.render_cola(self.pid))     # it keeps its place in the merge order
        ok, code, lines = publica.fusiona(self.pid, 7, self.si("PR #7"))
        self.assertEqual(code, "FUSIONADA", lines)

    def test_with_the_users_yes_the_first_pr_is_merged_once(self):
        did = self.si("¿Fusiono el PR #7 (uno, 0.2.0) en main?")
        ok, code, lines = publica.fusiona(self.pid, 7, did)
        self.assertEqual((ok, code), (True, "FUSIONADA"), lines)
        self.assertEqual(self.gh.merges(), [["pr", "merge", "7", "--merge", "--match-head-commit", self.pa["head"]]])
        self.assertEqual(self.me(self.a)["estado"], "publicada")
        self.assertTrue(next(it for it in decisiones.load(self.pid)["items"] if it["id"] == did).get("usada"))
        ok, code, _ = publica.fusiona(self.pid, 7, did)            # the same yes never merges twice
        self.assertFalse(ok)
        self.assertEqual(len(self.gh.merges()), 1)

    def test_no_merge_without_a_valid_yes_for_that_pr(self):
        d = decisiones.abre(self.pid, "¿Fusiono el PR #7?", si_es="Fusionar", notificar=False)
        self.assertEqual(publica.fusiona(self.pid, 7, d["id"])[1], "SIN-SI")        # not answered
        decisiones.cierra(self.pid, d["id"], "No", False)
        self.assertEqual(publica.fusiona(self.pid, 7, d["id"])[1], "SIN-SI")        # answered no
        self.assertEqual(publica.fusiona(self.pid, 7, "d999")[1], "SIN-SI")         # unknown
        otro = self.si("¿Fusiono el PR #8?")
        self.assertEqual(publica.fusiona(self.pid, 7, otro)[1], "SI-DE-OTRO-PR")
        self.assertEqual(publica.fusiona(self.pid, 77, self.si("¿Fusiono el PR #77?"))[1], "NO-EN-COLA")
        self.assertEqual(self.gh.merges(), [])

    def test_no_merge_of_a_state_other_than_the_verified_one(self):
        self.gh.prs[7]["headRefOid"] = "1" * 40
        self.assertEqual(publica.fusiona(self.pid, 7, self.si("PR #7"))[1], "PR-CAMBIO")
        self.gh.pr(7, "lookout/uno", self.pa["head"], checks=("SUCCESS", "FAILURE"))
        self.assertEqual(publica.fusiona(self.pid, 7, self.si("PR #7"))[1], "PR-NO-FUSIONABLE")
        self.gh.pr(7, "lookout/uno", self.pa["head"], checks=("SUCCESS", None))
        self.assertEqual(publica.fusiona(self.pid, 7, self.si("PR #7"))[1], "PR-NO-FUSIONABLE")   # still running
        self.gh.pr(7, "lookout/uno", self.pa["head"], mergeable="CONFLICTING", status="DIRTY")
        self.assertEqual(publica.fusiona(self.pid, 7, self.si("PR #7"))[1], "PR-NO-FUSIONABLE")
        self.gh.pr(7, "lookout/uno", self.pa["head"], state="CLOSED")
        self.assertEqual(publica.fusiona(self.pid, 7, self.si("PR #7"))[1], "PR-NO-FUSIONABLE")
        self.gh.falla = True
        self.assertEqual(publica.fusiona(self.pid, 7, self.si("PR #7"))[1], "SIN-GH")
        self.assertEqual(self.gh.merges(), [])

    def test_out_of_order_needs_the_flag(self):
        ok, code, lines = publica.fusiona(self.pid, 8, self.si("PR #8"))
        self.assertEqual(code, "FUERA-DE-ORDEN", lines)
        self.assertIn("#7", "\n".join(lines))
        ok, code, lines = publica.fusiona(self.pid, 8, self.si("PR #8"), fuera_de_orden=True)
        self.assertEqual(code, "FUSIONADA", lines)

    def test_a_repo_without_checks_merges_and_says_so(self):
        self.gh.pr(7, "lookout/uno", self.pa["head"], checks=())
        ok, code, lines = publica.fusiona(self.pid, 7, self.si("PR #7"))
        self.assertEqual(code, "FUSIONADA", lines)
        self.assertIn("sin checks", "\n".join(lines))

    def test_the_cli_takes_modo_hecho_pr_and_fusiona(self):
        import argparse
        import io
        from contextlib import redirect_stdout
        cli = f10.load_cli("lookout_cli_01327")
        cli.project = lambda _p: (self.pid, os.path.join(self.repo, ".git"))
        base = dict(proyecto="/x", agente=None, cola=False, hecho=False, retira=False, worktree="", modo="", pr=0,
                    fusiona=0, decision="", fuera_de_orden=False)

        def run(**kw):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = cli.cmd_publica(argparse.Namespace(**dict(base, **kw)))
            return rc, out.getvalue()
        rc, out = run(modo="directo")
        self.assertEqual((rc, publica.modo(self.pid)), (0, "directo"))
        rc, out = run(modo="pr")
        self.assertEqual(publica.modo(self.pid), "pr")
        rc, out = run(fusiona=7, decision=self.si("PR #7"))
        self.assertEqual(rc, 0, out)
        self.assertIn("FUSIONADA", out)
        rc, out = run(fusiona=8, decision="")
        self.assertEqual(rc, 5, out)


class ParserTest(unittest.TestCase):
    def test_the_parser_knows_the_new_flags(self):
        r = subprocess.run([sys.executable, os.path.join(f10.BIN, "lookout"), "publica", "-h"], capture_output=True,
                           text=True)
        for flag in ("--modo", "--pr", "--fusiona", "--decision", "--fuera-de-orden"):
            self.assertIn(flag, r.stdout)


if __name__ == "__main__":
    unittest.main()

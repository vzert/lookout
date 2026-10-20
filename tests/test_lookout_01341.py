"""0.13.41 (p-7e4c7bdb9f): the user authorizes in the supervisor's modal publishing without the reviewer.
Run: python3 -m unittest tests/test_lookout_01341.py

3-tier-memory, 2026-10-19 (d241, d243): codex gave break with unsafe=0 on «Prompts repetidos»; Víctor answered «ya sin
más revisiones, hacemos push», lookout kept saying NO and the push went out from the agent's pane, outside lookout: no
check of base, version or private paths, nothing in the queue. Now a decision of its own kind (`--sin-revisor`), the
user's literal choice in the modal, one agent, one use, lifts only the adversary gate, and only with no verdict or a
break with unsafe=0; it is tied to the verdict line it was asked about, and the rest of the check runs as always.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f3 as f3  # noqa: E402

import cierre  # noqa: E402
import decisiones  # noqa: E402
import gobierno  # noqa: E402
import publica  # noqa: E402

git = f3.git
SI = "Publicar sin revisor"


class SinRevisorCase(f3.GitCase):
    def worktree(self, slug, sid, verdict=f3.BREAK_SAFE, **kw):
        e = super().worktree(slug, sid, **kw)
        os.remove(os.path.join(self.projects, "-enc", sid + ".jsonl"))
        self.transcript(sid, [f3.EXT, f3.a_text(f3.M_EXT + "\n" + verdict)] if verdict else [f3.a_text("listo")])
        return e

    def st(self, e):
        return gobierno.estado(self.pid, e, self.projects)

    def abre(self, e, eleccion=SI, si_es=SI):
        ok, it = publica.abre_sin_revisor(self.pid, e, "¿Publico %s sin otra revisión?" % e["nombre"], si_es,
                                          self.st(e), notificar=False)
        self.assertTrue(ok, it)
        q = "%s (%s)" % (it["texto"], it["id"])
        tid = "toolu_" + it["id"]
        decisiones.registra_pregunta(self.pid, tid, [q])
        decisiones.registra_respuesta(self.pid, tid, eleccion, por_pregunta={q: eleccion})
        return it["id"]

    def ask(self, e, decision=""):
        return publica.pide(self.pid, e, self.st(e), decision=decision)

    def me(self, e):
        return next(p for p in publica.load(self.pid)["cola"] if p["session_id"] == e["session_id"])

    def dec(self, did):
        return next(d for d in decisiones.load(self.pid)["items"] if d["id"] == did)


class AutorizaTest(SinRevisorCase):
    def test_a_safe_break_is_still_a_no_without_the_users_yes(self):
        a = self.worktree("uno", "sa")
        ok, code, lines = self.ask(a)
        self.assertEqual((ok, code), (False, "BREAK"))
        self.assertIn("--sin-revisor", "\n".join(lines))   # the NO names the way in

    def test_the_users_yes_lifts_a_safe_break_and_the_queue_records_it(self):
        a = self.worktree("uno", "sa")
        did = self.abre(a)
        ok, code, lines = self.ask(a, did)
        self.assertEqual((ok, code), (True, "LISTA"), lines)
        text = "\n".join(lines)
        self.assertIn("SIN REVISOR", text)
        self.assertIn(did, text)
        self.assertIn("git push origin HEAD:main", lines[-1])
        p = self.me(a)
        self.assertEqual(p["sin_revisor"]["decision"], did)
        self.assertEqual(p["sin_revisor"]["veredicto"], f3.BREAK_SAFE)
        self.assertTrue(self.dec(did).get("usada"))
        self.assertIn("sin revisor", publica.render_cola(self.pid))

    def test_the_users_yes_lifts_a_missing_verdict(self):
        a = self.worktree("uno", "sa", verdict=None)
        self.assertEqual(self.ask(a)[1], "SIN-VEREDICTO")
        did = self.abre(a)
        ok, code, lines = self.ask(a, did)
        self.assertEqual((ok, code), (True, "LISTA"), lines)
        self.assertEqual(self.me(a)["sin_revisor"]["veredicto"], "")


class NoAutorizaTest(SinRevisorCase):
    def test_an_unsafe_break_cannot_even_be_asked(self):
        a = self.worktree("uno", "sa", verdict=f3.BREAK)
        ok, why = publica.abre_sin_revisor(self.pid, a, "¿Publico?", SI, self.st(a), notificar=False)
        self.assertFalse(ok)
        self.assertIn("unsafe", why)

    def test_a_hold_needs_no_such_decision(self):
        a = self.worktree("uno", "sa", verdict=f3.HOLD)
        ok, why = publica.abre_sin_revisor(self.pid, a, "¿Publico?", SI, self.st(a), notificar=False)
        self.assertFalse(ok)

    def test_a_break_that_turned_unsafe_after_the_yes_is_a_no(self):
        a = self.worktree("uno", "sa")
        did = self.abre(a)
        self.transcript("sa", [f3.EXT, f3.a_text(f3.M_EXT + "\n" + f3.BREAK)])
        ok, code, _ = self.ask(a, did)
        self.assertEqual((ok, code), (False, "SIN-REVISOR-NO"))
        self.assertFalse(self.dec(did).get("usada"))

    def test_a_new_safe_break_after_the_yes_is_not_the_one_the_user_accepted(self):
        a = self.worktree("uno", "sa")
        did = self.abre(a)
        otro = f3.BREAK_SAFE.replace("incomplete=2", "incomplete=1")
        self.transcript("sa", [f3.EXT, f3.a_text(f3.M_EXT + "\n" + otro)])
        self.assertEqual(self.ask(a, did)[1], "SIN-REVISOR-NO")

    def test_another_round_with_the_same_line_is_not_the_one_the_user_accepted(self):
        # Sonnet r1: dozens of real (session, line) pairs repeat the same unsafe=0 break line in later rounds
        a = self.worktree("uno", "sa")
        did = self.abre(a)
        self.transcript("sa", [f3.EXT, f3.a_text(f3.M_EXT + "\n" + f3.BREAK_SAFE)])
        self.assertEqual(self.ask(a, did)[1], "SIN-REVISOR-NO")

    def test_the_user_chose_something_else(self):
        a = self.worktree("uno", "sa")
        did = self.abre(a, eleccion="Otra ronda")
        self.assertEqual(self.ask(a, did)[1], "SIN-REVISOR-NO")

    def test_a_yes_the_supervisor_typed_does_not_count(self):
        a = self.worktree("uno", "sa")
        ok, it = publica.abre_sin_revisor(self.pid, a, "¿Publico?", SI, self.st(a), notificar=False)
        decisiones.cierra(self.pid, it["id"], SI, True)
        self.assertEqual(self.ask(a, it["id"])[1], "SIN-REVISOR-NO")

    def test_a_plain_push_yes_is_not_a_yes_to_skip_the_reviewer(self):
        a = self.worktree("uno", "sa")
        d = decisiones.abre(self.pid, "¿Push de uno?", ["uno"], notificar=False, si_es="Push")
        q = "¿Push de uno? (%s)" % d["id"]
        decisiones.registra_pregunta(self.pid, "toolu_x", [q])
        decisiones.registra_respuesta(self.pid, "toolu_x", "Push", por_pregunta={q: "Push"})
        self.assertEqual(self.ask(a, d["id"])[1], "SIN-REVISOR-NO")

    def test_another_agents_yes_does_not_count(self):
        a = self.worktree("uno", "sa")
        b = self.worktree("dos", "sb", version="0.3.0")
        did = self.abre(b)
        self.assertEqual(self.ask(a, did)[1], "SIN-REVISOR-NO")

    def test_a_yes_counts_once(self):
        a = self.worktree("uno", "sa")
        did = self.abre(a)
        self.assertEqual(self.ask(a, did)[1], "LISTA")
        git(a["worktree"], "commit", "-q", "--allow-empty", "-m", "otro")
        publica.concilia(self.pid)
        self.assertEqual(self.ask(a, did)[1], "SIN-REVISOR-NO")


class SigueVerificandoTest(SinRevisorCase):
    def test_base_moved_is_still_a_no_and_keeps_the_yes(self):
        a = self.worktree("uno", "sa")
        b = self.worktree("dos", "sb", verdict=f3.HOLD, version="0.3.0")
        self.assertEqual(self.ask(b)[1], "LISTA")
        git(b["worktree"], "push", "-q", "origin", "HEAD:main")
        publica.hecho(self.pid, b)
        did = self.abre(a)
        ok, code, _ = self.ask(a, did)
        self.assertEqual(code, "BASE-MOVIDA")
        self.assertFalse(self.dec(did).get("usada"))

    def test_private_paths_are_still_a_no(self):
        a = self.worktree("uno", "sa", extra="/Users/alguien/x")
        did = self.abre(a)
        self.assertEqual(self.ask(a, did)[1], "RUTAS-PRIVADAS")

    def test_version_not_renumbered_is_still_a_no(self):
        a = self.worktree("uno", "sa", version="0.1.0")
        with open(os.path.join(a["worktree"], "CHANGELOG.md"), "a") as fh:
            fh.write("- más\n")
        git(a["worktree"], "commit", "-qam", "changelog")
        did = self.abre(a)
        self.assertEqual(self.ask(a, did)[1], "VERSION-SIN-RENUMERAR")


class CaducaTest(SinRevisorCase):
    def test_an_authorized_lista_does_not_expire_for_its_accepted_break(self):
        a = self.worktree("uno", "sa")
        self.assertEqual(self.ask(a, self.abre(a))[1], "LISTA")
        publica.concilia(self.pid)
        self.assertEqual(self.me(a)["estado"], "lista")

    def test_it_expires_when_head_changes(self):
        a = self.worktree("uno", "sa")
        self.ask(a, self.abre(a))
        git(a["worktree"], "commit", "-q", "--allow-empty", "-m", "otro")
        publica.concilia(self.pid)
        self.assertEqual(self.me(a)["estado"], "caducada")

    def test_it_expires_when_another_round_repeats_the_accepted_line(self):
        a = self.worktree("uno", "sa")
        self.ask(a, self.abre(a))
        self.transcript("sa", [f3.EXT, f3.a_text(f3.M_EXT + "\n" + f3.BREAK_SAFE)])
        publica.concilia(self.pid)
        self.assertEqual(self.me(a)["estado"], "caducada")

    def test_it_expires_when_a_new_break_arrives(self):
        a = self.worktree("uno", "sa")
        self.ask(a, self.abre(a))
        self.transcript("sa", [f3.EXT, f3.a_text(f3.M_EXT + "\n" + f3.BREAK)])
        publica.concilia(self.pid)
        self.assertEqual(self.me(a)["estado"], "caducada")


class RecitaTest(SinRevisorCase):
    """Sonnet r2: an agent quotes the same verdict again with no new round (goalspec asks for it at close; about one
    real session in ten has more verdict lines than rounds). That is the verdict the user accepted, not another one."""
    def recita(self):
        self.transcript("sa", [f3.a_text(f3.BREAK_SAFE)])

    def test_a_requote_before_publica_keeps_the_yes(self):
        a = self.worktree("uno", "sa")
        did = self.abre(a)
        self.recita()
        self.assertEqual(self.ask(a, did)[1], "LISTA")

    def test_a_requote_does_not_expire_the_lista(self):
        a = self.worktree("uno", "sa")
        self.assertEqual(self.ask(a, self.abre(a))[1], "LISTA")
        self.recita()
        publica.concilia(self.pid)
        self.assertEqual(self.me(a)["estado"], "lista")

    def test_a_requote_after_publishing_still_lets_the_task_close(self):
        a = self.worktree("uno", "sa")
        self.assertEqual(self.ask(a, self.abre(a))[1], "LISTA")
        git(a["worktree"], "push", "-q", "origin", "HEAD:main")
        self.assertTrue(publica.hecho(self.pid, a)[0])
        self.recita()
        orig = cierre.emite
        cierre.emite = lambda *x, **k: (True, ["ok"])
        try:
            ok, lines = cierre.cierra(self.pid, "/x/.git", a, self.st(a), "resolved", "hecho", "d99")
        finally:
            cierre.emite = orig
        self.assertTrue(ok, lines)

    def test_a_round_launched_but_not_quoted_yet_is_a_no(self):
        a = self.worktree("uno", "sa")
        did = self.abre(a)
        self.transcript("sa", [f3.SPAWN])
        self.assertEqual(self.ask(a, did)[1], "SIN-REVISOR-NO")


class CierreTest(SinRevisorCase):
    def test_a_task_published_without_the_reviewer_can_be_closed_with_the_users_yes(self):
        a = self.worktree("uno", "sa")
        self.assertEqual(self.ask(a, self.abre(a))[1], "LISTA")
        git(a["worktree"], "push", "-q", "origin", "HEAD:main")
        self.assertTrue(publica.hecho(self.pid, a)[0])
        calls = []
        orig = cierre.emite
        cierre.emite = lambda *x, **k: (calls.append(x) or (True, ["ok"]))
        try:
            ok, lines = cierre.cierra(self.pid, "/x/.git", a, self.st(a), "resolved", "hecho", "d99")
        finally:
            cierre.emite = orig
        self.assertTrue(ok, lines)
        self.assertEqual(len(calls), 1)

    def test_without_that_publication_a_break_still_blocks_closing(self):
        a = self.worktree("uno", "sa")
        ok, lines = cierre.cierra(self.pid, "/x/.git", a, self.st(a), "resolved", "hecho", "d99")
        self.assertFalse(ok)
        self.assertIn("sin hold", lines[0])


class CliTest(SinRevisorCase):
    def test_decision_sin_revisor_then_publica_decision(self):
        import argparse
        import io
        from contextlib import redirect_stdout
        import test_lookout_f10 as f10
        cli = f10.load_cli("lookout_cli_01341")
        cli.project = lambda _p: (self.pid, os.path.join(self.repo, ".git"))
        a = self.worktree("uno", "sa")
        dec = dict(proyecto="/x", abre="¿Publico uno sin otra revisión?", agentes="uno", cierra=None, respuesta=None,
                   lista=False, si=False, no=False, nueva=False, si_es=SI, cierre=False, shells_parar="",
                   shells_dejar="", permiso=False, sin_revisor=True)
        pub = dict(proyecto="/x", agente="uno", cola=False, hecho=False, retira=False, worktree="", modo="", pr=0,
                   fusiona=0, decision="", fuera_de_orden=False)

        def run(fn, **kw):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = fn(argparse.Namespace(**kw))
            return rc, out.getvalue()
        rc, out = run(cli.cmd_decision, **dict(dec, agentes="uno,dos"))
        self.assertEqual(rc, 5, out)
        rc, out = run(cli.cmd_decision, **dec)
        self.assertEqual(rc, 0, out)
        did = decisiones.load(self.pid)["items"][-1]["id"]
        self.assertEqual(self.dec(did)["tipo"], "sin-revisor")
        self.assertIn("--decision " + did, out)
        rc, out = run(cli.cmd_publica, **pub)
        self.assertEqual(rc, 5, out)
        self.assertIn("--sin-revisor", out)
        q = "%s (%s)" % (dec["abre"], did)
        decisiones.registra_pregunta(self.pid, "toolu_cli", [q])
        decisiones.registra_respuesta(self.pid, "toolu_cli", SI, por_pregunta={q: SI})
        rc, out = run(cli.cmd_publica, **dict(pub, decision=did))
        self.assertEqual(rc, 0, out)
        self.assertIn("LISTA", out)
        self.assertIn("SIN REVISOR", out)


if __name__ == "__main__":
    unittest.main()

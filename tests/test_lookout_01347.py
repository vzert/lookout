"""0.13.47 (p-25b2921716): codex's round on the published 0.13.41 gave two breaks.
Run: python3 -m unittest tests/test_lookout_01347.py

1. `--hecho --pr N` for a PR opened outside lookout left the agent's live entry (esperando/turno) in the queue: the
   agent stood twice in the queue, and the stale entry kept the turn or the place of the others (codex: «quedan A/turno
   y A/pr-abierto»; B asks → ESPERA).
2. `--hecho` (and `concilia`, which reaches the same `publicada` when origin's tip is the verified head) accredited as
   verified a `lista` whose adversary gate no longer held (a new round with unsafe=1 after the user's yes without the
   reviewer, or after a hold). The commit is on origin either way, so lookout cannot refuse the fact: it records it as
   published with the gate expired, says so, and `--cola` / `--fusiona` show it.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f3 as f3  # noqa: E402
import test_lookout_01327 as t27  # noqa: E402
import test_lookout_01341 as t41  # noqa: E402
import test_lookout_01341_pr as t41pr  # noqa: E402

import decisiones  # noqa: E402
import publica  # noqa: E402

git = f3.git


def vivas(pid, sid):
    return [p for p in publica.load(pid)["cola"] if p["session_id"] == sid
            and p["estado"] in ("esperando",) + publica.VIVAS]


class RegistraReemplazaTest(t41pr.PrExternoCase):
    def test_a_waiting_entry_is_retired_when_its_pr_is_queued(self):
        b = self.worktree("dos", "sb", version="0.3.0")
        self.assertEqual(self.ask(b)[1], "LISTA")
        a = self.worktree("uno", "sa", version="0.4.0")
        self.assertEqual(self.ask(a)[1], "ESPERA")
        self.externo(a, 7)
        ok, lines = publica.hecho(self.pid, a, pr=7)
        self.assertTrue(ok, lines)
        self.assertEqual(vivas(self.pid, "sa"), [])
        viejo, = [p for p in self.cola() if p["session_id"] == "sa" and p["estado"] == "retirada"]
        self.assertIn("#7", viejo["motivo"])
        self.assertEqual(self.de_pr(7)[0]["estado"], publica.ABIERTO)

    def test_a_stale_turn_no_longer_makes_the_others_wait(self):
        a = self.worktree("uno", "sa")
        led = publica.load(self.pid)
        led["cola"].append({"session_id": "sa", "nombre": "uno", "estado": "turno", "pedida": 1, "orden": 1})
        publica.save(self.pid, led)
        b = self.worktree("dos", "sb", version="0.3.0")
        self.assertEqual(self.ask(b)[1], "ESPERA")
        self.externo(a, 8)
        ok, lines = publica.hecho(self.pid, a, pr=8)
        self.assertTrue(ok, lines)
        self.assertIn("Siguiente en la cola: dos", "\n".join(lines))   # the one the stale turn kept waiting
        self.assertEqual(vivas(self.pid, "sa"), [])
        self.assertEqual(self.ask(b)[1], "LISTA")


class PuertaCaducadaCase(t41.SinRevisorCase):
    def lista_y_break(self, e, sin_revisor=True):
        if sin_revisor:
            self.assertEqual(self.ask(e, self.abre(e))[1], "LISTA")
        else:
            self.transcript(e["session_id"], [f3.EXT, f3.a_text(f3.M_EXT + "\n" + f3.HOLD)])
            self.assertEqual(self.ask(e)[1], "LISTA")
        self.transcript(e["session_id"], [f3.EXT, f3.a_text(f3.M_EXT + "\n" + f3.BREAK)])
        git(e["worktree"], "push", "-q", "origin", "HEAD:main")


class HechoDirectoTest(PuertaCaducadaCase):
    def test_hecho_records_it_with_the_gate_expired_and_says_so(self):
        a = self.worktree("uno", "sa")
        self.lista_y_break(a)
        ok, lines = publica.hecho(self.pid, a)
        self.assertTrue(ok, lines)          # the commit is on origin: lookout records the fact
        text = "\n".join(lines)
        self.assertIn("ya no valía", text)
        self.assertIn("díselo al usuario", text)
        p = self.me(a)
        self.assertEqual(p["estado"], "publicada")
        self.assertIn("veredicto", p["puerta_caducada"])
        self.assertIn("verificación caducada", publica.render_cola(self.pid))

    def test_the_same_after_a_hold(self):
        a = self.worktree("uno", "sa")
        self.lista_y_break(a, sin_revisor=False)
        ok, lines = publica.hecho(self.pid, a)
        self.assertTrue(ok, lines)
        self.assertTrue(self.me(a).get("puerta_caducada"))

    def test_a_valid_gate_has_no_such_mark(self):
        a = self.worktree("uno", "sa")
        self.assertEqual(self.ask(a, self.abre(a))[1], "LISTA")
        git(a["worktree"], "push", "-q", "origin", "HEAD:main")
        ok, lines = publica.hecho(self.pid, a)
        self.assertTrue(ok, lines)
        self.assertNotIn("ya no valía", "\n".join(lines))
        self.assertFalse(self.me(a).get("puerta_caducada"))

    def test_concilia_marks_it_too(self):
        a = self.worktree("uno", "sa")
        self.lista_y_break(a)
        out = publica.concilia(self.pid)
        self.assertEqual(self.me(a)["estado"], "publicada")
        self.assertTrue(self.me(a).get("puerta_caducada"))
        self.assertIn("ya no valía", "\n".join(out))


class HechoPrTest(t27.PrModeCase):
    def test_hecho_pr_marks_the_open_pr_and_fusiona_says_it(self):
        a = self.worktree("uno", "sa")
        self.assertEqual(self.ask(a)[1], "LISTA")
        self.transcript("sa", [f3.EXT, f3.a_text(f3.M_EXT + "\n" + f3.BREAK)])
        self.push_rama(a)
        self.gh.pr(9, a["branch"], self.head(a))
        ok, lines = publica.hecho(self.pid, a, pr=9)
        self.assertTrue(ok, lines)
        self.assertIn("ya no valía", "\n".join(lines))
        p = self.me(a)
        self.assertEqual(p["estado"], publica.ABIERTO)
        self.assertTrue(p.get("puerta_caducada"))
        d = decisiones.abre(self.pid, "¿Fusiono el PR #9?", si_es="Fusionar", notificar=False)
        q = "¿Fusiono el PR #9? (%s)" % d["id"]
        decisiones.registra_pregunta(self.pid, "toolu_f", [q])
        decisiones.registra_respuesta(self.pid, "toolu_f", "Fusionar", por_pregunta={q: "Fusionar"})
        ok, code, lines = publica.fusiona(self.pid, 9, d["id"])
        # codex r1 on 0.13.47: the merge is the terminal action and has not happened yet, so it is a NO
        self.assertEqual(code, "PUERTA-CADUCADA", lines)
        self.assertEqual(self.gh.prs[9]["state"], "OPEN")


def si_fusiona(pid, n):
    d = decisiones.abre(pid, "¿Fusiono el PR #%d?" % n, si_es="Fusionar", notificar=False)
    q = "¿Fusiono el PR #%d? (%s)" % (n, d["id"])
    decisiones.registra_pregunta(pid, "toolu_f%d" % n, [q])
    decisiones.registra_respuesta(pid, "toolu_f%d" % n, "Fusionar", por_pregunta={q: "Fusionar"})
    return d["id"]


class PrAbiertoTest(t27.PrModeCase):
    """codex r1 on 0.13.47: a round that arrives after `--hecho --pr N`, on the same head, left `--fusiona` and the
    summary's merged reading publishing the PR as verified. Only while the agent's tree is still on the PR's head: an
    agent that moved on to new work (entry_of lets it ask again) has rounds about that work, not about the PR."""
    def test_a_new_round_on_the_same_head_flags_the_pr_and_fusiona_refuses(self):
        a = self.worktree("uno", "sa")
        self.abierto(a, 9)
        self.transcript("sa", [f3.EXT, f3.a_text(f3.M_EXT + "\n" + f3.BREAK)])
        out = publica.concilia(self.pid, ahora=10 ** 10)
        self.assertIn("ya no valía", "\n".join(out))
        self.assertTrue(self.me(a).get("puerta_caducada"))
        self.assertIn("verificación caducada", publica.render_cola(self.pid))
        did = si_fusiona(self.pid, 9)
        ok, code, lines = publica.fusiona(self.pid, 9, did)
        self.assertEqual((ok, code), (False, "PUERTA-CADUCADA"), lines)
        self.assertIn("vuelva a pedir", "\n".join(lines))
        self.assertEqual(self.gh.prs[9]["state"], "OPEN")
        self.assertFalse(next(d for d in decisiones.load(self.pid)["items"] if d["id"] == did).get("usada"))
        self.gh.prs[9]["state"] = "MERGED"      # the user merged it on GitHub
        out = publica.concilia(self.pid, ahora=2 * 10 ** 10)
        self.assertEqual(self.me(a)["estado"], "publicada")
        self.assertTrue(self.me(a).get("puerta_caducada"))
        self.assertIn("ya no valía", "\n".join(out))

    def test_fusiona_refuses_before_any_summary_saw_it(self):
        a = self.worktree("uno", "sa")
        self.abierto(a, 10)
        self.transcript("sa", [f3.EXT, f3.a_text(f3.M_EXT + "\n" + f3.BREAK)])
        ok, code, lines = publica.fusiona(self.pid, 10, si_fusiona(self.pid, 10))
        self.assertEqual(code, "PUERTA-CADUCADA", lines)
        self.assertTrue(self.me(a).get("puerta_caducada"))

    def test_new_work_after_the_pr_is_not_its_round(self):
        a = self.worktree("uno", "sa")
        self.abierto(a, 11)
        git(a["worktree"], "commit", "-q", "--allow-empty", "-m", "trabajo nuevo")
        self.transcript("sa", [f3.EXT, f3.a_text(f3.M_EXT + "\n" + f3.BREAK)])
        out = publica.concilia(self.pid, ahora=10 ** 10)
        self.assertNotIn("ya no valía", "\n".join(out))
        self.assertFalse(self.me(a).get("puerta_caducada"))
        ok, code, lines = publica.fusiona(self.pid, 11, si_fusiona(self.pid, 11))
        self.assertEqual(code, "FUSIONADA", lines)

    def test_a_pr_opened_outside_lookout_had_no_gate_to_expire(self):
        a = self.worktree("uno", "sa")
        git(a["worktree"], "push", "-q", "origin", "HEAD:refs/heads/" + a["branch"])
        self.gh.pr(12, a["branch"], self.head(a))
        self.assertTrue(publica.hecho(self.pid, a, pr=12)[0])
        self.transcript("sa", [f3.EXT, f3.a_text(f3.M_EXT + "\n" + f3.BREAK)])
        ok, code, lines = publica.fusiona(self.pid, 12, si_fusiona(self.pid, 12))
        self.assertEqual(code, "FUSIONADA", lines)


class RegistraTodasTest(t41pr.PrExternoCase):
    def test_every_live_entry_of_the_session_is_retired(self):
        a = self.worktree("uno", "sa")
        led = publica.load(self.pid)
        led["cola"] += [{"session_id": "sa", "nombre": "uno", "estado": "esperando", "pedida": 1, "orden": 1},
                        {"session_id": "sa", "nombre": "uno", "estado": "turno", "pedida": 2, "orden": 2}]
        publica.save(self.pid, led)
        self.externo(a, 13)
        self.assertTrue(publica.hecho(self.pid, a, pr=13)[0])
        self.assertEqual(vivas(self.pid, "sa"), [])


if __name__ == "__main__":
    unittest.main()

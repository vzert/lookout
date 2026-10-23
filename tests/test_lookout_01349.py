"""0.13.49: a vigente «Como retomar» is a relief, never a close. 3-tier-memory 2026-10-22, «Retomar diferente de
pendiente diario»: its last turn left a block citing p-3b9ad94124 (a pendiente the same session had just written down,
d398), lookout read it as vigente, and the supervisor opened d399 «¿Lo reinicio, lo dejo o cierro su pestaña?» with
«Cerrar su pestaña» recommended. d399 was opened between turns, just before the turn that left the block, and being
open when the block came it kept the agent out of «Te necesita». The user's rule: a pendiente written in the
same session is part of the agent's thread, so a vigente block is always relieved (`lookout relevo`, --goalspec).
Run: python3 -m unittest tests/test_lookout_01349.py
"""
import io
import os
import sys
import time
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_0130 as t130  # noqa: E402
import test_lookout_0137 as t137  # noqa: E402
import test_lookout_0139 as t139  # noqa: E402
import test_lookout_f3 as f3  # noqa: E402

import decisiones  # noqa: E402
import lookout_state  # noqa: E402
import registry  # noqa: E402

PEND = "p-3b9ad94124"
# the shape of its real block (the text shortened)
BLOQUE = ("Listo: la prueba del panel quedó cerrada.\n\n🔁 Como retomar:\n```\nRetomamos: enlazar main del checkout "
          "principal con origin/main y traer #65 y #66 id: %s\n```" % PEND)


class VigenteTest(t130.CierraPestanaTest):
    def vigente(self):
        self.pendientes("- [ ] main del checkout principal sin upstream — _id: %s_\n" % PEND)
        self.last(BLOQUE)
        lookout_state.append_event(self.pid, {"session_id": "s1", "event": "idle", "ts": time.time()})

    def pendientes(self, texto):
        os.makedirs(os.path.join(self.repo, "memory"), exist_ok=True)
        with open(os.path.join(self.repo, "memory", "_pendientes.md"), "w") as fh:
            fh.write(texto)
        f3.git(self.repo, "add", "memory")
        f3.git(self.repo, "commit", "-q", "-m", "m")
        f3.git(self.repo, "push", "-q")

    def decision(self, si_es="Cerrar su pestaña"):
        it = decisiones.abre(self.pid, "¿Lo reinicio, lo dejo o cierro su pestaña?", ["sidebar"], notificar=False,
                             si_es=si_es, tipo="cierre")
        t139.modal(self.pid, it["id"], si_es)
        return it["id"]

    def cierra_con(self, dn):
        e = registry.load(self.pid)["agents"]["s1"]
        return self.retiro.cierra(self.pid, e, "", fin_timeout=1, log=lambda m: None, confirmo=dn)

    def abre_cierre(self, cierre=True, extra=()):
        lk = t137.cli()
        lk.project = lambda arg: (self.pid, "")
        out = io.StringIO()
        argv = sys.argv
        sys.argv = ["lookout", "decision", self.pid, "--abre", "¿Cierro la pestaña de sidebar?", "--agentes",
                    "sidebar"] + (["--cierre", "--si-es", "Cerrar su pestaña"] if cierre else []) + list(extra)
        old = (lk.deliver.transcript_path, decisiones.herdr_cli.notifica)
        lk.deliver.transcript_path = self.retiro.deliver.transcript_path
        decisiones.herdr_cli.notifica = lambda *a, **k: None   # no real herdr notification from a test
        try:
            with redirect_stdout(out):
                rc = lk.main()
        finally:
            sys.argv = argv
            lk.deliver.transcript_path, decisiones.herdr_cli.notifica = old
        return rc, out.getvalue()

    def test_the_users_yes_to_close_does_not_close_a_vigente_block(self):
        self.vigente()
        ok, msg = self.cierra_con(self.decision())
        self.assertFalse(ok, msg)
        self.assertIn("lookout relevo", msg)
        self.assertIn(PEND, msg)
        self.assertNotIn(["agent", "prompt", "w1A:pE", "/exit"], self.calls)

    def test_without_the_yes_it_still_says_relief(self):
        self.vigente()
        ok, msg = self.cierra()
        self.assertFalse(ok, msg)
        self.assertIn("lookout relevo", msg)

    def test_once_its_pendiente_is_closed_it_closes(self):
        self.vigente()
        # the way out when the user really wants to drop that work: close or discard the pendiente first
        self.pendientes("- [x] main del checkout principal sin upstream — _id: %s_\n" % PEND)
        ok, msg = self.cierra()
        self.assertTrue(ok, msg)

    def test_an_ambiguo_block_still_closes_with_the_users_yes(self):
        self.vigente()
        self.last("Como retomar:\n```\nSigue con p-ffffffffff (recién creado).\n```")
        self.assertFalse(self.cierra()[0])
        ok, msg = self.cierra_con(self.decision())
        self.assertTrue(ok, msg)

    def test_a_failed_relief_can_still_be_closed_with_the_users_yes(self):
        self.vigente()
        reg = registry.load(self.pid)
        reg["agents"]["s1"]["tarea_estado"] = "relevo-fallido"
        registry.save(self.pid, reg)
        e = registry.load(self.pid)["agents"]["s1"]
        self.assertFalse(any("lookout relevo <" in f for f in self.retiro.revisa(self.pid, e, "", self.decision())))

    def test_a_close_question_is_not_opened_over_a_vigente_block(self):
        self.vigente()
        rc, out = self.abre_cierre()
        self.assertNotEqual(rc, 0, out)
        self.assertIn("NO ABIERTA", out)
        self.assertIn("lookout relevo", out)
        self.assertEqual([d for d in decisiones.load(self.pid).get("items") or () if d.get("tipo") == "cierre"], [])

    def test_a_question_without_cierre_over_a_vigente_block_says_relief_and_cannot_close(self):
        # codex r1: the generic --abre opens (a «¿Lo reinicio ya o espera?» is legitimate), says why it is not a close,
        # and its yes never authorizes cierra-pestana
        self.vigente()
        rc, out = self.abre_cierre(cierre=False)
        self.assertEqual(rc, 0, out)
        self.assertIn("OJO, sidebar", out)
        self.assertIn("lookout relevo", out)
        dn = decisiones.load(self.pid)["items"][-1]["id"]
        decisiones.cierra(self.pid, dn, "Cerrarla", True)
        self.assertFalse(self.cierra_con(dn)[0])

    def test_a_generic_question_with_si_es_over_a_vigente_block_needs_no_es_cierre(self):
        # codex r2: `--abre '¿Lo reinicio o cierro su pestaña?' --si-es 'Cerrar su pestaña'` without --cierre
        self.vigente()
        rc, out = self.abre_cierre(cierre=False, extra=["--si-es", "Cerrar su pestaña"])
        self.assertNotEqual(rc, 0, out)
        self.assertIn("NO ABIERTA", out)
        self.assertIn("--no-es-cierre", out)
        self.assertEqual(decisiones.load(self.pid).get("items") or [], [])
        # adversary r5: --nueva is what «ya hay decisiones» asks for (d399's agent had 16), so it waives nothing here
        prev = decisiones.abre(self.pid, "¿Algo previo?", ["sidebar"], notificar=False)
        decisiones.cierra(self.pid, prev["id"], "Sí", True)
        rc, out = self.abre_cierre(cierre=False, extra=["--si-es", "Cerrar su pestaña", "--nueva"])
        self.assertNotEqual(rc, 0, out)
        self.assertIn("--no-es-cierre", out)
        rc, out = self.abre_cierre(cierre=False, extra=["--si-es", "Sí, teclea aprobado", "--nueva", "--no-es-cierre"])
        self.assertEqual(rc, 0, out)
        self.assertIn("OJO, sidebar", out)

    def test_a_close_question_is_not_opened_while_it_is_mid_turn(self):
        self.vigente()
        # a close is not asked about before the turn's block can be read
        self.last(t130.SIDEBAR)
        lookout_state.append_event(self.pid, {"session_id": "s1", "event": "working", "ts": time.time()})
        rc, out = self.abre_cierre()
        self.assertNotEqual(rc, 0, out)
        self.assertIn("NO ABIERTA", out)
        self.assertIn("terminó su turno", out)

    def test_a_turn_that_ended_in_a_provider_error_is_not_mid_turn(self):
        # adversary r1: StopFailure writes pausa or unknown and no Stop follows
        self.last(t130.SIDEBAR)
        for ev in ("pausa", "unknown"):
            lookout_state.append_event(self.pid, {"session_id": "s1", "event": ev, "ts": time.time()})
            e = registry.load(self.pid)["agents"]["s1"]
            self.assertFalse(self.retiro.a_mitad_de_turno(self.pid, e), ev)
        rc, out = self.abre_cierre()
        self.assertEqual(rc, 0, out)

    def test_a_permission_dialog_is_mid_turn(self):
        # adversary r3: blocked (PermissionRequest), ask and negado wait inside the turn; its Stop is still to come
        self.last(t130.SIDEBAR)
        for ev in ("blocked", "ask", "negado"):
            lookout_state.append_event(self.pid, {"session_id": "s1", "event": ev, "ts": time.time()})
            e = registry.load(self.pid)["agents"]["s1"]
            self.assertTrue(self.retiro.a_mitad_de_turno(self.pid, e), ev)
        rc, out = self.abre_cierre()
        self.assertNotEqual(rc, 0, out)

    def test_a_close_question_opens_for_a_quiet_agent_with_no_vigente_block(self):
        self.vigente()
        self.last(t130.SIDEBAR)
        rc, out = self.abre_cierre()
        self.assertEqual(rc, 0, out)
        self.assertIn("abierta", out)


class AtiendeTest(unittest.TestCase):
    """A close decision does not attend a vigente block (d399); any other decision, and any for an ambiguo, does."""

    def ev(self, estado):
        return {"event": "idle", "ts": 100.0, "nombre": "uno", "retomar": {"estado": estado, "pendientes": [PEND]}}

    def test_a_close_decision_opened_before_a_vigente_block_does_not_attend_it(self):
        import heuristicas
        cierre = [{"id": "d399", "agentes": ["uno"], "estado": "abierta", "desde": 90.0, "tipo": "cierre"}]
        otra = [{"id": "d400", "agentes": ["uno"], "estado": "abierta", "desde": 90.0}]
        self.assertTrue(heuristicas.bloque_sin_atender(self.ev("vigente"), None, cierre))
        self.assertIsNone(heuristicas.bloque_sin_atender(self.ev("vigente"), None, otra))
        self.assertIsNone(heuristicas.bloque_sin_atender(self.ev("ambiguo"), None, cierre))


if __name__ == "__main__":
    unittest.main()

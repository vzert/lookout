"""0.13.9: a close the user decided. 3-tier-memory 2026-10-16, «Corrección snipet de cierre»: its «Como retomar» said
«Ninguno» and cited a pendiente waiting for a date, so lookout read it as `vigente` (a relief without asking); the user
answered «Cerrarla» in the supervisor's modal (d111) and `cierra-pestana` still refused, on the block and on a «¿» of
its own text («**¿Cerrado?** Sí.», an issue title).
Run: python3 -m unittest tests/test_lookout_0139.py
"""
import argparse
import os
import re
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_0130 as t130  # noqa: E402

import decisiones  # noqa: E402
import registry  # noqa: E402
import retomar  # noqa: E402

# its last turn, the parts that count (word for word, the project path shortened)
SNIPPET = """**¿Cerrado?** Sí.

Título: [3-tier-memory] ¿Filtrar la línea de extras bajó las preguntas del usuario?

🔁 Como retomar: Ninguno — 2.61.0 quedo publicado y verde en las tres plataformas; medir su efecto en cierres reales (p-f8df9ea916) espera a que se acumulen cierres, con recordatorio el 2026-10-22.

➕ Opcional — otra sesión, si tienes tiempo:
Proyecto: 3-tier-memory — /x/3-tier-memory
Retomamos: Mirar si las negativas de learning.update de 2.31.1 aparecen en cuarentenas reales de otros proyectos id: p-ce00d61406
Motivo: vencido desde 2026-09-26
Si ya no aplica, cierralo con /checkpoint-3t en vez de dejarlo abierto."""


SIN_HACER = ("Como retomar: Ninguno — p-0000000001 sigue abierto, hay que revisarlo el 2026-10-22.",
             "Como retomar: Ninguno — publicado el 2026-10-16; p-0000000001 sin resolver.",
             "Como retomar: Ninguno — resta mergear p-0000000001 (2026-10-20).",
             "Como retomar: Ninguno — aún no cerré p-0000000001 (2026-10-20).",
             "Como retomar: None — need to finish p-0000000001 by 2026-10-20.",
             "Como retomar: Ninguno — queda p-0000000001. Recordatorio 2026-10-22",
             "Como retomar: Ninguno — remaining: p-0000000001, reminder 2026-10-22",
             "Como retomar: Ninguno — p-0000000001 vencido desde 2026-09-26.",
             "Como retomar: Ninguno — p-0000000001 no está hecho; recordatorio el 2026-10-22",
             "Como retomar: Ninguno — p-0000000001 espera a que Víctor conteste; 2026-10-22",
             "Como retomar: Ninguno — falta cerrar p-0000000001.",  # adversary round 3 (sonnet), and 0.13.8's own
             # adversary round 4 (sonnet): any punctuation or formatting after the word
             "Como retomar: Ninguno, p-f8df9ea916 espera a que se acumulen cierres.",
             "Como retomar: Ninguno. p-f8df9ea916 espera.",
             "Como retomar: Ninguno: p-f8df9ea916.",
             "Como retomar: Ninguno (p-f8df9ea916 espera a la fecha).",
             "Como retomar: Ninguno, salvo p-f8df9ea916.",
             "Como retomar: **Ninguno** — p-f8df9ea916.",
             "Como retomar: `Ninguno` — p-f8df9ea916.",
             "Como retomar: Ninguno\u00a0— p-f8df9ea916.",
             # adversary round 5 (sonnet): underscores, the pendiente on the next line, a header with no colon
             "Como retomar: _Ninguno_, p-f8df9ea916",
             "Como retomar: Ninguno_ p-f8df9ea916",
             "Como retomar: Ninguno.\nPendiente p-f8df9ea916 espera a la fecha.",
             "Como retomar: Nada\np-f8df9ea916",
             "## Como retomar — Ninguno\nmedir p-f8df9ea916 cuando se acumulen.",
             "**Como retomar** — Ninguno, p-f8df9ea916")


class NingunoConPendienteTest(unittest.TestCase):
    """The user's rule (2026-10-16): a «Ninguno» that cites an open pendiente goes to the user's modal, whatever its words."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.tmp.name, "memory"))
        with open(os.path.join(self.tmp.name, "memory", "_pendientes.md"), "w") as fh:
            fh.write("- [ ] medir — _id: p-f8df9ea916_\n- [ ] otro — _id: p-0000000001_\n- [x] viejo — _id: p-0000000002_\n")

    def tearDown(self):
        self.tmp.cleanup()

    def info(self, text):
        return retomar.info(text, 1.0, [self.tmp.name], [])

    def test_the_real_block_and_every_wording_go_to_the_modal(self):
        for text in (SNIPPET,) + SIN_HACER:
            self.assertNotEqual(retomar.bloque(text)[0], "nada", text)
            r = self.info(text)
            self.assertEqual((r["estado"], r["motivo"]), ("ambiguo", retomar.NINGUNO_CITA), text)   # 0.13.8: vigente

    def test_a_plain_ninguno_is_still_nothing(self):
        for text in ("Como retomar: Ninguno — todo quedó en main.", "🔁 Como retomar: Ninguno",
                     "## Como retomar — Ninguno\nTodo quedó en main."):
            self.assertEqual(retomar.bloque(text)[0], "nada", text)

    def test_a_ninguno_that_cites_only_closed_ones_is_still_finished(self):
        r = self.info("Como retomar: Ninguno — p-0000000002 quedó cerrado.")
        self.assertTrue(r["motivo"].startswith(retomar.CERRADO), r)


def modal(pid, dn, respuesta, tu="tu1"):
    """The user answers decision dn in the supervisor's modal, as its hooks write it down."""
    q = "¿Qué hago con su pestaña? (%s)" % dn
    decisiones.registra_pregunta(pid, tu, [q])
    decisiones.registra_respuesta(pid, tu, respuesta, por_pregunta={q: respuesta})


class SiPorElHookTest(t130.f3.Base):
    """C7: the user's yes is written by the modal's hook (live 3-tier 2026-10-16: auto mode denied the supervisor's own
    `lookout decision --cierra d113 … --si` as «Auto-Mode Bypass», and nothing could be typed)."""

    def test_the_hook_closes_it_with_the_users_literal_choice(self):
        si = decisiones.abre(self.pid, "¿Tecleo «aprobado» en uno?", ["uno"], notificar=False, si_es="Sí, tecléalo")
        no = decisiones.abre(self.pid, "¿Tecleo «aprobado» en dos?", ["dos"], notificar=False, si_es="Sí, tecléalo")
        modal(self.pid, si["id"], "Sí, tecléalo", "t1")
        modal(self.pid, no["id"], "No, todavía no", "t2")
        items = {it["id"]: it for it in decisiones.load(self.pid)["items"]}
        self.assertEqual((items[si["id"]]["estado"], items[si["id"]]["aprueba"], items[si["id"]].get("por_hook")),
                         ("respondida", True, True))
        self.assertEqual((items[no["id"]]["estado"], items[no["id"]]["aprueba"]), ("respondida", False))
        self.assertTrue(decisiones.respondida(self.pid, si["id"]))
        self.assertIsNone(decisiones.respondida(self.pid, no["id"]))

    def test_without_si_es_nothing_changes(self):
        it = decisiones.abre(self.pid, "¿x?", ["uno"], notificar=False)
        modal(self.pid, it["id"], "Sí")
        self.assertEqual(decisiones.load(self.pid)["items"][-1]["estado"], "abierta")


class CierreDecididoTest(t130.CierraPestanaTest):
    def decision(self, respuesta="Cerrarla (Recomendado)", agentes=("sidebar",), cierre=True, hook=True):
        it = decisiones.abre(self.pid, "¿Cierro la pestaña de sidebar?", agentes, notificar=False,
                             si_es="Cerrarla (Recomendado)" if hook else "", tipo="cierre" if cierre else "")
        modal(self.pid, it["id"], respuesta)
        if not hook:
            decisiones.cierra(self.pid, it["id"], respuesta, True)   # the supervisor's own --cierra --si
        return it["id"]

    def cierra_con(self, dn):
        e = registry.load(self.pid)["agents"]["s1"]
        return self.retiro.cierra(self.pid, e, "", fin_timeout=1, log=lambda m: None, confirmo=dn)

    def test_the_real_block_closes_with_the_users_yes_and_not_without(self):
        self.last(SNIPPET)
        self.assertFalse(self.cierra()[0])
        ok, msg = self.cierra_con(self.decision())
        self.assertTrue(ok, msg)

    def test_any_label_the_user_picked_works(self):
        self.last(SNIPPET)
        it = decisiones.abre(self.pid, "¿Cierro sidebar?", ["sidebar"], notificar=False, si_es="Sí, ciérrala",
                             tipo="cierre")
        modal(self.pid, it["id"], "Sí, ciérrala")
        self.assertTrue(self.cierra_con(it["id"])[0])   # adversary r4: the accented imperative was refused

    def test_only_a_close_decision_the_hook_approved_closes(self):
        self.last("Listo. ¿Quieres que despliegue a producción ahora?")
        for nombre, dn in (("otra opción", self.decision(respuesta="Dejarla")),
                           ("no es de cierre", self.decision(cierre=False)),
                           ("sí del supervisor", self.decision(hook=False)),
                           ("otro agente", self.decision(agentes=("otro",))), ("no existe", "d99")):
            self.assertFalse(self.cierra_con(dn)[0], nombre)
        viejo = self.decision()
        ahora = time.time()   # a newer turn of the agent after the user's answer
        self.transcript("s1", [t130.u_text("sigue", ahora + 1), t130.a_text("Listo. ¿Despliego a producción?", ahora + 2)])
        self.assertFalse(self.cierra_con(viejo)[0])

    def test_the_users_yes_skips_the_block_and_question_checks(self):
        self.last(t130.NINGUNO_EN_EL_CUERPO + "\n¿Cerrado? Sí.")
        self.assert_no("es un relevo")
        ok, msg = self.cierra_con(self.decision())
        self.assertTrue(ok, msg)
        self.assertEqual(self.calls[-1], ["tab", "close", "w1A:tE"])

    def test_the_users_yes_never_skips_git_or_the_box(self):
        self.last(t130.NINGUNO_EN_EL_CUERPO)
        dn = self.decision()
        with open(os.path.join(self.repo, "a.txt"), "a") as fh:
            fh.write("b\n")
        ok, msg = self.cierra_con(dn)
        self.assertFalse(ok)
        self.assertIn("cambios sin commit", msg)
        self.box = "borrador"
        self.assertIn("caja", self.cierra_con(dn)[1])


SKILL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins", "lookout", "skills",
                     "supervisa", "SKILL.md")


class TextosConElSiDelHookTest(unittest.TestCase):
    """Adversary r6 (codex): the texts still told the supervisor to authorize with `--cierra … --si`, the command auto
    mode denied for d113. Every flow where a yes authorizes something opens the decision with --si-es."""

    def test_the_skill_never_asks_for_the_supervisors_si(self):
        with open(SKILL, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        # a `--si` that authorizes, not --si-es and not the --si|--no of a decision opened without it
        malas = [ln for ln in lines if re.search(r"--si(?![-|\w])", ln)
                 and not re.search(r"no corras|no sirve|un `--cierra --si` tuyo", ln)]
        self.assertEqual(malas, [])

    def test_every_text_that_opens_a_decision_names_si_es(self):
        # adversary r7 (codex): the push, the extra round, cierra, descarta and libera still said `--abre` alone
        bindir = os.path.join(os.path.dirname(SKILL), "..", "..", "bin")
        sin = []
        for name in sorted(os.listdir(bindir)):
            if not (name.endswith(".py") or name == "lookout"):
                continue
            with open(os.path.join(bindir, name), encoding="utf-8") as fh:
                lines = fh.read().splitlines()
            for i, ln in enumerate(lines):
                if not ("--abre" in ln or "lookout decision`" in ln) or ln.lstrip().startswith(("#", "p.add_argument", "p = sub")):
                    continue
                if '"""' in ln or "- 0.12.0" in ln or "as a close" in ln:
                    continue  # docstrings (adversary r9: the escalation of heuristicas.py counts too)
                if "--si-es" not in " ".join(lines[i:i + 3]):
                    sin.append("%s:%d" % (name, i + 1))
        # adversary r8 (codex): the skills too
        for skill in ("supervisa", "pendientes"):
            with open(os.path.join(os.path.dirname(os.path.dirname(SKILL)), skill, "SKILL.md"), encoding="utf-8") as fh:
                lines = fh.read().splitlines()
                for i, ln in enumerate(lines):
                    if (re.search(r"lookout decision[^`]*--abre|abres? la decisión|bloque de decisión", ln)
                            and "--si-es" not in " ".join(lines[i:i + 2]) and "El texto de" not in ln
                            and "NO ABIERTA" not in ln):
                        sin.append("%s/SKILL.md:%d" % (skill, i + 1))
        self.assertEqual(sin, [])

    def test_the_hooks_yes_is_the_label_exactly(self):
        # adversary r7 (codex): « Cerrar » and «Cerrar\n» were taken as the label «Cerrar»
        import test_lookout_0137 as t137
        for respuesta, aprueba in (("Cerrar", True), (" Cerrar ", False), ("Cerrar\n", False), ("cerrar", False)):
            t = t137.EnviaDelUsuarioTest()
            t.setUp()
            try:
                it = decisiones.abre(t137.PID, "¿Cierro su pestaña?", ["uno"], notificar=False, si_es="Cerrar")
                q = "¿Cierro su pestaña? (%s)" % it["id"]
                decisiones.registra_pregunta(t137.PID, "tu1", [q])
                decisiones.registra_respuesta(t137.PID, "tu1", respuesta, por_pregunta={q: respuesta})
                d = next(x for x in decisiones.load(t137.PID)["items"] if x["id"] == it["id"])
                self.assertEqual(d.get("aprueba"), aprueba, repr(respuesta))
            finally:
                t.tearDown()

    def test_the_label_is_kept_as_given(self):
        # adversary r10 (codex): the label was stripped when stored, so « Cerrar » never matched « Cerrar »
        import test_lookout_0137 as t137
        t = t137.EnviaDelUsuarioTest()
        t.setUp()
        try:
            it = decisiones.abre(t137.PID, "¿Cierro su pestaña?", ["uno"], notificar=False, si_es=" Cerrar ")
            q = "¿Cierro su pestaña? (%s)" % it["id"]
            decisiones.registra_pregunta(t137.PID, "tu1", [q])
            decisiones.registra_respuesta(t137.PID, "tu1", " Cerrar ", por_pregunta={q: " Cerrar "})
            d = next(x for x in decisiones.load(t137.PID)["items"] if x["id"] == it["id"])
            self.assertIs(d.get("aprueba"), True)
            self.assertNotIn("si_es", decisiones.abre(t137.PID, "¿Otra?", ["uno"], notificar=False, si_es="  "))
        finally:
            t.tearDown()

    def test_the_refusals_point_at_si_es(self):
        import test_lookout_0137 as t137
        import contextlib
        import io

        class T(t137.EnviaDelUsuarioTest):
            def runTest(self):
                pass
        t = T()
        t.setUp()
        try:
            for run in (lambda: t.envia("! git push origin lookout/uno", ""),
                        lambda: t.lk.cmd_gobierno(argparse.Namespace(proyecto=t137.PID, agente="uno", usuario_amplia=1,
                                                                     decision="", para="")),
                        lambda: t.lk.cmd_decision(argparse.Namespace(proyecto=t137.PID, abre="¿Publico?", agentes="uno",
                                                                     si_es="", cierre=False, nueva=False, cierra=None,
                                                                     respuesta=None, si=False, no=False, lista=False))):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    run()
                self.assertIn("--si-es", out.getvalue())
        finally:
            t.tearDown()


if __name__ == "__main__":
    unittest.main()

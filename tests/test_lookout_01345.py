"""0.13.45: the supervisor talks to the user in plain words. A user of the plugin (Valdespin, 2026-10-20) got a message
of ~1900 characters that cited «d116» and «d119», said «waiter», «rebase», «hooks viejos» and «bloques de relevo», asked
in prose to relieve four tabs and to reload hooks the skill says to handle without asking, and left the one thing he had
to type in the middle of a paragraph. He answered «MIRA NO ENTIENDO JAJAJA … Q ES EL WAITER». The skill now has a
section «Cómo hablarle al usuario»: what the user must do goes last (the chat scrolls, the last line is read first), the
text he must type goes in a code block, no decision ids or plugin words in the chat, and what the supervisor handles by
itself is not listed. The herdr notification of an unattended block says it in plain words too.
Run: python3 -m unittest tests/test_lookout_01345.py
"""
import os
import re
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_01332 as t32  # noqa: E402

import heuristicas  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUPERVISA = os.path.join(RAIZ, "plugins", "lookout", "skills", "supervisa", "SKILL.md")
PENDIENTES = os.path.join(RAIZ, "plugins", "lookout", "skills", "pendientes", "SKILL.md")


def leer(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def seccion(texto, titulo):
    m = re.search(r"^## %s\n(.*?)(?=^## )" % re.escape(titulo), texto, re.S | re.M)
    return m.group(1) if m else ""


class SeccionHablarTest(unittest.TestCase):
    def setUp(self):
        self.skill = leer(SUPERVISA)
        self.sec = seccion(self.skill, "Cómo hablarle al usuario")

    def test_the_section_exists_before_the_start(self):
        self.assertTrue(self.sec, "falta la sección «## Cómo hablarle al usuario»")
        self.assertLess(self.skill.index("## Cómo hablarle al usuario"), self.skill.index("## Arranque"))

    def test_what_the_user_must_do_goes_last(self):
        self.assertIn("al final", self.sec)
        self.assertIn("Lo que necesito de ti", self.sec)
        self.assertIn("Nada va después", self.sec)                  # measured: both runs added a line after it

    def test_text_to_type_goes_in_a_code_block(self):
        self.assertIn("bloque de código", self.sec)

    def test_no_decision_ids_or_plugin_words_in_the_chat(self):
        for palabra in ("d116", "waiter", "hook", "pane", "rebase", "relevo"):
            self.assertIn(palabra, self.sec, palabra)              # each one named, with its plain words

    def test_what_it_handles_alone_is_not_listed(self):
        self.assertIn("sin preguntar", self.sec)

    def test_an_unknown_word_gets_a_plain_answer(self):
        self.assertIn("qué es", self.sec.lower())

    def test_a_denied_envia_puts_the_text_last_in_a_code_block(self):
        # the Valdespin case: auto mode denied `lookout envia`, so the user had to type it himself
        self.assertIn("lookout envia", self.sec)

    def test_no_template_for_the_user_carries_plugin_words(self):
        # adversary r1: «una línea al usuario («Relevé <pestaña>: sigue con p-…, con goalspec …»)» survived, and haiku
        # wrote «Relevé» in the measured Valdespin message; the modal's «Relevarlo» label was user-facing too
        for viejo in ("Relevé", "«Relevarlo»", "Di en tu línea al usuario cuál elegiste", "«¿relevo, cierro o lo dejo?»"):
            self.assertNotIn(viejo, self.skill)

    def test_the_code_names_the_same_ambiguous_question_as_the_skill(self):
        # adversary r2: retomar.accion() and retiro's brake still gave the supervisor «¿relevo, cierro o lo dejo?»
        import retiro
        import retomar
        pregunta = "«¿Lo reinicio para que siga, cierro su pestaña o lo dejo?»"
        self.assertIn(pregunta, self.skill)
        self.assertIn(pregunta, retomar.accion({"estado": "ambiguo", "motivo": ""}))
        self.assertIn(pregunta, retiro.RELEVO_NO_CIERRE)

    def test_every_tell_the_user_order_and_modal_example_follows_the_section(self):
        # three rounds each found one more line («Relevé», the ambiguous question, `lookout permisos`): the section says
        # it governs every «dile/pásale» order and every «» modal example, and no modal example in skills or bin says
        # «¿relevo»
        self.assertIn("«dile», «díselo», «pásale» o «avisa»", self.sec)
        self.assertIn("preguntas de modal", self.sec)
        for base in (os.path.join(RAIZ, "plugins", "lookout", "skills"), os.path.join(RAIZ, "plugins", "lookout", "bin")):
            for d, _, files in os.walk(base):
                for f in files:
                    with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                        self.assertNotIn("«¿relevo", fh.read(), os.path.join(d, f))

    def test_modal_questions_carry_no_pendiente_ids(self):
        # adversary r3: «Ids (`p-…`, `#PR`, commits) solo al final» and pendientes' «id, agente y dónde trabaja»
        self.assertNotIn("Ids (`p-…`, `#PR`, commits) solo al final", self.skill)
        self.assertNotIn("entre paréntesis, id, agente y dónde trabaja", leer(PENDIENTES))
        self.assertIn("lookout exige ver en la pregunta", self.sec)   # the (dN), a permission's command, a push URL, #N

    def test_the_notification_points_to_the_supervisor_who_explains(self):
        self.assertIn("ese aviso solo le dice que abra tu pestaña", self.skill)

    def test_claude_code_modes_and_git_places_are_explained(self):
        # codex r4: modal instructions said «bypass», «plan», «Shift+Tab», «main», «worktree» unexplained
        for palabra in ("bypass", "Shift+Tab", "worktree", "main"):
            self.assertIn(palabra, self.sec, palabra)
        self.assertNotIn("(pestaña en main o el worktree que pidió el usuario)", leer(PENDIENTES))
        self.assertIn("Lanzar sin pedir permisos (bypass)", leer(PENDIENTES))
        # the MODO: line bin/modo.py gives the supervisor names the same option (run, not read)
        import modo
        viejos = modo.clase, modo.del_supervisor
        modo.clase, modo.del_supervisor = (lambda _m: "bypass"), (lambda _p: {})
        try:
            linea = modo.aviso_lanzar("x")
        finally:
            modo.clase, modo.del_supervisor = viejos
        self.assertIn("«Lanzar sin pedir permisos (bypass), como el supervisor»", linea)

    def test_merge_and_rebased_copy_questions_are_plain(self):
        # codex r5: «¿Fusiono el PR #<N> (…) en main?» and «lo que dice range-diff» went to the user; the merge hint in
        # publica.py is the same template, so it changes with the skill
        publica_src = leer(os.path.join(RAIZ, "plugins", "lookout", "bin", "publica.py"))
        for viejo in ("en main?»", "lo que dice range-diff>"):
            self.assertNotIn(viejo, self.skill)
        self.assertNotIn("¿Fusiono el PR #%d", publica_src)
        self.assertIn("¿Junto el cambio #<N>", self.skill)
        self.assertIn("¿Junto el cambio #%d", publica_src)
        self.assertIn("la versión principal del proyecto", self.sec)

    def test_the_permisos_output_is_not_copied_to_the_user(self):
        # codex r1: «pásale al usuario lo que imprime `lookout permisos`» sent paths, `activo = true` and `lookout aprueba`
        self.assertNotIn("pásale al usuario lo que\n  imprime `lookout permisos`", self.skill)
        self.assertIn("no le copies la salida de `lookout permisos`", self.skill)

    def test_the_ambiguous_row_fits_the_digest_with_a_long_tab(self):
        # the digest clips a row at MAX_COLS; the question must survive whole with a long tab name (codex r2: «152
        # medidos» had no test). Same shape as digest.py builds it: «  <quien> | bloque ambiguo HH:MM:SS → <accion>»
        import digest
        import retomar
        quien = "Empresas con crédito aprobado (empresas-credito-aprobado)"
        fila = "  %s | bloque ambiguo 12:34:56 → %s" % (quien, retomar.accion({"estado": "ambiguo", "motivo": ""}))
        self.assertLessEqual(len(fila), digest.MAX_COLS, len(fila))

    def test_the_start_table_has_no_branch_column(self):
        self.assertNotIn("rama/worktree, estado", self.skill)

    def test_pendientes_points_to_the_section(self):
        self.assertIn("Cómo hablarle al usuario", leer(PENDIENTES))


class AvisoDeBloqueTest(t32.Base):
    def test_the_block_notification_is_plain(self):
        self.agent("s1", "ag")
        t = time.time()
        self.ev("idle", t, retomar={"estado": "vigente", "pendientes": ["p-0ccd79fe36"], "bloque_id": "b1",
                                     "motivo": ""})
        heuristicas.avisa_bloques(t32.PID, t + 31 * 60)
        self.assertEqual(len(self.avisos), 1)
        texto = " ".join(self.avisos[0])
        for jerga in ("«Como retomar»", "relev", "vigente", "p-0ccd79fe36", "sin pendiente"):   # codex r1: no ids
            self.assertNotIn(jerga, texto)
        self.assertIn("31 min", texto)
        self.assertTrue(self.avisos[0][2].startswith("Supervisor: "), self.avisos[0])


class TituloDeAvisosTest(unittest.TestCase):
    """codex r2 + the user's choice (2026-10-20): a herdr notification's title starts «Supervisor:», the tab the user
    sees, not «lookout:», the plugin's name. Every notifica()/notify() call in bin/ is read from the code, so a new one
    has to follow too."""

    def test_notifica_itself_titles_every_notification_supervisor(self):
        # adversary r5: a regex over call lines missed a wrapped call, a title built in a variable, single quotes and
        # «Lookout:»; herdr_cli.notifica is the one path to `notification show`, so it sets the prefix itself
        import herdr_cli
        vistos = []
        viejo = herdr_cli.run
        herdr_cli.run = lambda args, timeout=None, **kw: (vistos.append(args), (0, "", ""))[1]
        try:
            for t in ("lookout: uno pide permiso", "Lookout: dos", "uno te necesita", "Supervisor: ya lo trae",
                      "  lookout:tres"):
                herdr_cli.notifica(None, "transicion", t, "cuerpo", sound=None)
        finally:
            herdr_cli.run = viejo
        titulos = [a[2] for a in vistos]
        self.assertEqual(titulos, ["Supervisor: uno pide permiso", "Supervisor: dos", "Supervisor: uno te necesita",
                                   "Supervisor: ya lo trae", "Supervisor: tres"])

    def test_no_notification_title_starts_with_lookout(self):
        binp = os.path.join(RAIZ, "plugins", "lookout", "bin")
        llamadas = 0
        for f in sorted(os.listdir(binp)):
            p = os.path.join(binp, f)
            if not os.path.isfile(p):
                continue
            texto = leer(p)
            for m in re.finditer(r"(?:notifica|notify)\((.*?)\n", texto):
                if "def " in texto[max(0, m.start() - 4):m.start()]:
                    continue
                llamadas += 1
                self.assertNotIn('"lookout: ', m.group(1), "%s: %s" % (f, m.group(0)))
        self.assertGreaterEqual(llamadas, 6)

    def test_no_notification_names_a_tab_that_may_not_exist(self):
        # codex r3: `inicia` keeps a supervisor tab the user already named, so «la pestaña «Supervisor»» can point to
        # a tab that does not exist
        for f in ("heuristicas.py", "lookout"):
            self.assertNotIn("pestaña «Supervisor»", leer(os.path.join(RAIZ, "plugins", "lookout", "bin", f)), f)

    def test_the_titles_say_supervisor(self):
        for f, s in (("heuristicas.py", '"Supervisor: %s tiene trabajo por seguir"'),
                     ("decisiones.py", '"Supervisor: tienes una decisión pendiente"'),
                     ("permisos.py", '"Supervisor: %s pide permiso"'),
                     ("lookout", '"Supervisor: necesito que me reinicies"')):
            self.assertIn(s, leer(os.path.join(RAIZ, "plugins", "lookout", "bin", f)), f)


class AvisoDeTransicionTest(t32.Base):
    """adversary r3: the herdr notification of an agent entering «Te necesita» or «Listo» carried digest.describe(), the
    supervisor's own line («→ corrección 1 de 2: `lookout corrige …`», «ESPERA ALGO TECLEADO EN SU PANE … dN …
    `lookout envia`»). The user gets a plain sentence that sends him to the supervisor's tab."""

    CASOS = {
        "repite": dict(event="repite", veces=3, firma="Bash git x falla", intentos=["a", "b"], correcciones=0),
        "replantea": dict(event="repite", veces=3, firma="f", intentos=["a"], replantea=True, correcciones=2),
        "sin_progreso": dict(event="sin_progreso", nivel="escalar", hace_s=2400, fuentes=["herdr", "transcript"]),
        "espera_pane": dict(event="idle", ultima="listo", espera_pane={"motivo": "gate", "cita": "aprobado"}),
    }

    def test_the_transition_notification_is_plain(self):
        self.agent("s1", "ag")
        vistos = 0
        for nombre, kw in self.CASOS.items():
            gp = heuristicas.grupos_path(t32.PID)
            if os.path.exists(gp):
                os.remove(gp)
            self.avisos.clear()
            e = self.ev(kw.pop("event"), time.time(), **kw)
            heuristicas.transicion(t32.PID, e)
            if not self.avisos:
                continue
            vistos += 1
            texto = " ".join(self.avisos[0])
            for jerga in ("lookout ", "pane", "PANE", "dN", "--", "→", "SendMessage"):
                self.assertNotIn(jerga, texto.split("--body", 1)[-1], (nombre, texto))
            self.assertIn("pestaña del supervisor", texto, nombre)
            self.assertNotIn("«Supervisor»", texto, nombre)   # codex r3: a tab the user named keeps its name
            self.assertTrue(self.avisos[0][2].startswith("Supervisor: "), self.avisos[0])
        self.assertGreaterEqual(vistos, 3)                            # the cases do reach the user


if __name__ == "__main__":
    unittest.main()

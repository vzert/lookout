"""0.13.12: the supervisor approves an agent's permission dialog only after the user's yes in its modal.

Live case (hook-para-checkpoint, 2026-10-17 11:17, auto mode): the user said yes in the supervisor's modal and still
had to go to the agent's pane, because the SKILL said «you never approve permissions». Now the yes is the user's,
written by the modal's hook on a `--permiso` decision tied to the agent's pending PermissionRequest (its full
command), and `lookout aprueba` presses the option «Yes» (never «Yes, and don't ask again», never «switch to auto
mode») only when the dialog on screen, read by structure, shows exactly that command.

The dialogs below were captured from Claude Code 2.1.302 on 2026-10-17 (tests/fixtures/permiso/): 98 columns (a wrap
eats the space), 39 columns (a wrap cuts mid-word), 196 columns with a 1078-character command, and the same command at
39 columns, where the header and the start of the command fall off the visible screen.
Run: python3 -m unittest tests/test_lookout_01312.py
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_0139 as t139  # noqa: E402
import test_lookout_f3 as f3  # noqa: E402

import aprueba  # noqa: E402
import decisiones  # noqa: E402
import lookout_state  # noqa: E402
import permisos  # noqa: E402
import registry  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "permiso")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


ANCHO, ESTRECHO = fixture("ancho-98.txt"), fixture("estrecho-39.txt")
LARGO, LARGO_CORTADO = fixture("largo-196.txt"), fixture("largo-39-sin-cabecera.txt")
SIN_BARRA = fixture("sin-barra-39.txt")   # two Bash calls in one message: the command lines carry no bar
CORTO = "git push origin HEAD:refs/heads/prueba-del-dialogo-de-permiso-ancho-y-estrecho-de-lookout-0-13-12"
LARGO_CMD = "git push origin HEAD:refs/heads/largo2 " + " ".join(
    "-o opcion%02d=valor-largo-de-relleno-para-ver-recorte" % i for i in range(20))
# what the agent's pane shows before the dialog: its prompt box and footer
CAJA = "⏺ listo\n────────\n❯ \n────────\n  ⏸ manual mode on\n"


def modal(pid, dn, respuesta, pregunta, tu="tp1"):
    """The user answers decision dn in the supervisor's modal, as its hooks write it down (the question as shown)."""
    q = "%s (%s)" % (pregunta, dn)
    decisiones.registra_pregunta(pid, tu, [q])
    decisiones.registra_respuesta(pid, tu, respuesta, por_pregunta={q: respuesta})


class DialogoTest(unittest.TestCase):
    def test_wide_and_narrow_are_read_by_structure(self):
        for nombre, texto in (("98", ANCHO), ("39", ESTRECHO)):
            d = aprueba.dialogo_permiso(texto)
            self.assertIsNotNone(d, nombre)
            self.assertEqual(d["si"], "1", nombre)
            self.assertTrue(aprueba.coincide(CORTO, d), nombre)
        d = aprueba.dialogo_permiso(LARGO)
        self.assertTrue(aprueba.coincide(LARGO_CMD, d))
        self.assertEqual(len(LARGO_CMD), 1078)

    def test_the_form_without_the_bar(self):
        d = aprueba.dialogo_permiso(SIN_BARRA)
        self.assertEqual((d["si"], d["prefijo"]), ("1", 1))
        self.assertTrue(aprueba.coincide("git push origin HEAD:refs/heads/par-uno", d))
        self.assertFalse(aprueba.coincide("git push origin HEAD:refs/heads/par-dos", d))
        mezcla = ANCHO.replace(" │ git push origin\n", " git push origin\n")
        self.assertIsNone(aprueba.dialogo_permiso(mezcla))   # one form per block

    def test_a_wrap_eats_one_space_and_only_where_the_next_word_did_not_fit(self):
        # adversary r2 (codex): two or three spaces at a wrap matched too
        d = aprueba.dialogo_permiso(ANCHO)
        for otro in (CORTO.replace("origin HEAD", "origin  HEAD"), CORTO.replace("origin HEAD", "origin   HEAD"),
                     CORTO.replace("origin HEAD", "origin\nHEAD"), CORTO.replace("origin HEAD", "origin\tHEAD")):
            self.assertFalse(aprueba.coincide(otro, d), repr(otro))
        # a short line whose next word would have fitted did not wrap there: it is not this command
        partido = {"lineas": ["git push", "origin x"], "ancho": 94, "prefijo": 3}
        self.assertFalse(aprueba.coincide("git push origin x", partido))
        d = aprueba.dialogo_permiso(ESTRECHO)
        self.assertFalse(aprueba.coincide(CORTO.replace("heads/p", "heads/ p"), d) and
                         aprueba.coincide(CORTO.replace("heads/p", "heads/  p"), d))
        self.assertFalse(aprueba.coincide(CORTO.replace("heads/p", "heads/  p"), d))

    def test_a_command_with_a_newline_is_never_matched(self):
        d = {"lineas": ["git status", "git push"], "ancho": 94, "prefijo": 3}
        self.assertFalse(aprueba.coincide("git status\ngit push", d))

    def test_a_dialog_whose_head_is_off_screen_is_not_read(self):
        # 39 columns: the 1078-character command pushes «Bash command» and «git push origin» off the visible screen
        self.assertIsNone(aprueba.dialogo_permiso(LARGO_CORTADO))

    def test_any_other_command_does_not_match(self):
        lineas = aprueba.dialogo_permiso(ESTRECHO)
        for otro in (CORTO.replace("ancho", "anxho"), CORTO + " --force", CORTO[:-1], "x" + CORTO,
                     CORTO.replace("origin HEAD", "origin  HEAD").replace("dialogo", "dia logo"), "", CORTO + "\n"):
            self.assertFalse(aprueba.coincide(otro, lineas), repr(otro))
        lineas = aprueba.dialogo_permiso(ANCHO)
        self.assertFalse(aprueba.coincide(CORTO.replace("origin HEAD", "originHEAD"), lineas))
        self.assertTrue(aprueba.coincide(CORTO, lineas))

    def test_yes_is_found_by_its_label_not_its_place(self):
        swapped = ANCHO.replace("❯ 1. Yes\n", "❯ 1. Yes, and don’t ask again for: git push *\n").replace(
            "   2. Yes, and don’t ask again for: git push *\n", "   2. Yes\n")
        self.assertEqual(aprueba.dialogo_permiso(swapped)["si"], "2")
        for sin_si in (ANCHO.replace("❯ 1. Yes\n", "❯ 1. Yes, sure\n"),
                       ANCHO.replace("   4. No\n", "   4. Yes\n")):   # two «Yes»: which one?
            self.assertIsNone(aprueba.dialogo_permiso(sin_si))

    def test_the_dialog_has_its_top_border(self):
        # adversary r1 (codex): text shaped like the dialog in earlier output is not the dialog
        sin_borde = ANCHO.split("\n", 1)[1]
        self.assertIsNone(aprueba.dialogo_permiso(sin_borde))
        self.assertIsNone(aprueba.dialogo_permiso("salida vieja\n" + sin_borde))
        self.assertIsNone(aprueba.dialogo_permiso(ANCHO.replace("─" * 95, "─" * 60, 1)))
        self.assertIsNotNone(aprueba.dialogo_permiso("salida vieja\n" + ANCHO))   # the real one, under output

    def test_the_options_are_the_dialogs_own(self):
        # adversary r5 (codex): a screen with a single «Yes» option was taken for the dialog
        opciones = ANCHO[ANCHO.index(" ❯ 1. Yes"):ANCHO.index("\n\n Esc to cancel")]
        for otras in (" ❯ 1. Yes", " ❯ 1. Yes\n   2. Yes, and don’t ask again for: git push *",
                      opciones.replace("   4. No", "   5. No"), opciones.replace("   4. No", "   4. Nope"),
                      opciones.replace("   2. Yes, and don’t ask again for: git push *", "   2. No")):
            self.assertIsNone(aprueba.dialogo_permiso(ANCHO.replace(opciones, otras)), repr(otras))
        self.assertIsNotNone(aprueba.dialogo_permiso(ANCHO.replace(opciones, " ❯ 1. Yes\n   2. No")))

    def test_the_dialog_must_end_the_screen(self):
        # the dialog's text typed in the prompt box (or scrolled above it) is not the dialog
        self.assertIsNone(aprueba.dialogo_permiso(ANCHO + CAJA))
        self.assertIsNone(aprueba.dialogo_permiso(CAJA))
        self.assertIsNone(aprueba.dialogo_permiso(ANCHO.replace("Bash command", "Read file")))
        self.assertIsNone(aprueba.dialogo_permiso(ANCHO.replace("Do you want to proceed?", "")))


class BlockedGuardaElComandoTest(f3.Base):
    def test_the_blocked_event_keeps_the_whole_command(self):
        # it kept 200 characters: a long command could never be compared
        lookout_state.write_marker("s1", {"project_id": self.pid, "nombre": "uno"})
        os.environ["LOOKOUT_PERMISOS"] = os.path.join(self.tmp.name, "no-existe.toml")
        try:
            permisos.handle({"hook_event_name": "PermissionRequest", "tool_name": "Bash", "session_id": "s1",
                             "tool_input": {"command": LARGO_CMD}, "permission_mode": "auto", "cwd": self.tmp.name},
                            {"project_id": self.pid, "nombre": "uno"})
        finally:
            os.environ.pop("LOOKOUT_PERMISOS", None)
        ev = [e for e in lookout_state.read_events(self.pid, 0)[0] if e.get("event") == "blocked"][-1]
        self.assertEqual(ev["comando"], LARGO_CMD)
        self.assertEqual(len(ev["detalle"]), 200)


class ApruebaTest(f3.Base):
    def setUp(self):
        super().setUp()
        self.agent("s1", nombre="uno", tarea="", pane_id="w1A:pU", cwd="/x", worktree="/x")
        self.calls, self.status, self.screens = [], "blocked", [ANCHO, CAJA]
        self.saved = (aprueba.herdr_cli.run, aprueba.herdr_cli.agent_get, aprueba.pantalla, aprueba.ESPERA,
                      aprueba.VIGILA, aprueba.PASO)
        aprueba.herdr_cli.run = lambda args, **k: (self.calls.append(list(args)), (0, "", ""))[1]
        aprueba.herdr_cli.agent_get = lambda pane: {"agent_session": {"value": "s1"}, "agent_status": self.status}
        aprueba.pantalla = lambda pane: self.screens[min(len(self.keys()), len(self.screens) - 1)]
        aprueba.ESPERA, aprueba.VIGILA, aprueba.PASO = 1.0, 0.3, 0.05

    def tearDown(self):
        (aprueba.herdr_cli.run, aprueba.herdr_cli.agent_get, aprueba.pantalla, aprueba.ESPERA, aprueba.VIGILA,
         aprueba.PASO) = self.saved
        super().tearDown()

    def keys(self):
        return [c[3:] for c in self.calls if c[:2] == ["agent", "send-keys"]]

    def blocked(self, cmd=CORTO, ts=None, sid="s1"):
        ev = {"session_id": sid, "hook": "PermissionRequest", "event": "blocked", "tool_name": "Bash",
              "detalle": cmd[:200], "comando": cmd, "ts": ts or time.time()}
        lookout_state.append_event(self.pid, ev)
        return ev

    def entry(self):
        return registry.load(self.pid)["agents"]["s1"]

    def decision(self, respuesta="Sí, apruébalo una vez", pregunta=None):
        cmd = aprueba.pendiente(self.pid, self.entry())["comando"]
        ok, it = aprueba.abre(self.pid, self.entry(), "¿Apruebo a uno, una vez: «%s»?" % cmd, "Sí, apruébalo una vez")
        self.assertTrue(ok, it)
        modal(self.pid, it["id"], respuesta, pregunta if pregunta is not None else "¿Apruebo a uno, una vez: «%s»?" % cmd)
        return it["id"]

    def test_the_users_yes_presses_yes_once(self):
        self.blocked()
        dn = self.decision()
        ok, msg = aprueba.aprueba(self.pid, self.entry(), dn)
        self.assertTrue(ok, msg)
        self.assertEqual(self.keys(), [["1"]])
        ok, msg = aprueba.aprueba(self.pid, self.entry(), dn)   # one yes, one dialog
        self.assertFalse(ok)
        self.assertEqual(self.keys(), [["1"]])

    def test_another_request_right_after_the_key_is_reported_loudly(self):
        # adversary r2 (codex) + the user's choice (accept the one-call window and warn)
        self.blocked(ts=time.time() - 5)
        dn = self.decision()
        real = aprueba.herdr_cli.run

        def run(args, **k):
            out = real(args, **k)
            if args[:2] == ["agent", "send-keys"]:
                self.blocked("git push origin HEAD:otra")
            return out
        aprueba.herdr_cli.run = run
        ok, msg = aprueba.aprueba(self.pid, self.entry(), dn)
        self.assertFalse(ok)
        self.assertEqual(self.keys(), [["1"]])
        self.assertIn("AVISO AL USUARIO", msg)
        self.assertIn("git push origin HEAD:otra", msg)

    def test_another_dialog_right_after_the_key_is_reported_too(self):
        # adversary r3 (codex): a dialog still on screen after the key (another one, drawn at once) skipped the watch
        self.screens = [ANCHO, SIN_BARRA]
        self.blocked(ts=time.time() - 5)
        dn = self.decision()
        real = aprueba.herdr_cli.run

        def run(args, **k):
            out = real(args, **k)
            if args[:2] == ["agent", "send-keys"]:
                self.blocked("git push origin HEAD:refs/heads/par-uno")
            return out
        aprueba.herdr_cli.run = run
        ok, msg = aprueba.aprueba(self.pid, self.entry(), dn)
        self.assertFalse(ok)
        self.assertIn("AVISO AL USUARIO", msg)

    def test_narrow_and_long_dialogs(self):
        for screen, cmd in ((ESTRECHO, CORTO), (LARGO, LARGO_CMD)):
            self.calls.clear()
            self.screens = [screen, CAJA]
            self.blocked(cmd)
            ok, msg = aprueba.aprueba(self.pid, self.entry(), self.decision())
            self.assertTrue(ok, msg)
            self.assertEqual(self.keys(), [["1"]])

    def assert_nothing_pressed(self, dn, frase):
        ok, msg = aprueba.aprueba(self.pid, self.entry(), dn)
        self.assertFalse(ok)
        self.assertIn(frase, msg)
        self.assertEqual(self.keys(), [])
        self.assertFalse([c for c in self.calls if "esc" in c])

    def test_no_or_wait_from_the_user_presses_nothing(self):
        self.blocked()
        self.assert_nothing_pressed(self.decision("No, espera"), "sí del usuario")
        self.assert_nothing_pressed("d99", "sí del usuario")

    def test_a_yes_of_another_kind_presses_nothing(self):
        self.blocked()
        dn = decisiones.abre(self.pid, "¿x?", ["uno"], notificar=False, si_es="Sí")["id"]
        t139.modal(self.pid, dn, "Sí")
        self.assert_nothing_pressed(dn, "sí del usuario")

    def test_another_command_on_screen_presses_nothing(self):
        self.blocked(CORTO.replace("ancho", "otro"))
        self.assert_nothing_pressed(self.decision(), "no es el que aprobó")

    def test_a_dialog_that_does_not_fit_presses_nothing(self):
        self.screens = [LARGO_CORTADO]
        self.blocked(LARGO_CMD)
        self.assert_nothing_pressed(self.decision(), "no cabe")

    def test_an_agent_that_moved_on_presses_nothing(self):
        self.blocked()
        dn = self.decision()
        lookout_state.append_event(self.pid, {"session_id": "s1", "hook": "PostToolUse", "event": "working",
                                              "ts": time.time()})
        self.assert_nothing_pressed(dn, "ya no espera")

    def test_a_newer_request_needs_a_new_yes(self):
        self.blocked(ts=time.time() - 5)
        dn = self.decision()
        self.blocked()   # same command, another call (it asked again): the user approved the first one
        self.assert_nothing_pressed(dn, "otra petición")

    def test_herdr_must_see_it_blocked(self):
        self.blocked()
        dn = self.decision()
        self.status = "working"
        self.assert_nothing_pressed(dn, "blocked")

    def test_a_dialog_still_there_after_the_key_is_reported(self):
        self.screens = [ANCHO]
        self.blocked()
        ok, msg = aprueba.aprueba(self.pid, self.entry(), self.decision())
        self.assertFalse(ok)
        self.assertEqual(self.keys(), [["1"]])   # pressed once, never again, never Esc
        self.assertIn("sigue", msg)

    def test_it_opens_only_with_a_pending_bash_request(self):
        ok, msg = aprueba.abre(self.pid, self.entry(), "¿Apruebo «%s»?" % CORTO, "Sí")
        self.assertFalse(ok)
        lookout_state.append_event(self.pid, {"session_id": "s1", "hook": "PermissionRequest", "event": "blocked",
                                              "tool_name": "Write", "detalle": "/x/a", "ts": time.time()})
        self.assertFalse(aprueba.abre(self.pid, self.entry(), "¿Apruebo «%s»?" % CORTO, "Sí")[0])
        ev = self.blocked()
        self.assertFalse(aprueba.abre(self.pid, self.entry(), "¿Apruebo su push?", "Sí")[0])   # no command in it
        ok, it = aprueba.abre(self.pid, self.entry(), "¿Apruebo «%s»?" % CORTO, "Sí")
        self.assertTrue(ok)
        self.assertEqual((it["tipo"], it["permiso"]["comando"], it["permiso"]["ts"]), ("permiso", CORTO, ev["ts"]))

    def test_a_cut_command_cannot_be_approved(self):
        # an event written by an older hook carries only `detalle` (200 characters)
        lookout_state.append_event(self.pid, {"session_id": "s1", "hook": "PermissionRequest", "event": "blocked",
                                              "tool_name": "Bash", "detalle": CORTO, "ts": time.time()})
        self.assertFalse(aprueba.abre(self.pid, self.entry(), "¿Apruebo «%s»?" % CORTO, "Sí")[0])

    def test_the_yes_counts_only_for_a_question_that_showed_the_command(self):
        # adversary r1 (codex): the supervisor's modal could ask something else than what it opened
        self.blocked()
        self.assert_nothing_pressed(self.decision(pregunta="¿Apruebo un echo inofensivo?"), "no mostraba el comando")
        # adversary r2 (codex): a longer command in the question contains the approved one
        self.blocked("git push origin HEAD")
        self.assert_nothing_pressed(self.decision(pregunta="¿Apruebo «git push origin HEAD:refs/heads/x»?"),
                                    "no mostraba el comando")
        self.assertFalse(aprueba.muestra("¿Apruebo git push origin HEAD?", "git push origin HEAD"))   # no «»
        self.assertFalse(aprueba.muestra("¿Apruebo «git  push origin HEAD»?", "git push origin HEAD"))

    def test_a_request_that_arrives_while_pressing_is_not_pressed(self):
        # adversary r1 (codex): a newer request injected while the yes is spent
        self.blocked(ts=time.time() - 5)
        dn = self.decision()
        real = decisiones.marca_usada
        decisiones.marca_usada = lambda pid, did, now=None: (self.blocked(), real(pid, did, now))
        try:
            self.assert_nothing_pressed(dn, "cambió de petición")
        finally:
            decisiones.marca_usada = real
        self.assertTrue(next(it for it in decisiones.load(self.pid)["items"] if it["id"] == dn).get("usada"))


class DecisionCliTest(unittest.TestCase):
    def test_decision_permiso_prints_the_whole_command_and_the_next_step(self):
        import argparse
        import contextlib
        import io
        import test_lookout_0137 as t137

        class T(t137.EnviaDelUsuarioTest):
            def runTest(self):
                pass
        t = T()
        t.setUp()
        try:
            ns = dict(proyecto=t137.PID, abre="¿Apruebo a uno, una vez: «%s»?" % LARGO_CMD, agentes="uno", si_es="Sí, una vez",
                      cierre=False, nueva=False, cierra=None, respuesta=None, si=False, no=False, lista=False,
                      permiso=True, shells_parar="", shells_dejar="")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(t.lk.cmd_decision(argparse.Namespace(**ns)), 5)   # nothing pending yet
            self.assertIn("no espera un permiso", out.getvalue())
            lookout_state.append_event(t137.PID, {"session_id": "s1", "hook": "PermissionRequest", "event": "blocked",
                                                  "tool_name": "Bash", "detalle": LARGO_CMD[:200],
                                                  "comando": LARGO_CMD, "ts": time.time()})
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(t.lk.cmd_decision(argparse.Namespace(**ns)), 0)
            self.assertIn(LARGO_CMD, out.getvalue())
            self.assertIn("lookout aprueba", out.getvalue())
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(t.lk.cmd_decision(argparse.Namespace(**dict(ns, agentes="uno,dos"))), 5)
        finally:
            t.tearDown()


if __name__ == "__main__":
    unittest.main()

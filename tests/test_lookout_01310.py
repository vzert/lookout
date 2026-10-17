"""0.13.10: agents with background shells. Measured 2026-10-17 (memory/research/lookout-shells-de-fondo-medicion.md):
of 17 real «está working» refusals, 9 were an agent quiet since its Stop that herdr saw `working` only because of a
background shell (the footer «· N shells ·»), and /exit with a live shell opens Claude Code's «Background work is
running» dialog, which cierra-pestana and relevo left open until their timeout.
Run: python3 -m unittest tests/test_lookout_01310.py
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_0130 as t130  # noqa: E402
import test_lookout_0138 as t138  # noqa: E402
import test_lookout_0139 as t139  # noqa: E402
import test_lookout_f2 as f2  # noqa: E402
import test_lookout_f3 as f3  # noqa: E402

import decisiones  # noqa: E402
import deliver  # noqa: E402
import lookout_state  # noqa: E402
import registry  # noqa: E402
import relevo  # noqa: E402

iso = t130.iso

# the dialog as Claude Code 2.1.302 draws it (captured at full width, 2026-10-17)
DIALOGO = """✻ Brewed for 3s · done 10:19 AM · 2 shells still running
▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔
   Background work is running
   The following will stop when you exit:
   shell · sleep 3000
   shell · until false; do pgrep -f nada-xyz
        >/dev/null; sle…
   ❯ 1. Exit and stop tasks
     2. Move to background and exit
     3. Stay
   Enter to confirm · Esc to cancel
"""
# the same dialog in a pane nobody looks at (23 columns, captured 2026-10-17)
DIALOGO_ESTRECHO = """▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔
   Background work
   is running
   The following
   will stop when
   you exit:

   shell · sleep
        3000

   ❯ 1. Exit and stop
        tasks
     2. Move to
        background and
        exit
     3. Stay

   Enter to confirm
   · Esc to cancel
"""
PIE_CON_SHELLS = """⏺ listo
✻ Worked for 10s · done 10:17 AM · 2 shells still running
────────────────────────────────────────────────────────
❯
────────────────────────────────────────────────────────
   Haiku 5.5  medium  [█░░░░░░░░░░░░░░░] 52k/1....
  ⏵⏵ auto mode on · 2 shells
"""
PIE_SIN_SHELLS = """⏺ listo
✻ Worked for 10s · done 10:17 AM
────────────────────────────────────────────────────────
❯
────────────────────────────────────────────────────────
  ⏵⏵ auto mode on
"""
SHELL = {"type": "shell", "status": "running", "command": "until ! pgrep -f tools/run-tests; do sleep 5; done"}


def stop(pid, sid, ts, event="idle", tareas=()):
    ev = {"session_id": sid, "hook": "Stop", "event": event, "ts": ts}
    if tareas:
        ev["tareas"] = list(tareas)
    lookout_state.append_event(pid, ev)


class QuietoTest(f3.Base):
    """herdr says working; the agent's own hooks and transcript say whether it is in a turn."""

    def setUp(self):
        super().setUp()
        self.e = self.agent("s1", "uno")
        self.now = time.time()
        self.transcript("s1", [t130.u_text("sigue", self.now - 60), t130.a_text("hecho", self.now - 30)])

    def q(self, status="working"):
        return deliver.quieto(self.pid, self.e, {"agent_status": status}, self.projects)

    def test_idle_and_done_are_quiet_as_before(self):
        self.assertTrue(self.q("idle"))
        self.assertTrue(self.q("done"))

    def test_working_after_a_stop_with_nothing_since_is_quiet(self):
        stop(self.pid, "s1", self.now - 20, "bg_wait", [SHELL])
        self.assertTrue(self.q())
        stop(self.pid, "s1", self.now - 10, "idle")
        lookout_state.append_event(self.pid, {"session_id": "s1", "hook": "Notification", "event": "notification",
                                              "ts": self.now - 5})
        self.assertTrue(self.q())   # a notification after the Stop is not a turn

    def test_the_stops_own_system_rows_do_not_count(self):
        stop(self.pid, "s1", self.now - 20, "bg_wait", [SHELL])
        self.transcript("s1", [{"type": "system", "subtype": "stop_hook_summary", "timestamp": iso(self.now - 19)}])
        self.assertTrue(self.q())

    def test_a_turn_with_no_prompt_hook_is_not_quiet(self):
        # 4 of the 8 right refusals: a task-notification or a message opened the turn, no UserPromptSubmit
        stop(self.pid, "s1", self.now - 20, "bg_wait", [SHELL])
        self.transcript("s1", [{"type": "queue-operation", "timestamp": iso(self.now - 5)},
                               {"type": "user", "timestamp": iso(self.now - 5),
                                "message": {"content": "<task-notification> done"}}])
        self.assertFalse(self.q())

    def test_its_hooks_in_a_turn_or_no_stop_are_not_quiet(self):
        self.assertFalse(self.q())   # only its start event
        stop(self.pid, "s1", self.now - 20)
        lookout_state.append_event(self.pid, {"session_id": "s1", "hook": "UserPromptSubmit", "event": "working",
                                              "ts": self.now - 10})
        self.assertFalse(self.q())

    def test_blocked_or_unknown_are_never_quiet(self):
        stop(self.pid, "s1", self.now - 20)
        self.assertFalse(self.q("blocked"))
        self.assertFalse(self.q("unknown"))

    def test_rows_it_cannot_date_or_read_are_a_turn(self):
        # adversary r1 (codex): a row with no or a bad timestamp after the Stop, and a partial line
        stop(self.pid, "s1", self.now - 20, "bg_wait", [SHELL])
        self.transcript("s1", [{"type": "assistant", "message": {"content": "sin hora"}}])
        self.assertFalse(self.q())

    def test_claude_codes_undated_bookkeeping_is_not_a_turn(self):
        # agente-3-tier-memory, 2026-10-16 22:16: «cost-state» and «last-prompt» after its Stop, quiet
        stop(self.pid, "s1", self.now - 20, "idle")
        self.transcript("s1", [{"type": "system", "timestamp": iso(self.now - 19)}, {"type": "cost-state"},
                               {"type": "last-prompt", "lastPrompt": "x"}])
        self.assertTrue(self.q())
        self.transcript("s1", [{"type": "otro-tipo"}])
        self.assertFalse(self.q())

    def test_a_bad_timestamp_is_a_turn(self):
        stop(self.pid, "s1", self.now - 20, "bg_wait", [SHELL])
        self.transcript("s1", [{"type": "user", "timestamp": "ayer", "message": {"content": "x"}}])
        self.assertFalse(self.q())

    def test_a_stamp_with_trailing_garbage_is_bad(self):
        # adversary r2 (codex): «…Zgarbage» parsed as a good stamp
        self.assertIsNone(deliver._ts({"timestamp": "1970-01-01T00:00:00.000Zgarbage"}))
        self.assertIsNone(deliver._ts({"timestamp": "2026-10-17T03:02:19"}))   # no zone
        self.assertIsNotNone(deliver._ts({"timestamp": "2026-10-17T03:02:19.512Z"}))
        self.assertIsNotNone(deliver._ts({"timestamp": "2026-10-17T03:02:19Z"}))
        self.assertIsNone(deliver._ts({"timestamp": "٢٠٢٦-10-17T03:02:19Z"}))   # r3 (both): ASCII digits only

    def test_a_line_that_is_not_utf8_is_a_turn(self):
        # adversary r2 (codex): bytes that are not UTF-8 were decoded with «replace» and read as a system row
        stop(self.pid, "s1", self.now - 20, "bg_wait", [SHELL])
        with open(deliver.transcript_path("s1", self.projects), "ab") as fh:
            fh.write(b'{"type": "system", "x": "\xff\xfe"}\n')
        self.assertFalse(self.q())

    def test_a_row_bigger_than_the_tail_is_a_turn(self):
        # adversary r1 (sonnet and codex): a 400 kB row after the Stop left only a fragment in the 256 kB tail
        stop(self.pid, "s1", self.now - 20, "idle")
        self.transcript("s1", [{"type": "user", "timestamp": iso(self.now - 5), "message": {"content": "sigue"}},
                               t130.a_text("x" * 400000, self.now - 1)])
        self.assertFalse(self.q())

    def test_a_file_that_looks_older_than_the_stop_is_still_read(self):
        # adversary r1 (codex): the mtime shortcut skipped the rows
        stop(self.pid, "s1", self.now - 20, "bg_wait", [SHELL])
        self.transcript("s1", [t130.u_text("otra", self.now - 5)])
        path = deliver.transcript_path("s1", self.projects)
        os.utime(path, (self.now - 100, self.now - 100))
        self.assertFalse(self.q())

    def test_no_transcript_is_not_quiet(self):
        e = self.agent("s9", "nueve")
        stop(self.pid, "s9", self.now - 20)
        self.assertFalse(deliver.quieto(self.pid, e, {"agent_status": "working"}, self.projects))


def fechado(self, now):
    """Its last turn, dated (a real transcript dates every user and assistant row)."""
    import json
    d = os.path.join(self.projects, "-tmp-x")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, self.sid + ".jsonl"), "w") as fh:
        for row in (t130.u_text("sigue", now - 60), t130.a_text("hecho", now - 30)):
            fh.write(json.dumps(row) + "\n")


class EnviaConShellTest(f2.StubCase):
    text = "Nota del supervisor: sigue con p-1."
    fechado = fechado

    def test_a_quiet_agent_with_a_shell_gets_it(self):
        self.stub(agent_get={"agent_status": "working", "cwd": self.tmp.name, "agent_session": {"value": self.sid}},
                  agent_read=f2.EMPTY_BOX)
        now = time.time()
        self.fechado(now)
        stop(self.pid, self.sid, now - 20, "bg_wait", [SHELL])
        self.hook_on_prompt()
        code, msg = deliver.deliver(self.pid, self.entry, "k1", self.text, 2, projects_dir=self.projects)
        self.assertEqual(code, 0, msg)
        self.assertEqual(len(self.calls(["agent", "prompt"])), 1)

    def test_working_without_a_stop_is_still_refused(self):
        self.stub(agent_get={"agent_status": "working", "cwd": self.tmp.name, "agent_session": {"value": self.sid}},
                  agent_read=f2.EMPTY_BOX)
        code, msg = deliver.deliver(self.pid, self.entry, "k1", self.text, 0.2, projects_dir=self.projects)
        self.assertEqual(code, 4)
        self.assertIn("está working", msg)


class RecargaConShellTest(t138.RecargaTest):
    fechado = fechado

    def test_a_quiet_agent_with_a_shell_gets_it(self):
        self.stub(agent_get={"agent_status": "working", "agent_session": {"value": self.sid}}, agent_read=f2.EMPTY_BOX,
                  read_after_prompt="  ⎿  Reloaded: 5 plugins · 20 skills\n" + f2.EMPTY_BOX)
        now = time.time()
        self.fechado(now)
        stop(self.pid, self.sid, now - 20, "bg_wait", [SHELL])
        old = deliver.transcript_path
        deliver.transcript_path = lambda sid, pd=None: old(sid, pd or self.projects)
        try:
            ok, msg = self.recarga.recarga(self.pid, self.entry, espera=1)
        finally:
            deliver.transcript_path = old
        self.assertTrue(ok, msg)


class BarridoConShellTest(t130.BarridoTest):
    def test_a_quiet_agent_herdr_sees_working_is_swept(self):
        import alta
        now = time.time()
        self.agent("s1", "hook-para-checkpoint")
        self.transcript("s1", [t130.u_text("sigue", now - 60), t130.a_text(t130.MINUTOS, now - 30)])
        stop(t130.PID, "s1", now - 20, "bg_wait", [SHELL])
        herdr = [{"agent_session": {"value": "s1"}, "agent_status": "working", "pane_id": "w1:p1"}]
        evs = alta.barre(t130.PID, herdr)
        self.assertEqual([(e["event"], e["retomar"]["estado"]) for e in evs], [("retomar", "vigente")])


class Pantalla:
    """What `agent read` shows of the pane: the footer, then the dialog after /exit."""

    def __init__(self, test, antes, despues=DIALOGO):
        self.test, self.antes, self.despues = test, antes, despues

    def __call__(self, pane):
        return self.despues if any(c[-1] == "/exit" for c in self.test.prompts()) else self.antes


class RelevoConShellsTest(t130.RelevoSinTareaTest):
    def setUp(self):
        super().setUp()
        import salida
        self.salida = salida
        self.saved_pantalla = salida.pantalla
        self.now = time.time()

    def tearDown(self):
        self.salida.pantalla = self.saved_pantalla
        super().tearDown()

    def minutos(self):
        self.agent("s1", nombre="minutos-github", tarea="", modelo="", pane_id="w1A:pJ", cwd="/x", worktree="/x")
        self.transcript("s1", self.config_rows() + [t130.u_text("sigue", self.now - 50),
                                                    t130.a_text(t130.MINUTOS, self.now - 30)])

    def prompts(self):
        return [c[1] for c in self.calls if c[0] == "run" and c[1][:2] == ["agent", "prompt"]]

    def keys(self):
        return [c[1][3:] for c in self.calls if c[0] == "run" and c[1][:2] == ["agent", "send-keys"]]

    def run_relevo(self, shells=""):
        return relevo._relevo(self.pid, registry.load(self.pid)["agents"]["s1"], lambda n: "nota", "", None, 1, 1,
                              lambda m: None, shells=shells)

    def decision(self, respuesta, agentes=("minutos-github",)):
        it = decisiones.abre(self.pid, "¿Cómo cierro minutos-github con sus shells?", agentes, notificar=False,
                             shells={"parar": "Cerrar y parar sus shells", "dejar": "Cerrar y dejarlos"})
        t139.modal(self.pid, it["id"], respuesta)
        return it["id"]

    def test_live_shells_stop_it_before_exit(self):
        self.minutos()
        stop(self.pid, "s1", self.now - 20, "bg_wait", [SHELL])
        self.salida.pantalla = Pantalla(self, PIE_CON_SHELLS)
        ok, msg = self.run_relevo()
        self.assertFalse(ok)
        self.assertIn("shells", msg)
        self.assertIn("--shells", msg)
        self.assertIn("run-tests", msg)
        self.assertNotIn(["agent", "prompt", "w1A:pJ", "/exit"], self.prompts())

    def test_the_footer_alone_also_stops_it(self):
        self.minutos()
        # a monitor never reaches the Stop's task list; the footer still counts it
        stop(self.pid, "s1", self.now - 20, "idle")
        self.salida.pantalla = Pantalla(self, PIE_CON_SHELLS)
        self.assertFalse(self.run_relevo()[0])
        self.assertEqual(self.prompts(), [])

    def elige(self, respuesta, tecla):
        self.minutos()
        stop(self.pid, "s1", self.now - 20, "bg_wait", [SHELL])
        self.salida.pantalla = Pantalla(self, PIE_CON_SHELLS)
        ok, msg = self.run_relevo(shells=self.decision(respuesta))
        self.assertTrue(ok, msg)
        self.assertEqual(self.keys(), [[tecla]])

    def test_stop_them_is_key_1(self):
        self.elige("Cerrar y parar sus shells", "1")

    def test_leave_them_is_key_2(self):
        self.elige("Cerrar y dejarlos", "2")

    def test_only_the_users_own_choice_for_this_agent_counts(self):
        self.minutos()
        stop(self.pid, "s1", self.now - 20, "bg_wait", [SHELL])
        self.salida.pantalla = Pantalla(self, PIE_CON_SHELLS)
        for nombre, dn in (("esperar", self.decision("Esperar a que terminen")),
                           ("otro agente", self.decision("Cerrar y parar sus shells", agentes=("otro",))),
                           ("no existe", "d99")):
            ok, msg = self.run_relevo(shells=dn)
            self.assertFalse(ok, nombre)
            self.assertEqual(self.prompts(), [], nombre)
        dn = decisiones.abre(self.pid, "¿x?", ["minutos-github"], notificar=False, si_es="Sí")["id"]
        t139.modal(self.pid, dn, "Sí")
        self.assertFalse(self.run_relevo(shells=dn)[0])   # a yes of another kind

    def test_a_dialog_it_did_not_expect_is_cancelled_and_asked(self):
        self.minutos()
        # race: no shell in its Stop nor its footer, and /exit still opens the dialog
        stop(self.pid, "s1", self.now - 20, "idle")
        self.salida.pantalla = Pantalla(self, PIE_SIN_SHELLS)
        relevo.deliver.wait_event = lambda *a, **k: False
        ok, msg = self.run_relevo()
        self.assertFalse(ok)
        self.assertEqual(self.keys(), [["esc"]])
        self.assertIn("--shells", msg)
        self.assertFalse([c for c in self.calls if c[0] == "arranca"])


class CierraConShellsTest(t139.CierreDecididoTest):
    def setUp(self):
        super().setUp()
        import salida
        self.salida = salida
        self.saved_pantalla = salida.pantalla
        salida.pantalla = lambda pane: PIE_SIN_SHELLS

    def tearDown(self):
        self.salida.pantalla = self.saved_pantalla
        super().tearDown()

    def test_a_quiet_agent_herdr_sees_working_can_be_closed(self):
        self.status = "working"
        lookout_state.append_event(self.pid, {"session_id": "s1", "hook": "Stop", "event": "idle", "ts": time.time()})
        ok, msg = self.cierra()
        self.assertTrue(ok, msg)

    def test_with_the_users_shells_choice_the_background_guard_gives_way(self):
        self.status = "working"
        lookout_state.append_event(self.pid, {"session_id": "s1", "hook": "Stop", "event": "bg_wait", "ts": time.time(),
                                              "tareas": [SHELL]})
        self.salida.pantalla = lambda pane: PIE_CON_SHELLS
        ok, msg = self.cierra()
        self.assertFalse(ok)
        self.assertIn("--shells", msg)
        it = decisiones.abre(self.pid, "¿Cómo cierro sidebar?", ["sidebar"], notificar=False,
                             shells={"parar": "Parar", "dejar": "Dejar"})
        t139.modal(self.pid, it["id"], "Parar")
        e = registry.load(self.pid)["agents"]["s1"]
        ok, msg = self.retiro.cierra(self.pid, e, "", fin_timeout=1, log=lambda m: None, shells=it["id"])
        self.assertTrue(ok, msg)


class DecisionShellsTest(f3.Base):
    def test_the_hook_writes_which_option_the_user_chose(self):
        it = decisiones.abre(self.pid, "¿Cómo cierro uno?", ["uno"], notificar=False,
                             shells={"parar": "Parar", "dejar": "Dejar"})
        t139.modal(self.pid, it["id"], "Dejar")
        d = decisiones.respondida(self.pid, it["id"])
        self.assertEqual((d["tipo"], d["eleccion"], d["por_hook"]), ("shells", "dejar", True))
        otra = decisiones.abre(self.pid, "¿Cómo cierro dos?", ["dos"], notificar=False,
                               shells={"parar": "Parar", "dejar": "Dejar"})
        t139.modal(self.pid, otra["id"], " Parar")   # exact label only
        self.assertIsNone(decisiones.respondida(self.pid, otra["id"]))

    def test_a_shells_decision_does_not_close_a_tab(self):
        it = decisiones.abre(self.pid, "¿x?", ["uno"], notificar=False, shells={"parar": "Parar", "dejar": "Dejar"})
        self.assertNotEqual(it.get("tipo"), "cierre")


class DialogoTest(unittest.TestCase):
    def test_it_is_read_by_structure(self):
        import salida
        self.assertEqual(salida.dialogo_exit(DIALOGO), {"parar": "1", "dejar": "2", "quedarse": "3"})
        self.assertEqual(salida.dialogo_exit(DIALOGO_ESTRECHO), {"parar": "1", "dejar": "2", "quedarse": "3"})
        self.assertIsNone(salida.dialogo_exit(PIE_CON_SHELLS))
        self.assertIsNone(salida.dialogo_exit("❯ 1. Exit and stop tasks\n"))   # text in a prompt, not the dialog

    def test_a_mimic_in_the_prompt_box_is_not_the_dialog(self):
        # adversary r1 (codex): the three option lines and «Enter to confirm» typed in the box, with the footer below
        mimic = ("⏺ listo\n────────\n❯ 1. Exit and stop tasks\n  2. Move to background and exit\n  3. Stay\n"
                 "  Enter to confirm · Esc to cancel\n────────\n  ⏵⏵ auto mode on · 1 shell\n")
        import salida
        self.assertIsNone(salida.dialogo_exit(mimic))
        sin_cabecera = DIALOGO.replace("Background work is running", "Algo")
        self.assertIsNone(salida.dialogo_exit(sin_cabecera))

    def test_a_cut_footer_still_counts(self):
        # adversary r1 (codex): a pane nobody looks at draws 23 columns and cuts «· 2 shells» to «· 2»
        import salida
        self.assertEqual(salida.shells_en_pie("────\n❯\n────\n  ⏵⏵ auto mode on · 2\n"), 2)

    def test_the_footer_counts_shells_and_tasks(self):
        import salida
        self.assertEqual(salida.shells_en_pie(PIE_CON_SHELLS), 2)
        self.assertEqual(salida.shells_en_pie(PIE_SIN_SHELLS), 0)
        self.assertEqual(salida.shells_en_pie("────\n❯\n────\n  ⏵⏵ auto mode on · 1 background task · ← for agents\n"), 1)
        self.assertEqual(salida.shells_en_pie("────\n❯ tengo 2 shells abiertos\n────\n  ⏵⏵ auto mode on\n"), 0)


class SinIdleDoneSueltoTest(unittest.TestCase):
    """The six actions ask deliver.quieto; none checks herdr's idle/done by itself again."""

    def test_no_action_reads_idle_done_by_itself(self):
        import re
        bin_ = os.path.dirname(deliver.__file__)
        for nombre in ("deliver.py", "lookout", "recarga.py", "relevo.py", "retiro.py", "alta.py"):
            with open(os.path.join(bin_, nombre), encoding="utf-8") as fh:
                texto = fh.read()
            if nombre == "deliver.py":
                texto = texto.split("def quieto", 1)[0] + texto.split("def quieto", 1)[1].split("\ndef ", 1)[1]
            sueltos = re.findall(r'agent_status"\)\s+not in \("idle", "done"\)', texto)
            self.assertEqual(sueltos, [], nombre)


if __name__ == "__main__":
    unittest.main()

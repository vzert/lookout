"""0.12.2: fewer wakes of the supervisor, a shorter waiter digest and four output bugs (B1-B4), measured on the
3-tier-memory supervision of 2026-10-15 (36 wakes in 7.6 h, 61 % with nothing to do).
Run: python3 -m unittest tests/test_lookout_0122.py
"""
import json
import os
import subprocess
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f3 as f3  # noqa: E402
import test_lookout_f4 as f4  # noqa: E402
import test_lookout_nombres as nombres  # noqa: E402

import digest  # noqa: E402
import heuristicas  # noqa: E402
import lookout_state  # noqa: E402
import on_state  # noqa: E402
import on_supervisor  # noqa: E402
import publica  # noqa: E402
import registry  # noqa: E402
import wait_event  # noqa: E402

PID, SUP = f4.PID, f4.SUP
SUP_ADDR = "uds:/tmp/sup.sock"


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) + ".%03dZ" % int((ts % 1) * 1000)


class WakeTest(f4.Base):
    def wait(self, ventana=0.0, timeout=1.5):
        path = lookout_state.events_path(PID)
        try:
            return wait_event.wait(path, 0, digest.WAKE_TYPES, timeout, digest.pidfile(PID), digest.cursor_path(PID),
                                   ventana=ventana, linea=False)
        except SystemExit as exc:  # its timeout ends it with sys.exit(2)
            return exc.code

    def test_waiting_for_a_background_task_does_not_wake(self):
        # N1: 19 of 36 wakes were «espera tarea de fondo», none of them something to answer
        lookout_state.append_event(PID, {"event": "bg_wait", "session_id": "s1", "nombre": "uno", "ts": time.time(),
                                         "tareas": [{"description": "suite"}]})
        self.assertEqual(self.wait(), 2)
        self.assertIn("espera tarea de fondo: suite", digest.render(PID))  # still in the next digest

    def test_a_burst_wakes_once(self):
        # N2: 11 of 36 wakes came less than 5 s after the waiter started
        self.agent("s1", "uno")
        self.agent("s2", "dos")
        lookout_state.append_event(PID, {"event": "idle", "session_id": "s1", "nombre": "uno", "ts": time.time()})
        t = threading.Timer(0.4, lambda: lookout_state.append_event(
            PID, {"event": "ask", "session_id": "s2", "nombre": "dos", "ts": time.time(), "questions": []}))
        t.start()
        r = self.run_lk("espera", PID, "--timeout", "5", LOOKOUT_VENTANA="1.2")
        t.join()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Eventos nuevos (2", r.stdout)
        self.assertNotIn("evento: ", r.stdout)  # N3: the digest's first event already says it

    def test_a_background_wait_that_asks_still_wakes(self):
        # adversary round 1: «¿Lo subo a main o abro PR? Mientras corre el CI.» was silent for an hour
        ev, _l, _o = on_state.build({"session_id": "s1", "hook_event_name": "Stop", "transcript_path": "",
                                     "last_assistant_message": "Terminé. ¿Lo subo a main o abro PR? Mientras corre el CI.",
                                     "background_tasks": [{"type": "shell", "status": "running", "command": "ci"}]},
                                    {"nombre": "uno"})
        self.assertEqual((ev["event"], ev.get("pregunta")), ("bg_wait", True))
        lookout_state.append_event(PID, dict(ev, ts=time.time()))
        self.assertEqual(self.wait(), 0)

    def test_any_question_mark_counts_as_a_question(self):
        # round 3: a narrower reading lost «push now?!» and «Should I push? Reply yes or no.»; a false wake is the safe side
        for msg in ("Should I push? Reply yes or no.", "push now?!", "Should I push? 🙂", "¿Lo subo?\n" + "línea\n" * 12,
                    "Corro grep '?' logs", "¿Lo subo", "これでいい？"):
            self.assertTrue(on_state.pregunta(msg), msg)
        self.assertFalse(on_state.pregunta("Listo, espero la suite."))

    def test_the_timeout_does_not_cut_the_window(self):
        # adversary round 1 (codex): a timeout shorter than the window ended a waiter that already had its event
        lookout_state.append_event(PID, {"event": "idle", "session_id": "s1", "nombre": "uno"})
        self.assertEqual(self.wait(ventana=1.0, timeout=0.3), 0)

    def test_the_waiters_own_line_does_not_say_no_waiter_flatly(self):
        # B1: «Waiter: no hay» was true when printed and read after a relaunch: it invited a second waiter
        out = digest.render(PID, mark=True, por_waiter=True)
        self.assertIn("salvo que ya hayas lanzado otro después de este despertar", out)
        self.assertIn("Waiter: no hay", digest.render(PID))

    def test_the_window_defaults_to_three_seconds(self):
        os.environ.pop("LOOKOUT_VENTANA", None)
        self.assertEqual(digest.ventana_s(), 3.0)


class NoAcuseTest(f4.Base):
    def test_a_reply_to_the_supervisors_message_still_wakes(self):
        # 0.12.2 round 3: reading «only an acknowledgement» from the text never converged («I cannot continue.» passed
        # as one); the user chose to drop it (2026-10-15). An end of turn after the supervisor's message wakes as before.
        path = os.path.join(self.tmp.name, "t.jsonl")
        with open(path, "w") as fh:
            for r in [{"type": "user", "message": {"content": 'Another Claude session sent a message:\n'
                                                              '<cross-session-message from="%s">\nsigue' % SUP_ADDR}},
                      {"type": "assistant", "message": {"content": [{"type": "text", "text": "Entendido."}]}}]:
                fh.write(json.dumps(r) + "\n")
        ev, _l, _o = on_state.build({"session_id": "s1", "hook_event_name": "Stop", "last_assistant_message": "Entendido.",
                                     "transcript_path": path}, {"nombre": "uno", "address": SUP_ADDR})
        self.assertEqual(ev["event"], "idle")
        self.assertNotIn("acuse", ev)


class LastLineTest(unittest.TestCase):
    def test_a_question_near_the_end_wins_over_the_last_line(self):
        msg = "Hice A y B.\n¿Paro la otra corrida o la dejo?\n1. Paro yo la corrida.\n2. Paras tú la otra corrida."
        self.assertEqual(on_state.last_line(msg), "¿Paro la otra corrida o la dejo?")

    def test_the_shown_line_is_the_question_whatever_its_mark_or_place(self):
        # adversary round 5 (codex): «¿Lo subo», «これでいい？» and a question followed by 9 lines woke the supervisor,
        # but the digest showed another line
        self.assertEqual(on_state.last_line("Hecho.\n¿Lo subo\nsigo con la suite"), "¿Lo subo")
        self.assertEqual(on_state.last_line("これでいい？\nlog"), "これでいい？")
        self.assertEqual(on_state.last_line("Should I push?\n" + "\n".join("context line %d" % i for i in range(9))),
                         "Should I push?")

    def test_a_last_list_item_carries_the_line_that_opens_the_list(self):
        msg = "Quedan dos caminos:\n1. Reintentar.\n2. Dejarlo para mañana."
        self.assertEqual(on_state.last_line(msg), "Quedan dos caminos: … 2. Dejarlo para mañana.")

    def test_a_background_wait_names_the_description_first(self):
        ev = {"event": "bg_wait", "nombre": "uno", "tareas": [{"command": "/private/tmp/x/scratchpad/run.sh --largo",
                                                                "description": "Suite completa"}]}
        self.assertIn("espera tarea de fondo: Suite completa", digest.describe(ev))


class StopWithAQueuedWakeTest(f4.Base):
    """B1: 5 of 5 Stop reminders came while the waiter's notification was queued; 2 led to «waiter ya vivo»."""

    def transcript_with(self, rows):
        path = os.path.join(self.tmp.name, "sup.jsonl")
        with open(path, "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        return path

    def test_no_reminder_while_the_wake_is_queued_and_one_after_it_was_seen(self):
        supervisor_md = f4.supervisor_md
        supervisor_md.mark_supervisor(SUP, PID)
        antes = time.time() - 30
        digest.marca_despertar(PID, SUP)
        queued = self.transcript_with([
            {"type": "user", "timestamp": iso(antes), "message": {"content": "supervisa"}},
            {"type": "queue-operation", "operation": "enqueue", "timestamp": iso(time.time())},
            {"type": "assistant", "timestamp": iso(time.time()), "message": {"content": [{"type": "text", "text": "x"}]}}])
        self.assertEqual(on_supervisor.stop_check({"transcript_path": queued}, PID, SUP, grace=0), "")
        seen = self.transcript_with([
            {"type": "user", "timestamp": iso(antes), "message": {"content": "supervisa"}},
            {"type": "queue-operation", "operation": "remove", "timestamp": iso(time.time()),
             "content": "<task-notification>\n<task-id>b1</task-id>"}])
        self.assertIn("lookout espera", f4.sigue(on_supervisor.stop_check({"transcript_path": seen}, PID, SUP, grace=0)))
        self.assertIn("lookout espera", f4.sigue(on_supervisor.stop_check({}, PID, SUP, grace=0)))  # unsure: remind

    def test_an_old_wake_or_another_sessions_wake_does_not_count(self):
        f4.supervisor_md.mark_supervisor(SUP, PID)
        path = self.transcript_with([{"type": "user", "timestamp": iso(time.time() - 500), "message": {"content": "x"}}])
        lookout_state.write_json(digest.despertar_path(PID), {"ts": time.time() - 90, "session_id": SUP})
        self.assertFalse(digest.despertar_en_cola(PID, SUP, path))
        digest.marca_despertar(PID, "otra")
        self.assertFalse(digest.despertar_en_cola(PID, SUP, path))

    def test_lookout_espera_marks_its_wake(self):
        self.agent("s1", "uno")
        lookout_state.append_event(PID, {"event": "idle", "session_id": "s1", "nombre": "uno"})
        r = self.run_lk("espera", PID, "--timeout", "5", LOOKOUT_VENTANA="0", CLAUDE_CODE_SESSION_ID=SUP)
        self.assertEqual(r.returncode, 0, r.stderr)
        d = lookout_state.read_json(digest.despertar_path(PID))
        self.assertEqual(d["session_id"], SUP)
        self.assertLess(time.time() - d["ts"], 10)


class ShortDigestTest(f4.Base):
    def test_a_second_wake_prints_only_what_changed(self):
        # N3: ~1.9 KB per wake, the same agents table and blocks every time
        self.agent("s1", "uno")
        lookout_state.append_event(PID, {"event": "idle", "session_id": "s1", "nombre": "uno"})
        first = digest.render(PID, mark=True, por_waiter=True)
        self.assertIn("  uno | lookout/uno", first)
        lookout_state.append_event(PID, {"event": "notification", "session_id": "s1", "nombre": "uno", "tipo": "x"})
        second = digest.render(PID, mark=True, por_waiter=True)
        self.assertIn("Agentes (1): sin cambios desde el despertar anterior", second)
        self.assertNotIn("  uno | lookout/uno", second)
        self.assertIn("  uno | lookout/uno", digest.render(PID))  # `resumen` always prints the table
        lookout_state.append_event(PID, {"event": "ask", "session_id": "s1", "nombre": "uno", "questions": []})
        self.assertIn("  uno | lookout/uno", digest.render(PID, mark=True, por_waiter=True))  # it changed

    def test_a_new_session_or_a_compaction_gets_the_whole_table(self):
        self.agent("s1", "uno")
        os.environ["CLAUDE_CODE_SESSION_ID"] = SUP
        lookout_state.append_event(PID, {"event": "idle", "session_id": "s1", "nombre": "uno"})
        digest.render(PID, mark=True, por_waiter=True)
        os.environ["CLAUDE_CODE_SESSION_ID"] = "relevo"                      # a relief never saw that table
        self.assertIn("  uno | lookout/uno", digest.render(PID, mark=True, por_waiter=True))
        self.assertIn("sin cambios", digest.render(PID, mark=True, por_waiter=True))
        f4.supervisor_md.mark_supervisor("relevo", PID)
        on_supervisor.handle({"session_id": "relevo", "hook_event_name": "PreCompact", "trigger": "auto"})
        self.assertIn("  uno | lookout/uno", digest.render(PID, mark=True, por_waiter=True))

    def test_echoes_of_the_supervisors_messages_are_not_events(self):
        # N4: 35 of 106 event lines were echoes and notices
        self.agent("s1", "uno")
        lookout_state.append_event(PID, {"event": "working", "session_id": "s1", "nombre": "uno",
                                         "prompt": '<cross-session-message from="%s">sigue' % SUP_ADDR})
        lookout_state.append_event(PID, {"event": "working", "session_id": "s1", "nombre": "uno",
                                         "prompt": "<task-notification>\n<task-id>b1"})
        lookout_state.append_event(PID, {"event": "idle", "session_id": "s1", "nombre": "uno", "ultima": "Hecho."})
        out = digest.render(PID)
        self.assertNotIn("cross-session-message", out)
        self.assertIn("Eventos nuevos (1; 2 ecos de tus mensajes y avisos sin mostrar):", out)

    def test_context_line_only_from_sixty_percent(self):
        self.assertFalse(digest.contexto_alto(PID, "Contexto: 127k de 427k (arranque 127k + 300k)."))
        self.assertTrue(digest.contexto_alto(PID, "Contexto: 257k de 427k."))
        self.assertTrue(digest.contexto_alto(PID, "Contexto: 500k de 427k. PRESUPUESTO SUPERADO"))
        self.transcript(SUP, [{"type": "assistant", "message": {"id": "m1", "usage": {
            "input_tokens": 3, "cache_read_input_tokens": 100000, "cache_creation_input_tokens": 0}}}])
        os.environ["CLAUDE_CODE_SESSION_ID"] = SUP
        os.environ["LOOKOUT_PRESUPUESTO"] = "400000"
        self.assertNotIn("Contexto:", digest.render(PID))
        os.environ["LOOKOUT_PRESUPUESTO"] = "150000"
        self.assertIn("Contexto: 100k de 150k.", digest.render(PID))


class LongBackgroundWaitTest(f4.Base):
    def test_a_background_wait_past_an_hour_wakes_once(self):
        # bg_wait no longer wakes, and the no-progress check never looked at it (EN_TURNO): without this an agent
        # whose task hangs would be seen by nobody
        self.agent("s1", "uno")
        lookout_state.append_event(PID, {"event": "bg_wait", "session_id": "s1", "nombre": "uno",
                                         "ts": time.time() - 3700})
        self.assertTrue(heuristicas.alguien_callado(PID))
        out = heuristicas.revisa(PID, agents=[], proceso=lambda _p: "vivo", reciente=lambda *_: False)
        self.assertEqual([(e["event"], e.get("fondo")) for e in out], [("largo", True)])
        self.assertIn("largo", digest.WAKE_TYPES.split(","))
        self.assertIn("esperando su tarea de fondo", digest.describe(out[0]))
        self.assertEqual(heuristicas.revisa(PID, agents=[], proceso=lambda _p: "vivo", reciente=lambda *_: False), [])

    def test_a_short_background_wait_is_left_alone(self):
        self.agent("s1", "uno")
        lookout_state.append_event(PID, {"event": "bg_wait", "session_id": "s1", "nombre": "uno",
                                         "ts": time.time() - 1500})
        self.assertFalse(heuristicas.alguien_callado(PID))
        self.assertEqual(heuristicas.revisa(PID, agents=[], proceso=lambda _p: "vivo", reciente=lambda *_: False), [])


class EntregaRenameTest(nombres.Case):
    """B2: the built-in /rename fires no UserPromptSubmit; waiting for one cost 30 s per agent (6 of 6)."""

    def run_entrega(self, box, timeout=2):
        registry.save("pA", {"agents": {"s1": {"session_id": "s1", "nombre": "nope-arreglar", "pane_id": "wS:p9",
                                               "tab_id": "wS:t9", "cwd": "/nope"}}})
        with open(os.path.join(nombres.FIX, box)) as fh:
            text = fh.read()
        self.stub(agent_get={"pane_id": "wS:p9", "tab_id": "wS:t9", "cwd": "/nope", "agent_status": "idle",
                             "agent_session": {"value": "s1"}}, tabs={}, agent_read=text)
        cli = nombres.load_cli()
        cli.project = lambda arg: ("pA", "/nope/.git")
        cli.render_nota = lambda pid, e: "nota corta"
        cli.RENAME_ESPERA = 1
        import contextlib
        import io
        buf = io.StringIO()
        t0 = time.time()
        with contextlib.redirect_stdout(buf):
            rc = cli.cmd_entrega(type("A", (), {"proyecto": "pA", "agente": "nope-arreglar", "pasos": "rename,nota",
                                                "timeout": timeout})())
        return rc, buf.getvalue(), time.time() - t0

    def test_an_empty_box_after_the_rename_lets_the_note_go_at_once(self):
        rc, out, took = self.run_entrega("caja-a1.ansi")
        self.assertNotIn("sin confirmar por hook", out)
        self.assertIn(["agent", "prompt", "wS:p9", "nota corta"], self.calls())
        self.assertLess(took, 3.2)  # the note's own wait (2 s, no hook in the stub); before: 2 more for the rename

    def test_a_box_that_still_holds_text_stops_the_note(self):
        rc, out, _ = self.run_entrega("caja-borrador.ansi")
        self.assertEqual(rc, 4)
        self.assertIn("NO ENTREGADO", out)
        self.assertNotIn(["agent", "prompt", "wS:p9", "nota corta"], self.calls())


def edit_ok(path, tid="e1", error=False):
    """An Edit call of another agent and its result: only a call that succeeded is its authorship (adversary r3)."""
    return [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": "Edit",
                                                           "input": {"file_path": path, "old_string": "a", "new_string": "b"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "is_error": error,
                                                      "content": "Error: no match" if error else "ok"}]}}]


class PublicaSharedCheckoutTest(f3.GitCase):
    """B4: in 3-tier-memory two agents on the main checkout got SUCIO over 6 files of another session, and the
    refused one kept «turno» for 6.6 h."""

    def shared(self):
        a = self.worktree("uno", "sa")
        b = self.agent("sb", nombre="dos", tarea="p-dos", worktree=a["worktree"], cwd=a["worktree"],
                       base="origin/main", branch="lookout/uno")
        return a, b

    def test_files_another_agent_left_uncommitted_do_not_refuse(self):
        a, _b = self.shared()
        p = os.path.join(a["worktree"], "VERSION")
        with open(p, "a") as fh:
            fh.write("de otra sesión\n")
        self.transcript("sb", edit_ok(p))
        ok, code, lines = self.ask(a)
        self.assertEqual((ok, code), (True, "LISTA"), lines)
        self.assertTrue(any(l.startswith("Aviso: el checkout es compartido") and "VERSION" in l for l in lines), lines)

    def test_a_write_lookout_cannot_see_stays_the_agents_own(self):
        # adversary round 1: a generator script, `git stash pop` or a subagent writes without an Edit lookout can read
        a, _b = self.shared()
        with open(os.path.join(a["worktree"], "VERSION"), "a") as fh:
            fh.write("generado\n")
        self.transcript("sa", [f3.a_tool("Bash", {"command": "python3 gen_version.py && make format"})])
        self.transcript("sb", [f3.a_tool("Bash", {"command": "git status"})])
        self.assertEqual(self.ask(a)[1], "SUCIO")

    def test_a_file_the_agent_edited_still_refuses(self):
        a, _b = self.shared()
        p = os.path.join(a["worktree"], "uno.txt")
        with open(p, "a") as fh:
            fh.write("sin commit\n")
        self.transcript("sa", [f3.a_tool("Edit", {"file_path": p, "old_string": "a", "new_string": "b"})])
        self.assertEqual(self.ask(a)[1], "SUCIO")

    def test_what_another_agents_bash_seems_to_write_does_not_make_a_file_its(self):
        # adversary round 2 (codex): escrituras_bash over-reports («if false; then echo … > VERSION»)
        a, _b = self.shared()
        with open(os.path.join(a["worktree"], "VERSION"), "a") as fh:
            fh.write("propio, por un script\n")
        self.transcript("sb", [f3.a_tool("Bash", {"command": "if false; then echo x > VERSION; fi"})])
        self.assertEqual(self.ask(a)[1], "SUCIO")

    def test_an_agent_whose_task_ended_does_not_share_the_tree(self):
        a, _b = self.shared()
        p = os.path.join(a["worktree"], "VERSION")
        with open(p, "a") as fh:
            fh.write("x\n")
        self.transcript("sb", edit_ok(p))
        reg = registry.load(self.pid)
        reg["agents"]["sb"]["tarea_estado"] = "terminada"
        registry.save(self.pid, reg)
        self.assertEqual(self.ask(a)[1], "SUCIO")

    def test_a_failed_edit_of_another_agent_is_not_its_authorship(self):
        a, _b = self.shared()
        p = os.path.join(a["worktree"], "VERSION")
        with open(p, "a") as fh:
            fh.write("x\n")
        self.transcript("sb", edit_ok(p, error=True))
        self.assertEqual(self.ask(a)[1], "SUCIO")

    def test_its_own_tree_counts_every_file(self):
        a = self.worktree("uno", "sa")
        with open(os.path.join(a["worktree"], "VERSION"), "a") as fh:
            fh.write("x\n")
        self.assertEqual(self.ask(a)[1], "SUCIO")

    def test_a_refused_check_frees_the_turn(self):
        a = self.worktree("uno", "sa")
        with open(os.path.join(a["worktree"], "VERSION"), "a") as fh:
            fh.write("x\n")
        self.assertEqual(self.ask(a)[1], "SUCIO")
        self.assertEqual([p["estado"] for p in publica.load(self.pid)["cola"]], ["rechazada"])
        b = self.worktree("dos", "sb", version="0.3.0")
        self.assertEqual(self.ask(b)[1], "LISTA")  # before: ESPERA behind a «turno» nobody held
        subprocess.run(["git", "-C", a["worktree"], "checkout", "--", "VERSION"], check=True)
        publica.retira(self.pid, b)
        self.assertEqual(self.ask(a)[1], "LISTA")  # asking again re-checks from the start


if __name__ == "__main__":
    unittest.main()

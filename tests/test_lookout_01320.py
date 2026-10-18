"""0.13.20: `lookout retoma` starts again, with `claude --resume`, an agent whose session ended without anyone asking.

Live case (3-tier, 2026-10-17 22:42:48): a stray `pkill … -n` killed three reliefs (SessionEnd reason «other»). Their
panes stayed open at a shell prompt, but they left the digest table («+N terminados»), `relevo` needs the session alive
and `lanza` opens new agents only; the supervisor asked the user to type `claude --resume` by hand. Measured the next
morning: `claude --resume <sid>` keeps the session id (its SessionStart comes with source «resume»), so the marker and
the registry entry still hold. Now the digest keeps such an agent in «Te necesita» with the command, and `retoma`
starts it in its own pane (or a new tab on its folder when the pane is gone) with the flags it ran with.
Run: python3 -m unittest tests/test_lookout_01320.py
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_lookout_f3 import Base, HAIKU, a_text  # noqa: E402

import digest  # noqa: E402
import lookout_state  # noqa: E402
import registry  # noqa: E402
import retoma  # noqa: E402


class RetomaCase(Base):
    def setUp(self):
        super().setUp()
        self.saved = (retoma.herdr_cli.pane_get, retoma.herdr_cli.agent_get, retoma.herdr_cli.run_json,
                      retoma.herdr_cli.run, retoma.lote.arranca, retoma.lote.live_sessions, retoma.lote.unique_name)
        self.started = []
        self.pane = {"pane_id": "w1:p1", "foreground_cwd": "/x", "cwd": "/x", "tab_id": "w1:t1"}
        retoma.herdr_cli.pane_get = lambda p: (True, dict(self.pane)) if self.pane else (False, None)
        retoma.herdr_cli.agent_get = lambda p: None
        retoma.herdr_cli.run_json = lambda args, timeout=10: self.created.append(args) or {
            "root_pane": {"pane_id": "w9:p1", "tab_id": "w9:t1"}}
        retoma.herdr_cli.run = lambda args, timeout=10: (0, "", "")
        retoma.lote.live_sessions = lambda agents=None: set()
        retoma.lote.unique_name = lambda n, agents=None: n
        self.created = []

        def arranca(pid, sid, pane, wt, nombre, sysfile, modelo, lectura, clave, trigger, confirmar, log,
                    puerto_de=None, esfuerzo="", permisos="", resume=False):
            self.started.append(dict(sid=sid, pane=pane, wt=wt, nombre=nombre, sysfile=sysfile, modelo=modelo,
                                     clave=clave, trigger=trigger, esfuerzo=esfuerzo, permisos=permisos, resume=resume))
            retoma.lote.set_estado(pid, sid, "trabajando", hooks="ok")
            return True, "lanzado"
        retoma.lote.arranca = arranca

    def tearDown(self):
        (retoma.herdr_cli.pane_get, retoma.herdr_cli.agent_get, retoma.herdr_cli.run_json, retoma.herdr_cli.run,
         retoma.lote.arranca, retoma.lote.live_sessions, retoma.lote.unique_name) = self.saved
        super().tearDown()

    def muerto(self, sid="s1", razon="other", **kw):
        self.agent(sid, nombre="ag", herdr_name="ag-2", prompt_sistema="/x/tareas/ag.relevo3.sistema.md",
                   esfuerzo="medium", permisos="auto", tarea_estado="trabajando", **kw)
        reg = registry.load(self.pid)
        reg["agents"][sid]["modelo"] = "claude-opus-5-5[1m]"  # Base.agent's `modelo` goes to its start event
        registry.save(self.pid, reg)
        self.transcript_en(sid, "-x")
        lookout_state.append_event(self.pid, {"session_id": sid, "event": "end", "hook": "SessionEnd", "razon": razon,
                                              "ts": time.time()})
        return registry.load(self.pid)["agents"][sid]

    def transcript_en(self, sid, carpeta):
        import json
        d = os.path.join(self.projects, carpeta)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, sid + ".jsonl"), "a") as fh:
            fh.write(json.dumps(a_text("trabajando")) + "\n")

    def go(self, sid="s1"):
        return retoma.retoma(self.pid, registry.load(self.pid)["agents"][sid], 1, lambda m: None)


class RetomaTest(RetomaCase):
    def test_a_dead_agent_in_its_live_pane_is_resumed_with_its_flags(self):
        self.muerto()
        ok, msg = self.go()
        self.assertTrue(ok, msg)
        s = self.started[0]
        self.assertEqual((s["sid"], s["pane"], s["wt"], s["resume"]), ("s1", "w1:p1", "/x", True))
        self.assertEqual((s["nombre"], s["sysfile"]), ("ag-2", "/x/tareas/ag.relevo3.sistema.md"))
        self.assertEqual((s["modelo"], s["esfuerzo"], s["permisos"]), ("claude-opus-5-5[1m]", "medium", "auto"))
        self.assertIn("terminó", s["trigger"])
        self.assertIn("SendMessage", s["trigger"])
        e = registry.load(self.pid)["agents"]["s1"]
        self.assertEqual((e["retomado_n"], e["tarea_estado"]), (1, "trabajando"))

    def test_a_second_resume_uses_a_new_delivery_key(self):
        self.muerto()
        self.go()
        lookout_state.append_event(self.pid, {"session_id": "s1", "event": "start", "ts": time.time()})
        lookout_state.append_event(self.pid, {"session_id": "s1", "event": "end", "razon": "other", "ts": time.time()})
        ok, msg = self.go()
        self.assertTrue(ok, msg)
        self.assertNotEqual(self.started[0]["clave"], self.started[1]["clave"])
        self.assertEqual(registry.load(self.pid)["agents"]["s1"]["retomado_n"], 2)

    def test_a_live_session_is_not_resumed(self):
        self.agent("s1", herdr_name="ag", prompt_sistema="/x/a.md", modelo=HAIKU, esfuerzo="low", permisos="auto")
        ok, msg = self.go()
        self.assertFalse(ok)
        self.assertIn("no terminó", msg)
        self.assertEqual(self.started, [])

    def test_a_pane_with_another_live_session_is_not_touched(self):
        self.muerto()
        retoma.herdr_cli.agent_get = lambda p: {"agent_session": {"value": "otra"}, "agent_status": "idle"}
        ok, msg = self.go()
        self.assertFalse(ok)
        self.assertIn("otra sesión", msg)
        self.assertEqual(self.started, [])

    def test_a_pane_in_another_folder_is_refused(self):
        self.muerto()
        self.pane["foreground_cwd"] = "/otra"
        ok, msg = self.go()
        self.assertFalse(ok)
        self.assertIn("/otra", msg)
        self.assertEqual(self.started, [])

    def test_a_gone_pane_gets_a_new_tab_on_its_folder(self):
        self.muerto()
        self.pane = None
        ok, msg = self.go()
        self.assertTrue(ok, msg)
        self.assertEqual(self.created[0][:4], ["workspace", "create", "--cwd", "/x"])
        self.assertEqual(self.started[0]["pane"], "w9:p1")
        e = registry.load(self.pid)["agents"]["s1"]
        self.assertEqual((e["pane_id"], e["tab_id"]), ("w9:p1", "w9:t1"))

    def test_a_failed_relief_goes_to_relevo(self):
        self.muerto()
        reg = registry.load(self.pid)
        reg["agents"]["s1"]["tarea_estado"] = "relevo-fallido"
        registry.save(self.pid, reg)
        ok, msg = self.go()
        self.assertFalse(ok)
        self.assertIn("lookout relevo", msg)

    def test_relieved_or_closed_agents_are_not_resumed(self):
        for extra in ({"tarea_estado": "relevada"}, {"retirado": "2026-10-17T10:00:00"}):
            self.muerto()
            reg = registry.load(self.pid)
            reg["agents"]["s1"].update(extra)
            registry.save(self.pid, reg)
            ok, msg = self.go()
            self.assertFalse(ok, extra)
        self.assertEqual(self.started, [])

    def test_without_its_transcript_there_is_nothing_to_resume(self):
        self.agent("s9", nombre="ag", prompt_sistema="/x/a.md", modelo=HAIKU, esfuerzo="low", permisos="auto")
        lookout_state.append_event(self.pid, {"session_id": "s9", "event": "end", "razon": "other", "ts": time.time()})
        ok, msg = self.go("s9")
        self.assertFalse(ok)
        self.assertIn("transcript", msg)


    def test_a_transcript_of_another_folder_is_refused(self):
        self.agent("s8", nombre="ag", prompt_sistema="/x/a.md", esfuerzo="low", permisos="auto")
        self.transcript_en("s8", "-otra")
        lookout_state.append_event(self.pid, {"session_id": "s8", "event": "end", "razon": "other", "ts": time.time()})
        ok, msg = self.go("s8")
        self.assertFalse(ok)
        self.assertIn("-otra", msg)
        self.assertEqual(self.started, [])

    def test_a_failed_start_is_not_a_failed_launch(self):
        import lote
        self.muerto()
        retoma.lote.arranca = lambda pid, sid, *a, **k: (lote.set_estado(pid, sid, "fallida", "sin SessionStart"),
                                                          (False, "no llegó el SessionStart"))[1]
        ok, msg = self.go()
        self.assertFalse(ok)
        e = registry.load(self.pid)["agents"]["s1"]
        self.assertEqual(e["tarea_estado"], "retoma-fallida")
        self.assertFalse(lote.retryable(e, set()))
        self.assertIn("lookout retoma", digest.render(self.pid, mark=False))


class ArrancaResumeTest(RetomaCase):
    def test_resume_replaces_session_id_and_nothing_else_changes(self):
        import lote
        lote.arranca = self.saved[4]
        seen = []
        saved = (lote.herdr_cli.run, lote.deliver.wait_event)
        lote.herdr_cli.run = lambda args, timeout=10: seen.append(args) or (0, "", "")
        lote.deliver.wait_event = lambda *a, **k: False
        try:
            self.agent("s1")
            lote.arranca(self.pid, "s1", "w1:p1", "/x", "ag", "/x/a.md", "m", False, "k", "t", 1, lambda m: None,
                         resume=True)
            lote.arranca(self.pid, "s1", "w1:p1", "/x", "ag", "/x/a.md", "m", False, "k", "t", 1, lambda m: None)
        finally:
            lote.herdr_cli.run, lote.deliver.wait_event = saved
        starts = [a for a in seen if a[:2] == ["agent", "start"]]
        self.assertIn("--resume", starts[0])
        self.assertNotIn("--session-id", starts[0])
        self.assertIn("--session-id", starts[1])
        self.assertNotIn("--resume", starts[1])
        self.assertEqual(starts[0][starts[0].index("--resume") + 1], "s1")
        for a in starts:
            self.assertEqual(a[a.index("-n") + 1], "ag")
            self.assertIn("--append-system-prompt-file", a)


class DigestMuertoTest(RetomaCase):
    def test_the_digest_keeps_it_with_the_command(self):
        self.muerto()
        out = digest.render(self.pid, mark=False)
        self.assertIn("Te necesita", out)
        fila = [l for l in out.splitlines() if "ag" in l and "retoma" in l]
        self.assertTrue(fila, out)
        self.assertIn("`lookout retoma %s ag`" % self.pid, fila[0])
        self.assertIn("other", fila[0])

    def test_an_exit_typed_by_someone_is_not_a_death(self):
        self.muerto(razon="prompt_input_exit")
        self.assertNotIn("retoma", digest.render(self.pid, mark=False))


if __name__ == "__main__":
    unittest.main()

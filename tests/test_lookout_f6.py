"""Unit tests for Fase 6 of lookout: stuck heuristics, ports, grouped view, Bash writes into another project.
Run: python3 -m unittest tests/test_lookout_f6.py

Every test points LOOKOUT_STATE_DIR at a temp folder and replaces herdr with a stub that records its arguments
(and, for `agent list`, prints what the test put in $HERDR_STUB_AGENTS), so nothing touches a real herdr.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "plugins", "lookout", "bin")
GUARD = os.path.join(ROOT, "plugins", "lookout", "hooks", "guard.sh")
sys.path.insert(0, BIN)

import digest  # noqa: E402
import herdr_cli  # noqa: E402
import heuristicas  # noqa: E402
import lookout_state  # noqa: E402
import lote  # noqa: E402
import on_state  # noqa: E402
import ports  # noqa: E402
import registry  # noqa: E402
import wait_event  # noqa: E402

PID = "pF6"
STUB = r'''#!/bin/sh
echo "$@" >> "%(log)s"
if [ "$1 $2" = "agent list" ]; then cat "%(agents)s" 2>/dev/null || echo '{"result":{"agents":[]}}'; exit 0; fi
echo '{"result":{}}'
'''


def git(*args, cwd=None):
    subprocess.run(["git"] + list(args), cwd=cwd, check=True, capture_output=True)


class F6Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = os.path.realpath(self.tmp.name)
        self.t = t
        self.state = os.path.join(t, "state")
        self.log = os.path.join(t, "herdr.log")
        self.agents_file = os.path.join(t, "agents.json")
        stub = os.path.join(t, "herdr")
        with open(stub, "w") as fh:
            fh.write(STUB % {"log": self.log, "agents": self.agents_file})
        os.chmod(stub, 0o755)
        keys = ("LOOKOUT_STATE_DIR", "HERDR_BIN_PATH", "HERDR_PANE_ID", "LOOKOUT_MIRAR_S", "LOOKOUT_ESCALAR_S",
                "LOOKOUT_LARGO_S", "LOOKOUT_REVISA_CADA", "LOOKOUT_EXEC_SETTINGS", "CLAUDE_PID", "LOOKOUT_PORT_BASE")
        self.saved = {k: os.environ.get(k) for k in keys}
        for k in keys:
            os.environ.pop(k, None)
        os.environ.update({"LOOKOUT_STATE_DIR": self.state, "HERDR_BIN_PATH": stub, "HERDR_PANE_ID": "w9:p1"})
        self.old_herdr = herdr_cli.HERDR
        herdr_cli.HERDR = stub
        self.wt = os.path.join(t, "repo-wt-x")
        os.makedirs(self.wt)
        git("init", "-q", "-b", "main", cwd=self.wt)
        reg = {"agents": {"s1": {"session_id": "s1", "nombre": "e1", "pane_id": "w9:p1", "worktree": self.wt,
                                  "cwd": self.wt, "branch": "x", "tarea": "p-1", "tarea_estado": "trabajando"}}}
        registry.save(PID, reg)
        self.marker = {"project_id": PID, "nombre": "e1", "display": "e1 (lookout)"}
        lookout_state.write_marker("s1", self.marker)

    def tearDown(self):
        herdr_cli.HERDR = self.old_herdr
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def calls(self):
        try:
            with open(self.log) as fh:
                return fh.read()
        except OSError:
            return ""

    def events(self, kind=None):
        evs = lookout_state.read_events(PID, 0)[0]
        return [e for e in evs if kind is None or e.get("event") == kind]

    def hook(self, payload, python="python3"):
        """Run the real hook path (guard.sh -> on_state.py) with this payload."""
        data = dict({"session_id": "s1"}, **payload)
        env = dict(os.environ)
        if python != "python3":
            out = subprocess.run([python, os.path.join(BIN, "on_state.py")], input=json.dumps(data), text=True,
                                 env=env, capture_output=True)
        else:
            out = subprocess.run(["sh", GUARD, "on_state.py"], input=json.dumps(data), text=True, env=env,
                                 capture_output=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout, "")

    def fail(self, msg="falta el archivo config.ini en /tmp/a/123", cmd="python3 check.py"):
        self.hook({"hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "tool_input": {"command": cmd},
                   "error": "Exit code 1\n" + msg, "is_interrupt": False})

    def set_agents(self, agents):
        with open(self.agents_file, "w") as fh:
            json.dump({"result": {"agents": agents}}, fh)


class FirmaTest(unittest.TestCase):
    def test_same_error_other_path_or_number_is_the_same(self):
        a = heuristicas.firma("Bash", "Exit code 1\nError: cannot open /tmp/a/b.txt line 12")
        b = heuristicas.firma("Bash", "Exit code 1\nError: cannot open /var/x/y.txt line 99")
        self.assertEqual(a, b)
        self.assertIn("Exit code 1", a)

    def test_other_error_or_tool_differs(self):
        a = heuristicas.firma("Bash", "Exit code 1\nError: cannot open x")
        self.assertNotEqual(a, heuristicas.firma("Bash", "Exit code 2\nError: cannot open x"))
        self.assertNotEqual(a, heuristicas.firma("Bash", "Exit code 1\nModuleNotFoundError: foo"))
        self.assertNotEqual(a, heuristicas.firma("Read", "Exit code 1\nError: cannot open x"))

    def test_real_spike_payload(self):
        # tests/spikes/evidencia/f6/probe.jsonl: the PostToolUseFailure of `python3 check.py`
        self.assertEqual(heuristicas.firma("Bash", "Exit code 1\nfalta el archivo config.ini"),
                         "Bash | Exit code 1 | falta el archivo config.ini")


class RepiteTest(F6Case):
    def test_third_same_error_adds_one_repite(self):
        self.fail()
        self.fail(msg="falta el archivo config.ini en /otra/ruta/9")
        self.assertEqual(self.events("repite"), [])
        self.fail()
        rep = self.events("repite")
        self.assertEqual(len(rep), 1)
        self.assertEqual((rep[0]["veces"], rep[0]["correcciones"], rep[0]["replantea"]), (3, 0, False))
        self.assertEqual(len(rep[0]["intentos"]), 3)
        self.fail()  # a 4th of the same streak does not wake again
        self.assertEqual(len(self.events("repite")), 1)
        cnt = lookout_state.read_json(heuristicas.counters_path(PID))
        e = list(cnt["agentes"]["s1"]["errores"].values())[0]
        self.assertEqual((e["seguidos"], e["correcciones"]), (4, 0))

    def test_interrupt_and_other_errors_do_not_count(self):
        self.hook({"hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "tool_input": {"command": "x"},
                   "error": "Exit code 1\nfalta el archivo config.ini", "is_interrupt": True})
        self.fail()
        self.fail(msg="otra cosa distinta")
        self.fail()
        self.assertEqual(self.events("repite"), [])
        self.assertEqual(len(self.events("fallo")), 3)

    def test_two_corrections_then_stop_and_rethink(self):
        e = registry.find(registry.load(PID), "e1")
        code, txt = heuristicas.corrige(PID, e, "resumen suficientemente largo para pasar")
        self.assertEqual(code, 5)  # nothing repeated yet
        for _ in range(3):
            self.fail()
        code, txt = heuristicas.corrige(PID, e, "corto")
        self.assertEqual(code, 5)
        code, txt = heuristicas.corrige(PID, e, "check.py busca config.ini; créalo copiando config.example.ini")
        self.assertEqual(code, 0)
        self.assertIn("Corrección 1 de 2", txt)
        self.assertIn("corre UNA vez el mismo comando", txt)
        code, _ = heuristicas.corrige(PID, e, "otra corrección sin que el error haya vuelto")
        self.assertEqual(code, 5)  # the correction has not failed yet
        self.fail()  # the agent checked once: same error -> the correction failed
        rep = self.events("repite")
        self.assertEqual((len(rep), rep[-1]["correcciones"], rep[-1]["replantea"]), (2, 1, False))
        self.fail()  # more of the same before the next correction: no new wake
        self.assertEqual(len(self.events("repite")), 2)
        code, txt = heuristicas.corrige(PID, e, "segunda corrección con otro enfoque concreto")
        self.assertEqual(code, 0)
        self.assertIn("Corrección 2 de 2", txt)
        self.fail()
        rep = self.events("repite")
        self.assertEqual((len(rep), rep[-1]["correcciones"], rep[-1]["replantea"]), (3, 2, True))
        code, txt = heuristicas.corrige(PID, e, "una tercera corrección que no debe salir")
        self.assertEqual(code, 5)
        self.assertTrue(txt.startswith("PARA"))
        self.assertEqual(len(self.events("correccion")), 2)
        self.assertIn("PARA Y REPLANTEA", digest.describe(rep[-1]))

    def agent_says(self, text):
        """Append a SendMessage the agent itself sent, now, to its own transcript (projects dir of the test)."""
        import datetime
        d = os.path.join(self.t, "projects", "-repo")
        os.makedirs(d, exist_ok=True)
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        line = {"type": "assistant", "timestamp": ts, "message": {"content": [
            {"type": "tool_use", "name": "SendMessage", "input": {"to": "uds:/x.sock", "message": text}}]}}
        with open(os.path.join(d, "s1.jsonl"), "a") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")

    def test_a_verified_report_counts_as_a_failed_correction(self):
        P = os.path.join(self.t, "projects")
        e = registry.find(registry.load(PID), "e1")
        for _ in range(3):
            self.fail()
        self.assertEqual(heuristicas.corrige(PID, e, "check.py busca config.ini; créalo copiando config.example.ini",
                                             projects_dir=P)[0], 0)
        code, txt = heuristicas.corrige(PID, e, "segunda corrección concreta y aplicable", projects_dir=P)
        self.assertEqual(code, 5)
        self.assertIn("--reporte", txt)
        # a quote the agent never sent is refused (adversary F6 round 4: the supervisor's word is not evidence)
        code, txt = heuristicas.corrige(PID, e, "segunda corrección concreta y aplicable",
                                        reporte="Apliqué la corrección y check.py sigue igual", projects_dir=P)
        self.assertEqual(code, 5)
        self.assertIn("no encuentro esa cita", txt)
        time.sleep(0.01)
        self.agent_says("Apliqué la corrección y check.py sigue igual: mismo error de config.ini")
        code, txt = heuristicas.corrige(PID, e, "segunda corrección concreta y aplicable",
                                        reporte="apliqué la corrección y   check.py sigue igual", projects_dir=P)
        self.assertEqual(code, 0)
        self.assertIn("Corrección 2 de 2", txt)
        self.assertIn("corre UNA vez el mismo comando", txt)
        self.assertTrue(self.events("correccion")[-1]["fallo_por_reporte"].startswith("apliqué"))
        self.assertIn("según su reporte", digest.describe(self.events("correccion")[-1]))
        # after correction 2: an unverified report still gets PARA (it always stops) but records nothing
        code, txt = heuristicas.corrige(PID, e, "tercera que no debe salir", reporte="inventado por el supervisor xx",
                                        projects_dir=P)
        self.assertEqual(code, 5)
        self.assertTrue(txt.startswith("PARA"))
        self.assertEqual(self.events("correccion_fallida"), [])
        time.sleep(0.01)
        self.agent_says("Tampoco funcionó la segunda corrección que me mandaste")
        code, txt = heuristicas.corrige(PID, e, "tercera que no debe salir",
                                        reporte="Tampoco funcionó la segunda corrección", projects_dir=P)
        self.assertEqual(code, 5)
        self.assertTrue(txt.startswith("PARA"))
        cf = self.events("correccion_fallida")
        self.assertEqual([(x["numero"], x["reporte"][:8]) for x in cf], [(2, "Tampoco ")])
        self.assertEqual(len(self.events("correccion")), 2)

    def test_counters_rebuild_from_events_after_relief(self):
        for _ in range(3):
            self.fail()
        e = registry.find(registry.load(PID), "e1")
        heuristicas.corrige(PID, e, "check.py busca config.ini; créalo copiando config.example.ini")
        before = lookout_state.read_json(heuristicas.counters_path(PID))["agentes"]
        os.remove(heuristicas.counters_path(PID))  # a relieved supervisor, a lost file
        heuristicas.guarda_contadores(PID)
        self.assertEqual(lookout_state.read_json(heuristicas.counters_path(PID))["agentes"], before)

    def test_new_session_start_resets_the_streak(self):
        self.fail()
        self.fail()
        self.hook({"hook_event_name": "SessionStart", "source": "startup"})
        self.fail()
        self.assertEqual(self.events("repite"), [])

    def test_repite_notifies_the_user_once(self):
        for _ in range(4):
            self.fail()
        self.assertEqual(self.calls().count("notification show"), 1)
        self.assertIn("te necesita", self.calls())

    def test_hook_under_system_python(self):
        if not os.path.exists("/usr/bin/python3"):
            self.skipTest("no /usr/bin/python3")
        for _ in range(3):
            self.hook({"hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "tool_input": {"command": "x"},
                       "error": "Exit code 1\nboom"}, python="/usr/bin/python3")
        self.assertEqual(len(self.events("repite")), 1)


class PausaTest(F6Case):
    def test_rate_limit_is_a_pause_not_a_failure(self):
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "hola"})
        self.hook({"hook_event_name": "StopFailure", "error": "rate_limit", "error_details": "429 Too Many Requests",
                   "last_assistant_message": "API Error: Rate limit reached"})
        p = self.events("pausa")
        self.assertEqual(len(p), 1)
        self.assertEqual(self.events("unknown"), [])
        self.assertNotIn("pausa", digest.WAKE_TYPES.split(","))
        self.assertEqual(registry.find(registry.load(PID), "e1")["tarea_estado"], "trabajando")
        self.assertNotIn("notification show", self.calls())
        self.assertIn("estado=pausa", self.calls())
        out = digest.render(PID, mark=False)
        self.assertIn("En pausa (proveedor):", out)
        self.assertIn("no es falla", out)

    def test_overloaded_pauses_auth_error_does_not(self):
        self.hook({"hook_event_name": "StopFailure", "error": "overloaded"})
        self.hook({"hook_event_name": "StopFailure", "error": "authentication_failed"})
        self.assertEqual([e["event"] for e in self.events() if e["event"] in ("pausa", "unknown")], ["pausa", "unknown"])


class RevisaTest(F6Case):
    def working(self, age, pid=4242):
        lookout_state.append_event(PID, {"session_id": "s1", "nombre": "e1", "event": "working", "claude_pid": pid,
                                         "ts": time.time() - age})

    def run_revisa(self, herdr_status, proc, reciente=False, age=None):
        agents = [] if herdr_status == "ausente" else [
            {"agent_session": {"value": "s1"}, "pane_id": "w9:p1", "agent_status": herdr_status}]
        return heuristicas.revisa(PID, agents=agents, proceso=lambda _pid: proc, reciente=lambda *_: reciente)

    def test_alive_and_busy_is_never_stuck(self):
        self.working(1300)  # past the 20 min escalation threshold
        self.assertEqual(self.run_revisa("working", "vivo"), [])
        self.assertEqual(self.events("sin_progreso"), [])

    def test_alive_for_hours_gets_one_look(self):
        self.working(3700)
        out = self.run_revisa("working", "vivo")
        self.assertEqual([e["event"] for e in out], ["largo"])
        self.assertEqual(self.run_revisa("working", "vivo"), [])  # once

    def test_escalation_moves_the_group_and_notifies_once(self):
        self.working(1300)
        self.run_revisa("ausente", "detenido")
        self.assertEqual(lookout_state.read_json(heuristicas.grupos_path(PID))["s1"]["grupo"], "te_necesita")
        self.assertEqual(self.calls().count("notification show"), 1)
        self.run_revisa("ausente", "detenido")
        self.assertEqual(self.calls().count("notification show"), 1)

    def test_stopped_process_is_flagged_with_two_sources(self):
        self.working(1300)
        out = self.run_revisa("ausente", "detenido")
        self.assertEqual([(e["event"], e["nivel"]) for e in out], [("sin_progreso", "escalar")])
        self.assertEqual(len(out[0]["fuentes"]), 3)
        self.assertEqual(self.run_revisa("ausente", "detenido"), [])  # once per level
        self.assertEqual(heuristicas.grupo(self.events(), "s1"), "te_necesita")

    def test_herdr_idle_with_live_process_is_a_look_before_escalating(self):
        self.working(400)
        out = self.run_revisa("idle", "vivo")
        self.assertEqual([(e["event"], e["nivel"]) for e in out], [("sin_progreso", "mirar")])
        self.assertEqual(heuristicas.grupo(self.events(), "s1"), "trabajando")

    def test_one_source_is_not_enough(self):
        self.working(1300)
        self.assertEqual(self.run_revisa("working", "desconocido"), [])

    def test_worktree_changing_is_progress(self):
        self.working(1300)
        self.assertEqual(self.run_revisa("idle", "detenido", reciente=True), [])

    def test_recent_or_idle_agent_is_not_checked(self):
        self.working(100)
        self.assertEqual(self.run_revisa("ausente", "muerto"), [])
        lookout_state.append_event(PID, {"session_id": "s1", "event": "idle", "ts": time.time() - 5000})
        self.assertEqual(self.run_revisa("ausente", "muerto"), [])

    def test_real_process_states(self):
        self.assertEqual(heuristicas.estado_proceso(os.getpid()), "vivo")
        p = subprocess.Popen(["python3", "-c", "import time; time.sleep(30)"])
        try:
            os.kill(p.pid, 19)  # SIGSTOP
            time.sleep(0.3)
            self.assertEqual(heuristicas.estado_proceso(p.pid), "detenido")
        finally:
            p.kill()
            p.wait()
        self.assertEqual(heuristicas.estado_proceso(p.pid), "muerto")
        self.assertEqual(heuristicas.estado_proceso(None), "desconocido")

    def test_worktree_reciente(self):
        since = time.time() - 60
        self.assertFalse(heuristicas.worktree_reciente(self.wt, since))
        with open(os.path.join(self.wt, "nuevo.txt"), "w") as fh:
            fh.write("x")
        self.assertTrue(heuristicas.worktree_reciente(self.wt, since))

    def test_waiter_runs_the_check_and_wakes(self):
        os.environ.update({"LOOKOUT_MIRAR_S": "0.5", "LOOKOUT_ESCALAR_S": "1", "LOOKOUT_REVISA_CADA": "0.2"})
        p = subprocess.Popen(["python3", "-c", "pass"])
        p.wait()  # a Claude pid that is gone
        self.working(1, pid=p.pid)
        self.set_agents([])  # herdr no longer lists it
        path = lookout_state.events_path(PID)
        cmd = [sys.executable, "-c", "import sys; sys.path.insert(0, %r); import wait_event; sys.exit(wait_event.wait("
               "%r, %d, %r, 20, '', '', None, revisa=%r))" % (BIN, path, os.path.getsize(path), digest.WAKE_TYPES, PID)]
        out = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ), timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("sin progreso", out.stdout)
        sp = self.events("sin_progreso")
        self.assertEqual(len(sp), 1)
        self.assertIn("proceso de Claude muerto", " ".join(sp[0]["fuentes"]))
        # the waiter woke on the event but waited for the rest of the pass: grouped view + one notification
        # (Fase 6 run 2: it exited first and killed that half)
        self.assertEqual(lookout_state.read_json(heuristicas.grupos_path(PID))["s1"]["grupo"], "te_necesita")
        self.assertEqual(self.calls().count("notification show"), 1)


class VistaTest(F6Case):
    def test_groups_and_notifications_only_on_transitions(self):
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "tarea"})
        self.hook({"hook_event_name": "Stop", "last_assistant_message": "hecho", "background_tasks": []})
        self.assertEqual(heuristicas.grupo(self.events(), "s1"), "idle")
        self.assertNotIn("notification show", self.calls())
        lookout_state.append_event(PID, {"session_id": "s1", "event": "idle", "reporto": True})
        heuristicas.transicion(PID, {"session_id": "s1", "event": "idle"})
        self.assertEqual(heuristicas.grupo(self.events(), "s1"), "idle")  # a report alone is not "listo"
        self.assertNotIn("notification show", self.calls())
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "otra"})
        self.hook({"hook_event_name": "Stop", "last_assistant_message": "listo\n[COMPLETION-REVIEW: none reason=xxxxxxxxxxxxxxxxxxxxxx]",
                   "background_tasks": []})
        self.assertEqual(heuristicas.grupo(self.events(), "s1"), "listo")
        self.assertEqual(self.calls().count("notification show"), 1)
        self.hook({"hook_event_name": "Notification", "notification_type": "idle_prompt"})
        self.assertEqual(self.calls().count("notification show"), 1)
        out = digest.render(PID, mark=False)
        self.assertIn("Listo para revisar:", out)

    def test_ask_moves_the_group_without_notifying(self):
        lookout_state.append_event(PID, {"session_id": "s1", "event": "ask"})
        heuristicas.transicion(PID, {"session_id": "s1", "event": "ask"})
        self.assertEqual(heuristicas.grupo(self.events(), "s1"), "te_necesita")
        self.assertNotIn("notification show", self.calls())


class BashWritesTest(unittest.TestCase):
    def w(self, cmd, cwd="/r/a"):
        return heuristicas.escrituras_bash(cmd, cwd)

    def test_write_targets(self):
        self.assertIn("/r/b/f.txt", self.w("echo x > /r/b/f.txt"))
        self.assertIn("/r/b/log", self.w("echo x >> /r/b/log"))
        self.assertIn("/r/b", self.w("cd /r/b && git commit -m x"))
        self.assertIn("/r/b/c.txt", self.w("cd /r/b && touch c.txt"))
        self.assertIn("/r/b/y", self.w("cp a.txt /r/b/y"))
        self.assertIn("/r/b/z", self.w("sed -i '' s/a/b/ /r/b/z"))
        self.assertIn("/r/b", self.w("git -C /r/b add ."))
        self.assertIn("/r/b/t", self.w("ls | tee -a /r/b/t"))
        self.assertIn("/r/b/q", self.w("rm -rf /r/b/q"))
        self.assertIn("/r/b/m", self.w("mkdir -p ../b/m"))
        self.assertIn("/r/b/e", self.w("python3 x.py 2> /r/b/e"))
        self.assertIn("/r/b", self.w("git --work-tree=/r/b add x"))
        self.assertIn("/r/b/.git", self.w("git --git-dir /r/b/.git commit -m x"))
        self.assertIn("/r/b/wt", self.w("git worktree add /r/b/wt -b rama"))
        self.assertIn("/r/b/wt", self.w("git worktree add -b rama /r/b/wt"))
        self.assertNotIn("/r/a/rama", self.w("git worktree add -b rama /r/b/wt"))
        self.assertIn("/r/b/nuevo", self.w("git worktree move ../a-wt /r/b/nuevo"))

    def test_reads_and_unknowns_are_not_writes(self):
        self.assertEqual(self.w("cat /r/b/f.txt"), [])
        self.assertEqual(self.w("git -C /r/b status"), [])
        self.assertEqual(self.w("python3 x.py 2>/dev/null"), [])
        self.assertEqual(self.w("echo x > $HOME/f"), [])
        self.assertEqual(self.w("ls 2>&1"), [])


class BashCrossRepoTest(F6Case):
    def test_bash_write_into_another_locked_project_warns_both(self):
        other = os.path.join(self.t, "otro")
        os.makedirs(other)
        lookout_state.write_json(os.path.join(lookout_state.project_dir("pOTRO"), "lock.json"), {"roots": [other]})
        lookout_state.write_json(os.path.join(lookout_state.project_dir(PID), "lock.json"), {"roots": [self.wt]})
        self.hook({"hook_event_name": "PostToolUse", "tool_name": "Bash", "cwd": self.wt,
                   "tool_input": {"command": "echo hola > %s/notas.txt" % other}})
        mine = self.events("crossrepo")
        theirs = [e for e in lookout_state.read_events("pOTRO", 0)[0] if e.get("event") == "crossrepo"]
        self.assertEqual((len(mine), len(theirs)), (1, 1))
        self.assertEqual(mine[0]["via"], "bash")
        self.assertIn("por Bash", digest.describe(mine[0]))
        self.hook({"hook_event_name": "PostToolUse", "tool_name": "Bash", "cwd": self.wt,
                   "tool_input": {"command": "echo hola > notas.txt"}})
        self.assertEqual(len(self.events("crossrepo")), 1)


class PortsTest(F6Case):
    def test_one_port_per_worktree_stable_and_free(self):
        os.environ["LOOKOUT_PORT_BASE"] = "47100"
        busy = socket.socket()
        busy.bind(("127.0.0.1", 47100))
        busy.listen(1)
        try:
            a = ports.asigna("/r/a-wt-1")
            b = ports.asigna("/r/a-wt-2")
        finally:
            busy.close()
        self.assertNotEqual(a, 47100)  # in use: skipped
        self.assertNotEqual(a, b)
        self.assertEqual(ports.asigna("/r/a-wt-1"), a)  # stable (a relief gets the same)
        self.assertEqual(ports.libera("/r/a-wt-1"), a)
        self.assertIsNone(ports.de("/r/a-wt-1"))

    def test_exec_args_merges_port_into_settings(self):
        f = os.path.join(self.t, "exec.json")
        with open(f, "w") as fh:
            json.dump({"permissions": {"allow": ["Read"]}, "env": {"LOOKOUT_STATE_DIR": "/x"}}, fh)
        os.environ["LOOKOUT_EXEC_SETTINGS"] = f
        args = lote.exec_args("haiku", False, {"PORT": 4107})
        s = json.loads(args[args.index("--settings") + 1])
        self.assertEqual(s["env"], {"LOOKOUT_STATE_DIR": "/x", "PORT": "4107"})
        self.assertEqual(s["permissions"], {"allow": ["Read"]})
        self.assertEqual(args.count("--settings"), 1)
        os.environ["LOOKOUT_EXEC_SETTINGS"] = json.dumps({"env": {"A": "1"}})
        args = lote.exec_args(None, False, {"PORT": 4108})
        self.assertEqual(json.loads(args[args.index("--settings") + 1])["env"], {"A": "1", "PORT": "4108"})

    def test_task_prompt_names_the_port(self):
        os.environ["LOOKOUT_PORT_BASE"] = "47200"
        item = {"id": "p-abc", "origen": "-", "texto": "levanta el server", "prioridad": "Media", "tipo": "codigo",
                "riesgo": "bajo", "archivos": []}
        plan = {"nombre": "x", "rama": "lookout/x", "worktree": "/r/repo-wt-x", "base": "main", "sin_worktree": False,
                "root": self.wt}
        text = lote.render_tarea(PID, item, plan, [item])
        port = ports.de("/r/repo-wt-x")
        self.assertTrue(port and port >= 47200)
        self.assertIn("Puerto para tu servidor de desarrollo: %d" % port, text)
        self.assertIn("$PORT", text)


if __name__ == "__main__":
    unittest.main()

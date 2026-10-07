"""Unit tests for phase 4 (digest budget, supervisor.md, the supervisor's own hooks, relief of the supervisor).
Run: python3 -m unittest tests/test_lookout_f4.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "plugins", "lookout", "bin")
HOOKS = os.path.join(ROOT, "plugins", "lookout", "hooks")
LK = os.path.join(BIN, "lookout")
sys.path.insert(0, BIN)

import decisiones  # noqa: E402
import digest  # noqa: E402
import herdr_cli  # noqa: E402
import lock  # noqa: E402
import lookout_state  # noqa: E402
import on_supervisor  # noqa: E402
import publica  # noqa: E402
import registry  # noqa: E402
import supervisor_md  # noqa: E402

PID = "pF4"
SUP = "s-sup"


def dead_pid():
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "state")
        self.projects = os.path.join(self.tmp.name, "projects")
        self.saved = {k: os.environ.get(k) for k in ("LOOKOUT_STATE_DIR", "CLAUDE_CODE_SESSION_ID", "LOOKOUT_PRESUPUESTO")}
        os.environ["LOOKOUT_STATE_DIR"] = self.state
        os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
        self.old_herdr = herdr_cli.HERDR
        herdr_cli.HERDR = "true"
        import deliver
        self.deliver = deliver
        self.old_tp = deliver.transcript_path
        projects = self.projects
        deliver.transcript_path = lambda sid, pd=None: self.old_tp(sid, pd or projects)
        self.repo = os.path.join(self.tmp.name, "repo")
        lookout_state.write_json(os.path.join(lookout_state.project_dir(PID), "lock.json"), {
            "project_id": PID, "common_dir": self.repo + "/.git", "roots": [self.repo], "desde": "2026-10-02T10:00:00",
            "supervisor": {"session_id": SUP, "pid": os.getpid(), "address": "uds:/tmp/sup.sock", "nombre": "sup"}})

    def tearDown(self):
        herdr_cli.HERDR = self.old_herdr
        self.deliver.transcript_path = self.old_tp
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def agent(self, sid, nombre, tarea="-", **kw):
        reg = registry.load(PID)
        reg.setdefault("agents", {})[sid] = dict({"session_id": sid, "nombre": nombre, "tarea": tarea, "pane_id": "w1:p1",
                                                  "cwd": "/x", "worktree": "/x", "branch": "lookout/" + nombre,
                                                  "hooks": "ok"}, **kw)
        registry.save(PID, reg)

    def transcript(self, sid, lines):
        d = os.path.join(self.projects, "-enc")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, sid + ".jsonl"), "a") as fh:
            for ev in lines:
                fh.write(json.dumps(ev) + "\n")

    def run_lk(self, *args, **env):
        e = dict(os.environ, LOOKOUT_STATE_DIR=self.state, HERDR_BIN_PATH="true", **env)
        return subprocess.run(["python3", LK] + list(args), capture_output=True, text=True, env=e)


class DigestBudgetTest(Base):
    def load(self, agents=10, events=60, decisions=6):
        for i in range(agents):
            self.agent("s%d" % i, "agente-%d" % i, tarea="p-%d" % i)
        for i in range(events):
            sid = "s%d" % (i % agents)
            if i % 7 == 0:
                lookout_state.append_event(PID, {"event": "ask", "session_id": sid, "nombre": "agente-%d" % (i % agents),
                                                 "questions": [{"question": "¿Sigo con la opción %d? " % i + "x" * 400,
                                                                "options": ["A", "B"]}]})
            else:
                lookout_state.append_event(PID, {"event": "idle", "session_id": sid, "nombre": "agente-%d" % (i % agents),
                                                 "ultima": "terminé el paso %d " % i + "y" * 600})
        for i in range(decisions):
            decisiones.abre(PID, "¿Borro el archivo %d? " % i + "z" * 300, ["agente-%d" % i], notificar=False)

    def test_a_heavy_digest_stays_within_40_lines_of_160_columns(self):
        self.load()
        out = digest.render(PID)
        lines = out.splitlines()
        self.assertLessEqual(len(lines), 40, out)
        self.assertLessEqual(max(len(x) for x in lines), 160)
        self.assertIn("Waiter:", out)          # the footer survives the cap
        self.assertIn("Decisiones del usuario pendientes", out)

    def test_all_asks_survive_while_repeated_idles_of_one_agent_fold(self):
        self.agent("s1", "uno")
        self.agent("s2", "dos")
        for i in range(6):
            lookout_state.append_event(PID, {"event": "idle", "session_id": "s1", "nombre": "uno", "ultima": "paso %d" % i})
        lookout_state.append_event(PID, {"event": "ask", "session_id": "s2", "nombre": "dos",
                                         "questions": [{"question": "¿A o B?", "options": ["A", "B"]}]})
        lookout_state.append_event(PID, {"event": "ask", "session_id": "s2", "nombre": "dos",
                                         "questions": [{"question": "¿C o D?", "options": ["C", "D"]}]})
        out = digest.render(PID)
        self.assertIn("¿A o B?", out)
        self.assertIn("¿C o D?", out)
        self.assertIn("paso 5 (+5 antes)", out)
        self.assertNotIn("paso 2", out)

    def test_a_notification_does_not_hide_the_last_real_event(self):
        self.agent("s1", "uno")
        lookout_state.append_event(PID, {"event": "idle", "session_id": "s1", "nombre": "uno", "ultima": "Confirmado, sigo."})
        lookout_state.append_event(PID, {"event": "notification", "session_id": "s1", "nombre": "uno", "tipo": "idle_prompt"})
        out = digest.render(PID)
        self.assertIn("Confirmado, sigo. (+1 antes)", out)
        self.assertNotIn("aviso", out)
        lookout_state.append_event(PID, {"event": "notification", "session_id": "s1", "nombre": "uno", "tipo": "idle_prompt"})
        self.assertIn("aviso (idle_prompt)", digest.render(PID))   # alone, it is shown with its type

    def test_hidden_agents_are_counted(self):
        # Fase 9 E1: clip() collapsed the indent, so "(+0 agentes más)" hid 2 of 9 agents in claude-vzert
        self.load(agents=30, events=0, decisions=0)
        lines = digest.render(PID).splitlines()
        shown = sum(1 for x in lines if x.startswith("  agente-"))
        oculto = next(x for x in lines if "agentes más" in x)
        n = int(oculto.split("+", 1)[1].split()[0])
        self.assertGreater(n, 0)
        self.assertEqual(shown + n, 30)

    def test_events_cut_for_room_come_back_in_the_next_digest(self):
        # Fase 9 E10 (adversary of 0.8.1, round 1): `resumen` used to mark as attended what it cut
        self.agent("s1", "uno")
        for i in range(60):
            lookout_state.append_event(PID, {"event": "ask", "session_id": "s1", "nombre": "uno",
                                             "questions": [{"question": "¿Pregunta %02d?" % i, "options": ["A"]}]})
        primero = digest.render(PID)
        self.assertIn("¿Pregunta 59?", primero)
        self.assertNotIn("¿Pregunta 00?", primero)
        self.assertIn("vuelven en el siguiente resumen", primero)
        vistas = set()
        for _ in range(6):
            out = digest.render(PID)
            vistas |= {"%02d" % i for i in range(60) if "¿Pregunta %02d?" % i in out}
            if "Eventos nuevos: ninguno" in out:
                break
        primeras = {"%02d" % i for i in range(60) if "¿Pregunta %02d?" % i in primero}
        self.assertEqual(vistas | primeras, {"%02d" % i for i in range(60)})  # every one was shown once

    def test_todo_shows_everything(self):
        self.load(agents=3, events=80, decisions=0)
        self.assertGreater(len(digest.render(PID, mark=False, todo=True).splitlines()), 40)

    def test_context_line_only_for_the_lock_owner_and_warns_over_budget(self):
        self.transcript(SUP, [{"type": "assistant", "message": {"id": "m1", "usage": {
            "input_tokens": 3, "cache_read_input_tokens": 125000, "cache_creation_input_tokens": 2000}}}])
        self.assertEqual(digest.presupuesto_line(PID, session_id="otro"), "")
        # 0.7.2: the budget counts from what the session held at `inicia` (a fixed 120k forced a relief after 7
        # minutes on claude-vzert, whose supervisor started at 71k). Without that record: 370k.
        import lock
        self.assertEqual(digest.presupuesto_limite(PID), (370000, 0))
        lock.set_contexto_inicial(PID, "otro", 50000)  # only the lock owner records it
        self.assertEqual(digest.presupuesto_limite(PID), (370000, 0))
        # `inicia` found no usage line yet (the transcript lags): the first summary records the size then
        self.assertEqual(digest.presupuesto_line(PID, session_id=SUP), "Contexto: 127k de 427k (arranque 127k + 300k).")
        lock.set_contexto_inicial(PID, SUP, 90000)  # once recorded for this session, it is kept
        self.assertEqual(digest.presupuesto_limite(PID), (427003, 127003))
        path = os.path.join(lookout_state.project_dir(PID), "lock.json")
        data = lookout_state.read_json(path)
        data["contexto_inicial"] = 71000
        lookout_state.write_json(path, data)
        self.assertIn("Contexto: 127k de 371k (arranque 71k + 300k).", digest.presupuesto_line(PID, session_id=SUP))
        self.transcript(SUP, [{"type": "assistant", "message": {"id": "m2", "usage": {
            "input_tokens": 3, "cache_read_input_tokens": 372000, "cache_creation_input_tokens": 0}}}])
        line = digest.presupuesto_line(PID, session_id=SUP)
        self.assertIn("PRESUPUESTO SUPERADO", line)
        self.assertIn("lookout retomar %s" % PID, line)
        self.transcript(SUP, [{"type": "assistant", "message": {"id": "m3", "usage": {
            "input_tokens": 3, "cache_read_input_tokens": 125000, "cache_creation_input_tokens": 2000}}}])
        os.environ["LOOKOUT_PRESUPUESTO"] = "150000"
        self.assertNotIn("SUPERADO", digest.presupuesto_line(PID, session_id=SUP))
        os.environ["CLAUDE_CODE_SESSION_ID"] = SUP
        self.assertIn("Contexto: 127k de 150k.", digest.render(PID))

    def start_waiter(self, claude_pid, session_id, watch="0.3"):
        env = dict(os.environ, LOOKOUT_STATE_DIR=self.state, LOOKOUT_WATCH_EVERY=watch)
        code = ("import sys; sys.path.insert(0, %r); import wait_event; "
                "sys.exit(wait_event.wait(%r, 0, 'ask', 30, %r, '', {'claude_pid': %d, 'session_id': %r}))"
                % (BIN, lookout_state.events_path(PID), digest.pidfile(PID), claude_pid, session_id))
        w = subprocess.Popen([sys.executable, "-c", code], env=env, stdout=subprocess.PIPE, text=True)
        for _ in range(50):
            if digest.waiter_alive(PID) == w.pid and os.path.exists(digest.pidfile(PID) + ".owner"):
                break
            time.sleep(0.1)
        return w

    def test_an_orphan_waiter_of_a_dead_supervisor_exits_by_itself(self):
        w = self.start_waiter(dead_pid(), "muerta", watch="30")   # slow watchdog: the digest sees it first
        try:
            self.assertEqual(digest.waiter_alive(PID), w.pid)
            self.assertTrue(digest.waiter_owner_dead(PID))
            self.assertIn("ya no supervisa", digest.render(PID))
            self.assertIsNone(w.poll())                            # nobody signals it (no pid reuse risk)
        finally:
            w.kill()
            w.wait()
        w = self.start_waiter(dead_pid(), "muerta")                # normal watchdog: it leaves on its own
        try:
            self.assertEqual(w.wait(timeout=5), 4)
            self.assertIn("ya no supervisa", w.stdout.read())
        finally:
            if w.poll() is None:
                w.kill()

    def test_a_new_waiter_waits_for_the_stale_one_and_takes_its_place(self):
        old = self.start_waiter(dead_pid(), "muerta", watch="1")
        new = self.start_waiter(os.getpid(), SUP)                  # owner = the lock's session: claims after the old exits
        try:
            self.assertEqual(old.wait(timeout=5), 4)
            for _ in range(50):
                if digest.waiter_alive(PID) == new.pid:
                    break
                time.sleep(0.1)
            self.assertEqual(digest.waiter_alive(PID), new.pid)
            self.assertIsNone(new.poll())
        finally:
            for p in (old, new):
                if p.poll() is None:
                    p.kill()
                p.wait()

    def test_after_clear_the_old_sessions_waiter_is_stale(self):
        # same Claude process (alive), the lock now names a new session: the old session's waiter leaves (/clear)
        w = self.start_waiter(os.getpid(), "s-vieja")
        try:
            self.assertEqual(w.wait(timeout=5), 4)
        finally:
            if w.poll() is None:
                w.kill()

    def test_a_waiter_of_a_live_supervisor_is_left_alone(self):
        w = self.start_waiter(os.getpid(), SUP)
        try:
            time.sleep(1.0)                                        # several watchdog rounds
            self.assertIsNone(w.poll())
            self.assertIn("Waiter: vivo", digest.render(PID))
        finally:
            w.kill()
            w.wait()

    def test_the_supervisors_stop_is_blocked_once_without_a_waiter(self):
        supervisor_md.mark_supervisor(SUP, PID)
        out = on_supervisor.stop_check({"session_id": SUP}, PID, SUP, grace=0)
        self.assertEqual(json.loads(out)["decision"], "block")
        self.assertIn("lookout espera %s" % PID, json.loads(out)["reason"])
        self.assertEqual(on_supervisor.stop_check({"stop_hook_active": True}, PID, SUP, grace=0), "")  # no loop
        self.assertEqual(on_supervisor.stop_check({}, PID, "otra-sesion", grace=0), "")               # not the owner
        w = self.start_waiter(os.getpid(), SUP)
        try:
            self.assertEqual(on_supervisor.stop_check({}, PID, SUP, grace=0), "")
        finally:
            w.kill()
            w.wait()
        # a held pidfile with an unreadable pid (-1) is not the supervisor's own waiter either (adversary F4 round 4)
        import fcntl
        with open(digest.pidfile(PID), "w") as fh:
            fh.write("12")                                    # no newline: incomplete, waiter_alive gives -1
        holder = subprocess.Popen([sys.executable, "-c", "import fcntl,os,sys,time;fd=os.open(sys.argv[1],os.O_RDWR);"
                                   "fcntl.flock(fd,fcntl.LOCK_EX);print('ok',flush=True);time.sleep(30)", digest.pidfile(PID)],
                                  stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "ok")
            self.assertEqual(digest.waiter_alive(PID), -1)
            self.assertEqual(json.loads(on_supervisor.stop_check({}, PID, SUP, grace=0))["decision"], "block")
        finally:
            holder.kill()
            holder.wait()
        # a stale waiter (dead owner) does not count as the supervisor's own (adversary F4 round 3, run 4 relief)
        w = self.start_waiter(dead_pid(), "muerta", watch="30")
        try:
            self.assertEqual(json.loads(on_supervisor.stop_check({}, PID, SUP, grace=0))["decision"], "block")
        finally:
            w.kill()
            w.wait()

    def test_the_supervisors_stop_goes_through_a_synchronous_hook(self):
        # claude-vzert, 2026-10-06: the Stop check ran from the async on_state.py entry; an async hook cannot block,
        # so "no hay waiter vivo" reached the supervisor six times as a loose note and it never relaunched its waiter.
        supervisor_md.mark_supervisor(SUP, PID)
        env = dict(os.environ, LOOKOUT_STATE_DIR=self.state)
        ev = {"session_id": SUP, "hook_event_name": "Stop", "stop_hook_active": False}
        for payload in (json.dumps(ev), json.dumps(ev, separators=(",", ":")), json.dumps(ev, indent="\t"),
                        '{"session_id": "%s",\n "stop_hook_active": false,\n\t"hook_event_name" :\t"Stop"}' % SUP):
            if True:  # any valid JSON layout: the event name is read after parsing, not from the text (adversary r1)
                r = subprocess.run(["sh", os.path.join(HOOKS, "guard.sh"), "on_state.py"], input=payload,
                                   capture_output=True, text=True, env=env)
                self.assertEqual((r.returncode, r.stdout), (0, ""))           # the async entry stays silent
                r = subprocess.run(["sh", os.path.join(HOOKS, "guard-sup.sh"), "on_supervisor.py"], input=payload,
                                   capture_output=True, text=True, env=env)
                self.assertEqual(json.loads(r.stdout)["decision"], "block")
        self.assertEqual(lookout_state.read_events(PID, 0)[0], [])   # not logged as an executor event
        stop = json.load(open(os.path.join(HOOKS, "hooks.json")))["hooks"]["Stop"]
        sync = [h for e in stop for h in e["hooks"] if "guard-sup.sh on_supervisor.py" in h["command"]]
        self.assertEqual(len(sync), 1)
        self.assertFalse(sync[0].get("async"))

    def test_a_waiter_wake_carries_the_digest_and_a_relaunch_does_not_repeat_it(self):
        # claude-vzert, 2026-10-06: relaunched without `resumen`, the waiter woke at once on the same 12:58 event,
        # the supervisor took it for broken and stopped launching it.
        self.agent("s-a", "uno")
        lookout_state.append_event(PID, {"event": "bg_wait", "session_id": "s-a", "nombre": "uno", "ts": time.time()})
        r = self.run_lk("espera", PID, "--timeout", "5")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Resumen (ya marcado como atendido", r.stdout)
        self.assertIn("Eventos nuevos (1", r.stdout)
        self.assertNotIn("corre lookout resumen", r.stdout)
        self.assertEqual(digest.get_cursor(PID), os.path.getsize(lookout_state.events_path(PID)))
        r = self.run_lk("espera", PID, "--timeout", "1")
        self.assertEqual(r.returncode, 2, r.stdout)                  # nothing new: it waits, it does not repeat

    def test_two_waiter_wakes_without_resumen_are_both_shown_once(self):
        # the mechanism itself (adversary r1: the end-to-end test below also passes on 0.8.0, which never marked)
        self.agent("s-a", "uno")
        lookout_state.append_event(PID, {"event": "ask", "session_id": "s-a", "nombre": "uno", "ts": time.time()})
        digest.render(PID, mark=True, por_waiter=True)
        lookout_state.append_event(PID, {"event": "idle", "session_id": "s-a", "nombre": "uno", "ts": time.time()})
        digest.render(PID, mark=True, por_waiter=True)
        out = digest.render(PID)
        self.assertIn("Eventos nuevos (2", out)
        self.assertIn("Eventos nuevos: ninguno", digest.render(PID))
        self.assertNotIn("desde", lookout_state.read_json(digest.cursor_path(PID)))

    def test_resumen_after_a_waiter_wake_still_shows_what_woke_it(self):
        # a supervisor that answers the task notification with `lookout resumen` instead of reading the waiter's
        # output must still see the event: the waiter's marking is undone once for `resumen`, never twice
        self.agent("s-a", "uno")
        lookout_state.append_event(PID, {"event": "ask", "session_id": "s-a", "nombre": "uno", "ts": time.time(),
                                         "pregunta": "¿A o B?"})
        self.assertEqual(self.run_lk("espera", PID, "--timeout", "5").returncode, 0)
        r = self.run_lk("resumen", PID)
        self.assertIn("Eventos nuevos (1", r.stdout)
        self.assertIn("Eventos nuevos: ninguno", self.run_lk("resumen", PID).stdout)
        self.assertEqual(self.run_lk("espera", PID, "--timeout", "1").returncode, 2)


class ReportedTurnTest(Base):
    def test_an_end_of_turn_after_its_report_does_not_wake_the_waiter(self):
        import on_state
        addr = "uds:/tmp/sup.sock"
        tp = os.path.join(self.tmp.name, "ag.jsonl")
        with open(tp, "w") as fh:
            for ev in ({"type": "user", "message": {"content": "turno viejo"}},
                       {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "SendMessage",
                                                                      "input": {"to": addr, "message": "viejo"}}]}},
                       {"type": "user", "message": {"content": "Añade una línea"}},
                       {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {}}]}},
                       {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}):
                fh.write(json.dumps(ev) + "\n")
        self.assertFalse(on_state.reported_this_turn(tp, addr))     # its only report was in an older turn
        with open(tp, "a") as fh:
            fh.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "u1", "name": "SendMessage",
                                                                               "input": {"to": addr, "message": "¿A o B?"}}]}}) + "\n")
        self.assertFalse(on_state.reported_this_turn(tp, addr))     # sent, but no result yet: still wakes
        with open(tp, "a") as fh:
            fh.write(json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "u1",
                                                                          "is_error": True, "content": "Error: no session"}]}}) + "\n")
        self.assertFalse(on_state.reported_this_turn(tp, addr))     # a failed report must still wake (adversary F4)
        with open(tp, "a") as fh:
            fh.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "u2", "name": "SendMessage",
                                                                               "input": {"to": addr, "message": "hecho"}}]}}) + "\n")
            fh.write(json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "u2",
                                                                          "content": "“hecho” → uds:/tmp/sup.sock"}]}}) + "\n")
        self.assertTrue(on_state.reported_this_turn(tp, addr))
        self.assertFalse(on_state.reported_this_turn(tp, "uds:/tmp/otro.sock"))
        self.assertFalse(on_state.reported_this_turn("/no/existe", addr))
        ev, _l, _o = on_state.build({"hook_event_name": "Stop", "session_id": "s1", "transcript_path": tp,
                                     "last_assistant_message": "hecho"}, {"nombre": "uno", "address": addr})
        self.assertEqual((ev["event"], ev.get("reporto")), ("idle", True))
        # the waiter skips it and wakes on the next unreported one
        lookout_state.append_event(PID, ev)
        lookout_state.append_event(PID, {"event": "idle", "session_id": "s2", "nombre": "dos"})
        out = subprocess.run([sys.executable, os.path.join(BIN, "wait_event.py"), lookout_state.events_path(PID),
                              "--offset", "0", "--types", digest.WAKE_TYPES, "--timeout", "5"],
                             capture_output=True, text=True, env=dict(os.environ))
        self.assertIn("dos", out.stdout)
        self.assertNotIn("uno", out.stdout)


class EnviaLogTest(Base):
    def test_an_answer_typed_by_envia_is_logged_for_the_relief(self):
        from importlib.machinery import SourceFileLoader
        import argparse
        lk = SourceFileLoader("lookout_cli", LK).load_module()
        self.agent("s1", "uno")
        old = lk.deliver.deliver
        lk.deliver.deliver = lambda pid, e, clave, texto, confirmar: (0, "entregado")
        try:
            lk.cmd_envia(argparse.Namespace(proyecto=PID, agente="uno", tarea=False, clave="r1",
                                            texto="Opción A: cursiva.", confirmar=1))
            lk.cmd_envia(argparse.Namespace(proyecto=PID, agente="uno", tarea=True, clave=None, texto=None, confirmar=1))
        finally:
            lk.deliver.deliver = old
        log = supervisor_md.read_log(PID)
        self.assertEqual([(x["to"], x["texto"]) for x in log], [("uno", "Opción A: cursiva.")])  # the task trigger is not an answer
        self.assertIn("→ uno: Opción A: cursiva.", open(supervisor_md.path(PID)).read())


class SupervisorMdTest(Base):
    def test_sections_decisions_answers_and_como_retomar(self):
        self.agent("s1", "uno", tarea="p-1", tarea_estado="trabajando")
        self.agent("s0", "viejo~s0", tarea="p-1", tarea_estado="relevada")
        d1 = decisiones.abre(PID, "¿Borro docs/viejo.md?", ["uno"], notificar=False)
        decisiones.cierra(PID, d1["id"], "sí, bórralo", True)
        decisiones.abre(PID, "¿Borro docs/otro.md?", ["dos"], notificar=False)
        supervisor_md.log(PID, {"tipo": "respuesta", "to": "uno", "texto": "Usa la opción B: es reversible."})
        supervisor_md.log(PID, {"tipo": "usuario", "answers": {"¿Borro docs/viejo.md?": "Sí"}})
        md = open(supervisor_md.write(PID)).read()
        for head in ("## Proyecto", "## Candado", "## Agentes y tareas", "## Decisiones del usuario — tomadas",
                     "## Decisiones del usuario — pendientes", "## Respuestas del supervisor a los agentes",
                     "## Contadores", "## Como retomar"):
            self.assertIn(head, md)
        self.assertIn("d1 (", md)
        self.assertIn("SÍ: sí, bórralo", md)
        self.assertIn("→ uno: Usa la opción B", md)
        self.assertNotIn("viejo~s0", md)                       # relieved sessions are history, not agents
        block = supervisor_md.retomar_block(PID)
        for word in ("Retomamos:", "Lee ", "Proximo paso:", "No repitas:", "Terminas cuando:", "dime en 3 lineas"):
            self.assertIn(word, block)
        self.assertIn("pendientes: d2.", block)                 # pending decisions travel in the paste itself
        # under ~700 characters with real paths (learning 10); the temp state dir of a test can be much longer
        short = block.replace(self.tmp.name, "/tmp/x")   # every path of the test lives under its temp dir
        self.assertLess(len(short), 700)
        self.assertIn(supervisor_md.path(PID), block)

    def test_digest_rewrites_supervisor_md(self):
        self.agent("s1", "uno")
        digest.render(PID)
        self.assertTrue(os.path.exists(supervisor_md.path(PID)))


class SupervisorHooksTest(Base):
    def payload(self, **kw):
        return dict({"session_id": SUP, "cwd": "/x"}, **kw)

    def test_only_a_supervisor_session_is_logged(self):
        on_supervisor.handle(self.payload(hook_event_name="PostToolUse", tool_name="SendMessage",
                                          tool_input={"to": "uno", "message": "sigue"}))
        self.assertEqual(supervisor_md.read_log(PID), [])     # no supervisor marker yet
        supervisor_md.mark_supervisor(SUP, PID)
        on_supervisor.handle(self.payload(hook_event_name="PostToolUse", tool_name="SendMessage",
                                          tool_input={"to": "uno", "message": "sigue con B"}))
        on_supervisor.handle(self.payload(hook_event_name="PostToolUse", tool_name="AskUserQuestion",
                                          tool_input={"questions": [{"question": "¿Borro?"}]},
                                          tool_response={"answers": {"¿Borro?": "Sí"}}))
        log = supervisor_md.read_log(PID)
        self.assertEqual([x["tipo"] for x in log], ["respuesta", "usuario"])
        self.assertEqual(log[0]["to"], "uno")
        self.assertEqual(log[1]["answers"], {"¿Borro?": "Sí"})
        self.assertIn("sigue con B", open(supervisor_md.path(PID)).read())

    def test_a_question_asked_and_never_answered_is_pending(self):
        supervisor_md.mark_supervisor(SUP, PID)
        q = {"questions": [{"question": "¿Apruebo que dos borre docs/viejo-dos.md?"}]}
        on_supervisor.handle(self.payload(hook_event_name="PreToolUse", tool_name="AskUserQuestion", tool_use_id="t1", tool_input=q))
        on_supervisor.handle(self.payload(hook_event_name="PreToolUse", tool_name="AskUserQuestion", tool_use_id="t2",
                                          tool_input={"questions": [{"question": "¿Lanzo el lote?"}]}))
        on_supervisor.handle(self.payload(hook_event_name="PostToolUse", tool_name="AskUserQuestion", tool_use_id="t2",
                                          tool_input={}, tool_response={"answers": {"¿Lanzo el lote?": "Sí"}}))
        md = open(supervisor_md.path(PID)).read()
        pend = md.split("## Decisiones del usuario — pendientes", 1)[1].split("##", 1)[0]
        self.assertIn("viejo-dos.md", pend)
        self.assertNotIn("Lanzo el lote", pend)
        self.assertIn("1 pregunta(s) sin respuesta", supervisor_md.retomar_block(PID))
        # the relief asks it again (new call) and the user answers: the old one is no longer pending
        on_supervisor.handle(self.payload(hook_event_name="PostToolUse", tool_name="AskUserQuestion", tool_use_id="t3",
                                          tool_input={}, tool_response={"answers": {"¿Apruebo que dos borre docs/viejo-dos.md?": "Sí"}}))
        self.assertEqual(supervisor_md.unanswered(supervisor_md.read_log(PID)), [])

    def test_guard_routes_the_supervisors_ask_without_denying_it(self):
        gate = os.path.join(HOOKS, "guard.sh")
        env = dict(os.environ, LOOKOUT_STATE_DIR=self.state)
        supervisor_md.mark_supervisor(SUP, PID)
        ev = {"session_id": SUP, "hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion", "tool_use_id": "t9",
              "tool_input": {"questions": [{"question": "¿Borro?"}]}}
        r = subprocess.run(["sh", gate, "on_ask.py"], input=json.dumps(ev), capture_output=True, text=True, env=env)
        self.assertEqual((r.returncode, r.stdout), (0, ""))           # no deny: the question reaches the user
        self.assertEqual(supervisor_md.read_log(PID)[-1]["tipo"], "pregunta")
        r = subprocess.run(["sh", gate, "on_state.py"], input=json.dumps(dict(ev, hook_event_name="Stop")),
                           capture_output=True, text=True, env=env)
        self.assertEqual(len(supervisor_md.read_log(PID)), 1)          # only the ask is routed
        # with an executor marker too, the supervisor's question is still never denied (adversary F4)
        lookout_state.write_marker(SUP, {"project_id": PID, "nombre": "x", "address": "uds:/tmp/o.sock"})
        r = subprocess.run(["sh", gate, "on_ask.py"], input=json.dumps(ev), capture_output=True, text=True, env=env)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_a_supervisor_that_is_also_an_executor_keeps_its_state_events(self):
        # Fase 9 E11 (adversary of 0.8.1, round 1): its StopFailure went to on_supervisor only and never to on_state
        gate = os.path.join(HOOKS, "guard.sh")
        env = dict(os.environ, LOOKOUT_STATE_DIR=self.state, HERDR_PANE_ID="")
        supervisor_md.mark_supervisor(SUP, PID)
        ev = {"session_id": SUP, "hook_event_name": "StopFailure", "error": "rate_limit", "error_details": "429"}
        subprocess.run(["sh", gate, "on_state.py"], input=json.dumps(ev), capture_output=True, text=True, env=env)
        self.assertEqual(lookout_state.read_events(PID, 0)[0], [])       # supervisor only: no executor event
        lookout_state.write_marker(SUP, {"project_id": PID, "nombre": "x", "address": "uds:/tmp/o.sock"})
        subprocess.run(["sh", gate, "on_state.py"], input=json.dumps(ev), capture_output=True, text=True, env=env)
        evs = lookout_state.read_events(PID, 0)[0]
        self.assertEqual([e.get("hook") for e in evs], ["StopFailure"])

    def test_session_start_after_compact_prints_como_retomar(self):
        supervisor_md.mark_supervisor(SUP, PID)
        out = on_supervisor.handle(self.payload(hook_event_name="SessionStart", source="compact"))
        self.assertIn("Retomamos:", out)
        self.assertIn(supervisor_md.path(PID), out)

    def test_guard_sup_lets_only_the_supervisor_through(self):
        gate = os.path.join(HOOKS, "guard-sup.sh")
        env = dict(os.environ, LOOKOUT_STATE_DIR=self.state)
        lookout_state.write_marker("s-exec", {"project_id": PID, "nombre": "uno"})  # an executor's marker
        ev = {"session_id": "s-exec", "hook_event_name": "PreCompact", "trigger": "auto"}
        r = subprocess.run(["sh", gate, "on_supervisor.py"], input=json.dumps(ev), capture_output=True, text=True, env=env)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertFalse(os.path.exists(supervisor_md.path(PID)))
        supervisor_md.mark_supervisor(SUP, PID)
        ev["session_id"] = SUP
        pre = os.path.join(HOOKS, "on-precompact.sh")
        r = subprocess.run(["sh", pre], input=json.dumps(ev), capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(supervisor_md.path(PID)))
        self.assertEqual(supervisor_md.read_log(PID)[-1]["tipo"], "precompact")

    def test_hooks_json_wires_the_supervisor_hooks(self):
        h = json.load(open(os.path.join(HOOKS, "hooks.json")))["hooks"]
        self.assertIn("on-precompact.sh", json.dumps(h["PreCompact"]))
        self.assertTrue(any(e.get("matcher") == "compact" and "guard-sup.sh" in json.dumps(e) for e in h["SessionStart"]))
        self.assertTrue(any("SendMessage" in (e.get("matcher") or "") and "guard-sup.sh" in json.dumps(e)
                            for e in h["PostToolUse"]))


class DecisionAlreadyTakenTest(Base):
    def test_a_decided_question_is_not_opened_again_without_nueva(self):
        d = decisiones.abre(PID, "¿Borro docs/viejo.md de uno?", ["uno"], notificar=False)
        decisiones.cierra(PID, d["id"], "sí", True)
        r = self.run_lk("decision", PID, "--abre", "¿Puede uno borrar docs/viejo.md?", "--agentes", "uno")
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("NO ABIERTA", r.stdout)
        self.assertIn("d1", r.stdout)
        self.assertEqual(len(decisiones.abiertas(PID)), 0)
        r = self.run_lk("decision", PID, "--abre", "¿Push de uno?", "--agentes", "uno", "--nueva")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(decisiones.abiertas(PID)), 1)
        r = self.run_lk("decision", PID, "--abre", "¿Push de dos?", "--agentes", "dos")
        self.assertEqual(r.returncode, 0)


class TrustDialogTest(Base):
    def test_a_path_wrapped_by_a_narrow_pane_is_still_recognised(self):
        import lote
        screen = ("\n Accessing workspace:\n\n /private/tmp/b/repo-prueba-w\n t-crear-uno-con-2-li-aad7ab\n\n"
                  " Quick safety check\n ❯ No, exit\n   Yes, I trust this folder\n")
        calls = []
        old = lote.herdr_cli.run
        lote.herdr_cli.run = lambda args, timeout=None: (calls.append(args) or (0, screen, ""))
        try:
            self.assertEqual(lote.trust_dialog("w1:p1", "/private/tmp/b/repo-prueba-wt-crear-uno-con-2-li-aad7ab"), "aceptado")
            self.assertTrue(lote.trust_dialog("w1:p1", "/private/tmp/b/otro").startswith("otra-ruta:"))
        finally:
            lote.herdr_cli.run = old
        self.assertEqual(sum(1 for c in calls if "send-keys" in c), 1)   # accepted only for its own worktree


class RetomarTest(Base):
    def test_retomar_prints_the_block_and_writes_the_file(self):
        self.agent("s1", "uno")
        r = self.run_lk("retomar", PID)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Retomamos:", r.stdout)
        self.assertTrue(os.path.exists(supervisor_md.path(PID)))


if __name__ == "__main__":
    unittest.main()

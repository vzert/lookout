"""0.13.11 (p-fce98427a8): while the supervisor's modal is open, a vigía keeps the alta and the sweep going.

3-tier-memory, 2026-10-16: the supervisor launched its waiter before a modal, as SKILL.md said (0.13.3); the waiter woke
at once on 11 events that had arrived during the turn and exited; with the modal open nobody relaunched it, and the
project went 65 min with no alta and no sweep. The supervisor's own PreToolUse[AskUserQuestion] hook now starts a
vigía that runs the waiter's checker pass while no waiter of its own is alive, and stops when the modal ends.
Run: python3 -m unittest tests.test_lookout_01311
"""
import fcntl
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
STUB = os.path.join(ROOT, "tests", "fixtures", "herdr_stub.py")
sys.path.insert(0, BIN)

import digest  # noqa: E402
import lookout_state  # noqa: E402
import registry  # noqa: E402
import supervisor_md  # noqa: E402

PID = "p01311"
SUP = "s-sup-01311"


def dead_pid():
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


class VigiaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.state = os.path.join(t, "state")
        self.conf = os.path.join(t, "herdr.json")
        self.calls = os.path.join(t, "calls.log")
        with open(self.conf, "w") as fh:
            json.dump({"agent_list": []}, fh)
        self.saved = os.environ.get("LOOKOUT_STATE_DIR")
        os.environ["LOOKOUT_STATE_DIR"] = self.state
        lookout_state.write_json(os.path.join(lookout_state.project_dir(PID), "lock.json"), {
            "project_id": PID, "common_dir": os.path.join(t, "repo", ".git"), "roots": [os.path.join(t, "repo")],
            "supervisor": {"session_id": SUP, "pid": os.getpid(), "address": "uds:/tmp/sup.sock", "nombre": "sup"}})
        supervisor_md.mark_supervisor(SUP, PID)
        self.claude_pid = os.getpid()
        self.held = []

    def tearDown(self):
        for fd in self.held:
            os.close(fd)
        self.hook("guard.sh", "on_state.py", {"hook_event_name": "UserPromptSubmit", "prompt": "fin"})
        self.wait_for(lambda: not self.vigia_alive(), 10)
        if self.saved is None:
            os.environ.pop("LOOKOUT_STATE_DIR", None)
        else:
            os.environ["LOOKOUT_STATE_DIR"] = self.saved
        self.tmp.cleanup()

    def env(self):
        return dict(os.environ, LOOKOUT_STATE_DIR=self.state, HERDR_BIN_PATH=STUB, HERDR_STUB_CONF=self.conf,
                    HERDR_STUB_LOG=self.calls, CLAUDE_PID=str(self.claude_pid), LOOKOUT_REVISA_CADA="0.3",
                    LOOKOUT_VIGIA_CADA="0.2", LOOKOUT_WATCH_EVERY="0.3")

    def hook(self, script, handler, ev, sid=SUP):
        # capture_output + timeout, as Claude Code waits for the hook: a child holding the hook's stdout open would hang it
        r = subprocess.run(["sh", os.path.join(HOOKS, script), handler], input=json.dumps(dict({"session_id": sid}, **ev)),
                           capture_output=True, text=True, env=self.env(), timeout=8)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def ask(self, tuid="tu-1", sid=SUP):
        q = {"questions": [{"question": "¿Sigo? (d1)", "header": "h", "multiSelect": False,
                            "options": [{"label": "A", "description": "a"}, {"label": "B", "description": "b"}]}]}
        return self.hook("guard.sh", "on_ask.py", {"hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion",
                                                    "tool_use_id": tuid, "tool_input": q}, sid=sid)

    def answer(self, tuid="tu-1"):
        self.hook("guard-sup.sh", "on_supervisor.py", {
            "hook_event_name": "PostToolUse", "tool_name": "AskUserQuestion", "tool_use_id": tuid,
            "tool_input": {"questions": []}, "tool_response": {"answers": {"¿Sigo? (d1)": "A"}}})

    def vigia_alive(self):
        path = os.path.join(lookout_state.project_dir(PID), "vigia.pid")
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError:
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
        except OSError:
            return True
        finally:
            os.close(fd)

    def passes(self):
        """`agent list` calls: each discovery pass (alta.pasada) makes one."""
        try:
            with open(self.calls) as fh:
                return sum(1 for line in fh if json.loads(line)[:2] == ["agent", "list"])
        except OSError:
            return 0

    @staticmethod
    def wait_for(cond, timeout):
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.1)
        return cond()

    def hold_waiter(self):
        fd = os.open(digest.pidfile(PID), os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(fd, b"%d\n" % os.getpid())
        lookout_state.write_json(digest.pidfile(PID) + ".owner", {"claude_pid": self.claude_pid, "session_id": SUP})
        self.held.append(fd)
        return fd

    def test_a_modal_with_no_waiter_still_gets_the_alta_and_the_sweep(self):
        r = self.ask()
        self.assertEqual(r.stdout, "")                     # the question goes to the user as usual
        self.assertTrue(self.wait_for(self.vigia_alive, 5))
        self.assertTrue(self.wait_for(lambda: self.passes() >= 1, 5))
        self.assertTrue(os.path.exists(os.path.join(lookout_state.project_dir(PID), "descubre.json")))

    def test_the_vigia_stops_when_the_modal_is_answered(self):
        self.ask()
        self.assertTrue(self.wait_for(self.vigia_alive, 5))
        self.answer()
        self.assertTrue(self.wait_for(lambda: not self.vigia_alive(), 5))

    def test_the_vigia_stops_on_a_prompt_or_a_failed_modal(self):
        for ev in ({"hook_event_name": "UserPromptSubmit", "prompt": "hola"},
                   {"hook_event_name": "PostToolUseFailure", "tool_name": "AskUserQuestion", "tool_use_id": "tu-1"},
                   {"hook_event_name": "SessionStart", "source": "startup"},
                   {"hook_event_name": "Stop", "stop_hook_active": True}):
            self.ask()
            self.assertTrue(self.wait_for(self.vigia_alive, 5), ev)
            if ev["hook_event_name"] == "Stop":
                self.hook("guard-sup.sh", "on_supervisor.py", ev)
            else:
                self.hook("guard.sh", "on_state.py", ev)
            self.assertTrue(self.wait_for(lambda: not self.vigia_alive(), 5), ev)

    def test_a_live_waiter_does_the_pass_and_the_vigia_waits(self):
        self.hold_waiter()
        self.ask()
        self.assertTrue(self.wait_for(self.vigia_alive, 5))
        time.sleep(1.5)
        self.assertEqual(self.passes(), 0)                 # the waiter's own checker covers it
        os.close(self.held.pop())                          # the waiter woke on an old event and left
        self.assertTrue(self.wait_for(lambda: self.passes() >= 1, 5))

    def test_the_vigia_leaves_when_its_supervisor_is_gone(self):
        self.claude_pid = dead_pid()
        self.ask()
        self.assertTrue(self.wait_for(lambda: not self.vigia_alive(), 5))
        self.assertEqual(self.passes(), 0)

    def test_a_new_modal_replaces_the_vigia_of_the_old_one(self):
        self.ask("tu-1")
        self.assertTrue(self.wait_for(self.vigia_alive, 5))
        self.ask("tu-2")
        self.answer("tu-1")                                # a late answer of the old modal leaves the new one watched
        time.sleep(1.0)
        self.assertTrue(self.vigia_alive())
        self.answer("tu-2")
        self.assertTrue(self.wait_for(lambda: not self.vigia_alive(), 5))

    def test_an_executors_question_starts_no_vigia(self):
        ex = "s-ejecutor"
        lookout_state.write_json(os.path.join(self.state, "sessions", ex + ".json"), {"project_id": PID})
        self.ask(sid=ex)
        time.sleep(1.0)
        self.assertFalse(self.vigia_alive())


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_0130 as t130  # noqa: E402
import test_lookout_f4 as f4  # noqa: E402


class CasoMedidoTest(t130.AvisoTest):
    """The 3-tier-memory case, end to end through the real hook entries: events of the turn are pending, the waiter
    launched before the modal wakes on them at once and leaves; with the modal open a hand-launched agent must still
    join (alta) and a quiet agent's «Como retomar» must still be announced (sweep)."""

    def setUp(self):
        super().setUp()
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        lk = lookout_state.read_json(os.path.join(lookout_state.project_dir(f4.PID), "lock.json"))
        lk["common_dir"] = lookout_state.git_common_dir(self.repo)
        lookout_state.write_json(os.path.join(lookout_state.project_dir(f4.PID), "lock.json"), lk)
        supervisor_md.mark_supervisor(f4.SUP, f4.PID)
        self.conf = os.path.join(self.tmp.name, "herdr.json")
        self.calls = os.path.join(self.tmp.name, "calls.log")
        with open(self.conf, "w") as fh:
            json.dump({"agent_list": [
                {"agent_session": {"value": "s1"}, "agent_status": "idle", "pane_id": "w1:p1", "agent": "claude",
                 "cwd": "/x"},
                {"agent_session": {"value": "s-nuevo"}, "agent_status": "idle", "pane_id": "w1:p9", "agent": "claude",
                 "cwd": self.repo, "name": "9"}]}, fh)

    def tearDown(self):
        self.sh("guard.sh", "on_state.py", {"hook_event_name": "UserPromptSubmit", "prompt": "fin"})
        VigiaTest.wait_for(lambda: not os.path.exists(os.path.join(lookout_state.project_dir(f4.PID), "modal.json")), 5)
        time.sleep(0.5)
        super().tearDown()

    def env(self, **kw):
        return dict(os.environ, **dict(dict(LOOKOUT_STATE_DIR=self.state, HERDR_BIN_PATH=STUB, HERDR_STUB_CONF=self.conf,
                    HERDR_STUB_LOG=self.calls, CLAUDE_PID=str(os.getpid()), CLAUDE_CONFIG_DIR=self.tmp.name,
                    LOOKOUT_REVISA_CADA="0.3", LOOKOUT_VIGIA_CADA="0.2"), **kw))

    def sh(self, script, handler, ev):
        r = subprocess.run(["sh", os.path.join(HOOKS, script), handler], input=json.dumps(dict({"session_id": f4.SUP}, **ev)),
                           capture_output=True, text=True, env=self.env(), timeout=8)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def retomar_barrido(self):
        evs, _ = lookout_state.read_events(f4.PID, 0)
        return [e for e in evs if e.get("event") == "retomar" and e.get("hook") == "barrido" and e.get("session_id") == "s1"]

    def test_the_measured_case(self):
        now = time.time()
        self.agent("s1", "hook-para-checkpoint")
        self.transcript("s1", [t130.u_text("sigue", now - 60), t130.a_text(t130.MINUTOS, now - 30)])
        for i in range(11):  # events of the supervisor's turn, not digested yet
            lookout_state.append_event(f4.PID, {"event": "ask", "session_id": "s1", "ts": now - 20 + i})
        # the waiter launched before the modal (SKILL.md, 0.13.3): it wakes on those events and leaves
        code = ("import sys; sys.path.insert(0, %r); import digest, lookout_state, wait_event\n"
                "sys.exit(wait_event.wait(lookout_state.events_path(%r), digest.get_cursor(%r), digest.WAKE_TYPES, 30,"
                " digest.pidfile(%r), digest.cursor_path(%r), revisa=%r, linea=False))") % (BIN, f4.PID, f4.PID, f4.PID,
                                                                                         f4.PID, f4.PID)
        t0 = time.time()
        w = subprocess.run([sys.executable, "-c", code], env=self.env(LOOKOUT_REVISA_CADA="60"), capture_output=True,
                           text=True, timeout=20)
        self.assertEqual(w.returncode, 0, w.stderr)
        self.assertLess(time.time() - t0, 10)
        self.assertEqual(digest.waiter_alive(f4.PID), 0)
        self.assertNotIn("s-nuevo", registry.load(f4.PID)["agents"])
        self.assertEqual(self.retomar_barrido(), [])
        # the modal opens: nobody relaunches the waiter until the user answers
        q = {"questions": [{"question": "¿Relevo? (d1)", "header": "h", "multiSelect": False,
                            "options": [{"label": "A", "description": "a"}, {"label": "B", "description": "b"}]}]}
        self.sh("guard.sh", "on_ask.py", {"hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion",
                                           "tool_use_id": "tu-m", "tool_input": q})
        self.assertTrue(VigiaTest.wait_for(lambda: "s-nuevo" in registry.load(f4.PID)["agents"], 10))   # alta
        self.assertTrue(VigiaTest.wait_for(lambda: len(self.retomar_barrido()) == 1, 10))                  # sweep
        evs, _ = lookout_state.read_events(f4.PID, 0)
        self.assertEqual([e["session_id"] for e in evs if e.get("event") == "nuevo"], ["s-nuevo"])
        self.assertEqual(self.retomar_barrido()[0]["retomar"]["estado"], "vigente")


class MarcaTest(unittest.TestCase):
    def test_a_late_answer_never_removes_a_newer_modal(self):
        # adversary r1 (codex): cierra read the old mark, a new modal wrote its own, cierra unlinked the new one
        import threading
        import vigia
        with tempfile.TemporaryDirectory() as t:
            saved = os.environ.get("LOOKOUT_STATE_DIR")
            os.environ["LOOKOUT_STATE_DIR"] = t
            real_read = vigia.lookout_state.read_json
            leido, sigue = threading.Event(), threading.Event()

            def slow_read(path, default=None):
                out = real_read(path, default)
                if path == vigia.modal_path(PID) and threading.current_thread().name == "tarde":
                    leido.set()
                    sigue.wait(2.0)
                return out
            try:
                lookout_state.write_json(vigia.modal_path(PID), {"session_id": SUP, "tool_use_id": "viejo"})
                vigia.lookout_state.read_json = slow_read
                th = threading.Thread(target=vigia.cierra, args=(PID, "viejo"), name="tarde")
                th.start()
                self.assertTrue(leido.wait(3))
                # the new modal's hook, in its own process, while the late answer sits between its read and its unlink
                nuevo = subprocess.Popen([sys.executable, "-c", (
                    "import sys; sys.path.insert(0, %r); import vigia, lookout_state\n"
                    "with vigia._marca(%r): lookout_state.write_json(vigia.modal_path(%r), "
                    "{'session_id': %r, 'tool_use_id': 'nuevo'})") % (BIN, PID, PID, SUP)],
                    env=dict(os.environ, LOOKOUT_STATE_DIR=t))
                time.sleep(0.5)
                sigue.set()
                th.join(5)
                self.assertEqual(nuevo.wait(5), 0)
                self.assertEqual((real_read(vigia.modal_path(PID)) or {}).get("tool_use_id"), "nuevo")
            finally:
                sigue.set()
                vigia.lookout_state.read_json = real_read
                if saved is None:
                    os.environ.pop("LOOKOUT_STATE_DIR", None)
                else:
                    os.environ["LOOKOUT_STATE_DIR"] = saved


class PassLockTest(unittest.TestCase):
    def test_one_checker_pass_at_a_time_across_processes(self):
        with tempfile.TemporaryDirectory() as t:
            saved = os.environ.get("LOOKOUT_STATE_DIR")
            os.environ["LOOKOUT_STATE_DIR"] = t
            try:
                import vigia
                ran = []
                with vigia.pasada_exclusiva(PID) as mia:
                    self.assertTrue(mia)
                    out = subprocess.run([sys.executable, "-c", (
                        "import sys; sys.path.insert(0, %r); import vigia\n"
                        "with vigia.pasada_exclusiva(%r) as mia: print(mia)") % (BIN, PID)],
                        capture_output=True, text=True, env=dict(os.environ, LOOKOUT_STATE_DIR=t), timeout=5)
                    ran.append(out.stdout.strip())
                self.assertEqual(ran, ["False"])           # the other process skips its pass, it does not queue
            finally:
                if saved is None:
                    os.environ.pop("LOOKOUT_STATE_DIR", None)
                else:
                    os.environ["LOOKOUT_STATE_DIR"] = saved


if __name__ == "__main__":
    unittest.main()

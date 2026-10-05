"""Unit tests for the lookout plugin scripts (phase 1). Run: python3 -m unittest tests/test_lookout.py

Every test points LOOKOUT_STATE_DIR at a temp folder and replaces herdr with a stub that
records its arguments, so nothing touches ~/.local/state/lookout or a real herdr session.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "plugins", "lookout", "bin")
GUARD = os.path.join(ROOT, "plugins", "lookout", "hooks", "guard.sh")
FIX = os.path.join(ROOT, "tests", "fixtures")
sys.path.insert(0, BIN)

import digest  # noqa: E402
import discover  # noqa: E402
import inputbox  # noqa: E402
import lock  # noqa: E402
import lookout_state  # noqa: E402
import on_state  # noqa: E402
import registry  # noqa: E402
import wait_event  # noqa: E402


def argparse_ns(**kw):
    import argparse
    return argparse.Namespace(**kw)


class StateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "state")
        self.stub_log = os.path.join(self.tmp.name, "herdr.log")
        stub = os.path.join(self.tmp.name, "herdr")
        with open(stub, "w") as fh:
            fh.write('#!/bin/sh\necho "$@" >> "%s"\necho \'{"result":{}}\'\n' % self.stub_log)
        os.chmod(stub, 0o755)
        self.env = {"LOOKOUT_STATE_DIR": self.state, "HERDR_BIN_PATH": stub}
        self.old = {k: os.environ.get(k) for k in list(self.env) + ["HERDR_PANE_ID"]}
        os.environ.update(self.env)
        os.environ["HERDR_PANE_ID"] = "w9:p1"
        import herdr_cli
        herdr_cli.HERDR = stub

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def herdr_calls(self):
        try:
            with open(self.stub_log) as fh:
                return fh.read()
        except OSError:
            return ""


class InputBoxTest(unittest.TestCase):
    def test_real_captures(self):
        for name in ("caja-a1.ansi", "caja-a2.ansi", "caja-a3.ansi", "caja-a4.ansi"):
            with open(os.path.join(FIX, name), encoding="utf-8") as fh:
                self.assertEqual(inputbox.classify(fh.read()), "vacia", name)
        with open(os.path.join(FIX, "caja-borrador.ansi"), encoding="utf-8") as fh:
            self.assertEqual(inputbox.classify(fh.read()), "borrador")

    def test_real_suggestion_capture(self):
        # Claude Code's own placeholder 'Try "…"' in a fresh session, captured from coord-test
        with open(os.path.join(FIX, "caja-sugerencia.ansi"), encoding="utf-8") as fh:
            self.assertEqual(inputbox.classify(fh.read()), "sugerencia")

    def test_dim_suggestion(self):
        text = "\x1b[38;2;153;153;153m❯\x1b[0m \x1b[2mhaz commit de los cambios\x1b[0m\n────\n"
        self.assertEqual(inputbox.classify(text), "sugerencia")

    def test_dim_then_normal_is_draft(self):
        text = "❯ \x1b[2msuger\x1b[22mencia escrita\n────\n"
        self.assertEqual(inputbox.classify(text), "borrador")

    def test_truecolor_2_is_not_dim(self):
        # 38;2;R;G;B contains a literal "2" that must not switch dim on
        text = "❯ \x1b[38;2;255;255;255mtexto normal\x1b[0m\n────\n"
        self.assertEqual(inputbox.classify(text), "borrador")

    def test_no_prompt(self):
        self.assertEqual(inputbox.classify("nada aquí"), "desconocida")


class OnStateTest(StateCase):
    marker = {"project_id": "pA", "nombre": "e1", "display": "e1 (lookout)"}

    def test_stop_idle_and_background(self):
        ev, label, _ = on_state.build({"hook_event_name": "Stop", "session_id": "s1",
                                       "last_assistant_message": "hecho\n[ADVERSARY-VERDICT: hold x]",
                                       "background_tasks": []}, self.marker)
        self.assertEqual((ev["event"], label), ("idle", "listo"))
        self.assertEqual(ev["marcadores"], ["[ADVERSARY-VERDICT: hold x]"])
        ev, label, _ = on_state.build({"hook_event_name": "Stop", "session_id": "s1",
                                       "background_tasks": [{"type": "shell", "status": "running",
                                                             "command": "sleep 40"}]}, self.marker)
        self.assertEqual((ev["event"], label), ("bg_wait", "fondo"))
        self.assertEqual(ev["tareas"][0]["command"], "sleep 40")

    def test_permission_and_prompt(self):
        ev, label, _ = on_state.build({"hook_event_name": "PermissionRequest", "tool_name": "Bash",
                                       "tool_input": {"command": "rm x"}}, self.marker)
        self.assertEqual((ev["event"], label, ev["detalle"]), ("blocked", "permiso", "rm x"))
        ev, label, _ = on_state.build({"hook_event_name": "UserPromptSubmit", "prompt": "hola"}, self.marker)
        self.assertEqual((ev["event"], label), ("working", "trabajando"))

    def test_crossrepo(self):
        a = os.path.join(self.tmp.name, "repoA")
        b = os.path.join(self.tmp.name, "repoB")
        os.makedirs(a)
        os.makedirs(b)
        for pid, root in (("pA", a), ("pB", b)):
            lookout_state.write_json(os.path.join(lookout_state.project_dir(pid), "lock.json"),
                                     {"roots": [os.path.realpath(root)]})
        marker_b = dict(self.marker, project_id="pB")
        ev, _, others = on_state.build({"hook_event_name": "PostToolUse", "tool_name": "Edit",
                                        "tool_input": {"file_path": os.path.join(a, "x.txt")}}, marker_b)
        self.assertEqual(ev["event"], "crossrepo")
        self.assertEqual(others, ["pA"])
        ev, _, _ = on_state.build({"hook_event_name": "PostToolUse", "tool_name": "Edit",
                                   "tool_input": {"file_path": os.path.join(b, "y.txt")}}, marker_b)
        self.assertIsNone(ev)

    def test_main_writes_both_projects_and_no_stdout(self):
        a = os.path.join(self.tmp.name, "repoA")
        os.makedirs(a)
        lookout_state.write_json(os.path.join(lookout_state.project_dir("pA"), "lock.json"),
                                 {"roots": [os.path.realpath(a)]})
        lookout_state.write_marker("sB", {"project_id": "pB", "nombre": "e3"})
        payload = json.dumps({"session_id": "sB", "hook_event_name": "PostToolUse", "tool_name": "Edit",
                              "tool_input": {"file_path": os.path.join(a, "z.txt")}})
        out = subprocess.run(["sh", GUARD, "on_state.py"], input=payload, capture_output=True, text=True,
                             env=dict(os.environ))
        self.assertEqual((out.returncode, out.stdout), (0, ""))
        for pid in ("pA", "pB"):
            evs, _ = lookout_state.read_events(pid)
            self.assertEqual([e["event"] for e in evs], ["crossrepo"], pid)


class GuardAndAskTest(StateCase):
    def run_guard(self, handler, payload):
        return subprocess.run(["sh", GUARD, handler], input=json.dumps(payload), capture_output=True,
                              text=True, env=dict(os.environ))

    def test_unsupervised_is_silent(self):
        out = self.run_guard("on_ask.py", {"session_id": "nadie", "tool_input": {"questions": []}})
        self.assertEqual((out.returncode, out.stdout), (0, ""))
        self.assertFalse(os.path.exists(os.path.join(self.state, "projects")))

    def test_path_traversal_session_is_ignored(self):
        out = self.run_guard("on_ask.py", {"session_id": "../x", "tool_input": {}})
        self.assertEqual((out.returncode, out.stdout), (0, ""))

    def test_nested_supervised_id_does_not_wake_python(self):
        # Real payload shape (captured 2026-10-02): compact JSON, top-level session_id first. A
        # supervised id nested later (e.g. in tool_input) must not start python.
        lookout_state.write_marker("s-sup", {"project_id": "pA"})
        payload = json.dumps({"session_id": "s-libre", "tool_input": {"session_id": "s-sup"}},
                             separators=(",", ":"))
        out = subprocess.run(["sh", "-x", GUARD, "on_ask.py"], input=payload, capture_output=True,
                             text=True, env=dict(os.environ))
        self.assertEqual((out.returncode, out.stdout), (0, ""))
        self.assertNotIn("python3", out.stderr)  # sh -x trace: python never started

    def test_unanchored_order_falls_back_and_handler_rechecks(self):
        # If Claude Code ever sent the nested id first, guard falls back to the first occurrence and
        # starts python; on_ask re-reads the real top-level id and stays silent (cost, not misrouting).
        lookout_state.write_marker("s-sup", {"project_id": "pA"})
        payload = '{"tool_input":{"session_id":"s-sup"},"session_id":"s-libre"}'
        out = subprocess.run(["sh", GUARD, "on_ask.py"], input=payload, capture_output=True,
                             text=True, env=dict(os.environ))
        self.assertEqual((out.returncode, out.stdout), (0, ""))
        self.assertFalse(os.path.exists(lookout_state.events_path("pA")))

    def test_supervised_ask_is_denied_and_logged(self):
        lookout_state.write_marker("s1", {"project_id": "pA", "supervisor": "sup", "address": "uds:/tmp/x.sock",
                                          "nombre": "e1"})
        out = self.run_guard("on_ask.py", {"session_id": "s1", "cwd": "/r", "tool_input": {"questions": [
            {"question": "¿A o B?", "options": [{"label": "A"}, {"label": "B"}]}]}})
        data = json.loads(out.stdout)["hookSpecificOutput"]
        self.assertEqual(data["permissionDecision"], "deny")
        self.assertIn('to="uds:/tmp/x.sock"', data["permissionDecisionReason"])
        self.assertNotIn("sup", data["permissionDecisionReason"].replace("supervisada", ""))
        evs, _ = lookout_state.read_events("pA")
        self.assertEqual(evs[0]["questions"], [{"question": "¿A o B?", "options": ["A", "B"]}])
        self.assertIn("report-metadata w9:p1", self.herdr_calls())


class LockTest(StateCase):
    def test_acquire_refuse_takeover(self):
        me = {"session_id": "s-me", "pid": os.getpid(), "address": "", "nombre": "sup1"}
        self.assertEqual(lock.acquire("pA", "/c", ["/r"], me)[0], "nuevo")
        self.assertEqual(lock.acquire("pA", "/c", ["/r"], me)[0], "propio")
        other = {"session_id": "s-other", "pid": os.getppid(), "address": "", "nombre": "sup2"}
        status, data = lock.acquire("pA", "/c", ["/r"], other)
        self.assertEqual(status, "ocupado")
        self.assertEqual(data["supervisor"]["nombre"], "sup1")
        # same Claude process with a new session (/clear): its own relief, not a second supervisor (Fase 4)
        cleared = {"session_id": "s-cleared", "pid": os.getpid(), "address": "", "nombre": "sup1"}
        status, data = lock.acquire("pA", "/c", ["/r"], cleared)
        self.assertEqual(status, "relevo-mismo-proceso")
        self.assertEqual((data["supervisor"]["session_id"], data["anterior"]["session_id"]), ("s-cleared", "s-me"))
        dead = subprocess.Popen(["true"])
        dead.wait()
        lookout_state.write_json(os.path.join(lookout_state.project_dir("pA"), "lock.json"),
                                 {"supervisor": {"session_id": "s-dead", "pid": dead.pid, "nombre": "viejo"}})
        status, data = lock.acquire("pA", "/c", ["/r"], other)
        self.assertEqual(status, "tomado-de-muerto")
        self.assertEqual(data["anterior"]["nombre"], "viejo")

    def test_owner_with_missing_socket_is_dead(self):
        self.assertFalse(lock.owner_alive({"pid": os.getpid(), "address": "uds:/nonexistent/x.sock"}))


class DiscoverRegistryTest(StateCase):
    def test_filters_by_common_dir_and_self(self):
        agents = [
            {"pane_id": "w9:p1", "cwd": "/repo", "agent": "claude", "agent_session": {"value": "self"}},
            {"pane_id": "w9:p2", "cwd": "/repo", "agent": "claude", "agent_session": {"value": "s2"},
             "terminal_title_stripped": "Arreglar login"},
            {"pane_id": "w9:p3", "cwd": "/repo-wt", "agent": "claude", "agent_session": {"value": "s3"}},
            {"pane_id": "w9:p4", "cwd": "/otro", "agent": "claude", "agent_session": {"value": "s4"}},
        ]
        common = {"/repo": "/repo/.git", "/repo-wt": "/repo/.git", "/otro": "/otro/.git"}
        found = discover.discover("/repo/.git", agents, common.get)
        self.assertEqual([f["session_id"] for f in found], ["s2", "s3"])

    def test_names_are_unique_and_markers_written(self):
        agents = [{"session_id": "s2", "kind": "claude", "cwd": "/nope", "title": "Arreglar login"},
                  {"session_id": "s3", "kind": "claude", "cwd": "/nope", "title": "Claude Code"},
                  {"session_id": "s4", "kind": "claude", "cwd": "/nope", "title": ""}]
        reg = registry.register("pA", {"nombre": "sup", "address": "uds:/x"}, agents)
        names = [e["nombre"] for e in reg["agents"].values()]
        self.assertEqual(names, ["nope-arreglar-login", "nope", "nope-2"])
        self.assertEqual(lookout_state.read_marker("s3")["address"], "uds:/x")
        again = registry.register("pA", {"nombre": "sup", "address": "uds:/x"}, agents)
        self.assertEqual([e["nombre"] for e in again["agents"].values()], names)


class NotaTest(StateCase):
    def test_nota_is_one_short_line(self):
        # herdr delivers a long prompt as a paste and Claude Code wraps it in <pasted_content>:
        # 574 chars arrived plain, ~1000 arrived wrapped, one line or many (coord-test, 2026-10-02;
        # tests/escenarios/evidencia/corrida1/notas-recibidas-por-ejecutores.txt). Keep a margin.
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader("lookout_cli", os.path.join(BIN, "lookout"))
        spec = importlib.util.spec_from_loader("lookout_cli", loader)
        cli = importlib.util.module_from_spec(spec)
        loader.exec_module(cli)
        lookout_state.write_json(os.path.join(lookout_state.project_dir("pA"), "lock.json"), {"supervisor": {
            "nombre": "supervisor-un-repo-con-nombre-largo", "address": "uds:/tmp/cc-socks/99999.sock"}})
        text = cli.render_nota("pA", {"nombre": "un-repo-con-nombre-largo-arreglar-login-2"})
        self.assertNotIn("\n", text)
        self.assertIn('to="uds:/tmp/cc-socks/99999.sock"', text)
        self.assertNotIn("supervisor-un-repo", text)  # no display name an executor could use as `to`
        self.assertLess(len(text), 700)


class DigestWaiterTest(StateCase):
    def test_cursor_marks_events_once(self):
        lookout_state.append_event("pA", {"event": "ask", "session_id": "s1", "nombre": "e1",
                                          "questions": [{"question": "¿A?", "options": ["A", "B"]}]})
        first = digest.render("pA")
        self.assertIn("¿A? [A | B]", first)
        self.assertIn("Waiter: no hay", first)
        self.assertIn("ninguno", digest.render("pA"))

    def test_waiter_starts_at_cursor_and_skips_handled(self):
        path = lookout_state.events_path("pA")
        lookout_state.append_event("pA", {"event": "idle", "nombre": "e1"})
        out = subprocess.run([sys.executable, os.path.join(BIN, "wait_event.py"), path, "--offset", "0",
                              "--types", digest.WAKE_TYPES, "--timeout", "5"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0)
        # one short line, not the event's JSON: it lands in the supervisor's context (Fase 4)
        self.assertIn("e1", out.stdout)
        self.assertIn("lookout resumen", out.stdout)
        self.assertEqual(len(out.stdout.splitlines()), 1)
        # an event already handled (cursor past it) does not wake; the next one does
        digest.render("pA")
        lookout_state.append_event("pA", {"event": "idle", "nombre": "viejo"})
        _, end = lookout_state.read_events("pA")
        digest.set_cursor("pA", end)
        proc = subprocess.Popen([sys.executable, os.path.join(BIN, "wait_event.py"), path, "--offset", "0",
                                 "--types", digest.WAKE_TYPES, "--timeout", "5", "--cursor",
                                 digest.cursor_path("pA"), "--pidfile", digest.pidfile("pA")],
                                stdout=subprocess.PIPE, text=True)
        t = threading.Timer(0.5, lambda: lookout_state.append_event("pA", {"event": "ask", "nombre": "nuevo"}))
        t.start()
        out, _ = proc.communicate(timeout=10)
        self.assertIn("nuevo", out)
        self.assertEqual(digest.waiter_alive("pA"), 0)  # file may stay; the lock is what counts

    def test_concurrent_waiters_only_one_wins(self):
        path = lookout_state.events_path("pA")
        procs = [subprocess.Popen([sys.executable, os.path.join(BIN, "wait_event.py"), path, "--timeout", "3",
                                   "--pidfile", digest.pidfile("pA")], stdout=subprocess.PIPE, text=True)
                 for _ in range(6)]
        codes = [p.wait(timeout=10) for p in procs]
        for p in procs:
            p.stdout.close()
        self.assertEqual(codes.count(2), 1, codes)  # exactly one claimed and then timed out
        self.assertEqual(codes.count(3), 5, codes)  # the rest refused

    def test_stale_pidfile_with_concurrent_waiters(self):
        # a dead waiter left its pidfile behind; several new waiters start at once: exactly one wins
        dead = subprocess.Popen(["true"])
        dead.wait()
        os.makedirs(lookout_state.project_dir("pA"), exist_ok=True)
        with open(digest.pidfile("pA"), "w") as fh:
            fh.write(str(dead.pid))
        self.assertEqual(digest.waiter_alive("pA"), 0)
        path = lookout_state.events_path("pA")
        procs = [subprocess.Popen([sys.executable, os.path.join(BIN, "wait_event.py"), path, "--timeout", "3",
                                   "--pidfile", digest.pidfile("pA")], stdout=subprocess.PIPE, text=True)
                 for _ in range(6)]
        codes = [p.wait(timeout=10) for p in procs]
        for p in procs:
            p.stdout.close()
        self.assertEqual((codes.count(2), codes.count(3)), (1, 5), codes)

    def test_second_waiter_refuses(self):
        path = lookout_state.events_path("pA")
        first = subprocess.Popen([sys.executable, os.path.join(BIN, "wait_event.py"), path, "--timeout", "5",
                                  "--pidfile", digest.pidfile("pA")], stdout=subprocess.PIPE, text=True)
        for _ in range(50):
            if os.path.exists(digest.pidfile("pA")):
                break
            time.sleep(0.05)
        second = subprocess.run([sys.executable, os.path.join(BIN, "wait_event.py"), path, "--timeout", "5",
                                 "--pidfile", digest.pidfile("pA")], capture_output=True, text=True)
        self.assertEqual(second.returncode, 3)
        self.assertIn("ya vivo", second.stdout)
        self.assertTrue(digest.waiter_alive("pA"))
        first.terminate()
        first.communicate(timeout=5)
        self.assertFalse(digest.waiter_alive("pA"))


    def test_waiter_alive_never_yields_a_killable_nonpositive_pid(self):
        # adversary round 3: os.kill(-1 or 0, ...) signals every process of the user or the group.
        # A held pidfile whose text is empty, partial (no newline yet), zero or negative gives -1,
        # and `lookout suelta` kills nothing then.
        import fcntl
        import importlib.machinery
        import importlib.util
        from unittest import mock
        os.makedirs(lookout_state.project_dir("pA"), exist_ok=True)
        path = digest.pidfile("pA")
        loader = importlib.machinery.SourceFileLoader("lookout_cli2", os.path.join(BIN, "lookout"))
        cli = importlib.util.module_from_spec(importlib.util.spec_from_loader("lookout_cli2", loader))
        loader.exec_module(cli)
        cases = {"": -1, "0\n": -1, "-1\n": -1, "00\n": -1, "123": -1, "abc\n": -1, " 7\n": -1,
                 "4242\n": 4242}
        for text, expected in cases.items():
            with open(path, "w") as fh:
                fh.write(text)
            holder = subprocess.Popen([sys.executable, "-c",
                                       "import fcntl,os,sys,time;fd=os.open(sys.argv[1],os.O_RDWR);"
                                       "fcntl.flock(fd,fcntl.LOCK_EX);print('ok',flush=True);time.sleep(30)", path],
                                      stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(holder.stdout.readline().strip(), "ok")
                got = digest.waiter_alive("pA")
                self.assertEqual(got, expected, repr(text))
                self.assertTrue(got > 0 or got == -1, repr(text))
                with mock.patch.object(cli, "project", return_value=("pA", None)), \
                        mock.patch.object(cli.lock, "release", return_value=True), \
                        mock.patch.object(cli.lock, "me", return_value={"session_id": "s"}), \
                        mock.patch.object(cli.os, "kill") as kill:
                    self.assertEqual(cli.cmd_suelta(argparse_ns(proyecto="x")), 0)
                # Fase 4: a readable pid is signalled only if that process is a lookout waiter (pid reuse, adversary
                # F4); 4242 here is an invented pid, so nothing is killed in any case.
                kill.assert_not_called()
            finally:
                holder.kill()
                holder.wait()
        # nobody holds the flock: 0 whatever the file says, and nothing is killed
        with open(path, "w") as fh:
            fh.write("4242\n")
        self.assertEqual(digest.waiter_alive("pA"), 0)

    def test_real_waiter_writes_a_complete_pid_line(self):
        path = lookout_state.events_path("pA")
        proc = subprocess.Popen([sys.executable, os.path.join(BIN, "wait_event.py"), path, "--timeout", "5",
                                 "--pidfile", digest.pidfile("pA")], stdout=subprocess.PIPE, text=True)
        try:
            for _ in range(100):
                if digest.waiter_alive("pA") > 0:
                    break
                time.sleep(0.05)
            self.assertEqual(digest.waiter_alive("pA"), proc.pid)
        finally:
            proc.terminate()
            proc.communicate(timeout=5)
        self.assertEqual(digest.waiter_alive("pA"), 0)
        self.assertTrue(os.path.exists(digest.pidfile("pA")))  # never unlinked

if __name__ == "__main__":
    unittest.main()

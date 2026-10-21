"""0.13.18: the brake on killing processes by name. An agent cannot run a pkill/pgrep/killall that would hit other
agents, nor `kill -1`.

Live case (3-tier, 2026-10-17 22:42:47): a subagent of decisiones-pendientes-bloqueadas ran
`pkill -f "tools/run-tests.sh" -n`. macOS's pkill stops reading options at the first pattern, so `-n` was a second
pattern, and every process with "-n" in its command line got SIGTERM: the three reliefs lookout had started with
`claude --session-id … -n <nombre>` died at once, with three test suites. Now the PreToolUse[Bash] hook denies, for any
registered agent and in any mode: an option after the pattern of pkill/pgrep; a pkill/killall pattern that matches a
Claude session as lookout starts it, herdr, a shell or lookout's own waiter; a pattern built at run time; `kill -1`.
Run: python3 -m unittest tests/test_lookout_01318.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_lookout_f2 import StubCase  # noqa: E402

import permisos  # noqa: E402
import registry  # noqa: E402


class FrenoProcesosTest(StubCase):
    def handle(self, cmd, mode="auto", **entry):
        e = {"session_id": "s1", "nombre": "ag", "worktree": "/r/repo-wt-x", "sin_worktree": False,
             "solo_lectura": False, "lanzado_por": "lookout"}
        e.update(entry)
        registry.save(self.pid, {"agents": {"s1": e}})
        data = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd},
                "permission_mode": mode, "session_id": "s1", "cwd": self.tmp.name}
        out = permisos.handle(data, {"project_id": self.pid, "nombre": "ag"}, rules={})
        hso = (out or {}).get("hookSpecificOutput") or {}
        return hso.get("permissionDecision"), hso.get("permissionDecisionReason", "")

    def test_the_live_command_is_denied(self):
        cmd = 'pkill -f "tools/run-tests.sh" -n 2>/dev/null; ps -p 97089 -o pid,command | cut -c1-150'
        for mode in ("auto", "default", "acceptEdits", "bypassPermissions"):
            decision, why = self.handle(cmd, mode=mode)
            self.assertEqual(decision, "deny", mode)
            self.assertIn("«-n»", why)
            self.assertIn("antes del patrón", why)

    def test_an_agent_on_the_main_checkout_too(self):
        self.assertEqual(self.handle('pkill -f run-tests -9', sin_worktree=True, worktree=self.tmp.name)[0], "deny")

    def test_what_would_hit_other_agents_is_denied(self):
        for cmd in ('pgrep -f "tools/run-tests.sh" -n', 'pkill -f claude', 'pkill claude', 'pkill -x claude',
                    'pkill -f -- -n', 'pkill -f session-id', 'pkill -f lookout', 'pkill -f "lookout espera"',
                    'pkill herdr', 'pkill -i CLAUDE', 'pkill bash', 'pkill -f "append-system-prompt"', 'pkill -f .',
                    'killall claude', 'killall -9 herdr', 'killall -m "cla.*"', 'killall zsh',
                    'kill -9 -1', 'kill -- -1', 'kill -s KILL -1', 'pkill -f "$PATRON"', 'pkill -f `cat p`',
                    "sh -c 'pkill -f x -n'", '(cd /tmp && pkill -f run-tests -9)', 'echo hola && pkill claude',
                    'sudo pkill -f claude', 'pkill -f "["',
                    # advisor review: a pgrep that feeds kill, and this machine's real paths
                    'kill $(pgrep -f claude)', 'pgrep -f claude | xargs kill', 'kill `pgrep -f "\\-n"`',
                    'pkill -f %s' % os.path.expanduser("~"), 'pkill -f %s' % os.path.expanduser("~").lstrip("/"),
                    'pkill -f .local/state/lookout'):
            self.assertEqual(self.handle(cmd)[0], "deny", cmd)

    def test_a_narrow_kill_passes(self):
        for cmd in ('pkill -f "tools/run-tests.sh"', 'pkill -n -f "tools/run-tests.sh"', 'pkill -9 -f mutation-check',
                    'pkill -TERM -f "/tmp/x/suite-lenta.sh"', 'pgrep -lf "sleep 30"', 'pgrep -f run-tests',
                    'kill 97089', 'kill -9 12345 23456', 'kill -TERM 4242', 'killall Finder', 'killall -9 node-x',
                    'ps aux | grep claude', 'echo pkill -f x -n', 'grep -n "pkill" tools/test-tmp-propio.sh',
                    'pgrep -u will -f run-tests', 'pkill -P 4242 -f sleep', 'kill $(pgrep -f run-tests)',
                    'pgrep -f mutation-check | xargs kill', 'killall -SIGINT Finder'):
            self.assertEqual(self.handle(cmd)[0], None, cmd)

    def test_the_reason_says_how_to_do_it(self):
        _, why = self.handle('pkill -f claude')
        self.assertIn("kill <pid>", why)
        self.assertIn("claude", why)


class FrenoPorElHookTest(unittest.TestCase):
    """The deployed path: hooks/guard.sh with the hook's JSON on stdin, as Claude Code runs it (main() swallows any
    exception as "allow", so a crash in the brake would only show here)."""

    def test_guard_sh_denies_the_live_command(self):
        import json
        import subprocess
        import tempfile
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        guard = os.path.join(root, "plugins", "lookout", "hooks", "guard.sh")
        with tempfile.TemporaryDirectory() as st:
            sid = "11111111-2222-3333-4444-555555555555"
            os.makedirs(os.path.join(st, "sessions"))
            with open(os.path.join(st, "sessions", sid + ".json"), "w") as fh:
                json.dump({"project_id": "pX", "nombre": "ag"}, fh)
            data = {"session_id": sid, "hook_event_name": "PreToolUse", "tool_name": "Bash", "permission_mode": "auto",
                    "cwd": st, "tool_input": {"command": 'pkill -f "tools/run-tests.sh" -n 2>/dev/null'}}
            env = dict(os.environ, LOOKOUT_STATE_DIR=st, HERDR_PANE_ID="")
            p = subprocess.run(["sh", guard, "permisos.py"], input=json.dumps(data), capture_output=True, text=True,
                               env=env, timeout=30)
            out = json.loads(p.stdout or "{}").get("hookSpecificOutput") or {}
            self.assertEqual(out.get("permissionDecision"), "deny", p.stdout + p.stderr)
            data["tool_input"]["command"] = 'pkill -f "tools/run-tests.sh"'
            p = subprocess.run(["sh", guard, "permisos.py"], input=json.dumps(data), capture_output=True, text=True,
                               env=env, timeout=30)
            # 0.13.46: the first Bash in auto mode carries the one-time notice (additionalContext), never a decision
            out = json.loads(p.stdout or "{}").get("hookSpecificOutput") or {}
            self.assertNotIn("permissionDecision", out, p.stdout)
            self.assertIn("no le pidas al usuario que lo copie", out.get("additionalContext", ""))
            p = subprocess.run(["sh", guard, "permisos.py"], input=json.dumps(data), capture_output=True, text=True,
                               env=env, timeout=30)
            self.assertEqual(p.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()

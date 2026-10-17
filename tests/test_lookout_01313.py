"""0.13.13: a relief whose work is not only measuring starts through goalspec.

By hand the user read the agent's «Como retomar» and, when it held anything but measuring, answered «sí, continúa,
pero hazlo usando goalspec». The supervisor makes that call now (SKILL.md, «Relevo con goalspec») and passes
`lookout relevo --goalspec`; the new session gets `/goalspec:goalspec <trigger>` typed. Measured 2026-10-17 in
~/.local/state/lookout: a typed `/goalspec:interview …` reaches UserPromptSubmit with its text as typed, so the
delivery is confirmed the same way as the plain trigger.
Run: python3 -m unittest tests/test_lookout_01313.py
"""
import os
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_0130 as t130  # noqa: E402
import test_lookout_f2 as f2  # noqa: E402

import lookout_state  # noqa: E402
import lote  # noqa: E402
import registry  # noqa: E402
import relevo  # noqa: E402
import retiro  # noqa: E402
import retomar  # noqa: E402

LOOKOUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins", "lookout", "bin", "lookout")


class RelevoGoalspecTest(t130.RelevoSinTareaTest):
    """Its stubs (herdr, arranca), not its tests: those run in test_lookout_0130."""
    def setUp(self):
        super().setUp()
        self.saved_gs = relevo.gobierno.goalspec_de
        self.instalado = True
        relevo.gobierno.goalspec_de = lambda entry: self.instalado

    def tearDown(self):
        relevo.gobierno.goalspec_de = self.saved_gs
        super().tearDown()

    def run_relevo(self, goalspec, tarea="p-1"):
        self.agent("s1", nombre="ag", tarea=tarea, modelo="", pane_id="w1A:pJ", cwd="/x", worktree="/x")
        self.transcript("s1", self.config_rows() + [t130.u_text("sigue", time.time() - 50),
                                                    t130.a_text(t130.MINUTOS, time.time() - 10)])
        logs = []
        ok, msg = relevo._relevo(self.pid, registry.load(self.pid)["agents"]["s1"], lambda n: "nota", "", None, 1, 1,
                                 logs.append, goalspec=goalspec)
        self.assertTrue(ok, msg)
        return [c[1] for c in self.calls if c[0] == "arranca"][-1]["trigger"], logs

    def test_with_goalspec_the_trigger_is_the_skill_command(self):
        trigger, _ = self.run_relevo(True)
        self.assertEqual(trigger, "/goalspec:goalspec " + relevo.TRIGGER.format(id="p-1"))

    def test_without_the_flag_the_trigger_is_the_old_one(self):
        trigger, _ = self.run_relevo(False)
        self.assertEqual(trigger, relevo.TRIGGER.format(id="p-1"))  # byte for byte what 0.13.12 typed

    def test_an_agent_without_a_task_gets_it_too(self):
        trigger, _ = self.run_relevo(True, tarea="")
        self.assertEqual(trigger, "/goalspec:goalspec " + relevo.TRIGGER_SIN_TAREA.format(id="ag"))

    def test_without_goalspec_installed_the_flag_changes_nothing_and_says_so(self):
        self.instalado = False
        trigger, logs = self.run_relevo(True)
        self.assertEqual(trigger, relevo.TRIGGER.format(id="p-1"))
        self.assertTrue(any("sin efecto" in m for m in logs), logs)

    def test_a_retry_keeps_the_call_of_the_failed_attempt(self):
        def falla(pid, sid, *a, **k):
            relevo.lote.set_estado(pid, sid, "fallida")
            return False, "no arrancó"
        ok_arranca, relevo.lote.arranca = relevo.lote.arranca, falla
        self.agent("s1", nombre="ag", tarea="p-1", modelo="", pane_id="w1A:pJ", cwd="/x", worktree="/x")
        self.transcript("s1", self.config_rows() + [t130.u_text("sigue", time.time() - 50),
                                                    t130.a_text(t130.MINUTOS, time.time() - 10)])
        ok, msg = relevo._relevo(self.pid, registry.load(self.pid)["agents"]["s1"], lambda n: "nota", "", None, 1, 1,
                                 lambda m: None, goalspec=True)
        self.assertFalse(ok, msg)
        old = registry.load(self.pid)["agents"]["s1"]
        self.assertEqual(old["tarea_estado"], "relevo-fallido")
        self.assertTrue(old.get("relevo_goalspec"))
        relevo.lote.arranca = ok_arranca
        lookout_state.append_event(self.pid, {"session_id": "s1", "event": "end"})
        relevo.herdr_cli.agent_get = lambda pane: {}
        old_live = relevo.lote.live_sessions
        relevo.lote.live_sessions = lambda: set()
        try:
            ok, msg = relevo._relevo(self.pid, registry.load(self.pid)["agents"]["s1"], lambda n: "nota", "", None, 1,
                                     1, lambda m: None)  # the retry without the flag
        finally:
            relevo.lote.live_sessions = old_live
        self.assertTrue(ok, msg)
        trigger = [c[1] for c in self.calls if c[0] == "arranca"][-1]["trigger"]
        self.assertTrue(trigger.startswith("/goalspec:goalspec "), trigger)
        agents = registry.load(self.pid)["agents"]
        self.assertNotIn("relevo_goalspec", agents["s1"])  # relieved: the call is spent
        self.assertFalse([e for e in agents.values() if e.get("relevo_goalspec")])


for _name in [n for n in dir(t130.RelevoSinTareaTest) if n.startswith("test")]:
    setattr(RelevoGoalspecTest, _name, None)


class TecleadoTest(f2.StubCase):
    """What reaches the pane (adversary, codex r1: the tests above read `arranca`'s argument, not what is typed). The
    real lote.arranca and deliver.deliver run against the herdr stub: the one `agent prompt` call carries the
    /goalspec:goalspec line, and the stub's UserPromptSubmit (cut at 120 characters, as the hook keeps it) confirms it."""
    def typed(self, tarea, goalspec, instalado=True):
        entry = dict(self.entry, tarea=tarea, worktree=self.tmp.name)
        registry.save(self.pid, {"agents": {self.sid: entry}})
        relevo.gobierno.goalspec_de, saved = (lambda e: instalado), relevo.gobierno.goalspec_de
        try:
            trigger = relevo.trigger_de(entry, goalspec, lambda m: None)
        finally:
            relevo.gobierno.goalspec_de = saved
        self.hook_on_prompt(start_event={"path": self.events, "session_id": self.sid})
        sysfile = os.path.join(self.tmp.name, "s.md")
        open(sysfile, "w").close()
        ok, msg = lote.arranca(self.pid, self.sid, "w1:p1", self.tmp.name, "ag1", sysfile, "m", False, "relevo:x",
                               trigger, 2, lambda m: None)
        self.assertTrue(ok, msg)  # confirmed by the stub's UserPromptSubmit
        prompts = self.calls(["agent", "prompt"])
        self.assertEqual(len(prompts), 1, prompts)
        return prompts[0][3]

    def test_with_the_flag_the_skill_command_is_typed_once_and_confirmed(self):
        self.assertEqual(self.typed("p-1", True), "/goalspec:goalspec " + relevo.TRIGGER.format(id="p-1"))

    def test_without_the_flag_the_old_line_is_typed(self):
        # byte for byte what 0.13.12 typed: its TRIGGER is unchanged (git diff 4cdb148 -- plugins/lookout/bin/relevo.py)
        self.assertEqual(self.typed("p-1", False), relevo.TRIGGER.format(id="p-1"))

    def test_an_agent_without_a_task_both_ways(self):
        self.assertEqual(self.typed("", True), "/goalspec:goalspec " + relevo.TRIGGER_SIN_TAREA.format(id="ag1"))

    def test_an_agent_without_a_task_without_the_flag(self):
        self.assertEqual(self.typed("", False), relevo.TRIGGER_SIN_TAREA.format(id="ag1"))

    def test_without_goalspec_installed_the_old_line_is_typed(self):
        self.assertEqual(self.typed("p-1", True, instalado=False), relevo.TRIGGER.format(id="p-1"))


class LineasTest(unittest.TestCase):
    def test_the_lines_the_supervisor_reads_name_the_flag(self):
        self.assertIn("--goalspec", retomar.accion({"estado": "vigente"}))
        self.assertIn("--goalspec", retiro.RELEVO_NO_CIERRE)

    def test_the_cli_takes_the_flag(self):
        out = subprocess.run([sys.executable, LOOKOUT, "relevo", "--help"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("--goalspec", out.stdout)


if __name__ == "__main__":
    unittest.main()

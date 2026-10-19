"""0.13.31 (p-231e8eeb51): `lookout entrega --pasos reload` confirms the /reload-plugins by the agent's transcript.

Until 0.13.30 the reload step of `entrega` waited with `herdr pane wait-output --match Reloaded:`, which searches the
screen as it already is: an older «Reloaded:» still on screen gave «reload: ok» before the new one, and a full screen
gave the false «sin confirmar» that 0.13.24 removed from `lookout recarga` (16 of them in 3-tier, 2026-10-17; codex r1
note). Now both use the same reader (recarga.teclea): the new `local_command` row of /reload-plugins in the transcript,
the screen only when lookout finds no transcript, and a prompt herdr did not type is said, not waited for.
Run: python3 -m unittest tests/test_lookout_01331.py
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f2 as f2  # noqa: E402
import test_lookout_01324 as t24  # noqa: E402
import test_lookout_nombres as nombres  # noqa: E402

import registry  # noqa: E402


class EntregaReloadTest(f2.StubCase):
    def setUp(self):
        super().setUp()
        self.old_cfg = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = self.tmp.name  # transcripts under <tmp>/projects, as StubCase.transcript
        registry.save(self.pid, {"agents": {self.sid: dict(self.entry)}})
        self.transcript()
        self.path = os.path.join(self.projects, "-tmp-x", self.sid + ".jsonl")
        self.cli = nombres.load_cli()
        self.cli.project = lambda arg: (self.pid, self.tmp.name + "/.git")
        self.cli.ENTREGA_RELOAD_ESPERA = 1

    def tearDown(self):
        if self.old_cfg is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self.old_cfg
        super().tearDown()

    def fila(self):
        return json.dumps({"type": "system", "subtype": "local_command", "content": t24.RELOADED,
                           "commandRun": {"command": "reload-plugins", "args": ""},
                           "timestamp": "2026-10-18T15:12:16.158Z"}) + "\n"

    def agente(self, **extra):
        return dict({"agent_status": "idle", "cwd": self.tmp.name, "agent_session": {"value": self.sid}}, **extra)

    def entrega(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.cli.cmd_entrega(type("A", (), {"proyecto": self.pid, "agente": "ag1", "pasos": "reload",
                                                "timeout": 1})())
        return [l for l in out.getvalue().splitlines() if l.startswith("reload:")]

    def test_the_new_row_in_the_transcript_confirms_it(self):
        # a full screen: its «Reloaded:» count does not move, the transcript row does
        self.stub(agent_get=self.agente(), agent_read=t24.LLENA,
                  prompt_append={"path": self.path, "line": self.fila()})
        linea = self.entrega()
        self.assertEqual(len(linea), 1, linea)
        self.assertTrue(linea[0].startswith("reload: ok"), linea)
        self.assertIn("transcript", linea[0])

    def test_an_old_reloaded_on_screen_confirms_nothing(self):
        # before: wait-output matched the «Reloaded:» already on screen and said ok with no new reload
        with open(self.path, "a") as fh:
            fh.write(self.fila())
        self.stub(agent_get=self.agente(), agent_read=t24.LLENA)
        linea = self.entrega()
        self.assertEqual(len(linea), 1, linea)
        self.assertFalse(linea[0].startswith("reload: ok"), linea)
        self.assertIn("sin confirmar", linea[0])
        self.assertIn("transcript", linea[0])

    def test_a_prompt_herdr_did_not_type_is_not_waited_for(self):
        self.stub(agent_get=self.agente(), agent_read=t24.LLENA,
                  prompt_append={"path": self.path, "line": self.fila()}, prompt_rc=1)
        linea = self.entrega()
        self.assertEqual(len(linea), 1, linea)
        self.assertFalse(linea[0].startswith("reload: ok"), linea)
        self.assertIn("herdr", linea[0])

    def test_it_no_longer_waits_on_the_screen(self):
        self.stub(agent_get=self.agente(), agent_read=t24.LLENA,
                  prompt_append={"path": self.path, "line": self.fila()})
        self.entrega()
        self.assertEqual(self.calls(["pane", "wait-output"]), [])

    def test_without_a_transcript_the_screen_still_confirms(self):
        os.remove(self.path)
        self.stub(agent_get=self.agente(), agent_read=f2.EMPTY_BOX,
                  read_after_prompt="  ⎿  Reloaded: 5 plugins · 20 skills\n" + f2.EMPTY_BOX)
        linea = self.entrega()
        self.assertEqual(len(linea), 1, linea)
        self.assertTrue(linea[0].startswith("reload: ok"), linea)
        self.assertIn("pantalla", linea[0])


if __name__ == "__main__":
    unittest.main()

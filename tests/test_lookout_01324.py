"""0.13.24: the name SendMessage takes for an agent, and a /reload-plugins confirmed by the agent's transcript.

p-e9c8601cfb (3-tier, 2026-10-17): after a relief or a /rename, lookout's name for an agent is not its session's name:
to=cambio-worktrees gave «No agent named» (the session was cambio-worktrees-2, its /rename had collided with the dead
session that still held the name), to=correccion-snipet-de-cierre gave «not reachable» (the session had renamed itself
3tier-snippet-linea-extras). Claude Code keeps each live session's name and socket in <config>/sessions/<pid>.json;
`inicia` and `resumen` now print that name as the agent's `to`, and say so when they cannot read it.

p-eff2c277ba (3-tier, 2026-10-17): «sin confirmar: no veo «Reloaded:»» in 16 calls, and in all 16 the agent's own
transcript has its `local_command` row «Reloaded: …» inside the call, most 1-6 s after it was typed. The screen count
was the defect: `agent read --source recent --lines 400` of a Claude Code pane returns its 47 visible rows, so once the
screen is full of «Reloaded:» lines a new one pushes an old one out and the count stays (measured on a test agent,
2026-10-18: 3 false failures in 19). The transcript row is the confirmation now; the screen only without a transcript.
Run: python3 -m unittest tests/test_lookout_01324.py
"""
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f2 as f2  # noqa: E402
import test_lookout_f7 as f7  # noqa: E402

import digest  # noqa: E402
import lookout_state  # noqa: E402
import registry  # noqa: E402

AGENT_SID = "00000000-0000-4000-8000-000000000001"
RELOADED = "<local-command-stdout>Reloaded: 5 plugins · 20 skills · 12 agents · 53 hooks</local-command-stdout>"
# a full screen: ten identical blocks before and after the reload, as the test agent's screen was
LLENA = ("❯ /reload-plugins\n  ⎿  Reloaded: 5 plugins · 20 skills\n\n" * 10) + f2.EMPTY_BOX


def arranque(pid):
    r = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True,
                       env=dict(os.environ, TZ="UTC", LC_ALL="C"))
    return r.stdout.strip()


def sesion(cfg, sid, name, pid=None, sock="/tmp/cc-socks/1.sock", proc_start=None, updated=1):
    d = os.path.join(cfg, "sessions")
    os.makedirs(d, exist_ok=True)
    pid = os.getpid() if pid is None else pid
    with open(os.path.join(d, "%d.json" % pid), "w") as fh:
        json.dump({"pid": pid, "sessionId": sid, "name": name, "nameSource": "user", "messagingSocketPath": sock,
                   "updatedAt": updated, "procStart": arranque(pid) if proc_start is None else proc_start}, fh)


def proceso_muerto():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


class IniciaToTest(f7.IniciaTest):
    def con_agente(self):
        self.stub(agent_list=[{"name": "cambio-worktrees", "pane_id": "w1:p8", "cwd": self.repo, "agent": "claude",
                               "agent_status": "idle", "agent_session": {"value": AGENT_SID}}])

    def fila(self, out):
        filas = [l for l in out.splitlines() if " | " in l and AGENT_SID[:8] in l]
        self.assertEqual(len(filas), 1, out)
        return filas[0]

    def test_the_row_gives_the_name_sendmessage_takes(self):
        self.con_agente()
        sesion(self.cfg, AGENT_SID, "cambio-worktrees-2")
        r = self.inicia()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("to (SendMessage)", r.stdout)
        self.assertIn("cambio-worktrees-2", self.fila(r.stdout))

    def test_without_its_session_file_it_says_it_does_not_know(self):
        self.con_agente()
        r = self.inicia()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("to desconocido", self.fila(r.stdout))

    def test_a_dead_process_file_is_not_its_name(self):
        self.con_agente()
        sesion(self.cfg, AGENT_SID, "nombre-de-un-muerto", pid=proceso_muerto())
        r = self.inicia()
        self.assertNotIn("nombre-de-un-muerto", r.stdout)
        self.assertIn("to desconocido", self.fila(r.stdout))


class SesionesTest(unittest.TestCase):
    """codex r1: a pid the system gave to another process names nobody; Sonnet r1: a bad updatedAt breaks nothing."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.base = os.path.join(self.tmp.name, "sessions")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_reused_pid_is_not_the_session(self):
        import sesiones
        sesion(self.tmp.name, AGENT_SID, "de-otro-proceso", proc_start="Mon Jan  1 00:00:00 2024")
        self.assertIsNone(sesiones.de(AGENT_SID, base=self.base))

    def test_without_proc_start_it_is_not_the_session(self):
        # codex r2: with no procStart a reused pid cannot be told apart (every live file has it: 23 of 23, 2026-10-18)
        import sesiones
        sesion(self.tmp.name, AGENT_SID, "sin-arranque", proc_start="")
        self.assertIsNone(sesiones.de(AGENT_SID, base=self.base))

    def test_the_same_start_is_the_session(self):
        import sesiones
        sesion(self.tmp.name, AGENT_SID, "cambio-worktrees-2")
        self.assertEqual(sesiones.de(AGENT_SID, base=self.base)["name"], "cambio-worktrees-2")

    def test_a_bad_updated_at_does_not_break_it(self):
        import sesiones
        sesion(self.tmp.name, AGENT_SID, "cambio-worktrees-2", updated="ayer")
        sesion(self.tmp.name, AGENT_SID, "otro", pid=1, proc_start=arranque(1), updated=5)
        self.assertIn(sesiones.de(AGENT_SID, base=self.base)["name"], ("cambio-worktrees-2", "otro"))


class ResumenToTest(f2.StubCase):
    def setUp(self):
        super().setUp()
        self.cfg = os.path.join(self.tmp.name, "cfg")
        self.old_cfg = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = self.cfg
        reg = registry.load(self.pid)
        reg.setdefault("agents", {})[self.sid] = dict(self.entry, nombre="correccion-snipet-de-cierre")
        registry.save(self.pid, reg)

    def tearDown(self):
        if self.old_cfg is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self.old_cfg
        super().tearDown()

    def test_a_renamed_session_shows_its_real_name(self):
        sesion(self.cfg, self.sid, "3tier-snippet-linea-extras")
        out = digest.render(self.pid, mark=False, todo=True)
        fila = [l for l in out.splitlines() if "correccion-snipet-de-cierre" in l]
        self.assertTrue(fila, out)
        self.assertIn("to=3tier-snippet-linea-extras", fila[0])

    def test_the_same_name_adds_nothing(self):
        sesion(self.cfg, self.sid, "correccion-snipet-de-cierre")
        out = digest.render(self.pid, mark=False, todo=True)
        self.assertNotIn("to=", out)


class RecargaTranscriptTest(f2.StubCase):
    def setUp(self):
        super().setUp()
        self.old_cfg = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = self.tmp.name  # transcripts under <tmp>/projects, as StubCase.transcript
        reg = registry.load(self.pid)
        reg.setdefault("agents", {})[self.sid] = dict(self.entry)
        registry.save(self.pid, reg)
        import recarga
        self.recarga = recarga
        self.transcript()
        self.path = os.path.join(self.projects, "-tmp-x", self.sid + ".jsonl")

    def tearDown(self):
        if self.old_cfg is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self.old_cfg
        super().tearDown()

    def fila(self):
        return json.dumps({"type": "system", "subtype": "local_command", "content": RELOADED,
                           "commandRun": {"command": "reload-plugins", "args": ""},
                           "timestamp": "2026-10-18T15:12:16.158Z"}) + "\n"

    def test_a_full_screen_with_the_row_in_the_transcript_is_confirmed(self):
        self.stub(agent_get={"agent_status": "idle", "agent_session": {"value": self.sid}}, agent_read=LLENA,
                  prompt_append={"path": self.path, "line": self.fila()})
        ok, msg = self.recarga.recarga(self.pid, self.entry, espera=1)
        self.assertTrue(ok, msg)
        self.assertIn("transcript", msg)
        self.assertTrue(registry.load(self.pid)["agents"][self.sid].get("recargado"))

    def test_an_older_row_confirms_nothing(self):
        with open(self.path, "a") as fh:
            fh.write(self.fila())
        self.stub(agent_get={"agent_status": "idle", "agent_session": {"value": self.sid}}, agent_read=LLENA)
        ok, msg = self.recarga.recarga(self.pid, self.entry, espera=1)
        self.assertFalse(ok)
        self.assertIn("sin confirmar", msg)
        self.assertIn("transcript", msg)
        self.assertFalse(registry.load(self.pid)["agents"][self.sid].get("recargado"))

    def test_a_prompt_herdr_did_not_type_is_not_a_reload(self):
        # codex r1: the prompt's exit code was ignored
        self.stub(agent_get={"agent_status": "idle", "agent_session": {"value": self.sid}}, agent_read=LLENA,
                  prompt_append={"path": self.path, "line": self.fila()}, prompt_rc=1)
        ok, msg = self.recarga.recarga(self.pid, self.entry, espera=1)
        self.assertFalse(ok, msg)
        self.assertIn("herdr", msg)
        self.assertFalse(registry.load(self.pid)["agents"][self.sid].get("recargado"))

    def test_with_a_transcript_the_screen_alone_confirms_nothing(self):
        # codex r1: a «Reloaded:» more on the screen with no new row in a transcript lookout reads
        self.stub(agent_get={"agent_status": "idle", "agent_session": {"value": self.sid}}, agent_read=f2.EMPTY_BOX,
                  read_after_prompt="  ⎿  Reloaded: 5 plugins · 20 skills\n" + f2.EMPTY_BOX)
        ok, msg = self.recarga.recarga(self.pid, self.entry, espera=1)
        self.assertFalse(ok, msg)
        self.assertIn("transcript", msg)

    def test_a_row_without_its_command_is_not_a_reload(self):
        # codex r2: «Reloaded:» alone does not say which command ran (192 of 192 real rows carry commandRun)
        sin = json.dumps({"type": "system", "subtype": "local_command", "content": RELOADED}) + "\n"
        self.stub(agent_get={"agent_status": "idle", "agent_session": {"value": self.sid}}, agent_read=LLENA,
                  prompt_append={"path": self.path, "line": sin})
        self.assertFalse(self.recarga.recarga(self.pid, self.entry, espera=1)[0])

    def test_another_local_command_is_not_a_reload(self):
        otra = json.dumps({"type": "system", "subtype": "local_command", "content": "<local-command-stdout>Reloaded: "
                           "nada</local-command-stdout>", "commandRun": {"command": "otra"}}) + "\n"
        self.stub(agent_get={"agent_status": "idle", "agent_session": {"value": self.sid}}, agent_read=LLENA,
                  prompt_append={"path": self.path, "line": otra})
        self.assertFalse(self.recarga.recarga(self.pid, self.entry, espera=1)[0])


if __name__ == "__main__":
    unittest.main()

"""0.13.29 (p-ad978476a5): an agent with a live background shell stays quiet after `lookout recarga`.
Run: python3 -m unittest tests/test_lookout_01329.py

Bench 2026-10-18 with 0.13.26: after `lookout recarga` of an agent herdr saw `working` only because of its shell, `envia`
said «NO ENTREGADO: está working». /reload-plugins writes, after the Stop, a `user` row with `<local-command-caveat>`
(isMeta), a `user` row with `<command-name>/reload-plugins</command-name>` and a `system` row `local_command` with its
stdout (rows copied from that transcript, text shortened). A skill typed in the box writes `<command-message>` and
`<command-name>` too, but no `local_command`: it opens a turn.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_0130 as t130  # noqa: E402
import test_lookout_01310 as t1310  # noqa: E402
import test_lookout_f3 as f3  # noqa: E402

import deliver  # noqa: E402

iso = t130.iso
CAVEAT = ("<local-command-caveat>The command below was run directly in Claude Code, not sent to you as a request, and "
          "its output goes straight to the user. It's recorded here as context for later messages.</local-command-caveat>")


def caveat(ts):
    return {"type": "user", "isMeta": True, "timestamp": iso(ts), "message": {"role": "user", "content": CAVEAT}}


def comando(ts, nombre="reload-plugins"):
    return {"type": "user", "timestamp": iso(ts), "message": {"role": "user", "content": (
        "<command-name>/%s</command-name>\n            <command-message>%s</command-message>\n"
        "            <command-args></command-args>" % (nombre, nombre))}}


def salida(ts, texto="Reloaded: 5 plugins · 20 skills · 12 agents · 53 hooks"):
    return {"type": "system", "subtype": "local_command", "level": "info", "isMeta": False, "timestamp": iso(ts),
            "content": "<local-command-stdout>%s</local-command-stdout>" % texto}


class QuietoTrasComandoLocalTest(f3.Base):
    def setUp(self):
        super().setUp()
        self.e = self.agent("s1", "uno")
        self.now = time.time()
        self.transcript("s1", [t130.u_text("sigue", self.now - 60), t130.a_text("hecho", self.now - 30)])
        t1310.stop(self.pid, "s1", self.now - 20, "bg_wait", [t1310.SHELL])
        self.transcript("s1", [{"type": "system", "subtype": "stop_hook_summary", "timestamp": iso(self.now - 19)},
                               {"type": "system", "subtype": "turn_duration", "timestamp": iso(self.now - 19)}])

    def q(self):
        return deliver.quieto(self.pid, self.e, {"agent_status": "working"}, self.projects)

    def test_a_reload_after_the_stop_is_not_a_turn(self):
        # the order Claude Code wrote them: caveat (stamped later), command, its stdout
        self.transcript("s1", [caveat(self.now - 9.9), comando(self.now - 10), salida(self.now - 9.9)])
        self.assertTrue(self.q())

    def test_two_local_commands_in_a_row_are_not_a_turn(self):
        # two local commands with that shape in a row (a real /rename writes other rows)
        self.transcript("s1", [caveat(self.now - 9.9), comando(self.now - 10), salida(self.now - 9.9),
                               caveat(self.now - 5), comando(self.now - 5, "rename"), salida(self.now - 5, "ok")])
        self.assertTrue(self.q())

    def test_a_skill_typed_after_the_stop_is_a_turn(self):
        self.transcript("s1", [{"type": "user", "timestamp": iso(self.now - 10), "message": {"content": (
            "<command-message>checkpoint-3t</command-message>\n<command-name>/checkpoint-3t</command-name>")}},
            {"type": "user", "isMeta": True, "timestamp": iso(self.now - 10),
             "message": {"content": [{"type": "text", "text": "# Memory Checkpoint"}]}}])
        self.assertFalse(self.q())

    def test_a_command_with_no_output_yet_is_a_turn(self):
        # typed a moment ago: Claude Code has not written its local_command row
        self.transcript("s1", [caveat(self.now - 9.9), comando(self.now - 10)])
        self.assertFalse(self.q())

    def test_a_lone_caveat_is_a_turn(self):
        self.transcript("s1", [caveat(self.now - 10)])
        self.assertFalse(self.q())

    def test_a_prompt_after_a_reload_is_a_turn(self):
        self.transcript("s1", [caveat(self.now - 9.9), comando(self.now - 10), salida(self.now - 9.9),
                               t130.u_text("haz otra cosa", self.now - 3)])
        self.assertFalse(self.q())

    def test_a_caveat_that_is_not_meta_is_a_turn(self):
        # the same text typed by a person is a prompt, not Claude Code's own row
        fila = caveat(self.now - 9.9)
        del fila["isMeta"]
        self.transcript("s1", [fila, comando(self.now - 10), salida(self.now - 9.9)])
        self.assertFalse(self.q())

    def test_a_command_row_with_more_than_the_command_is_a_turn(self):
        fila = comando(self.now - 10)
        fila["message"]["content"] += "\ny además haz esto"
        self.transcript("s1", [caveat(self.now - 9.9), fila, salida(self.now - 9.9)])
        self.assertFalse(self.q())

    def test_a_command_and_its_output_without_the_caveat_is_a_turn(self):
        # codex r2 of the release: the set Claude Code writes always has its caveat (201 of 201 real reloads)
        self.transcript("s1", [comando(self.now - 10), salida(self.now - 9.9)])
        self.assertFalse(self.q())


if __name__ == "__main__":
    unittest.main()

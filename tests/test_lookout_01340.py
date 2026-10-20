"""0.13.40: the Stop of a turn whose last message is not in the transcript yet still carries its «Como retomar»
(p-fab08d3d95, banco 2026-10-19: the first Stop of banco-bloque, 18:04:19.532, read the transcript 127 ms after the
row of its text was created and came without `retomar`; the waiter's sweep found the block 61 s later). The hook
already holds the turn's last message in `last_assistant_message`; a block that only it has counts.
Run: python3 -m unittest tests/test_lookout_01340.py
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_0130 as t130  # noqa: E402
import test_lookout_f4 as f4  # noqa: E402

import on_state  # noqa: E402
import retomar  # noqa: E402

PID = f4.PID
BANCO = "Revisé el banco.\n\n## Como retomar\n```\nProximo paso: revisar notas.txt (p-01dfac8763).\n```"
VIEJO = "Hecho.\n\n## Como retomar\n```\nProximo paso: medir el banco (p-34c1ec3f19).\n```"


class StopSinUltimaFilaTest(f4.Base):
    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.repo, "memory"))
        with open(os.path.join(self.repo, "memory", "_pendientes.md"), "w") as fh:
            fh.write("- [ ] x — _id: p-01dfac8763_\n- [ ] w — _id: p-34c1ec3f19_\n")
        self.agent("s1", "banco-bloque")

    def stop(self, rows, msg):
        self.transcript("s1", rows)
        marker = {"project_id": PID, "nombre": "banco-bloque", "address": "uds:/tmp/sup.sock"}
        ev, _label, _ = on_state.build({"hook_event_name": "Stop", "session_id": "s1", "cwd": self.repo,
                                        "transcript_path": self.deliver.transcript_path("s1"),
                                        "last_assistant_message": msg}, marker)
        return ev

    def completo(self, text):
        now = time.time()
        return self.stop([t130.u_text("revisa el banco", now - 3), t130.a_text(text, now - 1)], text)

    def test_the_prompt_row_without_the_text_row_still_carries_the_block(self):
        ev = self.stop([t130.u_text("revisa el banco", time.time() - 3)], BANCO)
        self.assertEqual(ev.get("retomar"), self.completo(BANCO)["retomar"])
        self.assertEqual(ev["retomar"]["estado"], "vigente")  # a time of its own: not «no sé de cuándo es el bloque»

    def test_only_the_previous_turn_on_disk_gives_this_turns_block(self):
        now = time.time()
        ev = self.stop([t130.u_text("mide", now - 60), t130.a_text(VIEJO, now - 50)], BANCO)
        self.assertEqual(ev["retomar"]["pendientes"], ["p-01dfac8763"])

    def test_the_previous_turns_block_does_not_come_back_with_a_last_message_without_one(self):
        now = time.time()
        ev = self.stop([t130.u_text("mide", now - 60), t130.a_text(VIEJO, now - 50)], "Listo.")
        self.assertNotIn("retomar", ev)

    def test_no_transcript_file_yet_still_carries_the_block(self):
        marker = {"project_id": PID, "nombre": "banco-bloque", "address": "uds:/tmp/sup.sock"}
        ev, _l, _o = on_state.build({"hook_event_name": "Stop", "session_id": "s1", "cwd": self.repo,
                                     "transcript_path": os.path.join(self.repo, "no-existe.jsonl"),
                                     "last_assistant_message": BANCO}, marker)
        self.assertEqual(ev["retomar"]["estado"], "vigente")

    def test_a_full_transcript_keeps_the_time_of_its_row(self):
        now = time.time()
        rows = [t130.u_text("sigue", now - 3600), t130.a_text(BANCO, now - 3500)]
        self.transcript("s1", rows)
        r = retomar.para_agente(PID, "s1", self.deliver.transcript_path("s1"), self.repo, ultimo=BANCO)
        self.assertEqual(r["estado"], "vigente")
        _t, ts = retomar.ultimo_turno(self.deliver.transcript_path("s1"))
        self.assertLess(ts, now - 3000)


class RetomarErrorTest(f4.Base):
    """An error while reading the block is no longer silent: the event says which one, so a live run shows it."""

    def test_an_error_reading_the_block_is_in_the_event(self):
        self.agent("s1", "banco-bloque")
        self.transcript("s1", [t130.u_text("revisa", time.time() - 3), t130.a_text(BANCO, time.time() - 1)])
        orig = retomar.info

        def roto(*a, **k):
            raise RuntimeError("registro a medio escribir")
        retomar.info = roto
        try:
            ev, _l, _o = on_state.build({"hook_event_name": "Stop", "session_id": "s1", "cwd": self.repo,
                                         "transcript_path": self.deliver.transcript_path("s1"),
                                         "last_assistant_message": BANCO}, {"project_id": PID, "nombre": "b"})
        finally:
            retomar.info = orig
        self.assertNotIn("retomar", ev)
        self.assertEqual(ev.get("retomar_error"), "RuntimeError: registro a medio escribir")


if __name__ == "__main__":
    unittest.main()

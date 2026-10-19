"""0.13.32: two agents of 3-tier-memory sat finished and unseen on 2026-10-18/19 (audit of the supervisor, 2026-10-19).
- decisiones-pendientes-bloqueadas closed its goalspec run at 08:45:03 ([COMPLETION-REVIEW], group «listo»); its next
  turn, 5 s later, carried no marker, so grupo() put it back in «idle» and the digest hid it in «+2 agentes más»
  while its last turn asked the user «¿Hacemos merge del PR #40?». A finished run now stays «listo» until a later
  goalspec marker other than a completion review (a new run) replaces it.
- pendientes-en-sessionstart left a vigente «Como retomar» at 18:43:02 (next session: make p-e376b39ea2 stable). The
  digest said «→ lookout relevo» on every wake for ~15 h; the supervisor neither relieved it nor opened a modal, and
  transicion() sends the user no notification for a block (the supervisor attends it). A vigente or ambiguo block
  still unattended after 30 min now sends the user ONE herdr notification.
Run: python3 -m unittest tests/test_lookout_01332.py
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f4 as f4  # noqa: E402

import decisiones  # noqa: E402
import herdr_cli  # noqa: E402
import heuristicas  # noqa: E402
import lookout_state  # noqa: E402
import registry  # noqa: E402
import vigia  # noqa: E402

PID = f4.PID
CR = "[COMPLETION-REVIEW: adversary model=different (gpt-5.6-luna; claude-sonnet-5-5) backends=both]"
BLOQUE = {"estado": "vigente", "pendientes": ["p-c87fde0912", "p-e376b39ea2"], "bloque_id": "b1", "motivo": ""}


class Base(f4.Base):
    def setUp(self):
        super().setUp()
        self.avisos = []
        self.old_run = herdr_cli.run

        def run(args, timeout=None, **kw):
            if args[:2] == ["notification", "show"]:
                self.avisos.append(args)
            return 0, "", ""
        herdr_cli.run = run

    def tearDown(self):
        herdr_cli.run = self.old_run
        super().tearDown()

    def ev(self, event, ts, sid="s1", **kw):
        e = dict({"event": event, "session_id": sid, "nombre": "ag", "ts": ts}, **kw)
        lookout_state.append_event(PID, e)
        return e

    def grupo(self, sid="s1"):
        return heuristicas.grupo(lookout_state.read_events(PID, 0)[0], sid,
                                 registry.load(PID)["agents"].get(sid), decisiones.load(PID).get("items"))


class ListoQueSeMantieneTest(Base):
    def test_a_reply_after_the_close_keeps_it_listo(self):
        self.agent("s1", "ag")
        t = time.time() - 600
        self.ev("working", t)
        self.ev("idle", t + 1, marcadores=[CR])
        self.ev("working", t + 2)
        self.ev("idle", t + 6, marcadores=[])           # 3-tier 08:45:08: its next turn, no marker
        self.ev("working", t + 400)
        self.ev("idle", t + 410, marcadores=[])         # 09:58: it answered the supervisor
        self.assertEqual(self.grupo(), "listo")

    def test_a_new_run_takes_it_out(self):
        self.agent("s1", "ag")
        t = time.time() - 600
        self.ev("idle", t, marcadores=[CR])
        self.ev("working", t + 10)
        self.ev("idle", t + 20, marcadores=["[ADVERSARY-VERDICT: break ungrounded=1 unfalsified=0 incomplete=0 "
                                            "autonomy-violations=0 unsafe=0]"])
        self.assertEqual(self.grupo(), "idle")

    def test_working_is_still_working(self):
        self.agent("s1", "ag")
        t = time.time() - 600
        self.ev("idle", t, marcadores=[CR])
        self.ev("working", t + 10)
        self.assertEqual(self.grupo(), "trabajando")

    def test_without_a_close_it_is_idle(self):
        self.agent("s1", "ag")
        self.ev("idle", time.time() - 10, marcadores=[])
        self.assertEqual(self.grupo(), "idle")

    def test_the_user_is_told_once(self):
        self.agent("s1", "ag")
        t = time.time() - 600
        heuristicas.transicion(PID, self.ev("idle", t, marcadores=[CR]))
        heuristicas.transicion(PID, self.ev("working", t + 1))
        heuristicas.transicion(PID, self.ev("idle", t + 6, marcadores=[]))
        listos = [a for a in self.avisos if "listo para revisar" in a[2]]
        self.assertEqual(len(listos), 1, self.avisos)


class BloqueSinAtenderTest(Base):
    def test_after_30_min_the_user_gets_one_notification(self):
        self.agent("s1", "ag")
        now = time.time()
        self.ev("idle", now - 31 * 60, retomar=dict(BLOQUE))
        self.assertEqual(len(heuristicas.avisa_bloques(PID, now)), 1)
        self.assertEqual(len(self.avisos), 1, self.avisos)
        self.assertIn("ag", self.avisos[0][2])
        self.assertEqual(heuristicas.avisa_bloques(PID, now + 120), [])   # once per block
        self.assertEqual(len(self.avisos), 1)

    def test_before_30_min_nothing(self):
        self.agent("s1", "ag")
        now = time.time()
        self.ev("idle", now - 10 * 60, retomar=dict(BLOQUE))
        self.assertEqual(heuristicas.avisa_bloques(PID, now), [])
        self.assertEqual(self.avisos, [])

    def test_a_modal_opened_after_it_attends_it(self):
        self.agent("s1", "ag")
        now = time.time()
        self.ev("idle", now - 31 * 60, retomar=dict(BLOQUE))
        decisiones.abre(PID, "¿relevo, cierro o lo dejo?", agentes=["ag"], notificar=False)
        self.assertEqual(heuristicas.avisa_bloques(PID, now), [])

    def test_new_work_after_it_attends_it(self):
        self.agent("s1", "ag")
        now = time.time()
        self.ev("idle", now - 31 * 60, retomar=dict(BLOQUE))
        self.ev("working", now - 60)
        self.assertEqual(heuristicas.avisa_bloques(PID, now), [])

    def test_a_retired_or_relieved_agent_is_not_announced(self):
        self.agent("s1", "ag", retirado=True)
        self.agent("s2", "bg", tarea_estado="relevada")
        now = time.time()
        self.ev("idle", now - 31 * 60, retomar=dict(BLOQUE))
        self.ev("idle", now - 31 * 60, sid="s2", retomar=dict(BLOQUE))
        self.assertEqual(heuristicas.avisa_bloques(PID, now), [])

    def test_a_new_block_is_announced_again(self):
        self.agent("s1", "ag")
        now = time.time()
        self.ev("idle", now - 90 * 60, retomar=dict(BLOQUE))
        self.assertEqual(len(heuristicas.avisa_bloques(PID, now - 50 * 60)), 1)
        self.ev("working", now - 45 * 60)
        self.ev("idle", now - 40 * 60, retomar=dict(BLOQUE, bloque_id="b2"))
        self.assertEqual(len(heuristicas.avisa_bloques(PID, now)), 1)
        self.assertEqual(len(self.avisos), 2)

    def test_the_same_block_on_a_later_reply_is_not_announced_again(self):
        # adversary r1: pendientes-en-sessionstart carried bloque 3b70ff1c74f1 on three idles (18:42:43, :55, 18:43:02)
        self.agent("s1", "ag")
        now = time.time()
        self.ev("idle", now - 120 * 60, retomar=dict(BLOQUE))
        self.assertEqual(len(heuristicas.avisa_bloques(PID, now - 60 * 60)), 1)
        self.ev("working", now - 50 * 60)
        self.ev("idle", now - 49 * 60, retomar=dict(BLOQUE))
        self.assertEqual(heuristicas.avisa_bloques(PID, now), [])
        self.assertEqual(len(self.avisos), 1, self.avisos)

    def test_the_30_min_count_from_the_first_idle_with_that_block(self):
        self.agent("s1", "ag")
        now = time.time()
        self.ev("idle", now - 40 * 60, retomar=dict(BLOQUE))
        self.ev("working", now - 6 * 60)
        self.ev("idle", now - 5 * 60, retomar=dict(BLOQUE))   # a reply 5 min ago re-carries the 40-min-old block
        self.assertEqual(len(heuristicas.avisa_bloques(PID, now)), 1)

    def test_the_checker_pass_runs_it(self):
        self.agent("s1", "ag")
        self.ev("idle", time.time() - 31 * 60, retomar=dict(BLOQUE))
        vigia.revisa(PID)
        self.assertEqual(len(self.avisos), 1, self.avisos)

    def test_the_digest_row_says_a_relief_or_a_modal(self):
        import retomar
        self.assertIn("--agentes", retomar.accion(BLOQUE))


if __name__ == "__main__":
    unittest.main()

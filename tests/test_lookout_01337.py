"""0.13.37: supervisor.md hides the session a failed relief never started, like the summary since 0.13.4
(p-e12aa7b891), and the skill tells the supervisor to let `lookout relevo` read the input box instead of stating what
it holds from an old reading (p-ca0cbbbadb).
Run: python3 -m unittest tests/test_lookout_01337.py
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f4 as f4  # noqa: E402

import lookout_state  # noqa: E402
import supervisor_md  # noqa: E402

PID = f4.PID


class FilaFantasmaTest(f4.Base):
    def test_supervisor_md_hides_the_session_a_failed_relief_never_started(self):
        # live 3-tier 2026-10-19: «agente-3-tier-memory-prueba-de-l~3b9909 | … | fallida | sin eventos» was still in
        # supervisor.md three days after the failed relief; the summary hid it since 0.13.4 (digest.py)
        self.agent("s1", "prueba", tarea_estado="relevo-fallido", tarea_motivo="no llegó el SessionStart")
        self.agent("s2", "prueba~s2", tarea_estado="fallida", relevo_de="s1")
        lookout_state.append_event(PID, {"event": "end", "session_id": "s1", "nombre": "prueba", "ts": time.time()})
        out = supervisor_md.render(PID)
        self.assertNotIn("prueba~s2", out)
        self.assertIn("relevo-fallido", out)  # the agent whose relief failed stays

    def test_a_failed_relief_child_that_did_start_stays(self):
        self.agent("s1", "prueba", tarea_estado="relevo-fallido")
        self.agent("s2", "prueba~s2", tarea_estado="fallida", relevo_de="s1")
        lookout_state.append_event(PID, {"event": "start", "session_id": "s2", "nombre": "prueba~s2", "ts": time.time()})
        self.assertIn("prueba~s2", supervisor_md.render(PID))

    def test_a_failed_launch_that_is_no_relief_stays(self):
        self.agent("s3", "otra", tarea_estado="fallida")
        self.assertIn("otra", supervisor_md.render(PID))


class CajaDeAhoraTest(unittest.TestCase):
    def test_the_skill_lets_relevo_read_the_box(self):
        # live 3-tier 2026-10-16 (d42): the supervisor told the user the agent's box held a draft, from a reading 18 h
        # old, and asked instead of relieving
        with open(os.path.join(f4.ROOT, "plugins", "lookout", "skills", "supervisa", "SKILL.md"), encoding="utf-8") as fh:
            skill = fh.read()
        self.assertIn("No afirmes qué hay en su caja", skill)
        self.assertIn("NO: la caja de", skill)


if __name__ == "__main__":
    unittest.main()

"""0.13.19: «hooks viejos» counts the reload lookout typed, not only the agent's last hook event.

Live case (3-tier, 2026-10-16/17): prompts-repetidos (4237bac9) stayed idle from 10-16 22:22 to 10-17 20:22 with no hook
event, the last one written by hooks older than 0.13.8 (no `v`). The supervisor reloaded it 4 times with «Reloaded:» on
screen; each time lookout was updated again the row came back as «lookout <0.13.8», the version of that old event, so
the reload looked useless and the supervisor reloaded in a loop. A reload loads what was installed then (`recargado`),
so the hooks run at least that version: the row names it and says a newer one arrived after the reload.
Run: python3 -m unittest tests/test_lookout_01319.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_lookout_0138 import HooksViejosTest, bloque, PID, VERSION  # noqa: E402

import digest  # noqa: E402

LK = "lookout@lookout-marketplace"
TRES = "3-tier-memory@3-tier-memory-marketplace"


class RecargaCuentaTest(HooksViejosTest):
    def test_a_reload_before_the_last_update_names_the_reloaded_version(self):
        self.agent("s1", "quieto", recargado={LK: "0.13.11"})
        self.ev("s1")                                    # its last hook event, before 0.13.8 (no `v`)
        fila = bloque(digest.render(PID, mark=True), "quieto")
        self.assertIn("hooks viejos: lookout 0.13.11 (instalada %s)" % VERSION, fila)
        self.assertNotIn("<0.13.8", fila)
        self.assertIn("ya recargado; la %s llegó después" % VERSION, fila)

    def test_the_same_for_a_plugin_its_hooks_cite(self):
        self.agent("s1", "tres", recargado={LK: VERSION, TRES: "2.62.5"})
        self.ev("s1", v=VERSION)
        self.hook_cita("s1", "2.62.0")                   # cited before the reload
        fila = bloque(digest.render(PID, mark=True), "tres")
        self.assertIn("3-tier-memory 2.62.5 (instalada 2.62.6)", fila)
        self.assertNotIn("2.62.0", fila)

    def test_a_newer_event_than_the_reload_still_counts(self):
        self.agent("s1", "nuevo", recargado={LK: "0.13.9"})
        self.ev("s1", v="0.13.11")
        fila = bloque(digest.render(PID, mark=True), "nuevo")
        self.assertIn("lookout 0.13.11 (instalada %s)" % VERSION, fila)
        self.assertNotIn("ya recargado", fila)

    def test_never_reloaded_reads_as_before(self):
        self.agent("s1", "viejo")
        self.ev("s1")
        fila = bloque(digest.render(PID, mark=True), "viejo")
        self.assertIn("lookout <0.13.8 (instalada %s)" % VERSION, fila)
        self.assertNotIn("ya recargado", fila)


if __name__ == "__main__":
    unittest.main()

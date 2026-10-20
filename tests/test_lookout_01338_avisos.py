"""0.13.38 (p-71e240cd2b): every herdr notification lookout sends is written, with herdr's exit code, to avisos.jsonl.
Run: python3 -m unittest tests/test_lookout_01338_avisos.py

Banco 2026-10-19: avisa_bloques wrote avisos_bloque.json and called herdr without looking at the result, so a live
test could not tell that the notification went out unless Víctor looked at the screen.
"""
import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f6  # noqa: E402,F401  (puts plugins/lookout/bin on sys.path)

import decisiones  # noqa: E402
import herdr_cli  # noqa: E402
import lookout_state  # noqa: E402
import permisos  # noqa: E402

BIN = os.path.dirname(herdr_cli.__file__)
PID = "p-avisos"


class AvisosCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        old = os.environ.get("LOOKOUT_STATE_DIR")
        os.environ["LOOKOUT_STATE_DIR"] = self.tmp.name
        self.addCleanup(lambda: os.environ.pop("LOOKOUT_STATE_DIR") if old is None
                        else os.environ.__setitem__("LOOKOUT_STATE_DIR", old))
        self.rc = 0
        self.calls = []
        real = herdr_cli.run
        self.addCleanup(setattr, herdr_cli, "run", real)
        herdr_cli.run = lambda args, timeout=10: (self.calls.append(list(args)) or (self.rc, "", "boom" if self.rc else ""))

    def avisos(self):
        try:
            with open(os.path.join(lookout_state.project_dir(PID), "avisos.jsonl"), encoding="utf-8") as fh:
                return [json.loads(line) for line in fh if line.strip()]
        except OSError:
            return []


class AvisosTest(AvisosCase):
    def test_a_decision_notification_is_logged_with_herdrs_exit_code(self):
        self.rc = 1
        decisiones.abre(PID, "¿Publico 0.2.0?", agentes=["uno"])
        self.assertEqual(len(self.calls), 1)
        av = self.avisos()
        self.assertEqual(len(av), 1, av)
        self.assertEqual((av[0]["tipo"], av[0]["rc"]), ("decision", 1))
        self.assertIn("decisión tuya pendiente", av[0]["titulo"])
        self.assertIn("boom", av[0].get("error", ""))
        self.assertIn("ts", av[0])

    def test_a_permission_notification_is_logged_and_still_returns_its_rc(self):
        n = permisos.notify(PID, "permiso", "lookout: uno pide permiso", "Bash git push")
        self.assertEqual(n["notif_rc"], 0)
        av = self.avisos()
        self.assertEqual([(a["tipo"], a["rc"]) for a in av], [("permiso", 0)])
        self.assertNotIn("error", av[0])

    def test_a_title_with_a_lone_surrogate_is_still_logged(self):
        # codex r2: text decoded from an agent's JSON can carry half a surrogate pair; the line was lost
        rc = herdr_cli.notifica(PID, "transicion", "lookout: uno \udcff listo", "cuerpo \ud800", sound=None)
        self.assertEqual(rc, 0)
        av = self.avisos()
        self.assertEqual([(a["tipo"], a["rc"]) for a in av], [("transicion", 0)])
        self.assertIn("lookout: uno", av[0]["titulo"])

    def test_no_module_sends_a_notification_without_going_through_the_log(self):
        directos = []
        for f in sorted(os.listdir(BIN)):
            p = os.path.join(BIN, f)
            if f == "herdr_cli.py" or not os.path.isfile(p) or not (f.endswith(".py") or f == "lookout"):
                continue
            with open(p, encoding="utf-8") as fh:
                for i, line in enumerate(fh, 1):
                    if re.search(r"""["']notification["'],\s*["']show["']""", line):
                        directos.append("%s:%d" % (f, i))
        self.assertEqual(directos, [])


if __name__ == "__main__":
    unittest.main()

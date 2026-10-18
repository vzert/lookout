"""0.13.21: `decision --cierra` on a decision that is already answered says so, and a modal that named no decision reads
as what it is.

Live case (3-tier, 2026-10-17): the vigía's test modals d125 and d126 named no decision, so the hook opened each as its
own entry and closed it with the user's answer («Listo»), with no yes or no. Later the supervisor tried
`lookout decision … --cierra d125` and lookout answered «No hay una decisión abierta d125.» (rc 5): it read as if d125
did not exist, and supervisor.md showed it as «respondió», neither yes nor no. Now `--cierra` on an answered decision
prints how it was answered (rc 0), on an unknown id says it does not exist, and the list says that an answer with no
yes or no authorizes nothing.
Run: python3 -m unittest tests/test_lookout_01321.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOOKOUT = os.path.join(ROOT, "plugins", "lookout", "bin", "lookout")
sys.path.insert(0, os.path.join(ROOT, "plugins", "lookout", "bin"))

PID = "pD21"
HOOK = {"id": "d125", "texto": "[prueba del vigía] ¿Listo?", "agentes": [], "desde": 1.0, "estado": "respondida",
        "origen": "hook", "tool_use_id": "t1", "pregunta": "[prueba del vigía] ¿Listo?",
        "respuesta_usuario": "[prueba del vigía] ¿Listo? = Listo", "respuesta": "[prueba del vigía] ¿Listo? = Listo",
        "aprueba": None, "hasta": 2.0}
SI = {"id": "d127", "texto": "¿Cerrar p-1?", "agentes": ["ag"], "desde": 1.0, "estado": "respondida", "si_es": "Cerrar",
      "tool_use_id": "t2", "respuesta": "Cerrar", "aprueba": True, "hasta": 2.0}
SUPERVISOR_NO = {"id": "d130", "texto": "¿Borrar x?", "agentes": ["ag"], "desde": 1.0, "estado": "respondida",
                 "respuesta": "no", "aprueba": False, "hasta": 2.0}


class CierraRespondidaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = os.path.join(self.tmp.name, "projects", PID)
        os.makedirs(d)
        with open(os.path.join(d, "lock.json"), "w") as fh:
            json.dump({"common_dir": "", "supervisor": {}}, fh)
        with open(os.path.join(d, "decisiones.json"), "w") as fh:
            json.dump({"items": [HOOK, SI, SUPERVISOR_NO]}, fh)

    def tearDown(self):
        self.tmp.cleanup()

    def cierra(self, did):
        p = subprocess.run([sys.executable, LOOKOUT, "decision", PID, "--cierra", did, "--si", "--respuesta", "x"],
                           capture_output=True, text=True, timeout=30,
                           env=dict(os.environ, LOOKOUT_STATE_DIR=self.tmp.name))
        return p.returncode, p.stdout + p.stderr

    def test_a_hook_modal_with_no_decision_is_said_to_be_answered(self):
        rc, out = self.cierra("d125")
        self.assertEqual(rc, 0, out)
        self.assertIn("ya está respondida", out)
        self.assertIn("«[prueba del vigía] ¿Listo? = Listo»", out)
        self.assertIn("no autoriza nada", out)
        self.assertNotIn("No hay una decisión abierta", out)

    def test_an_answered_yes_or_no_is_said_with_its_answer(self):
        rc, out = self.cierra("d130")
        self.assertEqual(rc, 0, out)
        self.assertIn("ya está respondida", out)
        self.assertIn("NO", out)

    def test_an_unknown_id_does_not_exist(self):
        rc, out = self.cierra("d999")
        self.assertEqual(rc, 5)
        self.assertIn("no existe", out)

    def test_nothing_is_rewritten(self):
        self.cierra("d125")
        with open(os.path.join(self.tmp.name, "projects", PID, "decisiones.json")) as fh:
            items = {i["id"]: i for i in json.load(fh)["items"]}
        self.assertIsNone(items["d125"]["aprueba"])
        self.assertEqual(items["d130"]["aprueba"], False)


class EtiquetaTest(unittest.TestCase):
    def test_supervisor_md_says_an_answer_with_no_yes_or_no_authorizes_nothing(self):
        import supervisor_md
        self.assertEqual(supervisor_md.veredicto(HOOK), "respondió, sin sí ni no (no autoriza nada)")
        self.assertEqual(supervisor_md.veredicto(SI), "SÍ")
        self.assertEqual(supervisor_md.veredicto(SUPERVISOR_NO), "NO")


if __name__ == "__main__":
    unittest.main()

"""0.13.42 (p-687158e30a): every `lookout decision --abre` reminds to put the decision's id at the end of the modal's
question. Since 0.13.9 the openings with --si-es (and later --shells-parar, --permiso, --sin-revisor) said «Pon «(dN)»
al final de su pregunta»; the one without --si-es only said how to close it, so the supervisor could ask without the
id and the decision stayed open (reminded once: the safe side, but a question the hook could not tie to it).
Run: python3 -m unittest tests/test_lookout_01342.py
"""
import argparse
import contextlib
import io
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class IdAlFinalTest(unittest.TestCase):
    def _abre(self, si_es):
        import test_lookout_0137 as t137

        class T(t137.EnviaDelUsuarioTest):
            def runTest(self):
                pass
        t = T()
        t.setUp()
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = t.lk.cmd_decision(argparse.Namespace(proyecto=t137.PID, abre="¿Publico?", agentes="uno",
                                                          si_es=si_es, cierre=False, nueva=False, cierra=None,
                                                          respuesta=None, si=False, no=False, lista=False))
            return rc, out.getvalue()
        finally:
            t.tearDown()

    def test_without_si_es_it_asks_for_the_id(self):
        rc, out = self._abre("")
        self.assertEqual(rc, 0, out)
        m = re.search(r"Decisión (d\d+) abierta", out)
        self.assertTrue(m, out)
        self.assertIn("Pon «(%s)» al final de su pregunta" % m.group(1), out)
        self.assertIn("--si-es", out)  # still says how a yes can authorize something

    def test_with_si_es_it_still_asks_for_the_id(self):
        rc, out = self._abre("Publicar")
        self.assertEqual(rc, 0, out)
        m = re.search(r"Decisión (d\d+) abierta", out)
        self.assertTrue(m, out)
        self.assertIn("Pon «(%s)» al final de su pregunta" % m.group(1), out)


if __name__ == "__main__":
    unittest.main()

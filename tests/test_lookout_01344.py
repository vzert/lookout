"""0.13.44: what lookout types in an agent's pane with the user's yes carries the question the user saw in the modal,
not only its id. 3-tier-memory, 2026-10-20: d288 approved the PLAN of «cambio-worktrees» with «el push va aparte»;
the agent only got «aprobado (d288)» (line 142 of its transcript) and wrote «Ratificado: d288» in its goalspec
checkpoint (line 198): neither the agent nor its external reviewer could read what d288 approved or left out.
Run: python3 -m unittest tests/test_lookout_01344.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_0137 as t0137  # noqa: E402

# d288 in the 3-tier-memory project's decisiones.json, word for word; the helper adds « (dN)» as the modal did
PREGUNTA_D288 = ("El relevo de «Cambio worktrees» tiene su plan para el fallo 1 del reporte de cloudflare-expert. "
                 "learning.update rechaza una regla con «codigo-antes» cuando su único «<» está dentro de código en "
                 "línea. El arreglo quita los tramos de código en línea antes de buscar, con la regla de markdown de "
                 "comillas invertidas emparejadas, sin adivinar por el texto. Un bloque de código real sigue "
                 "rechazado. Primero una prueba roja, después una mutación, las pruebas del fichero y el revisor. "
                 "Versión 2.63.26; el push va aparte. ¿Tecleo «aprobado» en su pane? (p-274c87b575)")


class AlcanceDeLaDecisionTest(t0137.EnviaDelUsuarioTest):
    # the helpers of 0.13.7's test; its own tests run in its module, not again here (None is not collected)
    locals().update({n: None for n in dir(t0137.EnviaDelUsuarioTest) if n.startswith("test_")})

    def test_the_approval_carries_the_question_the_user_saw(self):
        dn = self.decision(PREGUNTA_D288, "Sí, teclea «aprobado» (Recomendado)")
        self.assertEqual(self.envia("aprobado", dn), 0)
        (_n, _k, texto), = self.enviados
        self.assertTrue(texto.startswith("aprobado (%s) — lo que aprobó el usuario: «" % dn), texto)
        self.assertIn("el push va aparte", texto)
        self.assertIn(PREGUNTA_D288, texto)
        self.assertNotIn("\n", texto)                                    # one line in the agent's box

    def test_a_question_on_several_lines_is_typed_on_one(self):
        dn = self.decision("¿Tecleo «aprobado» en el pane de uno?\nNada sale de la máquina sin otro sí.", "Sí")
        self.assertEqual(self.envia("aprobado", dn), 0)
        (_n, _k, texto), = self.enviados
        self.assertNotIn("\n", texto)
        self.assertIn("en el pane de uno? Nada sale de la máquina sin otro sí.", texto)

    def test_a_command_still_goes_alone(self):
        dn = self.decision("¿Corro `! git push origin lookout/uno` en el pane de uno?", "Sí")
        self.assertEqual(self.envia("! git push origin lookout/uno", dn), 0)
        self.assertEqual(self.enviados, [("uno", "usuario:" + dn, "! git push origin lookout/uno")])


if __name__ == "__main__":
    import unittest
    unittest.main()

"""0.13.14: supervisor.md and the digest show the exact label of each open decision's modal option.

A decision opened with --si-es closes from the user's literal choice in the modal: any other label counts as no. A
supervisor that picks up an open decision (after a relief or a compaction) saw only the question, and had to read
decisiones.json to know the label to put in the modal (codex r11 on 0887ded). The same holds for the two labels of a
--shells-parar/--shells-dejar decision. The label goes before the question and is never clipped, so the digest's
160-column clip of a long question (or of a long label) never cuts it. Codex r1 on 0b199e0: the label was also missing
from supervisor.md's «Proximo paso» line and from the supervisor's Stop reminder.
Run: python3 -m unittest tests/test_lookout_01314.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f3 as f3  # noqa: E402
import test_lookout_f4 as f4  # noqa: E402

import decisiones  # noqa: E402
import digest  # noqa: E402
import on_supervisor  # noqa: E402
import supervisor_md  # noqa: E402

LARGA = "Sí, ciérrala aunque " + "cite un pendiente abierto y " * 7 + "fin"   # 213 characters, over the 160 columns
LARGO = "¿Cierro la pestaña de uno? " + "Su último turno dice que terminó, pero cita un pendiente abierto. " * 4


class EtiquetaTest(f3.Base):
    def setUp(self):
        super().setUp()
        self.si = decisiones.abre(self.pid, LARGO, ["uno"], notificar=False, si_es="Sí, ciérrala", tipo="cierre")
        self.sh = decisiones.abre(self.pid, "¿Qué hago con su suite de fondo?", ["dos"], notificar=False,
                                  shells={"parar": "Pararla y salir", "dejar": "Dejarla viva y salir"})
        self.sin = decisiones.abre(self.pid, "¿Sigo con el lote?", [], notificar=False)

    def linea(self, texto, did):
        filas = [x for x in texto.splitlines() if x.startswith("- %s " % did)]
        self.assertEqual(len(filas), 1, texto)
        return filas[0]

    def comprueba(self, texto):
        self.assertIn("«Sí, ciérrala»", self.linea(texto, self.si["id"]))
        sh = self.linea(texto, self.sh["id"])
        self.assertIn("«Pararla y salir»", sh)
        self.assertIn("«Dejarla viva y salir»", sh)
        self.assertNotIn("«", self.linea(texto, self.sin["id"]))

    def test_the_digest_shows_the_label(self):
        self.comprueba(digest.render(self.pid, mark=False))

    def test_supervisor_md_shows_the_label(self):
        with open(supervisor_md.write(self.pid), encoding="utf-8") as fh:
            md = fh.read()
        self.comprueba(md)
        paso = [x for x in md.splitlines() if x.startswith("Proximo paso:")]
        self.assertEqual(len(paso), 1, md)
        for etiqueta in ("«Sí, ciérrala»", "«Pararla y salir»", "«Dejarla viva y salir»"):
            self.assertIn(etiqueta, paso[0])

    def test_a_label_longer_than_the_digest_line_is_shown_whole(self):
        decisiones.abre(self.pid, LARGO, ["tres"], notificar=False, si_es=LARGA)
        out = digest.render(self.pid, mark=False)
        self.assertIn("«%s»" % LARGA, out)
        self.assertIn("«Sí, ciérrala»", out)

    def test_the_decisions_folded_by_the_digest_keep_their_label(self):
        # codex r2: past 5 decisions the digest folds the rest into one line, which named no label
        for n in range(4):
            decisiones.abre(self.pid, "¿Cierro la pestaña de otro%d?" % n, ["otro%d" % n], notificar=False,
                            si_es="Sí, cierra otro%d" % n)
        out = digest.render(self.pid, mark=False)
        self.assertIn("decisiones más", out)
        for etiqueta in ["Sí, ciérrala", "Pararla y salir", "Dejarla viva y salir"] + ["Sí, cierra otro%d" % n
                                                                                     for n in range(4)]:
            self.assertIn("«%s»" % etiqueta, out)


class RecordatorioTest(f4.Base):
    """The supervisor's Stop reminder of a decision nobody asked yet names its modal label too."""

    def setUp(self):
        super().setUp()
        f4.supervisor_md.mark_supervisor(f4.SUP, f4.PID)
        self.waiter = f4.DigestBudgetTest.start_waiter(self, os.getpid(), f4.SUP)  # only the reminder speaks

    def tearDown(self):
        self.waiter.kill()
        self.waiter.wait()
        self.waiter.stdout.close()
        super().tearDown()

    def test_the_stop_reminder_shows_the_label(self):
        decisiones.abre(f4.PID, "¿Cierro la pestaña de uno?", ["uno"], notificar=False, si_es="Sí, ciérrala")
        out = f4.sigue(on_supervisor.stop_check({}, f4.PID, f4.SUP, grace=0))
        self.assertIn("«Sí, ciérrala»", out)


if __name__ == "__main__":
    unittest.main()

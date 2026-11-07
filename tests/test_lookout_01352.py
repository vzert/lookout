"""0.13.52: an agent whose session leaves a pendiente of its own open is relieved, not closed. 3-tier-memory,
2026-11-07 (supervisor 693f92a0):
- «Proximo paso» (1157eeff) left p-1453f5b773 in the «Como retomar» of its session file
  memory/sessions/2026-10-28-medir-userpromptsubmit-comando.md; its last turn only said «termino aquí», and the
  supervisor closed its tab with --motivo, telling the user «no dejó nada pendiente». The user expected the relief:
  /exit, a new claude, the block pasted, until its thread is empty.
- «claude» (ced4ae52) ended with «🔁 Como retomar: Ninguno — …» and «➕ Opcional — otra sesión … _id: p-c3ac998a95_»;
  `\\b` after the id failed on the «_» of the italics, so lookout read «nada» and closed it. The user's rule: an
  optional block is not relieved on its own, it goes to the modal (ambiguo).
Run: python3 -m unittest tests/test_lookout_01352.py
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_0130 as t130  # noqa: E402
import test_lookout_f3 as f3  # noqa: E402

import registry  # noqa: E402
import relevo  # noqa: E402
import retomar  # noqa: E402

PROPIO = "p-1453f5b773"
CERRADO = "p-f5407da237"
OPCIONAL = "p-c3ac998a95"
# its real «Como retomar» section (shortened)
FICHA = ("---\ntype: session\nsession_id: %s\n---\n# Medido\n\n## Como retomar\n\n```\nRetomamos: medido que "
         "UserPromptSubmit recibe un comando como /cmd args tecleado (%s resuelto).\n\nProximo paso: medir en el cierre "
         "de la sesion que abras con este snippet como argumento de un comando que la ficha queda sellada (%s).\n```\n\n"
         "## Related\n- [[_session-index]]\n")
# claude's real last turn (shortened)
CLAUDE = ("REVISION DEL CIERRE:\n1. ninguno\n\n🔁 Como retomar: Ninguno — el arreglo entro a main como 2.68.1 (PR #87) y "
          "la sesion no deja pendientes.\n\n➕ Opcional — otra sesión, si tienes tiempo:\nProyecto: 3-tier-memory\n"
          "Retomamos: Medir con tools/recall-bench/bloqueos-reales.py (con_decision) que los learning.add traen "
          "--decision _id: %s_\nMotivo: vencido desde 2026-10-07\n" % OPCIONAL)
FIN = "El supervisor confirmó que no me queda nada, así que termino aquí."


def write_row(path, ts):
    return {"type": "assistant", "timestamp": t130.iso(ts),
            "message": {"content": [{"type": "tool_use", "name": "Write", "input": {"file_path": path, "content": "x"}}]}}


class PidTest(unittest.TestCase):
    def test_an_id_in_markdown_italics_is_found(self):
        self.assertEqual(retomar.PID_RE.findall("_id: %s_ y (%s)" % (OPCIONAL, PROPIO)), [OPCIONAL, PROPIO])
        self.assertEqual(retomar.PID_RE.findall("xp-1453f5b773 p-1453f5b773a"), [])

    def test_the_optional_section_alone_does_not_make_a_block(self):
        r = retomar.info(CLAUDE, time.time(), [], [])  # no memory to check it against: the modal
        self.assertEqual(r["estado"], "ambiguo")
        self.assertIn(retomar.OPCIONAL, r["motivo"])


class FichaTest(t130.CierraPestanaTest):
    def memoria(self, pendientes, sid="s1"):
        os.makedirs(os.path.join(self.repo, "memory", "sessions"), exist_ok=True)
        with open(os.path.join(self.repo, "memory", "_pendientes.md"), "w") as fh:
            fh.write(pendientes)
        self.ficha = os.path.join(self.repo, "memory", "sessions", "2026-10-28-medir.md")
        with open(self.ficha, "w") as fh:
            fh.write(FICHA % (sid, CERRADO, PROPIO))
        f3.git(self.repo, "add", "memory")
        f3.git(self.repo, "commit", "-q", "-m", "m")
        f3.git(self.repo, "push", "-q")

    def proximo_paso(self, abierto=True, sid="s1"):
        self.memoria("- [%s] Medir en un cierre real el sello — _id: %s_\n" % (" " if abierto else "x", PROPIO), sid)
        now = time.time()
        self.transcript("s1", [t130.u_text("retoma", now - 300), write_row(self.ficha, now - 200),
                               t130.a_text("Le mandé al supervisor el bloque «Como retomar».", now - 190)])
        self.last(FIN)

    def r(self):
        return retomar.para_agente(self.pid, "s1")

    def test_its_open_pendiente_in_the_session_file_is_vigente(self):
        self.proximo_paso()
        r = self.r()
        self.assertEqual(r["estado"], "vigente", r)
        self.assertEqual(r["pendientes"], [PROPIO])
        self.assertIn("lookout relevo", retomar.describe(r))

    def test_the_motivo_quote_does_not_close_it(self):
        self.proximo_paso()
        ok, msg = self.cierra(FIN)
        self.assertFalse(ok, msg)
        self.assertIn("lookout relevo", msg)
        self.assertIn(PROPIO, msg)
        self.assertFalse(registry.load(self.pid)["agents"]["s1"].get("retirado"))

    def test_the_relief_gets_the_session_files_block(self):
        self.proximo_paso()
        e = registry.load(self.pid)["agents"]["s1"]
        self.assertEqual(relevo.retomar_de(e["session_id"]), "")  # its last turn has none
        self.assertIn(PROPIO, relevo.retomar_de_ficha(self.pid, e))

    def test_the_chain_ends_when_its_pendiente_is_closed(self):
        self.proximo_paso(abierto=False)
        self.assertIsNone(self.r())
        e = registry.load(self.pid)["agents"]["s1"]
        self.assertEqual(relevo.retomar_de_ficha(self.pid, e), "")
        ok, msg = self.cierra(FIN)
        self.assertTrue(ok, msg)

    def test_a_session_file_of_another_session_is_not_its_thread(self):
        self.proximo_paso(sid="deadbeefcafe0001")
        self.assertIsNone(self.r())
        ok, msg = self.cierra(FIN)
        self.assertTrue(ok, msg)

    def test_a_ninguno_session_file_and_a_ninguno_turn_still_close(self):
        self.memoria("- [ ] otro — _id: %s_\n" % PROPIO)
        with open(self.ficha, "w") as fh:
            fh.write("---\nsession_id: s1\n---\n## Como retomar\n\nNinguno — la sesion no deja pendientes.\n")
        f3.git(self.repo, "commit", "-qam", "ninguno")
        f3.git(self.repo, "push", "-q")
        now = time.time()
        self.transcript("s1", [t130.u_text("checkpoint", now - 300), write_row(self.ficha, now - 200)])
        self.last("🔁 Como retomar: Ninguno — la sesion no deja pendientes.")
        self.assertEqual(self.r()["estado"], "nada")
        ok, msg = self.cierra()
        self.assertTrue(ok, msg)

    def test_an_optional_block_goes_to_the_modal(self):
        self.memoria("- [ ] Medir con bloqueos-reales — _id: %s_\n" % OPCIONAL)
        self.last(CLAUDE)
        r = self.r()
        self.assertEqual(r["estado"], "ambiguo", r)
        self.assertIn("modal", retomar.describe(r))
        ok, msg = self.cierra("la sesion no deja pendientes.")
        self.assertFalse(ok, msg)

    def test_an_open_id_on_the_optional_line_itself_goes_to_the_modal(self):
        # adversary r1: «➕ Opcional — otra sesión: seguir con p-…» on one line (claude-vzert c025299c writes it so)
        self.memoria("- [ ] seguir — _id: %s_\n" % OPCIONAL)
        for texto in ("🔁 Como retomar: Ninguno — todo hecho.\n\n➕ Opcional — otra sesión: seguir con %s abierto",
                      "Como retomar: Ninguno\n\n**Opcional** (otra sesión): %s"):
            self.last(texto % OPCIONAL)
            r = self.r()
            self.assertEqual((r["estado"], r["motivo"]), ("ambiguo", retomar.OPCIONAL), texto)
            ok, msg = self.cierra("todo hecho.")
            self.assertFalse(ok, msg)

    def test_optional_ids_closed_close_and_unknown_go_to_the_modal(self):
        self.memoria("- [x] seguir — _id: %s_\n" % OPCIONAL)
        self.last("Como retomar: Ninguno.\n\n➕ Opcional — otra sesión:\nRetomamos: p-cccccccccc")
        r = self.r()  # in no memory file: the user's decision (2026-11-07) is to ask
        self.assertEqual((r["estado"], r["motivo"]), ("ambiguo", retomar.OPCIONAL))
        self.assertFalse(self.cierra()[0])
        self.last("Como retomar: Ninguno.\n\n➕ Opcional — otra sesión:\nRetomamos: %s" % OPCIONAL)
        self.assertEqual(self.r()["estado"], "nada")
        ok, msg = self.cierra()
        self.assertTrue(ok, msg)

    def test_an_id_before_the_optional_section_is_still_ninguno_cita(self):
        self.memoria("- [ ] seguir — _id: %s_\n" % OPCIONAL)
        self.last("Como retomar: Ninguno — falta cerrar %s.\n\n➕ Opcional — otra sesión:\nRetomamos: algo" % OPCIONAL)
        self.assertEqual(self.r()["motivo"], retomar.NINGUNO_CITA)

    def test_a_blocked_pendiente_is_not_relieved(self):
        # codex r1: p-7a1fce0e68 waits for an install elsewhere; relieving it would loop
        self.memoria("- [ ] Medir en claude-vzert — _id: %s_ — _bloqueado: que claude-vzert instale 2.62.11_\n" % PROPIO)
        now = time.time()
        self.transcript("s1", [t130.u_text("retoma", now - 300), write_row(self.ficha, now - 200)])
        self.last(FIN)
        r = self.r()
        self.assertEqual(r["estado"], "ambiguo", r)
        self.assertIn("bloqueados", r["motivo"])
        self.assertFalse(self.cierra(FIN)[0])  # still not closed silently: the modal


if __name__ == "__main__":
    unittest.main()

"""0.13.43 (p-a323ee9360): the supervisa skill says where avisos.jsonl lives and what each line means, so a live test
knows where to look; before, only the CHANGELOG of 0.13.38 said it."""
import glob
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f4 as f4  # noqa: E402

SKILL = os.path.join(f4.ROOT, "plugins", "lookout", "skills", "supervisa")
BIN = os.path.join(f4.ROOT, "plugins", "lookout", "bin")
# herdr_cli.notifica(project_id, "decision", …) and permisos.notify(project_id, "permiso", …)
LLAMADA = re.compile(r"\b(?:notifica|notify)\(\s*[^,()]+(?:\([^()]*\))?\s*,\s*\"([\w-]+)\"")


def lee(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def tipos_del_codigo():
    tipos = set()
    for path in glob.glob(os.path.join(BIN, "*.py")) + [os.path.join(BIN, "lookout")]:
        tipos.update(LLAMADA.findall(lee(path)))
    return tipos


class AvisosJsonlDocumentadoTest(unittest.TestCase):
    def test_the_code_has_the_six_kinds(self):
        # guard for the regex below: if it stops matching, the doc test would pass on an empty set
        self.assertEqual(tipos_del_codigo(),
                         {"decision", "transicion", "bloque", "permiso", "negado", "relevo-supervisor"})

    def test_the_reference_says_where_and_every_kind(self):
        ref = lee(os.path.join(SKILL, "references", "heuristicas.md"))
        self.assertIn("projects/<project_id>/avisos.jsonl", ref)
        self.assertIn("LOOKOUT_STATE_DIR", ref)
        for campo in ("`ts`", "`tipo`", "`titulo`", "`rc`", "`error`"):
            self.assertIn(campo, ref)
        for tipo in tipos_del_codigo():
            self.assertIn("`%s`" % tipo, ref)

    def test_the_skill_points_to_the_reference(self):
        skill = lee(os.path.join(SKILL, "SKILL.md"))
        self.assertIn("avisos.jsonl", skill)
        self.assertIn("references/heuristicas.md", skill)


if __name__ == "__main__":
    unittest.main()

"""0.13.17: `lookout relevo --retomar` takes the PATH of a file, and says so.

Live case (3-tier supervisor, 2026-10-17): the help showed only `--retomar RETOMAR`, the supervisor passed the
«Como retomar» text itself, and lookout died with a FileNotFoundError traceback. Now the help names a file, and a
value that is not a readable file is refused with one line that says what it wants, before anything else runs.
Run: python3 -m unittest tests/test_lookout_01317.py
"""
import os
import subprocess
import sys
import tempfile
import unittest

LOOKOUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "lookout", "bin", "lookout")


def run(*args, env_extra=None):
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, LOOKOUT] + list(args), capture_output=True, text=True, env=env,
                          timeout=30)


class RetomarArchivoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {"LOOKOUT_STATE_DIR": self.tmp.name}

    def tearDown(self):
        self.tmp.cleanup()

    def test_help_says_it_is_a_file(self):
        out = run("relevo", "--help").stdout
        self.assertIn("--retomar ARCHIVO", out)
        self.assertRegex(out, r"(?s)--retomar ARCHIVO\s+ruta de un archivo")

    def test_text_instead_of_a_path_is_refused_without_traceback(self):
        p = run("relevo", "proyecto-x", "agente-x", "--retomar", "Retoma: falta la suite y el push",
                env_extra=self.env)
        salida = p.stdout + p.stderr
        self.assertNotIn("Traceback", salida)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("--retomar espera la ruta de un archivo", salida)
        self.assertIn("«Retoma: falta la suite y el push»", salida)

    def test_a_directory_is_refused_too(self):
        p = run("relevo", "proyecto-x", "agente-x", "--retomar", self.tmp.name, env_extra=self.env)
        salida = p.stdout + p.stderr
        self.assertNotIn("Traceback", salida)
        self.assertIn("--retomar espera la ruta de un archivo", salida)


if __name__ == "__main__":
    unittest.main()

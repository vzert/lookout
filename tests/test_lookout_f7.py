"""Fase 7 tests: herdr version / client-server check before `lookout inicia` takes the lock, and goalspec detection
(without goalspec: warn and go on, `gobierno` says SIN-GOALSPEC, the task prompt drops the adversary rules).

herdr is tests/fixtures/herdr_stub.py; the Claude config (installed plugins) is a temp CLAUDE_CONFIG_DIR.
Run: python3 -m unittest tests/test_lookout_f7.py
"""
import json
import os
import string
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "plugins", "lookout", "bin")
FIX = os.path.join(ROOT, "tests", "fixtures")
STUB = os.path.join(FIX, "herdr_stub.py")
LK = os.path.join(BIN, "lookout")
sys.path.insert(0, BIN)

import gobierno  # noqa: E402
import herdr_cli  # noqa: E402
import lookout_state  # noqa: E402
import registry  # noqa: E402
import lote  # noqa: E402
import requisitos  # noqa: E402

SID = "77777777-1111-2222-3333-444444444444"


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.conf = os.path.join(t, "stub.json")
        self.cfg = os.path.join(t, "claude-config")
        os.makedirs(os.path.join(self.cfg, "plugins"))
        keys = ("LOOKOUT_STATE_DIR", "HERDR_STUB_CONF", "HERDR_STUB_LOG", "CLAUDE_CONFIG_DIR")
        self.old_env = {k: os.environ.get(k) for k in keys}
        os.environ.update({"LOOKOUT_STATE_DIR": os.path.join(t, "state"), "HERDR_STUB_CONF": self.conf,
                           "HERDR_STUB_LOG": os.path.join(t, "calls.log"), "CLAUDE_CONFIG_DIR": self.cfg})
        os.chmod(STUB, 0o755)
        self.old_herdr = herdr_cli.HERDR
        herdr_cli.HERDR = STUB
        self.stub()

    def tearDown(self):
        herdr_cli.HERDR = self.old_herdr
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def stub(self, **conf):
        with open(self.conf, "w") as fh:
            json.dump(conf, fh)

    def install(self, plugins, settings=None):
        with open(os.path.join(self.cfg, "plugins", "installed_plugins.json"), "w") as fh:
            json.dump({"version": 2, "plugins": plugins}, fh)
        if settings is not None:
            with open(os.path.join(self.cfg, "settings.json"), "w") as fh:
                json.dump(settings, fh)

    def status(self, client="0.9.1", server="0.9.1", running=True, compatible=True):
        return {"client": {"version": client}, "server": {"status": "running" if running else "stopped",
                                                          "running": running, "version": server,
                                                          "compatible": compatible, "endpoint_compatible": compatible}}


class HerdrCheckTest(Case):
    def test_tested_version_passes(self):
        ok, problems, notes = requisitos.check_herdr()
        self.assertTrue(ok, problems)
        self.assertEqual(notes, [])

    def test_older_client_is_refused(self):
        self.stub(version="herdr 0.8.4", status=self.status(client="0.8.4", server="0.8.4"))
        ok, problems, _ = requisitos.check_herdr()
        self.assertFalse(ok)
        self.assertIn("0.8.4 es más viejo que el mínimo 0.9.1", " ".join(problems))

    def test_versions_compare_as_numbers_not_text(self):
        self.stub(version="herdr 0.10.0", status=self.status(client="0.10.0", server="0.10.0"))
        self.assertTrue(requisitos.check_herdr()[0])

    def test_missing_binary_says_not_on_path(self):
        herdr_cli.HERDR = os.path.join(self.tmp.name, "no-existe", "herdr")
        ok, problems, _ = requisitos.check_herdr()
        self.assertFalse(ok)
        self.assertIn("no está en el PATH", problems[0])

    def test_incompatible_server_is_refused(self):
        self.stub(status=self.status(server="0.9.0", compatible=False))
        ok, problems, _ = requisitos.check_herdr()
        self.assertFalse(ok)
        self.assertIn("no son compatibles", " ".join(problems))

    def test_old_server_is_refused_even_if_compatible(self):
        self.stub(status=self.status(server="0.9.0"))
        ok, problems, _ = requisitos.check_herdr()
        self.assertFalse(ok)
        self.assertIn("servidor de herdr es 0.9.0", " ".join(problems))

    def test_stopped_server_is_refused(self):
        self.stub(status=self.status(running=False))
        ok, problems, _ = requisitos.check_herdr()
        self.assertFalse(ok)
        self.assertIn("no está corriendo", problems[0])

    def test_unreadable_status_is_refused(self):
        self.stub(status="esto no es un objeto")
        ok, problems, _ = requisitos.check_herdr()
        self.assertFalse(ok)
        self.assertIn("no pude leer `herdr status --json`", problems[0])

    def test_newer_compatible_server_is_a_note(self):
        self.stub(status=self.status(server="0.9.3"))
        ok, _, notes = requisitos.check_herdr()
        self.assertTrue(ok)
        self.assertIn("distintos, pero compatibles", notes[0])


class GoalspecTest(Case):
    def test_absent(self):
        self.assertFalse(requisitos.goalspec_instalado("/x/repo"))
        self.install({"3-tier-memory@m": [{"scope": "user"}]})
        self.assertFalse(requisitos.goalspec_instalado("/x/repo"))

    def test_user_scope_from_any_marketplace(self):
        self.install({"goalspec@otro-marketplace": [{"scope": "user", "version": "1.0.0"}]})
        self.assertTrue(requisitos.goalspec_instalado("/x/repo"))

    def test_project_scope_only_for_its_project(self):
        repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(os.path.join(repo, "sub"))
        self.install({"goalspec@goal-forge": [{"scope": "local", "projectPath": repo}]})
        self.assertTrue(requisitos.goalspec_instalado(repo))
        self.assertTrue(requisitos.goalspec_instalado(os.path.join(repo, "sub")))
        self.assertFalse(requisitos.goalspec_instalado(repo + "-otro"))

    def test_disabled_in_settings_counts_as_absent(self):
        self.install({"goalspec@goal-forge": [{"scope": "user"}]}, {"enabledPlugins": {"goalspec@goal-forge": False}})
        self.assertFalse(requisitos.goalspec_instalado("/x/repo"))

    def test_project_settings_can_enable_it_again(self):
        repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(os.path.join(repo, ".claude"))
        self.install({"goalspec@goal-forge": [{"scope": "user"}]}, {"enabledPlugins": {"goalspec@goal-forge": False}})
        with open(os.path.join(repo, ".claude", "settings.json"), "w") as fh:
            json.dump({"enabledPlugins": {"goalspec@goal-forge": True}}, fh)
        self.assertTrue(requisitos.goalspec_instalado(repo))


class IniciaTest(Case):
    """`lookout inicia` end to end, as the supervisor runs it."""

    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        self.sock = os.path.join(self.tmp.name, "sock")
        open(self.sock, "w").close()

    def inicia(self):
        env = dict(os.environ, HERDR_BIN_PATH=STUB, CLAUDE_CODE_SESSION_ID=SID,
                   CLAUDE_CODE_MESSAGING_SOCKET=self.sock, CLAUDE_PID=str(os.getpid()))
        return subprocess.run([sys.executable, LK, "inicia", self.repo], capture_output=True, text=True, env=env)

    def lock_file(self):
        pid = lookout_state.project_id_for(lookout_state.git_common_dir(self.repo))
        return os.path.join(lookout_state.project_dir(pid), "lock.json")

    def test_old_herdr_refuses_before_the_lock(self):
        self.stub(version="herdr 0.8.0", status=self.status(client="0.8.0", server="0.8.0"))
        r = self.inicia()
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        self.assertIn("NO ARRANCO", r.stdout)
        self.assertIn("mínimo 0.9.1", r.stdout)
        self.assertFalse(os.path.exists(self.lock_file()))

    def test_without_goalspec_it_warns_and_goes_on(self):
        r = self.inicia()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("AVISO: goalspec no está instalado", r.stdout)
        self.assertTrue(os.path.exists(self.lock_file()))

    def test_with_goalspec_no_warning(self):
        self.install({"goalspec@goal-forge": [{"scope": "user"}]})
        r = self.inicia()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("goalspec", r.stdout)


    def test_inicia_retires_a_reused_pane_and_reconciles_the_queue(self):
        # Fase 9 E2/E3 wiring, adversary round 1 (subagent): without these calls in cmd_inicia every test stayed green
        import publica
        pid = lookout_state.project_id_for(lookout_state.git_common_dir(self.repo))
        reg = registry.load(pid)
        reg["agents"] = {"s-viejo": {"session_id": "s-viejo", "nombre": "viejo", "pane_id": "w1:p9", "tarea": "p-1",
                                     "tarea_estado": "terminada", "cwd": self.repo}}
        registry.save(pid, reg)
        publica.save(pid, {"cola": [{"session_id": "s-viejo", "nombre": "viejo", "estado": "turno", "pedida": 1}]})
        self.stub(agent_list=[{"name": "ajeno", "pane_id": "w1:p9", "cwd": "/private/tmp/otro-proyecto",
                               "kind": "claude", "agent_session": {"value": "s-ajeno"}}])
        r = self.inicia()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("s-ajeno", registry.load(pid)["agents"]["s-viejo"].get("retirado_por", ""))
        self.assertIn("Publicación de viejo caducada", r.stdout)
        self.assertNotIn("\nviejo |", r.stdout)  # a retired entry is not listed as an agent


class SinGoalspecTest(unittest.TestCase):
    BREAK = {"veredicto": "break", "unsafe": 0, "linea": "[ADVERSARY-VERDICT: break …]"}

    def test_no_verdict_and_no_goalspec_goes_to_the_user_saying_so(self):
        ok, code, text = gobierno.decide_push({"ultimo": None, "goalspec": False, "modelo_ejecutor": ""})
        self.assertTrue(ok)
        self.assertEqual(code, "SIN-GOALSPEC")
        self.assertIn("NO tuvo revisión independiente", text)

    def test_with_goalspec_a_missing_verdict_still_blocks(self):
        self.assertEqual(gobierno.decide_push({"ultimo": None, "goalspec": True, "modelo_ejecutor": ""})[1],
                         "SIN-VEREDICTO")

    def test_a_break_still_blocks_without_goalspec(self):
        self.assertEqual(gobierno.decide_push({"ultimo": self.BREAK, "goalspec": False, "modelo_ejecutor": ""})[1],
                         "BREAK")

    def test_task_prompt_with_and_without_goalspec(self):
        with open(lote.TEMPLATE, encoding="utf-8") as fh:
            tpl = fh.read()
        names = {f for _, f, _, _ in string.Formatter().parse(tpl) if f}
        base = {n: "<%s>" % n for n in names}
        con = tpl.format(**dict(base, **lote.gobernanza_campos(True)))
        sin = tpl.format(**dict(base, **lote.gobernanza_campos(False)))
        self.assertIn("Usa /goalspec.", con)
        self.assertIn("[ADVERSARY-VERDICT", con)
        self.assertNotIn("goalspec.", sin.replace("goalspec no está instalado", ""))
        self.assertNotIn("[ADVERSARY-VERDICT", sin)
        self.assertIn("goalspec no está instalado", sin)
        for text in (con, sin):  # what does not depend on goalspec stays
            self.assertIn("## Como retomar", text)
            self.assertIn("<publicar>", text)  # Fase 9 G: the publish rule depends on where the agent works (lote.py)


if __name__ == "__main__":
    unittest.main()

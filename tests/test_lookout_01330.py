"""0.13.30: three defects of the live run of 2026-10-18 (p-97fe1fe744), each measured with the installed 0.13.26.

1. `hará:` of a code task on the main checkout is the template's fixed first line. `lookout pendientes` on claude-vzert
   proposed three different pendientes with the same `hará:` («Trabajas en el checkout principal … no uses `git
   stash`, `reset`, `checkout`, `swi…»), cut before it says that the agent does not commit. B4 (0.9.0) exists so the
   user hears from the task file whether the agent commits or only measures.
2. «**[Victor] Avisar a los devs que su siguiente `dev-up` …**» (claude-vzert p-431b775c8a) came out `tipo codigo`
   (edit tools, riesgo normal): `plano()` leaves «Victor] Avisar…» and COMUNICACION is anchored at the start. An owner
   tag in brackets in front of the text is not the text.
3. `lookout lanza` started the first agent of the batch in the workspace it had just created, before its shell was
   ready: herdr answered `agent_pane_busy … is not an available shell`, lookout went on waiting 60 s for a SessionStart
   that could not come and said «¿cargó el plugin?». The start is retried while the pane is not a shell yet; any other
   failed start fails at once with herdr's own error.
Run: python3 -m unittest tests/test_lookout_01330.py
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f2 as f2  # noqa: E402
import test_lookout_f9 as f9  # noqa: E402

import lote  # noqa: E402
import pendientes  # noqa: E402
import registry  # noqa: E402

PID = f9.PID


class HaraTest(unittest.TestCase):
    def setUp(self):
        self.tmp = f9.tempfile.TemporaryDirectory()
        self.old = os.environ.get("LOOKOUT_STATE_DIR")
        os.environ["LOOKOUT_STATE_DIR"] = os.path.join(self.tmp.name, "state")

    def tearDown(self):
        if self.old is None:
            os.environ.pop("LOOKOUT_STATE_DIR", None)
        else:
            os.environ["LOOKOUT_STATE_DIR"] = self.old
        self.tmp.cleanup()

    def hara(self, *textos):
        items = f9.pendientes_md(self.tmp.name, *textos)
        os.makedirs(lote.tareas_dir(PID), exist_ok=True)
        for it in items:
            it["plan"] = lote.plan_for(it, self.tmp.name, "origin/main")
            it["prompt"] = lote.draft_path(PID, it["id"])
            with open(it["prompt"], "w", encoding="utf-8") as fh:
                fh.write(lote.render_tarea(PID, it, it["plan"], items))
        prop = {"archivo": "x", "total": len(items), "tope": 4, "libres": 4, "activos": [], "lote": items,
                "cola": [], "excluidos": []}
        return [l.strip() for l in lote.render_propuesta(prop).splitlines() if l.strip().startswith("hará:")]

    def test_two_code_tasks_on_main_say_different_things(self):
        a, b = self.hara("Crear `docs/hola.md` con una línea", "Arreglar `src/b.py` para que lea UTF-8")
        self.assertNotEqual(a, b)

    def test_a_code_task_on_main_says_it_does_not_commit(self):
        (h,) = self.hara("Crear `docs/adios.md` con una sola línea")
        self.assertIn("sin commit", h)
        self.assertIn("docs/adios.md", h)

    def test_a_read_only_task_keeps_its_own_line(self):
        (h,) = self.hara("**Medir** la latencia del recall")
        self.assertIn("investigación", h)


class EtiquetaTest(unittest.TestCase):
    def test_an_owner_tag_does_not_hide_a_message(self):
        t = "**[Victor] Avisar a los devs que su siguiente `dev-up` reconstruye desde cero y reinstala dependencias.**"
        self.assertEqual(pendientes.clasifica(t)[0], "comunicacion")

    def test_an_owner_tag_does_not_hide_an_investigation(self):
        self.assertEqual(pendientes.clasifica("[Victor] Medir la latencia del recall")[0], "investigacion")

    def test_a_verb_in_brackets_is_still_the_verb(self):
        # codex, publication round (2026-10-18): the 0.13.30 tag strip turned these into code with edit tools
        self.assertEqual(pendientes.clasifica("[Rotar] token de acceso del VPS"), ("credencial", "alto"))
        self.assertEqual(pendientes.clasifica("[Investigar] por qué falla el cron")[0], "investigacion")
        self.assertEqual(pendientes.clasifica("[Fix] Medir la latencia del recall")[0], "codigo")
        self.assertEqual(pendientes.clasifica("[Publicar] la versión 2.0 del paquete")[1], "alto")
        self.assertEqual(pendientes.clasifica("[Deploy] el worker nuevo")[1], "alto")

    def test_a_doubled_bracket_tag_is_a_tag_too(self):
        # codex, delta round on c27c4df: «[[P1]] Medir…» still fell to code with edit tools
        self.assertEqual(pendientes.clasifica("[[P1]] Medir la latencia del recall")[0], "investigacion")
        self.assertEqual(pendientes.clasifica("[[SMSA-12]] Avisar a los devs que cambió el README")[0], "comunicacion")
        self.assertEqual(pendientes.clasifica("[[Rotar]] token de acceso del VPS"), ("credencial", "alto"))
        self.assertEqual(pendientes.clasifica("[P1] [Victor] Medir la latencia del recall")[0], "investigacion")
        self.assertEqual(pendientes.clasifica("[P1] [Rotar] token de acceso del VPS"), ("credencial", "alto"))

    def test_a_link_at_the_start_is_still_read_as_its_text(self):
        self.assertEqual(pendientes.clasifica("[Medir](x.md) la latencia del recall")[0], "investigacion")


class ShellNoListoTest(f2.StubCase):
    def start(self, **conf):
        self.stub(agent_get={"agent_status": "idle", "cwd": self.tmp.name, "agent_session": {"value": self.sid}},
                  agent_read=f2.EMPTY_BOX, **conf)
        self.hook_on_prompt(start_event={"path": self.events, "session_id": self.sid})
        registry.save(self.pid, {"agents": {self.sid: dict(self.entry, worktree=self.tmp.name)}})
        sysfile = os.path.join(self.tmp.name, "s.md")
        open(sysfile, "w").close()
        t0 = time.time()
        ok, msg = lote.arranca(self.pid, self.sid, "w1:p1", self.tmp.name, "ag1", sysfile, "m", True, "tarea:p-1",
                               "trigger", 2, lambda m: None)
        return ok, msg, time.time() - t0

    def test_a_pane_that_is_not_a_shell_yet_is_retried(self):
        ok, msg, _ = self.start(start_error={"code": "agent_pane_busy", "times": 1,
                                             "message": "agent target pane w1:p1 is not an available shell"})
        self.assertTrue(ok, msg)
        self.assertEqual(len(self.calls(["agent", "start"])), 2)

    def test_another_failed_start_fails_at_once_with_herdrs_error(self):
        ok, msg, dt = self.start(start_error={"code": "agent_name_taken", "times": 9,
                                              "message": "agent name ag1 is taken"})
        self.assertFalse(ok)
        self.assertIn("agent_name_taken", msg)
        self.assertNotIn("SessionStart", msg)
        self.assertLess(dt, 10)
        self.assertEqual(len(self.calls(["agent", "start"])), 1)


class RegistroDobleTest(unittest.TestCase):
    """4. The retry of the failed start registered a second entry with the same name (avisar-a-los-devs-dd16b6: one
    `fallida` on the dead pane w25:p1, one `trabajando` on w28:p1), and `registry.find` by name gave the failed one:
    the supervisor could not type the agent's spec approval («envía al pane del primer intento fallido»)."""
    def test_by_name_the_live_retry_wins_over_the_failed_start(self):
        reg = {"agents": {
            "s-old": {"session_id": "s-old", "nombre": "ag", "herdr_name": "ag", "pane_id": "w25:p1",
                      "tarea": "p-1", "tarea_estado": "fallida"},
            "s-new": {"session_id": "s-new", "nombre": "ag", "herdr_name": "ag", "pane_id": "w28:p1",
                      "tarea": "p-1", "tarea_estado": "trabajando"}}}
        self.assertEqual(registry.find(reg, "ag")["session_id"], "s-new")

    def test_the_retry_retires_the_start_that_never_ran(self):
        tmp = f9.tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old = os.environ.get("LOOKOUT_STATE_DIR")
        os.environ["LOOKOUT_STATE_DIR"] = os.path.join(tmp.name, "state")
        self.addCleanup(lambda: os.environ.pop("LOOKOUT_STATE_DIR") if old is None
                        else os.environ.__setitem__("LOOKOUT_STATE_DIR", old))
        repo = os.path.join(tmp.name, "repo")
        os.makedirs(repo)
        it = f9.pendientes_md(tmp.name, "Avisar a los devs de que el README cambió")[0]
        plan = lote.plan_for(it, repo, "origin/main")
        registry.save(PID, {"agents": {
            "s-old": {"session_id": "s-old", "nombre": plan["nombre"], "tarea": it["id"], "tarea_estado": "fallida",
                      "tarea_motivo": "sin SessionStart: el plugin no cargó o Claude no arrancó"},
            "s-otro": {"session_id": "s-otro", "nombre": "otro", "tarea": "p-x", "tarea_estado": "fallida",
                       "tarea_motivo": "sin SessionStart: el plugin no cargó o Claude no arrancó"}}})
        with open(os.path.join(tmp.name, "d.md"), "w") as fh:
            fh.write("tarea")
        saved = (lote.arranca, lote.herdr_cli.run_json, lote.herdr_cli.run, lote.unique_name)
        lote.arranca = lambda *a, **k: (True, "ok")
        lote.herdr_cli.run_json = lambda *a, **k: {"root_pane": {"pane_id": "w9:p1", "tab_id": "w9:t1"}}
        lote.herdr_cli.run = lambda *a, **k: (0, "", "")
        lote.unique_name = lambda base, agents=None: base
        try:
            ok, _ = lote.lanza_uno(PID, os.path.join(repo, ".git"), it, plan, os.path.join(tmp.name, "d.md"), None,
                                   False, lambda m: None, "nota")
        finally:
            lote.arranca, lote.herdr_cli.run_json, lote.herdr_cli.run, lote.unique_name = saved
        self.assertTrue(ok)
        agents = registry.load(PID)["agents"]
        self.assertTrue(agents["s-old"].get("retirado"))
        self.assertFalse(agents["s-otro"].get("retirado"))  # another task's failure is not this retry's

    def test_a_failed_agent_alone_is_still_found(self):
        reg = {"agents": {"s-old": {"session_id": "s-old", "nombre": "ag", "tarea_estado": "fallida"}}}
        self.assertEqual(registry.find(reg, "ag")["session_id"], "s-old")


if __name__ == "__main__":
    unittest.main()

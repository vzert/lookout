"""Unit tests for phase 2 (pendientes.py, deliver.py, lote.py). Run: python3 -m unittest tests/test_lookout_f2.py

herdr is replaced by tests/fixtures/herdr_stub.py (scriptable per test); state goes to a temp folder.
The pendientes fixture is real 3-tier output: tests/escenarios/f2-pendientes.sh run through
journal-emit + journal-compact, then copied (tests/fixtures/pendientes-3t.md).
"""
import json
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "plugins", "lookout", "bin")
FIX = os.path.join(ROOT, "tests", "fixtures")
sys.path.insert(0, BIN)

import deliver  # noqa: E402
import herdr_cli  # noqa: E402
import inputbox  # noqa: E402
import lookout_state  # noqa: E402
import lote  # noqa: E402
import on_state  # noqa: E402
import pendientes  # noqa: E402
import registry  # noqa: E402

PEND = os.path.join(FIX, "pendientes-3t.md")
GUIA_INST, GUIA_USO, SALUDO = "p-9dae4431be", "p-e70e49048e", "p-e2be0f2c64"
FAQ, CHANGELOG, PUBLICAR, LIMPIA, CONTRIB = "p-743ebd0898", "p-990b334946", "p-169277f5bf", "p-a7a3997f1e", "p-d727250462"
EMPTY_BOX = "previo\n\x1b[38;2;153;153;153m❯\x1b[0m \n────────\n  status\n"
DRAFT_BOX = "previo\n❯ estoy escribiendo algo mío\n────────\n"


def ids(rows):
    return [r["id"] for r in rows]


class PendientesTest(unittest.TestCase):
    def setUp(self):
        self.items = pendientes.parse(PEND)

    def test_parses_fields_of_real_3tier_output(self):
        self.assertEqual(len(self.items), 8)
        by = {it["id"]: it for it in self.items}
        self.assertEqual(by[PUBLICAR]["bloqueado"], "que el usuario cree la cuenta del registro")
        self.assertEqual(by[LIMPIA]["prioridad"], "baja")
        self.assertEqual(by[GUIA_INST]["archivos"], ["docs/guia.md"])
        self.assertEqual(by[SALUDO]["origen"], "[[sessions/2026-10-02-semilla]]")
        self.assertEqual(by[CHANGELOG]["texto"], 'Crear `CHANGELOG.md` con una entrada "0.1.0 — versión inicial"')
        self.assertEqual(by[PUBLICAR]["riesgo"], "alto")

    def test_batch_excludes_blocked_and_never_pairs_coupled(self):
        p = pendientes.propose(self.items, 3, hoy="2026-10-02")
        self.assertEqual(ids(p["lote"]), [GUIA_INST, SALUDO, FAQ])
        self.assertEqual(sorted(ids(p["excluidos"])), sorted([PUBLICAR, LIMPIA]))
        cola = {r["id"]: r["motivo"] for r in p["cola"]}
        self.assertIn("acoplado con %s" % GUIA_INST, cola[GUIA_USO])
        self.assertEqual(cola[CHANGELOG], "tope de 3 agentes")
        self.assertFalse(set(ids(p["lote"])) & {PUBLICAR, LIMPIA})

    def test_running_tasks_hold_slots_and_files(self):
        p = pendientes.propose(self.items, 3, activos=[(GUIA_INST, ["docs/guia.md"]), (SALUDO, []), (FAQ, [])],
                               asignados=[GUIA_INST, SALUDO, FAQ], hoy="2026-10-02")
        self.assertEqual(p["libres"], 0)
        self.assertEqual(p["lote"], [])
        # one finishes (SALUDO): the slot frees and the queue moves; the coupled one waits for GUIA_INST
        p = pendientes.propose(self.items, 3, activos=[(GUIA_INST, ["docs/guia.md"]), (FAQ, [])],
                               asignados=[GUIA_INST, SALUDO, FAQ], hoy="2026-10-02")
        self.assertEqual(ids(p["lote"]), [CHANGELOG])
        self.assertIn("acoplado", {r["id"]: r["motivo"] for r in p["cola"]}[GUIA_USO])

    def test_future_review_date_is_excluded(self):
        items = [dict(self.items[0], revisar="2030-01-01", bloqueado="")]
        p = pendientes.propose(items, 3, hoy="2026-10-02")
        self.assertEqual(p["lote"], [])
        self.assertIn("revisar", p["excluidos"][0]["motivo"])

    def test_match_for_h13(self):
        self.assertEqual(sorted(ids(pendientes.match(self.items, ["docs/guia.md"]))), sorted([GUIA_INST, GUIA_USO]))
        self.assertEqual(pendientes.match(self.items, ["nada-de-esto"]), [])

    def test_paths_are_read_mechanically(self):
        self.assertEqual(pendientes.archivos("tocar `a/b.py` y docs/x.md, no `git status` ni https://x.io/a.md"),
                         ["a/b.py", "docs/x.md"])


class InputBoxTextTest(unittest.TestCase):
    def test_box_text(self):
        self.assertEqual(inputbox.read_box(EMPTY_BOX), ("vacia", ""))
        self.assertEqual(inputbox.read_box(DRAFT_BOX), ("borrador", "estoy escribiendo algo mío"))
        wrapped = "❯ Empieza la tarea p-1: está en tus\n  instrucciones de sistema\n────\n"
        self.assertEqual(inputbox.read_box(wrapped), ("borrador", "Empieza la tarea p-1: está en tus instrucciones de sistema"))


class StubCase(unittest.TestCase):
    sid = "11111111-2222-3333-4444-555555555555"
    pid = "pF2"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "state")
        self.conf = os.path.join(self.tmp.name, "stub.json")
        self.log = os.path.join(self.tmp.name, "calls.log")
        self.projects = os.path.join(self.tmp.name, "projects")
        self.old = {k: os.environ.get(k) for k in ("LOOKOUT_STATE_DIR", "HERDR_STUB_CONF", "HERDR_STUB_LOG")}
        os.environ.update({"LOOKOUT_STATE_DIR": self.state, "HERDR_STUB_CONF": self.conf, "HERDR_STUB_LOG": self.log})
        self.old_herdr = herdr_cli.HERDR
        herdr_cli.HERDR = os.path.join(FIX, "herdr_stub.py")
        os.chmod(herdr_cli.HERDR, 0o755)
        self.events = lookout_state.events_path(self.pid)
        os.makedirs(os.path.dirname(self.events), exist_ok=True)
        open(self.events, "a").close()
        self.entry = {"session_id": self.sid, "pane_id": "w1:p1", "cwd": self.tmp.name, "nombre": "ag1"}
        self.stub(agent_get={"agent_status": "idle", "cwd": self.tmp.name,
                             "agent_session": {"value": self.sid}}, agent_read=EMPTY_BOX)

    def tearDown(self):
        herdr_cli.HERDR = self.old_herdr
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def stub(self, **conf):
        with open(self.conf, "w") as fh:
            json.dump(conf, fh)

    def calls(self, verb=None):
        try:
            with open(self.log) as fh:
                rows = [json.loads(l) for l in fh]
        except OSError:
            return []
        return [r for r in rows if verb is None or r[:2] == verb]

    def hook_on_prompt(self, **extra):
        with open(self.conf) as fh:
            conf = json.load(fh)
        conf["prompt_event"] = {"path": self.events, "session_id": self.sid}
        conf.update(extra)
        self.stub(**conf)

    def transcript(self, *user_texts):
        d = os.path.join(self.projects, "-tmp-x")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, self.sid + ".jsonl"), "w") as fh:
            for t in user_texts:
                fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": t}}) + "\n")


class DeliverTest(StubCase):
    text = "Empieza la tarea p-1: está en tus instrucciones de sistema."

    def test_draft_is_never_overwritten(self):
        self.stub(agent_get={"agent_status": "idle", "cwd": self.tmp.name}, agent_read=DRAFT_BOX)
        code, msg = deliver.deliver(self.pid, self.entry, "k1", self.text, 0.2)
        self.assertEqual(code, 4)
        self.assertIn("borrador", msg)
        self.assertEqual(self.calls(["agent", "prompt"]), [])
        self.assertEqual(self.calls(["agent", "send-keys"]), [])

    def test_delivered_once_and_second_call_is_a_noop(self):
        self.hook_on_prompt()
        code, msg = deliver.deliver(self.pid, self.entry, "k1", self.text, 2)
        self.assertEqual(code, 0, msg)
        code, msg = deliver.deliver(self.pid, self.entry, "k1", self.text, 2)
        self.assertEqual(code, 0)
        self.assertIn("ya entregada", msg)
        self.assertEqual(len(self.calls(["agent", "prompt"])), 1)

    def test_timeout_then_reads_before_retry_and_does_not_resend(self):
        # the prompt reaches the agent, but its hook event lands after the confirmation window
        code, msg = deliver.deliver(self.pid, self.entry, "k1", self.text, 0.3)
        self.assertEqual(code, 6, msg)
        lookout_state.append_event(self.pid, {"session_id": self.sid, "event": "working", "prompt": self.text[:120]})
        code, msg = deliver.deliver(self.pid, self.entry, "k1", self.text, 0.3, projects_dir=self.projects)
        self.assertEqual(code, 0, msg)
        self.assertIn("sí llegó", msg)
        self.assertEqual(len(self.calls(["agent", "prompt"])), 1)

    def test_transcript_is_the_second_source(self):
        code, _ = deliver.deliver(self.pid, self.entry, "k1", self.text, 0.2, projects_dir=self.projects)
        self.assertEqual(code, 6)
        self.transcript("otra cosa", self.text)
        code, msg = deliver.deliver(self.pid, self.entry, "k1", self.text, 0.2, projects_dir=self.projects)
        self.assertEqual(code, 0, msg)
        self.assertEqual(len(self.calls(["agent", "prompt"])), 1)

    def test_own_text_stuck_in_box_gets_enter_not_a_second_prompt(self):
        code, _ = deliver.deliver(self.pid, self.entry, "k1", self.text, 0.2, projects_dir=self.projects)
        self.assertEqual(code, 6)
        stuck = "x\n❯ " + self.text[:30] + "\n  " + self.text[30:] + "\n────\n"
        self.stub(agent_get={"agent_status": "idle", "cwd": self.tmp.name}, agent_read=stuck,
                  enter_event={"path": self.events, "session_id": self.sid, "prompt": self.text})
        code, msg = deliver.deliver(self.pid, self.entry, "k1", self.text, 2, projects_dir=self.projects)
        self.assertEqual(code, 0, msg)
        self.assertEqual(len(self.calls(["agent", "prompt"])), 1)
        self.assertEqual(self.calls(["agent", "send-keys"]), [["agent", "send-keys", "w1:p1", "enter"]])

    def test_user_draft_that_starts_like_our_prompt_is_not_submitted(self):
        code, _ = deliver.deliver(self.pid, self.entry, "k1", self.text, 0.2, projects_dir=self.projects)
        self.assertEqual(code, 6)
        prefix = "x\n❯ " + self.text[:20] + "\n────\n"
        self.stub(agent_get={"agent_status": "idle", "cwd": self.tmp.name}, agent_read=prefix)
        code, msg = deliver.deliver(self.pid, self.entry, "k1", self.text, 0.2, projects_dir=self.projects)
        self.assertEqual(code, 4)
        self.assertIn("borrador", msg)
        self.assertEqual(self.calls(["agent", "send-keys"]), [])

    def test_concurrent_deliveries_send_once(self):
        import subprocess
        self.hook_on_prompt()
        registry.save(self.pid, {"agents": {self.sid: self.entry}})
        env = dict(os.environ, HERDR_BIN_PATH=herdr_cli.HERDR)
        cmd = [sys.executable, os.path.join(BIN, "deliver.py"), self.pid, "ag1", "--clave", "k1",
               "--texto", self.text, "--confirmar", "3"]
        procs = [subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, text=True) for _ in range(3)]
        outs = [p.communicate()[0] for p in procs]
        self.assertEqual(sorted(p.returncode for p in procs), [0, 0, 0], outs)
        self.assertEqual(len(self.calls(["agent", "prompt"])), 1)
        self.assertEqual(sum("ya entregada" in o for o in outs), 2)

    def test_escalates_after_three_attempts(self):
        for _ in range(3):
            code, _ = deliver.deliver(self.pid, self.entry, "k1", self.text, 0.1, projects_dir=self.projects)
            self.assertEqual(code, 6)
        code, msg = deliver.deliver(self.pid, self.entry, "k1", self.text, 0.1, projects_dir=self.projects)
        self.assertEqual(code, 5)
        self.assertIn("ESCALAR", msg)
        self.assertEqual(len(self.calls(["agent", "prompt"])), 3)

    def test_busy_or_foreign_pane_is_not_written(self):
        self.stub(agent_get={"agent_status": "working", "cwd": self.tmp.name}, agent_read=EMPTY_BOX)
        self.assertEqual(deliver.deliver(self.pid, self.entry, "k1", self.text, 0.1)[0], 4)
        self.stub(agent_get={"agent_status": "idle", "cwd": self.tmp.name, "agent_session": {"value": "otra"}},
                  agent_read=EMPTY_BOX)
        self.assertEqual(deliver.deliver(self.pid, self.entry, "k2", self.text, 0.1)[0], 4)
        self.assertEqual(self.calls(["agent", "prompt"]), [])

    def test_same_key_with_other_text_is_refused(self):
        self.hook_on_prompt()
        deliver.deliver(self.pid, self.entry, "k1", self.text, 2)
        self.assertEqual(deliver.deliver(self.pid, self.entry, "k1", "otro texto", 2)[0], 4)

    def test_count_in_transcript(self):
        self.transcript(self.text, "hola", "  " + self.text + "\n")
        self.assertEqual(deliver.count_in_transcript(self.sid, self.text, self.projects), 2)


class LoteTest(StubCase):
    def test_trust_dialog_only_for_its_own_worktree(self):
        dialog = "Accessing workspace:\n\n %s\n\n ❯ No, exit\n   Yes, I trust this folder\n"
        self.stub(agent_read=dialog % "/private/tmp/otro-repo")
        self.assertTrue(lote.trust_dialog("w1:p1", self.tmp.name).startswith("otra-ruta"))
        self.assertEqual(self.calls(["agent", "send-keys"]), [])
        self.stub(agent_read=dialog % self.tmp.name)
        self.assertEqual(lote.trust_dialog("w1:p1", self.tmp.name), "aceptado")
        self.assertEqual(self.calls(["agent", "send-keys"]), [["agent", "send-keys", "w1:p1", "down", "enter"]])

    def test_task_prompt_has_every_section_and_no_placeholder(self):
        items = pendientes.parse(PEND)
        it = {i["id"]: i for i in items}[GUIA_INST]
        plan = lote.plan_for(it, "/private/tmp/repo-x", "origin/main")
        self.assertEqual(plan["worktree"], "/private/tmp/repo-x-wt-" + plan["nombre"])
        self.assertEqual(plan["nombre"], "crear-guia-con-una-9dae44")
        self.assertTrue(plan["rama"].startswith("lookout/"))
        text = lote.render_tarea(self.pid, it, plan, items)
        for head in ("Objetivo del proyecto", "Tu tarea: pendiente " + GUIA_INST, "Alcance / no tocar", "Restricciones",
                     "Criterios de aceptación", "Checks a correr", "Memoria relevante", "Reporte"):
            self.assertIn(head, text)
        draft = os.path.join(self.tmp.name, "d.md")
        with open(draft, "w") as fh:
            fh.write(text)
        with open(lote.system_prompt(self.pid, it, draft, "NOTA-DE-PRUEBA")) as fh:
            self.assertTrue(fh.read().endswith("## Nota del supervisor\nNOTA-DE-PRUEBA\n"))
        self.assertIn(GUIA_USO, text)  # the coupled open item is cited as related memory
        self.assertNotIn("{", text.replace("{nombre}", ""))

    def test_investigation_gets_no_worktree_and_read_only_scope(self):
        items = pendientes.parse(PEND)
        it = dict({i["id"]: i for i in items}[FAQ], texto="Investigar por qué falla X", tipo="investigacion")
        plan = lote.plan_for(it, self.tmp.name, "origin/main")
        self.assertTrue(plan["sin_worktree"])
        self.assertEqual(plan["worktree"], self.tmp.name)
        text = lote.render_tarea(self.pid, it, plan, items)
        self.assertIn("modo lectura en el checkout principal", text)
        self.assertNotIn("Tu cambio queda en un commit", text)

    def test_draft_from_an_older_plan_is_rewritten(self):
        items = pendientes.parse(PEND)
        it = {i["id"]: i for i in items}[FAQ]
        plan = lote.plan_for(it, "/private/tmp/repo-x", "origin/main")
        path = os.path.join(self.tmp.name, "d.md")
        with open(path, "w") as fh:
            fh.write(lote.render_tarea(self.pid, it, plan, items))
        self.assertFalse(lote.draft_stale(path, plan))
        self.assertTrue(lote.draft_stale(path, dict(plan, worktree="/private/tmp/repo-x-wt-otro")))
        self.assertTrue(lote.draft_stale(path, dict(plan, rama="lookout/otra")))

    def test_failed_launch_is_retryable_once_its_worktree_is_gone(self):
        gone = os.path.join(self.tmp.name, "no-existe")
        f = {"session_id": "s1", "tarea_estado": "fallida", "worktree": gone}
        self.assertTrue(lote.retryable(f, set()))
        self.assertFalse(lote.retryable(f, {"s1"}))  # still alive in herdr
        self.assertFalse(lote.retryable(dict(f, worktree=self.tmp.name), set()))
        self.assertFalse(lote.retryable(dict(f, tarea_estado="terminada"), set()))
        inv = {"session_id": "s2", "tarea_estado": "fallida", "worktree": self.tmp.name, "sin_worktree": True}
        self.assertTrue(lote.retryable(inv, set()))
        self.assertFalse(lote.retryable(inv, {"s2"}))

    def test_executor_args(self):
        os.environ["LOOKOUT_EXEC_SETTINGS"] = "/x/exec.json"
        try:
            args = lote.exec_args("haiku")
        finally:
            os.environ.pop("LOOKOUT_EXEC_SETTINGS")
        self.assertEqual(args[:2], ["--model", "haiku"])
        self.assertIn("--plugin-dir", args)  # running from this tree, not from an installed cache
        self.assertEqual(args[-2:], ["--settings", "/x/exec.json"])
        args = lote.exec_args(None)
        self.assertEqual(json.loads(args[-1]), {"env": {"LOOKOUT_STATE_DIR": self.state}})
        ro = lote.exec_args(None, solo_lectura=True)
        self.assertEqual(ro[-7:], ["--permission-mode", "plan", "--disallowedTools", "Edit", "Write", "MultiEdit",
                                   "NotebookEdit"])  # last on the command line: the variadic list ends there

    def test_parallel_launches_are_serialised(self):
        import threading
        order = []

        def hold():
            with lote.project_mutex(self.pid):
                order.append("a-in")
                time.sleep(0.3)
                order.append("a-out")
        t = threading.Thread(target=hold)
        t.start()
        time.sleep(0.1)
        with lote.project_mutex(self.pid):
            order.append("b-in")
        t.join()
        self.assertEqual(order, ["a-in", "a-out", "b-in"])

    def test_agent_name_is_unique_in_the_herdr_session(self):
        self.assertEqual(lote.unique_name("a", [{"name": "b"}]), "a")
        self.assertEqual(lote.unique_name("a", [{"name": "a"}, {"name": "a-2"}]), "a-3")

    def test_finished_or_ended_tasks_free_their_slot(self):
        reg = {"agents": {
            "s1": {"session_id": "s1", "nombre": "a", "tarea": GUIA_INST, "tarea_estado": "trabajando"},
            "s2": {"session_id": "s2", "nombre": "b", "tarea": SALUDO, "tarea_estado": "terminada"},
            "s3": {"session_id": "s3", "nombre": "c", "tarea": FAQ, "tarea_estado": "trabajando"}}}
        lookout_state.append_event(self.pid, {"session_id": "s3", "event": "start"})
        lookout_state.append_event(self.pid, {"session_id": "s3", "event": "end"})
        by_id = {i["id"]: i for i in pendientes.parse(PEND)}
        self.assertEqual(lote.activos(self.pid, reg, by_id), [(GUIA_INST, ["docs/guia.md"])])


class SessionStartTest(unittest.TestCase):
    def test_session_start_event(self):
        ev, label, others = on_state.build({"hook_event_name": "SessionStart", "session_id": "s", "source": "startup",
                                            "model": "haiku"}, {"nombre": "a"})
        self.assertEqual((ev["event"], ev["fuente"], label, others), ("start", "startup", None, []))


if __name__ == "__main__":
    unittest.main()

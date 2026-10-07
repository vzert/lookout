"""0.9.0 (Fase 9) tests: what the first real session (claude-vzert, 2026-10-06) taught.

A4: `lookout libera` refuses until the supervisor compared the agent's report with its task; anything that went
outside it reaches the user in a decision before the slot is freed.
B1: the batch classifier reads the item without markdown (`**Medir** …` was typed as code).
B3: git refs (`origin/develop`) are not files and do not couple items.
C2/C3: closes go through `lookout cierra`/`descarta` and the user, also an agent's own /checkpoint-3t (C1 and the
abandoned close are tested with the real journal in test_lookout_f3.CierreTest).
C4: every AskUserQuestion of the supervisor reaches decisiones.json from its hook; the answer is recorded, never a yes.
C5: a prompt the user types straight into an agent's pane is on the supervisor's record as a direct decision.
F4: the task's governance asks the subagent round in every task and the external backend only for terminal ones.
E2: a registry entry whose pane holds another session is retired; an hour that is not today carries its date.
E3: the publication queue is reconciled: a stale holder expires, a pushed `lista` becomes publicada.
E4: the proposal prints one short line per queued item, and `libera` names the exact close command.
E5: "sin eventos hace Ns" gives way to what the check saw when it saw the agent alive after its last hook.
E6: a background `monitor` (an artifact's live updates) does not keep an agent "working".
E7: `ultima` skips code fences; the goal markers come from the whole turn.
E8: a PreToolUse block by another plugin's hook (only in the transcript) reaches the supervisor as such.
E9: a failure's signature keeps digits that are part of a name.
Orden del lote (decisión del usuario, 2026-10-06): prioridad alta primero y, dentro de cada prioridad, el más reciente.
B4: the batch proposal says what each agent will do from its task file («hará:»), in every batch.
B2: types comunicacion (draft, never send) and credencial (high risk, the user acts): no worktree, no commit.
Run: python3 -m unittest tests/test_lookout_f9.py
"""
import argparse
import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "plugins", "lookout", "bin")
sys.path.insert(0, BIN)

import decisiones  # noqa: E402
import lote  # noqa: E402
import pendientes  # noqa: E402
import on_supervisor  # noqa: E402
import registry  # noqa: E402
import supervisor_md  # noqa: E402

PID = "f9proyecto00"
SID = "11111111-2222-3333-4444-555555555555"


def load_cli():
    loader = importlib.machinery.SourceFileLoader("lookout_cli_f9", os.path.join(BIN, "lookout"))
    spec = importlib.util.spec_from_loader("lookout_cli_f9", loader)
    cli = importlib.util.module_from_spec(spec)
    loader.exec_module(cli)
    return cli


class LiberaRevisaAlcanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("LOOKOUT_STATE_DIR")
        os.environ["LOOKOUT_STATE_DIR"] = os.path.join(self.tmp.name, "state")
        reg = registry.load(PID)
        reg.setdefault("agents", {})[SID] = {
            "session_id": SID, "nombre": "rotar-o-confirmar", "tarea": "p-0000000001", "tarea_estado": "lanzada",
            "worktree": self.tmp.name, "sin_worktree": True, "prompt_sistema": "/x/tareas/p-0000000001.md"}
        registry.save(PID, reg)
        self.cli = load_cli()
        self.cli.project = lambda _p: (PID, "/x/.git")
        for name, stub in (("propone", lambda *a, **k: {}), ("render_propuesta", lambda _p: "(propuesta)")):
            self.addCleanup(setattr, lote, name, getattr(lote, name))  # the CLI shares the lote module
            setattr(lote, name, stub)

    def tearDown(self):
        if self.old is None:
            os.environ.pop("LOOKOUT_STATE_DIR", None)
        else:
            os.environ["LOOKOUT_STATE_DIR"] = self.old
        self.tmp.cleanup()

    def libera(self, **kw):
        a = argparse.Namespace(proyecto="/x", agente="rotar-o-confirmar", fallida=False, fuera="", usuario_confirmo="")
        for k, v in kw.items():
            setattr(a, k, v)
        out = io.StringIO()
        with redirect_stdout(out):
            rc = self.cli.cmd_libera(a)
        return rc, out.getvalue(), registry.load(PID)["agents"][SID]

    def test_without_the_review_libera_refuses_and_names_the_task_file(self):
        rc, out, e = self.libera()
        self.assertNotEqual(rc, 0)
        self.assertIn("/x/tareas/p-0000000001.md", out)
        self.assertEqual(e["tarea_estado"], "lanzada")

    def test_something_outside_needs_the_users_yes_first(self):
        fuera = "scp + rm -rf en el home del VPS"
        rc, out, e = self.libera(fuera=fuera)
        self.assertNotEqual(rc, 0)
        self.assertIn("lookout decision --abre", out)
        self.assertEqual(e["tarea_estado"], "lanzada")
        d = decisiones.abre(PID, "rotar-o-confirmar escribió en el VPS", notificar=False)
        decisiones.cierra(PID, d["id"], "sí, ya lo limpié yo", True)
        rc, out, e = self.libera(fuera=fuera, usuario_confirmo=d["id"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(e["tarea_estado"], "terminada")
        self.assertEqual(e["fuera_de_tarea"], fuera)

    def test_nothing_outside_frees_the_slot(self):
        rc, out, e = self.libera(fuera="ninguno")
        self.assertIn("lookout cierra %s rotar-o-confirmar --nota" % PID, out)  # E4: the exact command
        self.assertNotIn("F3", out)
        self.assertEqual(rc, 0, out)
        self.assertEqual(e["tarea_estado"], "terminada")
        self.assertNotIn("fuera_de_tarea", e)

    def test_the_skill_compares_report_and_task_before_libera(self):
        with open(os.path.join(ROOT, "plugins", "lookout", "skills", "pendientes", "SKILL.md"), encoding="utf-8") as fh:
            skill = fh.read()
        self.assertIn("--fuera ninguno", skill)
        self.assertIn("«riesgo asumido»", skill)


def pendientes_md(tmp, *textos):
    path = os.path.join(tmp, "_pendientes.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# Pendientes\n\n## Alta prioridad\n\n")
        for n, t in enumerate(textos):
            fh.write("- [ ] %s — _creado: 2026-10-06_ — _id: p-%010d_\n" % (t, n))
    return pendientes.parse(path)


class ClasificadorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_markdown_does_not_hide_an_investigation(self):
        textos = ["**Medir** si el certificado del VPS sigue vigente", "*Investigar* por qué cae el LB",
                  "__Evaluar__: costo de la réplica", "[Medir](https://x.invalid/doc) la latencia",
                  "`Medir` el uso de disco", "**Medir:** el tiempo de arranque"]
        items = pendientes_md(self.tmp.name, *textos)
        self.assertEqual([i["tipo"] for i in items], ["investigacion"] * len(textos))
        self.assertEqual([i["texto"] for i in items], textos)  # the text is kept as written

    def test_code_items_stay_code(self):
        items = pendientes_md(self.tmp.name, "Arreglar `src/a_b.py` y medir después", "**Mover** snake_case_var")
        self.assertEqual([i["tipo"] for i in items], ["codigo", "codigo"])


    # The six items of the claude-vzert batch (2026-10-06), names, hashes and hosts replaced; all came out «codigo».
    LOTE_VZERT = [
        ("**Hallazgo de historial git: tokens de acceso viejos siguen commiteados en `origin/develop`/`origin/master` "
         "de 8 repos** — el borrado fue limpieza de disco local, no reduce esa exposición", "credencial"),
        ("**Enviar a los 4 devs el cuestionario de valor percibido** (sección 8 del research) y volcar las respuestas "
         "en el research; con ellas decidir umbral/`top` del recall", "comunicacion"),
        ("**Pre-existing que dejó `/review-team` sobre el hook (decidir si se corrigen)**: `is_push` matchea la "
         "MENCIÓN de `git push` en heredocs; `SECRET_PATH` matchea `.environment`", "codigo"),
        ("**Medir la tasa REAL de bloques del recall tras la Fase 7**: volver a correr `usage2.py` sobre los JSONL de "
         "los 4 devs (solo contadores) y comparar con el simulado", "investigacion"),
        ("**Comunicar a los 5 devs que cerrar la ventana de VS Code NO mata el `vscode-server` remoto** — deben usar "
         "`Remote-SSH: Kill VS Code Server on Host`", "comunicacion"),
        ("**Rotar (o confirmar rotación de) el token GitHub de un dev** que estaba en texto plano en `_pendientes.md` "
         "del VPS: commiteado y presente en ≥3 ramas remotas de `origin`", "credencial"),
    ]

    def test_the_claude_vzert_batch_is_classified_right(self):
        items = pendientes_md(self.tmp.name, *[t for t, _ in self.LOTE_VZERT])
        self.assertEqual([i["tipo"] for i in items], [tipo for _, tipo in self.LOTE_VZERT])
        self.assertEqual([i["riesgo"] for i in items if i["tipo"] == "credencial"], ["alto", "alto"])

    def test_realistic_code_items_are_code(self):
        # adversary round 1 (subagent): these came out comunicacion/credencial/investigacion
        textos = ["Enviar a la cola de Redis los mensajes fallidos", "Escribir a la base de datos en lote",
                  "Responder a eventos de teclado en el modal",
                  "Enviar el lote de SMS a los clientes desde el endpoint /api/send",
                  "Responder al usuario cuando el webhook falle (agregar retry)", "Mandar a producción el fix de ayer",
                  "Fix: el token expuesto en el log de debug", "Medir y arreglar la latencia"]
        items = pendientes_md(self.tmp.name, *textos)
        self.assertEqual({i["texto"]: i["tipo"] for i in items}, {t: "codigo" for t in textos})
        mensajes = pendientes_md(self.tmp.name, "Avisar a los devs que el VPS se reinicia el viernes",
                                 "Mandar el correo de bienvenida a los 3 clientes nuevos")
        self.assertEqual([i["tipo"] for i in mensajes], ["comunicacion", "comunicacion"])

    def test_a_token_in_a_code_fix_is_still_code(self):
        items = pendientes_md(self.tmp.name, "Arreglar la validación del token en `src/login.py`",
                              "Avisar en el log cuando falla el parser (`src/p.py`)")
        self.assertEqual([i["tipo"] for i in items], ["codigo", "codigo"])

    def test_git_refs_are_not_files_and_do_not_couple(self):
        items = pendientes_md(self.tmp.name,
                              "Revisar tokens viejos en `origin/develop`/`origin/master` de 8 repos",
                              "Arreglar el build de `origin/develop` en `src/build.sh`",
                              "Limpiar `refs/remotes/upstream/main` y la rama `lookout/arreglar-faq-9dae44`")
        self.assertEqual([i["archivos"] for i in items], [[], ["src/build.sh"], []])
        prop = pendientes.propose(items, 3)
        self.assertEqual(len(prop["lote"]), 3, prop["cola"])

    def test_a_real_dir_is_still_a_file(self):
        items = pendientes_md(self.tmp.name, "Ordenar `docs/guias/` y `plugins/lookout/bin/lote.py`")
        self.assertEqual(items[0]["archivos"], ["docs/guias", "plugins/lookout/bin/lote.py"])

    def test_generic_files_do_not_couple(self):
        items = pendientes_md(self.tmp.name,
                              "**Rotar** el token que quedó en `memory/_pendientes.md`",
                              "Anotar en `memory/_pendientes.md` y `CLAUDE.md` la regla nueva",
                              "Arreglar `src/a.py` (ver `CLAUDE.md`)",
                              "Probar `src/a.py` tras el arreglo")
        prop = pendientes.propose(items, 4)
        lote_ids = {i["id"] for i in prop["lote"]}
        self.assertTrue({items[0]["id"], items[1]["id"]} <= lote_ids)  # the two that share only generic files
        self.assertEqual(len(prop["lote"]), 3)
        self.assertIn("src/a.py", prop["cola"][0]["motivo"])  # a specific file still couples
        prop = pendientes.propose(items[1:2], 3, activos=[("p-otro", ["memory/_pendientes.md"])])
        self.assertEqual(len(prop["lote"]), 1)

    def test_batch_takes_high_priority_first_then_the_newest(self):
        path = os.path.join(self.tmp.name, "_pendientes.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("## Alta prioridad\n\n"
                     "- [ ] Alta reciente — _creado: 2026-10-05_ — _id: p-alta000new_\n"
                     "- [ ] Alta sin fecha — _id: p-alta00nodt_\n"
                     "- [ ] Alta vieja — _creado: 2026-04-20_ — _id: p-alta000old_\n"
                     "- [ ] Alta de hoy — _creado: 2026-10-06_ — _id: p-alta00hoy0_\n"
                     "\n## Media prioridad\n\n"
                     "- [ ] Media de hoy — _creado: 2026-10-06_ — _id: p-media0hoy0_\n")
        prop = pendientes.propose(pendientes.parse(path), 5, hoy="2026-10-06")
        self.assertEqual([i["id"] for i in prop["lote"]],
                         ["p-alta00hoy0", "p-alta000new", "p-alta000old", "p-alta00nodt", "p-media0hoy0"])


class TareaSinCodigoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("LOOKOUT_STATE_DIR")
        os.environ["LOOKOUT_STATE_DIR"] = os.path.join(self.tmp.name, "state")

    def tearDown(self):
        if self.old is None:
            os.environ.pop("LOOKOUT_STATE_DIR", None)
        else:
            os.environ["LOOKOUT_STATE_DIR"] = self.old
        self.tmp.cleanup()

    def render(self, texto):
        it = pendientes_md(self.tmp.name, texto)[0]
        plan = lote.plan_for(it, self.tmp.name, "origin/main")
        return it, plan, lote.render_tarea(PID, it, plan, [it])

    def test_a_message_is_drafted_never_sent_and_has_no_worktree(self):
        it, plan, text = self.render("**Comunicar** a los devs que cierren su sesión remota")
        self.assertEqual(it["tipo"], "comunicacion")
        self.assertTrue(plan["sin_worktree"])
        self.assertIn("NO la envías", text)
        self.assertNotIn("commit de tu rama", text)

    def test_a_draft_from_an_older_template_is_rewritten(self):
        # A 0.8 draft left in the state folder kept its plan's worktree and branch, so it was reused as it was.
        it = pendientes_md(self.tmp.name, "Arreglar `src/a.py`")[0]
        plan = lote.plan_for(it, self.tmp.name, "origin/main")
        viejo = ("## Alcance / no tocar\n- Trabajas SOLO en tu worktree `%s` (rama `%s`).\n"
                 % (plan["worktree"], plan["rama"]))
        path = os.path.join(self.tmp.name, "viejo.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(viejo)
        self.assertTrue(lote.draft_stale(path, plan))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(lote.render_tarea(PID, it, plan, [it]))
        self.assertFalse(lote.draft_stale(path, plan))

    def test_a_credential_is_high_risk_never_copied_and_the_user_acts(self):
        it, plan, text = self.render("**Rotar** el token de la API de pagos")
        self.assertEqual((it["tipo"], it["riesgo"]), ("credencial", "alto"))
        self.assertTrue(plan["sin_worktree"])
        self.assertIn("NO la rotas", text)
        self.assertIn("nunca copias su valor", text)
        self.assertNotIn("commit de tu rama", text)

    def test_the_proposal_says_what_the_task_file_says(self):
        textos = ["**Comunicar** a los devs que cierren su sesión remota", "**Rotar** el token de la API de pagos",
                  "**Medir** la latencia del recall", "Arreglar `src/a.py`"]
        items = pendientes_md(self.tmp.name, *textos)
        os.makedirs(lote.tareas_dir(PID), exist_ok=True)
        for it in items:
            it["plan"] = lote.plan_for(it, self.tmp.name, "origin/main")
            it["prompt"] = lote.draft_path(PID, it["id"])
            with open(it["prompt"], "w", encoding="utf-8") as fh:
                fh.write(lote.render_tarea(PID, it, it["plan"], items))
        prop = {"archivo": "x", "total": 4, "tope": 4, "libres": 4, "activos": [], "lote": items, "cola": [],
                "excluidos": []}
        hara = [l for l in lote.render_propuesta(prop).splitlines() if l.strip().startswith("hará:")]
        self.assertEqual(len(hara), 4)
        self.assertIn("NO la envías", hara[0])
        self.assertIn("NO la rotas", hara[1])
        self.assertIn("investigación", hara[2])
        self.assertIn("SOLO en tu worktree", hara[3])

    def test_the_queue_is_one_short_line_per_item(self):
        largo = "Pendiente con un texto muy largo " + "palabra " * 400
        items = pendientes_md(self.tmp.name, *[largo + str(n) for n in range(30)])
        for it in items:
            it["archivos"] = []
        prop = {"archivo": "x", "total": 30, "tope": 0, "libres": 0, "activos": [], "lote": [],
                "cola": [dict(it, motivo="tope de 3 agentes") for it in items], "excluidos": []}
        out = lote.render_propuesta(prop)
        self.assertLess(len(out), 30 * 200)
        self.assertEqual(sum(1 for l in out.splitlines() if l.startswith("- p-")), 30)

    def test_the_skill_reads_the_tasks_in_every_batch(self):
        with open(os.path.join(ROOT, "plugins", "lookout", "skills", "pendientes", "SKILL.md"), encoding="utf-8") as fh:
            skill = fh.read()
        self.assertIn("en cada lote", skill)
        self.assertIn("hará:", skill)



class CierresTest(unittest.TestCase):
    def test_the_supervisor_never_emits_journal_closes_by_hand(self):
        with open(os.path.join(ROOT, "plugins", "lookout", "skills", "supervisa", "SKILL.md"), encoding="utf-8") as fh:
            skill = fh.read()
        self.assertIn("lookout descarta <project_id> <p-id>", skill)
        self.assertIn("--estado abandoned", skill)
        self.assertIn("**Nunca** corras `journal-emit.py --type pendiente.resolve`", skill)
        self.assertIn("también el que pide un agente que ya corría", skill)

    def test_the_note_to_running_agents_covers_their_checkpoint(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old = os.environ.get("LOOKOUT_STATE_DIR")
        os.environ["LOOKOUT_STATE_DIR"] = tmp.name
        self.addCleanup(lambda: os.environ.__setitem__("LOOKOUT_STATE_DIR", old) if old is not None
                        else os.environ.pop("LOOKOUT_STATE_DIR", None))
        nota = load_cli().render_nota(PID, {"nombre": "snippet"})
        self.assertIn("(aun en /checkpoint-3t)", nota)
        self.assertNotIn("\n", nota)  # one line: a multi-line prompt arrives as <pasted_content>

    def test_descarta_is_a_command(self):
        cli = load_cli()
        out = io.StringIO()
        argv = sys.argv
        sys.argv = ["lookout", "descarta", "--help"]
        try:
            with redirect_stdout(out), self.assertRaises(SystemExit):
                cli.main()
        finally:
            sys.argv = argv
        self.assertIn("--usuario-confirmo", out.getvalue())



class DecisionesDesdeHookTest(unittest.TestCase):
    SUP = SID

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("LOOKOUT_STATE_DIR")
        os.environ["LOOKOUT_STATE_DIR"] = self.tmp.name
        lookout_state = sys.modules["lookout_state"]
        lookout_state.write_json(supervisor_md.sup_marker(self.SUP), {"project_id": PID})

    def tearDown(self):
        if self.old is None:
            os.environ.pop("LOOKOUT_STATE_DIR", None)
        else:
            os.environ["LOOKOUT_STATE_DIR"] = self.old
        self.tmp.cleanup()

    def ask(self, tuid, pregunta, respuesta=None):
        q = {"questions": [{"question": pregunta, "header": "h", "options": []}]}
        on_supervisor.handle({"session_id": self.SUP, "hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion",
                              "tool_use_id": tuid, "tool_input": q})
        if respuesta is not None:
            on_supervisor.handle({"session_id": self.SUP, "hook_event_name": "PostToolUse",
                                  "tool_name": "AskUserQuestion", "tool_use_id": tuid, "tool_input": q,
                                  "tool_response": {"answers": {pregunta: respuesta}}})

    def test_a_question_is_on_record_with_its_answer_but_authorizes_nothing(self):
        self.ask("tu1", "¿Lanzo el lote?", "Lanzar el lote (Recomendado)")
        items = decisiones.load(PID)["items"]
        self.assertEqual(len(items), 1)
        d = items[0]
        self.assertEqual((d["estado"], d["origen"]), ("respondida", "hook"))
        self.assertIn("Lanzar el lote", d["respuesta"])
        self.assertIsNone(d["aprueba"])
        self.assertIsNone(decisiones.respondida(PID, d["id"]))  # only `decision --cierra … --si` authorizes

    def test_a_question_right_after_decision_abre_attaches_to_it(self):
        d1 = decisiones.abre(PID, "¿Cierro p-1?", notificar=False)
        self.ask("tu2", "¿Cierro el pendiente p-1?", "Sí, ciérralo")
        items = decisiones.load(PID)["items"]
        self.assertEqual(len(items), 1)  # no duplicate
        self.assertEqual(items[0]["id"], d1["id"])
        self.assertEqual(items[0]["estado"], "abierta")  # the supervisor closes it with --si/--no
        self.assertIn("Sí, ciérralo", items[0]["respuesta_usuario"])

    def test_an_unanswered_question_stays_open_for_the_user(self):
        self.ask("tu3", "¿Publico la rama?")
        self.assertIn("¿Publico la rama?", decisiones.render(PID))



class DecisionDirectaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("LOOKOUT_STATE_DIR")
        os.environ["LOOKOUT_STATE_DIR"] = self.tmp.name
        self.ls = sys.modules["lookout_state"]
        self.ls.write_marker(SID, {"project_id": PID, "nombre": "handoff-balanceador"})
        import deliver
        deliver.save_record(PID, "tarea:p-1", {"texto": "Empieza tu tarea p-1 (lookout).", "session_id": SID})

    def tearDown(self):
        if self.old is None:
            os.environ.pop("LOOKOUT_STATE_DIR", None)
        else:
            os.environ["LOOKOUT_STATE_DIR"] = self.old
        self.tmp.cleanup()

    def prompt(self, texto):
        import subprocess
        data = json.dumps({"session_id": SID, "hook_event_name": "UserPromptSubmit", "prompt": texto})
        subprocess.run([sys.executable, os.path.join(BIN, "on_state.py")], input=data, text=True, check=True,
                       env=dict(os.environ, HERDR_STUB_CONF=os.path.join(self.tmp.name, "no"), PATH="/usr/bin:/bin"))

    def stop(self, tareas, transcript=None, msg="listo"):
        import subprocess
        data = json.dumps({"session_id": SID, "hook_event_name": "Stop", "last_assistant_message": msg,
                           "background_tasks": tareas, "transcript_path": transcript or ""})
        subprocess.run([sys.executable, os.path.join(BIN, "on_state.py")], input=data, text=True, check=True,
                       env=dict(os.environ, PATH="/usr/bin:/bin"))
        return self.ls.read_events(PID, 0)[0][-1]["event"]

    def test_the_stop_event_carries_the_turns_markers_and_hook_blocks(self):
        # adversary round 1 (subagent): removing these calls from on_state.build left every test green (E7, E8 wiring)
        path = os.path.join(self.tmp.name, "t.jsonl")
        rows = [{"type": "user", "message": {"content": "publica"}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text":
                    "[ADVERSARY-MODEL: claude-sonnet-5-5]\n[ADVERSARY-VERDICT: hold]"}]}},
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "id": "t1",
                                                               "input": {"command": "git push"}}]}},
                {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True, "tool_use_id": "t1",
                    "content": "PreToolUse:Bash hook error: GATE: falta el veredicto"}]}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "Me lo negó un hook."}]}}]
        with open(path, "w") as fh:
            fh.write("\n".join(json.dumps(r) for r in rows) + "\n")
        self.assertEqual(self.stop([], path, "Me lo negó un hook."), "idle")
        ev = self.ls.read_events(PID, 0)[0][-1]
        self.assertIn("[ADVERSARY-VERDICT: hold]", ev.get("marcadores") or [])
        self.assertEqual(ev.get("bloqueos_hook"), [{"tool": "Bash", "motivo": "GATE: falta el veredicto"}])

    def test_an_artifact_monitor_is_not_work(self):
        mon = {"type": "monitor", "status": "running", "description": "live updates for artifact x"}
        self.assertEqual(self.stop([mon]), "idle")
        sh = {"type": "shell", "status": "running", "command": "make"}
        self.assertEqual(self.stop([mon, sh]), "bg_wait")

    def test_a_confirmed_delivery_pasted_again_by_the_user_is_the_users(self):
        import deliver
        import on_state
        deliver.save_record(PID, "tarea:p-1", {"texto": "Empieza tu tarea p-1 (lookout).", "session_id": SID,
                                               "estado": "confirmada"})
        self.assertEqual(on_state.origen_prompt(PID, SID, "Empieza tu tarea p-1 (lookout)."), "usuario")
        deliver.save_record(PID, "tarea:p-1", {"texto": "Empieza tu tarea p-1 (lookout).", "session_id": SID,
                                               "estado": "enviada"})
        self.assertEqual(on_state.origen_prompt(PID, SID, "Empieza tu tarea p-1 (lookout)."), "lookout")

    def test_only_the_users_own_text_is_a_direct_decision(self):
        self.prompt("Empieza tu tarea p-1 (lookout).")                      # lookout's delivery
        self.prompt("/rename handoff-balanceador")                          # lookout types it
        self.prompt('<cross-session-message from="uds:/x">ok</cross-session-message>')  # a peer
        self.prompt("Sí, cambia el balanceador de Cloudflare a producción ya")  # the user, in the pane
        self.prompt("<b>ojo</b>: no publiques todavía")                      # the user too, despite the «<»
        self.prompt('<pasted_content id="x1">\nEmpieza tu tarea p-1 (lookout).\n</pasted_content id="x1">')  # lookout, pasted
        self.prompt('<pasted_content id="x2">\nPlan B: sigue con el balanceador\n</pasted_content id="x2">')  # the user, pasted
        evs = [e for e in self.ls.read_events(PID, 0)[0] if e.get("event") == "working"]
        self.assertEqual([e.get("origen") for e in evs], ["lookout", "lookout", "par", "usuario", "usuario", "lookout",
                                                         "usuario"])
        directas = [x for x in supervisor_md.read_log(PID) if x.get("tipo") == "directa"]
        self.assertEqual(len(directas), 3)
        self.assertIn("balanceador de Cloudflare", directas[0]["texto"])
        with open(supervisor_md.path(PID), encoding="utf-8") as fh:
            self.assertIn("Decisiones directas del usuario en el pane", fh.read())



class GobernanzaTest(unittest.TestCase):
    def test_every_task_gets_the_subagent_round_and_terminal_ones_add_the_external(self):
        g = lote.gobernanza_campos(True)["gobernanza"]
        self.assertIn("Toda tarea lleva la ronda del subagente `goalspec:goal-adversary`", g)
        self.assertIn("`backends=both`", g)
        self.assertIn("Antes de cerrar", g)
        self.assertNotIn("(backend externo de goalspec).", g)  # 0.8.1 equated "another model" with the external one



class RegistroViejoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("LOOKOUT_STATE_DIR")
        os.environ["LOOKOUT_STATE_DIR"] = self.tmp.name

    def tearDown(self):
        if self.old is None:
            os.environ.pop("LOOKOUT_STATE_DIR", None)
        else:
            os.environ["LOOKOUT_STATE_DIR"] = self.old
        self.tmp.cleanup()

    def test_an_entry_whose_pane_is_another_session_is_retired_and_not_shown(self):
        sup = {"nombre": "sup", "address": "uds:/x"}
        viejo = {"session_id": "s-viejo", "pane_id": "w1:p2", "cwd": self.tmp.name, "kind": "claude"}
        nuevo = dict(viejo, session_id="s-nuevo")
        registry.register(PID, sup, [viejo])
        reg = registry.register(PID, sup, [nuevo])
        self.assertIn("otra sesión", reg["agents"]["s-viejo"].get("retirado_por", ""))
        self.assertNotIn("retirado", reg["agents"]["s-nuevo"])
        self.assertEqual(registry.find(reg, "w1:p2")["session_id"], "s-nuevo")
        import digest
        self.assertIn("Agentes (1, +1 terminados)", digest.render(PID, mark=False))

    def test_an_hour_from_another_day_carries_its_date(self):
        import time as _t
        import digest
        ayer = _t.time() - 86400
        self.assertEqual(digest.hhmmss(ayer), _t.strftime("%d-%m %H:%M:%S", _t.localtime(ayer)))
        self.assertEqual(len(digest.hhmmss(_t.time())), 8)
        self.assertIn("-", supervisor_md.hhmm(ayer))


    def test_a_pane_reused_by_another_projects_session_retires_the_entry(self):
        sup = {"nombre": "sup", "address": "uds:/x"}
        registry.register(PID, sup, [{"session_id": "s-viejo", "pane_id": "w1:p7", "cwd": self.tmp.name,
                                      "kind": "claude"}])
        reg = registry.register(PID, sup, [], todos=[{"pane_id": "w1:p7", "agent_session": {"value": "s-ajeno"}}])
        self.assertIn("s-ajeno", reg["agents"]["s-viejo"]["retirado_por"])

    def test_the_digest_reconciles_the_queue(self):
        # adversary round 1 (subagent): removing the call from digest.render left every test green (E3 wiring)
        import publica
        import digest
        reg = registry.load(PID)
        reg["agents"] = {"s-muerto": {"session_id": "s-muerto", "nombre": "workspace-365", "tarea": "p-1",
                                      "tarea_estado": "terminada"}}
        registry.save(PID, reg)
        publica.save(PID, {"cola": [{"session_id": "s-muerto", "nombre": "workspace-365", "estado": "turno",
                                     "pedida": 1}]})
        out = digest.render(PID)
        self.assertIn("Publicación de workspace-365 caducada", out)
        self.assertEqual(publica.load(PID)["cola"][0]["estado"], "caducada")

    def test_the_publication_queue_is_reconciled(self):
        import publica
        reg = registry.load(PID)
        reg["agents"] = {"s-muerto": {"session_id": "s-muerto", "nombre": "workspace-365", "tarea": "p-1",
                                      "tarea_estado": "terminada"},
                         "s-vivo": {"session_id": "s-vivo", "nombre": "otro", "tarea": "p-2", "tarea_estado": "lanzada"}}
        registry.save(PID, reg)
        publica.save(PID, {"cola": [
            {"session_id": "s-muerto", "nombre": "workspace-365", "estado": "turno", "pedida": 1},
            {"session_id": "s-vivo", "nombre": "otro", "estado": "lista", "head": "abc123", "worktree": "/x",
             "rama_remota": "main", "pedida": 2}]})
        out = publica.concilia(PID, remote_tip=lambda wt, b: "abc123")
        cola = {p["nombre"]: p["estado"] for p in publica.load(PID)["cola"]}
        self.assertEqual(cola, {"workspace-365": "caducada", "otro": "publicada"})
        self.assertEqual(len(out), 2)


    def test_an_agent_the_check_saw_alive_is_not_shown_as_silent(self):
        import digest
        import heuristicas
        import time as _t
        ls = sys.modules["lookout_state"]
        reg = registry.load(PID)
        reg["agents"] = {"s-build": {"session_id": "s-build", "nombre": "build", "pane_id": "w1:p3"}}
        registry.save(PID, reg)
        ls.append_event(PID, {"session_id": "s-build", "event": "working", "ts": _t.time() - 700})
        self.assertIn("sin eventos hace", digest.render(PID, mark=False))
        heuristicas.revisa_log(PID, {"session_id": "s-build", "nombre": "build", "decision": "vivo"})
        out = digest.render(PID, mark=False)
        self.assertNotIn("sin eventos hace", out)
        self.assertIn("el revisor lo vio vivo", out)



class UltimaLineaTest(unittest.TestCase):
    def test_a_fence_is_not_the_last_line_and_a_short_one_carries_context(self):
        import on_state
        self.assertEqual(on_state.last_line("Hecho el informe.\n```\nsalida del comando df\n```\n"), "salida del comando df")
        self.assertEqual(on_state.last_line("Resumen del cambio en el VPS\n\nSí."), "Resumen del cambio en el VPS … Sí.")
        self.assertEqual(on_state.last_line("```\n```"), "")

    def test_markers_come_from_the_whole_turn(self):
        import on_state
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t.jsonl")
        rows = [{"type": "user", "message": {"content": "haz la tarea"}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text":
                    "[ADVERSARY-MODEL: claude-sonnet-5-5]\n[ADVERSARY-VERDICT: hold]"}]}},
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "SendMessage", "id": "t1",
                    "input": {"to": "uds:/x", "message": "[COMPLETION-REVIEW: none reason=x]"}}]}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "Listo, reporté."}]}}]
        with open(path, "w") as fh:
            fh.write("\n".join(json.dumps(r) for r in rows) + "\n")
        m = on_state.markers_this_turn(path)
        self.assertEqual([x.split(":")[0] for x in m], ["[ADVERSARY-MODEL", "[ADVERSARY-VERDICT", "[COMPLETION-REVIEW"])


    def test_a_hook_block_is_seen_and_told_apart_from_the_user(self):
        import on_state
        import digest
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t.jsonl")
        # rows as Claude Code wrote them in the E8 spike (coord-test, 2026-10-06)
        rows = [{"type": "user", "message": {"content": "publica"}},
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "id": "t1",
                                                               "input": {"command": "git push"}}]}},
                {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True, "tool_use_id": "t1",
                    "content": "PreToolUse:Bash hook error: GATE-DE-PRUEBA: falta el veredicto del adversario"}]}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "Me lo negaron."}]}}]
        with open(path, "w") as fh:
            fh.write("\n".join(json.dumps(r) for r in rows) + "\n")
        b = on_state.hook_blocks(on_state.turn_rows(path))
        self.assertEqual(b, [{"tool": "Bash", "motivo": "GATE-DE-PRUEBA: falta el veredicto del adversario"}])
        line = digest.describe({"event": "idle", "ts": 0, "session_id": "s", "nombre": "a", "bloqueos_hook": b})
        self.assertIn("bloqueo de un hook en Bash, no del usuario", line)
        with open(os.path.join(ROOT, "plugins", "lookout", "skills", "supervisa", "references", "prompt-tarea.md"),
                  encoding="utf-8") as fh:
            self.assertIn("no es una negación del usuario", fh.read())



class FirmaTest(unittest.TestCase):
    def test_digits_inside_a_name_are_kept_and_loose_numbers_are_not(self):
        import heuristicas
        f = heuristicas.firma
        self.assertNotEqual(f("Bash", "Exit code 127\npython3: command not found"),
                            f("Bash", "Exit code 127\npython: command not found"))
        self.assertIn("sha256sum", f("Bash", "Exit code 1\nsha256sum: WARNING: 1 computed checksum did NOT match"))
        self.assertEqual(f("Bash", "Exit code 1\nError at line 12, col 4"), f("Bash", "Exit code 1\nError at line 99, col 7"))
        self.assertEqual(f("Bash", "Exit code 1\nport 8080 in use"), f("Bash", "Exit code 1\nport 4101 in use"))


if __name__ == "__main__":
    unittest.main()

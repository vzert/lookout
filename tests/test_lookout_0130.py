"""0.13.0: the supervisor's budget follows the model's window (p-3268dded6f), and the agents' life cycle: relief of an
agent with a live «Como retomar», closing the tab of a finished one, and taking in an agent launched by hand
(memory/plans/plan-lookout-altas-cierres-relevos.md, Fases 1-3).
Run: python3 -m unittest tests/test_lookout_0130.py
"""
import json
import os
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f3 as f3  # noqa: E402
import test_lookout_f4 as f4  # noqa: E402

import digest  # noqa: E402
import lock  # noqa: E402
import lookout_state  # noqa: E402
import lote  # noqa: E402
import on_state  # noqa: E402
import registry  # noqa: E402
import relevo  # noqa: E402
import wait_event  # noqa: E402

PID, SUP = f4.PID, f4.SUP


def model_line(model_id, marketing):
    return {"type": "attachment", "attachment": {"type": "model", "identity": {
        "modelId": model_id, "marketingName": marketing, "knowledgeCutoff": "June 2026"}}}


def usage(tokens, mid="m"):
    return {"type": "assistant", "message": {"id": mid, "usage": {
        "input_tokens": 3, "cache_read_input_tokens": tokens - 3, "cache_creation_input_tokens": 0}}}


class BudgetWindowTest(f4.Base):
    def test_a_1m_supervisor_at_382k_is_not_over_budget(self):
        # the 3-tier-memory supervisor of 2026-10-15: Opus 5.5 1M, started at 70k, read «382k de 370k» six times
        self.transcript(SUP, [model_line("claude-opus-5-5[1m]", "Opus 5.5 (1M context)"), usage(70000, "m0")])
        lock.set_contexto_inicial(PID, SUP, 70000)
        self.transcript(SUP, [usage(382000, "m1")])
        line = digest.presupuesto_line(PID, session_id=SUP)
        self.assertNotIn("SUPERADO", line)
        self.assertIn("Contexto: 382k de 800k (80 % de la ventana de 1000k).", line)
        self.transcript(SUP, [usage(801000, "m2")])
        self.assertIn("PRESUPUESTO SUPERADO", digest.presupuesto_line(PID, session_id=SUP))

    def test_the_last_model_line_counts(self):
        # a /model switch from 1M to a 200k model writes a new model line
        self.transcript(SUP, [model_line("claude-opus-5-5[1m]", "Opus 5.5 (1M context)"), usage(70000, "m0"),
                              model_line("claude-sonnet-5-5", "Sonnet 5.5")])
        self.assertEqual(digest.ventana_modelo(SUP), digest.VENTANA_BASE)

    def test_a_200k_supervisor_keeps_the_fixed_limit(self):
        self.transcript(SUP, [model_line("claude-sonnet-5-5", "Sonnet 5.5"), usage(70000, "m0")])
        lock.set_contexto_inicial(PID, SUP, 70000)
        self.assertEqual(digest.presupuesto_line(PID, session_id=SUP), "Contexto: 70k de 370k (arranque 70k + 300k).")

    def test_without_a_model_line_the_old_rule_holds(self):
        self.transcript(SUP, [usage(70000, "m0")])
        lock.set_contexto_inicial(PID, SUP, 70000)
        self.transcript(SUP, [usage(372000, "m1")])
        self.assertIsNone(digest.ventana_modelo(SUP))
        self.assertIn("PRESUPUESTO SUPERADO", digest.presupuesto_line(PID, session_id=SUP))

    def test_lookout_presupuesto_still_overrides(self):
        self.transcript(SUP, [model_line("claude-opus-5-5[1m]", "Opus 5.5 (1M context)"), usage(160000, "m0")])
        os.environ["LOOKOUT_PRESUPUESTO"] = "150000"
        line = digest.presupuesto_line(PID, session_id=SUP)
        self.assertIn("Contexto: 160k de 150k.", line)
        self.assertIn("SUPERADO", line)



# The four blocks of 3-tier-memory (2026-10-15, research C), shortened, without private paths.
MINUTOS = """9. El `Proximo paso` del snippet sigue siendo el siguiente paso real: sí.

🔁 Siguiente sesión — copia y pega:
```
Retomamos: tmp-propio en main (PR #22): pkill de run-tests ya no deja carpetas tmp.*.

Proximo paso: comprobar con el run-tests real si un mutation-check anidado queda huerfano tras pkill (p-01dfac8763).

Antes de actuar, dime en 3 lineas donde quedamos.
```"""
HOOK = """9. ninguno. `p-92aa5de144` es el único del hilo.

🔁 Siguiente sesión — copia y pega:
```
Retomamos: 2.59.0 manda la revision del cierre a un archivo; falta el caso sin git.

Proximo paso: decidir donde escribir el aviso cuando el proyecto no es repo git — p-92aa5de144.
```"""
WORKTREES = """🔁 Siguiente sesión — copia y pega:
```
Retomamos: 2.52.1 publicada.

Proximo paso: medir en Windows los demas scripts del plugin con rutas con acentos — p-34c1ec3f19.
```
🗓️ Recordatorio para el 2026-10-13 — ponlo en tu calendario:

Título: [3-tier-memory] ¿El checkpoint ya solo commitea lo suyo?"""
AGRUPAR = """The extras line suggests `p-88a7cc28c2`.

🔁 Siguiente sesión — copia y pega:
```
Retomamos: 2.57.0 (hilo de pendientes) publicada.

Proximo paso: decidir con Victor si checkpoint-audit avisa (POR-DISENO) (p-3d1c7ab131).

quedan 1 en el hilo: p-3f22a1cba1.
```"""
SIDEBAR = """9. Es el caso 5 (`Ninguno`), porque la sesión no dejó trabajo abierto.

🔁 Como retomar: Ninguno — los tres pendientes de la sesion quedaron cerrados y #19 y #20 estan en main.

➕ Opcional — otra sesión, si tienes tiempo:
Proyecto: 3-tier-memory — /ruta/3-tier-memory
Retomamos: Mirar si las negativas de learning.update aparecen en cuarentenas reales _id: p-ce00d61406_"""
NINGUNO_EN_EL_CUERPO = """## Como retomar
```
Retomamos: limpieza de ramas.
Proximo paso: borrar las 3 ramas viejas; ninguno de los otros pendientes depende de esto (p-0000000001).
```"""


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(ts))


def a_text(text, ts):
    return {"type": "assistant", "timestamp": iso(ts), "message": {"content": [{"type": "text", "text": text}]}}


def u_text(text, ts):
    return {"type": "user", "timestamp": iso(ts), "message": {"content": text}}


class BloqueTest(unittest.TestCase):
    def test_the_four_real_blocks_and_the_finished_one(self):
        import retomar
        for text, pid in ((MINUTOS, "p-01dfac8763"), (HOOK, "p-92aa5de144"), (WORKTREES, "p-34c1ec3f19"),
                          (AGRUPAR, "p-3d1c7ab131")):
            estado, blk = retomar.bloque(text)
            self.assertEqual(estado, "hay", text[:40])
            self.assertIn(pid, blk)
            self.assertTrue(blk.startswith("Retomamos:"), blk[:40])
            self.assertNotIn("Recordatorio", blk)
            self.assertEqual(relevo.extract_retomar(text), blk)
        self.assertEqual(retomar.bloque(SIDEBAR)[0], "nada")
        self.assertEqual(relevo.extract_retomar(SIDEBAR), "")
        # «ninguno» inside the body of a live block is not «nothing to resume»
        self.assertEqual(retomar.bloque(NINGUNO_EN_EL_CUERPO)[0], "hay")
        self.assertEqual(retomar.bloque("Hecho. Siguiente sesión: mañana miro el CI.")[0], "")
        # adversary round 1: «nothing» only when the header says just that, or that and a dash with its reason
        for nada in ("🔁 Como retomar: Ninguno", "Como retomar: Ninguno.", "Siguiente sesión: nada que retomar",
                     "Como retomar: Nada — todo quedó en main."):
            self.assertEqual(retomar.bloque(nada)[0], "nada", nada)
        for no in ("Como retomar: Ninguno, salvo que falta desplegar a producción.",
                   "Siguiente sesión: nada hasta que Víctor responda.",
                   "Como retomar: nada que hacer en el commit, pero falta el push de p-0000000001.",
                   "Como retomar: Ninguno — falta cerrar p-0000000001."):
            self.assertNotEqual(retomar.bloque(no)[0], "nada", no)


class VigenciaTest(f3.Base):
    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.tmp.name, "repo")
        os.makedirs(os.path.join(self.root, "memory"))
        with open(os.path.join(self.root, "memory", "_pendientes.md"), "w") as fh:
            fh.write("# Pendientes\n\n## Alta\n"
                     "- [ ] mutation-check huerfano — _creado: 2026-10-15_ — _id: p-01dfac8763_\n"
                     "- [ ] decidir aviso POR-DISENO — _id: p-3d1c7ab131_\n"
                     "- [ ] hilo — _id: p-3f22a1cba1_\n"
                     "- [ ] Windows acentos — _id: p-34c1ec3f19_\n"
                     "- [x] cerrado — _id: p-92aa5de144_\n")
        self.now = time.time()

    def info(self, sid, text, ts, otros=()):
        import retomar
        self.transcript(sid, [u_text("sigue", ts - 60), a_text(text, ts)])
        t, when = retomar.ultimo_turno(relevo.deliver.transcript_path(sid))
        return retomar.info(t, when, [self.root], [relevo.deliver.transcript_path(o) for o in otros], ahora=self.now)

    def test_vigente_ambiguo_nada(self):
        r = self.info("minutos", MINUTOS, self.now - 600)
        self.assertEqual((r["estado"], r["pendientes"]), ("vigente", ["p-01dfac8763"]))
        # everything it cites is closed: to the user, who usually closes it
        r = self.info("hook", HOOK, self.now - 600)
        self.assertEqual((r["estado"], r["pendientes"]), ("ambiguo", []))  # codex: the closed ones are dropped
        self.assertIn("ya está cerrado", r["motivo"])
        # another agent WORKED on its open p-id after the block: a tool call of its names it
        self.transcript("otro", [{"type": "assistant", "timestamp": iso(self.now - 300), "message": {"content": [
            {"type": "tool_use", "id": "x", "name": "Bash",
             "input": {"command": "bin/journal-emit.py --type pendiente.close --id p-3d1c7ab131"}}]}}])
        r = self.info("agrupar", AGRUPAR, self.now - 600, otros=["otro"])
        self.assertEqual((r["estado"], r["pendientes"]), ("ambiguo", ["p-3d1c7ab131", "p-3f22a1cba1"]))
        self.assertIn("otro agente trabajó p-3d1c7ab131", r["motivo"])
        # worked BEFORE the block: still vigente
        self.transcript("viejo", [{"type": "assistant", "timestamp": iso(self.now - 9000), "message": {"content": [
            {"type": "tool_use", "id": "y", "name": "Bash", "input": {"command": "grep p-01dfac8763 x"}}]}}])
        self.assertEqual(self.info("minutos2", MINUTOS, self.now - 600, otros=["viejo"])["estado"], "vigente")
        self.assertEqual(self.info("sidebar", SIDEBAR, self.now - 600)["estado"], "nada")

    def test_a_mention_is_not_work(self):
        # 0.13.2, 3-tier-memory 2026-10-15: a resume prompt pasted into another session named minutos-github's p-id
        # («Si ese paso es corto, suma en la misma sesion: p-01dfac8763») and its live block became ambiguous
        pegado = "Retomamos ... Si ese paso es corto, suma en la misma sesion: p-01dfac8763 (Baja)"
        self.transcript("otro", [u_text(pegado, self.now - 300),
                                 {"type": "attachment", "timestamp": iso(self.now - 299),
                                  "attachment": {"type": "prompt_snapshot", "text": pegado}},
                                 a_text("Leo p-01dfac8763 en la lista; no es mío.", self.now - 290),
                                 {"type": "user", "timestamp": iso(self.now - 280), "message": {"content": [
                                     {"type": "tool_result", "tool_use_id": "z", "content": "- [ ] x — p-01dfac8763"}]}}])
        self.assertEqual(self.info("minutos", MINUTOS, self.now - 600, otros=["otro"])["estado"], "vigente")

    def test_a_block_of_unknown_time_is_ambiguous(self):
        import retomar
        r = retomar.info(MINUTOS, None, [self.root], [])
        self.assertEqual((r["estado"], r["motivo"]), ("ambiguo", "no sé de cuándo es el bloque"))

    def test_a_subagent_of_another_agent_working_on_it_counts(self):
        self.transcript("otro", [u_text("hola", self.now - 900)])
        d = os.path.join(os.path.dirname(relevo.deliver.transcript_path("otro")), "otro", "subagents")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "agent-a.jsonl"), "w") as fh:
            fh.write(json.dumps({"type": "assistant", "timestamp": iso(self.now - 300), "message": {"content": [
                {"type": "tool_use", "id": "s", "name": "Edit", "input": {"file_path": "x", "new_string": "p-01dfac8763"}}]}}) + "\n")
        r = self.info("minutos", MINUTOS, self.now - 600, otros=["otro"])
        self.assertEqual(r["estado"], "ambiguo")

    def test_reading_or_asking_about_it_is_not_work(self):
        # codex, 0.13.2: a Read, a Grep or a question naming the p-id made a live block ambiguous
        for i, (tool, inp) in enumerate((("Read", {"file_path": "memory/p-01dfac8763.md"}),
                                         ("Grep", {"pattern": "p-01dfac8763"}),
                                         ("AskUserQuestion", {"questions": [{"question": "¿p-01dfac8763?"}]}))):
            self.transcript("lector%d" % i, [{"type": "assistant", "timestamp": iso(self.now - 300), "message": {
                "content": [{"type": "tool_use", "id": "r%d" % i, "name": tool, "input": inp}]}}])
            self.assertEqual(self.info("minutos%d" % i, MINUTOS, self.now - 600, otros=["lector%d" % i])["estado"],
                             "vigente", tool)

    def test_a_pendiente_found_nowhere_is_not_closed(self):
        r = self.info("nuevo", "Como retomar:\n```\nSigue con p-ffffffffff.\n```", self.now - 600)
        self.assertEqual(r["estado"], "ambiguo")
        self.assertIn("no encuentro en la memoria: p-ffffffffff", r["motivo"])

    def test_age_alone_is_not_ambiguous(self):
        # cambio-worktrees: a block of 7 days whose p-id is still open and nobody worked on
        r = self.info("worktrees", WORKTREES, self.now - 7 * 86400)
        self.assertEqual(r["estado"], "vigente")

    def test_closed_ones_are_dropped_and_the_open_ones_relieved(self):
        mixto = "Como retomar:\n```\nSigue con p-92aa5de144 y p-3f22a1cba1.\n```"
        r = self.info("mixto", mixto, self.now - 600)
        self.assertEqual((r["estado"], r["pendientes"]), ("vigente", ["p-3f22a1cba1"]))
        self.assertIn("ya cerrados: p-92aa5de144", r["motivo"])

    def test_only_the_last_turn_counts(self):
        # plan-ciclo: a block of 2026-10-07, then a prompt and a last message without one
        import retomar
        self.transcript("ciclo", [a_text(MINUTOS, self.now - 8 * 86400), u_text("¿sigue vigente?", self.now - 700),
                                  a_text("Mi lectura de esta mañana era vieja. No emito nada y termino aquí.",
                                         self.now - 600)])
        t, ts = retomar.ultimo_turno(relevo.deliver.transcript_path("ciclo"))
        self.assertIsNone(retomar.info(t, ts, [self.root], []))
        self.assertEqual(relevo.retomar_de("ciclo"), "")


class AvisoTest(f4.Base):
    """The supervisor learns of the block: in the Stop of the turn, and when it registers an agent already idle."""

    def wait(self, timeout):
        try:
            return wait_event.wait(lookout_state.events_path(PID), 0, digest.WAKE_TYPES, timeout, digest.pidfile(PID),
                                   digest.cursor_path(PID), linea=False)
        except SystemExit as e:
            return e.code

    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.repo, "memory"))
        with open(os.path.join(self.repo, "memory", "_pendientes.md"), "w") as fh:
            fh.write("- [ ] x — _id: p-01dfac8763_\n- [ ] w — _id: p-34c1ec3f19_\n")

    def stop(self, sid, text, reporto=False):
        now = time.time()
        rows = [u_text("sigue", now - 30), a_text(text, now - 5)]
        if reporto:
            rows[1:1] = [{"type": "assistant", "timestamp": iso(now - 10), "message": {"content": [
                {"type": "tool_use", "id": "tu1", "name": "SendMessage",
                 "input": {"to": "uds:/tmp/sup.sock", "message": "hecho"}}]}},
                {"type": "user", "timestamp": iso(now - 9), "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "tu1", "content": "sent"}]}}]
        self.transcript(sid, rows)
        path = self.deliver.transcript_path(sid)
        marker = {"project_id": PID, "nombre": "uno", "address": "uds:/tmp/sup.sock"}
        ev, _label, _ = on_state.build({"hook_event_name": "Stop", "session_id": sid, "transcript_path": path,
                                        "last_assistant_message": text, "cwd": self.repo}, marker)
        return ev

    def test_stop_carries_retomar_and_it_wakes_even_after_a_report(self):
        self.agent("s1", "uno")
        ev = self.stop("s1", MINUTOS)
        self.assertEqual(ev["retomar"]["estado"], "vigente")
        self.assertIn("dejó un bloque para retomar (p-01dfac8763, vigente)", digest.describe(ev))
        ev = self.stop("s1", SIDEBAR, reporto=True)
        self.assertTrue(ev.get("reporto"), ev)
        self.assertEqual(ev["retomar"]["estado"], "nada")
        lookout_state.append_event(PID, ev)
        self.assertEqual(self.wait(1.5), 0)  # sidebar: «Como retomar: Ninguno» came with its report and must still wake

    def test_a_reported_idle_without_a_block_still_does_not_wake(self):
        self.agent("s1", "uno")
        ev = self.stop("s1", "Listo, te reporté.", reporto=True)
        self.assertNotIn("retomar", ev)
        lookout_state.append_event(PID, ev)
        self.assertEqual(self.wait(1.0), 2)

    def test_registering_an_idle_agent_with_a_block_emits_retomar_once(self):
        import retomar
        now = time.time()
        self.agent("wt", "cambio-worktrees", estado_herdr="idle")
        self.transcript("wt", [u_text("sigue", now - 7 * 86400 - 60), a_text(WORKTREES, now - 7 * 86400)])
        self.agent("ciclo", "plan-ciclo", estado_herdr="idle")
        self.transcript("ciclo", [a_text(MINUTOS, now - 8 * 86400), u_text("¿sigue?", now - 700),
                                  a_text("No emito nada y termino aquí.", now - 600)])
        evs = retomar.al_registrar(PID, ["wt", "ciclo"])
        # 0.13.2: 7 days old, its p-id open and nobody worked on it: vigente (age is no longer a reason)
        self.assertEqual([(e["nombre"], e["retomar"]["estado"]) for e in evs], [("cambio-worktrees", "vigente")])
        self.assertIn("retomar", digest.WAKE_TYPES.split(","))
        self.assertEqual(retomar.al_registrar(PID, ["wt", "ciclo"]), [])  # once per block


class RelevoSinTareaTest(f3.Base):
    def setUp(self):
        super().setUp()
        self.saved = (relevo.herdr_cli.agent_get, relevo.herdr_cli.run, relevo.deliver.read_box,
                      relevo.deliver.wait_event, relevo.lote.arranca, relevo.lote.unique_name)
        self.calls = []
        relevo.herdr_cli.agent_get = lambda pane: {"agent_session": {"value": "s1"}, "agent_status": "idle"}
        relevo.herdr_cli.run = lambda args, **k: (self.calls.append(("run", list(args))), (0, "", ""))[1]
        relevo.deliver.read_box = lambda pane: ("vacia", "")
        relevo.deliver.wait_event = lambda *a, **k: True
        relevo.lote.unique_name = lambda n, agents=None: n + "-2"

        def arranca(pid, sid, pane, wt, nombre, sysfile, modelo, lectura, clave, trigger, confirmar, log,
                    puerto_de=None, esfuerzo="", permisos=""):
            self.calls.append(("arranca", dict(modelo=modelo, esfuerzo=esfuerzo, permisos=permisos, puerto=puerto_de,
                                               clave=clave, trigger=trigger, sysfile=sysfile)))
            relevo.lote.set_estado(pid, sid, "trabajando")
            return True, "ok"
        relevo.lote.arranca = arranca

    def tearDown(self):
        (relevo.herdr_cli.agent_get, relevo.herdr_cli.run, relevo.deliver.read_box, relevo.deliver.wait_event,
         relevo.lote.arranca, relevo.lote.unique_name) = self.saved
        super().tearDown()

    def config_rows(self):
        return [{"type": "attachment", "attachment": {"type": "model", "identity": {
                    "modelId": "claude-opus-5-5[1m]", "marketingName": "Opus 5.5 (1M context)"}}},
                {"type": "permission-mode", "permissionMode": "auto", "sessionId": "s1"},
                dict(a_text("trabajo", time.time() - 100), effort="medium")]

    def test_relief_of_a_discovered_agent_keeps_model_effort_and_mode(self):
        self.agent("s1", nombre="minutos-github", tarea="", modelo="", pane_id="w1A:pJ", cwd="/x", worktree="/x")
        self.agent("s2", nombre="hook-para-checkpoint", tarea="", modelo="", pane_id="w1A:pK", cwd="/x", worktree="/x")
        self.transcript("s1", self.config_rows() + [u_text("sigue", time.time() - 50), a_text(MINUTOS, time.time() - 10)])
        ok, msg = relevo._relevo(self.pid, registry.load(self.pid)["agents"]["s1"], lambda n: "nota", "", None, 1, 1,
                                 lambda m: None)
        self.assertTrue(ok, msg)
        self.assertIn(("run", ["agent", "prompt", "w1A:pJ", "/exit"]), self.calls)
        a = [c[1] for c in self.calls if c[0] == "arranca"][0]
        self.assertEqual((a["modelo"], a["esfuerzo"], a["permisos"]), ("claude-opus-5-5[1m]", "medium", "auto"))
        # no port: it had none; never the checkout's path, which every agent of the checkout shares
        self.assertIsNone(a["puerto"])
        self.assertTrue(a["clave"].startswith("relevo:minutos-github:"), a["clave"])
        self.assertIn("Retoma el trabajo de minutos-github", a["trigger"])
        body = open(a["sysfile"]).read()
        self.assertIn("p-01dfac8763", body)
        self.assertIn("la lanzó el usuario", body)
        # the flags reach `claude`
        args = lote.exec_args(a["modelo"], False, None, a["esfuerzo"], a["permisos"])
        self.assertEqual(args[:6], ["--model", "claude-opus-5-5[1m]", "--effort", "medium", "--permission-mode", "auto"])

    def test_an_agent_with_a_task_also_needs_a_readable_config(self):
        self.agent("s1", nombre="ag", tarea="p-1", pane_id="w1A:pJ")
        self.transcript("s1", [u_text("sigue", time.time() - 50), a_text(MINUTOS, time.time() - 10)])
        ok, msg = relevo._relevo(self.pid, registry.load(self.pid)["agents"]["s1"], lambda n: "nota", "", None, 1, 1,
                                 lambda m: None)
        self.assertFalse(ok)
        self.assertIn("esfuerzo, modo de permisos", msg)

    def test_a_retry_also_needs_a_readable_config(self):
        # a relief whose start failed is retried without /exit: it must not start with empty flags
        self.agent("s1", nombre="ag", tarea="p-1", pane_id="w1A:pJ", tarea_estado="relevo-fallido",
                   relevo_retomar="sigue con x")
        lookout_state.append_event(self.pid, {"session_id": "s1", "event": "end"})
        relevo.herdr_cli.agent_get = lambda pane: {}
        old_live = relevo.lote.live_sessions
        relevo.lote.live_sessions = lambda: set()
        try:
            ok, msg = relevo._relevo(self.pid, registry.load(self.pid)["agents"]["s1"], lambda n: "nota", "", None, 1,
                                     1, lambda m: None)
        finally:
            relevo.lote.live_sessions = old_live
        self.assertFalse(ok)
        self.assertIn("esfuerzo, modo de permisos", msg)
        self.assertFalse([c for c in self.calls if c[0] == "arranca"])

    def test_without_a_readable_config_there_is_no_relief(self):
        self.agent("s1", nombre="minutos-github", tarea="", modelo="", pane_id="w1A:pJ")
        self.transcript("s1", [u_text("sigue", time.time() - 50), a_text(MINUTOS, time.time() - 10)])
        ok, msg = relevo._relevo(self.pid, registry.load(self.pid)["agents"]["s1"], lambda n: "nota", "", None, 1, 1,
                                 lambda m: None)
        self.assertFalse(ok)
        self.assertIn("no leo modelo, esfuerzo, modo de permisos", msg)
        self.assertFalse([c for c in self.calls if c[0] == "run" and "/exit" in c[1]])  # nothing was touched

    def test_exit_without_sessionend_starts_nothing(self):
        self.agent("s1", nombre="minutos-github", tarea="", modelo="", pane_id="w1A:pJ")
        self.transcript("s1", self.config_rows() + [u_text("sigue", time.time() - 50), a_text(MINUTOS, time.time() - 10)])
        relevo.deliver.wait_event = lambda *a, **k: False
        ok, msg = relevo._relevo(self.pid, registry.load(self.pid)["agents"]["s1"], lambda n: "nota", "", None, 1, 1,
                                 lambda m: None)
        self.assertFalse(ok)
        self.assertIn("No arranco otro encima", msg)
        self.assertFalse([c for c in self.calls if c[0] == "arranca"])



class BarridoTest(AvisoTest):
    """0.13.2: a registered agent, quiet since before 0.13.0, whose last turn left a live block gets its `retomar`."""

    def test_a_quiet_agent_with_a_block_is_announced_once(self):
        import alta
        now = time.time()
        self.agent("s1", "hook-para-checkpoint", estado_herdr="working")  # the registry's status is the old one
        self.transcript("s1", [u_text("sigue", now - 60), a_text(MINUTOS, now - 30)])
        herdr = [{"agent_session": {"value": "s1"}, "agent_status": "idle", "pane_id": "w1:p1"},
                 {"agent_session": {"value": "otro"}, "agent_status": "idle", "pane_id": "w1:p2"}]
        evs = alta.barre(PID, herdr)
        self.assertEqual([(e["event"], e["hook"], e["retomar"]["estado"]) for e in evs], [("retomar", "barrido", "vigente")])
        self.assertEqual(alta.barre(PID, herdr), [])  # transcript unchanged: not read again
        os.utime(self.deliver.transcript_path("s1"), (now + 5, now + 5))
        self.assertEqual(alta.barre(PID, herdr), [])  # read again, same block: not announced again

    def test_a_block_its_stop_announced_is_not_swept_again(self):
        # adversary round 1 of 0.13.2: the Stop's idle carried the block, then the sweep announced it again
        import alta
        self.agent("s1", "uno")
        ev = self.stop("s1", MINUTOS)
        lookout_state.append_event(PID, ev)
        self.assertEqual(alta.barre(PID, [{"agent_session": {"value": "s1"}, "agent_status": "idle"}]), [])

    def test_work_of_a_retired_agent_counts(self):
        # codex, 0.13.2: retired sessions were left out of the "worked on it after the block" check
        import retomar
        now = time.time()
        self.agent("s1", "uno")
        self.transcript("s1", [u_text("sigue", now - 700), a_text(MINUTOS, now - 600)])
        self.agent("viejo", "viejo", retirado="2026-10-15T10:00:00")
        self.transcript("viejo", [{"type": "assistant", "timestamp": iso(now - 300), "message": {"content": [
            {"type": "tool_use", "id": "v", "name": "Bash", "input": {"command": "journal-emit --id p-01dfac8763"}}]}}])
        self.assertEqual(retomar.para_agente(PID, "s1")["estado"], "ambiguo")

    def test_a_working_agent_is_not_swept(self):
        import alta
        now = time.time()
        self.agent("s1", "uno", estado_herdr="idle")
        self.transcript("s1", [a_text(MINUTOS, now - 30)])
        self.assertEqual(alta.barre(PID, [{"agent_session": {"value": "s1"}, "agent_status": "working"}]), [])


class RetomarFilaTest(AvisoTest):
    """0.13.3: a block nobody attended stays in «Te necesita», with what to do, in every wake (live 3-tier 2026-10-16:
    agrupar-pendientes sat under «Trabajando» from 01:15 to 03:35Z and the supervisor never opened its modal)."""

    def block(self, sid, nombre, estado, motivo="", ts=None):
        self.agent(sid, nombre)
        ev = {"session_id": sid, "nombre": nombre, "event": "retomar", "hook": "barrido", "ts": ts or time.time(),
              "retomar": {"hay": True, "estado": estado, "pendientes": ["p-3f22a1cba1"], "motivo": motivo,
                          "bloque_id": "b-" + sid}}
        lookout_state.append_event(PID, ev)
        return ev

    def fila(self, out, nombre):
        lines = out.splitlines()
        grupo, fila = None, None
        for x in lines:
            if x.endswith(":") and not x.startswith(" "):
                grupo = x[:-1]
            elif x.startswith("  ") and "(%s)" % nombre in x or x.strip().startswith(nombre + " "):
                fila = (grupo, x)
        return fila

    def test_an_unattended_ambiguo_is_te_necesita_with_its_action_every_wake(self):
        import heuristicas
        self.block("s1", "agrupar-pendientes", "ambiguo", "otro agente trabajó p-3f22a1cba1 después del bloque")
        events, _ = lookout_state.read_events(PID, 0)
        self.assertEqual(heuristicas.grupo(events, "s1", registry.load(PID)["agents"]["s1"]), "te_necesita")
        for _ in range(2):  # the waiter's «sin cambios» must not hide it on the next wake
            out = digest.render(PID, por_waiter=True)
            g, row = self.fila(out, "agrupar-pendientes") or (None, out)
            self.assertEqual(g, "Te necesita", out)
            self.assertIn("modal", row)

    def test_an_in_turn_event_after_the_block_keeps_the_action(self):
        # advisor, 0.13.3: the row read the last event while grupo skips fallo/aprobado/crossrepo
        self.block("s1", "agrupar-pendientes", "ambiguo", "x")
        lookout_state.append_event(PID, {"session_id": "s1", "nombre": "agrupar-pendientes", "event": "aprobado",
                                         "ts": time.time()})
        g, row = self.fila(digest.render(PID), "agrupar-pendientes")
        self.assertEqual(g, "Te necesita")
        self.assertIn("modal", row)

    def test_a_vigente_row_says_relevo(self):
        self.block("s1", "cambio-worktrees", "vigente")
        g, row = self.fila(digest.render(PID), "cambio-worktrees")
        self.assertEqual(g, "Te necesita")
        self.assertIn("lookout relevo", row)

    def test_a_decision_naming_it_attends_it(self):
        import decisiones
        import heuristicas
        self.block("s1", "agrupar-pendientes", "ambiguo", "x", ts=time.time() - 5)
        decisiones.abre(PID, "¿relevo, cierro o lo dejo?", ["agrupar-pendientes"], notificar=False)
        events, _ = lookout_state.read_events(PID, 0)
        self.assertNotEqual(heuristicas.grupo(events, "s1", registry.load(PID)["agents"]["s1"],
                                              decisiones.load(PID)["items"]), "te_necesita")
        self.assertNotEqual(self.fila(digest.render(PID), "agrupar-pendientes")[0], "Te necesita")

    def test_nada_is_not_te_necesita(self):
        import heuristicas
        self.block("s1", "uno", "nada")
        events, _ = lookout_state.read_events(PID, 0)
        self.assertNotEqual(heuristicas.grupo(events, "s1"), "te_necesita")

    def test_the_event_line_says_what_to_do_before_the_motive(self):
        import retomar
        line = retomar.describe({"estado": "ambiguo", "pendientes": ["p-1"], "motivo": "otro agente trabajó p-1 " * 9})
        self.assertIn("modal", digest.clip(line))
        self.assertIn("lookout relevo", retomar.describe({"estado": "vigente", "pendientes": ["p-1"]}))
        self.assertIn("cierra-pestana", retomar.describe({"estado": "ambiguo", "pendientes": [],
                                                          "motivo": retomar.CERRADO + ": p-1"}))

    def test_no_herdr_notification_for_a_block(self):
        import heuristicas
        import herdr_cli
        ev = self.block("s1", "uno", "vigente")
        calls, old = [], herdr_cli.run
        herdr_cli.run = lambda args, **kw: calls.append(args) or (0, "", "")
        try:
            self.assertEqual(heuristicas.transicion(PID, ev)[1], "te_necesita")
        finally:
            herdr_cli.run = old
        self.assertEqual([a for a in calls if a[:1] == ["notification"]], [])

    def test_a_finished_turn_with_nada_still_notifies_listo(self):
        # advisor, 0.13.3: every Stop carries `retomar`; muting all of them dropped «listo para revisar»
        import heuristicas
        import herdr_cli
        self.agent("s1", "uno")
        ev = {"session_id": "s1", "nombre": "uno", "event": "idle", "ts": time.time(),
              "marcadores": ["[COMPLETION-REVIEW ok]"], "retomar": {"hay": False, "estado": "nada", "motivo": "Ninguno"}}
        lookout_state.append_event(PID, ev)
        calls, old = [], herdr_cli.run
        herdr_cli.run = lambda args, **kw: calls.append(args) or (0, "", "")
        try:
            self.assertEqual(heuristicas.transicion(PID, ev)[1:], ("listo", True))
        finally:
            herdr_cli.run = old
        self.assertEqual(len([a for a in calls if a[:1] == ["notification"]]), 1)

    def test_the_close_brake_says_relevo_or_modal(self):
        import retiro
        self.assertIn("lookout relevo", retiro.RELEVO_NO_CIERRE)
        self.assertIn("modal", retiro.RELEVO_NO_CIERRE)


class CierraPestanaTest(f3.Base):
    """Fase 2: each signal and guard stops the close by itself; with everything clean it /exits and closes the tab."""

    def setUp(self):
        super().setUp()
        import retiro
        self.retiro = retiro
        base = os.path.join(self.tmp.name, "g")
        os.makedirs(base)
        f3.git(base, "init", "-q", "--bare", "origin.git")
        self.repo = os.path.join(base, "repo")
        subprocess.run(["git", "clone", "-q", os.path.join(base, "origin.git"), self.repo], check=True,
                       capture_output=True)
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            f3.git(self.repo, "config", k, v)
        with open(os.path.join(self.repo, "a.txt"), "w") as fh:
            fh.write("a\n")
        f3.git(self.repo, "add", "a.txt")
        f3.git(self.repo, "commit", "-q", "-m", "a")
        f3.git(self.repo, "push", "-q", "-u", "origin", "HEAD")
        self.agent("s1", nombre="sidebar", tarea="", pane_id="w1A:pE", tab_id="w1A:tE", cwd=self.repo,
                   worktree=self.repo, pestana="sidebar")
        lookout_state.write_marker("s1", {"project_id": self.pid, "address": "uds:/tmp/sup.sock", "nombre": "sidebar"})
        self.last(SIDEBAR)
        self.calls, self.panes, self.status, self.box, self.ended = [], 1, "idle", "vacia", True
        self.saved = (retiro.herdr_cli.agent_get, retiro.herdr_cli.run, retiro.herdr_cli.tab_get,
                      retiro.deliver.read_box, retiro.deliver.wait_event)
        retiro.herdr_cli.agent_get = lambda pane: {"agent_session": {"value": "s1"}, "agent_status": self.status}
        retiro.herdr_cli.run = lambda args, **k: (self.calls.append(list(args)), (0, "", ""))[1]
        retiro.herdr_cli.tab_get = lambda t: {"pane_count": self.panes}
        retiro.deliver.read_box = lambda pane: (self.box, "")
        retiro.deliver.wait_event = lambda *a, **k: self.ended

    def tearDown(self):
        (self.retiro.herdr_cli.agent_get, self.retiro.herdr_cli.run, self.retiro.herdr_cli.tab_get,
         self.retiro.deliver.read_box, self.retiro.deliver.wait_event) = self.saved
        super().tearDown()

    def last(self, text, extra=()):
        now = time.time()
        self.transcript("s1", [u_text("sigue", now - 30)] + list(extra) + [a_text(text, now - 5)])

    def cierra(self, motivo=""):
        e = registry.load(self.pid)["agents"]["s1"]
        return self.retiro.cierra(self.pid, e, motivo, fin_timeout=1, log=lambda m: None)

    def assert_no(self, frase, motivo=""):
        ok, msg = self.cierra(motivo)
        self.assertFalse(ok, msg)
        self.assertIn(frase, msg)
        self.assertNotIn(["agent", "prompt", "w1A:pE", "/exit"], self.calls)
        self.assertFalse(registry.load(self.pid)["agents"]["s1"].get("retirado"))

    def test_clean_closes_the_tab_and_retires_it(self):
        ok, msg = self.cierra()
        self.assertTrue(ok, msg)
        # 0.13.10: it also reads the screen (the footer's shells, the dialog of /exit)
        self.assertEqual([c for c in self.calls if c[:2] != ["agent", "read"]],
                         [["agent", "prompt", "w1A:pE", "/exit"], ["tab", "close", "w1A:tE"]])
        self.assertIn("Cerré la pestaña de sidebar", msg)
        self.assertTrue(registry.load(self.pid)["agents"]["s1"].get("retirado"))
        self.assertIsNone(lookout_state.read_marker("s1"))

    def test_another_pane_in_the_tab_closes_only_its_pane(self):
        self.panes = 2
        ok, msg = self.cierra()
        self.assertTrue(ok, msg)
        self.assertEqual(self.calls[-1], ["pane", "close", "w1A:pE"])

    def test_screen_alone_or_the_report_alone_is_not_enough(self):
        self.status = "working"
        self.assert_no("herdr lo ve working")

    def test_completion_review_without_a_block_is_not_finished(self):
        self.last("Listo.\n[COMPLETION-REVIEW: adversary model=different (x) backends=both]\n¿Cerrado? Sí")
        self.assert_no("no dice que terminó")

    def test_motivo_must_be_in_its_last_turn(self):
        self.last("Mi lectura de esta mañana era vieja. No emito nada y termino aquí.")
        self.assert_no("no está tal cual", motivo="Terminé todo")
        self.assert_no("no está tal cual", motivo="No  emito nada y termino aquí")  # verbatim: no whitespace folding
        ok, msg = self.cierra(motivo="No emito nada y termino aquí")
        self.assertTrue(ok, msg)

    def test_ninguno_in_the_body_of_a_live_block_is_a_relief(self):
        self.last(NINGUNO_EN_EL_CUERPO)
        self.assert_no("es un relevo")

    def test_uncommitted_change(self):
        with open(os.path.join(self.repo, "a.txt"), "a") as fh:
            fh.write("b\n")
        self.assert_no("cambios sin commit")

    def test_unpushed_commit(self):
        with open(os.path.join(self.repo, "b.txt"), "w") as fh:
            fh.write("b\n")
        f3.git(self.repo, "add", "b.txt")
        f3.git(self.repo, "commit", "-q", "-m", "b")
        self.assert_no("sin dueño vivo conocido")  # no session's commit call covers it: it blocks everyone

    def commit_de(self, sid, subagente=False):
        """A commit in the shared checkout, made inside a Bash call of `sid` (or of a subagent of it)."""
        with open(os.path.join(self.repo, "b.txt"), "w") as fh:
            fh.write("b\n")
        f3.git(self.repo, "add", "b.txt")
        f3.git(self.repo, "commit", "-q", "-m", "b")
        ct = int(subprocess.run(["git", "-C", self.repo, "log", "-1", "--format=%ct"], capture_output=True,
                                text=True).stdout.strip())
        rows = [{"type": "assistant", "timestamp": iso(ct - 1), "message": {"content": [
            {"type": "tool_use", "id": "c1", "name": "Bash", "input": {"command": "git commit -q -F - <<'EOF'"}}]}},
            {"type": "user", "timestamp": iso(ct + 1), "message": {"content": [
                {"type": "tool_result", "tool_use_id": "c1", "content": ""}]}}]
        base = os.path.dirname(self.retiro.deliver.transcript_path("s1"))
        if subagente:
            d = os.path.join(base, sid, "subagents")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "agent-x.jsonl"), "w") as fh:
                fh.write("".join(json.dumps(r) + "\n" for r in rows))
        else:
            self.transcript(sid, rows)

    def test_a_commit_of_another_session_does_not_block_it(self):
        # 0.13.2: 3-tier-memory, 2026-10-15: 6 commits of one session blocked the close of all 8 agents of the checkout
        self.agent("s2", nombre="otro", tarea="", cwd=self.repo, worktree=self.repo)
        self.commit_de("s2")
        ok, msg = self.cierra()
        self.assertTrue(ok, msg)

    def test_a_relieved_owner_passes_its_commits_to_its_successor(self):
        # adversary round 1 of 0.13.2: the owner was the relieved predecessor; its work is the successor's to push
        self.agent("s2", nombre="viejo", tarea="", cwd=self.repo, worktree=self.repo, tarea_estado="relevada",
                   relevada_por="s1")
        self.commit_de("s2")
        self.assert_no("suyo(s) sin subir")

    def test_a_relieved_owner_whose_successor_is_another_agent_does_not_block(self):
        # 3-tier-memory, 2026-10-15: the 6 commits' owner was relieved; its successor owes them, nobody else
        self.agent("s3", nombre="sucesor", tarea="", cwd=self.repo, worktree=self.repo)
        self.agent("s2", nombre="viejo", tarea="", cwd=self.repo, worktree=self.repo, tarea_estado="relevada",
                   relevada_por="s3")
        self.commit_de("s2")
        ok, msg = self.cierra()
        self.assertTrue(ok, msg)

    def test_a_commit_of_a_retired_session_still_blocks(self):
        self.agent("s2", nombre="viejo", tarea="", cwd=self.repo, worktree=self.repo, retirado="2026-10-15T10:00:00")
        self.commit_de("s2")
        self.assert_no("sin dueño vivo conocido")

    def test_a_block_that_cites_only_closed_pendientes_can_be_closed(self):
        # adversary round 2 of 0.13.2: the skill recommends closing it, and the close refused it as a relief
        os.makedirs(os.path.join(self.repo, "memory", "pendientes"))
        with open(os.path.join(self.repo, "memory", "_pendientes.md"), "w") as fh:
            fh.write("- [ ] otro — _id: p-3f22a1cba1_\n")
        with open(os.path.join(self.repo, "memory", "pendientes", "_resueltos.md"), "w") as fh:
            fh.write("- [ ] hecho — _id: p-92aa5de144_\n")  # 3-tier moves a resolved line here verbatim
        f3.git(self.repo, "add", "memory")
        f3.git(self.repo, "commit", "-q", "-m", "m")
        f3.git(self.repo, "push", "-q")
        self.last("Como retomar:\n```\nSigue con p-3f22a1cba1.\n```")  # one still open: a relief, not a close
        self.assert_no("es un relevo")
        # adversary round 3: a p-id found nowhere (a pendiente.add not compacted yet) is not closed
        self.last("Como retomar:\n```\nSigue con p-ffffffffff (recién creado).\n```")
        self.assert_no("es un relevo")
        self.last("Como retomar:\n```\nSigue con p-92aa5de144.\n```")
        ok, msg = self.cierra()
        self.assertTrue(ok, msg)

    def test_a_commit_of_its_own_subagent_blocks_as_its_own(self):
        self.commit_de("s1", subagente=True)
        self.assert_no("suyo(s) sin subir")

    def test_pending_publication(self):
        import publica
        publica.save(self.pid, {"cola": [{"session_id": "s1", "estado": "esperando"}]})
        self.assert_no("publicación esperando")

    def test_open_decision_naming_it(self):
        import decisiones
        old = decisiones.herdr_cli.HERDR
        decisiones.herdr_cli.HERDR = "true"
        try:
            decisiones.abre(self.pid, "¿cierro sidebar?", ["sidebar"])
        finally:
            decisiones.herdr_cli.HERDR = old
        self.assert_no("sigue abierta y lo nombra")

    def test_unanswered_message_then_answered(self):
        import supervisor_md
        now = time.time()
        send = {"type": "assistant", "timestamp": iso(now - 20), "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "SendMessage", "input": {"to": "uds:/tmp/sup.sock", "message": "fin"}}]}}
        self.last(SIDEBAR, extra=[send])
        self.assert_no("no tiene respuesta")
        supervisor_md.log(self.pid, {"tipo": "respuesta", "to": "sidebar", "texto": "recibido", "ts": now})
        ok, msg = self.cierra()
        self.assertTrue(ok, msg)

    def test_a_draft_in_the_box(self):
        self.box = "borrador"
        self.assert_no("su caja tiene borrador")

    def test_a_question_in_its_last_turn(self):
        self.last(SIDEBAR + "\n\n¿Quieres que borre la rama?")
        self.assert_no("pregunta algo")

    def test_a_background_task(self):
        lookout_state.append_event(self.pid, {"event": "bg_wait", "session_id": "s1", "nombre": "sidebar"})
        self.assert_no("tarea de fondo")

    def test_exit_without_sessionend_closes_nothing(self):
        self.ended = False
        ok, msg = self.cierra()
        self.assertFalse(ok)
        self.assertIn("no salió", msg)
        self.assertNotIn(["tab", "close", "w1A:tE"], self.calls)
        self.assertFalse(registry.load(self.pid)["agents"]["s1"].get("retirado"))



class AltaTest(f4.Base):
    """Fase 3: the waiter registers a session of the project launched by hand, once, and wakes the supervisor."""

    def herdr(self, sid, pane, cwd, status="idle"):
        return {"agent": "claude", "agent_session": {"value": sid}, "agent_status": status, "cwd": cwd,
                "pane_id": pane, "tab_id": pane.replace(":p", ":t"), "terminal_id": "t-" + sid, "name": ""}

    def descubre(self, agents):
        import alta
        common = {self.repo: self.repo + "/.git", "/otro": "/otro/.git"}
        return alta.descubre(PID, agents, common_of=lambda cwd: common.get(cwd),
                             tab_of=lambda t: {"label": "Corrección", "pane_count": 1})

    def test_a_new_session_is_registered_once_with_its_marker(self):
        self.agent("s1", "uno")
        agents = [self.herdr("s1", "w1:p1", self.repo), self.herdr("nueva", "w1:p9", self.repo, "done"),
                  self.herdr("ajena", "w1:p8", "/otro"), self.herdr(SUP, "w1:p0", self.repo)]
        evs = self.descubre(agents)
        self.assertEqual([(e["event"], e["session_id"]) for e in evs], [("nuevo", "nueva")])
        self.assertTrue(lookout_state.read_marker("nueva"))  # its hooks report from now on
        self.assertIsNone(lookout_state.read_marker("ajena"))
        self.assertNotIn(SUP, registry.load(PID)["agents"])
        self.assertIn("nuevo", digest.WAKE_TYPES.split(","))
        self.assertIn("lookout entrega", digest.describe(evs[0]))
        self.assertEqual(self.descubre(agents), [])  # once

    def test_retired_or_relieved_sessions_never_come_back(self):
        self.agent("vieja", "vieja", retirado="2026-10-15T10:00:00", tarea_estado="relevada")
        self.assertEqual(self.descubre([self.herdr("vieja", "w1:p3", self.repo)]), [])

    def test_discovery_does_not_drop_a_concurrent_registry_write(self):
        # adversary round 1: descubre rewrote registry.json without the project mutex and lost a «retirado»
        import threading
        import alta
        self.agent("s1", "uno")
        old_git = registry.git_info
        empezo, listo = threading.Event(), threading.Event()

        def lento(cwd):
            empezo.set()
            listo.wait(2)
            return old_git(cwd)
        registry.git_info = lento
        try:
            t = threading.Thread(target=self.descubre, args=([self.herdr("nueva", "w1:p9", self.repo)],))
            t.start()
            empezo.wait(2)

            def retira():
                with lote.project_mutex(PID):
                    reg = registry.load(PID)
                    reg["agents"]["s1"]["retirado"] = "ahora"
                    registry.save(PID, reg)
            r = threading.Thread(target=retira)
            r.start()
            time.sleep(0.2)
            listo.set()
            t.join(5)
            r.join(5)
        finally:
            registry.git_info = old_git
        agents = registry.load(PID)["agents"]
        self.assertEqual(agents["s1"].get("retirado"), "ahora")
        self.assertIn("nueva", agents)

    def test_the_waiter_wakes_with_nuevo(self):
        import alta
        import heuristicas
        saved = (heuristicas.revisa_cada, alta.herdr_cli.agent_list, lookout_state.git_common_dir, alta.herdr_cli.tab_get)
        heuristicas.revisa_cada = lambda: 0.2
        alta.herdr_cli.agent_list = lambda: [self.herdr("nueva", "w1:p9", self.repo, "done")]
        lookout_state.git_common_dir = lambda cwd: self.repo + "/.git" if cwd == self.repo else None
        alta.herdr_cli.tab_get = lambda t: {"label": "x", "pane_count": 1}
        try:
            try:
                rc = wait_event.wait(lookout_state.events_path(PID), 0, digest.WAKE_TYPES, 5, digest.pidfile(PID),
                                     digest.cursor_path(PID), revisa=PID, linea=False)
            except SystemExit as e:
                rc = e.code
        finally:
            (heuristicas.revisa_cada, alta.herdr_cli.agent_list, lookout_state.git_common_dir,
             alta.herdr_cli.tab_get) = saved
        self.assertEqual(rc, 0)
        self.assertIn("nueva", registry.load(PID)["agents"])

    def herdr_falso(self, caja="vacia"):
        """Record the herdr calls of the alta's rename; the input box reads `caja`."""
        import alta
        llamadas = []
        saved = (alta.herdr_cli.run, alta.caja)
        alta.herdr_cli.run = lambda args, timeout=10: (llamadas.append(list(args)) or (0, "", ""))
        alta.caja = lambda pane: caja
        self.addCleanup(lambda: setattr(alta.herdr_cli, "run", saved[0]) or setattr(alta, "caja", saved[1]))
        return llamadas

    def test_a_new_agent_is_renamed_by_the_alta_itself(self):
        # 0.13.1: live 2026-10-15 a supervisor filtered the waiter's digest with its own grep, never ran `lookout
        # entrega`, and the hand-launched session kept its old name. The alta renames it without the supervisor.
        llamadas = self.herdr_falso()
        evs = self.descubre([self.herdr("nueva", "w1:p9", self.repo, "working")])
        nombre = evs[0]["nombre"]
        self.assertIn(["agent", "prompt", "w1:p9", "/rename " + nombre], llamadas)
        self.assertIn(["agent", "rename", "w1:p9", nombre], llamadas)
        self.assertIn(["pane", "rename", "w1:p9", "lookout: " + nombre], llamadas)
        self.assertEqual(evs[0]["renombre"], "hecho")
        self.assertEqual(registry.load(PID)["agents"]["nueva"]["herdr_name"], nombre)
        self.assertIn("renombrado", digest.describe(evs[0]))

    def test_a_refused_rename_is_not_reported_as_done(self):
        import alta
        llamadas = self.herdr_falso()
        alta.herdr_cli.run = lambda args, timeout=10: (llamadas.append(list(args)) or (1, "", "EACCES"))
        evs = self.descubre([self.herdr("nueva", "w1:p9", self.repo)])
        self.assertNotEqual(evs[0]["renombre"], "hecho")
        self.assertIn("sin renombrar", digest.describe(evs[0]))
        self.assertFalse(registry.load(PID)["agents"]["nueva"].get("herdr_name"))

    def test_a_refused_herdr_rename_is_reported_half_done(self):
        # codex round 2: «hecho» while herdr refused the agent, pane or tab rename
        import alta
        for rehusa, falta in ((["agent", "rename"], "agente"), (["pane", "rename"], "pane"), (["tab", "rename"], "pestaña")):
            llamadas = self.herdr_falso()
            alta.herdr_cli.run = lambda args, timeout=10, r=rehusa: (llamadas.append(list(args)) or
                                                                     ((1, "", "EACCES") if args[:2] == r else (0, "", "")))
            sid = "nueva-" + falta
            evs = alta.descubre(PID, [self.herdr(sid, "w1:p" + str(len(falta)), self.repo)],
                                common_of=lambda cwd: self.repo + "/.git" if cwd == self.repo else None,
                                tab_of=lambda t: {"label": "1", "number": 1, "pane_count": 1})
            self.assertEqual(evs[0]["renombre"], "a medias: herdr no renombró " + falta)
            self.assertIn("renombrado a medias", digest.describe(evs[0]))
            e = registry.load(PID)["agents"][sid]
            self.assertEqual(bool(e.get("herdr_name")), falta != "agente")

    def test_the_event_names_the_renamed_default_tab(self):
        import alta
        self.herdr_falso()
        evs = alta.descubre(PID, [self.herdr("nueva", "w1:p9", self.repo)],
                            common_of=lambda cwd: self.repo + "/.git" if cwd == self.repo else None,
                            tab_of=lambda t: {"label": "1", "number": 1, "pane_count": 1})
        nombre = evs[0]["nombre"]
        self.assertEqual(evs[0]["pestana"], nombre)
        self.assertEqual(registry.load(PID)["agents"]["nueva"]["pestana"], nombre)

    def test_the_alta_never_types_over_a_draft(self):
        llamadas = self.herdr_falso(caja="borrador")
        evs = self.descubre([self.herdr("nueva", "w1:p9", self.repo)])
        self.assertFalse([c for c in llamadas if c[:2] == ["agent", "prompt"]])
        self.assertEqual(evs[0]["renombre"], "caja con borrador")
        self.assertIn("sin renombrar", digest.describe(evs[0]))
        self.assertIn("lookout entrega", digest.describe(evs[0]))

    def test_the_checker_thread_ends_with_its_waiter(self):
        # 0.13.1: the in-process waiter of test_the_waiter_wakes_with_nuevo left its checker thread running; once
        # tearDown dropped LOOKOUT_STATE_DIR it wrote projects/pF4/descubre.json in the user's real state.
        import tempfile
        import threading
        import alta
        import heuristicas
        saved = (heuristicas.revisa_cada, alta.herdr_cli.agent_list)
        heuristicas.revisa_cada = lambda: 0.1
        alta.herdr_cli.agent_list = lambda: []
        lookout_state.append_event(PID, {"event": "ask", "session_id": "s1"})
        try:
            try:
                wait_event.wait(lookout_state.events_path(PID), 0, digest.WAKE_TYPES, 5, digest.pidfile(PID),
                                digest.cursor_path(PID), revisa=PID, linea=False)
            except SystemExit:
                pass
            otro = tempfile.mkdtemp()
            self.addCleanup(lambda: __import__("shutil").rmtree(otro, ignore_errors=True))
            os.environ["LOOKOUT_STATE_DIR"] = otro
            time.sleep(0.5)
            self.assertEqual(os.listdir(otro), [])
            self.assertFalse([t for t in threading.enumerate() if t.name == "lookout-revisor"])
        finally:
            heuristicas.revisa_cada, alta.herdr_cli.agent_list = saved

    def test_the_pass_runs_every_n_seconds(self):
        import alta
        os.environ["LOOKOUT_DESCUBRE_CADA"] = "120"
        try:
            self.assertTrue(alta.toca(PID, now=1000.0))
            self.assertFalse(alta.toca(PID, now=1100.0))
            self.assertTrue(alta.toca(PID, now=1121.0))
        finally:
            os.environ.pop("LOOKOUT_DESCUBRE_CADA", None)


if __name__ == "__main__":
    unittest.main()

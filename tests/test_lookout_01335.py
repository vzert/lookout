"""0.13.35 (p-5e02bc8cf9): a decision about the agent still open when its block arrives attends that block.
Live 3-tier 2026-10-19: the supervisor opened d183 at 09:06:45 («¿Tecleo «aprobado» para A? (p-0ccd79fe36)», agentes
cambio-worktrees); the agent's next idle, at 09:07:05, carried a vigente «Como retomar» for that same pendiente; the
user answered at 09:19:47 and the agent worked again at 09:19:53. Only a decision opened after the block counted, so for
those 13 min the digest said «bloque vigente → lookout relevo» of an agent that waited for the user's answer, and from
0.13.32 a longer modal would have sent the user a false «espera su relevo». An answered decision whose answer came
before the block still does not attend it.
Run: python3 -m unittest tests/test_lookout_01335.py
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_01332 as t32  # noqa: E402

import decisiones  # noqa: E402
import heuristicas  # noqa: E402
import lookout_state  # noqa: E402

PID = t32.PID
T = 1792400825.0  # 09:07:05, the idle with the block
BLOQUE = {"estado": "vigente", "pendientes": ["p-0ccd79fe36"], "bloque_id": "0cb54b5a0d12", "motivo": ""}
EV = {"event": "idle", "session_id": "s1", "nombre": "cambio-worktrees", "ts": T, "retomar": dict(BLOQUE)}
ENTRY = {"nombre": "cambio-worktrees"}


def d183(**kw):
    return dict({"id": "d183", "agentes": ["cambio-worktrees"], "desde": T - 20, "estado": "respondida",
                 "hasta": T + 762}, **kw)


class DecisionAbiertaTest(unittest.TestCase):
    def test_a_decision_open_when_the_block_arrives_attends_it(self):
        self.assertIsNone(heuristicas.bloque_sin_atender(EV, ENTRY, [d183()]))

    def test_one_still_open_attends_it(self):
        self.assertIsNone(heuristicas.bloque_sin_atender(EV, ENTRY, [d183(estado="abierta", hasta=None)]))

    def test_one_answered_before_the_block_does_not(self):
        self.assertEqual(heuristicas.bloque_sin_atender(EV, ENTRY, [d183(hasta=T - 5)]), BLOQUE)

    def test_one_about_another_agent_does_not(self):
        self.assertEqual(heuristicas.bloque_sin_atender(EV, ENTRY, [d183(agentes=["otro"])]), BLOQUE)

    def test_one_opened_after_still_attends_it(self):
        self.assertIsNone(heuristicas.bloque_sin_atender(EV, ENTRY, [d183(desde=T + 60, hasta=T + 90)]))


class SinAvisoFalsoTest(t32.Base):
    def test_a_long_modal_open_before_the_block_sends_no_notification(self):
        self.agent("s1", "ag")
        now = time.time()
        decisiones.abre(PID, "¿Tecleo «aprobado» para A? (p-0ccd79fe36)", agentes=["ag"], notificar=False)
        self.ev("idle", time.time() + 0.01, retomar=dict(BLOQUE))
        self.assertEqual(heuristicas.avisa_bloques(PID, now + 31 * 60), [])
        self.assertEqual(self.avisos, [])
        self.assertNotEqual(self.grupo(), "te_necesita")


class ModalEntreIdlesTest(t32.Base):
    """p-625b4aa422 (Sonnet MINOR, 0.13.32): a modal naming the agent opened after the first idle with the block and
    answered before a later idle re-carries it already put the block before the user; avisa_bloques compared it with
    the last idle and announced «ni abrió un modal después», which was false."""

    def test_a_modal_between_the_first_idle_and_a_re_carry_sends_no_notification(self):
        self.agent("s1", "ag")
        now = time.time()
        self.ev("idle", now - 40 * 60, retomar=dict(BLOQUE))
        did = decisiones.abre(PID, "¿relevo ya o espera al merge?", agentes=["ag"], notificar=False)
        d = decisiones.load(PID)
        for it in d["items"]:
            it.update(desde=now - 35 * 60, estado="respondida", hasta=now - 34 * 60, respuesta="espera")
        lookout_state.write_json(decisiones.path(PID), d)
        self.ev("working", now - 10 * 60)
        self.ev("idle", now - 9 * 60, retomar=dict(BLOQUE))   # the same bloque_id, after the answer
        self.assertEqual(heuristicas.avisa_bloques(PID, now), [], did)
        self.assertEqual(self.avisos, [])

    def test_a_modal_answered_before_the_first_idle_still_lets_it_notify(self):
        self.agent("s1", "ag")
        now = time.time()
        decisiones.abre(PID, "otra cosa", agentes=["ag"], notificar=False)
        d = decisiones.load(PID)
        for it in d["items"]:
            it.update(desde=now - 50 * 60, estado="respondida", hasta=now - 45 * 60)
        lookout_state.write_json(decisiones.path(PID), d)
        self.ev("idle", now - 40 * 60, retomar=dict(BLOQUE))
        self.assertEqual(len(heuristicas.avisa_bloques(PID, now)), 1)


class TranscriptUtf8RotoTest(unittest.TestCase):
    """p-da8bbd7dc2 (Sonnet MINOR, 0.13.15): one line of broken UTF-8 in a transcript made user_texts raise
    UnicodeDecodeError, and since 0.13.15 that read runs on every first send: the delivery failed instead of delivering.
    The broken line is read with replacement characters; the other lines still count."""

    def test_a_broken_byte_does_not_stop_the_read(self):
        import json
        import tempfile
        import deliver
        with tempfile.NamedTemporaryFile("wb", suffix=".jsonl", delete=False) as fh:
            fh.write((json.dumps({"type": "user", "message": {"content": "antes"}}) + "\n").encode())
            fh.write(b'{"type": "user", "message": {"content": "roto \xff\xfe aqu\xc3"}}\n')
            fh.write((json.dumps({"type": "user", "message": {"content": "después"}}) + "\n").encode())
        try:
            textos = deliver.user_texts(fh.name)
        finally:
            os.unlink(fh.name)
        self.assertEqual(textos[0], "antes")
        self.assertEqual(textos[-1], "después")
        self.assertEqual(len(textos), 3)


class DestinoCopiableTest(unittest.TestCase):
    """p-4c46390c7d (Sonnet r3, 0.13.16): explica_destino printed «remote «origin» → «url»» and nombra_destino rejects
    any «» other than the command and the URLs, so a supervisor that copied the line as given was refused."""

    def test_the_destination_line_copied_as_given_is_accepted(self):
        import aprueba
        dest = {"remote": "origin", "urls": ["git@github.com:vzert/lookout.git"], "motivo": ""}
        linea = aprueba.explica_destino(dest)
        tramo = linea.split("repo del agente: ", 1)[1].split(". Nómbralo", 1)[0]
        pregunta = "¿Apruebo «git push origin main»? Va a %s." % tramo
        self.assertTrue(aprueba.nombra_destino(pregunta, dest, "git push origin main"), pregunta)


class OtrosLectoresUtf8Test(unittest.TestCase):
    """p-da8bbd7dc2, adversary r3: the same strict read survived in four more transcript readers (retomar.ultimo_turno,
    relevo.assistant_texts, heuristicas.reporte_del_agente, gobierno.read_items): retomar, retiro and relevo failed on
    one broken byte."""

    def setUp(self):
        import json
        import tempfile
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "p"))
        self.path = os.path.join(self.dir, "p", "s1.jsonl")
        with open(self.path, "wb") as fh:
            fh.write(b'{"type": "assistant", "message": {"content": "roto \xff\xfe"}}\n')
            fh.write((json.dumps({"type": "assistant", "timestamp": "2026-10-19T23:00:00Z", "message": {
                "content": [{"type": "text", "text": "fin del turno"}]}}) + "\n").encode())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir)

    def test_retomar_ultimo_turno(self):
        import retomar
        self.assertIn("fin del turno", retomar.ultimo_turno(self.path)[0])

    def test_relevo_assistant_texts(self):
        import relevo
        self.assertIn("fin del turno", "\n".join(relevo.assistant_texts(self.path)))

    def test_heuristicas_reporte_del_agente(self):
        self.assertFalse(heuristicas.reporte_del_agente("s1", "algo", 0, projects_dir=self.dir))

    def test_gobierno_read_items(self):
        import gobierno
        self.assertIn(("text", "fin del turno"), gobierno.read_items(self.path))


import test_lookout_f3 as f3  # noqa: E402
import test_lookout_g as tg  # noqa: E402


class ToRealColaTest(f3.GitCase):
    """p-561f1a2173: «Siguiente en la cola: dos. Dile por SendMessage…» named the agent by lookout's name; after a
    relief or a /rename SendMessage does not take it (0.13.24, p-e9c8601cfb). It gives the session's `to` now."""

    def test_the_next_in_the_queue_comes_with_its_to(self):
        import publica
        import sesiones
        real = sesiones.to
        self.addCleanup(setattr, sesiones, "to", real)
        sesiones.to = lambda entry: "dos-2" if (entry or {}).get("session_id") == "sb" else None
        a = self.worktree("uno", "sa")
        b = self.worktree("dos", "sb")
        self.assertEqual(self.ask(a)[1], "LISTA")
        self.assertEqual(self.ask(b)[1], "ESPERA")
        f3.git(a["worktree"], "push", "-q", "origin", "HEAD:main")
        ok, lines = publica.hecho(self.pid, a)
        self.assertTrue(ok, lines)
        self.assertIn("to=dos-2", lines[-1])


class ToRealPuertoTest(tg.StubCase):
    """`lookout puerto` said «mándale por SendMessage» with lookout's name; it gives the session's `to` now. Takes
    CliEnMainTest's setup without inheriting (and re-running) its tests."""
    run_cli = tg.PideWorktreeTest.run_cli
    registra = tg.CliEnMainTest.registra

    def setUp(self):
        import importlib.machinery
        import importlib.util
        import subprocess
        super().setUp()
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(os.path.join(self.repo, "memory"))
        subprocess.run(["git", "init", "-q", "-b", "main", self.repo], check=True)
        loader = importlib.machinery.SourceFileLoader("lookout_cli_01335", os.path.join(tg.BIN, "lookout"))
        self.cli = importlib.util.module_from_spec(importlib.util.spec_from_loader("lookout_cli_01335", loader))
        loader.exec_module(self.cli)
        self.stub(agent_list=[])

    def test_puerto_gives_the_agents_to(self):
        import sesiones
        real = sesiones.to
        self.addCleanup(setattr, sesiones, "to", real)
        sesiones.to = lambda entry: "arreglar-a-2"
        os.environ["LOOKOUT_PORT_BASE"] = "47600"
        self.addCleanup(os.environ.pop, "LOOKOUT_PORT_BASE", None)
        self.registra()
        rc, out = self.run_cli("puerto", self.repo, "arreglar-a")
        self.assertIn(rc, (0, None), out)
        self.assertIn("to=arreglar-a-2", out)


class ToRealFondoTest(unittest.TestCase):
    """p-561f1a2173, adversary r5: the digest line of a long background wait said «pídele por SendMessage…» after the
    agent's tab name, with no `to`."""

    def test_the_background_wait_line_gives_the_agents_to(self):
        import digest
        import sesiones
        real = sesiones.to
        self.addCleanup(setattr, sesiones, "to", real)
        sesiones.to = lambda entry: "cambio-worktrees-2" if (entry or {}).get("session_id") == "s1" else None
        ev = {"event": "largo", "fondo": True, "session_id": "s1", "nombre": "cambio-worktrees", "ts": time.time(),
              "hace_s": 4000, "tareas": [{"description": "pytest -x"}]}
        self.assertIn("to=cambio-worktrees-2", digest.describe(ev))


import test_lookout_nombres as tn  # noqa: E402


class WorkspaceVacioTest(tn.Case):
    """p-9a9ef79ced (live 2026-10-18, w25 «avisar-a-los-devs-dd16b6»): when `agent start` failed for good, the herdr
    workspace lanza_uno had created for the agent stayed open and empty. It is closed now. Only after herdr's own «not
    started» (nothing runs in it): a start without SessionStart may have a Claude on screen, and a worktree's workspace
    holds the folder."""

    def lanza(self, resultado, sin_worktree=True):
        import lote
        self.stub(results={"workspace create": {
            "root_pane": {"pane_id": "w25:p1", "tab_id": "w25:t1"}, "tab": {"tab_id": "w25:t1", "label": "1"},
            "workspace": {"workspace_id": "w25", "label": "avisar"}}})
        draft = os.path.join(self.tmp.name, "draft.md")
        with open(draft, "w") as fh:
            fh.write("tarea")

        def arranca(project_id, sid, *a, **k):
            if resultado != "ok":
                lote.set_estado(project_id, sid, "fallida", resultado)
                return False, resultado
            return True, "ok"
        old = lote.arranca
        lote.arranca = arranca
        try:
            return lote.lanza_uno("pA", os.path.join(self.tmp.name, "repo", ".git"),
                                  {"id": "p-1", "texto": "Avisar a los devs"},
                                  {"nombre": "avisar", "worktree": os.path.join(self.tmp.name, "repo"),
                                   "rama": "main", "base": "main", "sin_worktree": sin_worktree},
                                  draft, None, False, lambda m: None, "nota")
        finally:
            lote.arranca = old

    def cerrados(self):
        return [c for c in self.calls() if c[:2] == ["workspace", "close"]]

    def test_herdr_not_starting_it_closes_its_empty_workspace(self):
        ok, _ = self.lanza("herdr no arrancó al agente: agent_name_taken")
        self.assertFalse(ok)
        self.assertEqual(self.cerrados(), [["workspace", "close", "w25"]])

    def test_a_start_without_sessionstart_keeps_it(self):
        ok, _ = self.lanza("sin SessionStart: el plugin no cargó o Claude no arrancó")
        self.assertFalse(ok)
        self.assertEqual(self.cerrados(), [])

    def test_a_started_agent_keeps_it(self):
        ok, _ = self.lanza("ok")
        self.assertTrue(ok)
        self.assertEqual(self.cerrados(), [])


if __name__ == "__main__":
    unittest.main()

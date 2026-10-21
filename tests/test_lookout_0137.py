"""0.13.7 (p-5ef58b9041): the supervisor is the user's only channel. What an agent needs typed in its own pane (its
goalspec spec waiting for «aprobado», a `! comando` for the user) reaches the supervisor's modal, and with the user's
yes the supervisor types it there through herdr.
Run: python3 -m unittest tests/test_lookout_0137.py
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from importlib.machinery import SourceFileLoader

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f2 as f2  # noqa: E402
import test_lookout_f4 as f4  # noqa: E402

import decisiones  # noqa: E402
import deliver  # noqa: E402
import digest  # noqa: E402
import lookout_state  # noqa: E402
import on_state  # noqa: E402
import supervisor_md  # noqa: E402

PID = f4.PID
# decisiones-pendientes-bloqueadas (3-tier-memory, 2026-10-16 23:13:25Z), its last message, word for word
ESPERA_REAL = ("Sigo esperando a que Víctor escriba «aprobado» en este pane. El supervisor ya aprobó el spec. "
               "Mientras no llegue esa aprobación, no edito nada.")


def cli():
    loader = SourceFileLoader("lookout_cli_0137", f4.LK)
    lk = importlib.util.module_from_spec(importlib.util.spec_from_loader("lookout_cli_0137", loader))
    loader.exec_module(lk)
    return lk


class EnviaDelUsuarioTest(f4.Base):
    def setUp(self):
        super().setUp()
        self.agent("s1", "uno")
        self.agent("s2", "dos")
        self.lk = cli()
        self.enviados = []
        self.old = self.lk.deliver.deliver
        self.lk.deliver.deliver = lambda pid, e, clave, texto, confirmar: (self.enviados.append(
            (e["nombre"], clave, texto)) or (0, "entregada"))

    def tearDown(self):
        self.lk.deliver.deliver = self.old
        super().tearDown()

    def envia(self, texto, dn="", agente="uno"):
        return self.lk.cmd_envia(argparse.Namespace(proyecto=PID, agente=agente, tarea=False, clave="k", texto=texto,
                                                    confirmar=1, usuario_confirmo=dn))

    def decision(self, pregunta, respuesta, si=True, agentes=("uno",)):
        it = decisiones.abre(PID, "¿Tecleo esto en el pane de uno?", agentes, notificar=False)
        decisiones.registra_pregunta(PID, "tu1", [pregunta + " (%s)" % it["id"]])
        decisiones.registra_respuesta(PID, "tu1", respuesta, por_pregunta={pregunta + " (%s)" % it["id"]: respuesta})
        decisiones.cierra(PID, it["id"], respuesta, si)
        return it["id"]

    def test_a_command_for_the_agents_pane_needs_the_users_yes(self):
        self.assertEqual(self.envia("! git push origin lookout/uno"), 5)    # before 0.13.7 it was typed as given
        self.assertEqual(self.enviados, [])

    def test_the_users_approval_is_typed_with_its_decision_id(self):
        dn = self.decision("El spec de uno corrige la regla y añade un aviso. ¿Tecleo «aprobado» en su pane?",
                           "Sí, teclea aprobado")
        self.assertEqual(self.envia("aprobado", dn), 0)
        self.assertEqual(self.enviados, [("uno", "usuario:" + dn, "aprobado (%s) — lo que aprobó el usuario: «El spec de "
                                          "uno corrige la regla y añade un aviso. ¿Tecleo «aprobado» en su pane? (%s)»"
                                          % (dn, dn))])   # 0.13.44: with the question the user saw
        log = supervisor_md.read_log(PID)
        self.assertEqual((log[-1]["to"], log[-1]["decision"]), ("uno", dn))

    def test_a_command_goes_as_is_and_only_the_text_the_user_saw(self):
        dn = self.decision("¿Corro `! git push origin lookout/uno` en el pane de uno?", "Sí")
        self.assertEqual(self.envia("! git push --force origin lookout/uno", dn), 5)   # not what the modal showed
        self.assertEqual(self.envia("! git push origin lookout/uno", dn), 0)
        self.assertEqual(self.enviados, [("uno", "usuario:" + dn, "! git push origin lookout/uno")])

    def test_the_text_the_user_wrote_in_other_counts(self):
        dn = self.decision("¿Qué le contesto a uno?", "usa la opción B y no toques main")
        self.assertEqual(self.envia("usa la opción B y no toques main", dn), 0)

    def test_only_the_whole_approved_text_spaces_included(self):
        # adversary r2 (sonnet): a whitespace-free substring check let a prefix or a moved space through
        dn = self.decision("¿Corro «! rm -rf /tmp/x/old» en el pane de uno?", "Sí")
        for malo in ("! rm -rf /", "! rm -rf /tmp/ x/old", "!rm -rf / tmp/x/old", "  !rm -rf /tmp/x",
                     "! rm -rf /tmp/x/old\n! rm -rf /", "Corro"):
            self.assertEqual(self.envia(malo, dn), 5, malo)
        self.assertEqual(self.enviados, [])
        self.assertEqual(self.envia("x\n! rm -rf /"), 5)                     # a command on a later line needs dN too
        self.assertEqual(self.envia("  ! rm -rf /tmp/x/old  ", dn), 0)       # the ends do not count
        self.assertEqual(self.enviados, [("uno", "usuario:" + dn, "! rm -rf /tmp/x/old")])

    def test_no_yes_another_agent_or_no_decision_types_nothing(self):
        no = self.decision("¿Tecleo «aprobado» en el pane de uno?", "No, todavía no", si=False)
        otro = self.decision("¿Tecleo «aprobado» en el pane de dos?", "Sí", agentes=("dos",))
        self.assertEqual(self.envia("aprobado", no), 5)
        self.assertEqual(self.envia("aprobado", otro), 5)
        self.assertEqual(self.envia("aprobado", "d99"), 5)
        self.assertEqual(self.enviados, [])
        abierta = decisiones.abre(PID, "¿Tecleo «aprobado» en el pane de uno?", ["uno"], notificar=False)
        self.assertEqual(self.envia("aprobado", abierta["id"]), 5)          # asked, not answered yet

    def test_a_yes_the_supervisor_wrote_without_a_modal_types_nothing(self):
        # adversary: --abre and --cierra --respuesta are the supervisor's own words; the user saw nothing
        it = decisiones.abre(PID, "Teclear aprobado en uno", ["uno"], notificar=False)
        decisiones.cierra(PID, it["id"], "aprobado", True)
        self.assertEqual(self.envia("aprobado", it["id"]), 5)
        self.assertEqual(self.enviados, [])

    def test_the_cli_takes_the_flag(self):
        r = self.run_lk("envia", PID, "uno", "--usuario-confirmo", "d7", "--texto", "aprobado")
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("NO TECLEADO", r.stdout)


class ComandoEntregadoTest(f2.StubCase):
    """Measured 2026-10-16 with a throwaway Claude: `herdr agent prompt "! echo hola"` runs it in shell mode, fires no
    UserPromptSubmit and leaves <bash-input> echo hola</bash-input> in the transcript."""
    cmd = "! git push origin lookout/uno"

    def bash_input(self, *cmds):
        d = os.path.join(self.projects, "-tmp-x")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, self.sid + ".jsonl"), "a") as fh:
            for c in cmds:
                fh.write(json.dumps({"type": "user", "message": {"role": "user",
                                                                 "content": "<bash-input> %s</bash-input>" % c}}) + "\n")
                fh.write(json.dumps({"type": "user", "message": {"role": "user",
                                                                 "content": "<bash-stdout>ok</bash-stdout>"}}) + "\n")

    def test_a_command_is_confirmed_by_its_transcript_and_never_sent_twice(self):
        self.bash_input("git push origin lookout/uno")       # the user ran the same command an hour ago
        code, msg = deliver.deliver(self.pid, self.entry, "usuario:d1", self.cmd, 0.3, projects_dir=self.projects)
        self.assertEqual(code, 6, msg)                        # the old one does not confirm this one
        self.bash_input("git push origin lookout/uno")       # this one ran
        code, msg = deliver.deliver(self.pid, self.entry, "usuario:d1", self.cmd, 0.3, projects_dir=self.projects)
        self.assertEqual(code, 0, msg)
        self.assertEqual(len(self.calls(["agent", "prompt"])), 1)


class EsperaEnSuPaneTest(f4.Base):
    def stop(self, msg, tp=None):
        ev, label, _ = on_state.build({"hook_event_name": "Stop", "session_id": "s1", "transcript_path": tp,
                                       "last_assistant_message": msg},
                                      {"nombre": "decisiones", "address": "uds:/tmp/sup.sock"})
        return ev

    def test_the_real_wait_is_marked_and_wakes_even_after_a_report(self):
        addr = "uds:/tmp/sup.sock"
        tp = os.path.join(self.tmp.name, "ag.jsonl")
        with open(tp, "w") as fh:
            for ev in ({"type": "user", "message": {"content": "<cross-session-message>aprobado por mi parte"}},
                       {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "u1", "name": "SendMessage",
                                                                      "input": {"to": addr, "message": "espero"}}]}},
                       {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "u1",
                                                                 "content": "enviado"}]}}):
                fh.write(json.dumps(ev) + "\n")
        ev = self.stop(ESPERA_REAL, tp)
        self.assertEqual(ev["event"], "idle")
        self.assertTrue(ev.get("reporto"))
        self.assertEqual(ev["espera_pane"]["cita"][:40], ESPERA_REAL[:40])
        self.assertIn("lookout envia", digest.describe(ev))
        self.assertIn("--usuario-confirmo", digest.describe(ev))
        lookout_state.append_event(PID, ev)
        out = subprocess.run([sys.executable, os.path.join(f4.BIN, "wait_event.py"), lookout_state.events_path(PID),
                              "--offset", "0", "--types", digest.WAKE_TYPES, "--timeout", "5"],
                             capture_output=True, text=True, env=dict(os.environ))
        self.assertIn("decisiones", out.stdout)

    def test_a_command_handed_to_the_user_and_the_ratify_brake_count(self):
        self.assertTrue(self.stop("Listo el commit. Corre tú `! git push origin lookout/uno` y me avisas.").get("espera_pane"))
        rows_brake = [{"motivo": "goalspec: this session posted its ## Goal-spec and has not shown it back to the "
                                 "human yet, so this tool call is held"}]
        self.assertEqual(on_state.espera_pane("Te mandé el spec.", rows_brake)["motivo"], "ratificar su spec de goalspec")

    def test_a_wait_with_a_task_of_its_own_running_still_wakes(self):
        ev, _l, _o = on_state.build({"hook_event_name": "Stop", "session_id": "s1", "last_assistant_message":
                                     "Mientras corre la suite: corre tú `! git push origin lookout/uno`.",
                                     "background_tasks": [{"type": "shell", "status": "running", "command": "make"}]},
                                    {"nombre": "decisiones", "address": "uds:/tmp/sup.sock"})
        self.assertEqual(ev["event"], "bg_wait")
        self.assertTrue(ev.get("espera_pane"))
        self.assertIn("ESPERA ALGO TECLEADO", digest.describe(ev))
        lookout_state.append_event(PID, ev)
        out = subprocess.run([sys.executable, os.path.join(f4.BIN, "wait_event.py"), lookout_state.events_path(PID),
                              "--offset", "0", "--types", digest.WAKE_TYPES, "--timeout", "5"],
                             capture_output=True, text=True, env=dict(os.environ))
        self.assertIn("decisiones", out.stdout)

    def test_a_command_that_starts_with_a_path_counts(self):
        # adversary r2 (codex): «! ./deploy.sh» and «! /bin/echo» were missed
        for msg in ("Corre tú `! ./deploy.sh` en este momento.", "Necesito «! /bin/echo hola» tecleado.", "! ~/bin/x",
                    "Teclea “! ./deploy.sh” cuando puedas.", 'Teclea "! git status" ahí.', "Teclea ‘! git status’ ahí.",
                    "Corre tú ! git status.", "Comando a teclear: ! ./deploy.sh"):
            self.assertTrue(self.stop(msg).get("espera_pane"), msg)

    def test_the_delivery_helper_never_types_a_command_by_itself(self):
        r = subprocess.run([sys.executable, os.path.join(f4.BIN, "deliver.py"), PID, "uno", "--clave", "k",
                            "--texto", "hola\n! ./deploy.sh"], capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn("--usuario-confirmo", r.stdout)

    def test_ordinary_endings_are_not_a_wait(self):
        for msg in ("Hecho: 3 pruebas en verde. El pane w1:p3 queda libre.", "x != y; a!=b", "Listo, nada más."):
            self.assertIsNone(self.stop(msg).get("espera_pane"), msg)


class AgenteSabeElCaminoTest(unittest.TestCase):
    def test_the_ask_deny_and_the_skill_say_the_supervisor_types_it(self):
        # the note stays under its 700 characters (test_lookout.NotaTest): the deny of AskUserQuestion carries it
        ask = open(os.path.join(f4.BIN, "on_ask.py"), encoding="utf-8").read()
        self.assertIn("la teclea en tu pane", ask)
        self.assertIn("No mandes al usuario a tu pane", ask)
        skill = open(os.path.join(f4.ROOT, "plugins", "lookout", "skills", "supervisa", "SKILL.md"),
                     encoding="utf-8").read()
        self.assertIn("--usuario-confirmo dN --texto", skill)
        self.assertNotIn("para que el usuario lo corra en el\npane del agente", skill)


if __name__ == "__main__":
    unittest.main()

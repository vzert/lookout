"""0.13.46: a Bash command auto mode's classifier refused, typed as «! comando» in the agent's pane by the supervisor with
the user's yes, so the user neither copies it from the agent's pane nor changes tab (claude-vzert user, 2026-10-21: the
agent wrote «Teclea esta línea completa, con el ! y la ruta absoluta…» for a deploy script). Runs the real
PermissionDenied/PreToolUse hook (permisos.handle) and the real `lookout decision` / `lookout envia` commands.
Run: python3 -m unittest tests/test_lookout_01346.py
"""
import argparse
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_0137 as t137  # noqa: E402
import test_lookout_f4 as f4  # noqa: E402

import decisiones  # noqa: E402
import lookout_state  # noqa: E402
import permisos  # noqa: E402
import teclea  # noqa: E402

PID = f4.PID
# the shape of the field case (a script in the session's scratchpad), with made-up names: the user's paths stay private
DEPLOY = ("bash /private/tmp/claude-501/-Users-alguien-Proyectos-tienda-pos/"
          "sesion-de-ejemplo/scratchpad/deploy-chat-continuar.sh")
CWD = "/Users/alguien/Proyectos/tienda/pos"
SI, SIEMPRE, NO = "Sí, tecléalo", "Sí, y siempre para este mismo comando", "No, todavía no"


class Base(f4.Base):
    def setUp(self):
        super().setUp()
        self.agent("s1", "uno")
        self.agent("s2", "dos")
        self.lk = t137.cli()
        self.enviados = []
        self.old = self.lk.deliver.deliver
        self.lk.deliver.deliver = lambda pid, e, clave, texto, confirmar: (self.enviados.append(
            (e["nombre"], clave, texto)) or (0, "entregada"))
        self.supervisor("sup1")
        self.tu = 0

    def tearDown(self):
        self.lk.deliver.deliver = self.old
        super().tearDown()

    def supervisor(self, sid):
        lookout_state.write_json(os.path.join(lookout_state.project_dir(PID), "lock.json"),
                                 {"supervisor": {"session_id": sid}})

    def niega(self, comando, sid="s1", cwd=CWD, tool="Bash"):
        ti = {"command": comando} if tool == "Bash" else {"file_path": comando}
        data = {"session_id": sid, "hook_event_name": "PermissionDenied", "tool_name": tool, "tool_input": ti,
                "permission_mode": "auto", "cwd": cwd, "reason": "[Production Deploy]"}
        nombre = {"s1": "uno", "s2": "dos"}[sid]
        self.assertIsNone(permisos.handle(data, {"project_id": PID, "nombre": nombre}, rules={}))  # never retry

    def run_cli(self, fn, **kw):
        out = io.StringIO()
        with redirect_stdout(out):
            code = fn(argparse.Namespace(**kw))
        return code, out.getvalue()

    def abre(self, pregunta, agente="uno", siempre_es=SIEMPRE):
        return self.run_cli(self.lk.cmd_decision, proyecto=PID, abre=pregunta, agentes=agente, negado=True,
                            si_es=SI, siempre_es=siempre_es, permiso=False, sin_revisor=False, cierre=False,
                            shells_parar="", shells_dejar="", cierra=None, nueva=False)

    def responde(self, dn, pregunta, respuesta):
        self.tu += 1
        q = pregunta if ("(%s)" % dn) in pregunta else pregunta + " (%s)" % dn
        decisiones.registra_pregunta(PID, "tu%d" % self.tu, [q])
        decisiones.registra_respuesta(PID, "tu%d" % self.tu, respuesta, por_pregunta={q: respuesta})

    def envia(self, texto, dn, agente="uno"):
        return self.run_cli(self.lk.cmd_envia, proyecto=PID, agente=agente, tarea=False, clave=None, texto=texto,
                            confirmar=1, usuario_confirmo=dn)[0]

    def ultima(self):
        return decisiones.load(PID)["items"][-1]["id"]


class EventoTest(Base):
    def test_the_refusal_keeps_the_whole_command_and_cwd(self):
        largo = DEPLOY + " --sin-cache " + "x" * 300
        self.niega(largo)
        ev = [e for e in lookout_state.read_events(PID, 0)[0] if e.get("event") == "negado"][-1]
        self.assertEqual((ev["comando"], ev["cwd"], ev["hook"]), (largo, CWD, "PermissionDenied"))
        self.assertEqual(len(ev["detalle"]), 200)   # the short one stays as it was

    def test_another_tool_keeps_no_command(self):
        self.niega("/etc/hosts", tool="Write")
        ev = [e for e in lookout_state.read_events(PID, 0)[0] if e.get("event") == "negado"][-1]
        self.assertNotIn("comando", ev)


class TecleaTest(Base):
    PREGUNTA = "Corre el deploy a producción de uno en %s. ¿Tecleo «! %s» en su pane?" % (CWD, DEPLOY)

    def test_the_field_case_with_the_users_yes_is_typed_once(self):
        self.niega(DEPLOY)
        code, out = self.abre(self.PREGUNTA)
        self.assertEqual(code, 0, out)
        dn = self.ultima()
        self.assertIn("«! %s»" % DEPLOY, out)
        self.assertEqual(self.envia("! " + DEPLOY, dn), 5)          # asked, not answered
        self.responde(dn, self.PREGUNTA, SI)
        self.assertEqual(self.envia("! " + DEPLOY, dn), 0)
        self.assertEqual(self.enviados, [("uno", "usuario:" + dn, "! " + DEPLOY)])

    def test_the_question_must_show_the_whole_line(self):
        self.niega(DEPLOY)
        for mala in ("¿Corro el deploy de uno?", "¿Tecleo «%s»?" % DEPLOY, "¿Tecleo «! %s»?" % DEPLOY[:-3]):
            code, out = self.abre(mala)
            self.assertEqual(code, 5, mala)
        self.assertEqual(decisiones.load(PID)["items"], [])

    def test_no_refusal_or_a_multiline_one_opens_nothing(self):
        code, out = self.abre(self.PREGUNTA)
        self.assertEqual(code, 5)
        self.niega("cat <<EOF > x\nhola\nEOF")
        code, out = self.abre("¿Tecleo «! cat <<EOF > x»?")
        self.assertEqual(code, 5)
        self.assertIn("varias líneas", out)

    def test_a_control_character_is_never_offered(self):
        # adversary r1 (sonnet): invisible in the modal, a keystroke in the pane
        for c in ("\x03", "\x15", "\x1b[200~", "\t", "\x0b", "\u2028", "\x7f", "\x85",
                  "\u200b", "\u202e", "\ufeff", "\u00ad", "\U000e0041", "\ufe0f",  # adversary r2: format characters
                  "\u034f", "\u180b", "\u0338", "\u00a0", "\u2003", "\u3164", "\u115f", "\uffa0", "\u2800",
                  "\u17b5", "\ue000",  # codex r2: marks, non-ASCII spaces, blank letters, private use
                  "\U00013441", "\u303f", "日", "\u05d0", "\u00d7"):  # codex r3: only a Latin keyboard
            cmd = "bash deploy.sh" + c + "rm -rf ~"
            self.niega(cmd)
            code, out = self.abre("¿Tecleo «! %s»?" % cmd)
            self.assertEqual(code, 5, repr(c))
        # codex r1: checked as refused, never trimmed first
        for cmd in ("\tgit status", "git status\t", "git status\n", "\ngit status", "  git status", "git status  ",
                    "echo a \\ "):
            self.niega(cmd)
            self.assertEqual(self.abre("¿Tecleo «! %s»?" % cmd.strip())[0], 5, repr(cmd))
            self.assertIsNone(teclea.linea(cmd), repr(cmd))
        self.assertEqual(decisiones.load(PID)["items"], [])
        self.niega(DEPLOY)
        self.assertEqual(self.abre(self.PREGUNTA)[0], 0)              # the field case still opens
        self.assertEqual(teclea.linea("echo ¿café? ñ Ü 'a  b' $X | grep -E \"x+\" && ls ~/p"),
                         "! echo ¿café? ñ Ü 'a  b' $X | grep -E \"x+\" && ls ~/p")   # what commands are made of

    def test_no_another_text_or_another_agent_types_nothing(self):
        self.niega(DEPLOY)
        self.abre(self.PREGUNTA)
        dn = self.ultima()
        self.responde(dn, self.PREGUNTA, NO)
        self.assertEqual(self.envia("! " + DEPLOY, dn), 5)
        self.niega(DEPLOY)
        self.abre(self.PREGUNTA)
        dn = self.ultima()
        self.responde(dn, self.PREGUNTA, SI)
        self.assertEqual(self.envia("! " + DEPLOY + "x", dn), 5)
        self.assertEqual(self.envia("! " + DEPLOY, dn, agente="dos"), 5)
        self.assertEqual(self.enviados, [])

    def test_lookouts_own_denials_are_never_offered(self):
        # a kill denied by lookout's PreToolUse writes a negado without a command: nothing to type
        out = permisos.handle({"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Bash",
                               "tool_input": {"command": "pkill -f claude"}, "permission_mode": "auto", "cwd": CWD},
                              {"project_id": PID, "nombre": "uno"}, rules={})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        code, _ = self.abre("¿Tecleo «! pkill -f claude»?")
        self.assertEqual(code, 5)


class RecetaTest(Base):
    def test_the_printed_command_is_quoted_for_the_supervisors_shell(self):
        # codex r4: inside "…" a $(…) or a backtick would run in the supervisor's own shell
        import shlex
        cmd = "bash x.sh \"$(id)\" `id` 'a b' $HOME"
        self.niega(cmd)
        code, out = self.abre("¿Tecleo «! %s»?" % cmd)
        self.assertEqual(code, 0, out)
        receta = out[out.index("`lookout envia ") + 1:]
        receta = receta[:receta.index("`. ")]
        args = shlex.split(receta)
        self.assertEqual(args[args.index("--texto") + 1], "! " + cmd)
        dn = self.ultima()
        self.responde(dn, "¿Tecleo «! %s»?" % cmd, SIEMPRE)
        self.niega(cmd)
        code, out = self.abre("¿Tecleo «! %s»?" % cmd)                 # the «siempre» refusal prints it too
        receta = out[out.index("`lookout envia ") + 1:]
        receta = receta[:receta.index("`, tal cual")]
        args = shlex.split(receta)
        self.assertEqual(args[args.index("--texto") + 1], "! " + cmd)


class SiempreTest(Base):
    PREGUNTA = TecleaTest.PREGUNTA

    def siempre(self):
        self.niega(DEPLOY)
        self.abre(self.PREGUNTA)
        dn = self.ultima()
        self.responde(dn, self.PREGUNTA, SIEMPRE)
        return dn

    def test_always_types_it_again_after_each_new_refusal(self):
        dn = self.siempre()
        self.assertEqual(self.envia("! " + DEPLOY, dn), 0)
        self.niega(DEPLOY)
        code, out = self.abre(self.PREGUNTA)                          # no new question for the same command
        self.assertEqual(code, 5)
        self.assertIn(dn, out)
        self.assertEqual(self.envia("! " + DEPLOY, dn), 0)
        claves = [c for _, c, _ in self.enviados]
        self.assertEqual(len(claves), 2)
        self.assertNotEqual(claves[0], claves[1])                     # one delivery per refusal

    def test_always_is_the_exact_text_cwd_agent_and_supervisor(self):
        dn = self.siempre()
        otro = DEPLOY[:-4] + "x.sh"                                   # one character
        self.niega(otro)
        self.assertEqual(self.envia("! " + otro, dn), 5)
        code, _ = self.abre("¿Tecleo «! %s» en uno?" % otro)
        self.assertEqual(code, 0)                                     # its own question, with its own text
        self.niega(DEPLOY, cwd="/otra/carpeta")                       # same text, another folder
        code, _ = self.abre(self.PREGUNTA)
        self.assertEqual(code, 0)                                     # asked again
        self.niega(DEPLOY, sid="s2")
        self.assertEqual(self.envia("! " + DEPLOY, dn, agente="dos"), 5)
        self.niega(DEPLOY)
        self.supervisor("sup2")                                       # a relief: the always is gone
        self.assertEqual(self.envia("! " + DEPLOY, dn), 5)
        self.assertEqual(self.enviados, [])

    def test_a_plain_yes_is_once(self):
        self.niega(DEPLOY)
        self.abre(self.PREGUNTA)
        dn = self.ultima()
        self.responde(dn, self.PREGUNTA, SI)
        self.assertEqual(self.envia("! " + DEPLOY, dn), 0)
        self.niega(DEPLOY)
        code, _ = self.abre(self.PREGUNTA)
        self.assertEqual(code, 0)                                     # a new refusal asks again
        self.assertEqual(self.lk.texto_del_usuario(PID, {"nombre": "uno", "session_id": "s1"}, dn, "! " + DEPLOY)[0],
                         "usuario:" + dn)                            # same key: the ledger types it once

    def test_the_two_labels_must_differ(self):
        self.niega(DEPLOY)
        code, _ = self.abre(self.PREGUNTA, siempre_es=SI)
        self.assertEqual(code, 5)


class AvisoAlAgenteTest(Base):
    def pre(self, sid="s1", mode="auto", comando="ls"):
        return permisos.handle({"session_id": sid, "hook_event_name": "PreToolUse", "tool_name": "Bash",
                                "tool_input": {"command": comando}, "permission_mode": mode, "cwd": CWD},
                               {"project_id": PID, "nombre": "uno"}, rules={})

    def test_once_per_agent_session_in_auto_mode(self):
        out = self.pre()
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("permissionDecision", out["hookSpecificOutput"])   # the classifier still decides
        for frase in ("no le pidas al usuario que lo copie", "reglas", "teclea en tu pane"):
            self.assertIn(frase, ctx)
        self.assertIsNone(self.pre())
        self.assertIn("additionalContext", self.pre(sid="s2")["hookSpecificOutput"])

    def test_not_outside_auto_mode(self):
        for mode in ("default", "acceptEdits", "plan", "bypassPermissions"):
            self.assertIsNone(self.pre(sid="s1", mode=mode), mode)

    def test_a_denial_of_lookout_keeps_its_reason_and_adds_nothing(self):
        out = self.pre(comando="pkill -f claude")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("additionalContext", self.pre()["hookSpecificOutput"])   # still due on the next Bash


class SkillTest(unittest.TestCase):
    def test_the_skill_offers_to_type_a_refused_bash(self):
        with open(os.path.join(os.path.dirname(f4.LK), "..", "skills", "supervisa", "SKILL.md"), encoding="utf-8") as fh:
            s = fh.read()
        regla = s[s.index("- **`auto mode le negó`**"):]
        regla = regla[:regla.index("\n- **", 3)]
        for frase in ("--negado", "--siempre-es", "lookout envia", "Ninguna marcada como recomendada", "No la rodees"):
            self.assertIn(frase, regla)


if __name__ == "__main__":
    unittest.main()

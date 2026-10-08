"""0.10.0 tests: Fase 9 F (flujo), and lookout no longer judging the adversary.

gobierno (user's decision 2026-10-07): lookout coordinates and supervises; which model and which backends an adversary
round needs is goalspec's policy. The push needs only the agent's last quoted verdict to be hold (0.9.0 also refused a
hold from the agent's own model, MISMO-MODELO).
F1: the task asks to send each decision to the supervisor as soon as it exists.
F2: a question the supervisor puts in the chat gets the user's answer on record from the supervisor's own prompt.
F3: `entrega` types the report note only after the /rename reached the agent.
F5: the batch cap counts every live session of the project, not only lookout's.
F6: `libera` prints the exact cleanup of the worktree and its branch, for the user to run.
F7: a launched agent's tab gets a short readable title, not the truncated slug.
F8: the supervisor does not read other plugins' reports or code on its own; it asks the agent.
Each test fails on 0.9.0 (cff3aeb) at its point of use.
Run: python3 -m unittest tests/test_lookout_f10.py
"""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "plugins", "lookout", "bin")
FIX = os.path.join(ROOT, "tests", "fixtures")
STUB = os.path.join(FIX, "herdr_stub.py")
sys.path.insert(0, BIN)

import gobierno  # noqa: E402
import herdr_cli  # noqa: E402
import lookout_state  # noqa: E402
import registry  # noqa: E402

HAIKU = "claude-haiku-4-5-20251001"
M_SUB = "[ADVERSARY-MODEL: Claude Sonnet 5.5 / claude-sonnet-5-5]"
M_EXT = "[ADVERSARY-MODEL: gpt-5.6-luna / gpt-5.6-luna]"
HOLD = "[ADVERSARY-VERDICT: hold ungrounded=0 unfalsified=0 incomplete=0 autonomy-violations=0 unsafe=0]"
BREAK = "[ADVERSARY-VERDICT: break ungrounded=1 unfalsified=0 incomplete=0 autonomy-violations=0 unsafe=0]"


def a_text(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def a_tool(name, inp):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}


SPAWN = a_tool("Agent", {"subagent_type": "goalspec:goal-adversary", "prompt": "x", "model": "sonnet"})
EXT = a_tool("Bash", {"command": "bash /x/goalspec/hooks/external-adversary.sh < payload.txt"})
EDIT = a_tool("Edit", {"file_path": "/x/src/a.py", "old_string": "a", "new_string": "b"})
COMMIT = a_tool("Bash", {"command": "git add -A && git commit -m 'fix: lo que dijo el externo'"})


def load_cli(name="lookout_cli_f10"):
    loader = importlib.machinery.SourceFileLoader(name, os.path.join(BIN, "lookout"))
    spec = importlib.util.spec_from_loader(name, loader)
    cli = importlib.util.module_from_spec(spec)
    loader.exec_module(cli)
    return cli


class StateCase(unittest.TestCase):
    pid = "pF10"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.projects = os.path.join(t, "projects")
        cfg = os.path.join(t, "claude-config", "plugins")
        os.makedirs(cfg)
        with open(os.path.join(cfg, "installed_plugins.json"), "w") as fh:
            json.dump({"version": 2, "plugins": {"goalspec@goal-forge": [{"scope": "user", "version": "0"}]}}, fh)
        self.conf = os.path.join(t, "stub.json")
        self.log = os.path.join(t, "calls.log")
        keys = ("LOOKOUT_STATE_DIR", "CLAUDE_CONFIG_DIR", "HERDR_STUB_CONF", "HERDR_STUB_LOG")
        self.old_env = {k: os.environ.get(k) for k in keys}
        os.environ.update({"LOOKOUT_STATE_DIR": os.path.join(t, "state"), "CLAUDE_CONFIG_DIR": os.path.dirname(cfg),
                           "HERDR_STUB_CONF": self.conf, "HERDR_STUB_LOG": self.log})
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

    def calls(self):
        try:
            with open(self.log) as fh:
                return [json.loads(l) for l in fh if l.strip()]
        except OSError:
            return []

    def transcript(self, sid, events):
        d = os.path.join(self.projects, "-enc")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, sid + ".jsonl"), "w") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")

    def agent(self, sid, nombre="ag", tarea="p-1", modelo=HAIKU, **kw):
        reg = registry.load(self.pid)
        reg.setdefault("agents", {})[sid] = dict({"session_id": sid, "nombre": nombre, "tarea": tarea,
                                                  "alta": "2026-10-07T10:00:00", "pane_id": "w1:p1", "cwd": "/x",
                                                  "worktree": "/x"}, **kw)
        registry.save(self.pid, reg)
        lookout_state.append_event(self.pid, {"session_id": sid, "event": "start", "modelo": modelo})
        return reg["agents"][sid]


class NoJuzgaAdversarioTest(StateCase):
    def push(self, e):
        return gobierno.decide_push(gobierno.estado(self.pid, e, self.projects))

    def test_a_hold_passes_whatever_model_or_backend_gave_it(self):
        M_SAME = "[ADVERSARY-MODEL: Claude Haiku 4.5 / claude-haiku-4-5-20251001]"  # the agent's own model
        M_UNK = "[ADVERSARY-MODEL: Claude / UNKNOWN]"
        for eventos in ([SPAWN, a_text(M_SAME + "\n" + HOLD)],
                        [SPAWN, a_text(M_UNK + "\n" + HOLD)],
                        [EXT, a_text(M_EXT + "\n" + BREAK), EDIT, SPAWN, a_text(M_SUB + "\n" + HOLD)],
                        [SPAWN, a_text(M_SUB + "\n" + HOLD), EDIT, COMMIT, EXT, a_text(M_EXT + "\n" + HOLD)]):
            e = self.agent("s1")
            self.transcript("s1", eventos)
            ok, code, text = self.push(e)
            self.assertEqual((ok, code), (True, "OK"))
            self.assertIn("lo decide goalspec, no lookout", text)

    def test_the_last_verdict_still_decides(self):
        e = self.agent("s1")
        self.transcript("s1", [SPAWN, a_text(M_SUB + "\n" + HOLD), EXT, a_text(M_EXT + "\n" + BREAK)])
        self.assertEqual(self.push(e)[:2], (False, "BREAK"))

def repo_con_pendientes(base, *textos):
    root = os.path.join(base, "repo")
    os.makedirs(os.path.join(root, "memory"))
    subprocess.run(["git", "init", "-q", "-b", "main", root], check=True)
    with open(os.path.join(root, "memory", "_pendientes.md"), "w", encoding="utf-8") as fh:
        fh.write("# Pendientes\n\n## Alta prioridad\n\n")
        for n, t in enumerate(textos):
            fh.write("- [ ] %s — _creado: 2026-10-07_ — _id: p-%010d_\n" % (t, n))
    return root, lookout_state.git_common_dir(root)


def vivo(sid, cwd, pane):
    return {"pane_id": pane, "cwd": cwd, "agent": "claude", "agent_status": "idle",
            "agent_session": {"value": sid}, "tab_id": ""}


class TopeTest(StateCase):
    def test_the_users_live_sessions_on_the_project_take_slots(self):
        import lote
        import lock
        root, common = repo_con_pendientes(self.tmp.name, "Arreglar `src/a.py`", "Arreglar `src/b.py`",
                                           "Arreglar `src/c.py`")
        os.makedirs(os.path.join(root, "sub"))
        lookout_state.write_json(os.path.join(lookout_state.project_dir(self.pid), "lock.json"),
                                 {"common_dir": common, "supervisor": {"session_id": "sup"}})
        self.assertEqual(lock.read(self.pid)["supervisor"]["session_id"], "sup")
        otro = os.path.join(self.tmp.name, "otro")
        subprocess.run(["git", "init", "-q", otro], check=True)
        # two sessions of the user on the project (one in a subfolder), the supervisor, and one on another repo
        self.stub(agent_list=[vivo("u1", root, "w1:p1"), vivo("u2", os.path.join(root, "sub"), "w1:p2"),
                              vivo("sup", root, "w1:p3"), vivo("x1", otro, "w2:p1")])
        prop = lote.propone(self.pid, common, tope=3)
        self.assertEqual(prop["libres"], 1)
        self.assertEqual(len(prop["lote"]), 1)
        self.assertIn("Ocupan hueco 2 sesiones vivas", lote.render_propuesta(prop))


class RespuestaEnChatTest(StateCase):
    SUP = "11111111-2222-3333-4444-555555555555"

    def setUp(self):
        super().setUp()
        import supervisor_md
        lookout_state.write_json(supervisor_md.sup_marker(self.SUP), {"project_id": self.pid})

    def prompt(self, texto):
        # the real hook entry: hooks.json sends UserPromptSubmit to guard.sh on_state.py (async)
        data = json.dumps({"session_id": self.SUP, "hook_event_name": "UserPromptSubmit", "prompt": texto})
        subprocess.run(["sh", os.path.join(ROOT, "plugins", "lookout", "hooks", "guard.sh"), "on_state.py"],
                       input=data, text=True, check=True, env=dict(os.environ, PATH="/usr/bin:/bin:" + os.path.dirname(sys.executable)))

    def test_the_users_chat_answer_lands_on_the_open_decision_and_authorizes_nothing(self):
        import decisiones
        import supervisor_md
        d = decisiones.abre(self.pid, "¿Publico la rama de fix-login?", notificar=False)
        self.prompt("/rename supervisor-proyecto")                                       # lookout typed it
        self.prompt('<cross-session-message from="uds:/x">listo</cross-session-message>')  # an agent
        self.prompt("<task-notification><task-id>b1</task-id></task-notification>")       # the waiter woke
        self.assertNotIn("respuesta_usuario", decisiones.load(self.pid)["items"][0])
        self.prompt("sí, publícala")
        it = decisiones.load(self.pid)["items"][0]
        self.assertEqual((it["id"], it["estado"], it["respuesta_usuario"]), (d["id"], "abierta", "sí, publícala"))
        self.assertIsNone(decisiones.respondida(self.pid, d["id"]))  # only `decision --cierra … --si` authorizes
        with open(supervisor_md.path(self.pid), encoding="utf-8") as fh:
            self.assertIn("sí, publícala", fh.read())

    def test_publica_opens_the_decision_and_asks_in_the_chat_with_agents_alive(self):
        # adversary round 1 (external): `publica` still sent the supervisor to an unconditional AskUserQuestion
        import argparse
        import io
        import publica
        from contextlib import redirect_stdout
        self.agent("s1", nombre="fix-login")
        cli = load_cli("lookout_cli_f10_publica")
        cli.project = lambda _p: (self.pid, os.path.join(self.tmp.name, "repo", ".git"))
        for mod, name, stub in ((publica, "pide", lambda *a, **k: (True, "LISTA", ["rama lookout/fix-login"])),
                                (publica, "regla_estado", lambda _r: ("aplicada", []))):
            self.addCleanup(setattr, mod, name, getattr(mod, name))
            setattr(mod, name, stub)
        out = io.StringIO()
        with redirect_stdout(out):
            cli.cmd_publica(argparse.Namespace(proyecto="/x", agente="fix-login", cola=False, hecho=False,
                                               retira=False))
        self.assertIn("lookout decision %s --abre" % self.pid, out.getvalue())
        self.assertIn("en el chat si hay agentes vivos", out.getvalue())

    def test_the_round_cap_and_the_close_ask_in_the_chat_too(self):
        # adversary round 2 (subagent): two more carriers of the rule still sent the supervisor to the modal
        import cierre
        e = self.agent("s1", nombre="fix-login")
        self.transcript("s1", [SPAWN, a_text(M_SUB + "\n" + BREAK)] * 5)
        ok, code, text = gobierno.decide_ronda(gobierno.estado(self.pid, e, self.projects))
        self.assertEqual((ok, code), (False, "PREGUNTA-USUARIO"))
        self.assertIn("en el chat", text)
        self.assertNotIn("AskUserQuestion", text)
        ok, lines = cierre.cierra(self.pid, "/x/.git", e, gobierno.estado(self.pid, e, self.projects), "completed",
                                  "nota", "")
        self.assertFalse(ok)
        self.assertIn("en el chat", lines[0])
        self.assertNotIn("AskUserQuestion", lines[0])

    def test_the_skill_asks_in_the_chat_while_agents_are_alive(self):
        with open(os.path.join(ROOT, "plugins", "lookout", "skills", "supervisa", "SKILL.md"), encoding="utf-8") as fh:
            skill = fh.read()
        self.assertIn("Con agentes vivos, pregunta en el chat", skill)
        self.assertIn("es regla de\n     goalspec, no tuya ni de lookout", skill)
        self.assertNotIn("MISMO-MODELO", skill)


class RenameAntesDeNotaTest(StateCase):
    def entrega(self, **stub):
        registry.save(self.pid, {"agents": {"s1": {"session_id": "s1", "nombre": "nope-arreglar", "pane_id": "wS:p9",
                                                   "tab_id": "wS:t9", "cwd": "/nope", "pestana": "x"}}})
        with open(os.path.join(FIX, "caja-a1.ansi")) as fh:
            vacia = fh.read()
        self.stub(agent_get={"pane_id": "wS:p9", "tab_id": "wS:t9", "cwd": "/nope", "agent_status": "idle",
                             "agent_session": {"value": "s1"}}, tabs={"wS:t9": {"label": "x", "pane_count": 1}},
                  agent_read=vacia, **stub)
        cli = load_cli()
        cli.project = lambda arg: (self.pid, "/nope/.git")
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.cmd_entrega(type("A", (), {"proyecto": self.pid, "agente": "nope-arreglar",
                                                "pasos": "rename,nota", "timeout": 1})())
        prompts = [c[3] for c in self.calls() if c[:2] == ["agent", "prompt"]]
        return rc, out.getvalue(), prompts

    def test_the_note_waits_for_the_rename_to_land(self):
        ev = {"path": lookout_state.events_path(self.pid), "session_id": "s1"}
        rc, out, prompts = self.entrega(prompt_event=ev)
        self.assertEqual(rc, 0)
        self.assertEqual(prompts[0], "/rename nope-arreglar")
        self.assertEqual(len(prompts), 2)
        self.assertIn("hooks confirmados", out)

    def test_a_rename_still_in_the_box_gets_no_note_typed_over_it(self):
        with open(os.path.join(FIX, "caja-borrador.ansi")) as fh:
            borrador = fh.read()
        rc, out, prompts = self.entrega(read_after_prompt=borrador)
        self.assertEqual(prompts, ["/rename nope-arreglar"])
        self.assertEqual(rc, 4)
        self.assertIn("NO ENTREGADO (nota)", out)


class LimpiezaTrasLiberaTest(StateCase):
    def libera(self, **entry):
        import argparse
        import io
        import lote
        from contextlib import redirect_stdout
        reg = registry.load(self.pid)
        reg.setdefault("agents", {})["s1"] = dict({"session_id": "s1", "nombre": "arreglar-login", "tarea": "p-1",
                                                    "tarea_estado": "lanzada", "prompt_sistema": "/x/p-1.md"}, **entry)
        registry.save(self.pid, reg)
        cli = load_cli()
        cli.project = lambda _p: (self.pid, "/x/.git")
        for name, stub in (("propone", lambda *a, **k: {}), ("render_propuesta", lambda _p: "(propuesta)")):
            self.addCleanup(setattr, lote, name, getattr(lote, name))
            setattr(lote, name, stub)
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.cmd_libera(argparse.Namespace(proyecto="/x", agente="arreglar-login", fallida=False,
                                                   fuera="ninguno", usuario_confirmo=""))
        return rc, out.getvalue()

    def test_libera_prints_the_exact_cleanup_for_the_user(self):
        wt = os.path.join(self.tmp.name, "repo-wt-arreglar-login")
        os.makedirs(wt)
        rc, out = self.libera(worktree=wt, branch="lookout/arreglar-login", sin_worktree=False)
        self.assertEqual(rc, 0, out)
        root = os.path.join(self.tmp.name, "repo")
        self.assertIn("! git -C %s worktree remove %s" % (root, wt), out)
        self.assertIn("! git -C %s branch -d lookout/arreglar-login" % root, out)
        self.assertNotIn("branch -D", out)

    def test_no_cleanup_without_a_worktree(self):
        rc, out = self.libera(worktree=self.tmp.name, sin_worktree=True, branch="main")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("worktree remove", out)


class TituloPestanaTest(StateCase):
    def test_a_launched_agent_tab_gets_a_short_readable_title(self):
        import lote
        wt = os.path.join(self.tmp.name, "repo-wt-rotar-o-confirmar-9f399b")
        draft = os.path.join(self.tmp.name, "draft.md")
        with open(draft, "w") as fh:
            fh.write("tarea")
        self.stub(results={"worktree create": {
            "root_pane": {"pane_id": "w1P:p1", "tab_id": "w1P:t1"},
            "tab": {"tab_id": "w1P:t1", "label": "1", "number": 1, "pane_count": 1}}})
        old = lote.arranca
        lote.arranca = lambda *a, **k: (True, "ok")
        try:
            ok, _ = lote.lanza_uno(self.pid, os.path.join(self.tmp.name, "repo", ".git"),
                                   {"id": "p-9f399bc9aa", "texto": "**Rotar o confirmar** el token `gho_` de la org"},
                                   {"nombre": "rotar-o-confirmar-9f399b", "worktree": wt,
                                    "rama": "lookout/rotar-o-confirmar-9f399b", "base": "main"},
                                   draft, None, False, lambda m: None, "nota")
        finally:
            lote.arranca = old
        self.assertTrue(ok)
        tab = [c for c in self.calls() if c[:2] == ["tab", "rename"]]
        self.assertEqual(tab, [["tab", "rename", "w1P:t1", "Rotar o confirmar el token…"]])
        e = registry.find(registry.load(self.pid), "rotar-o-confirmar-9f399b")  # the CLI name still finds it
        self.assertEqual(e["pestana"], "Rotar o confirmar el token…")


class TextosTest(unittest.TestCase):
    def test_the_task_asks_to_send_each_decision_as_soon_as_it_exists(self):
        import lote
        import pendientes
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["LOOKOUT_STATE_DIR"], old = os.path.join(tmp, "state"), os.environ.get("LOOKOUT_STATE_DIR")
            try:
                path = os.path.join(tmp, "_pendientes.md")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("# P\n\n## Alta prioridad\n\n- [ ] Arreglar `src/a.py` — _creado: 2026-10-07_ — _id: p-0000000001_\n")
                it = pendientes.parse(path)[0]
                text = lote.render_tarea("pX", it, lote.plan_for(it, tmp, "origin/main"), [it])
            finally:
                if old is None:
                    os.environ.pop("LOOKOUT_STATE_DIR", None)
                else:
                    os.environ["LOOKOUT_STATE_DIR"] = old
        self.assertIn("Cada decisión que necesites del usuario va al supervisor en cuanto exista", text)

    def test_the_supervisor_asks_the_agent_instead_of_reading_other_plugins(self):
        with open(os.path.join(ROOT, "plugins", "lookout", "skills", "supervisa", "SKILL.md"), encoding="utf-8") as fh:
            skill = fh.read()
        self.assertIn("no los leas por tu cuenta: pídele el dato al agente", skill)


if __name__ == "__main__":
    unittest.main()

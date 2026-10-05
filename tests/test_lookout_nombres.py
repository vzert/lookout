"""0.7.2 tests: agents are named to the user by their herdr tab, and the supervisor names its own tab and session.

A tab the user named gives a new agent its name; herdr's default label (the tab number) is not a name; the user is
told the tab, never the pane id; the supervisor's tab becomes «Supervisor» unless the user named it.
herdr is tests/fixtures/herdr_stub.py.
Run: python3 -m unittest tests/test_lookout_nombres.py
"""
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "plugins", "lookout", "bin")
FIX = os.path.join(ROOT, "tests", "fixtures")
STUB = os.path.join(FIX, "herdr_stub.py")
sys.path.insert(0, BIN)

import digest  # noqa: E402
import discover  # noqa: E402
import herdr_cli  # noqa: E402
import lookout_state  # noqa: E402
import registry  # noqa: E402


def load_cli():
    loader = importlib.machinery.SourceFileLoader("lookout_cli_nombres", os.path.join(BIN, "lookout"))
    spec = importlib.util.spec_from_loader("lookout_cli_nombres", loader)
    cli = importlib.util.module_from_spec(spec)
    loader.exec_module(cli)
    return cli


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.conf = os.path.join(t, "stub.json")
        self.log = os.path.join(t, "calls.log")
        keys = ("LOOKOUT_STATE_DIR", "HERDR_STUB_CONF", "HERDR_STUB_LOG")
        self.old_env = {k: os.environ.get(k) for k in keys}
        os.environ.update({"LOOKOUT_STATE_DIR": os.path.join(t, "state"), "HERDR_STUB_CONF": self.conf,
                           "HERDR_STUB_LOG": self.log})
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
        if not os.path.exists(self.log):
            return []
        with open(self.log) as fh:
            return [json.loads(x) for x in fh if x.strip()]


class OwnLabelTest(unittest.TestCase):
    def test_default_number_is_not_a_name(self):
        self.assertEqual(herdr_cli.own_label({"label": "69", "number": 69}), "")
        self.assertEqual(herdr_cli.own_label({"label": "", "number": 3}), "")
        self.assertEqual(herdr_cli.own_label(None), "")

    def test_a_chosen_label_is(self):
        self.assertEqual(herdr_cli.own_label({"label": "Cambio DeepSeek", "number": 69}), "Cambio DeepSeek")


class DiscoverTabTest(unittest.TestCase):
    def test_discover_reads_each_tab_once(self):
        agents = [
            {"pane_id": "wS:p25", "tab_id": "wS:t25", "cwd": "/repo", "agent": "claude", "agent_session": {"value": "s1"}},
            {"pane_id": "wS:p26", "tab_id": "wS:t25", "cwd": "/repo", "agent": "claude", "agent_session": {"value": "s2"}},
            {"pane_id": "wS:p27", "tab_id": "wS:t27", "cwd": "/repo", "agent": "claude", "agent_session": {"value": "s3"}},
        ]
        tabs = {"wS:t25": {"label": "Cambio DeepSeek", "number": 69, "pane_count": 2},
                "wS:t27": {"label": "71", "number": 71, "pane_count": 1}}
        seen = []

        def tab_of(tid):
            seen.append(tid)
            return tabs.get(tid)
        found = discover.discover("/repo/.git", agents, {"/repo": "/repo/.git"}.get, tab_of)
        self.assertEqual(seen, ["wS:t25", "wS:t27"])
        self.assertEqual([(f["pestana"], f["pestana_propia"], f["pestana_panes"]) for f in found],
                         [("Cambio DeepSeek", "Cambio DeepSeek", 2), ("Cambio DeepSeek", "Cambio DeepSeek", 2),
                          ("71", "", 1)])


class NamingTest(Case):
    def test_a_tab_the_user_named_gives_the_name(self):
        reg = registry.register("pA", {"nombre": "sup", "address": "uds:/x"}, [
            {"session_id": "s1", "kind": "claude", "cwd": "/nope", "title": "Migración a DeepSeek",
             "pestana": "Cambio DeepSeek", "pestana_propia": "Cambio DeepSeek", "pestana_panes": 1}])
        e = reg["agents"]["s1"]
        self.assertEqual(e["nombre"], "cambio-deepseek")
        self.assertEqual(registry.quien(e), "Cambio DeepSeek (cambio-deepseek)")

    def test_default_or_shared_tab_keeps_the_old_rule(self):
        reg = registry.register("pA", {"nombre": "sup", "address": "uds:/x"}, [
            {"session_id": "s1", "kind": "claude", "cwd": "/nope", "title": "Arreglar login",
             "pestana": "7", "pestana_propia": "", "pestana_panes": 1},
            {"session_id": "s2", "kind": "claude", "cwd": "/nope", "title": "Otra cosa",
             "pestana": "Dos panes", "pestana_propia": "Dos panes", "pestana_panes": 2}])
        self.assertEqual([e["nombre"] for e in reg["agents"].values()], ["nope-arreglar-login", "nope-otra-cosa"])

    def test_a_name_taken_elsewhere_in_herdr_gets_a_suffix(self):
        reg = registry.register("pA", {"nombre": "sup", "address": "uds:/x"}, [
            {"session_id": "s1", "kind": "claude", "cwd": "/nope", "title": "",
             "pestana": "Cambio DeepSeek", "pestana_propia": "Cambio DeepSeek", "pestana_panes": 1}],
            ajenos={"cambio-deepseek"})
        self.assertEqual(reg["agents"]["s1"]["nombre"], "cambio-deepseek-2")

    def test_a_registered_agent_keeps_its_name_but_learns_its_tab(self):
        first = {"session_id": "s1", "kind": "claude", "cwd": "/nope", "title": "Migración a DeepSeek"}
        registry.register("pA", {"nombre": "sup", "address": "uds:/x"}, [first])
        reg = registry.register("pA", {"nombre": "sup", "address": "uds:/x"}, [dict(
            first, pestana="Cambio DeepSeek", pestana_propia="Cambio DeepSeek", pestana_panes=1)])
        e = reg["agents"]["s1"]
        self.assertEqual(e["nombre"], "nope-migracion-a-deepseek")
        self.assertEqual(registry.quien(e), "Cambio DeepSeek (nope-migracion-a-deepseek)")
        self.assertEqual(lookout_state.read_marker("s1")["nombre"], "nope-migracion-a-deepseek")

    def test_quien_without_tab_or_with_the_same_name(self):
        self.assertEqual(registry.quien({"nombre": "a"}), "a")
        self.assertEqual(registry.quien({"nombre": "a", "pestana": "a"}), "a")


class ResumenTest(Case):
    def test_summary_and_events_name_the_tab_not_the_pane(self):
        registry.save("pA", {"agents": {"s1": {"session_id": "s1", "nombre": "cambio-deepseek", "pane_id": "wS:p25",
                                               "pestana": "Cambio DeepSeek", "branch": "main"}}})
        lookout_state.append_event("pA", {"event": "blocked", "session_id": "s1", "nombre": "cambio-deepseek",
                                          "tool_name": "Bash", "detalle": "rm x.bak", "motivo": "fuera del worktree"})
        text = digest.render("pA", mark=False)
        self.assertIn("Cambio DeepSeek (cambio-deepseek) | main", text)
        self.assertIn("Cambio DeepSeek (cambio-deepseek) espera permiso", text)
        self.assertNotIn("wS:p25", text)


class EntregaTabTest(Case):
    def entrega(self, tab):
        registry.save("pA", {"agents": {"s1": {"session_id": "s1", "nombre": "nope-arreglar", "pane_id": "wS:p9",
                                               "tab_id": "wS:t9", "cwd": "/nope", "pestana": tab["label"]}}})
        with open(os.path.join(FIX, "caja-a1.ansi")) as fh:
            box = fh.read()
        self.stub(agent_get={"pane_id": "wS:p9", "tab_id": "wS:t9", "cwd": "/nope", "agent_status": "idle",
                             "agent_session": {"value": "s1"}}, tabs={"wS:t9": tab}, agent_read=box)
        cli = load_cli()
        cli.project = lambda arg: ("pA", "/nope/.git")
        cli.cmd_entrega(type("A", (), {"proyecto": "pA", "agente": "nope-arreglar", "pasos": "rename", "timeout": 1})())
        return [c for c in self.calls() if c[:2] == ["tab", "rename"]], registry.load("pA")["agents"]["s1"]

    def test_default_tab_takes_the_agent_name(self):
        renames, e = self.entrega({"label": "9", "number": 9, "pane_count": 1})
        self.assertEqual(renames, [["tab", "rename", "wS:t9", "nope-arreglar"]])
        self.assertEqual(registry.quien(e), "nope-arreglar")

    def test_a_tab_the_user_named_is_never_renamed(self):
        renames, e = self.entrega({"label": "Cambio DeepSeek", "number": 9, "pane_count": 1})
        self.assertEqual(renames, [])
        self.assertEqual(registry.quien(e), "Cambio DeepSeek (nope-arreglar)")


class LanzaTabTest(Case):
    def test_launched_agent_tab_carries_its_name(self):
        import lote
        wt = os.path.join(self.tmp.name, "repo-wt-arreglar")
        draft = os.path.join(self.tmp.name, "draft.md")
        with open(draft, "w") as fh:
            fh.write("tarea")
        # `herdr worktree create --label` names the workspace; the tab comes back as "1" (seen 2026-10-05)
        self.stub(results={"worktree create": {
            "root_pane": {"pane_id": "w1P:p1", "tab_id": "w1P:t1"},
            "tab": {"tab_id": "w1P:t1", "label": "1", "number": 1, "pane_count": 1},
            "workspace": {"workspace_id": "w1P", "label": "arreglar"}}})
        old = lote.arranca
        lote.arranca = lambda *a, **k: (True, "ok")
        try:
            ok, _ = lote.lanza_uno("pA", os.path.join(self.tmp.name, "repo", ".git"), {"id": "p-1", "texto": "x"},
                                   {"nombre": "arreglar", "worktree": wt, "rama": "lookout/arreglar", "base": "main"},
                                   draft, None, False, lambda m: None, "nota")
        finally:
            lote.arranca = old
        self.assertTrue(ok)
        self.assertIn(["tab", "rename", "w1P:t1", "arreglar"], self.calls())
        e = next(iter(registry.load("pA")["agents"].values()))
        self.assertEqual((e["tab_id"], registry.quien(e)), ("w1P:t1", "arreglar"))


class SupervisorTabTest(Case):
    ME = {"pane": "w1K:p1", "nombre": "supervisor-claude-vzert"}

    def agent(self, title="Claude Code"):
        return {"pane_id": "w1K:p1", "tab_id": "w1K:t1", "terminal_title_stripped": title}

    def box(self, name):
        with open(os.path.join(FIX, name)) as fh:
            return fh.read()

    def test_default_tab_becomes_supervisor_and_session_is_renamed(self):
        self.stub(agent_get=self.agent(), tabs={"w1K:t1": {"label": "1", "number": 1, "pane_count": 1}},
                  agent_read=self.box("caja-a1.ansi"))
        out = load_cli().nombra_supervisor(self.ME)
        calls = self.calls()
        self.assertIn(["tab", "rename", "w1K:t1", "Supervisor"], calls)
        self.assertIn(["agent", "prompt", "w1K:p1", "/rename supervisor-claude-vzert"], calls)
        self.assertIn("pestaña «Supervisor»", out)

    def test_a_tab_the_user_named_stays(self):
        self.stub(agent_get=self.agent(), tabs={"w1K:t1": {"label": "Mi tablero", "number": 1, "pane_count": 1}},
                  agent_read=self.box("caja-a1.ansi"))
        out = load_cli().nombra_supervisor(self.ME)
        self.assertFalse([c for c in self.calls() if c[:2] == ["tab", "rename"]])
        self.assertIn("la dejo", out)

    def test_a_shared_tab_stays(self):
        self.stub(agent_get=self.agent(), tabs={"w1K:t1": {"label": "1", "number": 1, "pane_count": 2}},
                  agent_read=self.box("caja-a1.ansi"))
        load_cli().nombra_supervisor(self.ME)
        self.assertFalse([c for c in self.calls() if c[:2] == ["tab", "rename"]])

    def test_no_rename_over_a_draft_or_when_already_named(self):
        self.stub(agent_get=self.agent(), tabs={"w1K:t1": {"label": "1", "number": 1, "pane_count": 1}},
                  agent_read=self.box("caja-borrador.ansi"))
        out = load_cli().nombra_supervisor(self.ME)
        self.assertFalse([c for c in self.calls() if c[:2] == ["agent", "prompt"]])
        self.assertIn("caja de entrada tiene texto", out)
        self.stub(agent_get=self.agent("supervisor-claude-vzert"),
                  tabs={"w1K:t1": {"label": "Supervisor", "number": 1, "pane_count": 1}})
        open(self.log, "w").close()
        load_cli().nombra_supervisor(self.ME)
        self.assertFalse([c for c in self.calls() if c[:2] in (["agent", "prompt"], ["tab", "rename"])])

    def test_outside_herdr_nothing_is_touched(self):
        out = load_cli().nombra_supervisor({"pane": "", "nombre": "supervisor-x"})
        self.assertEqual(self.calls(), [])
        self.assertIn("sin pane", out)


if __name__ == "__main__":
    unittest.main()

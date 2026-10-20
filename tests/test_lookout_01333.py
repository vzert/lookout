"""0.13.33: a supervisor and its agents in different permission-mode classes lose their messages (user report,
2026-10-19, supervisor-POS_MEGAMAYOREO). Claude Code holds a message between a session that bypasses permission prompts
and one that does not ("permission mode class doesn't match"), in both directions, and drops it after 5 min unanswered.
- `lookout lanza` started every fresh agent without --permission-mode (lote.py:701): it took the user's default mode,
  whatever the supervisor ran in. It now passes the supervisor's own mode; a bypass one only when the user chose it
  (`--bypass`, from the /lookout:pendientes modal).
- An agent registered while it bypasses and the supervisor does not is moved with Shift+Tab (herdr send-keys), read on
  its footer after each press, until a prompting mode that is not plan. Measured 2026-10-19 on Claude Code: the cycle of
  a session started in auto is auto → manual → accept edits → plan → auto; one started in bypass went to auto with one
  press, and a message to it held before the press was delivered after.
- A supervisor that bypasses never raises an agent: the registration says so and the supervisor tells the user.
Run: python3 -m unittest tests/test_lookout_01333.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f4 as f4  # noqa: E402
import test_lookout_f9 as f9  # noqa: E402

import digest  # noqa: E402
import herdr_cli  # noqa: E402
import lote  # noqa: E402
import modo  # noqa: E402
import registry  # noqa: E402

PID = f4.PID
SUP = f4.SUP

PIES = {
    "auto": "  ⏵⏵ auto mode on (shift+tab to cycle) · ← for agents",
    "default": "  ⏸ manual mode on · ← for agents",
    "acceptEdits": "  ⏵⏵ accept edits on (shift+tab to cycle) · ← for agents",
    "plan": "  ⏸ plan mode on (shift+tab to cycle) · ← for agents",
    "bypassPermissions": "  ⏵⏵ bypass permissions on (shift+tab to cycle)",
}


def fila(m):
    return {"type": "permission-mode", "permissionMode": m, "sessionId": "x"}


class PieTest(unittest.TestCase):
    def test_each_footer_names_its_mode(self):
        for m, pie in PIES.items():
            self.assertEqual(modo.pie("❯ \n────\n   Haiku 5.5  medium\n" + pie + "\n"), m, pie)

    def test_a_screen_without_a_footer_names_none(self):
        self.assertEqual(modo.pie(" ❯ No, exit\n   Yes, I trust this folder\n Enter to confirm · Esc to cancel"), "")

    def test_a_mode_named_above_a_dialog_is_not_its_footer(self):
        # adversary r1: the conversation can quote a footer; a dialog on screen hides the real one
        pantalla = ("⏺ el pie decía «bypass permissions on»\n\n ❯ 1. Yes\n   2. Yes, allow all edits (shift+tab)\n"
                    "   3. No\n Esc to cancel")
        self.assertEqual(modo.pie(pantalla), "")

    def test_a_list_of_background_agents_under_the_footer(self):
        # measured 2026-10-19 (wS:p24): Claude draws its running subagents below the footer
        pantalla = "❯ \n────\n" + PIES["auto"] + "\n  ⏺ main\n  ◯ goalspec:goal-adversary  Adversario del diseño"
        self.assertEqual(modo.pie(pantalla), "auto")

    def test_the_held_message_dialog_has_no_footer(self):
        # the screen of the bench agent (w1K:pN, 2026-10-19) while message 1 was held
        pantalla = ("  ⏵⏵ bypass permissions on (shift+tab to cycle)\n⏺ Held peer message — from uds:/tmp/cc-socks/90833.sock\n"
                    " Held message from another session\n Another Claude session sent a message\n"
                    " The sending session's permission mode class doesn't match this session's\n"
                    " Message body (this is what will be delivered):\n╌╌╌╌\n │ Prueba 1 de lookout\n"
                    " │ …[1 line, 105 chars total]\n╌╌╌╌\n ❯ Deny — drop it and tell the sender it was declined\n"
                    "   Deliver this message to Claude")
        self.assertEqual(modo.pie(pantalla), "")

    def test_classes(self):
        self.assertEqual(modo.clase("bypassPermissions"), "bypass")
        for m in ("default", "auto", "acceptEdits", "dontAsk"):
            self.assertEqual(modo.clase(m), "permisos", m)
        self.assertEqual(modo.clase("plan"), "")  # plan counts as bypass only when bypass is available: unknown
        self.assertEqual(modo.clase(""), "")


class LanzaTest(f4.Base):
    def lanza(self, bypass=False):
        tmp = f9.tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = os.path.join(tmp.name, "repo")
        os.makedirs(repo)
        it = f9.pendientes_md(tmp.name, "Avisar a los devs de que el README cambió")[0]
        plan = lote.plan_for(it, repo, "origin/main")
        with open(os.path.join(tmp.name, "d.md"), "w") as fh:
            fh.write("tarea")
        visto = {}
        saved = (lote.arranca, lote.herdr_cli.run_json, lote.herdr_cli.run, lote.unique_name)

        def arranca(*a, **k):
            visto.update(k)
            return True, "ok"
        lote.arranca = arranca
        lote.herdr_cli.run_json = lambda *a, **k: {"root_pane": {"pane_id": "w9:p1", "tab_id": "w9:t1"}}
        lote.herdr_cli.run = lambda *a, **k: (0, "", "")
        lote.unique_name = lambda base, agents=None: base
        try:
            ok, _ = lote.lanza_uno(PID, os.path.join(repo, ".git"), it, plan, os.path.join(tmp.name, "d.md"), None,
                                   False, lambda m: None, "nota", bypass=bypass)
        finally:
            lote.arranca, lote.herdr_cli.run_json, lote.herdr_cli.run, lote.unique_name = saved
        self.assertTrue(ok)
        return visto.get("permisos", "")

    def test_a_fresh_agent_starts_in_the_supervisors_mode(self):
        self.transcript(SUP, [fila("default"), fila("auto")])
        self.assertEqual(self.lanza(), "auto")
        self.assertEqual(lote.exec_args(None, permisos="auto")[:2], ["--permission-mode", "auto"])

    def test_a_bypassing_supervisor_raises_no_agent_unless_the_user_chose_it(self):
        self.transcript(SUP, [fila("bypassPermissions")])
        self.assertEqual(self.lanza(), "")
        self.assertEqual(self.lanza(bypass=True), "bypassPermissions")

    def test_a_supervisor_in_plan_or_unknown_passes_nothing(self):
        self.assertEqual(self.lanza(), "")  # no transcript
        self.transcript(SUP, [fila("plan")])
        self.assertEqual(self.lanza(), "")

    def test_the_proposal_tells_a_bypassing_supervisor_to_ask(self):
        self.transcript(SUP, [fila("bypassPermissions")])
        self.assertIn("--bypass", modo.aviso_lanzar(PID))
        self.transcript(SUP, [fila("auto")])
        self.assertEqual(modo.aviso_lanzar(PID), "")


class Stub(f4.Base):
    """herdr answers `agent read` with self.pies[0] and moves to the next footer on each send-keys."""
    def setUp(self):
        super().setUp()
        self.keys = []
        self.pies = []
        self.old_run = herdr_cli.run
        self.old_pausa = modo.PAUSA
        modo.PAUSA = 0

        def run(args, timeout=None, **kw):
            if args[:2] == ["agent", "read"]:
                return 0, "❯ \n" + (self.pies[0] if self.pies else ""), ""
            if args[:2] == ["agent", "send-keys"]:
                self.keys.append(args[3:])
                if len(self.pies) > 1:
                    self.pies.pop(0)
                return 0, "{}", ""
            return 0, "", ""
        herdr_cli.run = run

    def tearDown(self):
        herdr_cli.run = self.old_run
        modo.PAUSA = self.old_pausa
        super().tearDown()


class EmpataTest(Stub):
    def empata(self, sup, ag, pies, status="idle"):
        self.transcript(SUP, [fila(sup)])
        self.transcript("s-a", [fila(ag)])
        self.agent("s-a", "ag", pane_id="w1:p7")
        self.pies = [PIES[p] if p in PIES else p for p in pies]
        return modo.empata(PID, [{"session_id": "s-a", "pane_id": "w1:p7", "status": status}])["s-a"]

    def test_a_bypassing_agent_is_lowered_to_a_prompting_mode(self):
        r = self.empata("auto", "bypassPermissions", ["bypassPermissions", "default"])
        self.assertEqual(self.keys, [["shift+tab"]])
        self.assertEqual((r["estado"], r["agente"], r["ahora"]), ("bajado", "bypassPermissions", "default"))
        self.assertEqual(registry.load(PID)["agents"]["s-a"]["permisos"], "default")

    def test_an_agent_without_a_transcript_is_read_on_its_footer(self):
        # measured 2026-10-19: a session started by herdr has no transcript until its first prompt
        self.transcript(SUP, [fila("auto")])
        self.agent("s-c", "ag", pane_id="w1:p9")
        self.pies = [PIES["bypassPermissions"], PIES["default"]]
        r = modo.empata(PID, [{"session_id": "s-c", "pane_id": "w1:p9", "status": "idle"}])["s-c"]
        self.assertEqual((r["estado"], r["ahora"]), ("bajado", "default"))

    def test_plan_is_never_where_it_stops(self):
        r = self.empata("auto", "bypassPermissions", ["bypassPermissions", "plan", "auto"])
        self.assertEqual(self.keys, [["shift+tab"], ["shift+tab"]])
        self.assertEqual(r["ahora"], "auto")

    def test_no_key_without_a_footer_it_can_read(self):
        r = self.empata("auto", "bypassPermissions", [" ❯ 1. Yes\n   2. No\n Esc to cancel"])
        self.assertEqual(self.keys, [])
        self.assertEqual(r["estado"], "sin-bajar")

    def test_no_key_while_it_waits_on_a_dialog(self):
        r = self.empata("auto", "bypassPermissions", ["bypassPermissions", "default"], status="blocked")
        self.assertEqual(self.keys, [])
        self.assertEqual(r["estado"], "sin-bajar")

    def test_it_gives_up_after_a_bounded_number_of_presses(self):
        r = self.empata("auto", "bypassPermissions", ["bypassPermissions"])
        self.assertEqual(len(self.keys), modo.MAX_PULSACIONES)
        self.assertEqual(r["estado"], "sin-bajar")

    def test_a_bypassing_supervisor_never_raises_an_agent(self):
        r = self.empata("bypassPermissions", "auto", ["auto"])
        self.assertEqual(self.keys, [])
        self.assertEqual(r["estado"], "supervisor-bypass")

    def test_the_same_class_touches_nothing(self):
        self.assertIsNone(modo.empata(PID, []).get("s-a"))
        self.transcript(SUP, [fila("auto")])
        self.transcript("s-a", [fila("default")])
        self.agent("s-a", "ag")
        self.assertEqual(modo.empata(PID, [{"session_id": "s-a", "pane_id": "w1:p7", "status": "idle"}]), {})
        self.assertEqual(self.keys, [])


class DescubreTest(Stub):
    """The waiter's own registration path (alta.descubre), not modo.empata alone."""
    def test_a_discovered_bypassing_agent_is_lowered_and_its_event_says_so(self):
        import alta
        import lookout_state
        self.transcript(SUP, [fila("auto")])
        self.transcript("s-b", [fila("bypassPermissions")])
        self.pies = [PIES["bypassPermissions"], PIES["auto"]]
        agents = [{"pane_id": "w1:p8", "name": "ag-b", "agent": "claude", "agent_status": "idle", "cwd": self.repo,
                   "terminal_id": "t8", "agent_session": {"value": "s-b"}}]
        out = alta.descubre(PID, agents=agents, common_of=lambda _: self.repo + "/.git",
                            tab_of=lambda _: {"tab_id": "w1:t1", "label": "ag-b", "panes": 1})
        self.assertEqual([e.get("session_id") for e in out], ["s-b"])
        self.assertEqual(out[0].get("modo", {}).get("estado"), "bajado")
        self.assertEqual(self.keys, [["shift+tab"]])
        evs, _ = lookout_state.read_events(PID, 0)
        self.assertEqual([e["modo"]["ahora"] for e in evs if e.get("event") == "nuevo"], ["auto"])


class DigestTest(unittest.TestCase):
    def test_the_new_agent_line_says_what_happened_to_its_mode(self):
        base = {"event": "nuevo", "session_id": "s-a", "nombre": "ag", "pestana": "ag", "estado_herdr": "idle"}
        bajado = digest.describe(dict(base, modo={"estado": "bajado", "agente": "bypassPermissions", "ahora": "auto"}))
        self.assertIn("bypass", bajado)
        self.assertIn("auto", bajado)
        sup = digest.describe(dict(base, modo={"estado": "supervisor-bypass", "agente": "auto", "supervisor": "bypassPermissions"}))
        self.assertIn("díselo al usuario", sup)
        sin = digest.describe(dict(base, modo={"estado": "sin-bajar", "agente": "bypassPermissions", "supervisor": "auto"}))
        self.assertIn("díselo al usuario", sin)
        # the digest clips each line at 160 characters: the note goes before the rest, so it is never the part cut
        largo = dict(base, nombre="pendientes-en-sessionstart-largo", pestana="Pendientes en SessionStart, nombre largo",
                     renombre="a medias: herdr no renombró la pestaña",
                     modo={"estado": "supervisor-bypass", "agente": "acceptEdits", "supervisor": "bypassPermissions"})
        self.assertIn("díselo al usuario", digest.clip("- " + digest.describe(largo)))


if __name__ == "__main__":
    unittest.main()

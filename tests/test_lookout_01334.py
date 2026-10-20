"""0.13.34: a supervisor watches at most LOOKOUT_CUPO agents (10 by default; user's decision 2026-10-19). Past that a
human cannot answer the supervisor, and every Claude takes memory. An external user supervised 17 agents.
- `alta.descubre` (the only path that registers a session it did not start) registers up to the free slots, first
  queued first. The rest go to registry.json `espera_cupo`: no note, no rename, no mode match. They keep working in
  their panes (lookout does not pause them), only without a supervisor (0.13.36: the supervisor now tells each one
  to wait its turn, tests/test_lookout_01336.py). One `espera_cupo` event each, once.
- A slot frees when a registered agent is retired, relieved or its session is gone from herdr; the next pass registers
  the first of the queue still alive (`nuevo` with `desde_cola`).
- `lanza`/`pendientes`: the batch cap never passes the cupo (that cap already counts every live session of the project).
- relevo and retoma swap one agent for another and register directly: they do not go through the cupo.
Run: python3 -m unittest tests/test_lookout_01334.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f4 as f4  # noqa: E402

import digest  # noqa: E402
import lookout_state  # noqa: E402
import lote  # noqa: E402
import registry  # noqa: E402

PID = f4.PID


def herdr(sid, pane):
    return {"pane_id": pane, "name": "", "agent": "claude", "agent_status": "working", "cwd": "", "terminal_id": "t",
            "agent_session": {"value": sid}}


class Env(f4.Base):
    def setUp(self):
        super().setUp()
        for k in ("LOOKOUT_CUPO", "LOOKOUT_TOPE"):
            self.saved[k] = os.environ.pop(k, None)


class CupoTest(Env):
    def test_ten_by_default_and_never_below_one(self):
        self.assertEqual(registry.cupo(), 10)
        os.environ["LOOKOUT_CUPO"] = "4"
        self.assertEqual(registry.cupo(), 4)
        os.environ["LOOKOUT_CUPO"] = "0"
        self.assertEqual(registry.cupo(), 1)
        os.environ["LOOKOUT_CUPO"] = "x"
        self.assertEqual(registry.cupo(), 10)

    def test_the_batch_cap_never_passes_the_cupo(self):
        os.environ["LOOKOUT_TOPE"] = "5"
        os.environ["LOOKOUT_CUPO"] = "2"
        self.assertEqual(lote.tope_default(), 2)
        os.environ["LOOKOUT_CUPO"] = "8"
        self.assertEqual(lote.tope_default(), 5)


class DescubreTest(Env):
    def descubre(self, sids):
        import alta
        self.repo_git = self.repo + "/.git"
        agents = [herdr(s, "w1:p%d" % n) for n, s in enumerate(sids, 10)]
        for a in agents:
            a["cwd"] = self.repo
        return alta.descubre(PID, agents=agents, common_of=lambda _: self.repo_git,
                             tab_of=lambda p: {"tab_id": "w1:t" + p[-2:], "label": "", "panes": 1})

    def eventos(self, tipo):
        evs, _ = lookout_state.read_events(PID, 0)
        return [e for e in evs if e.get("event") == tipo]

    def test_past_the_cupo_the_rest_wait_their_turn(self):
        os.environ["LOOKOUT_CUPO"] = "2"
        out = self.descubre(["s-a", "s-b", "s-c"])
        self.assertEqual([e["session_id"] for e in out], ["s-a", "s-b"])
        reg = registry.load(PID)
        self.assertEqual(sorted(reg["agents"]), ["s-a", "s-b"])
        self.assertEqual([x["session_id"] for x in reg["espera_cupo"]], ["s-c"])
        self.assertIsNone(lookout_state.read_marker("s-c"))  # no supervisor for it
        self.assertEqual([e["session_id"] for e in self.eventos("espera_cupo")], ["s-c"])
        # the next pass says nothing new about the same queue
        self.assertEqual(self.descubre(["s-a", "s-b", "s-c"]), [])
        self.assertEqual(len(self.eventos("espera_cupo")), 1)

    def test_a_freed_slot_goes_to_the_oldest_waiting(self):
        os.environ["LOOKOUT_CUPO"] = "1"
        self.descubre(["s-a", "s-b"])
        self.descubre(["s-a", "s-b", "s-c"])
        self.assertEqual([x["session_id"] for x in registry.load(PID)["espera_cupo"]], ["s-b", "s-c"])
        out = self.descubre(["s-b", "s-c"])  # s-a's session is gone from herdr
        self.assertEqual([(e["session_id"], e.get("desde_cola")) for e in out], [("s-b", True)])
        self.assertEqual([x["session_id"] for x in registry.load(PID)["espera_cupo"]], ["s-c"])

    def test_a_waiting_session_that_died_leaves_the_queue(self):
        os.environ["LOOKOUT_CUPO"] = "1"
        self.descubre(["s-a", "s-b"])
        self.descubre(["s-a"])
        self.assertEqual(registry.load(PID).get("espera_cupo"), [])

    def test_a_herdr_failure_keeps_the_queue_and_its_order(self):
        # adversary r1: agent_list() is [] when herdr fails; the queue was emptied and re-queued in a new order
        os.environ["LOOKOUT_CUPO"] = "1"
        self.descubre(["s-a", "s-b", "s-c"])
        self.descubre([])
        self.assertEqual([x["session_id"] for x in registry.load(PID)["espera_cupo"]], ["s-b", "s-c"])
        self.descubre(["s-a", "s-c", "s-b"])
        self.assertEqual([x["session_id"] for x in registry.load(PID)["espera_cupo"]], ["s-b", "s-c"])
        self.assertEqual(len(self.eventos("espera_cupo")), 2)

    def test_a_list_without_the_supervisors_pane_is_not_trusted(self):
        os.environ["LOOKOUT_CUPO"] = "1"
        lk = lookout_state.read_json(os.path.join(lookout_state.project_dir(PID), "lock.json"))
        lk["supervisor"]["pane"] = "w1:p99"
        lookout_state.write_json(os.path.join(lookout_state.project_dir(PID), "lock.json"), lk)
        self.assertEqual(self.descubre(["s-a"]), [])  # herdr answered without the supervisor: nothing changes
        self.assertEqual(registry.load(PID).get("agents", {}), {})

    def test_inicia_registers_within_the_cupo_too(self):
        # codex r1: `lookout inicia` registered every agent it found (12 of 12); it goes through alta.filtra_cupo
        import alta
        os.environ["LOOKOUT_CUPO"] = "2"
        self.agent("s-k", "conocido", pane_id="w1:p10")
        todos = [herdr(s, "w1:p%d" % n) for n, s in enumerate(["s-k", "s-x", "s-y", "s-z"], 10)]
        found = [{"kind": "claude", "session_id": s, "pane_id": "w1:p%d" % n}
                 for n, s in enumerate(["s-k", "s-x", "s-y", "s-z"], 10)] + [{"kind": "shell", "pane_id": "w1:p20"}]
        sup = {"session_id": f4.SUP}
        out = alta.filtra_cupo(PID, found, todos, sup)
        self.assertEqual([f.get("session_id") for f in out], ["s-k", "s-x", None])
        self.assertEqual([x["session_id"] for x in registry.load(PID)["espera_cupo"]], ["s-y", "s-z"])
        with open(os.path.join(f4.BIN, "lookout"), encoding="utf-8") as fh:
            self.assertIn("alta.filtra_cupo(pid, discover.discover(common, todos), todos, me)", fh.read())

    def test_inicia_with_an_untrusted_list_keeps_the_cupo_and_the_queue(self):
        # codex r2: filtra_cupo returned every finding when the list did not show the supervisor
        import alta
        os.environ["LOOKOUT_CUPO"] = "2"
        self.agent("s-k", "conocido", pane_id="w1:p10")
        todos = [herdr(s, "w1:p%d" % n) for n, s in enumerate(["s-x", "s-y"], 11)]  # s-k missing from the list
        found = [{"kind": "claude", "session_id": s} for s in ("s-k", "s-x", "s-y")]
        out = alta.filtra_cupo(PID, found, todos, {"session_id": f4.SUP, "pane": "w1:p99"})
        self.assertEqual([f["session_id"] for f in out], ["s-k", "s-x"])
        # nothing leaves the queue; since 0.13.36 the one left out is added at its end (and warned)
        self.assertEqual([x["session_id"] for x in registry.load(PID)["espera_cupo"]], ["s-y"])

    def test_the_supervisors_pane_held_by_another_session_is_not_it(self):
        import alta
        sup = {"session_id": "sup", "pane": "w:p1"}
        self.assertFalse(alta.lista_fiable([herdr("otra", "w:p1")], sup))
        self.assertTrue(alta.lista_fiable([herdr("sup", "w:p9")], sup))  # moved pane, same session
        self.assertTrue(alta.lista_fiable([{"pane_id": "w:p1", "agent_session": None}], sup))  # session not shown yet

    def test_a_queued_session_missing_from_one_pass_keeps_its_turn(self):
        # codex r5: alive in herdr but not found by discover this pass; a newer one took the freed slot
        import alta
        os.environ["LOOKOUT_CUPO"] = "1"
        self.descubre(["s-a", "s-b", "s-c"])
        reg = registry.load(PID)
        todos = [herdr(s, "w1:p%d" % n) for n, s in enumerate(["s-b", "s-c"], 11)]  # s-a gone: one slot free
        entran, _, _ = alta.turno(PID, reg, [{"session_id": "s-c", "pane_id": "w1:p12"}], todos)
        self.assertEqual(entran, [])
        self.assertEqual([x["session_id"] for x in registry.load(PID)["espera_cupo"]], ["s-b", "s-c"])

    def test_retired_and_relieved_agents_hold_no_slot(self):
        os.environ["LOOKOUT_CUPO"] = "2"
        self.agent("s-old", "viejo", tarea_estado="relevada", pane_id="w1:p10")
        self.agent("s-ret", "ret", retirado="2026-10-19T10:00:00", pane_id="w1:p11")
        self.agent("s-new", "nuevo", tarea_estado="trabajando", relevo_de="s-old", pane_id="w1:p12")
        out = self.descubre(["s-new", "s-x", "s-y"])
        self.assertEqual([e["session_id"] for e in out], ["s-x"])

    def test_a_launch_not_yet_in_herdr_holds_its_slot(self):
        os.environ["LOOKOUT_CUPO"] = "1"
        self.agent("s-l", "lanzado", tarea="p-1", tarea_estado="lanzando", pane_id="w1:p40")
        self.assertEqual(self.descubre(["s-x"]), [])


class DigestTest(Env):
    def test_the_waiting_event_names_its_tab_and_the_cupo(self):
        line = digest.describe({"event": "espera_cupo", "session_id": "s-c", "nombre": "", "pestana": "Cambio X",
                                "pane": "w1:p12", "cupo": 10})
        self.assertIn("Cambio X", line)
        self.assertIn("10", line)
        self.assertIn("pregúntale al usuario", line)  # 0.13.36: without its `to`

    def test_a_turn_from_the_queue_says_so(self):
        line = digest.describe({"event": "nuevo", "session_id": "s-b", "nombre": "b", "pestana": "b",
                                "estado_herdr": "working", "desde_cola": True})
        self.assertIn("turno", line)

    def test_resumen_shows_the_cupo_line_while_someone_waits(self):
        self.agent("s-a", "a", pane_id="w1:p10")
        reg = registry.load(PID)
        reg["espera_cupo"] = [{"session_id": "s-c", "pane_id": "w1:p12", "pestana": "Cambio X", "desde": 1.0}]
        registry.save(PID, reg)
        out = digest.render(PID, mark=False)
        self.assertIn("CUPO: 10, lleno en la última pasada", out)
        self.assertIn("1 esperan turno (Cambio X)", out)


if __name__ == "__main__":
    unittest.main()

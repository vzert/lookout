"""0.13.36: a queued agent is told to wait its turn (user's decision 2026-10-19, after 0.13.34 was published: the gap
of an agent that kept working unsupervised was not acceptable). When the cupo is full, the waiter matches the waiting
agent's permission mode (a message between a bypassing session and one that is not is held) and puts its SendMessage
`to` in the `espera_cupo` event; the supervisor sends it «Espera tu turno» once. When its turn comes, its note and
«Ya es tu turno».
Run: python3 -m unittest tests/test_lookout_01336.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f4 as f4  # noqa: E402
from test_lookout_01334 import Env, herdr  # noqa: E402

import digest  # noqa: E402
import lookout_state  # noqa: E402

PID = f4.PID


class AvisoTest(Env):
    """User's decision 2026-10-19 (after 0.13.34 was published): a waiting agent must not keep working unsupervised.
    The supervisor tells it by SendMessage to wait its turn, and to go on when its turn comes. lookout gives the `to`
    and matches its permission mode first (a message between a bypassing session and one that is not is held)."""
    def setUp(self):
        super().setUp()
        import modo
        import sesiones
        self.modo, self.sesiones = modo, sesiones
        self.old = (modo.empata, sesiones.de)
        self.empatados = []

        def empata(pid, found):
            self.empatados += [f["session_id"] for f in found]
            return {f["session_id"]: {"estado": "bajado", "agente": "bypassPermissions", "ahora": "auto"}
                    for f in found if f["session_id"] == "s-c"}
        modo.empata = empata
        sesiones.de = lambda sid, base=None: {"name": "nombre-" + sid, "socket": ""} if sid != "s-d" else None

    def tearDown(self):
        self.modo.empata, self.sesiones.de = self.old
        super().tearDown()

    def test_a_queued_agent_gets_its_to_and_its_mode_matched(self):
        import alta
        os.environ["LOOKOUT_CUPO"] = "1"
        agents = [herdr(s, "w1:p%d" % n) for n, s in enumerate(["s-a", "s-c", "s-d"], 10)]
        for a in agents:
            a["cwd"] = self.repo
        alta.descubre(PID, agents=agents, common_of=lambda _: self.repo + "/.git",
                      tab_of=lambda p: {"tab_id": "w1:t" + p[-2:], "label": "", "panes": 1})
        self.assertIn("s-c", self.empatados)
        self.assertIn("s-d", self.empatados)
        evs, _ = lookout_state.read_events(PID, 0)
        cola = {e["session_id"]: e for e in evs if e.get("event") == "espera_cupo"}
        self.assertEqual(cola["s-c"].get("to"), "nombre-s-c")
        self.assertEqual(cola["s-c"]["modo"]["estado"], "bajado")
        self.assertIsNone(cola["s-d"].get("to"))

    def test_the_line_tells_the_supervisor_to_send_the_wait_message(self):
        base = {"event": "espera_cupo", "session_id": "s-c", "pestana": "Cambio X", "pane": "w1:p12", "cupo": 10}
        con = digest.describe(dict(base, to="cambio-x"))
        self.assertIn("SendMessage to=cambio-x", con)
        self.assertIn("Espera tu turno", con)
        sin = digest.describe(base)
        self.assertIn("pregúntale al usuario", sin)
        modo = digest.describe(dict(base, to="cambio-x", modo={"estado": "sin-bajar", "agente": "bypassPermissions",
                                                                "supervisor": "auto"}))
        self.assertIn("MODO DISTINTO", modo)

    def test_a_long_tab_never_cuts_the_to(self):
        # adversary r1: the digest clips at 160 and the `to` came last (a 60-character tab cut it)
        ev = {"event": "espera_cupo", "session_id": "s-c", "pestana": "x" * 120, "pane": "w1:p12", "cupo": 10,
              "to": "agente-sesion-larga-de-treinta", "modo": {"estado": "bajado", "agente": "bypassPermissions",
                                                              "ahora": "auto"}}
        line = digest.clip(digest.describe(ev))
        self.assertIn("SendMessage to=agente-sesion-larga-de-treinta «Espera tu turno»", line)
        self.assertIn("xxxxxxxxxxxx", line)

    def test_inicia_with_an_untrusted_list_queues_and_warns_the_rest(self):
        # adversary r1: those left out by an untrusted list were neither queued nor warned
        import alta
        import registry
        os.environ["LOOKOUT_CUPO"] = "1"
        self.agent("s-k", "conocido", pane_id="w1:p10")
        reg = registry.load(PID)
        reg["espera_cupo"] = [{"session_id": "s-q", "pane_id": "w1:p19", "pestana": "", "desde": 1.0}]
        registry.save(PID, reg)
        found = [{"kind": "claude", "session_id": s, "pane_id": "w1:p1%d" % n} for n, s in enumerate(["s-k", "s-c"])]
        out = alta.filtra_cupo(PID, found, [herdr("s-c", "w1:p11")], {"session_id": f4.SUP, "pane": "w1:p99"})
        self.assertEqual([f["session_id"] for f in out], ["s-k"])
        self.assertEqual([x["session_id"] for x in registry.load(PID)["espera_cupo"]], ["s-q", "s-c"])
        evs, _ = lookout_state.read_events(PID, 0)
        self.assertEqual([e["session_id"] for e in evs if e.get("event") == "espera_cupo"], ["s-c"])
        self.assertIn("s-c", self.empatados)

    def test_a_mode_it_could_not_match_leads_the_line(self):
        # adversary r2: «MODO DISTINTO» came last and the 160 clip cut it; the message would be held
        for estado in ("sin-bajar", "supervisor-bypass"):
            ev = {"event": "espera_cupo", "session_id": "s-c", "pestana": "x" * 120, "cupo": 10, "to": "t" * 80,
                  "modo": {"estado": estado, "agente": "bypassPermissions", "supervisor": "auto"}}
            line = digest.clip_evento(ev, digest.describe(ev))  # how render shows it since codex r1
            self.assertIn("xxxxxxxxxxxx", line)  # adversary r3: its tab too, the only way to name it
            self.assertIn("MODO DISTINTO", line)
            self.assertIn("aprobarlo", line)

    def test_a_long_to_is_never_cut(self):
        # codex r1: nothing bounds a session's name; a `to` of 120 lost itself and the message to the 160 clip
        ev = {"event": "espera_cupo", "session_id": "s-c", "pestana": "x" * 120, "cupo": 10, "to": "t" * 120}
        line = digest.clip_evento(ev, "- " + digest.describe(ev))
        self.assertIn("SendMessage to=%s «Espera tu turno»" % ("t" * 120), line)
        self.assertIn("xxxxxxxxxxxx", line)
        otro = {"event": "idle", "session_id": "s-a", "nombre": "a" * 300}
        self.assertLessEqual(len(digest.clip_evento(otro, "- " + digest.describe(otro))), digest.MAX_COLS)

    def test_an_untrusted_list_never_lets_a_new_one_pass_the_queue(self):
        # codex r3: cupo 2, one registered, s-q queued, new s-c: s-c was admitted ahead of s-q
        import alta
        import registry
        os.environ["LOOKOUT_CUPO"] = "2"
        self.agent("s-k", "conocido", pane_id="w1:p10")
        reg = registry.load(PID)
        reg["espera_cupo"] = [{"session_id": "s-q", "pane_id": "w1:p19", "pestana": "", "desde": 1.0}]
        registry.save(PID, reg)
        found = [{"kind": "claude", "session_id": s, "pane_id": "w1:p1%d" % n} for n, s in enumerate(["s-k", "s-c"])]
        out = alta.filtra_cupo(PID, found, [herdr("s-c", "w1:p11")], {"session_id": f4.SUP, "pane": "w1:p99"})
        self.assertEqual([f["session_id"] for f in out], ["s-k"])
        self.assertEqual([x["session_id"] for x in registry.load(PID)["espera_cupo"]], ["s-q", "s-c"])

    def test_an_untrusted_list_never_admits_a_queued_one(self):
        # codex r4: cupo 3, registered a, queued q, found q and c: q was registered and stayed in the queue
        import alta
        import registry
        os.environ["LOOKOUT_CUPO"] = "3"
        self.agent("s-a", "a", pane_id="w1:p10")
        reg = registry.load(PID)
        reg["espera_cupo"] = [{"session_id": "s-q", "pane_id": "w1:p19", "pestana": "", "desde": 1.0}]
        registry.save(PID, reg)
        found = [{"kind": "claude", "session_id": s, "pane_id": "w1:p1%d" % n} for n, s in enumerate(["s-q", "s-c"])]
        out = alta.filtra_cupo(PID, found, [herdr("s-c", "w1:p11")], {"session_id": f4.SUP, "pane": "w1:p99"})
        self.assertEqual([f["session_id"] for f in out], ["s-c"])
        self.assertEqual([x["session_id"] for x in registry.load(PID)["espera_cupo"]], ["s-q"])

    def test_inicia_asks_the_message_for_the_ones_already_waiting(self):
        # codex r4: after a restart of the supervisor, those queued before got no new line
        with open(os.path.join(f4.BIN, "lookout"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("Ya esperaba antes de este inicia", src)
        self.assertIn("sesiones.to_texto(x)", src)

    def test_a_queued_agent_wakes_the_supervisor(self):
        # codex r5: espera_cupo was not a wake type: with the cupo full nothing woke the supervisor to send the message
        self.assertIn("espera_cupo", digest.WAKE_TYPES.split(","))

    def test_a_mode_it_could_not_match_still_sends_the_message(self):
        # codex r5: the user's ask has no exception; a held message reaches it once the user approves it
        ev = {"event": "espera_cupo", "session_id": "s-c", "pestana": "Cambio X", "cupo": 10, "to": "cambio-x",
              "modo": {"estado": "sin-bajar", "agente": "bypassPermissions", "supervisor": "auto"}}
        line = digest.clip_evento(ev, digest.describe(ev))
        self.assertIn("SendMessage to=cambio-x «Espera tu turno»", line)
        self.assertIn("aprobarlo", line)

    def test_its_turn_line_tells_the_supervisor_to_say_go_on(self):
        line = digest.describe({"event": "nuevo", "session_id": "s-b", "nombre": "b", "pestana": "b",
                                "estado_herdr": "idle", "desde_cola": True})
        self.assertIn("Ya es tu turno", line)

    def test_the_skill_carries_both_messages(self):
        with open(os.path.join(f4.ROOT, "plugins", "lookout", "skills", "supervisa", "SKILL.md"), encoding="utf-8") as fh:
            skill = fh.read()
        self.assertIn("«Espera tu turno»", skill)
        self.assertIn("«Ya es tu turno»", skill)


if __name__ == "__main__":
    unittest.main()

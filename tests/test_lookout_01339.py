"""0.13.39 (p-c1cb6123e4): the supervisor reacts to a held message, not only at registration.

0.13.33 matches an agent's permission mode only when it registers it. An agent moved to bypass hours later (or one
whose footer could not be read then) holds every message of the supervisor until the user approves it, and Claude
Code drops it after 5 min. The sender gets a [Cross-session delivery notice] as a prompt of its own session (measured
2026-10-19 in the 0.13.33 bench, texts below verbatim but for the msg_id): «held by that session» when it is held, «denied by the
recipient user» when the dialog is closed. The supervisor's UserPromptSubmit hook reads it, finds the agent by the
recipient's socket (<config>/sessions/<pid>.json, messagingSocketPath), lowers its mode when no dialog is on its screen,
and puts one `retenido` line in the digest, what to do first.
Run: python3 -m unittest tests/test_lookout_01339.py
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f4 as f4  # noqa: E402

import digest  # noqa: E402
import lookout_state  # noqa: E402
import on_supervisor  # noqa: E402
import supervisor_md  # noqa: E402

PID, SUP = f4.PID, f4.SUP
SOCK = "/tmp/cc-socks/42658.sock"
MSG = "msg00001-de-la-prueba-retenido"  # the bench's real msg_id is a UUID: the public export refuses those
HELD = ("[Cross-session delivery notice] Your message to another session was held by that session (recipient: uds:%s; "
        "msg_id: %s). NOT delivered: its Claude has not seen it. Do not report it as delivered, do not wait for a "
        "reply, and do not resend while held. The usual cause is that the two sessions run in different permission "
        "modes: a terminal session then asks its user to approve, but a Claude Desktop or non-interactive session "
        "cannot ask, so there the hold expires undelivered unless the modes come to match. A session can also be set "
        "to hold every message. Another notice follows on release, denial or expiry. Tell your user what is held and "
        "why, or choose another approach." % (SOCK, MSG))
DENIED = ("[Cross-session delivery notice] Your message to another session was denied by the recipient user "
          "(recipient: uds:%s; msg_id: %s). Not delivered to that session's Claude. Do not wait for a reply; continue, "
          "or choose another approach." % (SOCK, MSG))
FOOTER_BYPASS = "texto\n⏵⏵ bypass permissions on (shift+tab to cycle)\n"
FOOTER_AUTO = "texto\n⏵⏵ auto mode on (shift+tab to cycle)\n"
DIALOG = (" Held message from another session\n ❯ Deny — drop it and tell the sender it was declined\n"
          "   Deliver this message to Claude\n Enter to confirm · Esc to cancel\n")


class RetenidoTest(f4.Base):
    def setUp(self):
        super().setUp()
        import herdr_cli
        import modo
        import sesiones
        self.herdr_cli, self.modo, self.sesiones = herdr_cli, modo, sesiones
        self.old = (herdr_cli.run, modo.del_supervisor, modo.de_sesion, modo.PAUSA, sesiones.vivo)
        self.screen = [FOOTER_BYPASS]
        self.keys = []

        self.en_pane = "s-ag"  # the session herdr shows on w1:p7

        def run(args, *a, **kw):
            if args[:2] == ["agent", "get"]:
                return 0, json.dumps({"result": {"agent": {"agent_session": {"value": self.en_pane}}}}), ""
            if args[:2] == ["agent", "send-keys"]:
                self.keys.append(args[3])
                self.screen[0] = FOOTER_AUTO
                return 0, "", ""
            if args[:2] == ["agent", "read"]:
                return 0, self.screen[0], ""
            return 0, "", ""
        herdr_cli.run = run
        modo.del_supervisor = lambda pid: "auto"
        modo.de_sesion = lambda sid: ""
        modo.PAUSA = 0
        sesiones.vivo = lambda pid, proc_start=None: True
        self.cfg = os.path.join(self.tmp.name, "cfg")
        os.makedirs(os.path.join(self.cfg, "sessions"))
        self.saved["CLAUDE_CONFIG_DIR"] = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = self.cfg
        with open(os.path.join(self.cfg, "sessions", "42658.json"), "w") as fh:
            json.dump({"pid": 42658, "sessionId": "s-ag", "procStart": "x", "name": "cambio-x",
                       "messagingSocketPath": SOCK, "updatedAt": 1}, fh)
        self.agent("s-ag", "cambio-x", pane_id="w1:p7")
        supervisor_md.mark_supervisor(SUP, PID)

    def tearDown(self):
        (self.herdr_cli.run, self.modo.del_supervisor, self.modo.de_sesion, self.modo.PAUSA,
         self.sesiones.vivo) = self.old
        super().tearDown()

    def notice(self, text):
        on_supervisor.handle({"session_id": SUP, "hook_event_name": "UserPromptSubmit", "prompt": text},
                             via_async=True)

    def send(self, mid, ts=None):
        supervisor_md.log(PID, {"tipo": "respuesta", "session_id": SUP, "to": "cambio-x", "texto": "m",
                                "msg_id": mid, "mensaje": "m", **({"ts": ts} if ts else {})})

    def retenidos(self):
        return [e for e in lookout_state.read_events(PID, 0)[0] if e.get("event") == "retenido"]

    def test_a_held_notice_is_never_the_users_answer_in_the_chat(self):
        import decisiones
        decisiones.abre(PID, "¿Publico?")
        self.notice(HELD)
        self.assertFalse([x for x in supervisor_md.read_log(PID) if x.get("tipo") == "usuario"])

    def test_a_held_notice_with_the_dialog_on_screen_presses_nothing_and_asks_the_user(self):
        self.screen[0] = DIALOG
        self.modo.de_sesion = lambda sid: "bypassPermissions"
        self.notice(HELD)
        self.assertEqual(self.keys, [])
        evs = self.retenidos()
        self.assertEqual(len(evs), 1)
        ev = evs[0]
        self.assertEqual((ev["estado"], ev["destino"], ev["to"], ev["msg_id"]), ("retenido", "s-ag", "cambio-x", MSG))
        self.assertEqual(ev["session_id"], "")  # codex r6: never an event of the agent's
        line = digest.clip_evento(ev, digest.describe(ev))
        self.assertTrue(line.split(" ", 1)[1].startswith("RETENIDO"), line)
        self.assertIn("apruebe", line)
        self.assertIn("cambio-x", line)

    def test_a_held_notice_with_a_readable_bypass_footer_lowers_it(self):
        self.notice(HELD)
        self.assertEqual(self.keys, ["shift+tab"])
        ev = self.retenidos()[0]
        self.assertEqual(ev["modo"]["estado"], "bajado")
        import registry
        self.assertEqual(registry.load(PID)["agents"]["s-ag"]["permisos"], "auto")

    def test_the_same_notice_twice_makes_one_event(self):
        self.screen[0] = DIALOG
        self.notice(HELD)
        self.notice(HELD)
        self.assertEqual(len(self.retenidos()), 1)

    def test_a_denied_one_lowers_the_agent_and_says_what_to_resend(self):
        on_supervisor.handle({"session_id": SUP, "hook_event_name": "PostToolUse", "tool_name": "SendMessage",
                              "tool_input": {"to": "cambio-x", "message": "Sí, sigue con la prueba 3"},
                              "tool_response": {"success": True, "message": "→ cambio-x", "msg_id": MSG}})
        self.screen[0] = DIALOG
        self.notice(HELD)
        self.screen[0] = FOOTER_BYPASS
        self.notice(DENIED)
        evs = self.retenidos()
        self.assertEqual([e["estado"] for e in evs], ["retenido", "negado"])
        self.assertEqual(self.keys, ["shift+tab"])
        line = digest.clip_evento(evs[1], digest.describe(evs[1]))
        self.assertIn("reenvía", line)
        self.assertIn("to=cambio-x", line)
        self.assertIn("lookout reenvia %s %s" % (PID, MSG), line)
        self.assertIn("Sí, sigue con la prueba 3", line)
        self.assertLess(line.index("reenvía"), line.index("Sí, sigue"))

    def test_the_msg_id_of_a_send_goes_to_the_log_as_a_string_response_too(self):
        on_supervisor.handle({"session_id": SUP, "hook_event_name": "PostToolUse", "tool_name": "SendMessage",
                              "tool_input": {"to": "cambio-x", "message": "hola"},
                              "tool_response": json.dumps({"success": True, "msg_id": MSG})})
        r = [x for x in supervisor_md.read_log(PID) if x.get("tipo") == "respuesta"]
        self.assertEqual(r[-1].get("msg_id"), MSG)

    def test_same_class_means_the_agent_holds_every_message(self):
        self.screen[0] = FOOTER_AUTO
        self.notice(HELD)
        ev = self.retenidos()[0]
        self.assertEqual(self.keys, [])
        line = digest.describe(ev)
        self.assertIn("retiene todo", line)

    def test_a_bypassing_supervisor_never_raises_it(self):
        self.modo.del_supervisor = lambda pid: "bypassPermissions"
        self.screen[0] = FOOTER_AUTO
        self.notice(HELD)
        self.assertEqual(self.keys, [])
        self.assertIn("MODO DISTINTO", digest.describe(self.retenidos()[0]))

    def test_a_socket_of_no_agent_of_the_project_still_tells_the_supervisor(self):
        self.notice(HELD.replace(SOCK, "/tmp/cc-socks/1.sock"))
        ev = self.retenidos()[0]
        self.assertEqual(self.keys, [])
        self.assertIn("RETENIDO", digest.describe(ev))

    def test_it_wakes_the_supervisor(self):
        self.assertIn("retenido", digest.WAKE_TYPES.split(","))

    def test_a_long_message_never_cuts_the_action(self):
        on_supervisor.handle({"session_id": SUP, "hook_event_name": "PostToolUse", "tool_name": "SendMessage",
                              "tool_input": {"to": "cambio-x", "message": "y" * 500},
                              "tool_response": {"success": True, "msg_id": MSG}})
        self.notice(DENIED)
        ev = self.retenidos()[0]
        line = digest.clip_evento(ev, digest.describe(ev))
        self.assertIn("to=cambio-x", line)
        self.assertLessEqual(len(line), 400)

    # codex r1
    def test_a_resend_gives_the_whole_text_not_the_digest_cut(self):
        import retenido
        largo = "Primera línea.\n" + "z" * 900 + " FIN"
        on_supervisor.handle({"session_id": SUP, "hook_event_name": "PostToolUse", "tool_name": "SendMessage",
                              "tool_input": {"to": "cambio-x", "message": largo},
                              "tool_response": {"success": True, "msg_id": MSG}})
        self.assertEqual(retenido.mensaje(PID, MSG), largo)

    def test_lookout_reenvia_prints_it_whole(self):
        largo = "Línea 1\n  Línea 2 «con comillas»"
        on_supervisor.handle({"session_id": SUP, "hook_event_name": "PostToolUse", "tool_name": "SendMessage",
                              "tool_input": {"to": "cambio-x", "message": largo},
                              "tool_response": {"success": True, "msg_id": MSG}})
        r = self.run_lk("reenvia", PID, MSG)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, largo + "\n")
        self.assertNotEqual(self.run_lk("reenvia", PID, "otro").returncode, 0)

    def test_a_pane_herdr_shows_with_another_session_is_never_pressed(self):
        self.en_pane = "s-otra"
        self.notice(HELD)
        self.assertEqual(self.keys, [])
        line = digest.describe(self.retenidos()[0])
        self.assertIn("no veo su pane", line)

    def test_a_retired_agent_is_never_pressed(self):
        self.agent("s-ag", "cambio-x", pane_id="w1:p7", retirado="2026-10-20T10:00:00")
        self.notice(HELD)
        self.assertEqual(self.keys, [])

    def test_denied_after_held_lowered_it_is_no_hold_everything(self):
        self.send(MSG)
        self.notice(HELD)
        self.notice(DENIED)
        ev = self.retenidos()[1]
        self.assertEqual(ev["modo"]["estado"], "bajado")
        line = digest.describe(ev)
        self.assertIn("reenvía", line)
        self.assertNotIn("retiene todo", line)
        self.assertEqual(self.keys, ["shift+tab"])

    def test_the_manual_way_out_never_stops_at_plan(self):
        self.screen[0] = DIALOG
        self.modo.de_sesion = lambda sid: "bypassPermissions"
        self.notice(HELD)
        self.assertIn("ni plan", digest.describe(self.retenidos()[0]))

    def test_it_is_neither_folded_nor_the_agents_state(self):
        import deliver
        import heuristicas
        self.assertIn("retenido", deliver.NO_DEL_AGENTE)
        self.assertIn("retenido", digest.KEEP_ALL)
        self.assertIn("retenido", heuristicas.NO_ESTADO)
        self.assertIn("retenido", heuristicas.SINTETICOS)

    def test_a_wording_never_seen_is_never_a_delivery(self):
        # adversary r2: «timed out», «dropped»… fell to «ENTREGADO … nada que reenviar»
        import retenido
        for que in ("timed out", "dropped by that session", "lost"):
            a = retenido.lee("[Cross-session delivery notice] Your message to another session was %s "
                             "(recipient: uds:%s; msg_id: %s)." % (que, SOCK, MSG))
            self.assertEqual(a["estado"], "desconocido", que)
        for que in ("released by that session", "delivered after being held"):
            a = retenido.lee("[Cross-session delivery notice] Your message to another session was %s "
                             "(recipient: uds:%s; msg_id: %s)." % (que, SOCK, MSG))
            self.assertEqual(a["estado"], "liberado", que)
        self.notice("[Cross-session delivery notice] Your message to another session was dropped "
                    "(recipient: uds:%s; msg_id: %s)." % (SOCK, MSG))
        line = digest.describe(self.retenidos()[0])
        self.assertNotIn("ENTREGADO", line)
        self.assertIn("no sé si llegó", line)

    def test_a_negated_release_is_never_a_delivery(self):
        # codex r3
        import retenido
        for que in ("release failed", "not released", "released, then dropped undelivered"):
            a = retenido.lee("[Cross-session delivery notice] Your message to another session was %s "
                             "(recipient: uds:%s; msg_id: %s)." % (que, SOCK, MSG))
            self.assertNotEqual(a["estado"], "liberado", que)

    def test_a_cached_lowering_needs_the_supervisor_still_prompting(self):
        # codex r3
        self.notice(HELD)
        self.modo.del_supervisor = lambda pid: "bypassPermissions"
        self.screen[0] = DIALOG
        self.notice(DENIED)
        ev = self.retenidos()[1]
        self.assertNotEqual(ev["modo"]["estado"], "bajado")
        self.assertNotIn("→ reenvía", digest.describe(ev))

    def test_a_reused_lowering_never_extends_its_window(self):
        # codex r3
        import retenido
        self.send(MSG)
        self.notice(HELD)
        evs, _ = lookout_state.read_events(PID, 0)
        t0 = [e for e in evs if e.get("event") == "retenido"][0]["ts"]
        self.screen[0] = DIALOG
        self.notice(DENIED)
        self.assertIsNotNone(retenido._bajado_antes(PID, "s-ag", now=t0 + retenido.RECIENTE_S - 1, enviado=t0 - 1))
        self.assertIsNone(retenido._bajado_antes(PID, "s-ag", now=t0 + retenido.RECIENTE_S + 1, enviado=t0 - 1))

    def test_a_denied_with_no_footer_after_a_recent_lowering_is_still_lowered(self):
        self.send(MSG)
        self.notice(HELD)
        self.screen[0] = DIALOG
        self.notice(DENIED)
        ev = self.retenidos()[1]
        self.assertEqual(ev["modo"]["estado"], "bajado")
        self.assertEqual(self.keys, ["shift+tab"])

    def test_a_second_message_held_before_the_lowering_is_no_hold_everything(self):
        # codex r2: A and B held; A's held lowers it; B's denied finds the classes equal
        self.send(MSG)
        self.send("b" * 8 + MSG[8:])
        self.notice(HELD)
        self.notice(DENIED.replace(MSG, "b" * 8 + MSG[8:]))
        ev = self.retenidos()[1]
        self.assertEqual(ev["modo"]["estado"], "bajado")
        self.assertNotIn("retiene todo", digest.describe(ev))

    def test_a_message_sent_after_the_lowering_is_not_explained_by_it(self):
        # codex r4: held after the Shift+Tab: the classes match, so it holds every message
        import time
        self.send(MSG)
        self.notice(HELD)
        otro = "c" * 8 + MSG[8:]
        self.send(otro, ts=time.time() + 5)
        self.notice(DENIED.replace(MSG, otro))
        ev = self.retenidos()[1]
        self.assertEqual(ev["modo"]["estado"], "iguales")
        self.assertIn("retiene todo", digest.describe(ev))

    def test_the_cutoff_is_taken_before_the_first_press(self):
        # codex r5: a message sent during the presses was held before nothing; it is not explained by them
        import time
        self.send(MSG)
        t_antes = time.time()
        self.notice(HELD)
        ev = self.retenidos()[0]
        self.assertLessEqual(t_antes, ev["modo"]["desde"])
        self.assertLessEqual(ev["modo"]["desde"], ev["ts"])

    def test_a_pending_bash_permission_survives_a_notice(self):
        # codex r6: blocked → retenido made aprueba.pendiente() return None
        import aprueba
        ev = {"event": "blocked", "session_id": "s-ag", "nombre": "cambio-x", "tool_name": "Bash",
              "detalle": "ls", "comando": "ls", "hook": "PermissionRequest"}
        lookout_state.append_event(PID, ev)
        self.assertIsNotNone(aprueba.pendiente(PID, {"session_id": "s-ag"}))
        self.screen[0] = DIALOG
        self.notice(HELD)
        self.assertIsNotNone(aprueba.pendiente(PID, {"session_id": "s-ag"}))

    def test_supervisor_md_never_shows_the_notice_as_the_agents_state(self):
        # codex r2
        lookout_state.append_event(PID, {"event": "blocked", "session_id": "s-ag", "nombre": "cambio-x",
                                         "tool_name": "Bash"})
        self.screen[0] = DIALOG
        self.notice(HELD)
        md = supervisor_md.render(PID)
        fila = [l for l in md.splitlines() if "cambio-x" in l and "|" in l]
        self.assertTrue(fila and "retenido" not in fila[0], fila)

    def test_an_expiry_without_was_is_read(self):
        import retenido
        a = retenido.lee("[Cross-session delivery notice] Your message to another session expired undelivered "
                         "(recipient: uds:%s; msg_id: %s)." % (SOCK, MSG))
        self.assertEqual(a["estado"], "caducado")


class OrigenTest(unittest.TestCase):
    def test_an_agent_that_gets_the_notice_never_logs_it_as_the_users_decision(self):
        # an agent's own SendMessage to the supervisor can be held too: its notice is no decision taken in its pane
        import on_state
        self.assertEqual(on_state.origen_prompt(PID, "s-ag", HELD), "par")


if __name__ == "__main__":
    unittest.main()

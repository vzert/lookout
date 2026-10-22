"""0.13.48 (p-449b0a3bc6): the 0.13.39 held-message notice, measured live (2026-10-21, supervisor in auto, agent moved to
bypass by Shift+Tab after it registered; texts below verbatim but for the msg_id).

- The release notice says «was approved and released to that session»: 0.13.39 read it as a wording never seen
  («AVISO DE ENTREGA sin leer … reenvía»), though the message had reached the agent's Claude.
- The expiry notice says «was not approved before expiry»: read as caducado, as 0.13.39 assumed.
- With the hold dialog on the agent's screen there is no footer to read, and its transcript still says auto: a Shift+Tab
  made while the session is idle writes no `permission-mode` row. 0.13.39 took that for the same class («su sesión
  retiene todo mensaje»); the dialog itself says «The sending session's permission mode class doesn't match this
  session's».
Run: python3 -m unittest tests/test_lookout_01348.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_01339 as t39  # noqa: E402

import digest  # noqa: E402

SOCK, MSG = t39.SOCK, t39.MSG
RELEASED = ("[Cross-session delivery notice] Your message to another session was approved and released to that session "
            "(recipient: uds:%s; msg_id: %s)." % (SOCK, MSG))
EXPIRED = ("[Cross-session delivery notice] Your message to another session was not approved before expiry (recipient: "
           "uds:%s; msg_id: %s). Not delivered to that session's Claude, and nothing is waiting there. Do not wait for a "
           "reply, and do not resend unprompted: while the two sessions' permission modes differ a resend is only held "
           "again. Tell your user what was not delivered and why; send it again, edited if that helps, when they ask."
           % (SOCK, MSG))
SUP_ADDR = "uds:/tmp/sup.sock"  # the supervisor's address in test_lookout_f4's lock.json
# the last lines of the agent's pane while the message was held (bench, message 1; its socket swapped for SUP_ADDR)
DIALOG_REAL = (
    "⏺ Held peer message — from uds:/tmp/sup.sock [verified pid 12958] (peer claims name: supervisor-x); "
    "preview: «m» — not delivered to Claude (1 held). The sending session's permission mode class\n"
    "  doesn't match this session's. Review it below, or set \"crossSessionInbound\" to \"accept\".\n\n"
    "────────────────────────────────────────\n"
    " Held message from another session\n\n"
    " Another Claude session sent a message: from uds:/tmp/sup.sock [verified pid 12958] (peer claims name: "
    "supervisor-x)\n\n"
    " The sending session's permission mode class doesn't match this session's, so it wasn't delivered automatically.\n\n"
    " Message body (this is what will be delivered):\n"
    "╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌\n"
    " │ m\n"
    "╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌\n"
    " ❯ Deny — drop it and tell the sender it was declined\n"
    "   Deliver this message to Claude\n")


class BancoTest(t39.RetenidoTest):
    def test_the_measured_release_is_a_delivery(self):
        import retenido
        self.assertEqual(retenido.lee(RELEASED)["estado"], "liberado")
        self.notice(RELEASED)
        line = digest.describe(self.retenidos()[0])
        self.assertIn("ENTREGADO", line)
        self.assertNotIn("reenvía", line)

    def test_the_measured_expiry_is_an_expiry(self):
        import retenido
        self.assertEqual(retenido.lee(EXPIRED)["estado"], "caducado")

    def test_a_negated_approval_is_never_a_delivery(self):
        import retenido
        for que in ("not approved and released", "approved and released, then dropped undelivered",
                    "approved and not released"):
            a = retenido.lee("[Cross-session delivery notice] Your message to another session was %s "
                             "(recipient: uds:%s; msg_id: %s)." % (que, SOCK, MSG))
            self.assertNotEqual(a["estado"], "liberado", que)

    def test_the_real_dialog_has_no_footer(self):
        self.assertEqual(self.modo.pie(DIALOG_REAL), "")

    def test_a_stale_transcript_mode_never_beats_the_dialogs_class_mismatch(self):
        self.screen[0] = DIALOG_REAL
        self.modo.de_sesion = lambda sid: "auto"  # its last permission-mode row: the Shift+Tab to bypass wrote none
        self.notice(t39.HELD)
        self.assertEqual(self.keys, [])
        ev = self.retenidos()[0]
        self.assertEqual(ev["modo"]["estado"], "dialogo")
        line = digest.describe(ev)
        self.assertNotIn("retiene todo", line)
        self.assertIn("MODO DISTINTO", line)
        self.assertIn("Shift+Tab", line)

    def test_an_old_holds_line_above_another_dialog_is_no_mismatch(self):
        # the «⏺ Held peer message … doesn't match» line stays in the conversation after its dialog closed
        self.screen[0] = DIALOG_REAL.split("────")[0] + "\n Do you want to proceed?\n ❯ 1. Yes\n Esc to cancel\n"
        self.modo.de_sesion = lambda sid: "auto"
        self.notice(t39.HELD)
        self.assertEqual(self.retenidos()[0]["modo"]["estado"], "iguales")

    def held_with(self, screen):
        self.screen[0] = screen
        self.modo.de_sesion = lambda sid: "auto"
        self.notice(t39.HELD)
        return self.retenidos()[0]["modo"]["estado"]

    def test_a_dialog_of_another_sender_says_nothing_of_the_supervisors_class(self):
        # codex r1: a third session in bypass holds its own message there; the supervisor's may be held for another reason
        self.assertEqual(self.held_with(DIALOG_REAL.replace("uds:/tmp/sup.sock", "uds:/tmp/cc-socks/777.sock")),
                         "iguales")

    def test_a_wrapped_mismatch_line_still_counts(self):
        # codex r1: the terminal may break the line anywhere
        self.assertEqual(self.held_with(DIALOG_REAL.replace("class doesn't", "class\n doesn't")), "dialogo")

    def test_the_message_body_never_counts(self):
        # codex r1: the body is below «Message body»; a title or a mismatch phrase there is the message's, not the dialog's
        self.assertEqual(self.held_with(DIALOG_REAL.replace("│ m\n", "│ Held message from another session\n")),
                         "dialogo")
        sin = DIALOG_REAL.replace(" The sending session's permission mode class doesn't match this session's, so it "
                                  "wasn't delivered automatically.\n", "")
        self.assertFalse(self.modo.clase_distinta(sin.replace("│ m\n", "│ permission mode class doesn't match\n"),
                                                  SUP_ADDR))
        self.assertTrue(self.modo.clase_distinta(DIALOG_REAL, SUP_ADDR))
        # codex r2: a body with the phrase and a «Message body» line of its own (every body line starts with │)
        falso = "│ permission mode class doesn't match\n │ Message body (this is what will be delivered):\n"
        self.assertFalse(self.modo.clase_distinta(sin.replace("│ m\n", falso), SUP_ADDR))
        self.assertTrue(self.modo.clase_distinta(DIALOG_REAL.replace("│ m\n", falso), SUP_ADDR))

    def test_a_dialog_without_the_mismatch_still_trusts_the_transcript(self):
        # a session set to hold every message (crossSessionInbound) shows no class mismatch: same class stays «iguales»
        self.screen[0] = t39.DIALOG
        self.modo.de_sesion = lambda sid: "auto"
        self.notice(t39.HELD)
        self.assertEqual(self.retenidos()[0]["modo"]["estado"], "iguales")


def load_tests(loader, standard, pattern):
    """Only the tests of this file: the 0.13.39 ones run in their own."""
    return unittest.TestSuite(BancoTest(n) for n in sorted(BancoTest.__dict__) if n.startswith("test_"))


if __name__ == "__main__":
    unittest.main()

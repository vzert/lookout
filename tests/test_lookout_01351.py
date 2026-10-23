"""0.13.51: the supervisor never asks the user to type, in the supervisor's own tab, a «! comando» that an agent asked
for or that auto mode refused to an agent (3-tier-memory, 2026-10-22: «Bug en mod» had its `git push` refused; the
supervisor wrote «Lo que necesito de ti: 1. Escribe esto en esta pestaña, «Supervisor»…» six times instead of opening
`lookout decision --negado` and typing it in the agent's pane). The supervisor's Stop check now notices that line in the
last message and sends the supervisor back to the typing flow, once per command and refusal.
Run: python3 -m unittest tests/test_lookout_01351.py
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_01346 as t1346  # noqa: E402
import test_lookout_f4 as f4  # noqa: E402

import decisiones  # noqa: E402
import lookout_state  # noqa: E402
import on_supervisor  # noqa: E402

PID = f4.PID
PUSH = "git -C /Users/alguien/Proyectos/tienda-raya push origin HEAD:refs/heads/arreglo-raya"


def mensaje(comando):
    return ("1. El filtro de seguridad no dejó subir el cambio de «uno».\n\n**Lo que necesito de ti:**\n"
            "1. Escribe esto en esta pestaña, «Supervisor», y pulsa Enter:\n\n```\n! %s\n```\n" % comando)


class Base(t1346.Base):
    def setUp(self):
        super().setUp()
        self.tp = os.path.join(self.tmp.name, "sup.jsonl")

    def habla(self, texto, extra=()):
        with open(self.tp, "a") as fh:
            for fila in list(extra) + [{"type": "assistant", "message": {"content": [{"type": "text", "text": texto}]}}]:
                fh.write(json.dumps(fila) + "\n")

    def stop(self):
        out = on_supervisor.stop_check({"transcript_path": self.tp}, PID, "sup1", grace=0)
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""


class TeclearNoPedirTest(Base):
    def test_a_refused_command_asked_to_the_user_sends_the_supervisor_to_the_typing_flow(self):
        self.niega(PUSH)
        self.habla(mensaje(PUSH))
        ctx = self.stop()
        self.assertIn("lookout decision %s --abre" % PID, ctx)
        self.assertIn("--agentes uno", ctx)
        self.assertIn("--negado", ctx)
        self.assertIn(PUSH, ctx)

    def test_it_is_said_once_per_refusal(self):
        self.niega(PUSH)
        self.habla(mensaje(PUSH))
        self.assertIn("--negado", self.stop())
        self.habla(mensaje(PUSH))
        self.assertNotIn("--negado", self.stop())
        self.niega(PUSH)                      # a new refusal of the same command is a new case
        self.habla(mensaje(PUSH))
        self.assertIn("--negado", self.stop())

    def test_a_command_no_agent_owns_goes_to_a_quiet_agents_pane_once(self):
        # the user's choice for the case no agent owns (and the supervisor's own refusal leaves no event)
        propio = "git -C /Users/alguien/otro push origin HEAD:refs/heads/x"
        self.habla(mensaje(propio))
        ctx = self.stop()
        self.assertIn("--agentes <agente quieto>", ctx)
        self.assertNotIn("--agentes <agente quieto> --negado", ctx)     # the recipe has no --negado, only the prose does
        self.assertIn("lookout envia %s <agente quieto> --usuario-confirmo" % PID, ctx)
        self.assertIn("ningún agente está quieto", ctx)       # and the way back to asking the user
        self.habla(mensaje(propio))
        self.assertNotIn("<agente quieto>", self.stop())      # once per command
        self.habla(mensaje(propio + "2"))
        self.assertIn("<agente quieto>", self.stop())         # another command is another case

    def test_an_agents_command_never_falls_into_the_no_owner_case_after_its_own_warning(self):
        self.niega(PUSH)
        self.habla(mensaje(PUSH))
        self.assertIn("--negado", self.stop())
        self.habla(mensaje(PUSH))                                  # the next turn repeats it
        ctx = self.stop()
        self.assertNotIn("<agente quieto>", ctx)
        lookout_state.append_event(PID, {"event": "idle", "session_id": "s2", "nombre": "dos",
                                         "espera_pane": {"motivo": "m", "cita": "Corre ! make release-local"}})
        self.habla(mensaje("make release-local"))
        self.assertIn("--agentes dos", self.stop())
        self.habla(mensaje("make release-local"))
        self.assertNotIn("<agente quieto>", self.stop())

    def test_the_no_owner_text_does_not_claim_that_no_agent_asked(self):
        self.habla(mensaje("git -C /Users/alguien/otro status"))
        ctx = self.stop()
        self.assertNotIn("Ningún agente lo pidió", ctx)
        self.assertIn("No tengo un evento de un agente con este comando exacto", ctx)

    def test_with_no_agent_registered_nothing_is_said_about_a_quiet_one(self):
        import registry
        registry.save(PID, {"agents": {}})
        self.habla(mensaje("git -C /Users/alguien/otro status"))
        self.assertNotIn("<agente quieto>", self.stop())

    def test_only_the_last_message_counts(self):
        self.niega(PUSH)
        self.habla(mensaje(PUSH))
        self.habla("Listo, ya lo tecleé en su pane.")
        self.assertNotIn("--negado", self.stop())

    def test_an_agent_that_asks_for_a_typed_command_gets_the_ordinary_flow(self):
        lookout_state.append_event(PID, {"event": "idle", "session_id": "s2", "nombre": "dos",
                                         "espera_pane": {"motivo": "pide algo tecleado en su pane",
                                                         "cita": "Escribe en mi pane: ! make release-local"}})
        self.habla(mensaje("make release-local"))
        ctx = self.stop()
        self.assertIn("--agentes dos", ctx)
        self.assertNotIn("--negado", ctx)
        self.assertIn("lookout envia %s dos --usuario-confirmo" % PID, ctx)

    def test_the_stop_payload_wins_over_a_transcript_that_lacks_its_last_row(self):
        self.niega(PUSH)
        self.habla("Todavía sin escribir lo último.")
        out = on_supervisor.stop_check({"transcript_path": self.tp, "last_assistant_message": mensaje(PUSH)},
                                       PID, "sup1", grace=0)
        self.assertIn("--negado", json.loads(out)["hookSpecificOutput"]["additionalContext"])

    def test_a_stale_offending_row_does_not_fire_when_the_payload_says_it_was_corrected(self):
        self.niega(PUSH)
        self.habla(mensaje(PUSH))
        out = on_supervisor.stop_check({"transcript_path": self.tp, "last_assistant_message": "Listo, ya lo tecleé."},
                                       PID, "sup1", grace=0)
        self.assertNotIn("--negado", out)

    def test_the_line_for_the_user_never_says_the_user_types_it(self):
        self.niega(PUSH)
        self.habla(mensaje(PUSH))
        out = json.loads(on_supervisor.stop_check({"transcript_path": self.tp}, PID, "sup1", grace=0))
        self.assertNotIn("tecleas tú", out["systemMessage"])

    def test_a_refusal_recorded_before_0_13_46_with_only_detalle_is_recognized(self):
        lookout_state.append_event(PID, {"event": "negado", "hook": "PermissionDenied", "tool_name": "Bash",
                                         "session_id": "s1", "nombre": "uno", "detalle": PUSH})
        self.habla(mensaje(PUSH))
        ctx = self.stop()
        # `decision --negado` needs the whole `comando` of the event (teclea.negados): such an event gets the plain recipe
        self.assertNotIn("--negado", ctx)
        self.assertIn("lookout envia %s uno --usuario-confirmo" % PID, ctx)
        ok, _ = t1346.teclea.abre(PID, {"session_id": "s1", "nombre": "uno"}, "«! %s»" % PUSH, "Sí")
        self.assertFalse(ok)

    def test_a_legacy_detalle_clipped_at_200_characters_is_not_taken_for_the_command(self):
        largo = "echo " + "x" * 259
        lookout_state.append_event(PID, {"event": "negado", "hook": "PermissionDenied", "tool_name": "Bash",
                                         "session_id": "s1", "nombre": "uno", "detalle": largo[:200]})
        self.habla(mensaje(largo[:200]))
        ctx = self.stop()
        self.assertNotIn("es de «uno»", ctx)          # not taken for the agent's refusal ...
        self.assertIn("<agente quieto>", ctx)         # ... it is a command no agent owns

    def test_the_printed_recipe_never_lets_the_shell_run_part_of_the_command(self):
        import shlex
        peligro = 'echo "$(printf PWN)" `id`'
        self.niega(peligro)
        self.habla(mensaje(peligro))
        ctx = self.stop()
        receta = ctx[ctx.index("Corre `lookout decision") + len("Corre `"):]
        receta = receta[:receta.index("`, pregunta")]
        partes = shlex.split(receta)            # what the supervisor's shell would hand to lookout
        self.assertIn("«! %s»" % peligro, partes[partes.index("--abre") + 1])
        self.assertNotIn("$(printf PWN)", [p for p in partes if p.startswith("--")])

    def test_a_request_clipped_at_200_characters_by_the_agent_event_is_still_found(self):
        largo = "make release-local " + "x" * 236
        lookout_state.append_event(PID, {"event": "idle", "session_id": "s2", "nombre": "dos",
                                         "espera_pane": {"motivo": "m", "cita": ("Escribe en mi pane: ! " + largo)[:200]}})
        self.habla(mensaje(largo))
        self.assertIn("--agentes dos", self.stop())

    def test_inline_code_fences_come_off_whatever_their_length_and_a_commands_own_backticks_stay(self):
        f = on_supervisor.sin_codigo_en_linea
        self.assertEqual(f("`! make x`"), "! make x")
        self.assertEqual(f("``! echo `date` ``"), "! echo `date`")
        self.assertEqual(f("! echo `date`"), "! echo `date`")
        self.assertEqual(f("```"), "```")
        self.assertEqual(f("  ! ls  "), "! ls")

    def test_the_clip_guard_of_en_cita_matters_for_a_quote_that_was_not_clipped(self):
        # a 100-character quote ends with the start of a longer command: not clipped, so not a match
        self.assertFalse(on_supervisor.en_cita("make release-local --force", "z" * 80 + " ! make release-local"))

    def test_a_short_end_of_the_quote_is_not_taken_for_a_clipped_command(self):
        largo = "make release-local " + "x" * 80
        self.assertTrue(on_supervisor.en_cita(largo, ("y" * 150 + " ! " + largo)[:200]))   # cut by the clip
        self.assertFalse(on_supervisor.en_cita("ls -la /tmp", "y" * 193 + " ! ls -l"))   # 6 characters left: too short
        self.assertFalse(on_supervisor.en_cita("make release-local", "corto"))             # not clipped, not inside

    def test_the_refusal_recipe_wins_over_an_idle_event_that_quotes_the_command(self):
        self.niega(PUSH)
        lookout_state.append_event(PID, {"event": "idle", "session_id": "s1", "nombre": "uno",
                                         "espera_pane": {"motivo": "x", "cita": "Corre ! " + PUSH}})
        self.habla(mensaje(PUSH))
        self.assertIn("--negado", self.stop())

    def test_the_skill_does_not_offer_the_user_typing_as_the_first_way(self):
        ruta = os.path.join(f4.ROOT, "plugins", "lookout", "skills", "supervisa", "SKILL.md")
        with open(ruta, encoding="utf-8") as fh:
            skill = fh.read()
        i = skill.index("**Un comando que pide o espera un agente")
        parrafo = skill[i:i + 900]
        # the fallback is only for a `lookout envia` that the harness itself refused, after trying the typing flow
        self.assertIn("--negado", parrafo)
        self.assertIn("un agente", parrafo)
        self.assertNotIn("(el filtro de seguridad de Claude no me deja escribirlo a mí)", skill)


if __name__ == "__main__":
    unittest.main()

"""0.13.8: three ways an agent of the supervised project sat unseen in 3-tier-memory on 2026-10-16.
- pendientes-en-sessionstart waited 7 h for «aprobado» in its pane; its last three turns did not repeat the words the
  0.13.7 detector looks for, so the wait vanished from the digest (the wait now holds until something released it).
- prompts-repetidos ran 3-tier-memory 2.62.0 hooks with 2.62.6 installed, and pendientes-en-sessionstart lookout 0.13.5
  hooks with 0.13.7 installed: no fix reached them (each event now carries the hooks' version; a hook's output cites
  its plugin's path; `lookout recarga` types /reload-plugins into an idle agent with an empty box).
- 3tier-snippet-linea-extras kept a background shell alive 24 h: one `largo` and then silence (it now repeats, and
  says what the task is and who may stop it).
Run: python3 -m unittest tests/test_lookout_0138.py
"""
import json
import os
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f2 as f2  # noqa: E402
import test_lookout_f4 as f4  # noqa: E402

import digest  # noqa: E402
import heuristicas  # noqa: E402
import lookout_state  # noqa: E402
import on_state  # noqa: E402
import registry  # noqa: E402

PID = f4.PID
VERSION = json.load(open(os.path.join(f4.ROOT, "plugins", "lookout", ".claude-plugin", "plugin.json")))["version"]
# pendientes-en-sessionstart (3-tier-memory, 2026-10-16), last messages of its turns, word for word
ESPERA_1957 = "Esto es una espera: no he cerrado nada y no he ejecutado ningún cambio. Necesito que escribas «aprobado» aquí para empezar."
SIN_FRASE = ("No he cerrado nada. Sigo esperando tu «aprobado» en esta ventana para empezar.",
             "Sigo esperando tu «aprobado» en esta ventana. El supervisor confirmó que el plan es correcto, pero su mensaje "
             "no suelta el freno: eso solo pasa cuando escribes tú aquí.",
             "No he cerrado nada y no he hecho ningún cambio. Sigo esperando tu «aprobado» aquí.")
# endings of the same two sessions that wait for nobody's typing (the supervisor, a CI run, a merge)
NO_ESPERAN = ("No he cerrado nada todavía. Espero la respuesta del supervisor a la especificación; su mensaje retomará el trabajo.",
              "Sigo esperando el OK del supervisor al plan del hilo de 1 salto. Todavía no toqué código.",
              "Esto es una espera, no un cierre. Falta la respuesta del supervisor sobre el push; llega sola cuando la tenga.",
              "Entendido. No hago nada hasta que el supervisor me avise. Espero a que entre en main el PR de 2.62.11.",
              "A mí no me queda nada abierto, así que el supervisor puede relevarme.",
              "[ADVERSARY-VERDICT: hold ungrounded=0 unfalsified=0 incomplete=0 autonomy-violations=0 unsafe=0]",
              "**¿Cerrado?** No: falta tu merge para que el arreglo llegue a main.")
NOTA = ("Nota del supervisor lookout (encargo del usuario). Tu nombre: pendientes-en-sessionstart. Para toda decisión, al "
        "terminar o al atorarte, usa SendMessage con to=\"uds:/tmp/sup.sock\" en vez de AskUserQuestion.")


def bloque(out, nombre):
    """An agent's row of the digest table and the ↳ lines under it."""
    lines = out.splitlines()
    i = next(i for i, l in enumerate(lines) if l.startswith("  ") and l.split("|")[0].strip().startswith(nombre))
    j = i + 1
    while j < len(lines) and lines[j].startswith("    ↳"):
        j += 1
    return "\n".join(lines[i:j])


def texto(t):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": t}]}}


def prompt(t, meta=False):
    return dict({"type": "user", "message": {"content": t}}, **({"isMeta": True} if meta else {}))


def par(t):  # a peer's SendMessage, as the transcript stores it
    return prompt("Another Claude session sent a message:\n<cross-session-message from=\"uds:/tmp/sup.sock\">%s"
                  "</cross-session-message>" % t, meta=True)


def uso(tool, uid, ok=True, contenido="hecho"):
    return [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": uid, "name": tool, "input": {}}]}},
            {"type": "user", "message": {"content": [dict({"type": "tool_result", "tool_use_id": uid, "content": contenido},
                                                          **({"is_error": True} if not ok else {}))]}}]


class EsperaQueSeMantieneTest(f4.Base):
    def stop(self, msg, rows):
        tp = os.path.join(self.tmp.name, "ag-%d.jsonl" % time.monotonic_ns())
        with open(tp, "w") as fh:
            for r in rows + [texto(msg)]:
                fh.write(json.dumps(r) + "\n")
        ev, _l, _o = on_state.build({"hook_event_name": "Stop", "session_id": "s1", "transcript_path": tp,
                                     "last_assistant_message": msg}, {"nombre": "pend", "address": "uds:/tmp/sup.sock"})
        return ev

    def test_the_real_last_turns_are_a_wait(self):
        for msg in SIN_FRASE:   # 0.13.7: None for all three
            self.assertTrue(on_state.espera_pane(msg), msg)

    def test_endings_that_wait_for_nobodys_typing_are_not(self):
        for msg in NO_ESPERAN:
            self.assertIsNone(on_state.espera_pane(msg), msg)

    def test_the_wait_holds_through_lookouts_own_typing_and_peer_messages(self):
        rows = [par("aprobada por mi parte"),
                texto(ESPERA_1957),
                prompt("<local-command-caveat>The command below was run directly</local-command-caveat>", meta=True),
                prompt("<command-name>/reload-plugins</command-name>"),
                prompt("<local-command-stdout>Reloaded: 5 plugins</local-command-stdout>"),
                prompt(NOTA),
                par("Espera el «aprobado».")]
        rows += uso("SendMessage", "m1")
        ev = self.stop("No he cerrado nada y no he hecho ningún cambio. Sigo esperando.", rows)
        self.assertTrue(ev.get("espera_pane"), ev)
        self.assertEqual(ev["espera_pane"]["cita"], ESPERA_1957)

    def test_the_ratify_brake_starts_a_wait_too(self):
        rows = uso("Bash", "b1", ok=False, contenido="PreToolUse:Bash hook error: goalspec: this session posted its "
                                                      "## Goal-spec and has not shown it back to the human yet")
        rows += [texto("Mandé el spec al supervisor."), prompt(NOTA)]
        self.assertEqual(self.stop("Sigo sin tocar nada.", rows)["espera_pane"]["motivo"], "ratificar su spec de goalspec")

    def test_a_tool_that_ran_after_the_brake_in_the_same_turn_releases_it(self):
        # adversary r1 (codex): the brake of this turn forced the wait even after a Bash that ran
        rows = uso("Bash", "b1", ok=False, contenido="PreToolUse:Bash hook error: goalspec: this session posted its "
                                                      "## Goal-spec and has not shown it back to the human yet")
        rows += uso("Bash", "b2")
        self.assertIsNone(self.stop("Hecho el cambio.", rows).get("espera_pane"))

    def test_what_releases_it(self):
        base = [texto(ESPERA_1957)]
        for nombre, extra in (("un Bash que corrió", uso("Bash", "b2")), ("un Edit", uso("Edit", "e1")),
                              ("un ! tecleado", [prompt("<bash-input> git status</bash-input>")]),
                              ("el usuario contestó", [prompt("no, para")]),
                              ("el aprobado tecleado", [prompt("aprobado (d104)")])):
            self.assertIsNone(self.stop("Listo.", base + extra).get("espera_pane"), nombre)
        held = self.stop("Listo.", base + uso("Bash", "b3", ok=False, contenido="PreToolUse:Bash hook error: x"))
        self.assertTrue(held.get("espera_pane"), "un Bash frenado no la suelta")

    def test_the_digest_row_says_it_on_every_wake(self):
        self.agent("s1", "pend")
        ev = self.stop("Sigo esperando.", [texto(ESPERA_1957)])
        lookout_state.append_event(PID, dict(ev, ts=time.time()))
        self.assertEqual(heuristicas.grupo(lookout_state.read_events(PID, 0)[0], "s1"), "te_necesita")
        primera = digest.render(PID, mark=True, por_waiter=True)
        self.assertIn("ESPERA ALGO TECLEADO", primera.split("Eventos nuevos")[0])
        otra = digest.render(PID, mark=True, por_waiter=True)    # nothing new: the table folds, the wait does not
        self.assertIn("ESPERA ALGO TECLEADO", otra)

    def test_the_note_still_starts_as_the_detector_expects(self):
        with open(os.path.join(f4.ROOT, "plugins", "lookout", "skills", "supervisa", "references", "nota-reporte.md"),
                  encoding="utf-8") as fh:
            ref = fh.read()
        self.assertTrue(ref.startswith(on_state.NOTA_LOOKOUT))


class HooksViejosTest(f4.Base):
    def setUp(self):
        super().setUp()
        self.conf = os.path.join(self.tmp.name, "claude")
        os.makedirs(os.path.join(self.conf, "plugins"))
        with open(os.path.join(self.conf, "plugins", "installed_plugins.json"), "w") as fh:
            json.dump({"version": 2, "plugins": {"3-tier-memory@3-tier-memory-marketplace": [{"version": "2.62.6"}],
                                                 "lookout@lookout-marketplace": [{"version": VERSION}]}}, fh)
        self.old_conf = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = self.conf

    def tearDown(self):
        if self.old_conf is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self.old_conf
        super().tearDown()

    def ev(self, sid, **kw):
        lookout_state.append_event(PID, dict({"session_id": sid, "event": "idle", "hook": "Stop", "ultima": "ok",
                                              "ts": time.time()}, **kw))

    def hook_cita(self, sid, ver):
        self.transcript(sid, [{"type": "attachment", "attachment": {
            "type": "hook_success", "hookName": "UserPromptSubmit", "content":
            "python3 \"%s/plugins/cache/3-tier-memory-marketplace/3-tier-memory/%s/bin/journal-emit.py\" --type x"
            % (self.conf, ver)}}])

    def test_every_hook_event_carries_its_version(self):
        ev, _l, _o = on_state.build({"hook_event_name": "Stop", "session_id": "s1", "last_assistant_message": "ok"},
                                    {"nombre": "a"})
        self.assertEqual(ev.get("v"), VERSION)

    def test_the_digest_names_who_runs_old_hooks(self):
        self.agent("s1", "viejo")                   # lookout without `v`: before 0.13.8
        self.agent("s2", "tres")                    # 3-tier 2.62.0 cited by its own hook
        self.agent("s3", "aldia")
        self.ev("s1")
        self.ev("s2", v=VERSION)
        self.ev("s3", v=VERSION)
        self.hook_cita("s2", "2.62.0")
        self.hook_cita("s3", "2.62.6")
        out = digest.render(PID, mark=True)
        fila = lambda n: bloque(out, n)
        self.assertIn("hooks viejos", fila("viejo"))
        self.assertIn("lookout recarga", fila("viejo"))
        self.assertIn("3-tier-memory 2.62.0", fila("tres"))
        self.assertNotIn("hooks viejos", fila("aldia"))

    def test_only_the_agents_own_hooks_count(self):
        # adversary r1 (codex): a PermissionRequest of permisos.py had no `v`; the supervisor's own events have its version
        import permisos
        self.agent("s1", "aldia")
        self.ev("s1", v=VERSION)
        permisos.emit({"project_id": PID}, {"session_id": "s1", "event": "blocked", "hook": "PermissionRequest"})
        self.assertEqual(lookout_state.read_events(PID, 0)[0][-1].get("v"), VERSION)
        lookout_state.write_marker("s1", {"project_id": PID, "address": "uds:/tmp/sup.sock", "nombre": "aldia"})
        subprocess.run(["sh", os.path.join(f4.ROOT, "plugins", "lookout", "hooks", "guard.sh"), "on_ask.py"],
                       input=json.dumps({"session_id": "s1", "tool_input": {"questions": []}}), capture_output=True,
                       text=True, env=dict(os.environ))
        ask = lookout_state.read_events(PID, 0)[0][-1]
        self.assertEqual((ask.get("event"), ask.get("v")), ("ask", VERSION))     # its `ask` event too
        self.agent("s2", "viejo2")
        self.ev("s2")                                                          # its Stop, before 0.13.8
        self.ev("s2", hook="registro", event="retomar", v=VERSION)             # written by the supervisor
        out = digest.render(PID, mark=True)
        self.assertNotIn("hooks viejos", bloque(out, "aldia"))
        self.assertIn("hooks viejos", bloque(out, "viejo2"))

    def test_a_reload_lookout_typed_clears_it_until_the_next_update(self):
        self.agent("s1", "viejo", recargado={"lookout@lookout-marketplace": VERSION})
        self.ev("s1")
        self.assertNotIn("hooks viejos", digest.render(PID, mark=True))


class RecargaTest(f2.StubCase):
    def setUp(self):
        super().setUp()
        reg = registry.load(self.pid)
        reg.setdefault("agents", {})[self.sid] = dict(self.entry)
        registry.save(self.pid, reg)
        import recarga
        self.recarga = recarga

    def test_an_idle_agent_with_an_empty_box_gets_it(self):
        self.stub(agent_get={"agent_status": "idle", "agent_session": {"value": self.sid}}, agent_read=f2.EMPTY_BOX,
                  read_after_prompt="  ⎿  Reloaded: 5 plugins · 20 skills\n" + f2.EMPTY_BOX)
        ok, msg = self.recarga.recarga(self.pid, self.entry, espera=1)
        self.assertTrue(ok, msg)
        self.assertEqual([c[3] for c in self.calls(["agent", "prompt"])], ["/reload-plugins"])
        self.assertTrue(registry.load(self.pid)["agents"][self.sid].get("recargado"))

    def test_never_over_a_draft_or_a_working_agent(self):
        self.stub(agent_get={"agent_status": "idle", "agent_session": {"value": self.sid}}, agent_read=f2.DRAFT_BOX)
        self.assertFalse(self.recarga.recarga(self.pid, self.entry, espera=1)[0])
        self.stub(agent_get={"agent_status": "working", "agent_session": {"value": self.sid}}, agent_read=f2.EMPTY_BOX)
        self.assertFalse(self.recarga.recarga(self.pid, self.entry, espera=1)[0])
        self.assertEqual(self.calls(["agent", "prompt"]), [])

    def test_unconfirmed_is_said_and_not_recorded(self):
        self.stub(agent_get={"agent_status": "idle", "agent_session": {"value": self.sid}}, agent_read=f2.EMPTY_BOX)
        ok, msg = self.recarga.recarga(self.pid, self.entry, espera=1)
        self.assertFalse(ok)
        self.assertIn("sin confirmar", msg)
        self.assertFalse(registry.load(self.pid)["agents"][self.sid].get("recargado"))


class FondoColgadoTest(f4.Base):
    # 3tier-snippet-linea-extras' shell (pid 86555, started 2026-10-15 14:09, still alive 31 h later; shortened)
    COLGADA = ("cd ~/.claude/projects/ && ls -d *cloudflare-expert* ; f=$(ls *cloudflare-expert*/41cf89a7*.jsonl | head -1); "
               "grep -o \"p-43ecdb009f\" $f | head -3; python3 -I - \"$f\" <<'EOF'\nimport json,sys\nEOF")

    def bg(self, cmd, hace):
        self.agent("s1", "snippet")
        lookout_state.append_event(PID, {"session_id": "s1", "event": "bg_wait", "hook": "Stop", "ts": time.time() - hace,
                                         "tareas": [{"type": "shell", "status": "running", "command": cmd}]})

    def test_it_warns_again_while_it_lasts(self):
        largo = heuristicas.largo_s()
        self.bg(self.COLGADA, largo + 60)
        t0 = time.time()
        self.assertEqual([e["event"] for e in heuristicas.revisa(PID, now=t0, agents=[])], ["largo"])
        self.assertEqual(heuristicas.revisa(PID, now=t0 + 60, agents=[]), [])
        self.assertEqual([e["event"] for e in heuristicas.revisa(PID, now=t0 + 2 * largo, agents=[])], ["largo"])
        self.assertEqual(heuristicas.revisa(PID, now=t0 + 2 * largo + 60, agents=[]), [])

    def test_it_says_the_task_and_who_may_stop_it(self):
        self.bg(self.COLGADA, heuristicas.largo_s() + 60)
        ev = heuristicas.revisa(PID, agents=[])[0]
        line = digest.describe(ev)
        self.assertIn("cloudflare-expert", line)
        self.assertIn("TaskStop", line)
        self.assertNotIn("kill", line)

    def test_a_task_reserved_to_the_user_goes_to_the_user(self):
        self.bg("git push origin main", heuristicas.largo_s() + 60)
        line = digest.describe(heuristicas.revisa(PID, agents=[])[0])
        self.assertIn("pregunta al usuario", line)
        self.assertNotIn("TaskStop", line)


if __name__ == "__main__":
    unittest.main()

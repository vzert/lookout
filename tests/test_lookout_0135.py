"""0.13.5: the agent finishes in herdr, from its own state hook, a rename the alta left at «caja con …».
Run: python3 -m unittest tests/test_lookout_0135.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_0130 as t130  # noqa: E402

import lookout_state  # noqa: E402
import registry  # noqa: E402

PID = t130.PID


class RenombrePropioTest(t130.AltaTest):
    """3-tier-memory 2026-10-16: «Pendientes en sessionstart» was registered in 16 s while the user typed its first
    prompt; the alta said «caja con borrador». A retry from the waiter raced the pane (adversary, three rounds); the
    agent's own hook runs inside its session, in its pane."""

    def setUp(self):
        super().setUp()
        import alta
        saved = alta.herdr_cli.agent_get
        self.addCleanup(lambda: setattr(alta.herdr_cli, "agent_get", saved))
        self.herdr_name, self.sesion, self.responde = None, "nueva", True
        alta.herdr_cli.agent_get = lambda p: (dict({"agent_session": {"value": self.sesion}},
                                                   **({"name": self.herdr_name} if self.herdr_name else {}))
                                              if self.responde else None)

    def alta_con_borrador(self):
        llamadas = self.herdr_falso(caja="borrador")
        evs = self.descubre([self.herdr("nueva", "w1:p9", self.repo, "working")])
        self.assertEqual(evs[0]["renombre"], "caja con borrador")
        self.assertEqual(registry.load(PID)["agents"]["nueva"]["renombre"], "caja con borrador")
        return llamadas, evs[0]["nombre"]

    def test_its_own_hook_names_it_in_herdr_without_typing(self):
        import alta
        llamadas, nombre = self.alta_con_borrador()
        self.assertEqual(alta.renombra_propio(PID, "nueva", "w1:p9"), "hecho")
        self.assertFalse([c for c in llamadas if c[:2] == ["agent", "prompt"]])   # nothing typed into the box
        self.assertIn(["agent", "rename", "w1:p9", nombre], llamadas)
        e = registry.load(PID)["agents"]["nueva"]
        self.assertEqual(e["herdr_name"], nombre)
        self.assertTrue(e["renombre"].startswith("hecho por el agente"))
        del llamadas[:]
        self.assertEqual(alta.renombra_propio(PID, "nueva", "w1:p9"), "")         # done: never again
        self.assertEqual(llamadas, [])

    def test_a_name_the_user_gave_another_pane_or_an_old_entry_are_left_alone(self):
        import alta
        llamadas, _ = self.alta_con_borrador()
        self.herdr_name = "mi-nombre"                                             # given in herdr after the alta
        self.assertEqual(alta.renombra_propio(PID, "nueva", "w1:p9"), "")
        self.herdr_name = None
        self.assertEqual(alta.renombra_propio(PID, "nueva", "w1:p7"), "")         # not the registered pane
        self.assertEqual(alta.renombra_propio(PID, "nueva", ""), "")              # no HERDR_PANE_ID
        self.agent("vieja", "x", tarea="", pane_id="w1:p8", alta="2026-10-15T20:00:00")  # no recorded «caja con …»
        self.assertEqual(alta.renombra_propio(PID, "vieja", "w1:p8"), "")
        self.assertEqual(llamadas, [])

    def test_half_done_is_retried_up_to_the_cap(self):
        import alta
        llamadas, nombre = self.alta_con_borrador()
        alta.herdr_cli.run = lambda args, timeout=10: (llamadas.append(list(args)) or
                                                       ((1, "", "EACCES") if args[:2] == ["pane", "rename"] else (0, "", "")))
        for _ in range(alta.RENOMBRE_INTENTOS):
            self.assertTrue(alta.renombra_propio(PID, "nueva", "w1:p9").startswith("a medias"))
            self.herdr_name = nombre                                              # our own name now: not the user's
        self.assertEqual(alta.renombra_propio(PID, "nueva", "w1:p9"), "")         # capped
        self.assertTrue(registry.load(PID)["agents"]["nueva"]["renombre_parcial"])

    def test_herdr_must_answer_and_see_this_session(self):
        # adversary r1 (codex): agent_get None renamed anyway; only the name was checked, not the session
        import alta
        llamadas, _ = self.alta_con_borrador()
        self.responde = False
        self.assertEqual(alta.renombra_propio(PID, "nueva", "w1:p9"), "")
        self.responde, self.sesion = True, "otra"                   # a stale HERDR_PANE_ID now names another pane
        self.assertEqual(alta.renombra_propio(PID, "nueva", "w1:p9"), "")
        self.assertEqual(llamadas, [])

    def test_retired_meanwhile_its_record_is_not_written(self):
        import alta
        llamadas, _ = self.alta_con_borrador()
        real = alta.renombra_herdr

        def y_lo_retiran(entry, tab_of=None):
            reg = registry.load(PID)
            reg["agents"]["nueva"]["retirado"] = "2026-10-16T20:00:00"
            registry.save(PID, reg)
            return real(entry, tab_of)
        alta.renombra_herdr = y_lo_retiran
        self.addCleanup(lambda: setattr(alta, "renombra_herdr", real))
        alta.renombra_propio(PID, "nueva", "w1:p9")
        e = registry.load(PID)["agents"]["nueva"]
        self.assertFalse(e.get("herdr_name"))
        self.assertNotIn("renombre_intentos", e)


import test_lookout_f10 as f10  # noqa: E402


class EntregaCierraParcialTest(f10.RenameAntesDeNotaTest):
    def test_entrega_ends_the_agents_own_retries(self):
        # adversary r3 (codex): after a half-done retry, a full `lookout entrega` left renombre_parcial and the agent's
        # hook ran again
        guardar = registry.save

        def con_parcial(pid, reg):
            for e in reg.get("agents", {}).values():
                e.setdefault("renombre_parcial", True)
            guardar(pid, reg)
            registry.save = guardar
        registry.save = con_parcial
        self.addCleanup(lambda: setattr(registry, "save", guardar))
        ev = {"path": lookout_state.events_path(self.pid), "session_id": "s1"}
        rc, out, _ = self.entrega(prompt_event=ev)
        self.assertEqual(rc, 0, out)
        e = registry.load(self.pid)["agents"]["s1"]
        self.assertEqual(e.get("herdr_name"), "nope-arreglar")
        self.assertNotIn("renombre_parcial", e)


class HookLlamaTest(t130.AltaTest):
    def test_the_agents_state_hook_calls_it_with_its_own_pane(self):
        import io
        import alta
        import on_state
        visto = []
        saved = alta.renombra_propio
        alta.renombra_propio = lambda pid, sid, pane, tab_of=None: visto.append((pid, sid, pane)) or ""
        self.addCleanup(lambda: setattr(alta, "renombra_propio", saved))
        lookout_state.write_marker("nueva", {"project_id": PID, "address": "uds:/tmp/sup.sock", "nombre": "nueva"})
        old_env, old_in = os.environ.get("HERDR_PANE_ID"), sys.stdin
        os.environ["HERDR_PANE_ID"] = "w1:p9"
        try:
            for ev in ("Stop", "SessionEnd", "PostToolUse"):   # adversary r1: SessionEnd is sync with 5 s
                sys.stdin = io.StringIO('{"session_id": "nueva", "hook_event_name": "%s", "transcript_path": ""}' % ev)
                on_state.main()
        finally:
            sys.stdin = old_in
            if old_env is None:
                os.environ.pop("HERDR_PANE_ID", None)
            else:
                os.environ["HERDR_PANE_ID"] = old_env
        self.assertEqual(visto, [(PID, "nueva", "w1:p9")])


for _cls, _base in ((RenombrePropioTest, t130.AltaTest), (HookLlamaTest, t130.AltaTest),
                     (EntregaCierraParcialTest, f10.RenameAntesDeNotaTest)):
    for _n in [n for n in dir(_base) if n.startswith("test_")]:  # only each class's own tests run here
        if _n not in _cls.__dict__:
            setattr(_cls, _n, None)


if __name__ == "__main__":
    unittest.main()

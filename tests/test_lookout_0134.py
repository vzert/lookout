"""0.13.4: the supervisor is told when the skill text it loaded is older than the installed lookout (p-72a8efc1a9).
Run: python3 -m unittest tests/test_lookout_0134.py
"""
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f4 as f4  # noqa: E402

import lookout_state  # noqa: E402
import registry  # noqa: E402
import time  # noqa: E402
import on_supervisor  # noqa: E402

PID, SUP = f4.PID, f4.SUP
CACHE = "/opt/claude/plugins/cache/lookout-marketplace/lookout"


class SkillViejaTest(f4.Base):
    start_waiter = f4.DigestBudgetTest.start_waiter

    def setUp(self):
        super().setUp()
        self.saved["CLAUDE_CONFIG_DIR"] = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(self.tmp.name, "claude")
        self.instala("0.13.3")
        self.tr = os.path.join(self.tmp.name, "sup.jsonl")
        open(self.tr, "w").close()
        f4.supervisor_md.mark_supervisor(SUP, PID)
        self.waiter = self.start_waiter(os.getpid(), SUP)  # only the skill check speaks

    def tearDown(self):
        self.waiter.kill()
        self.waiter.wait()
        self.waiter.stdout.close()
        super().tearDown()

    def instala(self, version, marketplace="lookout-marketplace"):
        path = on_supervisor.installed_plugins_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump({"version": 2, "plugins": {"lookout@" + marketplace: [
                {"scope": "user", "installPath": "%s/%s" % (CACHE, version), "version": version}]}}, fh)

    def carga(self, version, skill="supervisa"):
        text = "Base directory for this skill: %s/%s/skills/%s\n\n# Supervisa" % (CACHE, version, skill)
        with open(self.tr, "a") as fh:
            fh.write(json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": text}]}}) + "\n")

    def stop(self):
        return on_supervisor.stop_check({"transcript_path": self.tr}, PID, SUP, grace=0)

    def test_an_old_skill_text_is_reminded_once(self):
        # 3-tier-memory 2026-10-16: 0.13.3 installed by /plugin, the supervisor still on the 0.13.2 skill text
        self.carga("0.13.2")
        out = self.stop()
        self.assertIn("cargada es la 0.13.2 y la instalada es la 0.13.3", f4.sigue(out))
        self.assertIn("Skill", f4.sigue(out))
        self.assertIn("0.13.2 cargada, 0.13.3 instalada", json.loads(out)["systemMessage"])
        self.assertEqual(self.stop(), "")            # once per pair
        self.instala("0.13.4")
        self.assertIn("la instalada es la 0.13.4", f4.sigue(self.stop()))  # a new install is a new pair

    def test_the_last_load_counts(self):
        self.carga("0.13.2")
        self.carga("0.13.3")
        self.assertEqual(self.stop(), "")
        self.carga("0.13.2")                         # read from where the last Stop left it
        self.assertIn("cargada es la 0.13.2", f4.sigue(self.stop()))

    def test_a_newer_loaded_text_is_no_reason(self):
        # adversary r1: loaded 0.13.4 with 0.13.3 installed asked for a reload
        self.carga("0.13.4")
        self.assertEqual(self.stop(), "")

    def test_a_transcript_replaced_in_place_is_read_again(self):
        # adversary r1: same path, a longer new file whose older load sits before the saved offset was missed
        self.carga("0.13.3")
        with open(self.tr, "a") as fh:
            fh.write(json.dumps({"type": "user", "message": {"content": "a" * 5000}}) + "\n")
        self.assertEqual(self.stop(), "")
        with open(self.tr, "w") as fh:
            fh.write(json.dumps({"type": "user", "message": {"content": "otro arranque"}}) + "\n")
        self.carga("0.13.2")
        with open(self.tr, "a") as fh:
            fh.write(json.dumps({"type": "user", "message": {"content": "b" * 9000}}) + "\n")
        self.assertIn("cargada es la 0.13.2", f4.sigue(self.stop()))

    def test_versions_sort_like_semver(self):
        v = on_supervisor._ver
        self.assertGreater(v("0.13.4-rc2"), v("0.13.4-rc1"))       # adversary r2
        self.assertGreater(v("0.13.4"), v("0.13.4-rc1"))
        self.assertGreater(v("0.13.10"), v("0.13.9"))
        self.assertFalse(v("0.13.4") > v("0.13.4"))

    def test_unsure_says_nothing(self):
        self.assertEqual(self.stop(), "")            # nothing loaded in the transcript
        self.carga("0.13.2", skill="pendientes")     # another skill of lookout
        self.assertEqual(self.stop(), "")
        self.carga("0.13.2")
        self.instala("0.13.3", marketplace="lookout-dev")  # installed from another marketplace
        self.assertEqual(self.stop(), "")
        self.assertEqual(on_supervisor.stop_check({}, PID, SUP, grace=0), "")  # no transcript


class UniqueNameTest(unittest.TestCase):
    def test_a_relief_of_a_32_character_name_stays_in_herdrs_limit(self):
        # live 3-tier 2026-10-16: «agente-3-tier-memory-prueba-de-l» + «-2» = 34, invalid_agent_name after the /exit
        import lote
        import re
        base = "agente-3-tier-memory-prueba-de-l"
        name = lote.unique_name(base, agents=[{"name": base}])
        self.assertRegex(name, r"^[a-z][a-z0-9_-]{0,31}$")
        self.assertTrue(name.endswith("-2"))
        many = [{"name": base}] + [{"name": base[:30] + "-%d" % i} for i in range(2, 10)]
        self.assertEqual(lote.unique_name(base, agents=many), base[:29] + "-10")
        self.assertEqual(lote.unique_name("corto", agents=[]), "corto")


class ReliefFailedTest(f4.Base):
    def test_a_failed_relief_stays_in_te_necesita_on_every_wake(self):
        # live 3-tier 2026-10-16: the relief failed after the /exit; the agent went to «terminados» and the supervisor
        # never told the user, and the session that never started showed as «x~3b9909 | sin eventos»
        import digest
        import time
        self.agent("s1", "prueba", tarea_estado="relevo-fallido", tarea_motivo="no llegó el SessionStart")
        self.agent("s2", "prueba~s2", tarea_estado="fallida", relevo_de="s1")
        lookout_state.append_event(PID, {"event": "end", "session_id": "s1", "nombre": "prueba", "ts": time.time()})
        for _ in range(2):
            out = digest.render(PID, mark=True, por_waiter=True)
            self.assertIn("Te necesita:", out)
            self.assertIn("relevo fallido → díselo al usuario", out.split("Te necesita:")[1])
            self.assertNotIn("prueba~s2", out)


import test_lookout_0130 as t130  # noqa: E402


class CierraRelevoFallidoTest(t130.CierraPestanaTest):
    """Adversary r1 (both backends): the failed-relief row advertised `cierra-pestana`, which refused it (its pane is a
    shell, its last turn keeps the block), and a tab the user closed by hand left the row forever."""

    def setUp(self):
        super().setUp()
        self.found, self.pane_session = True, None
        self.saved_pg = self.retiro.herdr_cli.pane_get
        self.retiro.herdr_cli.pane_get = lambda p: ((True, {"agent_session": {"value": self.pane_session}})
                                                    if self.found else (False, None))
        reg = registry.load(self.pid)
        reg["agents"]["s1"].update(tarea_estado="relevo-fallido", relevo_fallido_ts=time.time() - 10)
        registry.save(self.pid, reg)
        self.last("## Como retomar\n```\nRetomamos: x. Proximo paso: contar.\n```")

    def tearDown(self):
        self.retiro.herdr_cli.pane_get = self.saved_pg
        super().tearDown()

    def decide(self, did, aprueba, desde, agentes=("sidebar",)):
        import decisiones
        d = decisiones.load(self.pid)
        d.setdefault("items", []).append({"id": did, "agentes": list(agentes), "desde": desde, "estado": "respondida",
                                          "aprueba": aprueba})
        lookout_state.write_json(decisiones.path(self.pid), d)

    def cierra_con(self, did):
        e = registry.load(self.pid)["agents"]["s1"]
        return self.retiro.cierra(self.pid, e, "", fin_timeout=1, log=lambda m: None, confirmo=did)

    def no_con(self, did, frase):
        ok, msg = self.cierra_con(did)
        self.assertFalse(ok, msg)
        self.assertIn(frase, msg)
        self.assertEqual(self.calls, [])
        self.assertFalse(registry.load(self.pid)["agents"]["s1"].get("retirado"))

    def test_it_needs_the_users_yes_named_by_id(self):
        self.no_con("", "solo con la decisión del usuario")
        self.decide("d1", True, time.time() - 60)       # the «Relevarlo» that led to the failure
        self.no_con("d1", "no es un sí del usuario abierto después del fallo")
        self.decide("d2", False, time.time())
        self.no_con("d2", "no es un sí")
        self.decide("d3", True, time.time(), agentes=("otro",))
        self.no_con("d3", "no es un sí")
        self.decide("d4", True, time.time())
        self.no_con("d5", "solo con la decisión del usuario")  # an id that does not exist

    def test_with_the_users_yes_it_closes_without_exit(self):
        self.decide("d4", True, time.time())
        ok, msg = self.cierra_con("d4")
        self.assertTrue(ok, msg)
        self.assertEqual(self.calls, [["tab", "close", "w1A:tE"]])     # nothing to /exit: its session ended
        self.assertTrue(registry.load(self.pid)["agents"]["s1"].get("retirado"))

    def test_another_session_in_its_pane_stops_it(self):
        # adversary r2: the check reads the pane, not `agent list` (empty when herdr fails)
        self.decide("d4", True, time.time())
        self.pane_session = "otra-sesion"
        self.no_con("d4", "su pane tiene otra sesión")
        self.pane_session = "s1"                        # its own ended session still on the pane is fine
        self.assertTrue(self.cierra_con("d4")[0])

    def test_a_tab_the_user_closed_leaves_the_table_and_says_what_was_left(self):
        self.found = False
        with open(os.path.join(self.repo, "a.txt"), "a") as fh:
            fh.write("sin commit\n")
        ok, msg = self.cierra_con("")
        self.assertTrue(ok, msg)
        self.assertIn("ya no existe", msg)
        self.assertIn("Díselo al usuario, quedó:", msg)              # adversary r2: the guards still speak
        self.assertEqual(self.calls, [])
        self.assertTrue(registry.load(self.pid)["agents"]["s1"].get("retirado"))


for _n in [n for n in dir(t130.CierraPestanaTest) if n.startswith("test_")]:  # only this class's own tests run here
    if _n not in CierraRelevoFallidoTest.__dict__:
        setattr(CierraRelevoFallidoTest, _n, None)

if __name__ == "__main__":
    unittest.main()

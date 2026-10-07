"""Unit tests for phase 3 (gobierno.py, publica.py, cierre.py, relevo.py, decisiones.py).
Run: python3 -m unittest tests/test_lookout_f3.py

Transcripts are written in Claude Code's .jsonl shape; git repos are real (temp folders, a bare "origin");
the journal test runs 3-tier's own journal-emit + journal-compact on a copy of the real fixture.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "plugins", "lookout", "bin")
FIX = os.path.join(ROOT, "tests", "fixtures")
sys.path.insert(0, BIN)

import cierre  # noqa: E402
import decisiones  # noqa: E402
import gobierno  # noqa: E402
import herdr_cli  # noqa: E402
import lookout_state  # noqa: E402
import pendientes  # noqa: E402
import publica  # noqa: E402
import registry  # noqa: E402
import relevo  # noqa: E402

SALUDO = "p-e2be0f2c64"
FAQ, CHANGELOG = "p-743ebd0898", "p-990b334946"  # never launched in these tests (Fase 9 C1)
HOLD = "[ADVERSARY-VERDICT: hold ungrounded=0 unfalsified=0 incomplete=0 autonomy-violations=0 unsafe=0]"
BREAK = "[ADVERSARY-VERDICT: break ungrounded=1 unfalsified=0 incomplete=0 autonomy-violations=0 unsafe=1]"
BREAK_SAFE = "[ADVERSARY-VERDICT: break ungrounded=0 unfalsified=0 incomplete=2 autonomy-violations=0 unsafe=0]"
M_EXT = "[ADVERSARY-MODEL: gpt-5.6-luna / gpt-5.6-luna]"
M_SAME = "[ADVERSARY-MODEL: Claude Haiku 4.5 / claude-haiku-4-5-20251001]"
M_UNK = "[ADVERSARY-MODEL: Claude / UNKNOWN]"
HAIKU = "claude-haiku-4-5-20251001"


def a_text(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def a_tool(name, inp):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}


def tool_result(text):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "content": text}]}}


SPAWN = a_tool("Agent", {"subagent_type": "goalspec:goal-adversary", "prompt": "x", "model": "sonnet"})
EXT = a_tool("Bash", {"command": "bash /x/goalspec/hooks/external-adversary.sh < payload.txt"})


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True, check=True).stdout.strip()


class Base(unittest.TestCase):
    pid = "pF3"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "state")
        self.projects = os.path.join(self.tmp.name, "projects")
        self.old = os.environ.get("LOOKOUT_STATE_DIR")
        os.environ["LOOKOUT_STATE_DIR"] = self.state
        # goalspec installed (user scope) in a config of our own: the host's plugins must not decide a test (Fase 7)
        cfg = os.path.join(self.tmp.name, "claude-config", "plugins")
        os.makedirs(cfg)
        with open(os.path.join(cfg, "installed_plugins.json"), "w") as fh:
            json.dump({"version": 2, "plugins": {"goalspec@goal-forge": [{"scope": "user", "version": "0"}]}}, fh)
        self.old_cfg = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.dirname(cfg)
        self.old_tp = gobierno.deliver.transcript_path
        projects = self.projects
        gobierno.deliver.transcript_path = lambda sid, pd=None: self.old_tp(sid, pd or projects)

    def tearDown(self):
        gobierno.deliver.transcript_path = self.old_tp
        if self.old_cfg is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self.old_cfg
        if self.old is None:
            os.environ.pop("LOOKOUT_STATE_DIR", None)
        else:
            os.environ["LOOKOUT_STATE_DIR"] = self.old
        self.tmp.cleanup()

    def transcript(self, sid, events):
        d = os.path.join(self.projects, "-enc")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, sid + ".jsonl"), "a") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")

    def agent(self, sid, nombre="ag", tarea="p-1", modelo=HAIKU, alta="2026-10-02T10:00:00", **kw):
        reg = registry.load(self.pid)
        reg.setdefault("agents", {})[sid] = dict({"session_id": sid, "nombre": nombre, "tarea": tarea, "alta": alta,
                                                  "pane_id": "w1:p1", "cwd": "/x", "worktree": "/x"}, **kw)
        registry.save(self.pid, reg)
        lookout_state.append_event(self.pid, {"session_id": sid, "event": "start", "modelo": modelo})
        return reg["agents"][sid]


class GobiernoTest(Base):
    def test_family(self):
        self.assertEqual(gobierno.family(HAIKU), "haiku")
        self.assertEqual(gobierno.family("Claude Sonnet 5.5 / claude-sonnet-5-5"), "sonnet")
        self.assertEqual(gobierno.family("gpt-5.6-luna / gpt-5.6-luna"), "gpt")
        self.assertEqual(gobierno.family("Claude / UNKNOWN"), "")
        self.assertEqual(gobierno.family(""), "")

    def test_stuck_counters_never_wipe_the_tasks(self):
        # 0.7.3, claude-vzert: heuristicas.py rewrote counters.json whole and `lookout gobierno` crashed (KeyError
        # 'tareas'); a limit the user raised was lost with it.
        import heuristicas
        e = self.agent("s1")
        self.transcript("s1", [a_text("trabajo")])
        gobierno.amplia(self.pid, e, 8)
        heuristicas.guarda_contadores(self.pid)
        st = gobierno.estado(self.pid, e, self.projects)
        self.assertEqual(st["limite"], 8)
        self.assertNotEqual(heuristicas.counters_path(self.pid), gobierno.counters_path(self.pid))

    def test_a_counters_file_without_tareas_is_read(self):
        # the file an older lookout left: {"ts", "agentes"} and no "tareas"
        e = self.agent("s1")
        self.transcript("s1", [a_text("trabajo")])
        lookout_state.write_json(gobierno.counters_path(self.pid), {"ts": 1, "agentes": {"s9": {"errores": {}}}})
        st = gobierno.estado(self.pid, e, self.projects)
        self.assertEqual(st["limite"], gobierno.LIMITE_RONDAS)
        data = lookout_state.read_json(gobierno.counters_path(self.pid))
        self.assertIn("tareas", data)
        self.assertNotIn("agentes", data)

    def test_markers_only_count_in_own_text_on_their_own_line(self):
        e = self.agent("s1")
        self.transcript("s1", [
            a_text("Pido push. El adversario dijo `%s` antes." % HOLD),        # inline mention: not a quote
            tool_result(M_EXT + "\n" + HOLD),                                   # a tool result: never counts
        ])
        st = gobierno.estado(self.pid, e, self.projects)
        self.assertIsNone(st["ultimo"])
        self.assertEqual(gobierno.decide_push(st)[1], "SIN-VEREDICTO")

    def test_a_verdict_quoted_in_its_own_sendmessage_counts(self):
        e = self.agent("s1")
        self.transcript("s1", [EXT, a_tool("SendMessage", {"to": "uds:x", "message": "Listo.\n" + M_SAME + "\n" + HOLD})])
        self.assertEqual(gobierno.decide_push(gobierno.estado(self.pid, e, self.projects))[1], "MISMO-MODELO")

    def test_a_model_line_from_an_older_text_does_not_vouch_for_a_later_verdict(self):
        e = self.agent("s1")
        self.transcript("s1", [EXT, a_text(M_EXT + "\n" + BREAK), EXT, a_text("Ronda 2:\n" + HOLD)])
        st = gobierno.estado(self.pid, e, self.projects)
        self.assertEqual(st["ultimo"]["modelo"], "")
        self.assertEqual(gobierno.decide_push(st)[1], "MISMO-MODELO")

    def test_last_break_blocks_push(self):
        e = self.agent("s1")
        self.transcript("s1", [EXT, a_text(M_EXT + "\n" + HOLD), EXT, a_text("Ronda 2:\n" + M_EXT + "\n" + BREAK)])
        ok, code, text = gobierno.decide_push(gobierno.estado(self.pid, e, self.projects))
        self.assertEqual((ok, code), (False, "BREAK"))
        self.assertIn("unsafe=1", text)

    def test_same_model_or_unknown_hold_needs_another_model(self):
        e = self.agent("s1")
        self.transcript("s1", [SPAWN, a_text(M_SAME + "\n" + HOLD)])
        self.assertEqual(gobierno.decide_push(gobierno.estado(self.pid, e, self.projects))[1], "MISMO-MODELO")
        self.transcript("s1", [SPAWN, a_text(M_UNK + "\n" + HOLD)])
        self.assertEqual(gobierno.decide_push(gobierno.estado(self.pid, e, self.projects))[1], "MISMO-MODELO")
        self.transcript("s1", [EXT, a_text(M_EXT + "\n" + HOLD)])
        st = gobierno.estado(self.pid, e, self.projects)
        self.assertEqual(gobierno.decide_push(st)[1], "OK")
        self.assertEqual(st["rondas"], 3)

    def test_round_cap_asks_the_user_then_allows_after_extension(self):
        e = self.agent("s1")
        self.transcript("s1", [EXT, a_text(M_EXT + "\n" + BREAK_SAFE)] * 5)
        st = gobierno.estado(self.pid, e, self.projects)
        self.assertEqual(st["rondas"], 5)
        ok, code, text = gobierno.decide_ronda(st)
        self.assertEqual((ok, code), (False, "PREGUNTA-USUARIO"))
        self.assertIn("abrir la 6", text)
        gobierno.amplia(self.pid, e, 6)
        self.assertEqual(gobierno.decide_ronda(gobierno.estado(self.pid, e, self.projects))[1], "OK")
        c = gobierno.load_counters(self.pid)["tareas"]["p-1"]
        self.assertEqual((c["limite"], c["rondas"]), (6, 5))

    def test_four_rounds_may_open_the_fifth(self):
        e = self.agent("s1")
        self.transcript("s1", [EXT, a_text(M_EXT + "\n" + BREAK_SAFE)] * 4)
        self.assertEqual(gobierno.decide_ronda(gobierno.estado(self.pid, e, self.projects))[1], "OK")

    def test_rounds_add_up_across_a_relief(self):
        self.agent("s1", alta="2026-10-02T10:00:00")
        e2 = self.agent("s2", alta="2026-10-02T11:00:00", relevo_de="s1")
        self.transcript("s1", [EXT, a_text(M_EXT + "\n" + BREAK)] * 3)
        self.transcript("s2", [SPAWN, a_text(M_EXT + "\n" + HOLD)] * 2)
        st = gobierno.estado(self.pid, e2, self.projects)
        self.assertEqual(st["rondas"], 5)
        self.assertEqual(st["ultimo"]["veredicto"], "hold")
        self.assertEqual(gobierno.decide_ronda(st)[1], "PREGUNTA-USUARIO")


class GitCase(Base):
    def setUp(self):
        super().setUp()
        t = self.tmp.name
        seed = os.path.join(t, "seed")
        os.makedirs(seed)
        git(seed, "init", "-q", "-b", "main")
        with open(os.path.join(seed, "VERSION"), "w") as fh:
            fh.write("0.1.0\n")
        with open(os.path.join(seed, "CHANGELOG.md"), "w") as fh:
            fh.write("# Changelog\n\n## 0.1.0\n- inicial\n")
        git(seed, "add", "-A")
        git(seed, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        self.origin = os.path.join(t, "origin.git")
        subprocess.run(["git", "clone", "-q", "--bare", seed, self.origin], check=True)
        self.repo = os.path.join(t, "repo")
        subprocess.run(["git", "clone", "-q", self.origin, self.repo], check=True)
        for k, v in (("user.name", "a"), ("user.email", "a@a")):
            git(self.repo, "config", k, v)

    def worktree(self, slug, sid, version="0.2.0", extra=""):
        wt = self.repo + "-wt-" + slug
        git(self.repo, "worktree", "add", "-q", "-b", "lookout/" + slug, wt, "origin/main")
        if version:
            with open(os.path.join(wt, "VERSION"), "w") as fh:
                fh.write(version + "\n")
            with open(os.path.join(wt, "CHANGELOG.md"), "w") as fh:
                fh.write("# Changelog\n\n## %s\n- %s\n\n## 0.1.0\n- inicial\n" % (version, slug))
        with open(os.path.join(wt, slug + ".txt"), "w") as fh:
            fh.write("hola " + extra + "\n")
        git(wt, "add", "-A")
        git(wt, "commit", "-qm", slug)
        e = self.agent(sid, nombre=slug, tarea="p-" + slug, worktree=wt, cwd=wt, base="origin/main", branch="lookout/" + slug)
        self.transcript(sid, [EXT, a_text(M_EXT + "\n" + HOLD)])
        return e

    def ask(self, e):
        return publica.pide(self.pid, e, gobierno.estado(self.pid, e, self.projects))


class PublicaTest(GitCase):
    def test_two_agents_same_version_are_serialized_and_second_must_renumber(self):
        a = self.worktree("uno", "sa")
        b = self.worktree("dos", "sb")
        ok, code, lines = self.ask(a)
        self.assertEqual((ok, code), (True, "LISTA"), lines)
        self.assertIn("git push origin HEAD:main", lines[-1])
        ok, code, _ = self.ask(b)
        self.assertEqual((ok, code), (False, "ESPERA"))
        git(a["worktree"], "push", "-q", "origin", "HEAD:main")
        ok, lines = publica.hecho(self.pid, a)
        self.assertTrue(ok, lines)
        self.assertIn("dos", lines[-1])
        ok, code, _ = self.ask(b)            # same base, now stale
        self.assertEqual(code, "BASE-MOVIDA")
        git(b["worktree"], "fetch", "-q", "origin")
        r = subprocess.run(["git", "-C", b["worktree"], "rebase", "-q", "origin/main"], capture_output=True, text=True)
        if r.returncode != 0:  # VERSION and CHANGELOG conflict: keep b's side (0.2.0 again), renumber below
            git(b["worktree"], "checkout", "--theirs", "VERSION", "CHANGELOG.md")
            git(b["worktree"], "add", "VERSION", "CHANGELOG.md")
            subprocess.run(["git", "-C", b["worktree"], "-c", "core.editor=true", "rebase", "--continue"],
                           capture_output=True, check=True)
        ok, code, _ = self.ask(b)            # rebased, its changelog entry still says 0.2.0, which origin already has
        self.assertEqual(code, "VERSION-SIN-RENUMERAR")
        with open(os.path.join(b["worktree"], "VERSION"), "w") as fh:
            fh.write("0.3.0\n")
        git(b["worktree"], "commit", "-qam", "renumera")
        ok, code, lines = self.ask(b)
        self.assertEqual((ok, code), (True, "LISTA"), lines)
        vers = [p.get("version") for p in publica.load(self.pid)["cola"] if p["estado"] in ("lista", "publicada")]
        self.assertEqual(sorted(vers), ["0.2.0", "0.3.0"])

    def test_a_push_that_changes_no_version_file_claims_no_version(self):
        a = self.worktree("doc", "sa", version="")
        ok, code, lines = self.ask(a)
        self.assertEqual((ok, code), (True, "LISTA"), lines)
        self.assertTrue(any("no la cambia" in l for l in lines))

    def test_a_ready_publication_that_went_stale_does_not_block_the_queue(self):
        a = self.worktree("uno", "sa", version="0.2.0")
        self.assertEqual(self.ask(a)[1], "LISTA")
        self.transcript("sa", [EXT, a_text(M_EXT + "\n" + BREAK)])     # a later round broke it
        b = self.worktree("dos", "sb", version="0.3.0")
        ok, code, lines = self.ask(b)
        self.assertEqual((ok, code), (True, "LISTA"), lines)
        estados = {p["nombre"]: p["estado"] for p in publica.load(self.pid)["cola"]}
        self.assertEqual(estados, {"uno": "caducada", "dos": "lista"})

    def test_a_ready_publication_whose_head_moved_is_stale(self):
        a = self.worktree("uno", "sa", version="0.2.0")
        self.assertEqual(self.ask(a)[1], "LISTA")
        with open(os.path.join(a["worktree"], "otro.txt"), "w") as fh:
            fh.write("x\n")
        git(a["worktree"], "add", "-A")
        git(a["worktree"], "commit", "-qm", "otro")
        b = self.worktree("dos", "sb", version="0.3.0")
        self.assertEqual(self.ask(b)[1], "LISTA")

    def test_version_used_by_another_ready_publication(self):
        a = self.worktree("uno", "sa", version="0.2.0")
        self.assertEqual(self.ask(a)[1], "LISTA")
        publica.retira(self.pid, a)
        led = publica.load(self.pid)
        led["cola"][0]["estado"] = "publicada"   # as if it went out, origin not yet fetched by b
        publica.save(self.pid, led)
        b = self.worktree("dos", "sb", version="0.2.0")
        self.assertEqual(self.ask(b)[1], "VERSION-USADA")

    def test_break_dirty_and_private_paths_are_refused(self):
        a = self.worktree("uno", "sa", extra="ver /Users/alguien/secreto")
        self.assertEqual(self.ask(a)[1], "RUTAS-PRIVADAS")
        publica.retira(self.pid, a)
        b = self.worktree("dos", "sb")
        with open(os.path.join(b["worktree"], "dos.txt"), "a") as fh:
            fh.write("sin commit\n")
        self.assertEqual(self.ask(b)[1], "SUCIO")
        publica.retira(self.pid, b)
        c = self.worktree("tres", "sc")
        self.transcript("sc", [EXT, a_text(M_EXT + "\n" + BREAK)])
        self.assertEqual(self.ask(c)[1], "BREAK")

    def test_more_private_paths(self):
        for i, txt in enumerate(["ver /tmp/x.log", "en ~/notas.md", "home /root/.ssh", "de /var/tmp/a"]):
            e = self.worktree("p%d" % i, "sp%d" % i, version="", extra=txt)
            self.assertEqual(self.ask(e)[1], "RUTAS-PRIVADAS", txt)
            publica.retira(self.pid, e)

    def test_a_ready_publication_of_a_session_that_ended_is_stale(self):
        a = self.worktree("uno", "sa", version="0.2.0")
        self.assertEqual(self.ask(a)[1], "LISTA")
        lookout_state.append_event(self.pid, {"session_id": "sa", "event": "end"})
        b = self.worktree("dos", "sb", version="0.3.0")
        self.assertEqual(self.ask(b)[1], "LISTA")

    def test_rule_is_read_never_written(self):
        self.assertEqual(publica.regla_estado(self.repo)[0], "ausente")
        self.assertFalse(os.path.exists(publica.settings_path(self.repo)))
        txt = publica.regla_texto(self.repo)
        self.assertIn(publica.settings_path(self.repo), txt)
        self.assertFalse(os.path.exists(publica.settings_path(self.repo)))
        snippet = json.loads(txt[txt.index("{"):])
        os.makedirs(os.path.join(self.repo, ".claude"))
        with open(publica.settings_path(self.repo), "w") as fh:
            json.dump({"permissions": {"allow": publica.ALLOW}}, fh)
        self.assertEqual(publica.regla_estado(self.repo)[0], "parcial")   # push allowed, force not denied: not enough
        with open(publica.settings_path(self.repo), "w") as fh:
            json.dump(snippet, fh)
        self.assertEqual(publica.regla_estado(self.repo)[0], "aplicada")

    def test_version_sources(self):
        wt = self.repo
        self.assertEqual(publica.version_at(wt, "HEAD"), ("VERSION", "0.1.0"))
        os.remove(os.path.join(wt, "VERSION"))
        with open(os.path.join(wt, "CHANGELOG.md"), "w") as fh:
            fh.write("# Changelog\n\n## 1.4.2 — algo\n\n## 1.4.1\n")
        git(wt, "add", "-A")
        git(wt, "commit", "-qm", "cl")
        self.assertEqual(publica.version_at(wt, "HEAD"), ("CHANGELOG.md", "1.4.2"))


TIER_BIN = cierre.tier_bin()  # read with the host's config, before Base points CLAUDE_CONFIG_DIR at a temp dir


class CierreTest(Base):
    def setUp(self):
        super().setUp()
        tb = TIER_BIN
        if not tb or not os.path.isfile(os.path.join(tb, "journal-compact.py")):
            self.skipTest("plugin 3-tier no instalado (en CI: LOOKOUT_3TIER_BIN)")
        self.tb = tb
        self.old_tb = os.environ.get("LOOKOUT_3TIER_BIN")
        os.environ["LOOKOUT_3TIER_BIN"] = tb
        self.addCleanup(lambda: os.environ.__setitem__("LOOKOUT_3TIER_BIN", self.old_tb) if self.old_tb is not None
                        else os.environ.pop("LOOKOUT_3TIER_BIN", None))
        self.root = os.path.join(self.tmp.name, "repo")
        mem = os.path.join(self.root, "memory")
        for d in ("learnings", "sessions", "pendientes", "plans", "research"):
            os.makedirs(os.path.join(mem, d))
        with open(os.path.join(mem, ".memory-config"), "w") as fh:
            fh.write("journal_strict=1\n")
        shutil.copy(os.path.join(FIX, "pendientes-3t.md"), os.path.join(mem, "_pendientes.md"))
        self.pend = os.path.join(mem, "_pendientes.md")
        self.common = os.path.join(self.root, ".git")

    def test_close_goes_through_the_journal_and_lands_only_on_compaction(self):
        e = self.agent("s1", tarea=SALUDO)
        self.transcript("s1", [EXT, a_text(M_EXT + "\n" + HOLD)])
        st = gobierno.estado(self.pid, e, self.projects)
        before = open(self.pend).read()
        ok, lines = cierre.cierra(self.pid, self.common, e, st, "resolved", "saludo.py creado y verificado", True,
                                  sin_push="banco de prueba sin origin")
        self.assertTrue(ok, lines)
        self.assertEqual(open(self.pend).read(), before)          # untouched by the emit
        journal = os.listdir(os.path.join(self.root, "memory", ".journal"))
        self.assertTrue(journal)
        subprocess.run(["python3", os.path.join(self.tb, "journal-compact.py"), "--memory-dir",
                        os.path.join(self.root, "memory"), "--quiet"], check=True)
        self.assertNotIn(SALUDO, [it["id"] for it in pendientes.parse(self.pend)])
        self.assertEqual(registry.load(self.pid)["agents"]["s1"]["tarea_estado"], "terminada")

    def test_close_refuses_without_user_or_hold(self):
        e = self.agent("s1", tarea=SALUDO)
        self.transcript("s1", [EXT, a_text(M_EXT + "\n" + BREAK)])
        st = gobierno.estado(self.pid, e, self.projects)
        ok, lines = cierre.cierra(self.pid, self.common, e, st, "resolved", "n", False, sin_push="x")
        self.assertFalse(ok)
        self.assertIn("usuario", lines[0])
        ok, lines = cierre.cierra(self.pid, self.common, e, st, "resolved", "n", True, sin_push="x")
        self.assertFalse(ok)
        self.assertIn("hold", lines[0])
        self.assertFalse(os.path.exists(os.path.join(self.root, "memory", ".journal")))

    def compacta(self):
        subprocess.run(["python3", os.path.join(self.tb, "journal-compact.py"), "--memory-dir",
                        os.path.join(self.root, "memory"), "--quiet"], check=True)
        return [it["id"] for it in pendientes.parse(self.pend)]

    def test_abandoning_needs_the_user_but_no_hold_and_no_push(self):
        # Fase 9 C2: an abandoned task claims no result; claude-vzert had no way to close one without a hold or a push.
        e = self.agent("s1", tarea=SALUDO)
        self.transcript("s1", [EXT, a_text(M_EXT + "\n" + BREAK)])
        st = gobierno.estado(self.pid, e, self.projects)
        ok, lines = cierre.cierra(self.pid, self.common, e, st, "abandoned", "ya no hace falta", False)
        self.assertFalse(ok)
        self.assertIn("usuario", lines[0])
        ok, lines = cierre.cierra(self.pid, self.common, e, st, "abandoned", "ya no hace falta", True)
        self.assertTrue(ok, lines)
        self.assertNotIn(SALUDO, self.compacta())
        ok, lines = cierre.cierra(self.pid, self.common, dict(e, tarea=FAQ), st, "resolved", "n", True)
        self.assertFalse(ok)  # a resolved close still needs the hold
        self.assertIn("hold", lines[0])

    def test_a_pendiente_that_never_had_an_agent_is_discarded_by_journal(self):
        # Fase 9 C1: before `descarta`, the supervisor emitted journal events by hand for p-1bb49d113a.
        ok, lines = cierre.descarta(self.pid, self.common, FAQ, "abandoned", "n", False, "sup")
        self.assertFalse(ok)
        self.assertIn("usuario", lines[0])
        ok, lines = cierre.descarta(self.pid, self.common, FAQ, "resolved", "n", True, "sup")
        self.assertFalse(ok)
        self.assertIn("lookout cierra", lines[0])
        self.agent("s1", tarea=CHANGELOG, tarea_estado="trabajando")
        ok, lines = cierre.descarta(self.pid, self.common, CHANGELOG, "abandoned", "n", True, "sup")
        self.assertFalse(ok)
        self.assertIn("tiene un agente", lines[0])
        self.assertFalse(os.path.exists(os.path.join(self.root, "memory", ".journal")))
        ok, lines = cierre.descarta(self.pid, self.common, FAQ, "superseded", "lo cubre otro", True, "sup")
        self.assertTrue(ok, lines)
        abiertos = self.compacta()
        self.assertNotIn(FAQ, abiertos)
        self.assertIn(CHANGELOG, abiertos)


class RegistryAfterReliefTest(Base):
    def test_find_prefers_the_live_session_over_the_relieved_one(self):
        reg = {"agents": {
            "old": {"session_id": "old", "nombre": "ag~old", "pane_id": "w1:p1", "herdr_name": "ag", "tarea_estado": "relevada"},
            "new": {"session_id": "new", "nombre": "ag", "pane_id": "w1:p1", "herdr_name": "ag-2", "tarea_estado": "trabajando"}}}
        self.assertEqual(registry.find(reg, "ag")["session_id"], "new")
        self.assertEqual(registry.find(reg, "w1:p1")["session_id"], "new")
        self.assertEqual(registry.find(reg, "old")["session_id"], "old")
        self.assertEqual(registry.find(reg, "ag~old")["session_id"], "old")


class RelevoTest(Base):
    def test_extract_como_retomar(self):
        text = ("Listo.\n\n## Como retomar\n\n```\nRetomamos: tarea p-1.\nProximo paso: correr checks.\n```\n\n## Otra\nx")
        self.assertEqual(relevo.extract_retomar(text), "Retomamos: tarea p-1.\nProximo paso: correr checks.")
        self.assertEqual(relevo.extract_retomar("**Como retomar**\nSigue con X.\nY."), "Sigue con X.\nY.")
        self.assertEqual(relevo.extract_retomar("nada aquí"), "")

    def test_last_como_retomar_wins_and_prompt_keeps_task(self):
        e = self.agent("s1", tarea="p-1")
        self.transcript("s1", [a_text("## Como retomar\n```\nviejo\n```"), a_text("## Como retomar\n```\nnuevo\n```")])
        self.assertEqual(relevo.retomar_de("s1", self.projects), "nuevo")
        src = os.path.join(self.tmp.name, "p-1.sistema.md")
        with open(src, "w") as fh:
            fh.write("# Encargo\n\n## Tu tarea: p-1\nhaz x\n\n## Nota del supervisor\nnota vieja\n")
        e["prompt_sistema"] = src
        path = relevo.relevo_prompt(self.pid, e, "nuevo", "nota nueva", 1)
        body = open(path).read()
        self.assertIn("## Tu tarea: p-1", body)
        self.assertIn("## Relevo", body)
        self.assertIn("nuevo", body)
        self.assertIn("nota nueva", body)
        self.assertNotIn("nota vieja", body)


class RelevoFallidoTest(Base):
    def test_a_failed_start_keeps_the_task_with_the_old_session_and_can_be_retried(self):
        src = os.path.join(self.tmp.name, "p-1.sistema.md")
        with open(src, "w") as fh:
            fh.write("# Encargo\n## Tu tarea: p-1\n")
        self.agent("old", nombre="ag", pane_id="w9:p1", herdr_name="ag", prompt_sistema=src, tarea_estado="trabajando")
        saved = (relevo.herdr_cli.agent_get, relevo.herdr_cli.run, relevo.deliver.read_box, relevo.deliver.wait_event,
                 relevo.lote.arranca, relevo.lote.unique_name, relevo.lote.live_sessions)
        calls = []
        def arranca_falla(pid, sid, *a, **k):
            relevo.lote.set_estado(pid, sid, "fallida", "sin SessionStart")
            calls.append(sid)
            return False, "no llegó el SessionStart"
        relevo.herdr_cli.agent_get = lambda pane: {"agent_session": {"value": "old"}, "agent_status": "idle"}
        relevo.herdr_cli.run = lambda *a, **k: (0, "", "")
        relevo.deliver.read_box = lambda pane: ("vacia", "")
        relevo.deliver.wait_event = lambda *a, **k: True
        relevo.lote.arranca = arranca_falla
        relevo.lote.unique_name = lambda n, agents=None: n + "-2"
        relevo.lote.live_sessions = lambda: set()
        try:
            ok, msg = relevo._relevo(self.pid, registry.load(self.pid)["agents"]["old"], lambda n: "nota", "sigue con x",
                                     None, 1, 1, lambda m: None)
            self.assertFalse(ok)
            reg = registry.load(self.pid)["agents"]
            self.assertEqual((reg["old"]["tarea_estado"], reg["old"]["nombre"]), ("relevo-fallido", "ag"))
            self.assertEqual(reg[calls[0]]["nombre"], "ag~" + calls[0][:6])
            self.assertEqual(registry.find(registry.load(self.pid), "ag")["session_id"], "old")
            # retry: the old session ended, nothing to /exit, the saved "Como retomar" is reused
            lookout_state.append_event(self.pid, {"session_id": "old", "event": "end"})
            relevo.herdr_cli.agent_get = lambda pane: {}
            relevo.lote.arranca = lambda pid, sid, *a, **k: (relevo.lote.set_estado(pid, sid, "trabajando"), (True, "ok"))[1]
            ok, msg = relevo._relevo(self.pid, registry.load(self.pid)["agents"]["old"], lambda n: "nota", "", None, 1, 1,
                                     lambda m: None)
            self.assertTrue(ok, msg)
            reg = registry.load(self.pid)["agents"]
            self.assertEqual(reg["old"]["tarea_estado"], "relevada")
            self.assertEqual(registry.find(registry.load(self.pid), "ag")["tarea_estado"], "trabajando")
        finally:
            (relevo.herdr_cli.agent_get, relevo.herdr_cli.run, relevo.deliver.read_box, relevo.deliver.wait_event,
             relevo.lote.arranca, relevo.lote.unique_name, relevo.lote.live_sessions) = saved


class DecisionesTest(Base):
    def test_open_close_and_age(self):
        old = herdr_cli.HERDR
        herdr_cli.HERDR = "true"
        try:
            it = decisiones.abre(self.pid, "¿push de uno?", ["uno"])
        finally:
            herdr_cli.HERDR = old
        txt = decisiones.render(self.pid, now=it["desde"] + 5 * 3600 + 60)
        self.assertIn("hace 5 h 1 min", txt)
        self.assertIn("esperan: uno", txt)
        self.assertIsNone(decisiones.respondida(self.pid, it["id"]))   # asked, not answered: cannot be cited
        decisiones.cierra(self.pid, it["id"], "sí", True)
        self.assertEqual(decisiones.render(self.pid), "")
        self.assertEqual(decisiones.respondida(self.pid, it["id"])["respuesta"], "sí")
        self.assertIsNone(decisiones.respondida(self.pid, "d99"))

    def test_an_answer_no_authorizes_nothing(self):
        old = herdr_cli.HERDR
        herdr_cli.HERDR = "true"
        try:
            it = decisiones.abre(self.pid, "¿cierro p-1?")
        finally:
            herdr_cli.HERDR = old
        decisiones.cierra(self.pid, it["id"], "no, déjalo abierto", False)
        self.assertIsNone(decisiones.respondida(self.pid, it["id"]))
        self.assertEqual(decisiones.render(self.pid), "")             # answered: no longer pending

    def test_cli_needs_a_yes_decision_to_confirm_or_extend(self):
        old = herdr_cli.HERDR
        herdr_cli.HERDR = "true"
        try:
            it = decisiones.abre(self.pid, "¿amplío a 6?")
        finally:
            herdr_cli.HERDR = old
        decisiones.cierra(self.pid, it["id"], "no", False)
        self.agent("s1")
        lookout_state.write_json(os.path.join(lookout_state.project_dir(self.pid), "lock.json"),
                                 {"common_dir": os.path.join(self.tmp.name, "repo", ".git")})
        lk = os.path.join(BIN, "lookout")
        env = dict(os.environ, LOOKOUT_STATE_DIR=self.state)
        r = subprocess.run(["python3", lk, "gobierno", self.pid, "ag", "--usuario-amplia", "6", "--decision", it["id"]],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertNotIn("limite", json.dumps(gobierno.load_counters(self.pid)))
        r = subprocess.run(["python3", lk, "decision", self.pid, "--cierra", "d1", "--respuesta", "x"],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 5)
        self.assertIn("--si", r.stdout)


if __name__ == "__main__":
    unittest.main()

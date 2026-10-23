"""0.13.50: audit of the supervisor on 3-tier-memory (2026-10-22). The main checkout stays behind origin after a merge
(3-tier: main «behind 5», an agent ran the memory scripts from the plugin cache because the checkout's were old); the
goalspec plain close («**¿Cerrado?** Sí.») read as a question by cierra-pestana (21 of 26 denials said «pregunta
algo»; in 6 of 10 last turns the label was the only «?»); the
supervisor polling relevo/recarga/envia against a working agent (up to 6 calls in a row); an idle agent without a task
nobody saw for 38 minutes; publica printing «Adversario: OK» before its NO; RUTAS-PRIVADAS on generic paths.
Run: python3 -m unittest tests/test_lookout_01350.py
"""
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f3 as f3  # noqa: E402

import deliver  # noqa: E402
import digest  # noqa: E402
import lookout_state  # noqa: E402
import publica  # noqa: E402
import retiro  # noqa: E402

git = f3.git


class CheckoutCase(f3.GitCase):
    """The repo of GitCase is the main checkout; a second clone pushes to origin as a merged PR would."""

    def setUp(self):
        super().setUp()
        lookout_state.write_json(os.path.join(lookout_state.project_dir(self.pid), "lock.json"), {
            "project_id": self.pid, "common_dir": os.path.realpath(self.repo) + "/.git",
            "roots": [self.repo], "supervisor": {"session_id": "s-sup", "pid": os.getpid()}})
        otro = os.path.join(self.tmp.name, "otro")
        subprocess.run(["git", "clone", "-q", self.origin, otro], check=True)
        for k, v in (("user.name", "b"), ("user.email", "b@b")):
            git(otro, "config", k, v)
        for i in range(3):
            with open(os.path.join(otro, "f%d.txt" % i), "w") as fh:
                fh.write("x\n")
            git(otro, "add", "-A")
            git(otro, "commit", "-qm", "merged %d" % i)
        git(otro, "push", "-q", "origin", "main")
        self.tip = git(otro, "rev-parse", "HEAD")
        self.head0 = git(self.repo, "rev-parse", "HEAD")

    def head(self):
        return git(self.repo, "rev-parse", "HEAD")


class AlDiaTest(CheckoutCase):
    def test_fast_forwards_a_clean_main(self):
        lines = publica.al_dia(self.pid, fetch=True)
        self.assertEqual(self.head(), self.tip)
        self.assertTrue(any("al día" in l and "3 commit" in l for l in lines), lines)

    def test_without_fetch_uses_the_local_origin_ref(self):
        git(self.repo, "fetch", "-q", "origin")
        publica.al_dia(self.pid)
        self.assertEqual(self.head(), self.tip)

    def test_dirty_tree_is_left_alone_with_the_command(self):
        with open(os.path.join(self.repo, "VERSION"), "w") as fh:
            fh.write("9.9.9\n")
        lines = publica.al_dia(self.pid, fetch=True)
        self.assertEqual(self.head(), self.head0)
        self.assertTrue(any("pull --ff-only" in l and "sin commit" in l for l in lines), lines)

    def test_an_untracked_file_is_left_alone_too(self):
        with open(os.path.join(self.repo, "nuevo.txt"), "w") as fh:
            fh.write("de un agente\n")
        lines = publica.al_dia(self.pid, fetch=True)
        self.assertEqual(self.head(), self.head0)
        self.assertTrue(any("nuevo.txt" in l for l in lines), lines)

    def test_an_ignored_file_origin_brings_is_left_alone(self):
        with open(os.path.join(self.repo, ".git", "info", "exclude"), "a") as fh:
            fh.write("f1.txt\nlocal-ignorado.txt\n")
        with open(os.path.join(self.repo, "f1.txt"), "w") as fh:
            fh.write("del checkpoint\n")
        lines = publica.al_dia(self.pid, fetch=True)
        self.assertEqual(self.head(), self.head0)
        self.assertTrue(any("f1.txt" in l and "ignorado" in l for l in lines), lines)
        with open(os.path.join(self.repo, "f1.txt")) as fh:
            self.assertEqual(fh.read(), "del checkpoint\n")

    def test_an_ignored_file_origin_does_not_touch_does_not_block(self):
        with open(os.path.join(self.repo, ".git", "info", "exclude"), "a") as fh:
            fh.write("memoria.md\n")
        with open(os.path.join(self.repo, "memoria.md"), "w") as fh:
            fh.write("x\n")
        publica.al_dia(self.pid, fetch=True)
        self.assertEqual(self.head(), self.tip)

    def test_mira_changes_nothing(self):
        lines = publica.al_dia(self.pid, fetch=True, mira=True)
        self.assertEqual(self.head(), self.head0)
        self.assertTrue(any("lo pondría al día" in l and "3 commit" in l for l in lines), lines)

    def test_a_live_agent_with_no_event_blocks_it_a_dead_one_does_not(self):
        self.agent("s-v", nombre="sin-eventos", cwd=self.repo, worktree=self.repo)
        led = lookout_state.read_events(self.pid, 0)[0]
        # f3.agent writes a start event; this agent must have none
        with open(lookout_state.events_path(self.pid), "w") as fh:
            fh.write("")
        self.assertEqual(publica.en_turno_en(self.pid, self.repo, vivas={"s-v"}), ["sin-eventos"])
        self.assertEqual(publica.en_turno_en(self.pid, self.repo, vivas=set()), [])
        self.assertTrue(led is not None)

    def test_other_branch_is_left_alone(self):
        git(self.repo, "switch", "-q", "-c", "otra")
        lines = publica.al_dia(self.pid, fetch=True)
        self.assertEqual(self.head(), self.head0)
        self.assertTrue(any("otra" in l for l in lines), lines)

    def test_agent_in_turn_on_the_main_checkout_blocks_it(self):
        self.agent("s-a", nombre="trabaja", cwd=self.repo, worktree=self.repo)
        lookout_state.append_event(self.pid, {"session_id": "s-a", "event": "working", "ts": time.time()})
        lines = publica.al_dia(self.pid, fetch=True)
        self.assertEqual(self.head(), self.head0)
        self.assertTrue(any("trabaja" in l for l in lines), lines)

    def test_agent_between_turns_does_not_block_it(self):
        self.agent("s-a", nombre="quieto", cwd=self.repo, worktree=self.repo)
        lookout_state.append_event(self.pid, {"session_id": "s-a", "event": "working", "ts": time.time() - 9})
        lookout_state.append_event(self.pid, {"session_id": "s-a", "event": "idle", "ts": time.time()})
        publica.al_dia(self.pid, fetch=True)
        self.assertEqual(self.head(), self.tip)

    def test_a_hook_event_between_turns_does_not_block_it(self):
        self.agent("s-a", nombre="largo", cwd=self.repo, worktree=self.repo)
        lookout_state.append_event(self.pid, {"session_id": "s-a", "event": "idle", "ts": time.time() - 9})
        lookout_state.append_event(self.pid, {"session_id": "s-a", "event": "largo", "ts": time.time()})
        publica.al_dia(self.pid, fetch=True)
        self.assertEqual(self.head(), self.tip)

    def test_agent_in_its_own_worktree_does_not_block_it(self):
        self.agent("s-a", nombre="fuera", cwd=self.repo + "-wt-x", worktree=self.repo + "-wt-x")
        lookout_state.append_event(self.pid, {"session_id": "s-a", "event": "working", "ts": time.time()})
        publica.al_dia(self.pid, fetch=True)
        self.assertEqual(self.head(), self.tip)

    def test_local_commits_ahead_are_never_merged(self):
        with open(os.path.join(self.repo, "local.txt"), "w") as fh:
            fh.write("y\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "local")
        mine = self.head()
        lines = publica.al_dia(self.pid, fetch=True)
        self.assertEqual(self.head(), mine)
        self.assertTrue(any("por delante" in l for l in lines), lines)

    def test_same_warning_is_said_once_per_origin_tip(self):
        with open(os.path.join(self.repo, "VERSION"), "w") as fh:
            fh.write("9.9.9\n")
        self.assertTrue(publica.al_dia(self.pid, fetch=True))
        self.assertEqual(publica.al_dia(self.pid, fetch=True), [])

    def test_up_to_date_says_nothing(self):
        git(self.repo, "pull", "-q", "--ff-only")
        self.assertEqual(publica.al_dia(self.pid, fetch=True), [])

    def test_no_lock_is_a_no_op(self):
        os.remove(os.path.join(lookout_state.project_dir(self.pid), "lock.json"))
        self.assertEqual(publica.al_dia(self.pid, fetch=True), [])
        self.assertEqual(self.head(), self.head0)


class AlDiaCallersTest(CheckoutCase):
    def test_concilia_brings_it_up_to_date_after_a_publication(self):
        led = publica.load(self.pid)
        led["cola"].append({"session_id": "s-z", "nombre": "z", "estado": "lista", "head": self.tip,
                            "rama_remota": "main", "worktree": self.repo, "pedida": time.time()})
        publica.save(self.pid, led)
        out = publica.concilia(self.pid, remote_tip=lambda wt, br: self.tip)
        self.assertEqual(self.head(), self.tip)
        self.assertTrue(any("al día" in l for l in out), out)

    def test_digest_keeps_the_whole_warning_with_its_command(self):
        with open(os.path.join(self.repo, "VERSION"), "w") as fh:
            fh.write("9.9.9\n")
        led = publica.load(self.pid)
        led["cola"].append({"session_id": "s-z", "nombre": "z", "estado": "lista", "head": self.tip,
                            "rama_remota": "main", "worktree": self.repo, "pedida": time.time()})
        publica.save(self.pid, led)
        old = publica.remote_tip
        publica.remote_tip = lambda wt, br: self.tip
        try:
            out = digest.render(self.pid, mark=True)
        finally:
            publica.remote_tip = old
        linea = next(l for l in out.splitlines() if l.startswith("Checkout principal"))
        self.assertIn("pull --ff-only`", linea)

    def test_digest_brings_it_up_to_date_from_the_local_ref(self):
        git(self.repo, "fetch", "-q", "origin")
        out = digest.render(self.pid, mark=True)
        self.assertEqual(self.head(), self.tip)
        self.assertIn("al día", out)

    def test_fusiona_brings_it_up_to_date(self):
        src = open(os.path.join(f3.ROOT if hasattr(f3, "ROOT") else os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "plugins", "lookout", "bin", "publica.py"), encoding="utf-8").read()
        cuerpo = src.split("def fusiona(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("al_dia(", cuerpo)


class CierraPreguntaTest(f3.Base):
    def setUp(self):
        super().setUp()
        self.old_rtp = retiro.deliver.transcript_path
        projects = self.projects
        retiro.deliver.transcript_path = lambda sid, pd=None: self.old_rtp(sid, pd or projects)

    def tearDown(self):
        retiro.deliver.transcript_path = self.old_rtp
        super().tearDown()

    def turno(self, sid, text):
        e = self.agent(sid, nombre=sid)
        self.transcript(sid, [{"type": "user", "message": {"content": "haz tu tarea"}, "timestamp": "2026-10-22T10:00:00Z"},
                              dict(f3.a_text(text), timestamp="2026-10-22T10:01:00Z")])
        return retiro.guarda_mensaje(self.pid, e)

    def test_goalspec_close_labels_are_not_a_question(self):
        self.assertEqual(self.turno("s1", "**Dónde quedamos:** listo.\n\n**¿Cerrado?** Sí."), "")
        self.assertEqual(self.turno("s2", "**Where we are:** done.\n\n**Closed?** Yes."), "")
        self.assertEqual(self.turno("s3", "Cerrado? sí\n¿Cerrado? Sí, mi parte está hecha."), "")

    def test_a_close_label_inside_a_fence_is_code(self):
        self.assertIn("pregunta algo", self.turno("s7", "**¿Cerrado?** Sí.\n```text\ncerrado? foo\n```"))

    def test_indented_and_tilde_fences_are_code_too(self):
        self.assertIn("pregunta algo", self.turno("s8", "Listo.\n ```text\n cerrado? foo\n ```"))
        self.assertIn("pregunta algo", self.turno("s9", "Listo.\n~~~text\ncerrado? foo\n~~~"))
        self.assertEqual(self.turno("s10", "~~~\nx\n~~~\n**¿Cerrado?** Sí."), "")

    def test_a_question_inside_code_still_counts(self):
        self.assertIn("pregunta algo", self.turno("s4", "**¿Cerrado?** Sí.\n\nCorrí `grep -E 'a?b' x`."))

    def test_a_real_question_still_waits(self):
        self.assertIn("pregunta algo", self.turno("s5", "**¿Cerrado?** Sí.\n\n¿La fusiono yo o me lo pides?"))
        self.assertIn("pregunta algo", self.turno("s6", "Terminé. Should I push now?"))


class EsperaQuietoTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("LOOKOUT_STATE_DIR")
        os.environ["LOOKOUT_STATE_DIR"] = self.tmp.name

    def tearDown(self):
        if self.old is None:
            os.environ.pop("LOOKOUT_STATE_DIR", None)
        else:
            os.environ["LOOKOUT_STATE_DIR"] = self.old
        self.tmp.cleanup()

    def test_waits_until_quiet(self):
        estados = iter(["working", "working", "idle"])
        live, esperado, estado = deliver.espera_quieto("p", {"session_id": "s", "pane_id": "w:1"}, 5, intervalo=0.01,
                                                       agent_get=lambda pane: {"agent_status": next(estados)})
        self.assertEqual((live["agent_status"], estado), ("idle", "idle"))
        self.assertRaises(StopIteration, next, estados)  # it asked three times

    def test_bounded_when_never_quiet(self):
        t0 = time.time()
        live, esperado, estado = deliver.espera_quieto("p", {"session_id": "s", "pane_id": "w:1"}, 0.2, intervalo=0.01,
                                                       agent_get=lambda pane: {"agent_status": "working"})
        self.assertEqual((live, estado), (None, "working"))
        self.assertLess(time.time() - t0, 2)

    def test_quiet_at_once_does_not_wait(self):
        live, esperado, _e = deliver.espera_quieto("p", {"session_id": "s", "pane_id": "w:1"}, 5, intervalo=1,
                                                   agent_get=lambda pane: {"agent_status": "idle"})
        self.assertEqual((live["agent_status"], esperado), ("idle", 0))

    def test_a_dialog_or_a_missing_pane_is_not_waited_for(self):
        for st in ({"agent_status": "blocked"}, None):
            t0 = time.time()
            live, _s, estado = deliver.espera_quieto("p", {"session_id": "s", "pane_id": "w:1"}, 5, intervalo=1,
                                                     agent_get=lambda pane: st)
            self.assertIsNone(live)
            self.assertLess(time.time() - t0, 0.5)
            self.assertIn("no espero", deliver.no_quieto({"nombre": "x"}, 0, estado))

    def test_cli_commands_wait_before_refusing(self):
        loader = importlib.machinery.SourceFileLoader("lookout_cli_01350", os.path.join(f3.BIN, "lookout"))
        cli = importlib.util.module_from_spec(importlib.util.spec_from_loader("lookout_cli_01350", loader))
        loader.exec_module(cli)
        import inspect
        for fn in ("cmd_entrega", "cmd_envia", "cmd_relevo", "cmd_recarga"):
            self.assertIn("quieto_o_espera(", inspect.getsource(getattr(cli, fn)), fn)
        estados = iter(["working", "working", "idle"])
        old_get, old_int = cli.deliver.herdr_cli.agent_get, cli.deliver.espera_quieto.__defaults__
        cli.deliver.herdr_cli.agent_get = lambda pane: {"agent_status": next(estados)}
        cli.deliver.espera_quieto.__defaults__ = (0.01, None)
        try:
            a = type("A", (), {"espera": 5.0})()
            self.assertEqual(cli.quieto_o_espera("p", {"session_id": "s", "pane_id": "w:1", "nombre": "x"}, a), "")
            cli.deliver.herdr_cli.agent_get = lambda pane: {"agent_status": "working"}
            a.espera = 0.05
            no = cli.quieto_o_espera("p", {"session_id": "s", "pane_id": "w:1", "nombre": "x"}, a)
            self.assertIn("No lo repitas en bucle", no)
            cli.deliver.herdr_cli.agent_get = lambda pane: {"agent_status": "blocked"}
            a.espera = 5.0
            t0 = time.time()
            self.assertEqual(cli.quieto_o_espera("p", {"session_id": "s", "pane_id": "w:1", "nombre": "x"}, a), "")
            self.assertLess(time.time() - t0, 0.5)  # left to the command, which says «está blocked»
            # envia: a refusal that is not about the turn (a draft) is printed as it came, with no wait
            llamadas = []
            borrador = (4, "NO ENTREGADO: la caja de entrada de x tiene un borrador ('hola'). No escribo encima; avisa al usuario.")
            old_dl, old_find, old_load = cli.deliver.deliver, cli.registry.find, cli.registry.load
            cli.deliver.deliver = lambda *x, **k: llamadas.append(1) or borrador
            cli.registry.find = lambda reg, n: {"session_id": "s", "pane_id": "w:1", "nombre": "x"}
            cli.registry.load = lambda pid: {}
            cli.deliver.herdr_cli.agent_get = lambda pane: {"agent_status": "working"}
            old_project = cli.project
            cli.project = lambda p: ("p", None)
            try:
                b = type("B", (), {"proyecto": "p", "agente": "x", "tarea": False, "usuario_confirmo": "", "texto": "hola",
                                   "clave": "k1", "confirmar": 1, "espera": 5.0})()
                import io
                import contextlib
                buf = io.StringIO()
                t0 = time.time()
                with contextlib.redirect_stdout(buf):
                    self.assertEqual(cli.cmd_envia(b), 4)
                self.assertLess(time.time() - t0, 0.5)
                self.assertIn("borrador", buf.getvalue())
                self.assertEqual(len(llamadas), 1)
            finally:
                cli.deliver.deliver, cli.registry.find, cli.registry.load = old_dl, old_find, old_load
                cli.project = old_project
        finally:
            cli.deliver.herdr_cli.agent_get = old_get
            cli.deliver.espera_quieto.__defaults__ = old_int


class IdleSinTareaTest(f3.Base):
    def setUp(self):
        super().setUp()
        lookout_state.write_json(os.path.join(lookout_state.project_dir(self.pid), "lock.json"), {
            "project_id": self.pid, "common_dir": "/nonexistent/.git", "roots": [],
            "supervisor": {"session_id": "s-sup", "pid": os.getpid()}})

    def idle(self, hace, tarea=""):
        self.agent("s-i", nombre="parado", tarea=tarea)
        lookout_state.append_event(self.pid, {"session_id": "s-i", "event": "idle", "ts": time.time() - hace})

    def test_idle_without_task_for_long_shows_what_to_do(self):
        self.idle(40 * 60)
        out = digest.render(self.pid, mark=False)
        self.assertIn("parado sin tarea", out)

    def test_it_repeats_on_an_unchanged_waiter_wake(self):
        self.idle(40 * 60)
        digest.render(self.pid, mark=True, por_waiter=True)
        out = digest.render(self.pid, mark=True, por_waiter=True)
        self.assertIn("parado sin tarea", out)

    def test_recent_idle_or_a_task_says_nothing(self):
        self.idle(60)
        self.assertNotIn("parado sin tarea", digest.render(self.pid, mark=False))


class PublicaSalidaTest(f3.GitCase):
    def test_no_line_leads_when_a_later_check_refuses(self):
        e = self.worktree("rutas", "s-r", extra="/Users/alguien/secreto")
        ok, code, lines = self.ask(e)
        self.assertFalse(ok)
        self.assertEqual(code, "RUTAS-PRIVADAS")
        self.assertTrue(lines[0].startswith("NO:"), lines)
        self.assertFalse(any(l.startswith("Adversario: OK") for l in lines[:2]), lines)

    def test_generic_paths_are_not_private(self):
        for s in ("`~/.claude/sessions/<pid>.json`", "o `/tmp/...`", "(`/tmp/…`, `/d/a/…`)",
                  "`python3 x.py /c/Users" + "/.../sessions/x.md`", "/home/…/y"):  # split: tools/exporta-publico.sh
            self.assertIsNone(publica.PRIVATE_RE.search(s), s)
        for s in ("/Users/alguien/x", "/home" + "/ana/y", "/Users" + "/.hidden/x", "/tmp/claude-501/z", "/tmp/.3t-revision-cierre.md", "/tmp/x.log",
                  "~/Projects/claude-vzert", "~/notas.md", "/private/tmp/q", "/var/folders/ab/c"):
            self.assertIsNotNone(publica.PRIVATE_RE.search(s), s)


class SkillCheckpointTest(unittest.TestCase):
    def test_skill_says_not_to_add_sin_push_to_a_checkpoint(self):
        path = os.path.join(os.path.dirname(f3.BIN), "skills", "supervisa", "SKILL.md")
        text = open(path, encoding="utf-8").read()
        sec = text.split("**Las decisiones van antes del `/checkpoint-3t`", 1)[1][:1500]
        self.assertIn("sin push", sec)
        self.assertIn("nunca hace push", sec)


if __name__ == "__main__":
    unittest.main()

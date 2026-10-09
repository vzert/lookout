"""Fase 9 G tests (0.11.0): every agent of /lookout:pendientes runs in its own herdr tab on the main checkout; a
worktree only when the user asks for one (decision of 2026-10-08, after measuring claude-vzert: the first batch's 3
agents ran in worktrees and left 3 `-wt-` folders and 3 `lookout/*` branches holding only a report; the repo has no
code of its own, 685 of its 708 files are memory/).

G1: a code task gets the main checkout, not a worktree; a read-only task stays read-only.
G2: the code task on the main checkout edits without commit and lists its files; nothing that moves the shared tree.
G3: `lookout pendientes --worktree <id>` (the user's word) gives that item a worktree; `--en-main` takes it back.
G4: two code agents on the same checkout get two ports; `libera` returns the port by the agent's own key.
G5: the launch opens a workspace on the main checkout with edit tools on; a relief keeps read-only only for read-only.
Each test fails on 0.10.0 (a91877b) and passes here, except three guards 0.10.0 already met:
test_a_relieved_read_only_agent_stays_read_only, test_reads_and_the_checkpoint_commit_pass and
test_only_agents_lookout_launched_on_main.
Run: python3 -m unittest tests/test_lookout_g.py
"""
import importlib.machinery
import importlib.util
import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "plugins", "lookout", "bin")
sys.path.insert(0, BIN)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lote  # noqa: E402
import pendientes  # noqa: E402
import ports  # noqa: E402
import registry  # noqa: E402
import heuristicas  # noqa: E402
import lookout_state  # noqa: E402
import relevo  # noqa: E402
import time  # noqa: E402
from test_lookout_f2 import StubCase  # noqa: E402
from test_lookout_f6 import F6Case, PID as PID6  # noqa: E402


def items_md(tmp, *textos):
    path = os.path.join(tmp, "_pendientes.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# Pendientes\n\n## Alta prioridad\n\n")
        for n, t in enumerate(textos):
            fh.write("- [ ] %s — _creado: 2026-10-08_ — _id: p-%010d_\n" % (t, n))
    return pendientes.parse(path)


class EnMainTest(StubCase):
    def test_a_code_task_runs_on_the_main_checkout_by_default(self):
        it = items_md(self.tmp.name, "Arreglar `src/a.py`")[0]
        self.assertEqual(it["tipo"], "codigo")
        plan = lote.plan_for(it, self.tmp.name, "origin/main")
        self.assertEqual(plan["worktree"], self.tmp.name)
        self.assertTrue(plan["sin_worktree"])
        self.assertFalse(plan.get("solo_lectura"))
        self.assertNotIn("-wt-", plan["worktree"])

    def test_a_read_only_task_stays_read_only(self):
        it = items_md(self.tmp.name, "**Medir** la latencia del recall")[0]
        plan = lote.plan_for(it, self.tmp.name, "origin/main", con_worktree=True)  # a worktree never makes it writable
        self.assertTrue(plan["sin_worktree"])
        self.assertTrue(plan["solo_lectura"])
        self.assertIn("modo lectura", lote.render_tarea(self.pid, it, plan, [it]))

    def test_the_code_task_on_main_edits_without_commit_and_lists_its_files(self):
        it = items_md(self.tmp.name, "Arreglar `src/a.py`")[0]
        text = lote.render_tarea(self.pid, it, lote.plan_for(it, self.tmp.name, "origin/main"), [it])
        alcance = text.split("## Alcance / no tocar", 1)[1].split("\n## ", 1)[0]
        criterios = text.split("## Criterios de aceptación", 1)[1].split("\n## ", 1)[0]
        restricciones = text.split("## Restricciones", 1)[1].split("\n## ", 1)[0]
        self.assertIn("checkout principal `%s`" % self.tmp.name, alcance)
        for verbo in ("`git stash`", "`checkout`", "`commit`", "`clean`"):
            self.assertIn(verbo, alcance)
        self.assertIn("sin commit", criterios)
        # the user's decision (2026-10-08): the one commit allowed on main is /checkpoint-3t's, by its own paths
        self.assertIn("La única excepción es `/checkpoint-3t`", alcance)
        self.assertIn("`git commit --only`", alcance)
        self.assertIn("lista cada archivo", criterios)
        self.assertNotIn("commit de tu rama", text)
        self.assertNotIn("modo lectura", text)
        self.assertNotIn("Quédate en tu worktree", restricciones)
        self.assertIn("Quédate en el checkout principal y en tu pestaña", restricciones)
        self.assertNotIn("rebase sobre la base", text)  # the worktree-only publish rule would contradict the scope

    def test_the_proposal_says_tab_on_the_main_checkout(self):
        items = items_md(self.tmp.name, "Arreglar `src/a.py`")
        os.makedirs(lote.tareas_dir(self.pid), exist_ok=True)
        for it in items:
            it["plan"] = lote.plan_for(it, self.tmp.name, "origin/main")
            it["prompt"] = lote.draft_path(self.pid, it["id"])
            with open(it["prompt"], "w", encoding="utf-8") as fh:
                fh.write(lote.render_tarea(self.pid, it, it["plan"], items))
        prop = {"archivo": "x", "total": 1, "tope": 3, "libres": 3, "activos": [], "lote": items, "cola": [],
                "excluidos": []}
        linea = [l for l in lote.render_propuesta(prop).splitlines() if "agente " in l][0]
        self.assertIn("pestaña en el checkout principal", linea)
        self.assertNotIn("worktree ", linea)


class DraftStaleTest(StubCase):
    def test_a_kept_draft_of_another_mode_or_port_is_rewritten(self):
        os.environ["LOOKOUT_PORT_BASE"] = "47800"
        try:
            it = items_md(self.tmp.name, "Arreglar `src/a.py`")[0]
            plan = lote.plan_for(it, self.tmp.name, "origin/main")
            path = os.path.join(self.tmp.name, "d.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(lote.render_tarea(self.pid, it, plan, [it]))
            self.assertFalse(lote.draft_stale(path, plan))
            # same id, now read-only (its text was retyped): the code-on-main draft would tell it to edit
            self.assertTrue(lote.draft_stale(path, dict(plan, solo_lectura=True)))
            # its port was freed (libera --fallida) and the next launch may get another one
            ports.libera(lote.clave_puerto(plan))
            ports.asigna("/r/otro")  # takes the freed port
            self.assertTrue(lote.draft_stale(path, plan))
        finally:
            os.environ.pop("LOOKOUT_PORT_BASE", None)

    def test_the_mode_cannot_come_from_the_pendientes_own_words(self):
        it = items_md(self.tmp.name, "Arreglar el modo lectura de `src/a.py`")[0]
        self.assertEqual(it["tipo"], "codigo")
        plan = lote.plan_for(it, self.tmp.name, "origin/main")
        path = os.path.join(self.tmp.name, "d.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(lote.render_tarea(self.pid, it, plan, [it]))
        self.assertTrue(lote.draft_stale(path, dict(plan, solo_lectura=True)))

    def test_a_refined_draft_without_a_free_port_is_kept(self):
        os.environ["LOOKOUT_PORT_SPAN"] = "0"
        try:
            it = items_md(self.tmp.name, "Arreglar `src/a.py`")[0]
            plan = lote.plan_for(it, self.tmp.name, "origin/main")
            text = lote.render_tarea(self.pid, it, plan, [it])
            self.assertIn("No quedó un puerto libre para ti", text)
            path = os.path.join(self.tmp.name, "d.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text.replace("## Criterios de aceptación (verificables)\n",
                                      "## Criterios de aceptación (verificables)\n- Afinado por el supervisor.\n"))
            self.assertFalse(lote.draft_stale(path, plan))
            os.environ["LOOKOUT_PORT_SPAN"] = "400"
            self.assertTrue(lote.draft_stale(path, plan))  # a port is free now: the agent will get it, so rewrite
        finally:
            os.environ.pop("LOOKOUT_PORT_SPAN", None)

    def test_the_port_cannot_come_from_the_pendientes_own_words(self):
        os.environ["LOOKOUT_PORT_BASE"] = "48100"
        try:
            it = items_md(self.tmp.name, "Cambiar el texto «No quedó un puerto libre para ti» en `src/b.py`")[0]
            plan = lote.plan_for(it, self.tmp.name, "origin/main")
            path = os.path.join(self.tmp.name, "d.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(lote.render_tarea(self.pid, it, plan, [it]))
            antes = ports.libera(lote.clave_puerto(plan))
            ports.asigna("/r/otro")  # another agent takes it
            self.assertTrue(lote.draft_stale(path, plan))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(lote.render_tarea(self.pid, it, dict(plan, puerto=None), [it]))
            self.assertNotIn("desarrollo: %d " % antes, open(path, encoding="utf-8").read())
        finally:
            os.environ.pop("LOOKOUT_PORT_BASE", None)


class PideWorktreeTest(StubCase):
    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(os.path.join(self.repo, "memory"))
        subprocess.run(["git", "init", "-q", "-b", "main", self.repo], check=True)
        items_md(os.path.join(self.repo, "memory"), "Arreglar `src/a.py`", "Arreglar `src/b.py`")
        loader = importlib.machinery.SourceFileLoader("lookout_cli_g", os.path.join(BIN, "lookout"))
        spec = importlib.util.spec_from_loader("lookout_cli_g", loader)
        self.cli = importlib.util.module_from_spec(spec)
        loader.exec_module(self.cli)
        self.stub(agent_list=[])

    def run_cli(self, *args):
        out = io.StringIO()
        old = sys.argv
        sys.argv = ["lookout"] + list(args)
        try:
            with redirect_stdout(out):
                try:
                    rc = self.cli.main()
                except SystemExit as e:
                    rc = e.code
        finally:
            sys.argv = old
        return rc, out.getvalue()

    def test_a_worktree_only_for_the_item_the_user_asked(self):
        rc, out = self.run_cli("pendientes", self.repo, "--worktree", "p-0000000001")
        self.assertIn(rc, (0, None), out)
        lineas = [l for l in out.splitlines() if "agente " in l]
        self.assertEqual(len(lineas), 2, out)
        self.assertIn("pestaña en el checkout principal", lineas[0])
        self.assertIn("-wt-", lineas[1])
        self.assertIn("lo pidió el usuario", lineas[1])
        rc, out = self.run_cli("pendientes", self.repo, "--en-main", "p-0000000001")
        self.assertNotIn("-wt-", out)


class CliEnMainTest(PideWorktreeTest):
    """The CLI paths, not the helpers (adversary 2026-10-08: mutating them back to 0.10.0 left the suite green)."""

    def registra(self, **extra):
        pid, _ = self.cli.project(self.repo)
        e = {"session_id": "s-main", "nombre": "arreglar-a", "pane_id": "w1:p1", "worktree": self.repo, "cwd": self.repo,
             "branch": "main", "tarea": "p-0000000000", "tarea_estado": "trabajando", "sin_worktree": True,
             "solo_lectura": False, "clave_puerto": self.repo + "-tab-arreglar-a", "lanzado_por": "lookout"}
        e.update(extra)
        registry.save(pid, {"agents": {"s-main": e}})
        return pid, e

    def test_libera_returns_the_port_of_a_code_agent_on_main(self):
        os.environ["LOOKOUT_PORT_BASE"] = "47400"
        try:
            pid, e = self.registra()
            port = ports.asigna(e["clave_puerto"])
            self.assertTrue(port)
            rc, out = self.run_cli("libera", self.repo, "arreglar-a", "--fuera", "ninguno")
            self.assertIn(rc, (0, None), out)
            self.assertIsNone(ports.de(e["clave_puerto"]))
        finally:
            os.environ.pop("LOOKOUT_PORT_BASE", None)

    def test_puerto_serves_a_code_agent_on_main_by_its_own_key(self):
        os.environ["LOOKOUT_PORT_BASE"] = "47500"
        try:
            pid, e = self.registra()
            rc, out = self.run_cli("puerto", self.repo, "arreglar-a")
            self.assertIn(rc, (0, None), out)
            self.assertTrue(ports.de(e["clave_puerto"]))
            self.assertIsNone(ports.de(self.repo))  # never the shared checkout's path
        finally:
            os.environ.pop("LOOKOUT_PORT_BASE", None)

    def test_two_discovered_sessions_on_main_get_two_ports(self):
        os.environ["LOOKOUT_PORT_BASE"] = "47600"
        try:
            pid, _ = self.cli.project(self.repo)
            base = {"worktree": self.repo, "cwd": self.repo, "branch": "main", "pane_id": "w1:p9"}
            registry.save(pid, {"agents": {s: dict(base, session_id=s, nombre=s) for s in ("user-a", "user-b")}})
            out = [self.run_cli("puerto", self.repo, s)[1] for s in ("user-a", "user-b")]
            pa = ports.de(self.repo + "-tab-user-a")
            pb = ports.de(self.repo + "-tab-user-b")
            self.assertTrue(pa and pb, out)
            self.assertNotEqual(pa, pb)
            self.assertIsNone(ports.de(self.repo))
            self.assertEqual(os.path.realpath(lote.puerto_de(registry.load(pid)["agents"]["user-a"])),
                             os.path.realpath(self.repo + "-tab-user-a"))
        finally:
            os.environ.pop("LOOKOUT_PORT_BASE", None)

    def test_the_old_shared_port_is_freed_once_nobody_holds_it(self):
        os.environ["LOOKOUT_PORT_BASE"] = "47900"
        try:
            pid, _ = self.cli.project(self.repo)
            viejo = ports.asigna(self.repo)  # what 0.10.0 gave a session discovered on main
            base = {"worktree": self.repo, "cwd": self.repo, "branch": "main", "pane_id": "w1:p9"}
            registry.save(pid, {"agents": {s: dict(base, session_id=s, nombre=s) for s in ("user-a", "user-b")}})
            self.run_cli("puerto", self.repo, "user-a")
            self.assertEqual(ports.de(self.repo), viejo)  # user-b still on the shared key
            self.run_cli("puerto", self.repo, "user-b")
            self.assertIsNone(ports.de(self.repo))
        finally:
            os.environ.pop("LOOKOUT_PORT_BASE", None)

    def test_a_failed_code_agent_on_main_waits_for_the_users_word(self):
        pid, e = self.registra(tarea_estado="fallida")
        self.assertFalse(lote.retryable(e, set()))  # its half-done edits are in the shared tree
        rc, out = self.run_cli("pendientes", self.repo, "--reintenta", "p-0000000000")
        self.assertTrue(lote.retryable(registry.load(pid)["agents"]["s-main"], set()))
        leido = registry.load(pid)["agents"]["s-main"]
        leido["solo_lectura"] = True  # a read-only one never wrote: retried as before
        leido.pop("reintentar")
        self.assertTrue(lote.retryable(leido, set()))

    def test_libera_fallida_says_the_edits_stay_on_main(self):
        self.registra()
        rc, out = self.run_cli("libera", self.repo, "arreglar-a", "--fuera", "ninguno", "--fallida")
        self.assertIn("--reintenta p-0000000000", out)


class RelevoEnMainTest(StubCase):
    def relieve(self, **extra):
        src = os.path.join(self.tmp.name, "p-1.sistema.md")
        with open(src, "w") as fh:
            fh.write("# Encargo\n## Tu tarea: p-1\n")
        e = {"session_id": "old", "nombre": "ag", "pane_id": "w9:p1", "herdr_name": "ag", "prompt_sistema": src,
             "tarea": "p-1", "tarea_estado": "trabajando", "worktree": self.tmp.name, "cwd": self.tmp.name,
             "sin_worktree": True}
        e.update(extra)
        registry.save(self.pid, {"agents": {"old": e}})
        saved = (relevo.herdr_cli.agent_get, relevo.herdr_cli.run, relevo.deliver.read_box, relevo.deliver.wait_event,
                 relevo.lote.arranca, relevo.lote.unique_name)
        seen = []
        relevo.herdr_cli.agent_get = lambda pane: {"agent_session": {"value": "old"}, "agent_status": "idle"}
        relevo.herdr_cli.run = lambda *a, **k: (0, "", "")
        relevo.deliver.read_box = lambda pane: ("vacia", "")
        relevo.deliver.wait_event = lambda *a, **k: True
        relevo.lote.arranca = lambda *a, **k: (seen.append(a), (True, "ok"))[1]
        relevo.lote.unique_name = lambda n, agents=None: n + "-2"
        try:
            ok, msg = relevo._relevo(self.pid, registry.load(self.pid)["agents"]["old"], lambda n: "nota", "sigue",
                                     None, 1, 1, lambda m: None)
        finally:
            (relevo.herdr_cli.agent_get, relevo.herdr_cli.run, relevo.deliver.read_box, relevo.deliver.wait_event,
             relevo.lote.arranca, relevo.lote.unique_name) = saved
        self.assertTrue(ok, msg)
        return seen[0]

    def test_a_relieved_code_agent_on_main_keeps_its_edit_tools_and_port(self):
        args = self.relieve(solo_lectura=False, clave_puerto="/r/repo-tab-ag")
        self.assertFalse(args[7])  # lectura
        self.assertEqual(args[12], "/r/repo-tab-ag")  # puerto_de

    def test_a_relieved_read_only_agent_stays_read_only(self):
        self.assertTrue(self.relieve(solo_lectura=True)[7])
        self.assertTrue(self.relieve()[7])  # a 0.10.0 entry without solo_lectura


class AtascoEnMainTest(F6Case):
    def test_a_change_in_the_shared_tree_is_not_progress_of_an_agent_on_main(self):
        reg = registry.load(PID6)
        reg["agents"]["s1"]["sin_worktree"] = True
        registry.save(PID6, reg)
        lookout_state.append_event(PID6, {"session_id": "s1", "nombre": "e1", "event": "working", "claude_pid": 4242,
                                          "ts": time.time() - 1300})
        out = heuristicas.revisa(PID6, agents=[], proceso=lambda _pid: "detenido", reciente=lambda *_: True)
        self.assertEqual([e["event"] for e in out], ["sin_progreso"])


class FrenoArbolTest(StubCase):
    """An agent lookout launched on the main checkout cannot move the shared tree by git (user's decision, round 6)."""

    def handle(self, cmd, **entry):
        import permisos
        e = {"session_id": "s1", "nombre": "ag", "worktree": self.tmp.name, "sin_worktree": True,
             "solo_lectura": False, "lanzado_por": "lookout"}
        e.update(entry)
        registry.save(self.pid, {"agents": {"s1": e}})
        data = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd},
                "permission_mode": "auto", "session_id": "s1", "cwd": self.tmp.name}
        out = permisos.handle(data, {"project_id": self.pid, "nombre": "ag"}, rules={})
        return ((out or {}).get("hookSpecificOutput") or {}).get("permissionDecision")

    def test_git_that_moves_the_tree_is_denied_on_main(self):
        for cmd in ("git checkout main", "git -C . stash", "git commit -m x", "cd src && git reset --hard",
                    "/usr/bin/git switch otra", "git -c a=b rebase main", "git clean -fd", "git restore a.py",
                    "git commit --only -m x -- memory/a.md src/b.py", "git commit --only -- memory/../src/x",
                    # round 7: inside a subshell, $( ) or backticks; and the other writers of the shared index/refs
                    "(git checkout x)", "(cd sub && git stash)", "echo $(git stash)", 'echo "$(git reset --hard)"',
                    "echo `git stash`", "git branch -f main HEAD~3", "git branch nueva", "git update-ref refs/heads/main HEAD",
                    "git add -A", "git add src/a.py", "git rm a.py", "git mv a b", "git $X",
                    # round 8: $( ) and backticks inside the git's own command, brace expansion, a comment's apostrophe
                    'git -C "$(git rev-parse --show-toplevel)" checkout main', "git -C `pwd` reset --hard",
                    "git $(echo checkout) main", "git {checkout,} main", "# don't touch\n(cd sub && git stash)"):
            self.assertEqual(self.handle(cmd), "deny", cmd)

    def test_reads_and_the_checkpoint_commit_pass(self):
        for cmd in ("git status --short", "git diff -- src/a.py", "git log --oneline -3", "git stash list",
                    "git commit --only -m checkpoint -- memory/sessions/a.md memory/_pendientes.md",
                    'git add -- memory/a.md && git commit --only -m "checkpoint (fix) {x}" -- memory/a.md',
                    "git branch -a", "git branch --list 'f*'", "git status; npm run dev -- --port $PORT",
                    "git branch --contains HEAD", "git branch --merged main", "git branch -av",
                    'git branch --format "%(refname:short)"', "git log -S x  # it's a read"):
            self.assertIsNone(self.handle(cmd), cmd)

    def test_the_rail_table_of_rounds_7_to_9(self):
        # the whole table the adversaries built, read by the quote-aware scanner (one pass, no regex over the raw text)
        import permisos
        deny = ['git checkout main', 'git -C . stash', 'git commit -m x', 'cd src && git reset --hard', '/usr/bin/git switch otra',
                'git -c a=b rebase main', 'git clean -fd', 'git restore a.py', 'git commit --only -m x -- memory/a.md src/b.py',
                'git commit --only -- memory/../src/x', '(git checkout x)', '(cd sub && git stash)', 'echo $(git stash)',
                'echo "$(git reset --hard)"', 'echo `git stash`', 'git branch -f main HEAD~3', 'git branch nueva',
                'git update-ref refs/heads/main HEAD', 'git add -A', 'git add src/a.py', 'git rm a.py', 'git mv a b', 'git $X',
                'git -C "$(git rev-parse --show-toplevel)" checkout main', 'git -C `pwd` reset --hard', 'git $(echo checkout) main',
                'git {checkout,} main', "# don't touch\n(cd sub && git stash)", "# let's see\necho $(git checkout main)",
                'git log --grep "fix #12" --oneline && git -C "$(git rev-parse --show-toplevel)" checkout main',
                'echo "== #2 ==" && git -C "$(git rev-parse --show-toplevel)" switch main', 'echo "step #2"; git $(echo checkout) main',
                "echo 'a #b' && git -C `pwd` reset --hard", 'git update-index --assume-unchanged a', 'git sparse-checkout set src',
                'git apply --index p.diff', 'git symbolic-ref HEAD refs/heads/x', 'git commit --only -- memory/$X',
                'git add -- memory/$X', '{ git checkout x; }', 'git-checkout y', "echo it's; git checkout x", 'git -C `pwd`',
        # round 10
        'git bisect start HEAD HEAD~3', 'git bisect bad', 'git worktree add -b x ../wt HEAD', "git $'checkout' main",
        'git $"stash"']
        allow = ['git status --short', 'git diff -- src/a.py', 'git log --oneline -3', 'git stash list', 'git stash show -p',
                 'git commit --only -m checkpoint -- memory/sessions/a.md memory/_pendientes.md',
                 'git add -- memory/a.md && git commit --only -m "checkpoint (fix) {x}" -- memory/a.md', 'git branch -a',
                 "git branch --list 'f*'", 'git status; npm run dev -- --port $PORT', 'git diff $(git merge-base HEAD main)',
                 'git branch --contains HEAD', 'git branch --merged main', 'git branch -av', 'git branch --format "%(refname:short)"',
                 "git log -S x  # it's a read", 'git diff -- src/{a,b}.py', 'git show HEAD:src/{a,b}.py',
                 'git log --oneline -- docs/{plan,README}.md', "git log --pretty=format:'{%h,%an}' -5",
                 """git log --format='{"c":"%H","a":"%an"}' -3""", 'git log --format=%H', 'git show stash@{0}', 'git log @{u}..',
                 'ls {a,b}; git status', 'git status && echo $HOME', 'git log --oneline # see $foo', 'git apply --check p.diff',
                 'git log --grep "fix #12" --oneline', "echo '$(git checkout x)'", 'echo "\\$(git checkout x)"',
         'git bisect log', 'git worktree list']
        self.assertEqual([c for c in deny if not permisos.arbol_compartido(c)], [])
        self.assertEqual([c for c in allow if permisos.arbol_compartido(c)], [])

    def test_only_agents_lookout_launched_on_main(self):
        self.assertIsNone(self.handle("git checkout main", sin_worktree=False, worktree="/r/repo-wt-x"))
        self.assertIsNone(self.handle("git checkout main", lanzado_por=""))  # the user's own session


class PuertosTest(StubCase):
    def test_two_code_agents_on_main_get_two_ports_and_libera_returns_its_own(self):
        os.environ["LOOKOUT_PORT_BASE"] = "47300"
        try:
            a, b = items_md(self.tmp.name, "Arreglar `src/a.py`", "Arreglar `src/b.py`")
            pa = lote.plan_for(a, self.tmp.name, "origin/main")
            pb = lote.plan_for(b, self.tmp.name, "origin/main")
            ta = lote.render_tarea(self.pid, a, pa, [a, b])
            tb = lote.render_tarea(self.pid, b, pb, [a, b])
            self.assertTrue(pa.get("puerto") and pb.get("puerto"))
            self.assertNotEqual(pa["puerto"], pb["puerto"])
            self.assertIn("Puerto para tu servidor de desarrollo: %d" % pa["puerto"], ta)
            self.assertIn("Puerto para tu servidor de desarrollo: %d" % pb["puerto"], tb)
            entry = {"worktree": self.tmp.name, "sin_worktree": True, "clave_puerto": lote.clave_puerto(pa)}
            self.assertEqual(ports.libera(lote.puerto_de(entry)), pa["puerto"])
            self.assertEqual(ports.de(lote.clave_puerto(pb)), pb["puerto"])  # the other agent keeps its port
        finally:
            os.environ.pop("LOOKOUT_PORT_BASE", None)


class LanzaEnMainTest(StubCase):
    def test_the_launch_opens_a_workspace_on_main_with_edit_tools(self):
        repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(repo)
        it = items_md(self.tmp.name, "Arreglar `src/a.py`")[0]
        plan = lote.plan_for(it, repo, "origin/main")
        draft = os.path.join(self.tmp.name, "draft.md")
        with open(draft, "w") as fh:
            fh.write("tarea")
        self.stub(results={"workspace create": {"root_pane": {"pane_id": "w1P:p1", "tab_id": "w1P:t1"},
                                                "tab": {"tab_id": "w1P:t1", "label": "1"}}})
        seen = []
        old = lote.arranca
        lote.arranca = lambda *a, **k: (seen.append(a), (True, "ok"))[1]
        try:
            ok, msg = lote.lanza_uno(self.pid, os.path.join(repo, ".git"), it, plan, draft, None, False,
                                     lambda m: None, "nota")
        finally:
            lote.arranca = old
        self.assertTrue(ok, msg)
        verbos = [c[:2] for c in self.calls()]
        self.assertIn(["workspace", "create"], verbos)
        self.assertNotIn(["worktree", "create"], verbos)
        self.assertFalse(seen[0][7])  # lectura: the code agent keeps its edit tools
        e = next(iter(registry.load(self.pid)["agents"].values()))
        self.assertEqual((e["worktree"], e["sin_worktree"], e["solo_lectura"]), (repo, True, False))
        self.assertEqual(e["clave_puerto"], repo + "-tab-" + plan["nombre"])
        self.assertEqual(e["puerto"], ports.de(e["clave_puerto"]))  # its own port, not the shared checkout's
        self.assertIsNone(ports.de(repo))

    def test_publica_refuses_an_agent_on_main(self):
        import publica
        ok, code, lines = publica.pide(self.pid, {"session_id": "s", "nombre": "ag", "worktree": self.tmp.name,
                                                  "sin_worktree": True, "solo_lectura": False}, {})
        self.assertEqual((ok, code), (False, "EN-MAIN"))

    def test_a_relief_is_read_only_only_for_a_read_only_task(self):
        viejo = {"worktree": "/r/repo", "sin_worktree": True}  # a 0.10.0 entry: only read-only tasks had no worktree
        self.assertTrue(lote.solo_lectura(viejo))
        nuevo = {"worktree": "/r/repo", "sin_worktree": True, "solo_lectura": False, "clave_puerto": "/r/repo-tab-x"}
        self.assertFalse(lote.solo_lectura(nuevo))
        self.assertEqual(lote.puerto_de(nuevo), "/r/repo-tab-x")
        self.assertNotIn("--disallowedTools", lote.exec_args(None, lote.solo_lectura(nuevo)))


if __name__ == "__main__":
    unittest.main()

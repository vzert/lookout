"""0.13.6: an agent's marker keeps every address its supervisor had.
Run: python3 -m unittest tests/test_lookout_0136.py
"""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_0130 as t130  # noqa: E402
import test_lookout_f3 as f3  # noqa: E402
import test_lookout_f10 as f10  # noqa: E402

import lookout_state  # noqa: E402
import publica  # noqa: E402
import registry  # noqa: E402

PID = t130.PID


class DireccionesTest(t130.AltaTest):
    """3-tier-memory 2026-10-16: the supervisor moved from 2476.sock to 95700.sock; the agents' markers kept only the
    new address, and 3-tier's checkpoint-close-guard stopped counting the questions already sent to the old one."""

    def sup(self, n):
        return {"nombre": "supervisor-x", "address": "uds:/tmp/cc-socks/%s.sock" % n}

    def registra(self, n):
        registry.register(PID, self.sup(n), [{"session_id": "s1", "kind": "claude", "pane_id": "w1:p1",
                                              "cwd": self.repo}])
        return lookout_state.read_marker("s1")

    def test_a_new_supervisor_adds_its_address_and_keeps_the_old_ones(self):
        m = self.registra(2476)
        self.assertEqual(m["direcciones"], ["uds:/tmp/cc-socks/2476.sock"])
        m = self.registra(95700)
        self.assertEqual(m["address"], "uds:/tmp/cc-socks/95700.sock")   # still a string: 3-tier reads it as text
        self.assertEqual(m["direcciones"], ["uds:/tmp/cc-socks/2476.sock", "uds:/tmp/cc-socks/95700.sock"])
        m = self.registra(95700)
        self.assertEqual(len(m["direcciones"]), 2)                        # no duplicates
        m = self.registra(2476)                                           # back to an old one: it becomes the last
        self.assertEqual(m["direcciones"], ["uds:/tmp/cc-socks/95700.sock", "uds:/tmp/cc-socks/2476.sock"])

    def test_a_marker_written_before_0136_counts_its_address(self):
        lookout_state.write_json(lookout_state.marker_path("s1"), {"project_id": PID, "supervisor": "supervisor-x",
                                                                   "address": "uds:/tmp/cc-socks/2476.sock"})
        m = self.registra(95700)
        self.assertEqual(m["direcciones"], ["uds:/tmp/cc-socks/2476.sock", "uds:/tmp/cc-socks/95700.sock"])

    def test_no_empty_address_and_another_project_starts_over(self):
        registry.register(PID, {"nombre": "supervisor-x", "address": ""},
                          [{"session_id": "s1", "kind": "claude", "pane_id": "w1:p1", "cwd": self.repo}])
        self.assertEqual(lookout_state.read_marker("s1")["direcciones"], [])
        lookout_state.write_marker("s2", {"project_id": "otro", "address": "uds:/a.sock"})
        lookout_state.write_marker("s2", {"project_id": PID, "address": "uds:/b.sock"})
        self.assertEqual(lookout_state.read_marker("s2")["direcciones"], ["uds:/b.sock"])

    def test_a_malformed_address_or_list_never_reaches_the_marker(self):
        # adversary r1 (codex): a non-text address went through as given; a string list split into characters
        lookout_state.write_marker("s3", {"project_id": PID, "address": {"sock": 1}})
        self.assertEqual(lookout_state.read_marker("s3")["address"], "")
        lookout_state.write_json(lookout_state.marker_path("s3"), {"project_id": PID, "address": "uds:/a.sock",
                                                                   "direcciones": "abc"})
        lookout_state.write_marker("s3", {"project_id": PID, "address": "uds:/b.sock", "direcciones": "xyz"})
        self.assertEqual(lookout_state.read_marker("s3")["direcciones"], ["uds:/a.sock", "uds:/b.sock"])

    def test_an_agent_relief_carries_the_list(self):
        # relevo.py copies the old session's marker to the new session id
        self.registra(2476)
        self.registra(95700)
        viejo = lookout_state.read_marker("s1")
        lookout_state.write_marker("s1-nueva", dict(viejo, nombre="x", display="x (lookout)"))
        self.assertEqual(lookout_state.read_marker("s1-nueva")["direcciones"], viejo["direcciones"])


class PublicaWorktreeTest(f3.GitCase):
    """3-tier-memory 2026-10-16: agents launched on the main checkout work in a worktree of their own (`cd` in their
    Bash); herdr and the registry see only the main checkout, and `publica` answered BASE-MOVIDA for branches that did
    contain origin/main (aviso-sin-git 8138785, plan-poda-guardian 1c6de25)."""

    def setUp(self):
        super().setUp()
        self.common = os.path.join(self.repo, ".git")
        # origin moves on; the main checkout is never fetched (it sits on another branch in the real case)
        otro = os.path.join(self.tmp.name, "otro")
        subprocess.run(["git", "clone", "-q", self.origin, otro], check=True)
        with open(os.path.join(otro, "x.txt"), "w") as fh:
            fh.write("x\n")
        f3.git(otro, "add", "-A")
        f3.git(otro, "-c", "user.name=o", "-c", "user.email=o@o", "commit", "-qm", "otro")
        f3.git(otro, "push", "-q", "origin", "HEAD:main")
        # the agent's own worktree, built on the current origin/main
        self.wt = self.repo + "-wt-propio"
        f3.git(self.repo, "fetch", "-q", "origin")
        f3.git(self.repo, "worktree", "add", "-q", "-b", "propio", self.wt, "origin/main")
        f3.git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")   # main checkout stays stale
        with open(os.path.join(self.wt, "VERSION"), "w") as fh:
            fh.write("0.2.0\n")
        f3.git(self.wt, "commit", "-qam", "0.2.0")
        # registered the way the alta registers a hand-launched agent: herdr's cwd, the main checkout
        self.e = self.agent("sa", nombre="propio", tarea="p-propio", worktree=self.repo, cwd=self.repo,
                            branch="main", base="origin/main")
        self.transcript("sa", [f3.EXT, f3.a_text(f3.M_EXT + "\n" + f3.HOLD)])

    def cli(self, **kw):
        import argparse
        import io
        from contextlib import redirect_stdout
        cli = f10.load_cli("lookout_cli_0136")
        cli.project = lambda _p: (self.pid, self.common)
        real = f3.gobierno.estado
        self.addCleanup(setattr, f3.gobierno, "estado", real)
        f3.gobierno.estado = lambda pid, e, projects=None, **kw: real(pid, e, projects or self.projects, **kw)
        out = io.StringIO()
        args = dict(proyecto="/x", agente="propio", cola=False, hecho=False, retira=False, worktree="")
        args.update(kw)
        with redirect_stdout(out):
            rc = cli.cmd_publica(argparse.Namespace(**args))
        return rc, out.getvalue()

    def test_without_the_flag_the_main_checkout_is_checked_and_the_no_says_so(self):
        rc, out = self.cli()
        self.assertEqual(rc, 5)
        self.assertIn("BASE-MOVIDA", out)
        self.assertIn("--worktree <ruta>", out)

    def test_with_the_flag_its_own_worktree_is_checked_pushed_and_confirmed(self):
        rc, out = self.cli(worktree=self.wt)
        self.assertEqual(rc, 0, out)
        self.assertIn("LISTA", out)
        me = publica.load(self.pid)["cola"][0]
        self.assertEqual((me["worktree"], me["rama"]), (os.path.realpath(self.wt), "propio"))
        self.assertEqual(publica.caducada(self.pid, me), "")       # HEAD read in its worktree, not the main one
        f3.git(self.wt, "push", "-q", "origin", "HEAD:main")
        rc, out = self.cli(hecho=True)                              # no flag needed after the check
        self.assertEqual(rc, 0, out)
        self.assertIn("Publicada", out)

    def test_a_path_of_another_repository_or_none_is_refused(self):
        ajeno = os.path.join(self.tmp.name, "ajeno")
        subprocess.run(["git", "init", "-q", ajeno], check=True)
        for ruta in (ajeno, os.path.join(self.tmp.name, "no-existe")):
            rc, out = self.cli(worktree=ruta)
            self.assertEqual(rc, 5)
            self.assertIn("WORKTREE-AJENO", out)
        self.assertEqual(publica.load(self.pid)["cola"], [])


if __name__ == "__main__":
    unittest.main()

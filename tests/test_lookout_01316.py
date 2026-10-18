"""0.13.16: the question of a `--permiso` decision names the real destination of the agent's push, read by lookout.

Live case (banco 0.13.12, 2026-10-17): with a local test remote the supervisor wrote «a GitHub» and «no se puede
deshacer limpio» in its modal, and the user's yes rested on that text. Now the PermissionRequest hook keeps the
agent's cwd in the `blocked` event; `lookout decision --permiso` reads, in that repo, where a `git push` goes (the
remote and its push URL, as git resolves them) and prints it; the question must show each URL between «», and
`lookout aprueba` checks it again on the question the user answered. A push whose destination lookout cannot read
(a chained command, `git -c`, a remote that is not there) opens with that said, and no URL is asked for.
Run: python3 -m unittest tests/test_lookout_01316.py
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_01312 as t1312  # noqa: E402
import test_lookout_f3 as f3  # noqa: E402
import test_lookout_f4 as f4  # noqa: E402

import aprueba  # noqa: E402
import lookout_state  # noqa: E402
import permisos  # noqa: E402
import registry  # noqa: E402


def git(repo, *args):
    subprocess.run(["git", "-C", repo] + list(args), check=True, capture_output=True)


class Repo:
    """A real repo with remotes whose URLs are local paths that differ per test."""

    def __init__(self, base):
        self.dir = os.path.join(base, "repo")
        os.makedirs(self.dir)
        git(self.dir, "init", "-q", "-b", "main")
        self.origin = os.path.join(base, "remoto-origin.git")
        self.otro = os.path.join(base, "remoto-otro.git")
        git(self.dir, "remote", "add", "origin", self.origin)
        git(self.dir, "remote", "add", "otro", self.otro)


class DestinoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.r = Repo(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def destino(self, cmd, cwd=None):
        return aprueba.destino(cmd, cwd or self.r.dir)

    def test_a_named_remote_is_its_push_url(self):
        d = self.destino("git push origin HEAD:refs/heads/x")
        self.assertEqual((d["remote"], d["urls"]), ("origin", [self.r.origin]))
        self.assertEqual(self.destino("git push -u otro main")["urls"], [self.r.otro])
        # options that take a value do not count as the repository
        self.assertEqual(self.destino("git push -o ci.skip --push-option x otro main")["urls"], [self.r.otro])
        self.assertEqual(self.destino("git push --repo otro")["urls"], [self.r.otro])
        self.assertEqual(self.destino("git push --repo=otro")["urls"], [self.r.otro])
        self.assertEqual(self.destino("git push --force-with-lease=main otro main")["urls"], [self.r.otro])

    def test_a_pushurl_wins_over_the_url(self):
        empuje = os.path.join(self.tmp.name, "empuje.git")
        git(self.r.dir, "remote", "set-url", "--push", "origin", empuje)
        self.assertEqual(self.destino("git push origin main")["urls"], [empuje])

    def test_without_a_remote_git_decides_it(self):
        self.assertEqual(self.destino("git push")["urls"], [self.r.origin])   # no config: origin
        git(self.r.dir, "config", "branch.main.remote", "otro")
        self.assertEqual(self.destino("git push")["urls"], [self.r.otro])
        git(self.r.dir, "config", "branch.main.remote", "origin")
        git(self.r.dir, "config", "remote.pushDefault", "otro")
        self.assertEqual(self.destino("git push -f")["urls"], [self.r.otro])
        git(self.r.dir, "config", "remote.pushDefault", "origin")
        git(self.r.dir, "config", "branch.main.pushRemote", "otro")
        self.assertEqual(self.destino("git push")["urls"], [self.r.otro])

    def test_git_dash_c_reads_that_repo(self):
        fuera = os.path.join(self.tmp.name, "fuera")
        os.makedirs(fuera)
        self.assertEqual(self.destino("git -C repo push otro main", cwd=self.tmp.name)["urls"], [self.r.otro])
        self.assertEqual(self.destino("git -C .. -C repo push", cwd=fuera)["urls"], [self.r.origin])

    def test_a_url_or_a_path_is_itself(self):
        self.assertEqual(self.destino("git push https://example.invalid/a/b.git main")["urls"],
                         ["https://example.invalid/a/b.git"])
        self.assertEqual(self.destino("git push ../remoto-otro.git main")["urls"], [self.r.otro])

    def test_what_lookout_cannot_read_is_said_never_guessed(self):
        for cmd in ("cd repo && git push origin main", "git push origin main; git push otro main",
                    "git -c remote.origin.pushurl=/tmp/x push origin main", "GIT_DIR=/x git push",
                    "git push $REMOTO main", "git push no-existe main", "git push 'origin", "git push --mirror --repo"):
            d = self.destino(cmd)
            self.assertIsNotNone(d, cmd)
            self.assertEqual(d["urls"], [], cmd)
            self.assertTrue(d["motivo"], cmd)
        git(self.r.dir, "config", "url./tmp/reescrito/.pushInsteadOf", "https://example.invalid/")
        self.assertEqual(self.destino("git push https://example.invalid/a.git main")["urls"], [])

    def test_a_rewrite_of_a_remote_url_is_applied(self):
        git(self.r.dir, "remote", "set-url", "otro", "https://example.invalid/otro.git")
        git(self.r.dir, "config", "url./tmp/reescrito/.pushInsteadOf", "https://example.invalid/")
        self.assertEqual(self.destino("git push otro main")["urls"], ["/tmp/reescrito/otro.git"])

    def test_not_a_push_has_no_destination(self):
        for cmd in ("git status", "ls -la", "git fetch origin", "git log --grep push"):
            self.assertIsNone(self.destino(cmd), cmd)

    def test_an_attached_option_value_is_not_the_next_word(self):
        # adversary r1 (sonnet): `-ofoo` is -o with its value attached; the next word is the repository
        self.assertEqual(self.destino("git push -ofoo otro main")["urls"], [self.r.otro])
        self.assertEqual(self.destino("git push -fo otro")["urls"], [self.r.origin])   # here otro is -o's value
        self.assertEqual(self.destino("git push -uofoo otro main")["urls"], [self.r.otro])

    def test_a_push_behind_another_program_says_it_is_not_read(self):
        # adversary r1 (sonnet): a wrapper gave no destination line at all, and no URL was asked for
        for cmd in ("timeout 30 git push origin main", "sudo git push origin", "bash -c 'git push otro'",
                    "/usr/bin/git push otro", "env git push otro", "echo git push origin"):
            d = self.destino(cmd)
            self.assertIsNotNone(d, cmd)
            self.assertEqual(d["urls"], [], cmd)
            self.assertTrue(d["motivo"], cmd)
        # the shell reads `git pu''sh` as `git push`, and so does lookout
        self.assertEqual(self.destino("git pu''sh otro main")["urls"], [self.r.otro])

    def test_a_detached_head_without_a_remote_is_not_read(self):
        # adversary r1 (codex): git does not push from a detached HEAD without a repository and a refspec
        git(self.r.dir, "commit", "-q", "--allow-empty", "-m", "x")
        git(self.r.dir, "checkout", "-q", "--detach")
        self.assertEqual(self.destino("git push")["urls"], [])
        self.assertEqual(self.destino("git push otro HEAD:refs/heads/x")["urls"], [self.r.otro])

    def test_credentials_in_a_url_are_never_shown(self):
        git(self.r.dir, "remote", "set-url", "otro", "https://usuario:secreto@example.invalid/otro.git")
        self.assertEqual(self.destino("git push otro main")["urls"], ["https://***@example.invalid/otro.git"])
        self.assertEqual(self.destino("git push https://tok@example.invalid/a.git main")["urls"],
                         ["https://***@example.invalid/a.git"])

    def test_no_cwd_no_destination_read(self):
        d = aprueba.destino("git push origin main", "")
        self.assertEqual(d["urls"], [])


class BlockedGuardaElCwdTest(f3.Base):
    def test_the_blocked_event_keeps_the_agents_cwd(self):
        lookout_state.write_marker("s1", {"project_id": self.pid, "nombre": "uno"})
        os.environ["LOOKOUT_PERMISOS"] = os.path.join(self.tmp.name, "no-existe.toml")
        try:
            permisos.handle({"hook_event_name": "PermissionRequest", "tool_name": "Bash", "session_id": "s1",
                             "tool_input": {"command": "git push"}, "permission_mode": "auto", "cwd": self.tmp.name},
                            {"project_id": self.pid, "nombre": "uno"})
        finally:
            os.environ.pop("LOOKOUT_PERMISOS", None)
        ev = [e for e in lookout_state.read_events(self.pid, 0)[0] if e.get("event") == "blocked"][-1]
        self.assertEqual(ev["cwd"], self.tmp.name)


class AbreConDestinoTest(t1312.ApruebaTest):
    def setUp(self):
        super().setUp()
        self.r = Repo(self.tmp.name)
        self.cmd = t1312.CORTO   # the captured dialog shows it: a push to origin

    def blocked(self, cmd=None, ts=None, sid="s1", cwd=None):
        ev = {"session_id": sid, "hook": "PermissionRequest", "event": "blocked", "tool_name": "Bash",
              "detalle": (cmd or self.cmd)[:200], "comando": cmd or self.cmd, "ts": ts or time.time(),
              "cwd": cwd if cwd is not None else self.r.dir}
        lookout_state.append_event(self.pid, ev)
        return ev

    def test_the_question_must_name_the_url(self):
        self.blocked()
        ok, msg = aprueba.abre(self.pid, self.entry(), "¿Apruebo a uno, una vez, su push a GitHub: «%s»?" % self.cmd,
                               "Sí")
        self.assertFalse(ok)
        self.assertIn("«%s»" % self.r.origin, msg)
        ok, it = aprueba.abre(self.pid, self.entry(), "¿Apruebo a uno, una vez: «%s» a «%s»?" % (self.cmd, self.r.origin),
                              "Sí")
        self.assertTrue(ok, it)
        self.assertEqual(it["permiso"]["destino"]["urls"], [self.r.origin])

    def test_no_other_destination_next_to_the_real_one(self):
        # adversary r2 (codex): the real URL plus an invented one passed
        self.blocked()
        for extra in ("«https://evil.invalid/x.git»", "«GitHub»", "a github.com/vzert/x", "a evil.example:repo",
                      "a www.evil.example/repo", "a git@github.com:vzert/x.git"):
            q = "¿Apruebo a uno, una vez: «%s» a «%s» %s?" % (self.cmd, self.r.origin, extra)
            self.assertFalse(aprueba.abre(self.pid, self.entry(), q, "Sí")[0], extra)
            self.assertFalse(aprueba.nombra_destino(q, aprueba.destino(self.cmd, self.r.dir), self.cmd), extra)

    def test_an_unread_destination_rejects_every_url_shape(self):
        # adversary r2 (codex): `evil.example:repo` and `www.evil.example/repo` passed the unread guard
        dest = aprueba.destino("git -c x.y=z push origin main", self.r.dir)
        cmd = "git -c x.y=z push origin main"
        for extra in ("evil.example:repo", "www.evil.example/repo", "github.com/vzert/x", "«a GitHub»"):
            q = "¿Apruebo «%s», «%s», a %s?" % (cmd, aprueba.DESCONOCIDO, extra)
            self.assertFalse(aprueba.nombra_destino(q, dest, cmd), extra)
        self.assertTrue(aprueba.nombra_destino("¿Apruebo «%s», «%s»? (d3)" % (cmd, aprueba.DESCONOCIDO), dest, cmd))

    def test_a_destination_lookout_cannot_read_asks_for_no_url(self):
        cmd = "git -c x.y=z push origin main"
        self.blocked(cmd)
        # adversary r1 (codex): an unread destination let the question name an invented one; now it must say so
        ok, msg = aprueba.abre(self.pid, self.entry(), "¿Apruebo a uno, una vez: «%s» a «https://inventado»?" % cmd, "Sí")
        self.assertFalse(ok)
        self.assertIn("«%s»" % aprueba.DESCONOCIDO, msg)
        q = "¿Apruebo a uno, una vez: «%s», «%s»?" % (cmd, aprueba.DESCONOCIDO)
        ok, it = aprueba.abre(self.pid, self.entry(), q, "Sí")
        self.assertTrue(ok, it)
        self.assertEqual(it["permiso"]["destino"]["urls"], [])
        self.assertTrue(it["permiso"]["destino"]["motivo"])
        # and aprueba checks it on the question the user answered
        t1312.modal(self.pid, it["id"], "Sí", "¿Apruebo a uno, una vez: «%s» a «https://inventado»?" % cmd)
        ok, msg = aprueba.aprueba(self.pid, self.entry(), it["id"])
        self.assertFalse(ok)
        self.assertEqual(self.keys(), [])

    def test_a_command_that_is_not_a_push_is_as_before(self):
        self.blocked("ls -la")
        ok, it = aprueba.abre(self.pid, self.entry(), "¿Apruebo a uno, una vez: «ls -la»?", "Sí")
        self.assertTrue(ok, it)
        self.assertIsNone(it["permiso"].get("destino"))

    def test_the_yes_counts_only_for_a_question_that_named_the_url(self):
        self.blocked()
        ok, it = aprueba.abre(self.pid, self.entry(), "¿Apruebo a uno, una vez: «%s» a «%s»?" % (self.cmd, self.r.origin),
                              "Sí")
        self.assertTrue(ok, it)
        # the modal asked without the URL: the hook wrote down that question
        t1312.modal(self.pid, it["id"], "Sí", "¿Apruebo a uno, una vez: «%s»?" % self.cmd)
        ok, msg = aprueba.aprueba(self.pid, self.entry(), it["id"])
        self.assertFalse(ok)
        self.assertIn("destino", msg)
        self.assertEqual(self.keys(), [])

    def test_with_the_url_in_the_answered_question_it_presses(self):
        self.blocked()
        q = "¿Apruebo a uno, una vez: «%s» a «%s»?" % (self.cmd, self.r.origin)
        ok, it = aprueba.abre(self.pid, self.entry(), q, "Sí")
        self.assertTrue(ok, it)
        t1312.modal(self.pid, it["id"], "Sí", q)
        ok, msg = aprueba.aprueba(self.pid, self.entry(), it["id"])
        self.assertTrue(ok, msg)
        self.assertEqual(self.keys(), [["1"]])


# the tests of 0.13.12 run in their own file, not again here with this setUp
for _n in dir(t1312.ApruebaTest):
    if _n.startswith("test_") and _n not in AbreConDestinoTest.__dict__:
        setattr(AbreConDestinoTest, _n, None)


class DecisionCliDestinoTest(f4.Base):
    def test_decision_permiso_prints_the_destination(self):
        # adversary r2 (codex): bin/lookout itself, run as a program
        self.agent("s1", "uno")
        r = Repo(self.tmp.name)
        cmd = "git push otro HEAD:refs/heads/x"
        lookout_state.append_event(f4.PID, {"session_id": "s1", "hook": "PermissionRequest", "event": "blocked",
                                            "tool_name": "Bash", "detalle": cmd, "comando": cmd, "ts": time.time(),
                                            "cwd": r.dir})
        args = ["decision", f4.PID, "--agentes", "uno", "--permiso", "--si-es", "Sí, una vez", "--abre"]
        p = self.run_lk(*args + ["¿Apruebo a uno su push a GitHub: «%s»?" % cmd])
        self.assertEqual(p.returncode, 5, p.stdout + p.stderr)
        self.assertIn("«%s»" % r.otro, p.stdout)
        p = self.run_lk(*args + ["¿Apruebo a uno su push a «%s»: «%s»?" % (r.otro, cmd)])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("remote «otro» → «%s»" % r.otro, p.stdout)


if __name__ == "__main__":
    unittest.main()

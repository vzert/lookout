"""The forced dialog of auto mode (permisos.reserved) is a tripwire that reads command text, not a boundary: no text
rule catches every way bash can build a command. So its acceptance criterion is finite (decided 2026-10-05, after five
adversary rounds that each found one more form):

  (a) never weaker than 0.7.1: every command 0.7.1 stopped, this version stops too. No exception: seven adversary
      rounds showed that every "variable that is only an argument" exception was a hole;
  (b) fewer dialogs on real reads (measured on a live project, not here).

This test checks (a) over generated families: reserved commands with prefixes, wrappers, ways of writing the program,
global options and nested substitutions, and deletes with paths, wrappers and find. The 0.7.1 code is frozen in
tests/fixtures/permisos_071.py.
Run: python3 -m unittest tests/test_lookout_diferencial.py
"""
import importlib.util
import itertools
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "plugins", "lookout", "bin")
sys.path.insert(0, BIN)

import permisos  # noqa: E402

_spec = importlib.util.spec_from_file_location("permisos_071", os.path.join(ROOT, "tests", "fixtures", "permisos_071.py"))
permisos_071 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(permisos_071)



def close(prefix):
    return ("'" if prefix in ("sh -c '", "ssh h '") else '"' if prefix == 'bash -c "' else "") + (
        "; done" if prefix.startswith("for ") else "")


def reserved_families():
    pre = ["", "sudo ", "env ", "nice ", "timeout 5 ", "{ ", "! ", "if ", "H=1 ", "H=$(true) ", "X=$(true); ",
           "cd x && ", "ls | ", "echo $(date) && ", "command ", "exec ", "time ", "xargs ", "sh -c '", 'bash -c "',
           "ssh h '", "for i in 1; do "]
    progs = {"git": ["git", "/usr/bin/git", "g''it", "gi\\t", '"git"', "git${IFS}"], "gh": ["gh", "'gh'", "/opt/bin/gh"],
             "npm": ["npm", "n''pm"],
             "dyn": ["$(printf git)", "`echo gh`", "${G}", "$( echo gh )", "$(echo $(echo git))"]}
    mids = {"git": ["", " -C $D", " -c core.x=1", " --git-dir=$X"], "gh": ["", " -R o/r", " -R $R", " --repo=o/r"],
            "npm": ["", " --prefix $P"], "dyn": ["", " -C $D", " -R o/r"]}
    subs = {"git": ["push", "merge", "$S", "$(printf push)", "p*sh", "pu''sh", "p\\ush", "${S}"],
            "gh": ["pr merge", "release create", "workflow run x", "repo delete r", "repo archive r", "api -X DELETE x",
                   "api --method=PUT x", "api x -f a=b", "api x --input f", "$S", "api -X $M x", "pr $A",
                   "pr $(printf merge)"],
            "npm": ["publish", "$S", "$(printf publish)"],
            "dyn": ["push", "merge", "$S", "api -X DELETE x", "pr merge", "publish", "repo delete r"]}
    arg = ["", " origin main", " $B", ' "$B"', " 1", " $N --yes"]
    for k in progs:
        for p, g, m, s, a in itertools.product(pre, progs[k], mids[k], subs[k], arg):
            yield p + g + m + " " + s + a + close(p)
    nest = ["$(printf git)", "$(echo $(true); printf git)", "$(true && printf git)", "$(false || printf gh)",
            "$(printf 'g'; printf 'it')", "`printf git`", "$(printf \\`echo git\\`)", "$(cat <<<git)", "$(echo git\n)",
            "$( (printf git) )", "git", "gh", "npm", "/usr/bin/git", "'git'"]
    optv = ["", " --namespace foo", " --config-env alias.x=ENV", " --workspace foo", " -C $D", " --git-dir $G",
            " -c x=$V", " --exec-path=/x", " --literal-pathspecs", " -R $R", " --hostname h", " --prefix $P", " -w foo"]
    tails = [" $C", " $C x", " $(printf push)", " `echo push`", " log $X", " pr view $N", " api $X", " run $S",
             " rebase $X \"$Y\" --root", " submodule $X $Y", " bisect $X $Y", " exec $S \"$Y\"", " api graphql $X"]
    ctx = ["", "if ", "{ ", "nice ", "x && ", "for i in $(true); do ", "H=$(true) ", "f() { ", "(", "\n"]
    for c, g, o, t in itertools.product(ctx, nest, optv, tails):
        yield c + g + o + t
    for p, g in itertools.product(["", "/usr/libexec/git-core/", "/Library/Developer/CommandLineTools/usr/libexec/git-core/"],
                                  ["git-push", "git.push", "git-merge", "git.merge", "npm-publish", "gh-pr-merge"]):
        for a in ("", " origin main", " $B"):
            yield p + g + a
    yield from ("for x in $(printf git); do $x push; done", "H=$(printf git); $H $P", "H=$(printf git) && $H push",
                "for n in $(printf git) $P; do :; done", "H=$(printf git)\n$H $P", "git \\\n $C", "gh \\\n pr $A",
                "npm\t$C")


def delete_families():
    pre = ["", "sudo ", "sudo -u root ", "env ", "nice -n 5 ", "timeout 5 ", "{ ", "! ", "if ", "H=1 ", "cd x && ",
           "ls | ", "command ", "exec ", "time ", "xargs ", "sh -c '", 'bash -c "', "find . -exec ", "find /etc -exec ",
           "printf x > /tmp/a.$$; ", "for i in 1; do "]
    dele = ["rm", "rmdir", "mv", "/bin/rm", "r''m", "\\rm", "$(printf rm)", "`echo rm`"]
    opt = ["", " -rf", " -f --", " -v"]
    path = ["/etc/x", "../fuera", "$HOME/x", "/tmp/a.$$", "/tmp/$X", "x/../../fuera", "{}", "/wt/../x", "~/x",
            '"/etc/x"', "'/etc/x'", "/etc/x\\ y", "a /etc/x", "/tmp/a.$$ /etc/x"]
    end = ["", " ;", " \\;", " +"]
    for p, d, o, pa, e in itertools.product(pre, dele, opt, path, end):
        yield p + d + o + " " + pa + e + close(p)


class NeverWeakerThan071Test(unittest.TestCase):
    def regressions(self, cases):
        out = []
        for c in cases:
            if permisos_071.reserved(c, "/wt", "/wt", {}) and not permisos.reserved(c, "/wt", "/wt", {}):
                out.append(c)
        return out

    def test_reserved_commands(self):
        bad = self.regressions(reserved_families())
        self.assertEqual(bad[:20], [], "%d commands 0.7.1 stopped and this version lets through" % len(bad))

    def test_deletes(self):
        bad = self.regressions(delete_families())
        self.assertEqual(bad[:20], [], "%d deletes 0.7.1 stopped and this version lets through" % len(bad))

    def test_variables_after_git_gh_npm_keep_the_dialog(self):
        # round 7: git status writes the index, cat-file --textconv runs filters, "$(…)" runs a command
        for c in ("gh pr view $N", "git status $X; $Y", 'git -C "$(touch>/tmp/m)" status', 'git -C "$D" config x y',
                  "git cat-file --textconv $X", "gh api $X", "git rebase $X --root", "npm exec $S"):
            self.assertTrue(permisos.reserved(c, "/wt", "/wt", {}), c)

if __name__ == "__main__":
    unittest.main()

# lookout 0.7.1 (ba865a4) permisos.py, frozen: the floor that tests/test_lookout_diferencial.py compares against.
# Do not edit. A newer version may stop a dialog only where that test says it may.
#!/usr/bin/env python3
"""Tool permissions of the executors (D6, docs/plan.md 3.12 and Fase 5). Runs behind hooks/guard.sh, synchronous.

Three hook events, one deterministic evaluator (never the supervisor's LLM, never the pane text):
  PermissionRequest  approve ONE call ("Yes" once: decision.behavior "allow", never updatedPermissions) when the
                     user activated the rules, the executor is in manual mode, it has a registered worktree and
                     tool_name + tool_input fit the rules. Anything else: no output (the dialog stays for the user),
                     a herdr notification and a `blocked` event for the supervisor.
  PreToolUse[Bash]   auto mode only: force the dialog ("ask") for what D6 reserves to the user (push, merge,
                     publish, deletes outside the worktree), so the classifier cannot approve it on its own.
                     Exception: a push that fits the temporary rule the user applied (`lookout regla-push`, H15).
  PermissionDenied   auto mode refused a call: a `negado` event + notification. Never `retry` (H4: no way around).

Why nothing is approved outside manual mode (Fase 5 spike, tests/spikes/evidencia/v6-auto/): in auto mode the SECOND
identical try of a call the classifier refused opens a dialog and fires PermissionRequest; a hook answering "allow"
there let a refused `--force` push through. Auto mode only shows dialogs the docs reserve to a person.
"""
import fnmatch
import glob
import json
import os
import re
import shlex
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import herdr_cli  # noqa: E402
import lookout_state  # noqa: E402
import publica  # noqa: E402
import registry  # noqa: E402

try:
    import tomllib
except ImportError:  # python < 3.11 (the hooks ran /usr/bin/python3 3.9.6 in the Fase 5 bench): mini_toml below
    tomllib = None

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(PLUGIN_ROOT, "rules", "permisos.toml")
FORBIDDEN_CHARS = re.compile(r"[;&|<>`$\n\r]")
SPLIT_OPS = re.compile(r"&&|\|\||[;&|\n]")
FILE_KEY = {"NotebookEdit": "notebook_path"}
GLOB_CHARS = re.compile(r"[*?\[]")
# [usuario] of the template, used when the rules lack it (template unreadable): the forced dialog fails closed.
DEFAULT_USUARIO = {"bash_empieza": ["git push", "git merge", "gh pr merge", "gh release", "gh workflow run", "npm publish"],
                   "borrar_fuera": ["rm", "rmdir", "mv"]}


# ---------- rules ----------

def user_rules_path():
    return os.environ.get("LOOKOUT_PERMISOS") or os.path.join(os.path.expanduser("~"), ".config", "lookout",
                                                              "permisos.toml")


def mini_toml(text):
    """The TOML subset the rules use: [section], key = true|false|"string"|[array of strings] (arrays may span lines),
    # comments. Anything else raises ValueError, so a file it cannot read approves nothing."""
    data, buf = {}, ""
    cur = data
    for raw in text.splitlines():
        line = buf + " " + _strip_comment(raw) if buf else _strip_comment(raw)
        s = line.strip()
        if not s:
            continue
        if buf == "" and s.startswith("[") and s.endswith("]") and "=" not in s:
            cur = data.setdefault(s[1:-1].strip(), {})
            continue
        if "=" not in s:
            raise ValueError("línea no entendida: %r" % raw)
        key, val = (x.strip() for x in s.split("=", 1))
        if val.startswith("[") and not val.endswith("]"):
            buf = line
            continue
        buf = ""
        cur[key] = _toml_value(val)
    if buf:
        raise ValueError("lista sin cerrar")
    return data


def _strip_comment(line):
    out, quoted = [], False
    for ch in line:
        if ch == '"':
            quoted = not quoted
        if ch == "#" and not quoted:
            break
        out.append(ch)
    return "".join(out)


def _toml_value(val):
    if val in ("true", "false"):
        return val == "true"
    if val.startswith('"') and val.endswith('"') and len(val) >= 2:
        return json.loads(val)
    if val.startswith("[") and val.endswith("]"):
        items = re.findall(r'"(?:[^"\\]|\\.)*"', val)
        if re.sub(r'"(?:[^"\\]|\\.)*"', "", val[1:-1]).replace(",", "").strip():
            raise ValueError("lista con algo que no es texto: %r" % val)
        return [json.loads(x) for x in items]
    raise ValueError("valor no entendido: %r" % val)


def _load_toml(path):
    if not os.path.isfile(path):
        return None
    try:
        if tomllib is not None:
            with open(path, "rb") as fh:
                return tomllib.load(fh)
        with open(path, encoding="utf-8") as fh:
            return mini_toml(fh.read())
    except (OSError, ValueError):
        return None


def load_rules():
    """Effective rules: the plugin template with the user's lists on top. `activo` comes ONLY from the user's file."""
    rules = _load_toml(TEMPLATE) or {}
    user = _load_toml(user_rules_path())
    activo = bool(user and user.get("activo") is True)
    for section, values in (user or {}).items():
        if isinstance(values, dict):
            rules.setdefault(section, {}).update(values)
    rules["activo"] = activo
    return rules


# ---------- paths ----------

def real(path, cwd):
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    return os.path.realpath(path)


def inside(path, root):
    return bool(root) and (path == root or path.startswith(root + os.sep))


def excluded(path, root, names):
    rel = os.path.relpath(path, root)
    lower = {n.lower() for n in names}  # macOS volumes are case-insensitive: .GIT/config is .git/config
    return any(part.lower() in lower for part in rel.split(os.sep))


def path_like(token):
    return token.startswith(("/", "~")) or ".." in token.split("/")


def worktree_of(session_id, marker):
    """Realpath of the agent's registered worktree, or '' (an investigation without worktree has none)."""
    entry = (registry.load(marker.get("project_id", "")).get("agents") or {}).get(session_id) or {}
    if entry.get("sin_worktree") or not entry.get("worktree"):
        return ""
    return os.path.realpath(entry["worktree"])


# ---------- approve (manual mode only) ----------

def _short_flag_hit(token, flag):
    return (len(flag) == 2 and flag[0] == "-" and flag[1] != "-" and token.startswith("-")
            and not token.startswith("--") and flag[1] in token[1:])


def _forbidden_word(token, words):
    for w in words:
        if token == w or token.startswith(w + "=") or (w.startswith("--") and token.startswith(w)) \
                or _short_flag_hit(token, w):
            return w
    return ""


def evaluate(tool, ti, worktree, cwd, rules):
    """(True, why) when the rules approve this single call; (False, why) otherwise."""
    if not worktree:
        return False, "sin worktree registrado"
    arch = rules.get("archivos") or {}
    if tool in (arch.get("herramientas") or []):
        raw = ti.get(FILE_KEY.get(tool, "file_path")) or ""
        if not raw:
            return False, "sin ruta"
        p = real(raw, cwd)
        if not inside(p, worktree):
            return False, "ruta fuera del worktree"
        if p == worktree or excluded(p, worktree, set(arch.get("excluir") or [])):
            return False, "ruta excluida (%s)" % os.path.relpath(p, worktree)
        return True, "archivo dentro del worktree"
    if tool == "Bash":
        cmd = (ti.get("command") or "").strip()
        if not cmd or FORBIDDEN_CHARS.search(cmd) or "$(" in cmd:
            return False, "no es un comando único y simple"
        try:
            toks = shlex.split(cmd)
        except ValueError:
            return False, "comando ilegible"
        bash = rules.get("bash") or {}
        prefix = next((c for c in bash.get("comandos") or [] if toks[:len(c.split())] == c.split()), "")
        if not prefix:
            return False, "comando sin regla"
        words = list(bash.get("palabras_prohibidas") or [])
        if prefix == "git commit" and "--no-verify" in words:
            words.append("-n")  # git commit's short form of --no-verify
        bad = next((w for w in (_forbidden_word(t, words) for t in toks) if w), "")
        if bad:
            return False, "palabra prohibida %s" % bad
        if not inside(os.path.realpath(cwd), worktree):
            return False, "directorio actual fuera del worktree"
        names = set(arch.get("excluir") or [])
        for t in toks[len(prefix.split()):]:
            # Every argument, not only the ones that look like paths: a symlink inside the worktree can point out of it.
            # An option's value (--opt=value) is checked too; a bare option is skipped.
            if t.startswith("-"):
                if "=" in t:
                    t = t.split("=", 1)[1]
                elif not t.startswith("--") and len(t) > 2 and re.search(r"[/~.]", t[2:]):
                    t = t[2:]  # an operand glued to a short option: -o/tmp/x, -t../dir
                else:
                    continue
                if not t:
                    continue
            if "{" in t and "}" in t:
                return False, "llaves del shell: %s" % t  # brace expansion could name any path
            paths = [real(t, cwd)]
            if GLOB_CHARS.search(t):  # the shell expands it: check every path it would name (dotfiles included)
                paths += [os.path.realpath(m) for m in glob.glob(os.path.join(cwd, os.path.expanduser(t)))]
            for p in paths:
                if not inside(p, worktree):
                    return False, "ruta fuera del worktree: %s" % t
                if p != worktree and excluded(p, worktree, names):
                    return False, "ruta excluida: %s" % t
        return True, "comando permitido: %s" % prefix
    return False, "herramienta sin regla"


# ---------- reserved to the user (forced dialog in auto mode) ----------

def _reserved_regex(entry):
    return re.compile(r"\b" + r"\b[^;&|\n]*\b".join(re.escape(w) for w in entry.split()) + r"\b")


def _strip_prefix(toks):
    while toks and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]) or toks[0] in ("sudo", "command", "env", "nohup",
                                                                                     "exec", "time")):
        toks = toks[1:]
    return toks


def _glob_subcommand(cmd):
    """True when a git/gh/npm subcommand (the first word after the tool and its global options) has a glob or a brace."""
    for part in SPLIT_OPS.split(cmd):
        toks = part.split()
        for i, t in enumerate(toks):
            if re.sub(r"[\"'\\]", "", os.path.basename(t)) not in ("git", "gh", "npm"):
                continue
            j = i + 1
            while j < len(toks) and toks[j].startswith("-"):
                j += 2 if toks[j] in ("-C", "-c", "--git-dir", "--work-tree", "-R", "--repo") else 1
            if j < len(toks) and re.search(r"[*?\[{]", toks[j]):
                return True
    return False


def temp_push_rule_covers(cmd, worktree, cwd):
    """True when `cmd` is one plain push the user's applied temporary rule (H15) allows and does not deny."""
    if FORBIDDEN_CHARS.search(cmd) or re.search(r"[\\'\"*?\[\]{}]", cmd):
        return False  # one plain command: no operators, redirections, $, `, backslash, quotes ('--force') or globs
    roots = lookout_state.worktree_roots(worktree or cwd)
    if not roots or publica.regla_estado(roots[0])[0] != "aplicada":
        return False
    pat = lambda r: r[len("Bash("):-1]  # noqa: E731
    return any(fnmatch.fnmatchcase(cmd, pat(a)) for a in publica.ALLOW if "push" in a) and \
        not any(fnmatch.fnmatchcase(cmd, pat(d)) for d in publica.DENY)


def reserved(cmd, worktree, cwd, rules):
    """'' when the command is not reserved to the user, else why. Over-inclusive on purpose: a false hit only
    shows the user a dialog."""
    usr = dict(DEFAULT_USUARIO, **(rules.get("usuario") or {}))
    raw = cmd.strip()  # the H15 exception is judged on the text as written (a backslash in it: no exception)
    cmd = re.sub(r"\\\r?\n", "", cmd)  # line continuations: `git \<newline>push` is one command for the shell
    # Also look at the text without quotes and backslashes (gi''t push, g\\it push), and when the command builds words at
    # run time ($(...), `...`, eval) the last word alone is enough (push, merge, publish...).
    plain = re.sub(r"[\"'\\]", "", cmd)
    dynamic = "$(" in cmd or "`" in cmd or re.search(r"\beval\b|\$\{?[A-Za-z_]", cmd)
    for entry in usr.get("bash_empieza") or []:
        hit = _reserved_regex(entry).search(cmd) or _reserved_regex(entry).search(plain) or (
            dynamic and re.search(r"\b%s\b" % re.escape(entry.split()[-1]), plain))
        if hit:
            if entry == "git push" and temp_push_rule_covers(raw, worktree, cwd):
                continue
            return entry
    if re.search(r"\beval\b", cmd) or re.search(r"\b(git|gh|npm)\b[^;&|\n]*(\$|`)", cmd):
        return "comando armado en tiempo de ejecución"  # what it runs cannot be read from the text
    if _glob_subcommand(cmd):
        return "subcomando con comodines o llaves"  # `git p*sh`, `git p{u,}sh`: the shell picks the subcommand
    root = worktree or os.path.realpath(cwd)
    deleters = set(usr.get("borrar_fuera") or [])
    for part in SPLIT_OPS.split(cmd):
        try:
            toks = _strip_prefix(shlex.split(part))
        except ValueError:
            toks = _strip_prefix(part.split())
        # The deleter may come after wrappers with their own options (sudo -u root rm …): look for it anywhere.
        at = next((i for i, t in enumerate(toks) if os.path.basename(t) in deleters), None)
        if at is None:
            continue
        for t in toks[at + 1:]:
            if t.startswith("-"):
                continue
            if "$" in t or "`" in t or not inside(real(t, cwd), root):
                return "%s fuera del worktree" % os.path.basename(toks[at])
    return ""


# ---------- side effects ----------

def notify(title, body):
    """herdr notification for the user. Returns {notificado: send time, notif_rc: herdr's exit code}; the <10 s
    budget of Fase 5 is measured on the send time."""
    ts = time.time()
    rc, _, _ = herdr_cli.run(["notification", "show", title[:120], "--body", body[:300], "--sound", "request"],
                             timeout=3)
    return {"notificado": ts, "notif_rc": rc}


def emit(marker, ev):
    pid = marker.get("project_id", "unknown")
    lookout_state.append_event(pid, ev)
    try:
        import heuristicas
        heuristicas.transicion(pid, ev, notificar=False)  # grouped view (Fase 6); this hook already notified
    except Exception:
        pass


def handle(data, marker, rules=None):
    """Returns the hook's stdout dict, or None for no output. Never raises past main()."""
    rules = rules if rules is not None else load_rules()
    name = data.get("hook_event_name", "")
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    mode = data.get("permission_mode", "")
    cwd = data.get("cwd") or os.getcwd()
    sid = data.get("session_id", "")
    detalle = str(ti.get("command") or ti.get("file_path") or ti.get("notebook_path") or "")[:200]
    base = {"session_id": sid, "nombre": marker.get("nombre", ""), "pane": os.environ.get("HERDR_PANE_ID", ""),
            "hook": name, "tool_name": tool, "detalle": detalle, "modo": mode}
    who = marker.get("nombre") or sid[:8]

    if name == "PreToolUse":
        if mode != "auto" or tool != "Bash":
            return None
        why = reserved(ti.get("command") or "", worktree_of(sid, marker), cwd, rules)
        if not why:
            return None
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                       "permissionDecisionReason": "lookout: %s es del usuario (D6)" % why}}

    if name == "PermissionDenied":
        n = notify("lookout: auto mode negó una acción de %s" % who, "%s %s — %s" % (tool, detalle, data.get("reason")))
        emit(marker, dict(base, event="negado", motivo=str(data.get("reason") or "")[:200], **n))
        return None

    if name != "PermissionRequest":
        return None
    if mode != "default":
        ok, why = False, "modo %s: lookout no aprueba nada fuera del modo manual" % (mode or "?")
    elif not rules.get("activo"):
        ok, why = False, "reglas no activadas por el usuario"
    else:
        ok, why = evaluate(tool, ti, worktree_of(sid, marker), cwd, rules)
    if ok:
        emit(marker, dict(base, event="aprobado", regla=why))
        return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
    n = notify("lookout: %s pide permiso" % who, "%s %s — %s" % (tool, detalle, why))
    emit(marker, dict(base, event="blocked", motivo=why, **n))
    herdr_cli.report_metadata(base["pane"], "permiso", marker.get("display"))
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    marker = lookout_state.read_marker(data.get("session_id", ""))
    if not marker:
        return 0
    try:
        out = handle(data, marker)
    except Exception:  # a permission hook must never break the agent: no output = the normal dialog
        return 0
    if out:
        json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())

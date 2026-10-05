"""What lookout needs before it supervises anything (Fase 7): herdr new enough, client and server compatible,
and goalspec (optional: without it the push governance has no adversary verdict to read).

herdr is a hard requirement: `lookout inicia` refuses before taking the lock. goalspec is not: lookout warns
and goes on; `gobierno.decide_push` then says SIN-GOALSPEC instead of waiting forever for a verdict.
"""
import json
import os
import re

import herdr_cli

MIN_HERDR = (0, 9, 1)  # the version every spike and live run used (docs/decisiones-fase0.md, min_herdr_version)
VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def parse_version(text):
    m = VERSION_RE.search(text or "")
    return tuple(int(x) for x in m.groups()) if m else None


def fmt(v):
    return ".".join(str(x) for x in v)


def check_herdr():
    """(ok, problems, notes). problems = reasons to refuse; notes = things worth saying but not blocking."""
    code, out, err = herdr_cli.run(["--version"], timeout=5)
    if code != 0:
        if code == 124 and ("No such file" in err or "not found" in err.lower() or "Errno 2" in err):
            return False, ["herdr no está en el PATH (lookout lo necesita: https://herdr.dev)."], []
        return False, ["`herdr --version` falló (código %d): %s" % (code, (err or out).strip()[:200])], []
    client = parse_version(out)
    if not client:
        return False, ["no entiendo la versión de herdr: %r" % out.strip()[:80]], []
    problems, notes = [], []
    if client < MIN_HERDR:
        problems.append("herdr %s es más viejo que el mínimo %s. Actualízalo (`herdr update`) y reinicia su servidor."
                        % (fmt(client), fmt(MIN_HERDR)))
    code, out, err = herdr_cli.run(["status", "--json"], timeout=5)
    try:
        st = json.loads(out) if code == 0 else None
    except ValueError:
        st = None
    if not isinstance(st, dict):  # every herdr >= the minimum has `status --json`; failing it = no usable server
        problems.append("no pude leer `herdr status --json` (código %d: %s): no sé si su servidor corre ni si es "
                        "compatible. Revisa `herdr status`." % (code, (err or out).strip()[:120]))
        return False, problems, notes
    server = st.get("server") or {}
    if not server.get("running", server.get("status") == "running"):
        problems.append("el servidor de herdr no está corriendo (`herdr status`). Arráncalo y vuelve a intentar.")
        return False, problems, notes
    sv = parse_version(str(server.get("version", "")))
    if sv and sv < MIN_HERDR:
        problems.append("el servidor de herdr es %s, más viejo que el mínimo %s. Reinícialo con el binario nuevo."
                        % (fmt(sv), fmt(MIN_HERDR)))
    if server.get("compatible") is False or server.get("endpoint_compatible") is False:
        problems.append("el cliente de herdr (%s) y su servidor (%s) no son compatibles (`herdr status`). "
                        "Reinicia el servidor con el binario actual." % (fmt(client), fmt(sv) if sv else "?"))
    elif sv and sv != client and not problems:
        notes.append("cliente herdr %s y servidor %s distintos, pero compatibles." % (fmt(client), fmt(sv)))
    if server.get("restart_needed") or server.get("server_binary_stale"):
        notes.append("herdr pide reiniciar su servidor (`herdr status`: restart_needed/server_binary_stale).")
    return not problems, problems, notes


def config_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def goalspec_instalado(project_root):
    """True when a goalspec plugin is installed for this project (user scope, or project/local scope whose
    projectPath contains project_root) and not disabled in the user's or the project's settings."""
    data = _load(os.path.join(config_dir(), "plugins", "installed_plugins.json"))
    keys = []
    for key, entries in (data.get("plugins") or {}).items():
        if key.split("@")[0] != "goalspec":
            continue
        for e in entries if isinstance(entries, list) else []:
            scope = e.get("scope")
            if scope == "user" or (e.get("projectPath") and project_root and _inside(project_root, e["projectPath"])):
                keys.append(key)
                break
    if not keys:
        return False
    settings = [os.path.join(config_dir(), "settings.json")]
    if project_root:
        settings += [os.path.join(project_root, ".claude", n) for n in ("settings.json", "settings.local.json")]
    enabled = {k: True for k in keys}
    for path in settings:  # later files win, as Claude Code applies them
        for k, v in (_load(path).get("enabledPlugins") or {}).items():
            if k in enabled and v is False:
                enabled[k] = False
            elif k in enabled and v is True:
                enabled[k] = True
    return any(enabled.values())


AVISO_GOALSPEC = ("AVISO: goalspec no está instalado para este proyecto. Sigo sin su gobernanza: no hay veredicto del "
                  "adversario que leer antes de un push (`lookout gobierno` dirá SIN-GOALSPEC). Díselo al usuario.")

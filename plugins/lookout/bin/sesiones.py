"""0.13.24 (p-e9c8601cfb): the name SendMessage takes for an agent is its live session's name, not lookout's.

3-tier, 2026-10-17: to=cambio-worktrees gave «No agent named» (the relief's /rename collided with the dead session that
still held the name: Claude Code called it cambio-worktrees-2), to=correccion-snipet-de-cierre gave «not reachable» (the
session had renamed itself). Claude Code keeps each live session in <config>/sessions/<pid>.json (sessionId, name,
messagingSocketPath, procStart); a file whose process is gone names nobody, and neither does one whose pid the system
gave to another process since (its start time is not the file's procStart: codex r1).
"""
import glob
import json
import os
import subprocess

import requisitos


def arranque(pid):
    """Start time of `pid` as Claude Code writes procStart (UTC, C locale), or None when ps cannot say."""
    try:
        r = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5,
                           env=dict(os.environ, TZ="UTC", LC_ALL="C"))
    except (OSError, subprocess.SubprocessError):
        return None
    return " ".join(r.stdout.split()) if r.returncode == 0 else None


def vivo(pid, proc_start=None):
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        pass
    except OSError:
        return False
    # with no procStart a reused pid cannot be told apart, so it names nobody (codex r2; Claude Code always writes it)
    return bool(proc_start) and arranque(pid) == " ".join(str(proc_start).split())


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def de(session_id, base=None):
    """{name, socket} of the live Claude Code session `session_id`, or None."""
    if not session_id:
        return None
    base = base or os.path.join(requisitos.config_dir(), "sessions")
    mejor = None
    for f in glob.glob(os.path.join(base, "*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or d.get("sessionId") != session_id or not d.get("name") \
                or not vivo(d.get("pid"), d.get("procStart")):
            continue
        if mejor is None or _num(d.get("updatedAt")) > _num(mejor.get("updatedAt")):
            mejor = d
    if mejor is None:
        return None
    # one line: a name is printed inside a table row
    return {"name": " ".join(str(mejor["name"]).split()), "socket": str(mejor.get("messagingSocketPath") or "")}


def to(entry):
    """The `to` for SendMessage to this agent, or None when lookout cannot read it."""
    s = de((entry or {}).get("session_id"))
    return s["name"] if s else None


def to_texto(entry):
    """'to=<name>' for the supervisor, or 'to desconocido' (its session is not in <config>/sessions)."""
    t = to(entry)
    return "to=%s" % t if t else "to desconocido"

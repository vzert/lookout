"""One supervisor per project (docs/plan.md 3.4, D1).

lock.json is created with O_EXCL. If it exists, the owner is alive when its Claude process
(pid) still runs and its messaging socket still exists. A live owner -> refuse and name it.
A dead owner -> take the lock over and say so. The same session re-taking its lock is fine.
"""
import json
import os
import time

import lookout_state


def me(nombre=None):
    """Identity of the calling Claude session, from the env Claude Code gives the Bash tool."""
    sock = os.environ.get("CLAUDE_CODE_MESSAGING_SOCKET", "")
    return {
        "session_id": os.environ.get("CLAUDE_CODE_SESSION_ID", ""),
        "pid": int(os.environ.get("CLAUDE_PID", "0") or 0),
        "address": ("uds:" + sock) if sock else "",
        "pane": os.environ.get("HERDR_PANE_ID", ""),
        "nombre": nombre or "",
    }


def owner_alive(owner):
    if not owner:
        return False
    if not lookout_state.pid_alive(owner.get("pid")):
        return False
    addr = owner.get("address", "")
    if addr.startswith("uds:") and not os.path.exists(addr[4:]):
        return False
    return True


def acquire(project_id, common_dir, roots, supervisor):
    """Return (status, lock). status: 'nuevo' | 'propio' | 'tomado-de-muerto' | 'relevo-mismo-proceso' | 'ocupado'."""
    path = os.path.join(lookout_state.project_dir(project_id), "lock.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        "project_id": project_id,
        "common_dir": common_dir,
        "roots": roots,
        "supervisor": supervisor,
        "desde": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        current = lookout_state.read_json(path) or {}
        owner = current.get("supervisor") or {}
        if owner.get("session_id") and owner.get("session_id") == supervisor.get("session_id"):
            current["roots"] = roots
            current["supervisor"] = supervisor
            lookout_state.write_json(path, current)
            return "propio", current
        if owner_alive(owner) and owner.get("pid") and owner.get("pid") == supervisor.get("pid"):
            # Same Claude process, new session: the supervisor ran /clear and resumes itself (Fase 4 manual relief).
            data["anterior"] = owner
            lookout_state.write_json(path, data)
            return "relevo-mismo-proceso", data
        if owner_alive(owner):
            return "ocupado", current
        data["anterior"] = owner
        lookout_state.write_json(path, data)
        return "tomado-de-muerto", data
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    return "nuevo", data


def read(project_id):
    return lookout_state.read_json(os.path.join(lookout_state.project_dir(project_id), "lock.json"))


def release(project_id, session_id):
    path = os.path.join(lookout_state.project_dir(project_id), "lock.json")
    current = lookout_state.read_json(path) or {}
    if (current.get("supervisor") or {}).get("session_id") != session_id:
        return False
    os.remove(path)
    return True

"""Identity registry of a project's agents, keyed by Claude session_id (docs/plan.md 3.3).

Each agent gets one descriptive name (V12) that the supervisor applies in three layers:
/rename (Claude session -> ListAgents name), `herdr agent rename` and `herdr pane rename`. When the user already
named the agent's herdr tab, the name comes from that label, and the user is always told the tab (`quien`).
"""
import os
import re
import subprocess
import time

import lookout_state

GENERIC_TITLES = {"", "claude", "claude code"}


def path(project_id):
    return os.path.join(lookout_state.project_dir(project_id), "registry.json")


def load(project_id):
    return lookout_state.read_json(path(project_id), {"agents": {}})


def save(project_id, reg):
    lookout_state.write_json(path(project_id), reg)


def slug(text, limit=24):
    text = text.lower()
    text = re.sub(r"[áàä]", "a", text)
    text = re.sub(r"[éèë]", "e", text)
    text = re.sub(r"[íìï]", "i", text)
    text = re.sub(r"[óòö]", "o", text)
    text = re.sub(r"[úùü]", "u", text)
    text = text.replace("ñ", "n")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:limit].rstrip("-")


def git_info(cwd):
    def g(*args):
        try:
            out = subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return out.stdout.strip() if out.returncode == 0 else ""
    return g("rev-parse", "--show-toplevel"), g("branch", "--show-current")


def propose_name(agent, worktree, taken):
    """A tab the user named, alone in its tab, gives the name (what the user sees in herdr is what lookout says).
    Otherwise: worktree folder + the session title."""
    own = slug(agent.get("pestana_propia") or "", 40) if (agent.get("pestana_panes") or 1) == 1 else ""
    if own:
        name = own
    else:
        base = os.path.basename(worktree or agent.get("cwd", "")) or "agente"
        title = agent.get("title", "").strip()
        tail = "" if title.lower() in GENERIC_TITLES or title.startswith(base) else slug(title)
        name = slug(base, 20) + ("-" + tail if tail else "")
    name = name[:40].rstrip("-")
    candidate, n = name, 2
    while candidate in taken:
        candidate = "%s-%d" % (name, n)
        n += 1
    return candidate


def quien(entry):
    """How to name an agent to the user: its herdr tab, which is what the user sees (a pane id says nothing).
    'Cambio DeepSeek (cambio-deepseek)' when they differ; the name alone when the tab carries it or is unknown."""
    nombre = entry.get("nombre") or ""
    tab = (entry.get("pestana") or "").strip()
    if not tab or tab == nombre:
        return nombre
    return "%s (%s)" % (tab, nombre)


def register(project_id, supervisor, agents, ajenos=()):
    """Add or refresh the discovered agents; write their supervision markers. Returns the registry.

    A registered agent keeps its name (agents address the supervisor and are addressed by it); only new ones get
    one. `ajenos`: herdr names of other agents in the herdr session, which a new name must not take (herdr names
    are unique across the whole session)."""
    reg = load(project_id)
    known = reg.setdefault("agents", {})
    taken = {a.get("nombre") for a in known.values()} | set(n for n in ajenos if n)
    for a in agents:
        sid = a.get("session_id")
        if not sid or a.get("kind") != "claude":
            continue
        worktree, branch = git_info(a["cwd"])
        entry = known.get(sid) or {}
        if not entry.get("nombre"):
            entry["nombre"] = propose_name(a, worktree, taken)
            taken.add(entry["nombre"])
        entry.update({
            "session_id": sid,
            "pane_id": a.get("pane_id", ""),
            "tab_id": a.get("tab_id", ""),
            "pestana": a.get("pestana", ""),
            "pestana_propia": a.get("pestana_propia", ""),
            "pestana_panes": a.get("pestana_panes") or 1,
            "terminal_id": a.get("terminal_id", ""),
            "herdr_name": a.get("herdr_name", ""),
            "cwd": a.get("cwd", ""),
            "worktree": worktree,
            "branch": branch,
            "estado_herdr": a.get("status", ""),
        })
        entry.setdefault("hooks", "sin-confirmar")
        entry.setdefault("tarea", "")
        entry.setdefault("alta", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        known[sid] = entry
        lookout_state.write_marker(sid, {
            "project_id": project_id,
            "supervisor": supervisor.get("nombre") or "supervisor",
            "address": supervisor.get("address", ""),
            "nombre": entry["nombre"],
            "display": entry["nombre"] + " (lookout)",
        })
    save(project_id, reg)
    return reg


def find(reg, key):
    """Entry by name, session_id, pane_id or herdr name. A relieved session (F3) shares its pane, and once had the
    same herdr name, with the session that replaced it: the live one wins, and the old one is found only by its own
    session_id or its renamed `nombre` (seen 2026-10-02: publica and cierra acted on the dead session)."""
    agents = reg.get("agents", {})
    if key in agents:
        return agents[key]
    hits = [e for sid, e in agents.items() if key in (e.get("nombre"), e.get("pane_id"), e.get("herdr_name"))]
    live = [e for e in hits if e.get("tarea_estado") != "relevada"]
    return (live or hits or [None])[0]

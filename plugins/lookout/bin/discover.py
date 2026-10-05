"""Find the Claude agents of one project among herdr's agents (docs/plan.md 3.7 step 2, D1).

A project is a git common dir: the main checkout and all its worktrees share it, so an agent
working in a worktree belongs to the same project as one on the main checkout.
"""
import os

import herdr_cli
import lookout_state


def resolve_project(arg):
    """Return (project_id, common_dir) for a path, or for a known project_id. (None, None) if not."""
    if arg and os.path.isdir(arg):
        common = lookout_state.git_common_dir(arg)
        if not common:
            return None, None
        return lookout_state.project_id_for(common), common
    if arg and os.path.isfile(os.path.join(lookout_state.project_dir(arg), "lock.json")):
        lock = lookout_state.read_json(os.path.join(lookout_state.project_dir(arg), "lock.json")) or {}
        return arg, lock.get("common_dir")
    return None, None


def self_ids():
    return os.environ.get("HERDR_PANE_ID", ""), os.environ.get("CLAUDE_CODE_SESSION_ID", "")


def discover(common_dir, agents=None, common_of=None):
    """Agents whose cwd resolves to `common_dir`, excluding the calling session.

    `agents` and `common_of` are injectable for tests (default: herdr agent list, git).
    Returns a list of dicts: pane_id, terminal_id, herdr_name, session_id, cwd, title, kind, status.
    """
    agents = herdr_cli.agent_list() if agents is None else agents
    common_of = common_of or lookout_state.git_common_dir
    my_pane, my_session = self_ids()
    cache = {}
    found = []
    for a in agents:
        cwd = a.get("cwd") or ""
        if not cwd:
            continue
        if cwd not in cache:
            cache[cwd] = common_of(cwd)
        if cache[cwd] != common_dir:
            continue
        session = (a.get("agent_session") or {}).get("value", "")
        if a.get("pane_id") == my_pane or (session and session == my_session):
            continue
        found.append({
            "pane_id": a.get("pane_id", ""),
            "terminal_id": a.get("terminal_id", ""),
            "herdr_name": a.get("name", ""),
            "session_id": session,
            "cwd": cwd,
            "title": a.get("terminal_title_stripped", ""),
            "kind": a.get("agent", ""),
            "status": a.get("agent_status", ""),
        })
    return found

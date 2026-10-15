"""0.13.0: take in an agent the user launches by hand while the project is supervised (memory/plans/
plan-lookout-altas-cierres-relevos.md, Fase 3; research A). The user's decision (2026-10-15): it joins by itself.

Before this only `lookout inicia` registered agents: one started later had no marker, so its hooks wrote nothing
(hooks/guard.sh) and the supervisor never saw it. Now the waiter's checker thread (wait_event.revisor) looks every
LOOKOUT_DESCUBRE_CADA seconds (120): a Claude session of this project in herdr's agent list that is not in the
registry is registered (its marker makes its hooks report) and a `nuevo` event wakes the supervisor, who delivers its
note (`lookout entrega`). Never the supervisor itself, another project's session, or one already registered (a relieved
or retired one stays in the registry, so it never comes back as new).
"""
import os
import time

import herdr_cli
import lock
import lookout_state
import registry


def cada():
    try:
        return max(10.0, float(os.environ.get("LOOKOUT_DESCUBRE_CADA") or 120))
    except ValueError:
        return 120.0


def toca(project_id, now=None):
    """Is a discovery pass due? herdr's agent list can take up to 10 s, so not on every pass of the checker; the time of
    the last pass lives in the project's state (each wake starts a new waiter process)."""
    now = time.time() if now is None else now
    path = os.path.join(lookout_state.project_dir(project_id), "descubre.json")
    last = float((lookout_state.read_json(path) or {}).get("ts") or 0)
    if now - last < cada():
        return False
    lookout_state.write_json(path, {"ts": now})
    return True


def descubre(project_id, agents=None, common_of=None, tab_of=None):
    """Register the new sessions of the project; append one `nuevo` event each. Returns those events."""
    import discover
    import retomar
    lk = lock.read(project_id) or {}
    common = lk.get("common_dir")
    sup = lk.get("supervisor") or {}
    if not common or not sup.get("session_id"):
        return []
    todos = herdr_cli.agent_list() if agents is None else agents
    known = set(registry.load(project_id).get("agents", {}))
    candidatos = [a for a in todos if (a.get("agent_session") or {}).get("value")
                  and (a.get("agent_session") or {}).get("value") not in known
                  and (a.get("agent_session") or {}).get("value") != sup["session_id"]
                  and a.get("pane_id") != sup.get("pane")]
    if not candidatos:
        return []
    found = [f for f in discover.discover(common, candidatos, common_of, tab_of)
             if f.get("kind") == "claude" and f.get("session_id")]
    if not found:
        return []
    import lote
    out = []
    # registry.json is rewritten by relevo, cierra-pestana and lanza under this mutex: a register from the waiter's
    # thread without it could drop their change (adversary round 1: a «retirado» lost)
    with lote.project_mutex(project_id):
        known = set(registry.load(project_id).get("agents", {}))
        found = [f for f in found if f["session_id"] not in known]
        if not found:
            return []
        mine = {f["session_id"] for f in found}
        ajenos = {t.get("name") for t in todos if (t.get("agent_session") or {}).get("value") not in mine}
        reg = registry.register(project_id, sup, found, ajenos, todos)
    for f in found:
        e = reg["agents"].get(f["session_id"]) or {}
        ev = {"event": "nuevo", "session_id": f["session_id"], "nombre": e.get("nombre", ""), "pane": f.get("pane_id", ""),
              "hook": "descubre", "pestana": f.get("pestana", ""), "estado_herdr": f.get("status", "")}
        lookout_state.append_event(project_id, ev)
        out.append(ev)
    retomar.al_registrar(project_id, sorted(mine))  # one already idle with a «Como retomar» (Fase 1)
    return out

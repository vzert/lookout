"""0.13.0: take in an agent the user launches by hand while the project is supervised (memory/plans/
plan-lookout-altas-cierres-relevos.md, Fase 3; research A). The user's decision (2026-10-15): it joins by itself.

Before this only `lookout inicia` registered agents: one started later had no marker, so its hooks wrote nothing
(hooks/guard.sh) and the supervisor never saw it. Now the waiter's checker thread (wait_event.revisor) looks every
LOOKOUT_DESCUBRE_CADA seconds (120): a Claude session of this project in herdr's agent list that is not in the
registry is registered (its marker makes its hooks report) and a `nuevo` event wakes the supervisor, who delivers its
note (`lookout entrega`). Never the supervisor itself, another project's session, or one already registered (a relieved
or retired one stays in the registry, so it never comes back as new).

0.13.1: the alta also renames it (`/rename` of the session, herdr's agent and pane names, a tab with herdr's default
label), as `lookout entrega` does. Live 2026-10-15 a supervisor read the waiter's digest through its own grep, missed
the `nuevo` line, never ran `entrega`, and two hand-launched sessions kept their old names. The note stays with
`entrega`: it is long and needs an idle agent. Never typed over a draft: with text in its input box nothing is typed.
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


def caja(pane):
    """What the agent's input box holds (inputbox.classify): "vacia", "sugerencia", "borrador", ... """
    import inputbox
    code, out, _ = herdr_cli.run(["agent", "read", pane, "--source", "visible", "--format", "ansi"])
    return inputbox.classify(out) if code == 0 else "desconocida"


def renombra(entry, tab_of=None):
    """Rename a new agent the way `lookout entrega` does; returns "hecho" or why not. herdr accepts the /rename while
    the session works and Claude Code applies it at the end of the turn (spike 2026-10-05)."""
    pane, nombre = entry.get("pane_id") or "", entry.get("nombre") or ""
    if not pane or not nombre:
        return "sin pane o sin nombre"
    box = caja(pane)
    if box not in ("vacia", "sugerencia"):
        return "caja con " + box
    # what reaches the session is the /rename: if herdr refused it, nothing was renamed (codex round 1)
    if herdr_cli.run(["agent", "prompt", pane, "/rename " + nombre])[0] != 0:
        return "herdr no tecleó el /rename"
    return renombra_herdr(entry, tab_of)


def renombra_herdr(entry, tab_of=None):
    """herdr's side of the rename (agent, pane, tab): calls to herdr only, nothing typed into the session's box."""
    pane, nombre = entry.get("pane_id") or "", entry.get("nombre") or ""
    fallos = []
    if herdr_cli.run(["agent", "rename", pane, nombre])[0] == 0:
        entry["herdr_name"] = nombre
    else:
        fallos.append("agente")
    if herdr_cli.run(["pane", "rename", pane, "lookout: " + nombre])[0] != 0:
        fallos.append("pane")
    tab_id = entry.get("tab_id") or ""
    tab = (tab_of or herdr_cli.tab_get)(tab_id) if tab_id else None
    if tab and (tab.get("pane_count") or 1) == 1 and not herdr_cli.own_label(tab):
        if herdr_cli.run(["tab", "rename", tab_id, nombre])[0] == 0:
            entry["pestana"] = nombre
        else:
            fallos.append("pestaña")
    # codex round 2: a refused herdr rename is not "hecho"; the session's /rename did go
    return "hecho" if not fallos else "a medias: herdr no renombró " + ", ".join(fallos)


RENOMBRE_INTENTOS = 3


def renombra_propio(project_id, session_id, pane, tab_of=None):
    """0.13.5: the alta renames once, from the waiter; a box with the user's draft at that moment («caja con borrador»)
    left the agent without its herdr name until the supervisor delivered the note (3-tier-memory 2026-10-16: a
    session registered in 16 s while the user typed its first prompt). The agent's own state hook finishes it: it runs
    inside that session, and `pane` is its HERDR_PANE_ID, so the pane is that session's while the hook runs. A retry
    from the waiter, outside, had to guess which session the pane held and raced it (adversary, three rounds). Only
    herdr's side (agent, pane, tab), nothing typed into the box; only when the alta recorded «caja con …», herdr shows
    no other name for it (one the user gave is kept), and at most RENOMBRE_INTENTOS times. Returns the result or ""."""
    import lote
    e = registry.load(project_id).get("agents", {}).get(session_id) or {}
    if (not pane or e.get("pane_id") != pane or not str(e.get("renombre") or "").startswith("caja con")
            or (e.get("herdr_name") and not e.get("renombre_parcial")) or e.get("retirado")
            or e.get("tarea_estado") in ("relevada", "relevando", "relevo-fallido", "fallida")
            or int(e.get("renombre_intentos") or 0) >= RENOMBRE_INTENTOS):
        return ""
    # adversary r1 (codex): herdr must answer and see THIS session on that pane (a pane moved to another workspace
    # gets a new id, and HERDR_PANE_ID keeps the old one); a name other than ours was given after the alta
    vivo = herdr_cli.agent_get(pane)
    if not vivo or (vivo.get("agent_session") or {}).get("value") != session_id:
        return ""
    if vivo.get("name") and vivo.get("name") != e.get("nombre"):
        return ""
    copia = dict(e)
    r = renombra_herdr(copia, tab_of)
    with lote.project_mutex(project_id):
        reg = registry.load(project_id)
        x = reg["agents"].get(session_id)
        # adversary r1 (codex): retired or relieved meanwhile: its record is not written over
        if x and not x.get("retirado") and x.get("tarea_estado") not in ("relevada", "relevando", "relevo-fallido"):
            x["renombre_intentos"] = int(x.get("renombre_intentos") or 0) + 1
            x["renombre_parcial"] = r.startswith("a medias")
            if r == "hecho":
                x["renombre"] = "hecho por el agente en herdr (el /rename de la sesión llega con la nota)"
            for k in ("herdr_name", "pestana"):
                if copia.get(k):
                    x[k] = copia[k]
            registry.save(project_id, reg)
    return r


def pasada(project_id):
    """One discovery pass of the waiter's checker: herdr's agent list once, for the alta and for the sweep."""
    todos = herdr_cli.agent_list()
    descubre(project_id, todos)
    barre(project_id, todos)


def barre(project_id, agents):
    """0.13.2: an agent already registered and quiet, whose last turn left a «Como retomar», never gets another Stop,
    so its block was never read (3-tier-memory, 2026-10-15: hook-para-checkpoint, vigente, idle since 00:51 and never
    relieved). Each pass reads the last turn of the registered agents herdr sees idle or done; `retomar.al_registrar`
    writes one `retomar` event per block and classification (not one its Stop already announced; again when it changes,
    e.g. an ambiguo now vigente). A transcript that did not change since the last read is
    skipped (the per-agent read also scans the other agents' transcripts)."""
    import retomar
    reg = registry.load(project_id).get("agents", {})
    estados, cambiados = {}, []
    vistos_path = os.path.join(lookout_state.project_dir(project_id), "barrido.json")
    vistos = lookout_state.read_json(vistos_path) or {}
    for a in agents or []:
        sid = (a.get("agent_session") or {}).get("value")
        e = reg.get(sid)
        if not sid or not e or e.get("retirado") or a.get("agent_status") not in ("idle", "done"):
            continue
        import deliver
        try:
            mtime = os.path.getmtime(deliver.transcript_path(sid))
        except (OSError, TypeError):
            continue
        if vistos.get(sid) == mtime:
            continue
        estados[sid] = a.get("agent_status")
        cambiados.append(sid)
        vistos[sid] = mtime
    if not cambiados:
        return []
    out = retomar.al_registrar(project_id, cambiados, estados=estados, hook="barrido")
    lookout_state.write_json(vistos_path, vistos)
    return out


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
    copias = {f["session_id"]: dict(reg["agents"].get(f["session_id"]) or {}) for f in found}
    renombres = {sid: renombra(c, tab_of) for sid, c in copias.items()}
    with lote.project_mutex(project_id):  # herdr calls above run outside the mutex; only the save is inside
        reg = registry.load(project_id)
        for sid, r in renombres.items():
            e = reg["agents"].get(sid)
            if e:  # renombra sets each field only when herdr accepted it
                e["renombre"] = r  # 0.13.5: the agent's own hook finishes what a draft stopped (renombra_propio)
                for k in ("herdr_name", "pestana"):
                    if copias[sid].get(k):
                        e[k] = copias[sid][k]
        registry.save(project_id, reg)
    for f in found:
        e = reg["agents"].get(f["session_id"]) or {}
        ev = {"event": "nuevo", "session_id": f["session_id"], "nombre": e.get("nombre", ""), "pane": f.get("pane_id", ""),
              "hook": "descubre", "pestana": e.get("pestana") or f.get("pestana", ""), "estado_herdr": f.get("status", ""),
              "renombre": renombres.get(f["session_id"], "")}
        lookout_state.append_event(project_id, ev)
        out.append(ev)
    retomar.al_registrar(project_id, sorted(mine))  # one already idle with a «Como retomar» (Fase 1)
    return out

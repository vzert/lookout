"""The user's pending decisions (T4 of the pilot: ~5 h for an answer with three agents waiting).

The supervisor opens one entry each time it puts a question to the user (AskUserQuestion) and closes it
when the answer comes. The digest shows the open ones with their age, so neither the supervisor nor a
relief of it forgets what is waiting on the user; opening one also shows a herdr notification.
No repeated reminders here (that is F6). An option offered to the user stays blocked until the user
answers (T3): an open entry is that block, written down.
"""
import os
import time

import herdr_cli
import lookout_state


def path(project_id):
    return os.path.join(lookout_state.project_dir(project_id), "decisiones.json")


def load(project_id):
    return lookout_state.read_json(path(project_id)) or {"n": 0, "items": []}


def abre(project_id, texto, agentes=(), notificar=True):
    d = load(project_id)
    d["n"] += 1
    item = {"id": "d%d" % d["n"], "texto": texto, "agentes": list(agentes), "desde": time.time(), "estado": "abierta"}
    d["items"].append(item)
    lookout_state.write_json(path(project_id), d)
    if notificar:
        herdr_cli.run(["notification", "show", "lookout: decisión tuya pendiente", "--body", texto[:160],
                       "--sound", "request"], timeout=5)
    return item


def cierra(project_id, did, respuesta, aprueba):
    """`aprueba` is the user's yes/no, stated explicitly: only a yes authorizes anything (adversary round 2:
    an answer "no" used to count as authorization)."""
    d = load(project_id)
    for it in d["items"]:
        if it["id"] == did and it["estado"] == "abierta":
            it.update(estado="respondida", respuesta=respuesta, aprueba=bool(aprueba), hasta=time.time())
            lookout_state.write_json(path(project_id), d)
            return it
    return None


def respondida(project_id, did):
    """The decision with this id answered YES by the user, or None: what --usuario-confirmo / --usuario-amplia must cite, so the
    user's yes is on the record before it is used (adversary round 1: a bare flag let the caller assert it)."""
    return next((it for it in load(project_id)["items"]
                 if it["id"] == did and it["estado"] == "respondida" and it.get("aprueba") is True), None)


def tomadas_de(project_id, agentes):
    """Answered decisions that concern any of these agents (Fase 4: what a relief must not ask again)."""
    want = set(agentes or ())
    return [it for it in load(project_id)["items"]
            if it["estado"] == "respondida" and want and want & set(it.get("agentes") or ())]


def abiertas(project_id):
    return [it for it in load(project_id)["items"] if it["estado"] == "abierta"]


def edad(ts, now=None):
    m = int(((now or time.time()) - ts) // 60)
    return "%d min" % m if m < 120 else "%d h %d min" % (m // 60, m % 60)


def render(project_id, now=None):
    items = abiertas(project_id)
    if not items:
        return ""
    return "Decisiones del usuario pendientes (%d):\n" % len(items) + "\n".join(
        "- %s (hace %s%s): %s" % (it["id"], edad(it["desde"], now),
                                  "; esperan: " + ", ".join(it["agentes"]) if it["agentes"] else "", it["texto"])
        for it in items)

"""The user's pending decisions (T4 of the pilot: ~5 h for an answer with three agents waiting).

The supervisor opens one entry each time it puts a question to the user (AskUserQuestion) and closes it
when the answer comes. The digest shows the open ones with their age, so neither the supervisor nor a
relief of it forgets what is waiting on the user; opening one also shows a herdr notification.
No repeated reminders here (that is F6). An option offered to the user stays blocked until the user
answers (T3): an open entry is that block, written down.
"""
import os
import re
import time

import herdr_cli
import lookout_state


def path(project_id):
    return os.path.join(lookout_state.project_dir(project_id), "decisiones.json")


def load(project_id):
    return lookout_state.read_json(path(project_id)) or {"n": 0, "items": []}


def abre(project_id, texto, agentes=(), notificar=True, si_es="", tipo="", shells=None, permiso=None):
    """0.13.9: `si_es` = the label of the modal option that means yes; the modal's hook then closes the decision
    itself, aprueba = (the user's literal choice == si_es), so no `--cierra … --si` of the supervisor is needed (live
    3-tier 2026-10-16: auto mode denied that command as «Auto-Mode Bypass» for d113). `tipo` = "cierre": a decision
    about closing the tab of `agentes` (retiro.cierre_decidido accepts only that kind). 0.13.10: `shells` =
    {"parar": label, "dejar": label}: what /exit does with the background work of `agentes` (salida.eleccion); the
    hook writes down which of the two the user chose, and any other answer (wait) authorizes nothing. 0.13.12:
    `permiso` = {"comando", "ts"} of the agent's pending permission request (aprueba.abre, tipo "permiso")."""
    if shells:
        tipo = "shells"
    d = load(project_id)
    d["n"] += 1
    item = dict({"id": "d%d" % d["n"], "texto": texto, "agentes": list(agentes), "desde": time.time(),
                 "estado": "abierta"}, **({"si_es": si_es} if si_es and si_es.strip() else {}),  # as given (r10)
                **({"tipo": tipo} if tipo else {}),
                **({"opciones": {k: v for k, v in shells.items() if v and v.strip()}} if shells else {}),
                **({"permiso": dict(permiso)} if permiso else {}))
    d["items"].append(item)
    lookout_state.write_json(path(project_id), d)
    if notificar:
        herdr_cli.notifica(project_id, "decision", "lookout: decisión tuya pendiente", texto[:160], timeout=5)
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


def marca_usada(project_id, did, now=None):
    """0.13.12: a yes to a permission request presses one dialog, once (aprueba.aprueba)."""
    d = load(project_id)
    for it in d["items"]:
        if it["id"] == did:
            it["usada"] = now or time.time()
    lookout_state.write_json(path(project_id), d)


def respondida(project_id, did):
    """The decision with this id answered YES by the user, or None: what --usuario-confirmo / --usuario-amplia must cite, so the
    user's yes is on the record before it is used (adversary round 1: a bare flag let the caller assert it)."""
    return next((it for it in load(project_id)["items"]
                 if it["id"] == did and it["estado"] == "respondida" and it.get("aprueba") is True), None)


# Fase 9 C4: every AskUserQuestion of the supervisor is on record from its hook, without depending on the model
# (claude-vzert: not one question of the session reached decisiones.json). 0.12.0: the supervisor asks the user's
# pending decisions in ONE modal (3-tier-memory, 2026-10-15: two decisions in prose, 34 s apart, lost in the scroll),
# one question per decision with its id at the end: `(d3)`. A question attaches ONLY to the decision whose id it names
# (the last id in its full text; adversary rounds 1-2: every guess, "all open ones" and then "the oldest waiting",
# put an answer on a decision the modal never asked). A decision counts as answered only when the answer to its own
# question arrives. Anything unmatched stays waiting, and the Stop check reminds it once: a miss errs toward asking.
# A modal that names no decision at all becomes its own entry, as before. The hook writes down the user's answer as
# given and never turns it into a yes: only the literal --si-es choice (or `decision --cierra … --si`) authorizes
# (respondida()).
ID_EN_PREGUNTA = re.compile(r"\bd(\d+)\b")


def esperando(project_id, d=None):
    """Decisions the supervisor opened that have no answer of the user yet (modal or chat). A modal the user dismissed,
    or one whose questions did not name the decision, leaves it here."""
    d = d or load(project_id)
    return [it for it in d["items"] if it["estado"] == "abierta" and it.get("origen") != "hook"
            and not it.get("respuesta_usuario")]


def sin_preguntar(project_id):
    """What the supervisor's Stop check reminds it of (0.12.0): a decision it opened that the user has not answered."""
    return esperando(project_id)


def marca_recordadas(project_id, ids, now=None):
    """The Stop check reminds each decision once: it stamps the ones it named, so the next turn end does not nag."""
    d = load(project_id)
    for it in d["items"]:
        if it["id"] in ids:
            it["recordada"] = now or time.time()
    lookout_state.write_json(path(project_id), d)


def id_de(pregunta):
    """The decision id a question names: the LAST `dN` in its full text (the id goes at the end), or None."""
    ids = ID_EN_PREGUNTA.findall(pregunta or "")
    return "d" + ids[-1] if ids else None


def registra_pregunta(project_id, tool_use_id, preguntas, now=None):
    """`preguntas`: the modal's FULL question texts (never truncated: the id is at the end). A string joined by " | "
    is split."""
    now = now or time.time()
    if isinstance(preguntas, str):
        preguntas = [q for q in preguntas.split(" | ") if q]
    d = load(project_id)
    libres = {it["id"]: it for it in esperando(project_id, d)}
    ligadas = []
    for q in preguntas:
        it = libres.pop(id_de(q), None)
        if it:
            it.update(tool_use_id=tool_use_id, pregunta=q[:2000])
            ligadas.append(it)
    if ligadas:
        item = ligadas[-1]
    else:
        texto = " | ".join(q[:300] for q in preguntas)
        d["n"] += 1
        item = {"id": "d%d" % d["n"], "texto": texto, "agentes": [], "desde": now, "estado": "abierta",
                "origen": "hook", "tool_use_id": tool_use_id, "pregunta": texto}
        d["items"].append(item)
    lookout_state.write_json(path(project_id), d)
    return item


def registra_respuesta(project_id, tool_use_id, respuesta, now=None, por_pregunta=None):
    """The user's literal answer. A decision the hook opened (a modal naming no decision) is closed with the whole
    `respuesta` (aprueba unknown: None). A decision the supervisor opened gets only the answer to ITS question
    (`por_pregunta`: question text -> answer, as Claude Code reports it); with no answer to its question it stays
    waiting. It stays open for `decision --cierra … --si|--no`, unless it was opened with `si_es` (0.13.9): then this
    closes it, yes only if the user's choice is that label. Returns the last one it touched, or None."""
    if not tool_use_id:
        return None
    por_pregunta = por_pregunta or {}
    d = load(project_id)
    hit = None
    for it in d["items"]:
        if it.get("tool_use_id") != tool_use_id:
            continue
        if it.get("origen") == "hook":
            it["respuesta_usuario"] = respuesta
            if it["estado"] == "abierta":
                it.update(estado="respondida", respuesta=respuesta, aprueba=None, hasta=now or time.time())
            hit = it
            continue
        mia = next((a for q, a in por_pregunta.items() if id_de(q) == it["id"]), None)
        if mia not in (None, ""):
            it["respuesta_usuario"] = str(mia)[:300]
            if it.get("si_es") and it["estado"] == "abierta":  # 0.13.9: the user's own choice decides, by structure
                it.update(estado="respondida", respuesta=str(mia)[:300], aprueba=str(mia) == it["si_es"],
                          por_hook=True, hasta=now or time.time())
            elif it.get("opciones") and it["estado"] == "abierta":  # 0.13.10: which option, the exact label
                cual = next((k for k, v in it["opciones"].items() if str(mia) == v), None)
                it.update(estado="respondida", respuesta=str(mia)[:300], aprueba=cual is not None, eleccion=cual,
                          por_hook=True, hasta=now or time.time())
            hit = it
    if hit:
        lookout_state.write_json(path(project_id), d)
    return hit


def registra_respuesta_chat(project_id, respuesta, now=None):
    """Fase 9 F2: the user's chat answer goes to the most recent open decision, as `registra_respuesta` does for a
    modal one. None when nothing is open (the prompt is still on the supervisor's log)."""
    d = load(project_id)
    abiertas_ = [it for it in d["items"] if it["estado"] == "abierta"]
    if not abiertas_:
        return None
    it = max(abiertas_, key=lambda x: x["desde"])
    it["respuesta_usuario"] = respuesta
    it["via"] = "chat"
    if it.get("origen") == "hook":
        it.update(estado="respondida", respuesta=respuesta, aprueba=None, hasta=now or time.time())
    lookout_state.write_json(path(project_id), d)
    return it


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


def clave_render(project_id):
    """What render() shows, without the ages that change every minute: digest prints the block again only when this
    changes (0.12.2)."""
    return [{k: v for k, v in it.items() if k != "desde"} for it in abiertas(project_id)]


def etiquetas(it):
    """0.13.14: the exact labels of the modal options this decision reads (--si-es, or --shells-parar/--shells-dejar),
    for supervisor.md, the digest and the Stop reminder: with any other label the user's yes counts as no (codex r11 on
    0887ded). Never clipped, a newline written as \\n, and before the question, so a clip of a long question never
    cuts it."""
    ops = [("sí", it.get("si_es"))] + sorted((it.get("opciones") or {}).items(), key=lambda kv: kv[0] != "parar")
    ops = ["%s = «%s»" % (k, str(v).replace("\n", "\\n")) for k, v in ops if v]
    return " [modal: %s]" % ", ".join(ops) if ops else ""


def render(project_id, now=None, ancho=None):
    """`ancho` (the digest's line width): each line on one line and at most that wide, clipping only the question."""
    items = abiertas(project_id)
    if not items:
        return ""
    filas = []
    for it in items:
        cabeza = "- %s (hace %s%s)%s: " % (it["id"], edad(it["desde"], now),
                                          "; esperan: " + ", ".join(it["agentes"]) if it["agentes"] else "", etiquetas(it))
        texto = it["texto"]
        if ancho:
            texto = " ".join(str(texto).split())
            n = max(ancho - len(cabeza), 40)
            texto = texto if len(texto) <= n else texto[:n - 1] + "…"
        filas.append(cabeza + texto)
    return "Decisiones del usuario pendientes (%d):\n" % len(items) + "\n".join(filas)

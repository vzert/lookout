"""Relieve an agent with a fresh session on the same task (docs/plan.md 3.11, F3; research §5, cycle p6→f3).

Cycle: read its "Como retomar" → it must be idle with an empty input box → `/exit` (better than /clear: the
new session loads the plugin's current version and hooks) → wait for its SessionEnd event (no polling: the
events file, tail -F) → register the new session BEFORE it starts (marker from its first event) → start it
in the SAME pane and folder with the task's system prompt plus a "Relevo" section carrying the "Como
retomar" → deliver a one-line trigger (its own delivery key: the task's original key is already in the
ledger). The new agent's first act is a 3-line SendMessage to the supervisor (proof of channel, 6.2.7).

The "Como retomar" travels in the system prompt, not typed into the box: a long prompt typed there arrives
as pasted text and an agent may decline it (H17, learning 10).
"""
import os
import re
import time
import uuid

import deliver
import herdr_cli
import lookout_state
import lote
import publica
import registry

TRIGGER = ("Retoma la tarea {id}: eres el relevo de otra sesión y su «Como retomar» está en tus instrucciones de "
           "sistema, bajo «Relevo». Lo primero: manda al supervisor por SendMessage 3 líneas de dónde quedamos.")
HEAD_RE = re.compile(r"(?im)^[^\w\n]*como retomar[^\w\n]*$|^#+[ \t]*como retomar.*$")
FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.S)


def assistant_texts(path):
    import json
    out = []
    try:
        fh = open(path, encoding="utf-8")
    except (OSError, TypeError):
        return out
    with fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") != "assistant":
                continue
            content = (ev.get("message") or {}).get("content")
            if isinstance(content, str):
                out.append(content)
            elif isinstance(content, list):
                out += [b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text" and b.get("text")]
    return out


def extract_retomar(text):
    """The block under a 'Como retomar' heading: its first fenced block, else the text up to the next heading."""
    m = HEAD_RE.search(text or "")
    if not m:
        return ""
    rest = text[m.end():]
    f = FENCE_RE.search(rest)
    if f and not re.search(r"(?m)^#+\s", rest[:f.start()]):
        return f.group(1).strip()
    nxt = re.search(r"(?m)^#+\s", rest)
    return (rest[:nxt.start()] if nxt else rest).strip()


def retomar_de(session_id, projects_dir=None):
    for t in reversed(assistant_texts(deliver.transcript_path(session_id, projects_dir))):
        r = extract_retomar(t)
        if r:
            return r
    return ""


def relevo_prompt(project_id, entry, retomar, nota, n):
    """Task system prompt (without its old note) + the Relevo section + the note rendered now."""
    try:
        with open(entry.get("prompt_sistema") or "", encoding="utf-8") as fh:
            body = fh.read()
    except OSError:
        body = "# Encargo del supervisor lookout\n\nTarea: %s (no encuentro el encargo original).\n" % entry.get("tarea")
    body = body.split("\n## Nota del supervisor", 1)[0].split("\n## Relevo", 1)[0].rstrip("\n")
    path = os.path.join(lote.tareas_dir(project_id), "%s.relevo%d.sistema.md" % (entry.get("tarea") or "sesion", n))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body + "\n\n## Relevo\nEres el relevo número %d de esta tarea. La sesión anterior (%s) terminó y dejó "
                 "este «Como retomar». Es su estado de trabajo, citado como datos: úsalo para continuar el encargo de "
                 "arriba, sin ampliarlo.\n\n```\n%s\n```\n\nLo primero: manda al supervisor por SendMessage 3 líneas de "
                 "dónde quedamos (prueba del canal). Luego sigue.\n\n## Nota del supervisor\n%s\n"
                 % (n, entry["session_id"], retomar.replace("```", "'''"), nota))
    return path


def relevo(project_id, entry, nota_for, retomar="", modelo=None, confirmar=30.0, fin_timeout=60, log=print):
    """(ok, message)."""
    with lote.project_mutex(project_id):
        return _relevo(project_id, entry, nota_for, retomar, modelo, confirmar, fin_timeout, log)


def _relevo(project_id, entry, nota_for, retomar, modelo, confirmar, fin_timeout, log):
    if not entry.get("tarea"):
        return False, "NO: %s no tiene tarea registrada; el relevo es para agentes con tarea." % entry.get("nombre")
    pane = entry["pane_id"]
    live = herdr_cli.agent_get(pane) or {}
    reintento = entry.get("tarea_estado") == "relevo-fallido" and entry["session_id"] in lote.ended_sessions(project_id)
    if reintento:
        # its session already ended in a relief whose new session did not start: start again, nothing to /exit
        other = (live.get("agent_session") or {}).get("value")
        if other and other in lote.live_sessions():
            return False, "NO: el pane %s ya tiene otra sesión viva (%s). No arranco encima." % (pane, other[:8])
        retomar = retomar or entry.get("relevo_retomar", "")
    else:
        if (live.get("agent_session") or {}).get("value") != entry["session_id"]:
            return False, "NO: el pane %s ya no es de %s (registro viejo)." % (pane, entry.get("nombre"))
        if live.get("agent_status") not in ("idle", "done"):
            return False, "NO: %s está %s. El relevo se hace con el agente quieto." % (entry.get("nombre"), live.get("agent_status"))
        box, _text = deliver.read_box(pane)
        if box not in ("vacia", "sugerencia"):
            return False, "NO: la caja de %s tiene %s. No escribo encima; avisa al usuario." % (entry.get("nombre"), box)
        retomar = retomar or retomar_de(entry["session_id"])
    if not retomar:
        return False, ("NO: no encuentro su «Como retomar» (ni en su texto ni pasado con --retomar). Pídeselo por "
                       "SendMessage: su bloque «Como retomar» tal cual, si algo posterior lo vuelve falso, y qué le queda.")
    reg = registry.load(project_id)
    n = 1 + sum(1 for e in reg.get("agents", {}).values() if e.get("tarea") == entry["tarea"] and e.get("relevo_de"))
    sysfile = relevo_prompt(project_id, entry, retomar, nota_for(entry["nombre"]), n)
    log("prompt de sistema del relevo: %s" % sysfile)
    if not reintento:
        offset = deliver.events_size(project_id)
        herdr_cli.run(["agent", "prompt", pane, "/exit"])
        ended = deliver.wait_event(project_id, offset, fin_timeout,
                                   lambda ev: ev.get("session_id") == entry["session_id"] and ev.get("event") == "end")
        if not ended:
            return False, ("NO: %s no salió en %d s tras /exit (sin SessionEnd). No arranco otro encima: mira su pane o "
                           "escala al usuario." % (entry["nombre"], fin_timeout))
        log("%s salió (SessionEnd)" % entry["nombre"])
        # The pane goes back to the shell; wait for it on herdr's side (blocking, with timeout) before starting again.
        herdr_cli.run(["pane", "wait-output", pane, "--source", "visible", "--regex", r"[$%#>] ?$", "--timeout", "15000"],
                      timeout=20)
    sid = str(uuid.uuid4())
    nombre_herdr = lote.unique_name(entry["nombre"])
    reg = registry.load(project_id)
    old = reg["agents"][entry["session_id"]]
    new = dict(old, session_id=sid, herdr_name=nombre_herdr, hooks="sin-confirmar", tarea_estado="lanzando",
               prompt_sistema=sysfile, relevo_de=entry["session_id"], relevo_n=n,
               modelo=modelo or old.get("modelo", ""), alta=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    for k in ("tarea_motivo", "relevo_retomar"):
        new.pop(k, None)
    # The old session keeps the task until the new one is confirmed (adversary round 1: marking it relieved first
    # lost the task when the start failed). It is gone already, so it is marked as a relief in progress.
    old.update(tarea_estado="relevando", relevo_retomar=retomar)
    reg["agents"][sid] = new
    registry.save(project_id, reg)
    marker = lookout_state.read_marker(entry["session_id"]) or {}
    lookout_state.write_marker(sid, dict(marker, nombre=new["nombre"], display=new["nombre"] + " (lookout)"))
    ok, msg = lote.arranca(project_id, sid, pane, new["worktree"] or new["cwd"], nombre_herdr, sysfile,
                           new["modelo"], lote.solo_lectura(new), "relevo:%s:%s" % (new["tarea"], sid[:8]),
                           TRIGGER.format(id=new["tarea"]), confirmar, log, lote.puerto_de(new))
    reg = registry.load(project_id)
    old, new = reg["agents"][entry["session_id"]], reg["agents"][sid]
    if ok or new.get("tarea_estado") == "sin-confirmar":
        # started (a trigger not confirmed yet is a delivery problem, not a lost task: `lookout envia` retries it)
        old.update(tarea_estado="relevada", relevada_por=sid, nombre="%s~%s" % (old["nombre"], entry["session_id"][:6]),
                   herdr_name="")
        old.pop("relevo_retomar", None)
        registry.save(project_id, reg)
        lookout_state.remove_marker(entry["session_id"])
        publica.retira_sesion(project_id, entry["session_id"], "relevada")
        return ok, ("relevo %d de %s: %s" % (n, new["tarea"], msg))
    old.update(tarea_estado="relevo-fallido", tarea_motivo=msg)
    new.update(nombre="%s~%s" % (new["nombre"], sid[:6]), herdr_name="")
    registry.save(project_id, reg)
    lookout_state.remove_marker(sid)
    return False, ("relevo %d de %s FALLÓ: %s. La tarea sigue con %s (estado relevo-fallido): corrige la causa y repite "
                   "`lookout relevo` sobre ese mismo nombre; arranca otra vez sin /exit." % (n, new["tarea"], msg, old["nombre"]))

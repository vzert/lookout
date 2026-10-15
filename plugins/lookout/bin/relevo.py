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
import time
import uuid

import deliver
import herdr_cli
import lookout_state
import lote
import publica
import registry
import retomar as retomar_mod

TRIGGER = ("Retoma la tarea {id}: eres el relevo de otra sesión y su «Como retomar» está en tus instrucciones de "
           "sistema, bajo «Relevo». Lo primero: manda al supervisor por SendMessage 3 líneas de dónde quedamos.")
TRIGGER_SIN_TAREA = ("Retoma el trabajo de {id}: eres el relevo de otra sesión y su «Como retomar» está en tus "
                     "instrucciones de sistema, bajo «Relevo». Lo primero: manda al supervisor por SendMessage 3 líneas "
                     "de dónde quedamos.")


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
    """The block to resume from (retomar.bloque): "" when there is none or its header says there is nothing to
    resume («Como retomar: Ninguno»)."""
    estado, blk = retomar_mod.bloque(text)
    return blk if estado == "hay" else ""


def retomar_de(session_id, projects_dir=None):
    """0.13.0: only the agent's LAST turn. Searching back took a stale block under newer messages without one
    (plan-ciclo, 3-tier-memory: a block of 2026-10-07 under its last message of 2026-10-15)."""
    text, _ts = retomar_mod.ultimo_turno(deliver.transcript_path(session_id, projects_dir))
    return extract_retomar(text)


def clave_de(entry):
    """The task id, or the agent's name for one launched by hand (0.13.0: discovered agents have no task)."""
    return entry.get("tarea") or entry.get("nombre", "").split("~")[0]


def relevo_prompt(project_id, entry, retomar, nota, n):
    """Task system prompt (without its old note) + the Relevo section + the note rendered now."""
    try:
        with open(entry.get("prompt_sistema") or "", encoding="utf-8") as fh:
            body = fh.read()
    except OSError:
        if entry.get("tarea"):
            body = "# Encargo del supervisor lookout\n\nTarea: %s (no encuentro el encargo original).\n" % entry.get("tarea")
        else:
            body = ("# Agente supervisado por lookout\n\nLa sesión anterior (%s) la lanzó el usuario, sin encargo escrito de "
                    "lookout: tu trabajo es el de su «Como retomar», abajo.\n" % entry.get("nombre"))
    body = body.split("\n## Nota del supervisor", 1)[0].split("\n## Relevo", 1)[0].rstrip("\n")
    path = os.path.join(lote.tareas_dir(project_id), "%s.relevo%d.sistema.md" % (clave_de(entry) or "sesion", n))
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
    # 0.13.0: the relief runs with the old session's model (with its window), effort and permission mode; one that cannot
    # be read stops it (adversary round 1: also for an agent with a task): a relief must not change the agent silently.
    # The API's message.model is not used: it drops the window («claude-opus-5-5» for a [1m] session).
    cfg = retomar_mod.config(deliver.transcript_path(entry["session_id"]))
    modelo = modelo or cfg.get("modelo") or entry.get("modelo", "")
    faltan = [k for k, v in (("modelo", modelo), ("esfuerzo", cfg.get("esfuerzo")), ("modo de permisos", cfg.get("permisos")))
              if not v]
    if faltan:  # a retry too (adversary round 2): its ended session's transcript still says how it ran
        return False, ("NO: no leo %s de %s en su transcript. No lo relevo solo: pregúntale al usuario (o repite con "
                       "--modelo si solo falta el modelo y él lo confirma)." % (", ".join(faltan), entry.get("nombre")))
    reg = registry.load(project_id)
    if entry.get("tarea"):
        n = 1 + sum(1 for e in reg.get("agents", {}).values() if e.get("tarea") == entry["tarea"] and e.get("relevo_de"))
    else:
        n = int(entry.get("relevo_n") or 0) + 1
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
               modelo=modelo or old.get("modelo", ""), esfuerzo=cfg.get("esfuerzo") or old.get("esfuerzo", ""),
               permisos=cfg.get("permisos") or old.get("permisos", ""), alta=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
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
                           new["modelo"], lote.solo_lectura(new), "relevo:%s:%s" % (clave_de(new), sid[:8]),
                           (TRIGGER if new.get("tarea") else TRIGGER_SIN_TAREA).format(id=clave_de(new)), confirmar, log,
                           # an agent launched by hand had no port of lookout; its checkout path is shared by all
                           lote.puerto_de(new) if new.get("tarea") or new.get("clave_puerto") else None,
                           new.get("esfuerzo", ""), new.get("permisos", ""))
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
        return ok, ("relevo %d de %s: %s" % (n, clave_de(new), msg))
    old.update(tarea_estado="relevo-fallido", tarea_motivo=msg)
    new.update(nombre="%s~%s" % (new["nombre"], sid[:6]), herdr_name="")
    registry.save(project_id, reg)
    lookout_state.remove_marker(sid)
    return False, ("relevo %d de %s FALLÓ: %s. La tarea sigue con %s (estado relevo-fallido): corrige la causa y repite "
                   "`lookout relevo` sobre ese mismo nombre; arranca otra vez sin /exit." % (n, clave_de(new), msg, old["nombre"]))

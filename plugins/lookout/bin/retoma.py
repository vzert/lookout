"""0.13.20: `lookout retoma` starts again an agent whose session ended without anyone asking, with `claude --resume`.

Live 3-tier 2026-10-17 22:42:48: a stray `pkill … -n` killed three reliefs (SessionEnd reason «other»). Their panes stayed
at a shell prompt, `relevo` needs the session alive, `lanza` only opens new agents, and the supervisor asked the user to
type `claude --resume` by hand. `--resume <sid>` keeps the session id (measured the next morning: SessionStart with
source «resume» and the same id), so its marker, registry entry and task still hold: nothing is re-registered.
In its own pane when the pane is at a shell prompt in the session's folder; a new tab on that folder when the pane is
gone. The trigger tells it what happened; its context is its own (no new system prompt).
"""
import os
import re
import time

import deliver
import herdr_cli
import lookout_state
import lote
import registry
import retomar as retomar_mod

FINES = ("relevada", "relevando")
TRIGGER = ("Tu sesión terminó a las %s sin que nadie lo pidiera (SessionEnd «%s») y lookout la retomó con --resume. Lo que "
           "corría en segundo plano murió con ella. Antes de seguir, manda al supervisor por SendMessage 3 líneas: en qué "
           "ibas, qué quedó a medias y qué haces ahora.")


def fin(project_id, sid):
    """Its last start/end event when that is an end, else None."""
    last = None
    for ev in lookout_state.read_events(project_id, 0)[0]:
        if ev.get("session_id") == sid and ev.get("event") in ("start", "end"):
            last = ev
    return last if last and last.get("event") == "end" else None


def salio_solo(ev, entry):
    """An agent whose session ended without lookout or anyone typing /exit: what `retoma` is for. A /exit gives
    «prompt_input_exit»; the kill of 2026-10-17 gave «other»."""
    return bool(ev and ev.get("event") == "end" and ev.get("razon") == "other" and not entry.get("retirado")
                and entry.get("tarea_estado") not in FINES + ("relevo-fallido",))


def retoma(project_id, entry, confirmar=30.0, log=print):
    """(ok, message)."""
    with lote.project_mutex(project_id):
        return _retoma(project_id, entry, confirmar, log)


def _retoma(project_id, entry, confirmar, log):
    sid, nombre = entry["session_id"], entry.get("nombre")
    if entry.get("tarea_estado") == "relevo-fallido":
        return False, ("NO: %s quedó en un relevo fallido; eso se repite con `lookout relevo %s %s`." % (
            nombre, project_id, nombre))
    if entry.get("retirado") or entry.get("tarea_estado") in FINES:
        return False, "NO: %s ya no es un agente de la tabla (relevado o cerrado)." % nombre
    end = fin(project_id, sid)
    if not end or sid in lote.live_sessions():
        return False, "NO: la sesión de %s no terminó (sigue viva): no hay nada que retomar." % nombre
    tr = deliver.transcript_path(sid)
    if not tr:
        return False, ("NO: no encuentro el transcript de %s (%s): sin él no hay --resume. Escala al usuario." % (
            nombre, sid[:8]))
    carpeta = entry.get("cwd") or entry.get("worktree")
    # --resume looks for the conversation under the folder it starts in: a transcript of another folder is not found
    if carpeta and os.path.basename(os.path.dirname(tr)) != re.sub(r"[^A-Za-z0-9-]", "-", carpeta.rstrip("/")):
        return False, ("NO: el transcript de %s está en %s y su carpeta registrada es %s: --resume no lo encontraría. "
                       "Escala al usuario." % (nombre, os.path.dirname(tr), carpeta))
    cfg = retomar_mod.config(tr)
    modelo = entry.get("modelo") or cfg.get("modelo")
    esfuerzo = entry.get("esfuerzo") or cfg.get("esfuerzo")
    permisos = entry.get("permisos") or cfg.get("permisos")
    faltan = [k for k, v in (("modelo", modelo), ("esfuerzo", esfuerzo), ("modo de permisos", permisos)) if not v]
    if faltan:
        return False, ("NO: no leo %s de %s en su registro ni en su transcript. No lo retomo cambiándolo en silencio: "
                       "pregúntale al usuario." % (", ".join(faltan), nombre))
    pane, tab = entry.get("pane_id"), entry.get("tab_id", "")
    found, info = herdr_cli.pane_get(pane) if pane else (False, None)
    if found is None:
        return False, "NO: no pude preguntarle a herdr por el pane %s. Repite en un momento." % pane
    if found:
        other = ((herdr_cli.agent_get(pane) or {}).get("agent_session") or {}).get("value")
        if other:
            return False, "NO: el pane %s ya tiene otra sesión (%s). No arranco encima." % (pane, other[:8])
        aqui = info.get("foreground_cwd") or info.get("cwd") or ""
        if carpeta and aqui and aqui.rstrip("/") != carpeta.rstrip("/"):
            return False, ("NO: el pane %s está en %s y la sesión de %s es de %s; --resume no la encontraría ahí. "
                           "Teclea en ese pane `cd %s` (o ciérralo) y repite." % (pane, aqui, nombre, carpeta, carpeta))
    else:
        res = herdr_cli.run_json(["workspace", "create", "--cwd", carpeta, "--label", nombre, "--no-focus"], timeout=30)
        root = (res or {}).get("root_pane") or (res or {}).get("pane") or {}
        pane = root.get("pane_id")
        if not pane:
            return False, "NO: su pane ya no existe y herdr workspace create falló para %s." % carpeta
        tab = ((res or {}).get("tab") or {}).get("tab_id") or root.get("tab_id") or ""
        if tab and entry.get("pestana"):
            herdr_cli.run(["tab", "rename", tab, entry["pestana"]])
        log("su pane ya no existe: pestaña nueva en %s, pane %s" % (carpeta, pane))
    n = int(entry.get("retomado_n") or 0) + 1
    nombre_herdr = lote.unique_name(entry.get("herdr_name") or nombre)
    reg = registry.load(project_id)
    e = reg["agents"][sid]
    e.update(pane_id=pane, tab_id=tab, herdr_name=nombre_herdr, retomado_n=n, retomado_ts=time.time(),
             modelo=modelo, esfuerzo=esfuerzo, permisos=permisos, tarea_estado="retomando")
    registry.save(project_id, reg)
    if not lookout_state.read_marker(sid):
        lookout_state.write_marker(sid, {"project_id": project_id, "nombre": nombre, "display": nombre + " (lookout)"})
    trigger = TRIGGER % (time.strftime("%H:%M", time.localtime(end.get("ts") or time.time())), end.get("razon") or "?")
    ok, msg = lote.arranca(project_id, sid, pane, carpeta, nombre_herdr, entry.get("prompt_sistema") or "", modelo,
                           lote.solo_lectura(entry), "retoma:%s:%d" % (sid[:8], n), trigger, confirmar, log,
                           lote.puerto_de(entry) if entry.get("tarea") or entry.get("clave_puerto") else None,
                           esfuerzo, permisos, resume=True)
    if (registry.load(project_id)["agents"].get(sid) or {}).get("tarea_estado") == "fallida":
        # not «fallida»: that one `lookout pendientes` would launch again as a new agent (lote.retryable), while the
        # digest still asks to resume this one
        lote.set_estado(project_id, sid, "retoma-fallida", msg)
    return ok, ("retoma %d de %s: %s" % (n, nombre, msg))

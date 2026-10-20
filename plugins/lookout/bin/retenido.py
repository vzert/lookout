"""0.13.39 (p-c1cb6123e4): the supervisor reacts to a message of its own that another session held.

0.13.33 matches an agent's permission mode only when it registers it. An agent moved to bypass later (or one whose
footer could not be read then) holds every message of the supervisor until the user approves it, and Claude Code drops
it when the dialog stays unanswered. The sender gets a [Cross-session delivery notice] as a prompt of its own session,
which fires its UserPromptSubmit (measured 2026-10-19 in the 0.13.33 bench):
  «… Your message to another session was held by that session (recipient: uds:/tmp/cc-socks/<pid>.sock; msg_id: <id>)…»
  «… Your message to another session was denied by the recipient user (recipient: …; msg_id: …)…»
«Another notice follows on release, denial or expiry»: only the first two texts were seen; any other one is read by the
same shape, and one that says «expir» counts as dropped (not measured).

The recipient is found by its socket (sesiones.por_socket). With no dialog on its screen and the agent in bypass while
the supervisor prompts, it is moved with Shift+Tab as at registration (modo.baja); with the hold dialog on screen
nothing is pressed (a key there picks Deny or Deliver). One `retenido` event per notice tells the supervisor what to do.
"""
import fcntl
import os
import re

import lookout_state

AVISO = "[Cross-session delivery notice]"
# adversary r1: «was» optional, the expiry text was not seen
FORMA = re.compile(r"^\[Cross-session delivery notice\] Your message to another session (?:was |has )?(.+?) "
                   r"\(recipient: ([^;()]+); msg_id: ([^)\s;]+)\)")
VISTOS_MAX = 200


def es_aviso(prompt):
    return str(prompt or "").lstrip().startswith(AVISO)


def lee(prompt):
    """{estado, socket, msg_id, que} of a delivery notice, or None. estado: retenido, negado, caducado, liberado, or
    desconocido (adversary r2: a wording never seen is never taken for a delivery)."""
    m = FORMA.match(str(prompt or "").lstrip())
    if not m:
        return None
    que = m.group(1).lower()
    estado = ("caducado" if "expir" in que else "negado" if "denied" in que else
              "retenido" if que.startswith("held") else
              # codex r3: affirmative only («release failed», «not released» are not)
              "liberado" if re.match(r"(released|delivered)\b", que) and not re.search(r"\b(not|never|fail|un)", que) else
              "desconocido")
    return {"estado": estado, "socket": m.group(2).strip(), "msg_id": m.group(3), "que": " ".join(que.split())[:80]}


def _lock(project_id):
    os.makedirs(lookout_state.project_dir(project_id), exist_ok=True)
    fd = os.open(os.path.join(lookout_state.project_dir(project_id), "retenido.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _nuevo(project_id, clave):
    """True the first time this notice is seen (Claude Code may hand the same notice twice)."""
    path = os.path.join(lookout_state.project_dir(project_id), "retenidos.json")
    vistos = lookout_state.read_json(path) or []
    if clave in vistos:
        return False
    lookout_state.write_json(path, (vistos + [clave])[-VISTOS_MAX:])
    return True


def _agente(project_id, session_id):
    """The registered (or queued) agent of this project with that session, or None."""
    import registry
    reg = registry.load(project_id)
    e = (reg.get("agents") or {}).get(session_id)
    if e and (e.get("retirado") or e.get("tarea_estado") in ("relevada", "relevando", "fallida")):
        return None  # codex r1: its pane may be another session's by now
    if e:
        return {"nombre": e.get("nombre", ""), "pane": e.get("pane_id", ""), "status": e.get("status", "")}
    for c in reg.get("espera_cupo") or []:
        if c.get("session_id") == session_id:
            return {"nombre": "", "pane": c.get("pane_id", ""), "pestana": c.get("pestana", ""), "cola": True}
    return None


def mensaje(project_id, msg_id):
    """The full text the supervisor sent with that msg_id (on_supervisor logs it), or None: what `lookout reenvia`
    prints, so a resend is the original and never the digest's 120-character cut (codex r1)."""
    import supervisor_md
    for x in reversed(supervisor_md.read_log(project_id)):
        if x.get("tipo") == "respuesta" and x.get("msg_id") == msg_id:
            return x.get("mensaje") if x.get("mensaje") is not None else x.get("texto", "")
    return None


RECIENTE_S = 15 * 60  # a hold lasts 5 min by default (dialogExpiry): a lowering older than this explains no hold


def _enviado(project_id, msg_id):
    """When the supervisor sent that message (its log entry), or None."""
    import supervisor_md
    for x in reversed(supervisor_md.read_log(project_id)):
        if x.get("tipo") == "respuesta" and x.get("msg_id") == msg_id:
            return float(x.get("ts") or 0) or None
    return None


def _bajado_antes(project_id, session_id, now=None, enviado=None):
    """The `modo` of a recent notice that lowered this same recipient (codex r1: held lowers it, and the denied that
    follows finds the classes equal; codex r2: also for another message held before the lowering). That is no «holds
    every message»."""
    import time
    now = time.time() if now is None else now
    for ev in reversed(lookout_state.read_events(project_id, 0)[0]):
        if now - float(ev.get("ts") or 0) > RECIENTE_S:
            break
        # codex r3: only a real Shift+Tab, never a reused one (it would push the 15 min on and on)
        if (ev.get("event") == "retenido" and ev.get("destino") == session_id
                and (ev.get("modo") or {}).get("estado") == "bajado" and not ev["modo"].get("antes")):
            # codex r4: it explains only a message sent before that Shift+Tab (one sent after was held anyway)
            # codex r5: the time taken before the first press, not the event's (written after the presses)
            corte = float(ev["modo"].get("desde") or ev.get("ts") or 0)
            return ev["modo"] if enviado is not None and enviado <= corte else None
    return None


def _pane_suyo(pane, session_id):
    """codex r1: the registry's pane is pressed only if herdr shows THIS session on it now."""
    import herdr_cli
    vivo = herdr_cli.agent_get(pane) if pane else None
    return bool(vivo) and (vivo.get("agent_session") or {}).get("value") == session_id


def _modo(project_id, session_id, ag, msg_id):
    """What could be done about the mode now: {estado, agente, supervisor[, ahora]}. estado: bajado, sin-bajar,
    dialogo (bypass, but a dialog is on its screen: nothing pressed), sin-pane (herdr does not show it on its pane:
    nothing pressed), iguales (same class: it holds every message), supervisor-bypass, or desconocido."""
    import modo
    sup = modo.del_supervisor(project_id)
    suyo = _pane_suyo(ag.get("pane"), session_id)
    pie = modo.leer_pie(ag["pane"]) if suyo else ""
    # codex r3: only while the supervisor still prompts (a switch to bypass since makes them differ again)
    antes = (_bajado_antes(project_id, session_id, enviado=_enviado(project_id, msg_id))
             if modo.clase(sup) == "permisos" else None)
    if antes and not pie:  # adversary r2: lowered minutes ago and no footer to read now (a dialog): still lowered
        return dict(antes, antes=True)
    actual = pie or modo.de_sesion(session_id)
    cs, ca = modo.clase(sup), modo.clase(actual)
    r = {"agente": actual, "supervisor": sup}
    if not cs:
        r["estado"] = "desconocido"
    elif not ca:
        r["estado"] = "desconocido" if suyo else "sin-pane"
    elif cs == ca:
        r = dict(antes, antes=True) if antes else dict(r, estado="iguales")
    elif cs == "bypass":
        r["estado"] = "supervisor-bypass"
    elif not suyo:
        r["estado"] = "sin-pane"
    elif not pie or ag.get("status") == "blocked":
        r["estado"] = "dialogo"
    else:
        import time
        r["desde"] = time.time()
        ahora = modo.baja(ag["pane"])
        r["estado"] = "bajado" if ahora else "sin-bajar"
        if ahora:
            r["ahora"] = ahora
            if not ag.get("cola"):
                modo.guarda(project_id, session_id, ahora)
    return r


def reacciona(project_id, prompt):
    """Called from the supervisor's UserPromptSubmit. True when `prompt` is a delivery notice (handled or not): it is
    never the user's answer in the chat. Appends one `retenido` event per new notice of a known shape."""
    if not es_aviso(prompt):
        return False
    a = lee(prompt)
    if not a:
        return True
    import sesiones
    fd = _lock(project_id)  # held and denied arrive 200 ms apart: one Shift+Tab sequence at a time
    try:
        if not _nuevo(project_id, "%s:%s" % (a["msg_id"], a["estado"])):
            return True
        s = sesiones.por_socket(a["socket"])
        ag = _agente(project_id, s["session_id"]) if s else None
        ev = {"event": "retenido", "estado": a["estado"], "msg_id": a["msg_id"], "socket": a["socket"],
              # codex r6: the recipient goes in `destino`, never in `session_id`: every reader of an agent's last event
              # (deliver.NO_DEL_AGENTE, aprueba, salida, retoma…) would take this notice for the agent's own
              "session_id": "", "destino": (s or {}).get("session_id", ""), "to": (s or {}).get("name", ""),
              "nombre": (ag or {}).get("nombre", ""), "pane": (ag or {}).get("pane", ""),
              "pestana": (ag or {}).get("pestana", ""), "hook": "aviso", "proyecto": project_id, "que": a["que"]}
        m = mensaje(project_id, a["msg_id"])
        if m is not None:
            ev["texto"] = m[:200]  # only to tell which one it was; `lookout reenvia` prints it whole
        if ag:
            ev["modo"] = _modo(project_id, s["session_id"], ag, a["msg_id"])
        lookout_state.append_event(project_id, ev)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    return True


def describe(ev, head):
    """The digest line: what to do first (the digest clips at 160), then who it is."""
    import supervisor_md
    r = ev.get("modo") or {}
    st = r.get("estado", "")
    to = ev.get("to") or ""
    quien = "to=%s" % to if to else "la sesión de %s" % (ev.get("socket") or "?")
    donde = "«%s»" % (ev.get("pestana") or ev.get("nombre") or to or ev.get("pane") or "?")
    if not r:
        modo_txt = "no es un agente registrado de este proyecto"
    elif st == "bajado":
        modo_txt = "ya bajé su modo %s→%s con Shift+Tab%s" % (r.get("agente"), r.get("ahora"),
                                                             " al retenerse" if r.get("antes") else "")
    elif st == "iguales":
        modo_txt = "mismo modo que tú: su sesión retiene todo mensaje (crossSessionInbound)"
    elif st == "supervisor-bypass":
        modo_txt = "MODO DISTINTO (tú bypass, él %s): no lo subo" % (r.get("agente") or "?")
    elif st == "sin-pane":
        modo_txt = "no veo su pane en herdr: no pulso nada (él %s, tú %s)" % (r.get("agente") or "?",
                                                                              r.get("supervisor") or "?")
    elif st in ("dialogo", "sin-bajar"):
        modo_txt = "MODO DISTINTO (él %s, tú %s): %s" % (
            r.get("agente") or "?", r.get("supervisor") or "?",
            "con el diálogo en pantalla no pulso nada" if st == "dialogo" else "no bajó")
    else:
        modo_txt = "no leo su modo"
    salir = "pulse Shift+Tab hasta un modo que no sea bypass ni plan"  # codex r1: plan comes after bypass
    if ev.get("texto") is not None:
        reenvio = "`lookout reenvia %s %s` y SendMessage %s con ese texto tal cual («%s»)" % (
            ev.get("proyecto") or "<proyecto>", ev.get("msg_id"), quien, supervisor_md.one_line(ev["texto"], 60))
    else:
        reenvio = "SendMessage %s con el mismo mensaje (lookout no lo tiene: msg_id %s)" % (quien, ev.get("msg_id"))
    # the way out of bypass only when it is known to bypass (a sin-pane with no mode read is not)
    fuera = st in ("dialogo", "sin-bajar") or (st == "sin-pane" and r.get("agente") == "bypassPermissions")
    if ev.get("estado") == "retenido":
        pide = "dile al usuario que lo apruebe en %s" % donde
        if fuera:
            pide += " y " + salir
        return "%s RETENIDO tu mensaje a %s → %s · %s" % (head, quien, pide, modo_txt)
    if ev.get("estado") in ("negado", "caducado"):
        que = "NEGADO" if ev["estado"] == "negado" else "CADUCADO"
        if st == "bajado":
            return "%s %s → reenvía: %s · %s" % (head, que, reenvio, modo_txt)
        if st == "iguales":
            return "%s %s → díselo al usuario antes de reenviar (%s) · %s" % (head, que, reenvio, modo_txt)
        if fuera:
            return "%s %s → dile al usuario que en %s %s; luego reenvía: %s · %s" % (
                head, que, donde, salir, reenvio, modo_txt)
        return "%s %s → díselo al usuario; luego reenvía: %s · %s" % (head, que, reenvio, modo_txt)
    if ev.get("estado") == "liberado":
        return "%s ENTREGADO tras retenerlo, a %s → nada que reenviar · %s" % (head, quien, modo_txt)
    return "%s AVISO DE ENTREGA sin leer («%s») → no sé si llegó: pregúntale a %s si lo recibió y, si no, reenvía: %s · %s" % (
        head, ev.get("que") or "?", quien, reenvio, modo_txt)

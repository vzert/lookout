"""Short digest for the supervisor (docs/plan.md 3.7 step 7): read this, not the screen.

Prints the agents table (registry + last event per agent) and the events not handled yet,
then advances the project's cursor so the same event is never answered twice, whether it
arrived through SendMessage, the waiter, or both.
"""
import os
import signal
import time

import lookout_state
import registry

# `pausa` (provider limit) does not wake: it is not something to answer (Fase 6). `fallo` neither: only its 3rd repeat.
WAKE_TYPES = "ask,blocked,negado,idle,bg_wait,unknown,crossrepo,end,repite,sin_progreso,largo"
ESTADO = {
    "working": "trabajando",
    "ask": "pregunta",
    "blocked": "espera permiso",
    "negado": "auto mode le negó",
    "aprobado": "permiso aprobado por regla",
    "notification": "aviso",
    "idle": "terminó su turno",
    "bg_wait": "espera tarea de fondo",
    "unknown": "error de API",
    "crossrepo": "tocó otro proyecto",
    "end": "salió",
    "start": "arrancó",
    "fallo": "falló una herramienta",
    "repite": "repite el mismo error",
    "correccion": "recibió corrección",
    "correccion_fallida": "corrección fallida",
    "sin_progreso": "sin progreso",
    "largo": "trabaja hace mucho sin eventos",
    "pausa": "en pausa (límite del proveedor, no es falla)",
}


def cursor_path(project_id):
    return os.path.join(lookout_state.project_dir(project_id), "cursor.json")


def get_cursor(project_id):
    return int((lookout_state.read_json(cursor_path(project_id)) or {}).get("offset", 0))


def set_cursor(project_id, offset):
    lookout_state.write_json(cursor_path(project_id), {"offset": offset, "ts": time.time()})


def pidfile(project_id):
    return os.path.join(lookout_state.project_dir(project_id), "waiter.pid")


def waiter_alive(project_id):
    """pid (> 0) of the live waiter; 0 if none; -1 if one holds the flock but its pid is not readable.
    Alive = someone holds the pidfile's flock (wait_event.py)."""
    import fcntl
    try:
        fd = os.open(pidfile(project_id), os.O_RDONLY)
    except OSError:
        return 0
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            # Held, but only a complete "<pid>\n" line with pid > 0 names it: an empty or half-written
            # file (between ftruncate and write) or "0" must never reach os.kill (adversary round 3).
            data = os.read(fd, 32).decode(errors="replace")
            body = data[:-1] if data.endswith("\n") else ""
            return int(body) if body.isdigit() and int(body) > 0 else -1
        fcntl.flock(fd, fcntl.LOCK_UN)
        return 0
    finally:
        os.close(fd)


def hhmmss(ts):
    return time.strftime("%H:%M:%S", time.localtime(ts or 0))


def describe(ev, quien=None):
    """One line per event. `quien`: session_id -> how to name the agent to the user (its herdr tab, registry.quien)."""
    kind = ev.get("event", "")
    who = (quien or {}).get(ev.get("session_id")) or ev.get("nombre") or ev.get("session_id", "")[:8]
    head = "%s %s %s" % (hhmmss(ev.get("ts")), who, ESTADO.get(kind, kind))
    if kind == "ask":
        qs = ev.get("questions") or []
        parts = ["%s [%s]" % (q.get("question", ""), " | ".join(q.get("options", []))) for q in qs]
        return head + ": " + " ; ".join(parts)
    if kind == "blocked":
        return head + ": %s %s" % (ev.get("tool_name", ""), ev.get("detalle", "")) + (
            " (%s)" % ev["motivo"] if ev.get("motivo") else "")
    if kind == "negado":
        return head + ": %s %s %s" % (ev.get("tool_name", ""), ev.get("detalle", ""), ev.get("motivo", ""))
    if kind == "aprobado":
        return head + ": %s %s" % (ev.get("tool_name", ""), ev.get("detalle", ""))
    if kind == "bg_wait":
        cmds = [t.get("command") or t.get("description") or t.get("type", "") for t in ev.get("tareas", [])]
        return head + ": " + "; ".join(c for c in cmds if c) + (" — " + ev.get("ultima", "") if ev.get("ultima") else "")
    if kind == "idle":
        extra = ("(ya te reportó) " if ev.get("reporto") else "") + ev.get("ultima", "")
        if ev.get("marcadores"):
            extra += " " + " ".join(ev["marcadores"])
        return head + (": " + extra if extra else "")
    if kind == "crossrepo":
        return head + ": %s %s (proyecto %s → %s)" % (
            ev.get("tool_name", ""), ev.get("file_path", ""), ev.get("desde_proyecto", ""), ev.get("proyecto_tocado", "")) + (
            " — por Bash: %s" % ev.get("detalle", "") if ev.get("via") == "bash" else "")
    if kind == "fallo":
        return head + ": %s" % ev.get("firma", "")
    if kind == "repite":
        tail = " | ".join(ev.get("intentos") or [])
        if ev.get("replantea"):
            nxt = "PARA Y REPLANTEA: ya hubo %d correcciones; no mandes otra, escala al usuario" % ev.get("correcciones", 0)
        else:
            nxt = "corrección %d de 2: `lookout corrige <proyecto> %s --resumen \"…\"`" % (
                ev.get("correcciones", 0) + 1, ev.get("nombre") or ev.get("session_id", "")[:8])
        return head + " %d veces: «%s»; intentos: %s → %s" % (ev.get("veces", 0), ev.get("firma", ""), tail, nxt)
    if kind == "correccion":
        return head + " %s de 2: %s" % (ev.get("numero", "?"), ev.get("resumen", "")) + (
            " (la anterior falló según su reporte: «%s»)" % ev["fallo_por_reporte"] if ev.get("fallo_por_reporte") else "")
    if kind == "correccion_fallida":
        return head + " la corrección %s no sirvió según su reporte: «%s»" % (ev.get("numero", "?"), ev.get("reporte", ""))
    if kind == "sin_progreso":
        accion = ("avisa al usuario (agente, desde cuándo, fuentes)" if ev.get("nivel") == "escalar"
                  else "una lectura de su pantalla")
        return head + " hace %dm (%s): %s → %s" % (ev.get("hace_s", 0) // 60, ev.get("nivel", ""),
                                                  "; ".join(ev.get("fuentes") or []), accion)
    if kind == "largo":
        return head + ": %dm sin eventos, pero vivo (herdr working, proceso vivo) → una lectura de su pantalla" % (
            ev.get("hace_s", 0) // 60)
    if kind == "pausa":
        return head + ": %s %s — espera y sigue solo; no lo relances ni lo marques fallido" % (
            ev.get("error", ""), ev.get("detalle", ""))
    if kind == "unknown":
        return head + ": " + ev.get("error", "")
    if kind == "notification":
        return head + " (%s)" % (ev.get("tipo") or "-") + (": " + ev.get("mensaje", "") if ev.get("mensaje") else "")
    if kind == "working":
        return head + (": " + ev.get("prompt", "") if ev.get("prompt") else "")
    return head


MAX_LINES = 40   # Fase 4: one digest per wake, at most 40 lines
MAX_COLS = 160   # and at most 160 characters per line (lines alone do not bound tokens)
KEEP_ALL = ("ask", "blocked", "negado", "crossrepo", "unknown", "repite", "sin_progreso", "largo", "correccion")  # events that need an answer are never collapsed
# Budget of the supervisor's own context, counted FROM what the session already held when `lookout inicia` ran
# (system prompt, tools, skills, project memory: 71k on claude-vzert, 2026-10-05). A fixed 120k left that supervisor
# 49k of work and forced a relief after 7 minutes. LOOKOUT_PRESUPUESTO (absolute tokens) still overrides.
# A model with a small window compacts before this: PreCompact rewrites supervisor.md and SessionStart[compact]
# prints the «Como retomar», so that path is covered too.
PRESUPUESTO_EXTRA = 300000
PRESUPUESTO_SIN_ARRANQUE = 370000  # when the starting size was not recorded (a lock from an older lookout)


def clip(line, n=MAX_COLS):
    line = " ".join(str(line).split())
    return line if len(line) <= n else line[:n - 1] + "…"


def context_tokens(session_id, projects_dir=None):
    """Context size of this session's last API call, from its own transcript (usage of the last assistant line):
    input + cache read + cache creation. None if unknown. Reads only the tail of the file."""
    import json
    import deliver
    path = deliver.transcript_path(session_id, projects_dir) if session_id else ""
    if not path:
        return None
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 400000))
            tail = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    for line in reversed(tail):
        if '"usage"' not in line:
            continue
        try:
            u = (json.loads(line).get("message") or {}).get("usage") or {}
        except ValueError:
            continue
        if u:
            return u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
    return None


def presupuesto_limite(project_id):
    """(limit, starting size or 0). LOOKOUT_PRESUPUESTO, when set, is the whole limit."""
    import lock
    try:
        env = int(os.environ.get("LOOKOUT_PRESUPUESTO") or 0)
    except ValueError:
        env = 0
    if env > 0:
        return env, 0
    base = int((lock.read(project_id) or {}).get("contexto_inicial") or 0)
    return (base + PRESUPUESTO_EXTRA, base) if base else (PRESUPUESTO_SIN_ARRANQUE, 0)


def presupuesto_line(project_id, session_id=None, projects_dir=None):
    import lock
    sid = session_id if session_id is not None else os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    owner = ((lock.read(project_id) or {}).get("supervisor") or {}).get("session_id")
    if not sid or sid != owner:
        return ""
    tok = context_tokens(sid, projects_dir)
    if tok is None:
        return ""
    # `inicia` may run before its session's transcript has a usage line (it lags the hooks ~1 s): then the first
    # summary records the starting size, a little higher than the true start.
    lock.set_contexto_inicial(project_id, sid, tok)
    limit, base = presupuesto_limite(project_id)
    line = "Contexto: %dk de %dk%s." % (tok // 1000, limit // 1000,
                                        " (arranque %dk + %dk)" % (base // 1000, PRESUPUESTO_EXTRA // 1000) if base else "")
    if tok >= limit:
        line += (" PRESUPUESTO SUPERADO: termina lo que tengas abierto y haz el relevo (skill, «Relevo del supervisor»): "
                 "`lookout retomar %s`." % project_id)
    return line


def waiter_owner_dead(project_id):
    """The live waiter belongs to a supervisor session that is gone (its Claude process no longer runs, or the lock now
    names another session: /clear, a relief). It exits by itself within WATCH_EVERY seconds (wait_event.watchdog)."""
    import wait_event
    owner = lookout_state.read_json(pidfile(project_id) + ".owner") or {}
    return wait_event.owner_stale(owner, os.path.join(lookout_state.project_dir(project_id), "lock.json"))


def collapse(new):
    """Events grouped per agent: the ones that need an answer stay, each one; of the rest only the last per agent,
    with how many were folded into it."""
    out, folded, last = [], {}, {}
    for i, ev in enumerate(new):
        if ev.get("event") in KEEP_ALL:
            out.append((i, ev, 0))
        else:
            key = ev.get("session_id")
            if key in last:
                folded[key] = folded.get(key, 0) + 1
                # a herdr notification never hides the agent's real last event (Fase 4 run 2: "aviso" with no text)
                if ev.get("event") == "notification" and last[key][1].get("event") != "notification":
                    continue
            last[key] = (i, ev)
    out += [(i, ev, folded.get(k, 0)) for k, (i, ev) in last.items()]
    return [(ev, n) for _i, ev, n in sorted(out, key=lambda x: x[0])]


def render(project_id, mark=True, limit=None, todo=False):
    maxl = 10 ** 6 if todo else MAX_LINES
    reg = registry.load(project_id)
    agents = reg.get("agents", {})
    quien = {s: registry.quien(e) for s, e in agents.items()}
    all_events, _ = lookout_state.read_events(project_id, 0)
    last = {}
    for ev in all_events:
        if ev.get("event") != "notification":
            last[ev.get("session_id")] = ev
    offset = get_cursor(project_id)
    new, end = lookout_state.read_events(project_id, offset)
    import heuristicas
    vivos = {s: e for s, e in agents.items() if e.get("tarea_estado") != "relevada" and (last.get(s) or {}).get("event") != "end"}
    head = ["Agentes (%d%s), por grupo: pestaña (nombre) | rama | tarea | último evento" % (
        len(vivos), ", +%d terminados" % (len(agents) - len(vivos)) if len(agents) > len(vivos) else "")]
    now = time.time()
    by_group = {}
    for sid, e in vivos.items():
        by_group.setdefault(heuristicas.grupo(all_events, sid, e), []).append((sid, e))
    for g in heuristicas.GRUPOS:
        if not by_group.get(g):
            continue
        head.append("%s:" % heuristicas.TITULO[g])
        for sid, e in by_group[g]:
            ev = last.get(sid)
            estado = ("%s %s" % (ESTADO.get(ev.get("event"), ev.get("event")), hhmmss(ev.get("ts")))) if ev else "sin eventos"
            beat = heuristicas.ultimo_real(all_events, sid)
            if beat and beat.get("event") in heuristicas.EN_TURNO:
                estado += " (sin eventos hace %ds)" % int(now - float(beat.get("ts") or now))
            head.append(clip("  %s | %s | %s | %s" % (registry.quien(e), e.get("branch") or "-", e.get("tarea") or "-", estado)))
    import decisiones
    import publica
    tail = []
    dec = decisiones.render(project_id)
    if dec:
        dl = dec.splitlines()
        if not todo and len(dl) > 6:
            dl = dl[:6] + ["(+%d decisiones más: `lookout decision %s`)" % (len(dl) - 6, project_id)]
        tail += [clip(x) for x in dl]
    if any(p["estado"] in ("esperando", "turno", "lista") for p in publica.load(project_id)["cola"]):
        tail += [clip(x) for x in publica.render_cola(project_id).splitlines()]
    pid = waiter_alive(project_id)
    if pid and waiter_owner_dead(project_id):
        tail.append("Waiter: el que hay es de una sesión que ya no supervisa; se cierra solo en ≤10 s. Al terminar este "
                    "turno lanza `lookout espera %s` con run_in_background: espera a que se cierre y toma su lugar." % project_id)
    elif pid:
        tail.append("Waiter: vivo (pid %d). No lances otro." % pid)
    else:
        tail.append("Waiter: no hay. Al terminar este turno lanza `lookout espera %s` con run_in_background." % project_id)
    pres = presupuesto_line(project_id)
    if pres:
        tail.append(clip(pres, 400))
    room = maxl - len(head) - len(tail) - 2
    if len(head) - 1 > max(3, room // 2):  # many agents: keep the table from eating the events
        keep = max(3, room // 2)
        hidden = sum(1 for x in head[1 + keep:] if x.startswith("  "))
        head = head[:1 + keep] + ["(+%d agentes más: `lookout resumen %s --todo`)" % (hidden, project_id)]
        room = maxl - len(head) - len(tail) - 2
    body = []
    if new:
        items = [(ev, 0) for ev in new] if todo else collapse(new)
        cap = max(1, room - 2)  # its header line and the "+N más" line
        if limit:
            cap = min(cap, limit)
        shown = items[-cap:]
        body.append("Eventos nuevos (%d%s):" % (len(new), "; agrupados por agente, %d líneas" % len(shown) if len(shown) < len(new) else ""))
        for ev, n in shown:
            body.append(clip("- " + describe(ev, quien) + (" (+%d antes)" % n if n else "")))
        if len(items) > len(shown):
            body.append("(+%d eventos más antiguos sin mostrar: `lookout resumen %s --todo`)" % (len(items) - len(shown), project_id))
    else:
        body.append("Eventos nuevos: ninguno (ya atendidos).")
    if mark:
        set_cursor(project_id, end)
        try:
            import supervisor_md
            supervisor_md.write(project_id)
        except Exception:
            pass
    lines = head + [""] + body + [""] + tail
    return "\n".join(lines[:maxl])

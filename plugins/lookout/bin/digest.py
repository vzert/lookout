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
import sesiones

# `pausa` (provider limit) does not wake: it is not something to answer (Fase 6). `fallo` neither: only its 3rd repeat.
# 0.12.2: `bg_wait` wakes only when its turn asked something (`pregunta`, wait_event): 19 of 36 wakes in 3-tier-memory
# (2026-10-15) were background waits with nothing to answer. One that waits too long wakes as `largo` (heuristicas.revisa).
WAKE_TYPES = "ask,blocked,negado,idle,bg_wait,unknown,crossrepo,end,repite,sin_progreso,largo,retomar,nuevo"
ESTADO = {
    "working": "trabajando",
    "ask": "pregunta",
    "blocked": "espera permiso",
    "negado": "auto mode le negó",
    "aprobado": "permiso aprobado por regla",
    "notification": "aviso",
    "idle": "terminó su turno",
    "retomar": "estaba quieto con un «Como retomar»",
    "nuevo": "agente nuevo (lanzado a mano), ya registrado",
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


def ventana_s():
    """Seconds the waiter waits after its first event so a burst wakes the supervisor once (0.12.2)."""
    try:
        return max(0.0, float(os.environ.get("LOOKOUT_VENTANA") or 3))
    except ValueError:
        return 3.0


DESPERTAR_VIGENTE = 60  # s: how long a waiter's queued notification keeps the Stop reminder quiet (B1)


def despertar_path(project_id):
    return os.path.join(lookout_state.project_dir(project_id), "despertar.json")


def marca_despertar(project_id, session_id):
    lookout_state.write_json(despertar_path(project_id), {"ts": time.time(), "session_id": session_id})


def despertar_en_cola(project_id, session_id, transcript_path, now=None):
    """B1 (0.12.2): a waiter of this session woke less than DESPERTAR_VIGENTE s ago and the session has not seen it yet
    (no task notification nor waiter output in its transcript after that moment): the notification is queued and will
    open the next turn, where the supervisor relaunches the waiter. 5 of 5 Stop reminders in 3-tier-memory came then,
    and 2 of them led to a second waiter that died with «waiter ya vivo». Unsure (no transcript, unreadable) -> False:
    the reminder goes out as before."""
    import json
    now = time.time() if now is None else now
    d = lookout_state.read_json(despertar_path(project_id)) or {}
    ts = float(d.get("ts") or 0)
    if not ts or d.get("session_id") != session_id or not 0 <= now - ts < DESPERTAR_VIGENTE or not transcript_path:
        return False
    try:
        with open(transcript_path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 300000))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return False
    import calendar
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        stamp = str(row.get("timestamp") or "")
        try:
            t = calendar.timegm(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")) + float("0" + stamp[19:23].rstrip("Z"))
        except ValueError:
            continue
        if t < ts - 1:
            return True   # back past the wake with nothing that delivered it
        if "<task-notification>" in line or "Resumen (ya marcado como atendido" in line:
            return False  # it reached the session: the usual reminder applies
    return False


def cursor_path(project_id):
    return os.path.join(lookout_state.project_dir(project_id), "cursor.json")


def get_cursor(project_id):
    return int((lookout_state.read_json(cursor_path(project_id)) or {}).get("offset", 0))


RECORTADOS_MAX = 200


def ev_key(ev):
    return (ev.get("session_id"), ev.get("ts"), ev.get("event"), ev.get("hook"))


def olvida_vistos(project_id):
    """After a compaction the supervisor no longer holds the last table: the next wake prints everything again."""
    cur = lookout_state.read_json(cursor_path(project_id))
    if cur and cur.pop("vistos", None) is not None:
        lookout_state.write_json(cursor_path(project_id), cur)


def set_cursor(project_id, offset, desde=None, recortados=None, vistos=None):
    """`desde`: where the events the waiter printed (and marked) start. The waiter prints the digest into its output
    file; a supervisor that answers its notification with `lookout resumen` instead of reading that file would get
    "ninguno" and lose what woke it. So the next `resumen` shows them once more, from `desde`; the waiter itself
    resumes from `offset` and never repeats them."""
    data = {"offset": offset, "ts": time.time()}
    if desde is not None:
        data["desde"] = desde
    if recortados:
        # Fase 9 E10: events a `resumen` cut for room are not "attended": they come back in the next one
        data["recortados"] = recortados[-RECORTADOS_MAX:]
    if vistos:
        data["vistos"] = vistos  # 0.12.2: what the last waiter wake printed, to print only what changed
    lookout_state.write_json(cursor_path(project_id), data)


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
    """Fase 9 E2: with the date when it is not today ("terminó 20:56:23" was from the day before)."""
    t = time.localtime(ts or 0)
    return time.strftime("%H:%M:%S" if t[:3] == time.localtime()[:3] else "%d-%m %H:%M:%S", t)


def espera_pane_txt(ev):
    """0.13.7: the user answers in your modal and you type it; the user never goes to the agent's pane."""
    p = ev.get("espera_pane")
    if not p:
        return ""
    return ("ESPERA ALGO TECLEADO EN SU PANE (%s): «%s» → al modal con dN, --agentes y --si-es; con su sí, "
            "`lookout envia <proyecto> <agente> --usuario-confirmo dN --texto \"<texto>\"`. " % (p.get("motivo"), p.get("cita")))


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
        # 0.12.2: the description first; a command is often a long scratchpad path
        cmds = [t.get("description") or t.get("command") or t.get("type", "") for t in ev.get("tareas", [])]
        return head + ": " + espera_pane_txt(ev) + "; ".join(c for c in cmds if c) + (
            " — " + ev.get("ultima", "") if ev.get("ultima") else "")
    if kind == "nuevo":  # 0.13.0 (Fase 3); 0.13.1: the alta renamed it itself, or says why not
        r = ev.get("renombre") or ""
        ren = ("renombrado" if r == "hecho" else "renombrado " + r if r.startswith("a medias") else
               "sin renombrar (%s)" % r if r else "")
        import modo
        m = modo.describe(ev.get("modo"))  # 0.13.33
        return head + ": %s%s%spestaña «%s», %s → `lookout entrega` para darle su nota" % (
            "le tocó su turno del cupo; " if ev.get("desde_cola") else "",  # 0.13.34
            m + "; " if m else "", ren + ", " if ren else "", ev.get("pestana") or "-", ev.get("estado_herdr") or "sin estado")
    if kind == "espera_cupo":  # 0.13.34: not registered, so it has no name yet: its tab or pane
        return "%s %s: espera turno (cupo de %s lleno); sigue en su pane sin supervisor, díselo al usuario" % (hhmmss(ev.get("ts")), ev.get("pestana") or ev.get("pane") or
                                                          ev.get("session_id", "")[:8], ev.get("cupo") or registry.cupo())
    if kind == "retomar":  # 0.13.0: registered while already idle, with a «Como retomar» in its last turn
        import retomar
        return head + ": " + retomar.describe(ev.get("retomar"))
    if kind == "idle":
        if ev.get("retomar"):
            import retomar
            extra = ("(ya te reportó) " if ev.get("reporto") else "") + retomar.describe(ev["retomar"])
        else:
            extra = ("(ya te reportó) " if ev.get("reporto") else "") + ev.get("ultima", "")
        extra = espera_pane_txt(ev) + extra
        if ev.get("marcadores"):
            extra += " " + " ".join(ev["marcadores"])
        for b in ev.get("bloqueos_hook") or []:  # Fase 9 E8: a plugin's hook, not the user
            extra += " [bloqueo de un hook en %s, no del usuario: %s]" % (b.get("tool"), b.get("motivo"))
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
    if kind == "largo" and ev.get("fondo"):
        tareas = ev.get("tareas") or []
        if not tareas:
            return head + ": %dm esperando su tarea de fondo → una lectura de su pantalla" % (ev.get("hace_s", 0) // 60)
        # 0.13.8: what it waits on and who may stop it; lookout never kills a process
        res = [t.get("reservada") for t in tareas if t.get("reservada")]
        accion = ("es algo reservado al usuario (%s): pregunta al usuario si la para" % "; ".join(res) if res else
                  "pídele por SendMessage (%s) que diga si aún la necesita y, si no, que la pare con TaskStop"
                  % sesiones.to_texto(ev))  # 0.13.35 (p-561f1a2173): its real to, not its tab's name
        return head + ": %dh%02dm esperando su tarea de fondo «%s» → %s" % (
            ev.get("hace_s", 0) // 3600, ev.get("hace_s", 0) // 60 % 60,
            " | ".join(" ".join((t.get("description") or t.get("command") or "")[:120].split()) for t in tareas), accion)
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
# 0.13.0: that limit ignored the model's window. A 1M Opus supervisor on 3-tier-memory read «382k de 370k ...
# PRESUPUESTO SUPERADO» six times and asked for a relief it did not need (2026-10-15, p-3268dded6f). With the window
# known (the transcript's model line: «claude-opus-5-5[1m]»), the limit is VENTANA_USO of it when that is above the
# fixed one; a 200k window keeps the fixed limit, since it compacts before reaching it (see above).
VENTANA_USO = 0.8
VENTANA_1M = 1000000
VENTANA_BASE = 200000


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


def ventana_modelo(session_id, projects_dir=None):
    """Context window of the session's model, from the last model line Claude Code writes in its transcript
    (attachment type "model": modelId «claude-opus-5-5[1m]», marketingName «Opus 5.5 (1M context)»). A /model switch
    writes a new one, so the last one counts. None if there is none."""
    import json
    import deliver
    path = deliver.transcript_path(session_id, projects_dir) if session_id else ""
    if not path:
        return None
    ident = None
    try:
        with open(path, "rb") as fh:
            for raw in fh:
                if b'"identity"' not in raw or b'"attachment"' not in raw:
                    continue
                try:
                    att = json.loads(raw).get("attachment") or {}
                except ValueError:
                    continue
                if att.get("type") == "model" and isinstance(att.get("identity"), dict):
                    ident = att["identity"]
    except OSError:
        return None
    if not isinstance(ident, dict) or not (ident.get("modelId") or ident.get("marketingName")):
        return None
    uno_m = str(ident.get("modelId", "")).lower().endswith("[1m]") or "1m context" in str(ident.get("marketingName", "")).lower()
    return VENTANA_1M if uno_m else VENTANA_BASE


def presupuesto_limite(project_id, ventana=None):
    """(limit, starting size or 0). LOOKOUT_PRESUPUESTO, when set, is the whole limit. With the model's window known,
    the limit is never below VENTANA_USO of it."""
    import lock
    try:
        env = int(os.environ.get("LOOKOUT_PRESUPUESTO") or 0)
    except ValueError:
        env = 0
    if env > 0:
        return env, 0
    base = int((lock.read(project_id) or {}).get("contexto_inicial") or 0)
    limit, base = (base + PRESUPUESTO_EXTRA, base) if base else (PRESUPUESTO_SIN_ARRANQUE, 0)
    if ventana and int(ventana * VENTANA_USO) > limit:
        return int(ventana * VENTANA_USO), 0
    return limit, base


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
    ventana = ventana_modelo(sid, projects_dir)
    limit, base = presupuesto_limite(project_id, ventana)
    if base:
        detalle = " (arranque %dk + %dk)" % (base // 1000, PRESUPUESTO_EXTRA // 1000)
    elif ventana and not os.environ.get("LOOKOUT_PRESUPUESTO"):
        detalle = " (%d %% de la ventana de %dk)" % (round(VENTANA_USO * 100), ventana // 1000)
    else:
        detalle = ""
    line = "Contexto: %dk de %dk%s." % (tok // 1000, limit // 1000, detalle)
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


def es_eco(ev):
    """N4 (0.12.2): lines that are not news to the supervisor: the agent's turn opened by a message (the supervisor's
    own SendMessage, a peer's) or by a task notification, and herdr's «idle_prompt» notice. 35 of 106 event lines in
    3-tier-memory. The agent's real next event (its end of turn, its question) still shows."""
    if ev.get("event") == "working":
        return (ev.get("prompt") or "").lstrip().startswith(("<cross-session-message", "<task-notification"))
    return ev.get("event") == "notification" and ev.get("tipo") == "idle_prompt"


def clave(obj):
    import hashlib
    import json
    return hashlib.sha1(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


CONTEXTO_DESDE = 0.6


def contexto_alto(project_id, line):
    """Is the session at or over CONTEXTO_DESDE of its budget? Read from the line itself («Contexto: Nk de Lk»)."""
    import re
    m = re.match(r"Contexto: (\d+)k de (\d+)k", line)
    return not m or int(m.group(2)) <= 0 or int(m.group(1)) >= CONTEXTO_DESDE * int(m.group(2))


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


def render(project_id, mark=True, limit=None, todo=False, por_waiter=False):
    maxl = 10 ** 6 if todo else MAX_LINES
    reg = registry.load(project_id)
    agents = reg.get("agents", {})
    quien = {s: registry.quien(e) for s, e in agents.items()}
    all_events, _ = lookout_state.read_events(project_id, 0)
    last, last_estado = {}, {}
    import heuristicas
    last_se = {}  # 0.13.20: its last start/end, what retoma.salio_solo reads (as heuristicas.grupo does)
    for ev in all_events:
        if ev.get("event") != "notification":
            last[ev.get("session_id")] = ev
        if ev.get("event") in ("start", "end"):
            last_se[ev.get("session_id")] = ev
        if ev.get("event") not in heuristicas.NO_ESTADO:  # the event grupo() reads (0.13.3: the block's row)
            last_estado[ev.get("session_id")] = ev
    cur = lookout_state.read_json(cursor_path(project_id)) or {}
    offset = int(cur.get("offset", 0))
    desde = cur.get("desde")
    if por_waiter:
        # B3 (0.12.2): only THIS wake is shown again by the next `resumen`. With min(desde, offset) the mark never moved
        # between wakes, and the first `resumen` after 36 of them repeated 158 events the waiters had already shown.
        desde = offset
    elif desde is not None:
        offset = min(int(desde), offset)                            # what the waiter showed, once more
    new, end = lookout_state.read_events(project_id, offset)
    vistos = {ev_key(ev) for ev in new}
    new = [ev for ev in cur.get("recortados") or [] if ev_key(ev) not in vistos] + new
    ecos = [ev for ev in new if es_eco(ev)]
    new = [ev for ev in new if not es_eco(ev)]
    import heuristicas
    import retoma  # 0.13.20: an agent whose session ended without anyone asking stays, with `lookout retoma`
    # 0.13.4: a failed relief ended the session and started none; it stays until the relief is repeated or it is closed
    # and the session it tried to start is no agent (a ghost row «x~3b9909 | sin eventos»)
    vivos = {s: e for s, e in agents.items() if e.get("tarea_estado") != "relevada" and not e.get("retirado")
             and not (e.get("relevo_de") and e.get("tarea_estado") == "fallida" and s not in last)
             and ((last.get(s) or {}).get("event") != "end" or e.get("tarea_estado") == "relevo-fallido"
                  or retoma.salio_solo(last_se.get(s), e))}
    head = ["Agentes (%d%s), por grupo: pestaña (nombre) | rama | tarea | último evento" % (
        len(vivos), ", +%d terminados" % (len(agents) - len(vivos)) if len(agents) > len(vivos) else "")]
    cola = reg.get("espera_cupo") or []
    if cola:  # 0.13.34
        # codex r4: no count of its own (the table's rows are not the slots): a queue means the last pass found it full
        head.insert(0, "CUPO: %d, lleno en la última pasada · %d esperan turno (%s), sin supervisor hasta que se libere "
                       "un hueco" % (registry.cupo(), len(cola), ", ".join(x.get("pestana") or x.get("pane_id") or
                                                                         x["session_id"][:8] for x in cola)))
    now = time.time()
    revisiones = heuristicas.ultimas_revisiones(project_id)
    by_group = {}
    tabla_clave = []
    filas_bloque = []
    import decisiones
    decs = decisiones.load(project_id).get("items")
    for sid, e in vivos.items():
        by_group.setdefault(heuristicas.grupo(all_events, sid, e, decs), []).append((sid, e))
    for g in heuristicas.GRUPOS:
        if not by_group.get(g):
            continue
        head.append("%s:" % heuristicas.TITULO[g])
        for sid, e in by_group[g]:
            ev = last.get(sid)
            estado = ("%s %s" % (ESTADO.get(ev.get("event"), ev.get("event")), hhmmss(ev.get("ts")))) if ev else "sin eventos"
            ev_e = last_estado.get(sid)
            blk = heuristicas.bloque_sin_atender(ev_e, e, decs) if ev_e and g == "te_necesita" else None
            n0 = len(filas_bloque)
            if e.get("tarea_estado") == "relevo-fallido":  # 0.13.4: every wake, like a block, until attended
                estado = "relevo fallido → díselo al usuario; `lookout relevo` otra vez, o una decisión --cierre --si-es y con su sí `lookout cierra-pestana … --usuario-confirmo <id>` (%s)" % (
                    e.get("tarea_motivo") or "?")
                filas_bloque.append("  " + clip("%s | %s" % (registry.quien(e), estado), MAX_COLS - 2))
            elif retoma.salio_solo(last_se.get(sid), e):  # 0.13.20: every wake, until it is resumed or closed
                fin = last_se[sid]
                estado = ("salió sin que nadie lo pidiera %s (SessionEnd «%s») → `lookout retoma %s %s`; tú, no el "
                          "usuario" % (hhmmss(fin.get("ts")), fin.get("razon"), project_id, e.get("nombre")))
                filas_bloque.append("  " + clip("%s | %s" % (registry.quien(e), estado), MAX_COLS - 2))
            elif blk:  # 0.13.3: the row says what to do, every wake, until it is attended
                import retomar
                estado = "bloque %s %s → %s" % (blk.get("estado"), hhmmss(ev_e.get("ts")), retomar.accion(blk))
                filas_bloque.append("  " + clip("%s | %s" % (registry.quien(e), estado), MAX_COLS - 2))
            # 0.13.8: what the supervisor must do for this agent goes under its row, on every wake (a wait in its pane,
            # hooks older than the installed plugins); live 3-tier 2026-10-16, both sat unseen for hours
            extra = []
            if ev_e and ev_e.get("event") in ("idle", "bg_wait") and ev_e.get("espera_pane") and not blk:
                extra.append(espera_pane_txt(ev_e).strip())
            import deliver
            import versiones
            viejo = versiones.viejos(e, all_events, deliver.transcript_path(sid))
            if viejo:
                extra.append("hooks viejos: %s → `lookout recarga %s %s` (lo hace con el agente quieto y la caja vacía; "
                             "si no, tras su turno)" % (versiones.texto(viejo), project_id, e.get("nombre")))
            filas_bloque[n0:n0] = ["  " + clip("%s | %s" % (registry.quien(e), x), MAX_COLS - 2) for x in extra]
            tabla_clave.append([g, registry.quien(e), e.get("branch") or "", e.get("tarea") or "", estado] + extra)
            beat = heuristicas.ultimo_real(all_events, sid)
            if beat and beat.get("event") in heuristicas.EN_TURNO:
                rv = revisiones.get(sid) or {}
                if (float(rv.get("ts") or 0) > float(beat.get("ts") or 0)
                        and str(rv.get("decision", "")).startswith(("vivo", "progreso"))):
                    # Fase 9 E5: the check saw it alive after its last hook; "no events" alone invited screen reads
                    estado += " (el revisor lo vio %s hace %ds)" % (rv["decision"], int(now - float(rv["ts"])))
                else:
                    estado += " (sin eventos hace %ds)" % int(now - float(beat.get("ts") or now))
            # Fase 9 E1: the indent goes on after clip(), which collapses spaces; the hidden-agents count relies on it
            etiqueta = registry.quien(e)
            to = sesiones.to(e)  # 0.13.24 (p-e9c8601cfb): after a relief or a /rename its session has another name
            if to and to != e.get("nombre"):
                etiqueta += " [to=%s]" % to
            head.append("  " + clip("%s | %s | %s | %s" % (etiqueta, e.get("branch") or "-", e.get("tarea") or "-",
                                                          estado), MAX_COLS - 2))
            head += ["    ↳ " + clip(x, MAX_COLS - 6) for x in extra]
    import decisiones
    import publica
    # what the previous wake printed counts only for the same supervisor session, and never after a compaction
    # (olvida_vistos): a relief or a summarized context has not seen it
    sesion = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    antes = (cur.get("vistos") or {}) if por_waiter else {}
    if antes.get("sesion") != sesion:
        antes = {}
    vistos_ahora = {"tabla": clave(tabla_clave), "sesion": sesion}
    if por_waiter and antes.get("tabla") == vistos_ahora["tabla"]:
        # N3 (0.12.2): a waiter wake prints only what changed since the previous wake; `resumen` always prints it all
        head = ["Agentes (%d): sin cambios desde el despertar anterior (tabla: `lookout resumen %s --no-marcar`)." % (
            len(vivos), project_id)]
        if filas_bloque:  # 0.13.3: a block nobody attended is repeated on every wake, not folded into «sin cambios»
            head += ["%s:" % heuristicas.TITULO["te_necesita"]] + filas_bloque
    tail = []
    dec = decisiones.render(project_id, ancho=MAX_COLS)  # 0.13.14: clipped there, the modal labels whole
    if dec:
        dl = dec.splitlines()
        vistos_ahora["decisiones"] = clave([decisiones.clave_render(project_id)])
        if por_waiter and antes.get("decisiones") == vistos_ahora["decisiones"]:
            dl = ["Decisiones del usuario pendientes: %d, sin cambios (`lookout decision %s`)." % (len(dl) - 1, project_id)]
        elif not todo and len(dl) > 6:
            ocultas = decisiones.abiertas(project_id)[5:]  # 0.13.14: their ids and modal labels still show (codex r2)
            dl = dl[:6] + ["(+%d decisiones más: %s; sus preguntas: `lookout decision %s`)" % (
                len(dl) - 6, ", ".join(it["id"] + decisiones.etiquetas(it) for it in ocultas), project_id)]
        tail += dl
    if mark and any(p["estado"] in publica.EN_COLA for p in publica.load(project_id)["cola"]):
        tail += [clip(x) for x in publica.concilia(project_id)]  # Fase 9 E3; 0.13.27: open PRs too
    if any(p["estado"] in publica.EN_COLA for p in publica.load(project_id)["cola"]):
        cola = publica.render_cola(project_id)
        vistos_ahora["publicaciones"] = clave([cola])
        if por_waiter and antes.get("publicaciones") == vistos_ahora["publicaciones"]:
            tail.append("Publicaciones: sin cambios (`lookout resumen %s --no-marcar`)." % project_id)
        else:
            tail += [clip(x) for x in cola.splitlines()]
    pid = waiter_alive(project_id)
    if pid and waiter_owner_dead(project_id):
        tail.append("Waiter: el que hay es de una sesión que ya no supervisa; se cierra solo en ≤10 s. Al terminar este "
                    "turno lanza `lookout espera %s` con run_in_background: espera a que se cierre y toma su lugar." % project_id)
    elif pid:
        tail.append("Waiter: vivo (pid %d). No lances otro." % pid)
    elif por_waiter:
        # B1 (0.12.2): true when printed (this waiter just left) but read later; a waiter launched since then holds
        tail.append("Waiter: el que te despertó ya salió. Al terminar este turno lanza `lookout espera %s` con "
                    "run_in_background, salvo que ya hayas lanzado otro después de este despertar." % project_id)
    else:
        tail.append("Waiter: no hay. Al terminar este turno lanza `lookout espera %s` con run_in_background." % project_id)
    pres = presupuesto_line(project_id)
    if pres and not contexto_alto(project_id, pres):
        pres = ""  # N3 (0.12.2): the budget line only from 60 % of the limit
    if pres:
        tail.append(clip(pres, 400))
    room = maxl - len(head) - len(tail) - 2
    if len(head) - 1 > max(3, room // 2):  # many agents: keep the table from eating the events
        keep = max(3, room // 2)
        hidden = sum(1 for x in head[1 + keep:] if x.startswith("  ") and not x.startswith("    ↳"))
        head = head[:1 + keep] + ["(+%d agentes más: `lookout resumen %s --todo`)" % (hidden, project_id)]
        room = maxl - len(head) - len(tail) - 2
    body = []
    recortados = []
    if new:
        items = [(ev, 0) for ev in new] if todo else collapse(new)
        cap = max(1, room - 2)  # its header line and the "+N más" line
        if limit:
            cap = min(cap, limit)
        shown = items[-cap:]
        notas = ["agrupados por agente, %d líneas" % len(shown)] if len(shown) < len(new) else []
        if ecos:
            notas.append("%d ecos de tus mensajes y avisos sin mostrar" % len(ecos))
        body.append("Eventos nuevos (%d%s):" % (len(new), "".join("; " + n for n in notas)))
        for ev, n in shown:
            body.append(clip("- " + describe(ev, quien) + (" (+%d antes)" % n if n else "")))
        if len(items) > len(shown):
            recortados = [ev for ev, _n in items[:len(items) - len(shown)]]
            body.append("(+%d eventos más antiguos sin mostrar: vuelven en el siguiente resumen; ya: `lookout resumen %s "
                        "--todo`)" % (len(items) - len(shown), project_id))
    else:
        body.append("Eventos nuevos: ninguno (ya atendidos)." if not ecos else
                    "Eventos nuevos: ninguno (%d ecos de tus mensajes y avisos, sin mostrar)." % len(ecos))
    if mark:
        set_cursor(project_id, end, desde if por_waiter else None, recortados, vistos_ahora if por_waiter else None)
        try:
            import supervisor_md
            supervisor_md.write(project_id)
        except Exception:
            pass
    lines = head + [""] + body + [""] + tail
    return "\n".join(lines[:maxl])

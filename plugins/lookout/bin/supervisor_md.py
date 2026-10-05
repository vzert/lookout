"""The supervisor's own state, for its relief (docs/plan.md 3.11 and Fase 4).

supervisor.md is rewritten in full from files only (lock, registry, decisions, the supervisor's log, counters,
publication queue), never from the model's memory: whatever the supervisor decided is already on disk when a
new session reads it. Fixed sections: project, lock, agents and tasks, the user's decisions (taken and pending),
the supervisor's answers to the agents, counters, and «Como retomar» in the 3-tier format.

sup-log.jsonl is the supervisor's decision log. Its own hooks write it (hooks/guard-sup.sh → on_supervisor.py):
every SendMessage it sends (to, text) and every AskUserQuestion the user answers (questions, answers). Deterministic
on purpose: a supervisor skips a step whose answer looks obvious (learning 28), so the log does not depend on it.
"""
import os
import time

import lookout_state

LOG_KEEP = 15  # supervisor answers shown in supervisor.md
TXT = 220      # characters per quoted text


def path(project_id):
    return os.path.join(lookout_state.project_dir(project_id), "supervisor.md")


def log_path(project_id):
    return os.path.join(lookout_state.project_dir(project_id), "sup-log.jsonl")


def log(project_id, entry):
    import json
    entry = dict(entry, ts=entry.get("ts") or time.time())
    os.makedirs(lookout_state.project_dir(project_id), exist_ok=True)
    fd = os.open(log_path(project_id), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def read_log(project_id):
    import json
    out = []
    try:
        fh = open(log_path(project_id), encoding="utf-8")
    except OSError:
        return out
    with fh:
        for line in fh:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def one_line(text, n=TXT):
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[:n - 1] + "…"


def hhmm(ts):
    return time.strftime("%H:%M", time.localtime(ts or 0))


def agent_name(reg, to):
    """Registry name of a SendMessage target (an agent name, or an address)."""
    for e in reg.get("agents", {}).values():
        if to in (e.get("nombre"), e.get("herdr_name"), e.get("session_id")):
            return e.get("nombre")
    return to


def unanswered(slog):
    """Questions the supervisor put to the user (PreToolUse) with no answer logged (PostToolUse) for the same call."""
    answered = {x.get("tool_use_id") for x in slog if x.get("tipo") == "usuario" and x.get("tool_use_id")}
    # a relief asks the same question again in a new call: an answer to the same text closes the old one too
    texts = {one_line(q, 300) for x in slog if x.get("tipo") == "usuario" for q in (x.get("answers") or {})}
    return [x for x in slog if x.get("tipo") == "pregunta" and x.get("tool_use_id") not in answered
            and not (x.get("preguntas") and all(q in texts for q in x["preguntas"]))]


def retomar(project_id, repo, md_path, abiertas, sin_respuesta=0):
    """3-tier format, kept under ~700 characters: a longer paste reaches Claude as pasted text (learning 10)."""
    pend = ", ".join([d["id"] for d in abiertas] + (["%d pregunta(s) sin respuesta" % sin_respuesta] if sin_respuesta else [])) or "ninguna"
    return "\n".join([
        "Retomamos: supervisión lookout de %s (project_id %s); la sesión supervisora anterior terminó." % (repo, project_id),
        "Lee %s" % md_path,
        "Proximo paso: /lookout:supervisa %s y sigue «Si eres el relevo». Decisiones del usuario pendientes: %s." % (repo, pend),
        "No repitas: preguntar lo que supervisor.md da por decidido (tomadas y tus respuestas a los agentes).",
        "Terminas cuando: el usuario pida soltar (lookout suelta %s)." % project_id,
        "Antes de actuar, dime en 3 lineas donde quedamos.",
    ])


def render(project_id, now=None):
    import decisiones
    import lock
    import publica
    import registry
    now = now or time.time()
    lk = lock.read(project_id) or {}
    sup = lk.get("supervisor") or {}
    common = lk.get("common_dir", "")
    repo = os.path.dirname(common.rstrip("/")) if common.endswith(".git") else common
    reg = registry.load(project_id)
    events, _ = lookout_state.read_events(project_id, 0)
    last = {}
    for ev in events:
        if ev.get("event") != "notification":
            last[ev.get("session_id")] = ev
    dec = decisiones.load(project_id)["items"]
    tomadas = [d for d in dec if d.get("estado") == "respondida"]
    abiertas = [d for d in dec if d.get("estado") == "abierta"]
    slog = read_log(project_id)
    md = path(project_id)
    L = ["# Supervisor lookout — %s" % (repo or project_id),
         "", "Escrito %s por lookout desde sus archivos (no lo edites a mano)." % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
         "", "## Proyecto", "- project_id: %s" % project_id, "- repo: %s" % repo,
         "- raíces: %s" % ", ".join(lk.get("roots") or []),
         "", "## Candado",
         "- supervisor: %s, sesión %s, pid %s, dirección %s, desde %s" % (
             sup.get("nombre"), sup.get("session_id"), sup.get("pid"), sup.get("address"), lk.get("desde")),
         "", "## Agentes y tareas", "nombre | pane | rama | tarea | estado de la tarea | último evento"]
    for sid, e in reg.get("agents", {}).items():
        if e.get("tarea_estado") == "relevada":
            continue
        ev = last.get(sid)
        L.append("%s | %s | %s | %s | %s | %s" % (
            e.get("nombre"), e.get("pane_id"), e.get("branch") or "-", e.get("tarea") or "-", e.get("tarea_estado") or "-",
            ("%s %s" % (ev.get("event"), hhmm(ev.get("ts")))) if ev else "sin eventos"))
    L += ["", "## Decisiones del usuario — tomadas"]
    respuestas = [x for x in slog if x.get("tipo") == "usuario"]
    L += ["- %s (%s): %s → %s: %s" % (d["id"], hhmm(d.get("hasta")), one_line(d["texto"], 120),
                                      "SÍ" if d.get("aprueba") else "NO", one_line(d.get("respuesta"), 120))
          for d in tomadas] or ([] if respuestas else ["- ninguna"])
    if respuestas:
        L.append("Respuestas del usuario en tus AskUserQuestion (registradas por hook):")
        L += ["- %s %s → %s" % (hhmm(x["ts"]), one_line(q, 100), one_line(a, 80))
              for x in respuestas[-8:] for q, a in (x.get("answers") or {}).items()]
    sin_resp = unanswered(slog)
    L += ["", "## Decisiones del usuario — pendientes"]
    L += ["- %s (abierta hace %s; esperan: %s): %s" % (d["id"], decisiones.edad(d["desde"], now),
                                                       ", ".join(d.get("agentes") or []) or "-", one_line(d["texto"]))
          for d in abiertas] + ["- pregunta de las %s sin respuesta del usuario (AskUserQuestion): %s"
                                % (hhmm(q["ts"]), one_line(" / ".join(q.get("preguntas") or []), 200)) for q in sin_resp] or ["- ninguna"]
    L += ["", "## Respuestas del supervisor a los agentes (últimas %d)" % LOG_KEEP]
    mine = [x for x in slog if x.get("tipo") == "respuesta"]
    L += ["- %s → %s: %s" % (hhmm(x["ts"]), agent_name(reg, x.get("to", "")), one_line(x.get("texto")))
          for x in mine[-LOG_KEEP:]] or ["- ninguna"]
    cnt = lookout_state.read_json(os.path.join(lookout_state.project_dir(project_id), "counters.json")) or {}
    L += ["", "## Contadores"]
    tareas = cnt.get("tareas") or {}
    L += ["- %s: %d rondas (límite %s); último: %s" % (t, v.get("rondas", 0), v.get("limite", 5), v.get("ultimo", "-"))
          for t, v in tareas.items()] or ["- sin rondas de adversario"]
    cola = [p for p in publica.load(project_id)["cola"] if p.get("estado") in ("esperando", "turno", "lista")]
    L += ["- cola de publicación: " + (", ".join("%s (%s)" % (p.get("nombre"), p.get("estado")) for p in cola) or "vacía")]
    L += ["", "## Como retomar", "```", retomar(project_id, repo, md, abiertas, len(sin_resp)), "```", ""]
    return "\n".join(L)


def write(project_id, now=None):
    """Rewrite supervisor.md in full (atomic). Returns its path."""
    p = path(project_id)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = "%s.%d.tmp" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(render(project_id, now))
    os.replace(tmp, p)
    return p


def retomar_block(project_id):
    text = render(project_id)
    return text.split("## Como retomar\n", 1)[1].strip()


# ---------- supervisor marker (which session is the supervisor; read by hooks/guard-sup.sh) ----------

def sup_marker(session_id):
    return os.path.join(lookout_state.state_root(), "supervisores", session_id + ".json")


def mark_supervisor(session_id, project_id):
    if lookout_state._safe_id(session_id):
        lookout_state.write_json(sup_marker(session_id), {"project_id": project_id, "desde": time.time()})


def unmark_supervisor(session_id):
    if lookout_state._safe_id(session_id):
        try:
            os.remove(sup_marker(session_id))
        except OSError:
            pass


def supervised_by(session_id):
    if not lookout_state._safe_id(session_id):
        return None
    return (lookout_state.read_json(sup_marker(session_id)) or {}).get("project_id")

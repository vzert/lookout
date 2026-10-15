"""0.13.0: close the tab of a finished agent (memory/plans/plan-lookout-altas-cierres-relevos.md, Fase 2; research B).

The user's decision (2026-10-15): a finished agent's tab is closed by the supervisor, who tells the user in one line,
after TWO signals and with nothing of the agent left behind. Closing ends its session: every guard below stops it,
and says which one, so the supervisor can pass it to the user.

Signal 1, finished: its last turn says so — a «Como retomar: Ninguno» header (retomar.bloque → "nada"), or a quote the
supervisor gives with --motivo that appears verbatim in that last turn (plan-ciclo: «No emito nada y termino aquí»).
A goalspec [COMPLETION-REVIEW or a task marked terminada alone never count (askuserquestion-pendientes declared
«¿Cerrado? Sí» and still waited for an answer). A live block («hay») is a relief, never a close.
Signal 2, screen: herdr says idle/done, its input box is empty or a suggestion.
Guards: no uncommitted change of its own; no local commit of its own not on the remote; no publication of its own
waiting/holding the turn; no open decision naming it; no message of its to the supervisor newer than the last answer to
it; a last turn with no «?», «¿» or «？» (the 0.12.2 rule: a question waits for someone); no background task of its own.
Threat model: an accidental omission (work left behind, a pending answer); not an agent that lies on purpose.
"""
import json
import os
import re
import time

import decisiones
import deliver
import herdr_cli
import lookout_state
import lote
import publica
import registry
import retomar
import supervisor_md

FIN_TIMEOUT = 60


def _turno(session_id):
    return retomar.ultimo_turno(deliver.transcript_path(session_id))


def senal_terminado(entry, motivo=""):
    """'' if its last turn says it finished, else why not."""
    text, _ts = _turno(entry["session_id"])
    estado, blk = retomar.bloque(text)
    if estado == "hay":
        return "su último turno deja un bloque para retomar con trabajo: es un relevo, no un cierre"
    if estado == "nada":
        return ""
    if motivo and motivo.strip() and motivo.strip() in text:  # verbatim (adversary round 1: no whitespace folding)
        return ""
    if motivo:
        return "la cita de --motivo no está tal cual en su último turno"
    return ("su último turno no dice que terminó: ni «Como retomar: Ninguno» ni una cita suya con --motivo (un "
            "[COMPLETION-REVIEW o una tarea terminada solos no bastan)")


def senal_pantalla(entry):
    live = herdr_cli.agent_get(entry["pane_id"]) or {}
    if (live.get("agent_session") or {}).get("value") != entry["session_id"]:
        return "su pane ya no es suyo (registro viejo)"
    if live.get("agent_status") not in ("idle", "done"):
        return "herdr lo ve %s" % (live.get("agent_status") or "sin estado")
    box, _ = deliver.read_box(entry["pane_id"])
    if box not in ("vacia", "sugerencia"):
        return "su caja tiene %s (un borrador del usuario o un diálogo)" % box
    return ""


def _git(wt, *args):
    return publica.git(wt, *args)


def guarda_cambios(project_id, entry):
    wt = entry.get("worktree") or entry.get("cwd") or ""
    code, out = _git(wt, "status", "--porcelain")
    if code != 0:
        return "no puedo leer `git status` en %s" % wt
    propios, _ajenos = publica.reparte_sucios(project_id, entry, wt, out)
    if propios:
        return "cambios sin commit suyos: %s" % ", ".join(l[3:] for l in propios[:5])
    return ""


COMMIT_RE = re.compile(r"\[[^\]\s]+(?: \([^)]*\))? ([0-9a-f]{7,40})\]")


def sus_commits(session_id):
    """Short hashes its own `git commit` printed («[main 0192f4a] …»), from the tool results of its transcript. None if
    the transcript cannot be read."""
    path = deliver.transcript_path(session_id)
    out = set()
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"tool_result"' in line and "] " in line:
                    out |= set(COMMIT_RE.findall(line))
    except (OSError, TypeError):
        return None
    return out


def guarda_sin_subir(project_id, entry):
    wt = entry.get("worktree") or entry.get("cwd") or ""
    code, out = _git(wt, "rev-list", "@{u}..HEAD")
    if code != 0:
        code, out = _git(wt, "rev-list", "HEAD", "--not", "--remotes")
    if code != 0:
        return "no puedo saber si tiene commits sin subir en %s" % wt
    pendientes = [h for h in (out or "").split() if h]
    if not pendientes:
        return ""
    # Strict on purpose, also in a shared checkout: a commit made with -q, by a subagent or by a script prints no
    # «[rama hash]» in its transcript (3-tier-memory, 2026-10-15: none of the 6 unpushed 2.58.1 commits did), so
    # matching hashes would call an agent with unpushed work clean. Closing waits for the push, whoever owes it.
    mios = sus_commits(entry["session_id"]) or set()
    suyos = [h for h in pendientes if any(h.startswith(m) for m in mios)]
    if suyos:
        return "%d commit(s) suyo(s) sin subir en %s" % (len(suyos), wt)
    return "%d commit(s) sin subir en su árbol %s (quizá de otro agente): primero el push" % (len(pendientes), wt)


def guarda_publicacion(project_id, entry):
    p = publica.entry_of(publica.load(project_id), entry["session_id"])
    if p and p.get("estado") in ("esperando", "turno", "lista"):
        return "tiene una publicación %s" % p["estado"]
    return ""


def guarda_decision(project_id, entry):
    nombres = {entry.get("nombre"), entry.get("herdr_name")} - {None, ""}
    for it in decisiones.abiertas(project_id):
        if nombres & set(it.get("agentes") or ()):
            return "la decisión %s sigue abierta y lo nombra" % it.get("id")
    return ""


def _ultimo_mensaje_al_supervisor(session_id, address):
    path = deliver.transcript_path(session_id)
    last = None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"SendMessage"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                for b in (row.get("message") or {}).get("content") or []:
                    if isinstance(b, dict) and b.get("name") == "SendMessage" and \
                            (b.get("input") or {}).get("to") == address:
                        last = retomar._ts(row) or last
    except (OSError, TypeError):
        return None
    return last


def _direcciones(project_id, entry):
    out = {entry.get("nombre"), entry.get("herdr_name")} - {None, ""}
    for ev in lookout_state.read_events(project_id, 0)[0]:
        if ev.get("session_id") == entry["session_id"] and ev.get("claude_pid"):
            out.add("/%d.sock" % ev["claude_pid"])
    return out


def guarda_mensaje(project_id, entry):
    marker = lookout_state.read_marker(entry["session_id"]) or {}
    enviado = _ultimo_mensaje_al_supervisor(entry["session_id"], marker.get("address", ""))
    text, _ts = _turno(entry["session_id"])
    if any(c in text for c in "?¿？"):
        return "su último turno pregunta algo («?», «¿» o «？»): espera respuesta"
    if not enviado:
        return ""
    dirs = _direcciones(project_id, entry)
    respondido = 0.0
    for row in supervisor_md.read_log(project_id):
        to = str(row.get("to") or "")
        if row.get("tipo") in ("respuesta", "directa") and (
                row.get("session_id") == entry["session_id"] or to in dirs or any(to.endswith(d) for d in dirs if d.startswith("/"))):
            respondido = max(respondido, float(row.get("ts") or 0))
    if enviado > respondido:
        return ("su último mensaje al supervisor no tiene respuesta: contéstale primero (aunque sea un acuse) y "
                "repite")
    return ""


def guarda_fondo(project_id, entry):
    last = None
    for ev in lookout_state.read_events(project_id, 0)[0]:
        if ev.get("session_id") == entry["session_id"] and ev.get("event") in ("idle", "bg_wait", "working"):
            last = ev
    if last and last.get("event") == "bg_wait":
        return "espera una tarea de fondo suya"
    return ""


GUARDAS = (guarda_cambios, guarda_sin_subir, guarda_publicacion, guarda_decision, guarda_mensaje, guarda_fondo)


def revisa(project_id, entry, motivo=""):
    """The list of reasons not to close ([] = it can be closed)."""
    out = []
    for check in (lambda: senal_terminado(entry, motivo), lambda: senal_pantalla(entry)):
        r = check()
        if r:
            out.append(r)
    for g in GUARDAS:
        r = g(project_id, entry)
        if r:
            out.append(r)
    return out


def cierra(project_id, entry, motivo="", fin_timeout=FIN_TIMEOUT, log=print):
    """(ok, message for the user)."""
    with lote.project_mutex(project_id):
        frenos = revisa(project_id, entry, motivo)
        if frenos:
            return False, "NO cierro la pestaña de %s: %s." % (entry.get("nombre"), "; ".join(frenos))
        pane = entry["pane_id"]
        offset = deliver.events_size(project_id)
        herdr_cli.run(["agent", "prompt", pane, "/exit"])
        ended = deliver.wait_event(project_id, offset, fin_timeout,
                                   lambda ev: ev.get("session_id") == entry["session_id"] and ev.get("event") == "end")
        if not ended:
            return False, ("NO cierro la pestaña de %s: no salió en %d s tras /exit (sin SessionEnd). Mira su pane o "
                           "avisa al usuario." % (entry.get("nombre"), fin_timeout))
        tab = herdr_cli.tab_get(entry.get("tab_id")) or {}
        if entry.get("tab_id") and int(tab.get("pane_count") or 0) == 1:
            code, _o, err = herdr_cli.run(["tab", "close", entry["tab_id"]])
            que = "pestaña"
        else:
            code, _o, err = herdr_cli.run(["pane", "close", pane])
            que = "pane"
        reg = registry.load(project_id)
        e = reg["agents"].get(entry["session_id"]) or {}
        e.update(retirado=time.strftime("%Y-%m-%dT%H:%M:%S%z"), retirado_por="terminado: %s cerrada por el supervisor" % que)
        registry.save(project_id, reg)
        publica.retira_sesion(project_id, entry["session_id"], "terminado")
        if lote.puerto_de(e):
            import ports
            ports.libera(lote.puerto_de(e))
        lookout_state.remove_marker(entry["session_id"])
        if code != 0:
            return False, ("%s salió, pero herdr no cerró su %s (%s): ciérrala a mano." % (
                entry.get("nombre"), que, (err or "").strip()[:120]))
        return True, "Cerré la %s de %s: terminó y no dejó nada pendiente." % (
            que, entry.get("pestana") or entry.get("nombre"))

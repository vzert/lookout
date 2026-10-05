"""Stuck heuristics of docs/plan.md 6.1 (Fase 6): counters in files, never in the supervisor's memory.

Everything here is derived from events.jsonl, so a relieved supervisor (or a crash) never leaves the counters out of
sync: counters.json is only a snapshot of what the events say, rewritten each time something is counted.

  Same error, repeated   PostToolUseFailure -> `fallo` with a signature (tool + "Exit code N" + first output line,
                         digits and paths blanked). The 3rd `fallo` with one signature (since the session started) adds
                         a `repite`. `lookout corrige` records a `correccion`, whose text asks the agent to apply it and
                         check ONCE; if that signature fails again even once, the correction failed: a new `repite`.
                         It also failed when the agent reports so without running the command again: the supervisor
                         quotes that report (`corrige --reporte`), and lookout checks the quote is in a SendMessage the
                         agent itself sent after that correction (its own transcript), never the supervisor's word.
                         After 2 failed corrections of one signature `corrige` refuses: stop and rethink (no ping-pong).
  No progress            checked by the waiter (a script; the supervisor never polls) only while an agent's last
                         state is "working" and its last hook event is older than the "mirar" threshold. Never from
                         one source: stale hooks alone say nothing. Alive = herdr says working AND its Claude process
                         runs (not stopped, not gone). Progress = files of its worktree or its HEAD changed recently.
                         `sin_progreso` (mirar / escalar) needs the stale hooks plus another source saying "not
                         working"; a session that is alive but quiet for hours gets one `largo` (look at it once).
  API error              StopFailure rate_limit / overloaded -> `pausa`: a pause of the provider, not a task failure.

Thresholds (seconds, env): LOOKOUT_MIRAR_S 300, LOOKOUT_ESCALAR_S 1200, LOOKOUT_LARGO_S 3600, LOOKOUT_REVISA_CADA 30.
"""
import fcntl
import os
import re
import shlex
import subprocess
import time

import lookout_state

REPITE_EN = 3          # the same error this many times -> `repite`
MAX_CORRECCIONES = 2   # after this many failed corrections: stop and rethink
PAUSA_ERRORS = ("rate_limit", "overloaded")
SINTETICOS = ("repite", "correccion", "correccion_fallida", "sin_progreso", "largo")  # written by lookout, not by the agent's hooks
EN_TURNO = ("working", "aprobado", "fallo", "crossrepo")         # the agent should be producing events
NO_ESTADO = ("notification", "aprobado", "fallo", "crossrepo", "correccion_fallida")  # events that do not change an agent's state


def umbral(name, default):
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return float(default)


def mirar_s():
    return umbral("LOOKOUT_MIRAR_S", 300)


def escalar_s():
    return umbral("LOOKOUT_ESCALAR_S", 1200)


def largo_s():
    return umbral("LOOKOUT_LARGO_S", 3600)


def revisa_cada():
    return umbral("LOOKOUT_REVISA_CADA", 30)


# ---------- same error ----------

def _norm(text):
    text = re.sub(r"(?:~|\.{0,2})?/[^\s:'\"()]+", "<ruta>", text)
    text = re.sub(r"0x[0-9a-fA-F]+|\d+", "#", text)
    return " ".join(text.split())[:120]


def firma(tool, error):
    """Signature of one failure: the tool, the stable "Exit code N" line (hooks docs) and the first output line, with
    paths and numbers blanked, so retrying the same thing with another path or line number is still the same error."""
    lines = [l.strip() for l in (error or "").splitlines() if l.strip()]
    code = ""
    if lines and re.match(r"^Exit code -?\d+$", lines[0]):
        code = lines.pop(0)
    lines = [l for l in lines if not re.match(r"^\.\.\. \[\d+ characters truncated\] \.\.\.$", l)]
    first = _norm(lines[0]) if lines else ""
    return " | ".join(x for x in (tool or "?", code, first) if x)


def _project_events(project_id):
    return lookout_state.read_events(project_id, 0)[0]


def umbral_repite(corr):
    """Failures of one signature that make a `repite`: 3 before any correction; after a correction, the first one
    (the agent was told to check once: the error coming back means the correction failed)."""
    return REPITE_EN if corr == 0 else 1


def racha(events, sid, sig):
    """(failures of `sig` since its last correction or the session's start, corrections of `sig` so far)."""
    n = corr = 0
    for ev in events:
        if ev.get("session_id") != sid:
            continue
        kind = ev.get("event")
        if kind == "start":
            n = corr = 0
        elif kind == "correccion" and ev.get("firma") == sig:
            n, corr = 0, corr + 1
        elif kind == "fallo" and ev.get("firma") == sig:
            n += 1
    return n, corr


def intentos(events, sid, sig, k=REPITE_EN):
    out = [str(ev.get("detalle") or "") for ev in events if ev.get("session_id") == sid and ev.get("event") == "fallo"
           and ev.get("firma") == sig]
    return out[-k:]


def contadores(events):
    """counters.json content: per agent, per signature, the current streak and its corrections; and per agent the
    no-progress warnings already given."""
    agents = {}
    for ev in events:
        sid = ev.get("session_id")
        kind = ev.get("event")
        if not sid or kind not in ("fallo", "correccion", "start", "sin_progreso", "largo"):
            continue
        a = agents.setdefault(sid, {"nombre": ev.get("nombre", ""), "errores": {}, "avisos": []})
        if kind == "start":
            a["errores"] = {}
        elif kind in ("fallo", "correccion"):
            e = a["errores"].setdefault(ev.get("firma", ""), {"seguidos": 0, "correcciones": 0, "ultimo": 0})
            if kind == "fallo":
                e["seguidos"] += 1
            else:
                e["seguidos"], e["correcciones"] = 0, e["correcciones"] + 1
            e["ultimo"] = ev.get("ts", 0)
        else:
            a["avisos"].append({"evento": kind, "nivel": ev.get("nivel", ""), "desde": ev.get("desde")})
    return {"ts": time.time(), "agentes": agents}


def counters_path(project_id):
    # Its own file: counters.json belongs to gobierno.py (adversary rounds and the user's raised limits per task).
    # Writing this snapshot there wiped them (0.7.3, KeyError 'tareas' in `lookout gobierno` on claude-vzert).
    return os.path.join(lookout_state.project_dir(project_id), "atascado.json")


class mutex(object):
    """flock around "read events, decide, append" so two async hooks never both write the 3rd-failure `repite`."""

    def __init__(self, project_id):
        self.path = os.path.join(lookout_state.project_dir(project_id), "counters.lock")

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)


def guarda_contadores(project_id, events=None):
    events = _project_events(project_id) if events is None else events
    lookout_state.write_json(counters_path(project_id), contadores(events))


def registra_fallo(project_id, ev):
    """Append the `fallo` event and, on the 3rd of its signature since the last correction, a `repite`. Returns the
    `repite` event or None."""
    with mutex(project_id):
        lookout_state.append_event(project_id, ev)
        events = _project_events(project_id)
        n, corr = racha(events, ev.get("session_id"), ev.get("firma"))
        rep = None
        if n == umbral_repite(corr):
            rep = {k: ev.get(k) for k in ("session_id", "nombre", "pane", "tool_name", "firma")}
            rep.update(event="repite", veces=n, correcciones=corr, intentos=intentos(events, ev["session_id"], ev["firma"]),
                       replantea=corr >= MAX_CORRECCIONES)
            lookout_state.append_event(project_id, rep)
            events.append(rep)
        guarda_contadores(project_id, events)
        return rep


def ultima_firma(events, sid):
    for ev in reversed(events):
        if ev.get("session_id") == sid and ev.get("event") == "repite":
            return ev.get("firma")
    return None


def _norm_txt(text):
    return " ".join((text or "").split()).lower()


def reporte_del_agente(session_id, cita, desde, projects_dir=None):
    """True when `cita` (whitespace and case folded) is inside a SendMessage the agent itself sent after `desde`
    (epoch seconds), read from the agent's own transcript."""
    import datetime
    import json
    import deliver
    path = deliver.transcript_path(session_id, projects_dir)
    want = _norm_txt(cita)
    if not path or not want:
        return False
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return False
    with fh:
        for line in fh:
            if '"SendMessage"' not in line:
                continue
            try:
                d = json.loads(line)
                ts = datetime.datetime.fromisoformat(d.get("timestamp", "").replace("Z", "+00:00")).timestamp()
            except (ValueError, TypeError):
                continue
            if ts < desde or d.get("type") != "assistant":
                continue
            for b in (d.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "SendMessage" \
                        and want in _norm_txt(json.dumps(b.get("input") or {}, ensure_ascii=False)):
                    return True
    return False


def ultima_correccion(events, sid, sig):
    for ev in reversed(events):
        if ev.get("session_id") == sid and ev.get("event") == "correccion" and ev.get("firma") == sig:
            return ev
    return None


def corrige(project_id, entry, resumen, sig=None, reporte=None, projects_dir=None):
    """Record one correction for the agent's repeated error. Returns (code, text): 0 + the message to send, or
    5 + why not (stop and rethink after MAX_CORRECCIONES; nothing repeated; no summary).
    `reporte`: the agent's own words saying the correction did not work, when it reported instead of running the
    command again (Fase 6 runs 3-4); quoted in the event, it counts that correction as failed like a new `repite`."""
    sid = entry["session_id"]
    with mutex(project_id):
        events = _project_events(project_id)
        sig = sig or ultima_firma(events, sid)
        if not sig:
            return 5, "NO: %s no tiene un error repetido registrado (ningún `repite`)." % entry["nombre"]
        n, corr = racha(events, sid, sig)
        reporte = " ".join((reporte or "").split())
        last_corr = ultima_correccion(events, sid, sig)
        verificado = bool(reporte) and len(reporte) >= 20 and last_corr is not None and reporte_del_agente(
            sid, reporte, float(last_corr.get("ts") or 0), projects_dir)
        if corr >= MAX_CORRECCIONES and n < umbral_repite(corr) and verificado \
                and not any(e.get("event") == "correccion_fallida" and e.get("session_id") == sid
                            and e.get("numero") == corr and e.get("firma") == sig for e in events):
            # the last correction failed by the agent's own report (no new repite): record it before stopping
            fe = {"session_id": sid, "nombre": entry["nombre"], "event": "correccion_fallida", "firma": sig,
                  "numero": corr, "reporte": reporte[:300]}
            lookout_state.append_event(project_id, fe)
            events.append(fe)
            guarda_contadores(project_id, events)
        if corr >= MAX_CORRECCIONES:
            return 5, ("PARA: ya van %d correcciones para «%s» y el error volvió. No mandes otra corrección (sin "
                       "ping-pong). Replantea: escala al usuario con `lookout decision %s --abre …` y AskUserQuestion, "
                       "con los intentos y tu propuesta (otro enfoque, otra tarea, o parar a %s); al agente dile que "
                       "espere tu mensaje." % (corr, sig, project_id, entry["nombre"]))
        por_reporte = corr >= 1 and n < umbral_repite(corr) and verificado
        if reporte and not verificado and n < umbral_repite(corr):
            return 5, ("NO: no encuentro esa cita en un SendMessage de %s posterior a la última corrección (su transcript). "
                       "Copia sus palabras tal cual (≥20 caracteres)." % entry["nombre"])
        if n < umbral_repite(corr) and not por_reporte:
            extra = (" Si el agente te reportó que la corrección no sirvió, cita su reporte con --reporte \"…\"."
                     if corr >= 1 else "")
            return 5, ("NO: «%s» falló %d vez/veces desde la última corrección; la corrección va tras %d.%s"
                       % (sig, n, umbral_repite(corr), extra))
        resumen = " ".join((resumen or "").split())
        if len(resumen) < 20:
            return 5, "NO: el resumen debe decir qué falla, por qué y qué hacer distinto (≥20 caracteres)."
        k = corr + 1
        ev = {"session_id": sid, "nombre": entry["nombre"], "event": "correccion", "firma": sig, "numero": k,
              "resumen": resumen[:600]}
        if por_reporte:
            ev["fallo_por_reporte"] = reporte[:300]
        lookout_state.append_event(project_id, ev)
        events.append(ev)
        guarda_contadores(project_id, events)
    texto = ("[supervisor lookout] Corrección %d de %d: el mismo error volvió («%s»). %s Aplica esto ya y luego corre UNA "
             "vez el mismo comando que fallaba, aunque creas que va a fallar: es la comprobación. Si falla igual, no pruebes "
             "variantes: repórtamelo y termina tu turno." % (k, MAX_CORRECCIONES, sig, resumen))
    return 0, texto


# ---------- no progress ----------

def estado_proceso(pid):
    """vivo | detenido | muerto | desconocido (from `ps`: T = stopped, Z = zombie)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return "desconocido"
    if pid <= 0:
        return "desconocido"
    try:
        out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return "desconocido"
    stat = out.stdout.strip()
    if not stat:
        return "muerto"
    if stat[0] == "T":
        return "detenido"
    if stat[0] == "Z":
        return "muerto"
    return "vivo"


def claude_pid(events, sid):
    for ev in reversed(events):
        if ev.get("session_id") == sid and ev.get("claude_pid"):
            return ev["claude_pid"]
    return None


def estado_herdr(agents, sid, pane):
    """herdr's screen-detected status of this session: working | idle | done | blocked | unknown | ausente."""
    for a in agents or []:
        if ((a.get("agent_session") or {}).get("value") == sid) or (pane and a.get("pane_id") == pane and not sid):
            return a.get("agent_status") or "unknown"
    return "ausente"


def worktree_reciente(path, since):
    """True when a changed file of the worktree, or its HEAD commit, is newer than `since` (epoch seconds)."""
    if not path or not os.path.isdir(path):
        return False
    try:
        head = subprocess.run(["git", "-C", path, "log", "-1", "--format=%ct"], capture_output=True, text=True,
                              timeout=5).stdout.strip()
        if head.isdigit() and int(head) >= since:
            return True
        out = subprocess.run(["git", "-C", path, "status", "--porcelain", "-z", "--untracked-files=all"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    for i, item in enumerate(x for x in out.split("\0") if x):
        if i >= 300:
            break
        rel = item[3:] if len(item) > 3 and item[2] == " " else item
        try:
            if os.path.getmtime(os.path.join(path, rel)) >= since:
                return True
        except OSError:
            continue
    return False


def ultimo_real(events, sid):
    """The agent's last own hook event (synthetic ones and herdr notifications left out): its heartbeat."""
    for ev in reversed(events):
        if ev.get("session_id") == sid and ev.get("event") not in SINTETICOS + ("notification",):
            return ev
    return None


def ya_avisado(events, sid, kind, nivel, desde):
    return any(ev.get("session_id") == sid and ev.get("event") == kind and ev.get("nivel", "") == nivel
               and ev.get("desde") == desde for ev in events)


def revisa_log(project_id, row):
    """One line per agent the check looked at (revisa.log): the evidence that it ran and what it saw, so "no event"
    can be told apart from "never checked"."""
    import json
    path = os.path.join(lookout_state.project_dir(project_id), "revisa.log")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(row, ts=time.time()), ensure_ascii=False) + "\n")


def revisa(project_id, now=None, agents=None, proceso=estado_proceso, reciente=worktree_reciente):
    """One check of every registered agent; appends and returns the `sin_progreso` / `largo` events it decided.
    Cheap when nobody is quiet: herdr and ps are asked only about an agent whose hooks went stale."""
    import registry
    now = time.time() if now is None else now
    mirar, escalar, largo = mirar_s(), escalar_s(), largo_s()
    out = []
    with mutex(project_id):
        events = _project_events(project_id)
        reg = registry.load(project_id).get("agents", {})
        for sid, entry in reg.items():
            if entry.get("tarea_estado") == "relevada":
                continue
            last = ultimo_real(events, sid)
            if not last or last.get("event") not in EN_TURNO:
                continue
            age = now - float(last.get("ts") or now)
            if age < mirar:
                continue
            if agents is None:
                import herdr_cli
                agents = herdr_cli.agent_list()
            hd = estado_herdr(agents, sid, entry.get("pane_id"))
            pr = proceso(claude_pid(events, sid))
            base = {"session_id": sid, "nombre": entry.get("nombre", ""), "pane": entry.get("pane_id", ""),
                    "desde": last.get("ts"), "hace_s": int(age), "herdr": hd, "proceso": pr}
            log = {"session_id": sid, "nombre": base["nombre"], "hace_s": int(age), "herdr": hd, "proceso": pr}
            if hd == "working" and pr == "vivo":
                # Alive and busy (a long build, a long test run): never stuck. Only after hours, one look at it.
                if age >= largo and not ya_avisado(events, sid, "largo", "", last.get("ts")):
                    out.append(dict(base, event="largo"))
                revisa_log(project_id, dict(log, decision="vivo" + (" (largo)" if age >= largo else "")))
                continue
            if reciente(entry.get("worktree") or entry.get("cwd"), now - mirar):
                revisa_log(project_id, dict(log, decision="progreso en el worktree"))
                continue  # its files are changing: progress
            fuentes = ["hooks: sin eventos hace %ds (último: %s)" % (age, last.get("event"))]
            if pr in ("detenido", "muerto"):
                fuentes.append("proceso de Claude %s" % pr)
            if hd != "working":
                fuentes.append("herdr: %s" % hd)
            if len(fuentes) < 2:
                revisa_log(project_id, dict(log, decision="una sola fuente"))
                continue  # one source only (rule of gold: never declare stuck from a single store)
            nivel = "escalar" if age >= escalar else "mirar"
            revisa_log(project_id, dict(log, decision="sin_progreso " + nivel, fuentes=fuentes))
            if ya_avisado(events, sid, "sin_progreso", nivel, last.get("ts")):
                continue
            out.append(dict(base, event="sin_progreso", nivel=nivel, fuentes=fuentes))
        for ev in out:
            lookout_state.append_event(project_id, ev)
            events.append(ev)
        if out:
            guarda_contadores(project_id, events)
    for ev in out:  # outside the mutex: transicion takes it too (same file, new fd: it would block on itself)
        transicion(project_id, ev)
    return out


def alguien_callado(project_id, now=None):
    """Cheap pre-check for the waiter: is any agent's last own event in-turn and older than the "mirar" threshold?"""
    now = time.time() if now is None else now
    events = _project_events(project_id)
    last = {}
    for ev in events:
        if ev.get("event") not in SINTETICOS + ("notification",):
            last[ev.get("session_id")] = ev
    return any(ev.get("event") in EN_TURNO and now - float(ev.get("ts") or now) >= mirar_s() for ev in last.values())


# ---------- grouped view ----------

GRUPOS = ("te_necesita", "listo", "trabajando", "pausa", "idle")
TITULO = {"te_necesita": "Te necesita", "listo": "Listo para revisar", "trabajando": "Trabajando",
          "pausa": "En pausa (proveedor)", "idle": "Idle"}


def grupo(events, sid, entry=None):
    """The agent's group in the grouped view, from its last state event (fallo/aprobado/crossrepo/notification are
    in-turn noise and do not move it: a `repite` keeps it in "te necesita" while it keeps failing)."""
    entry = entry or {}
    for ev in reversed(events):
        if ev.get("session_id") != sid or ev.get("event") in NO_ESTADO:
            continue
        k = ev.get("event")
        if k in ("ask", "blocked", "negado", "repite", "unknown"):
            return "te_necesita"
        if k == "sin_progreso":
            return "te_necesita" if ev.get("nivel") == "escalar" else "trabajando"
        if k == "pausa":
            return "pausa"
        if k == "idle":
            # "Listo" = finished work: a completion review, or a task marked done. A report to the supervisor alone is
            # not (it is often a question or "waiting for you"): the supervisor already has that message (Fase 6 run 1).
            done = any("[COMPLETION-REVIEW" in m for m in ev.get("marcadores") or []) \
                or entry.get("tarea_estado") == "terminada"
            return "listo" if done else "idle"
        if k in ("working", "bg_wait", "correccion", "largo"):
            return "trabajando"
        if k == "start":
            return "idle"
        if k == "end":
            return "fin"
        return "trabajando"
    return "idle"


def grupos_path(project_id):
    return os.path.join(lookout_state.project_dir(project_id), "grupos.json")


AVISA = ("te_necesita", "listo")
# `ask` is answered by the supervisor itself (D5): no notification to the user for it. `blocked` / `negado` already got
# theirs from permisos.py.
NO_AVISA_POR = ("ask", "blocked", "negado")


def transicion(project_id, ev, notificar=True):
    """After an event: recompute the agent's group; on a change INTO "te necesita" or "listo", one herdr notification.
    Returns (old, new, notified)."""
    import herdr_cli
    import registry
    sid = ev.get("session_id")
    if not sid:
        return None, None, False
    with mutex(project_id):
        events = _project_events(project_id)
        entry = (registry.load(project_id).get("agents") or {}).get(sid) or {}
        new = grupo(events, sid, entry)
        data = lookout_state.read_json(grupos_path(project_id)) or {}
        old = (data.get(sid) or {}).get("grupo")
        if new == old:
            return old, new, False
        avisa = notificar and new in AVISA and ev.get("event") not in NO_AVISA_POR
        data[sid] = {"grupo": new, "ts": time.time(), "por": ev.get("event"), "avisado": avisa}
        lookout_state.write_json(grupos_path(project_id), data)
    if avisa:
        who = (registry.quien(entry) if entry.get("nombre") else "") or ev.get("nombre") or sid[:8]
        title = "lookout: %s %s" % (who, "te necesita" if new == "te_necesita" else "está listo para revisar")
        import digest
        herdr_cli.run(["notification", "show", title[:120], "--body", digest.describe(ev, {sid: who})[:300]], timeout=3)
    return old, new, avisa


# ---------- writes by Bash into another project (V11) ----------

SPLIT = re.compile(r"&&|\|\||[;&|\n]")
WRITERS_ALL = ("rm", "rmdir", "mkdir", "touch", "truncate", "chmod", "chown", "unlink")
WRITERS_LAST = ("cp", "mv", "install", "ln", "rsync")
GIT_WRITES = ("add", "commit", "checkout", "switch", "reset", "restore", "rm", "mv", "apply", "stash", "merge",
              "rebase", "cherry-pick", "revert", "pull", "clean", "tag", "branch", "worktree", "am", "push")


def _abs(tok, cwd):
    tok = os.path.expanduser(tok)
    if "$" in tok or "`" in tok:
        return None
    return os.path.normpath(tok if os.path.isabs(tok) else os.path.join(cwd or "/", tok))


def escrituras_bash(cmd, cwd):
    """Paths a Bash command would write, read from its text (V11: the hook only gets `command`). A heuristic that
    over-reports on purpose: a false hit only produces a warning. Follows `cd` across the parts of one command."""
    cmd = re.sub(r"\\\r?\n", " ", cmd or "")
    out = []
    here = cwd
    for part in SPLIT.split(cmd):
        part = part.strip()
        if not part:
            continue
        for m in re.finditer(r"(?:^|[^<>&0-9])\d?>>?\|?\s*([^\s;&|<>]+)", part):  # > file, >> file, 2> file
            t = m.group(1).strip("'\"")
            if t and not t.startswith("&") and t != "/dev/null":
                out.append(_abs(t, here))
        try:
            toks = shlex.split(re.sub(r"\d?>>?\|?\s*[^\s;&|<>]+", " ", part))
        except ValueError:
            toks = part.split()
        while toks and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]) or toks[0] in ("sudo", "command", "env",
                                                                                   "nohup", "exec", "time")):
            toks = toks[1:]
        if not toks:
            continue
        name = os.path.basename(toks[0])
        args = [t for t in toks[1:] if not t.startswith("-")]
        if name == "cd" and args:
            here = _abs(args[0], here) or here
            out.append(here)  # working inside another project is worth a warning on its own
        elif name in WRITERS_ALL:
            out += [_abs(t, here) for t in args]
        elif name in WRITERS_LAST and len(args) >= 2:
            out.append(_abs(args[-1], here))
        elif name == "tee":
            out += [_abs(t, here) for t in args]
        elif name == "sed" and any(t == "-i" or t.startswith("-i") or t == "--in-place" for t in toks[1:]):
            out += [_abs(t, here) for t in args[1:]]
        elif name == "git":
            i, path, extra = 1, here, []
            while i < len(toks) and toks[i].startswith("-"):
                t = toks[i]
                if t == "-C" and i + 1 < len(toks):
                    path = _abs(toks[i + 1], path) or path
                    i += 2
                elif t in ("--git-dir", "--work-tree") and i + 1 < len(toks):
                    extra.append(_abs(toks[i + 1], path))  # adversary F6: these name the repo that gets written
                    i += 2
                elif t.startswith(("--git-dir=", "--work-tree=")):
                    extra.append(_abs(t.split("=", 1)[1], path))
                    i += 1
                elif t == "-c":
                    i += 2
                else:
                    i += 1
            if i < len(toks) and toks[i] in GIT_WRITES:
                out.append(path)
                out += extra
                if toks[i] == "worktree" and i + 1 < len(toks) and toks[i + 1] in ("add", "move"):
                    # `git worktree add <path>` / `move <wt> <path>`: the new folder is written too
                    rest, j = [], i + 2
                    while j < len(toks):  # options that take a value (-b rama) must not be read as the path
                        t = toks[j]
                        if t in ("-b", "-B", "--reason", "--lock-reason"):
                            j += 2
                            continue
                        if not t.startswith("-"):
                            rest.append(t)
                        j += 1
                    if rest:
                        out.append(_abs(rest[-1] if toks[i + 1] == "move" else rest[0], path))
    seen, res = set(), []
    for p in out:
        if p and p not in seen:
            seen.add(p)
            res.append(p)
    return res

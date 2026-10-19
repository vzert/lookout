"""0.13.0: close the tab of a finished agent (memory/plans/plan-lookout-altas-cierres-relevos.md, Fase 2; research B).

The user's decision (2026-10-15): a finished agent's tab is closed by the supervisor, who tells the user in one line,
after TWO signals and with nothing of the agent left behind. Closing ends its session: every guard below stops it,
and says which one, so the supervisor can pass it to the user.

Signal 1, finished: its last turn says so — a «Como retomar: Ninguno» header (retomar.bloque → "nada"), or a quote the
supervisor gives with --motivo that appears verbatim in that last turn (plan-ciclo: «No emito nada y termino aquí»).
A goalspec [COMPLETION-REVIEW or a task marked terminada alone never count (askuserquestion-pendientes declared
«¿Cerrado? Sí» and still waited for an answer). A live block («hay») is a relief, never a close.
Signal 2, screen: the agent is quiet (deliver.quieto: herdr idle/done, or «working» only because of a background shell
after its Stop), its input box is empty or a suggestion. Live background work goes to the user first (salida).
Guards: no uncommitted change of its own; no local commit of its own not on the remote; no publication of its own
waiting/holding the turn; no open decision naming it; no message of its to the supervisor newer than the last answer to
it; a last turn with no «?», «¿» or «？» (the 0.12.2 rule: a question waits for someone); no background task of its own.
Threat model: an accidental omission (work left behind, a pending answer); not an agent that lies on purpose.
"""
import json
import re
import os
import subprocess
import time

import decisiones
import deliver
import herdr_cli
import lookout_state
import lote
import publica
import registry
import retomar
import salida
import supervisor_md

FIN_TIMEOUT = 60


def _turno(session_id):
    return retomar.ultimo_turno(deliver.transcript_path(session_id))


# 0.13.3: the brake says what to do (live 3-tier 2026-10-16: the supervisor read it and did nothing with the block)
RELEVO_NO_CIERRE = ("su último turno deja un bloque para retomar con trabajo: es un relevo, no un cierre (vigente → "
                    "`lookout relevo`, con --goalspec salvo que sea solo medir, y si no lo relevas, modal con --agentes; ambiguo → modal «¿relevo, cierro o lo dejo?» con --agentes; si el usuario "
                    "contesta que la cierres, repite con --usuario-confirmo dN de una decisión --cierre --si-es)")


def senal_terminado(entry, motivo="", project_id=""):
    """'' if its last turn says it finished, else why not. 0.13.2: a block whose every cited pendiente is closed is
    finished too (the supervise skill recommends closing it; adversary round 2: the close refused it)."""
    text, _ts = _turno(entry["session_id"])
    estado, blk = retomar.bloque(text)
    if estado == "hay":
        r = retomar.para_agente(project_id, entry["session_id"]) if project_id else None
        if r and (r.get("motivo") or "").startswith(retomar.CERRADO):
            return ""
        return RELEVO_NO_CIERRE
    if estado == "nada":
        return ""
    if motivo and motivo.strip() and motivo.strip() in text:  # verbatim (adversary round 1: no whitespace folding)
        return ""
    if motivo:
        return "la cita de --motivo no está tal cual en su último turno"
    return ("su último turno no dice que terminó: ni «Como retomar: Ninguno» ni una cita suya con --motivo (un "
            "[COMPLETION-REVIEW o una tarea terminada solos no bastan)")


def senal_pantalla(entry, project_id=""):
    live = herdr_cli.agent_get(entry["pane_id"]) or {}
    if (live.get("agent_session") or {}).get("value") != entry["session_id"]:
        return "su pane ya no es suyo (registro viejo)"
    if not deliver.quieto(project_id, entry, live):
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


MARGEN_COMMIT = 2  # s around a Bash call: the commit's committer time has a 1 s resolution


def _iso(ts):
    import datetime
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def _llamadas_commit(path, desde):
    """[(start, end)] of the Bash calls in a transcript whose command says «commit» and that ended after `desde`."""
    out, starts = [], {}
    try:
        if os.path.getmtime(path) < desde:
            return out
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return out
    with fh:
        for line in fh:
            if "commit" not in line and '"tool_result"' not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            content = (o.get("message") or {}).get("content")
            t = _iso(o.get("timestamp"))
            if not isinstance(content, list) or t is None:
                continue
            for it in content:
                if not isinstance(it, dict):
                    continue
                if it.get("type") == "tool_use" and it.get("name") == "Bash" and \
                        "commit" in str((it.get("input") or {}).get("command", "")):
                    starts[it.get("id")] = t
                elif it.get("type") == "tool_result" and it.get("tool_use_id") in starts:
                    t0 = starts.pop(it["tool_use_id"])
                    if t >= desde:
                        out.append((t0, t))
    return out


def duenos_commits(project_id, wt, hashes):
    """{hash: set of registered session ids} — 0.13.2. A commit belongs to a session when one of its Bash calls (or one
    of its subagents') whose command says «commit» was running at the commit's time. That covers `-q`, a subagent and a
    script called from such a command, none of which print «[rama hash]» (the reason 0.13.0 stopped matching hashes).
    Measured on 3-tier-memory, 2026-10-15: the 6 unpushed commits of the shared checkout all fell inside calls of one
    session, and of no other. A commit no call covers has no owner and keeps blocking everyone."""
    out = {h: set() for h in hashes}
    if not hashes:
        return out
    code, log = _git(wt, "log", "--no-walk", "--format=%H %ct", *hashes)
    if code != 0:
        return out
    horas = {}
    for linea in (log or "").splitlines():
        partes = linea.split()
        if len(partes) == 2 and partes[1].isdigit():
            horas[partes[0]] = int(partes[1])
    if not horas:
        return out
    desde = min(horas.values()) - MARGEN_COMMIT
    for sid in registry.load(project_id).get("agents", {}):
        path = deliver.transcript_path(sid)
        if not path:
            continue
        rutas = [path] + sorted(glob_subagentes(path, sid))
        llamadas = [c for r in rutas for c in _llamadas_commit(r, desde)]
        for h, ct in horas.items():
            if any(t0 - MARGEN_COMMIT <= ct <= t1 + MARGEN_COMMIT for t0, t1 in llamadas):
                out.setdefault(h, set()).add(sid)
    return out


def glob_subagentes(path, sid):
    import glob
    return glob.glob(os.path.join(os.path.dirname(path), sid, "subagents", "*.jsonl"))


def _patch_ids(wt, args):
    """{commit: patch-id} of `git log -p <args>` (git patch-id --stable: the same change on another base keeps its id)."""
    try:
        log = subprocess.run(["git", "-C", wt, "log", "--no-color", "--no-ext-diff", "-p"] + list(args),
                             capture_output=True, timeout=30)
        ids = subprocess.run(["git", "-C", wt, "patch-id", "--stable"], input=log.stdout, capture_output=True,
                             timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    out = {}
    for linea in ids.stdout.decode("utf-8", "replace").splitlines():
        partes = linea.split()
        if len(partes) == 2:
            out[partes[1]] = partes[0]
    return out


def ramas_destino(wt):
    """The remote refs a commit has to reach to count as upstream (0.13.23, codex review of 0.13.22: a patch on any
    remote ref let a tab close with the commit only on an unrelated branch): each remote's main branch (its HEAD, else
    main or master) and the branch's own upstream."""
    refs = []
    code, up = _git(wt, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if code == 0 and up.strip():
        refs.append(up.strip())
    code, remotos = _git(wt, "remote")
    for r in (remotos or "").split() if code == 0 else []:
        code, cabeza = _git(wt, "symbolic-ref", "--short", "refs/remotes/%s/HEAD" % r)
        # its HEAD first; main and master after it, also when that HEAD names a branch that is gone (round 2, codex)
        candidatas = ([cabeza.strip()] if code == 0 and cabeza.strip() else []) + ["%s/main" % r, "%s/master" % r]
        for c in candidatas:
            if _git(wt, "rev-parse", "--verify", "--quiet", c + "^{commit}")[0] == 0 and c not in refs:
                refs.append(c)
                break
    return refs


def ya_arriba(wt, hashes, dias=30):
    """({hash: remote hash with the same patch}, {hash: remote hash with the same subject and author, another patch}) —
    0.13.22. 3-tier 2026-10-17: the 6 «unpushed» commits of reopen-replay-ts had reached main through a rebased PR; by
    hash they were unpushed, by content 3 were upstream and 3 had a rebased copy. Only ramas_destino, the last `dias`
    days before the oldest of them."""
    if not hashes:
        return {}, {}
    code, log = _git(wt, "log", "--no-walk", "--format=%H%x00%ct%x00%ae%x00%s", *hashes)
    if code != 0:
        return {}, {}
    meta = {}
    for linea in (log or "").splitlines():
        partes = linea.split("\x00")
        if len(partes) == 4 and partes[1].isdigit():
            meta[partes[0]] = (int(partes[1]), partes[2], partes[3])
    if not meta:
        return {}, {}
    refs = ramas_destino(wt)
    if not refs:
        return {}, {}
    since = "--since=@%d" % (min(m[0] for m in meta.values()) - dias * 86400)
    remotos = _patch_ids(wt, refs + ["--no-merges", since])
    por_parche = {pid: h for h, pid in remotos.items()}
    locales = _patch_ids(wt, ["--no-walk"] + list(meta))
    iguales = {h: por_parche[pid] for h, pid in locales.items() if pid in por_parche}
    code, rlog = _git(wt, "log", *refs, "--no-merges", since, "--format=%H%x00%ae%x00%s")
    por_asunto = {}
    for linea in (rlog or "").splitlines() if code == 0 else []:
        partes = linea.split("\x00")
        if len(partes) == 3:
            por_asunto.setdefault((partes[1], partes[2]), partes[0])
    copias = {h: por_asunto[(m[1], m[2])] for h, m in meta.items() if h not in iguales and (m[1], m[2]) in por_asunto}
    return iguales, copias


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
    iguales, copias = ya_arriba(wt, pendientes)  # 0.13.22: already upstream by content, or a rebased copy there
    pendientes = [h for h in pendientes if h not in iguales]
    if not pendientes:
        return ""
    # A commit made with -q, by a subagent or by a script prints no «[rama hash]» in its transcript (3-tier-memory,
    # 2026-10-15: none of the 6 unpushed 2.58.1 commits did), so the printed hash alone would call an agent with
    # unpushed work clean. 0.13.2: the owner is read from the time of its Bash calls (duenos_commits); a commit with
    # no owner still blocks everyone, and one owned only by other sessions no longer blocks this one.
    # A commit stops blocking this agent only when every owner is ANOTHER agent still alive (not relieved, not
    # retired): one of a relieved predecessor is this agent's work to push (adversary round 1 of 0.13.2).
    # A relieved owner's work passes to its successor (relevada_por, followed to the live end of the chain): the
    # successor must push it, and the other agents are free of it (3-tier-memory, 2026-10-15: the 6 commits' owner
    # was relieved while this was being measured).
    sid = entry["session_id"]
    agentes = registry.load(project_id).get("agents", {})

    def actual(s):
        vistos = set()
        while s in agentes and agentes[s].get("relevada_por") and s not in vistos:
            vistos.add(s)
            s = agentes[s]["relevada_por"]
        return s
    crudos = duenos_commits(project_id, wt, pendientes)
    duenos = {h: {actual(s) for s in ss} for h, ss in crudos.items()}

    def vivo_ajeno(s):
        e = agentes.get(s) or {}
        return s != sid and e and not e.get("retirado") and e.get("tarea_estado") not in ("relevada", "relevando")
    rebasados = [h for h in pendientes if h in copias]
    if rebasados:
        _c, rama = _git(wt, "rev-parse", "--abbrev-ref", "HEAD")
        return ("%d commit(s) sin subir en %s con una copia rebasada en el remoto (mismo asunto y autor, otro parche): "
                "%s. No los cuento como trabajo de %s: compáralos con `git range-diff` y pregúntale al usuario qué hacer "
                "con la rama %s" % (len(rebasados), wt, ", ".join("%s → %s" % (h[:7], copias[h][:7]) for h in rebasados[:3])
                                    + (" y %d más" % (len(rebasados) - 3) if len(rebasados) > 3 else ""),
                                    entry.get("nombre"), (rama or "").strip() or "?"))
    suyos = [h for h in pendientes if sid in duenos.get(h, ())]
    if suyos:
        if any(sid in crudos.get(h, ()) for h in suyos):
            return "%d commit(s) suyo(s) sin subir en %s" % (len(suyos), wt)
        # all made by an earlier session of its chain (3-tier 2026-10-17: its first session, before its current task)
        antes = sorted({s for h in suyos for s in crudos.get(h, ()) if s != sid})
        _c, fechas = _git(wt, "log", "--no-walk", "--format=%cs", *suyos)
        dias = sorted(set((fechas or "").split()))
        return "%d commit(s) suyo(s) sin subir en %s, hechos por su sesión anterior %s (%s): primero el push" % (
            len(suyos), wt, ", ".join(s[:8] for s in antes) or "?", " a ".join(dias[:1] + dias[-1:] if len(dias) > 1 else dias))
    frenan = [h for h in pendientes if not duenos.get(h) or not all(vivo_ajeno(s) for s in duenos[h])]
    if frenan:
        return "%d commit(s) sin subir en su árbol %s sin dueño vivo conocido: primero el push" % (len(frenan), wt)
    return ""


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


def guarda_mensaje(project_id, entry, decidido=False):
    marker = lookout_state.read_marker(entry["session_id"]) or {}
    enviado = _ultimo_mensaje_al_supervisor(entry["session_id"], marker.get("address", ""))
    text, _ts = _turno(entry["session_id"])
    if not decidido and any(c in text for c in "?¿？"):
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


def _fallido_desde(project_id, entry):
    """When the relief failed: its stamp, or (state older than 0.13.4) the end event of its session."""
    if entry.get("relevo_fallido_ts"):
        return float(entry["relevo_fallido_ts"])
    events, _ = lookout_state.read_events(project_id, 0)
    ends = [float(ev.get("ts") or 0) for ev in events
            if ev.get("session_id") == entry["session_id"] and ev.get("event") == "end"]
    return max(ends) if ends else None


def revisa_relevo_fallido(project_id, entry, confirmo=""):
    """0.13.4 (adversary r1-r2): a failed relief ended the session and started none, so neither its last turn nor its
    pane can say it finished. A tab the user already closed is his decision; otherwise the decision `confirmo` (dN)
    must be one the user answered yes, opened after the failure and naming the agent, and its pane must hold no other
    session (read from the pane itself: an empty `agent list` after a herdr failure is no evidence)."""
    found, pane = herdr_cli.pane_get(entry["pane_id"])
    if found is False:
        return [], "gone"
    if found is None:
        return ["no puedo preguntarle a herdr por su pane"], ""
    out = []
    sesion = (pane.get("agent_session") or {}).get("value")
    if sesion and sesion != entry["session_id"]:
        out.append("su pane tiene otra sesión (%s)" % sesion[:8])
    desde = _fallido_desde(project_id, entry)
    it = next((x for x in decisiones.load(project_id).get("items") or () if x.get("id") == confirmo), None) if confirmo else None
    if not it or desde is None:
        out.append("un relevo fallido se cierra solo con la decisión del usuario: ábrela con `lookout decision … --abre "
                   "«¿cierro su pestaña?» --agentes %s --cierre --si-es \"<etiqueta del sí>\"`, pregúntala en el modal y "
                   "repite con --usuario-confirmo <id>" % entry.get("nombre"))
    elif not decision_de_cierre(project_id, entry, confirmo, desde):
        out.append("la decisión %s no es un sí del usuario abierto después del fallo que nombre a %s (hace falta "
                   "--cierre y --si-es, y que el usuario elija esa opción en tu modal)" % (confirmo, entry.get("nombre")))
    return out, ""


def revisa(project_id, entry, motivo="", confirmo="", shells=""):
    """The list of reasons not to close ([] = it can be closed). `shells`: the decision (dN) with the user's choice
    for its live background work (0.13.10, salida): with it, the background guard gives way to that choice."""
    if entry.get("tarea_estado") == "relevo-fallido":
        frenos, gone = revisa_relevo_fallido(project_id, entry, confirmo)
        return [] if gone else frenos + [r for r in (g(project_id, entry) for g in GUARDAS) if r]
    out = []
    vivo = salida.shells_vivos(project_id, entry)
    eleccion = salida.eleccion(project_id, entry, shells) if vivo else None
    decidido = cierre_decidido(project_id, entry, confirmo)
    for check in ((lambda: "") if decidido else (lambda: senal_terminado(entry, motivo, project_id)),
                  lambda: senal_pantalla(entry, project_id)):
        r = check()
        if r:
            out.append(r)
    for g in GUARDAS:
        if g is guarda_fondo and vivo:
            continue  # said below, with what /exit would do to it
        r = guarda_mensaje(project_id, entry, decidido) if g is guarda_mensaje else g(project_id, entry)
        if r:
            out.append(r)
    if vivo and not eleccion:
        out.append(salida.pide_modal(entry, vivo) + (
            " (%s no es una elección del usuario, en tu modal, abierta después de su último Stop, que nombre a %s)"
            % (shells, entry.get("nombre")) if shells else ""))
    return out


def cierre_decidido(project_id, entry, confirmo):
    """0.13.9: the user decided to close it: `confirmo` (dN) answered yes by the user in the modal (its answer written
    down by the supervisor's hook), naming this agent. It skips only what reads the agent's own words (finished? a
    question?), which the user already weighed; never the screen, git, a publication, an open decision, an unanswered
    message or a background task. Live 3-tier 2026-10-16: d111 «Cerrarla» and `cierra-pestana` still refused."""
    _text, ts = _turno(entry["session_id"])
    return ts is not None and decision_de_cierre(project_id, entry, confirmo, ts)


def decision_de_cierre(project_id, entry, confirmo, despues_de):
    """dN is the user's yes to closing THIS agent's tab, by structure, never by its words (adversary r3-r4): opened
    as a close (`lookout decision --abre … --cierre`), naming the agent, approved by the modal's hook from the user's
    own choice (`--si-es`; a `--cierra … --si` is the supervisor's word), and opened after `despues_de`."""
    d = decisiones.respondida(project_id, confirmo) if confirmo else None
    return bool(d and d.get("tipo") == "cierre" and d.get("por_hook") and d.get("respuesta_usuario")
                and entry.get("nombre") in (d.get("agentes") or ()) and float(d.get("desde") or 0) > despues_de)




def cierra(project_id, entry, motivo="", fin_timeout=FIN_TIMEOUT, log=print, confirmo="", shells=""):
    """(ok, message for the user)."""
    with lote.project_mutex(project_id):
        fallido = entry.get("tarea_estado") == "relevo-fallido"
        if fallido and revisa_relevo_fallido(project_id, entry, confirmo)[1] == "gone":
            # nothing left to close; the guards cannot stop it, but what they find goes to the user (adversary r2)
            ojo = [r for r in (g(project_id, entry) for g in GUARDAS) if r]
            reg = registry.load(project_id)
            reg["agents"][entry["session_id"]].update(retirado=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                                       retirado_por="relevo fallido: el usuario cerró su pestaña")
            registry.save(project_id, reg)
            publica.retira_sesion(project_id, entry["session_id"], "terminado")
            lookout_state.remove_marker(entry["session_id"])
            return True, "%s: su pestaña ya no existe; lo saco de la tabla.%s" % (
                entry.get("nombre"), (" Díselo al usuario, quedó: " + "; ".join(ojo) + ".") if ojo else "")
        frenos = revisa(project_id, entry, motivo, confirmo, shells)
        if frenos:
            return False, "NO cierro la pestaña de %s: %s." % (entry.get("nombre"), "; ".join(frenos))
        pane = entry["pane_id"]
        ended = fallido  # its session ended in the relief: nothing to /exit
        if not fallido:
            ended, por_que = salida.salir(project_id, entry, salida.eleccion(project_id, entry, shells), fin_timeout, log)
            if not ended and por_que:
                return False, "NO cierro la pestaña de %s: %s." % (entry.get("nombre"), por_que)
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

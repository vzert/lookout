"""0.13.0: the «Como retomar» an agent leaves at the end of its last turn, and what the supervisor does with it
(memory/plans/plan-lookout-altas-cierres-relevos.md, Fase 1; research 2026-10-15, C).

- `bloque(text)` finds the block: a «Como retomar» line or heading, or 3-tier's «🔁 Siguiente sesión — copia y pega:»,
  and the fenced block right after it; «Como retomar: Ninguno …» on the header line itself means nothing to resume.
- `ultimo_turno(path)` reads ONLY the agent's last turn (assistant text since the last real user prompt): an older
  block under a newer message without one is stale (plan-ciclo: a block of 2026-10-07 under its last message).
- `info(...)` gives the `retomar` field of an event: {hay, estado: vigente | ambiguo | nada, pendientes, motivo}.
  vigente = every cited p-id still open in the project's memory/_pendientes.md, no other agent cited them after the
  block, the block is from the last turn and younger than LOOKOUT_RETOMAR_HORAS (24). Anything else with work is
  ambiguo and goes to the user; the relief runs alone only on vigente.
- `config(path)` reads the model (with its window, «claude-opus-5-5[1m]»), effort and permission mode the agent ran
  with, so its relief runs the same way. None for one that cannot be read: then no automatic relief.
"""
import calendar
import json
import os
import re
import time

HEAD_RE = re.compile(r"(?im)^[^\w\n]*(?:como retomar|siguiente sesi[oó]n)\b[^\n]*$|^#+[ \t]*como retomar[^\n]*$")
FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
# «Ninguno», «Nada que retomar», or one of them followed by a dash and its explanation («Ninguno — los tres pendientes
# quedaron cerrados»). Adversary round 1: a prefix match took «Ninguno, salvo que falta desplegar» for finished.
NADA_RE = re.compile(r"(?i)^[^\w]*(?:ninguno|ninguna|nada(?: que retomar)?|none|nothing)[ \t]*(?:[.!]?[ \t]*$|[—–-][ \t])")
PID_RE = re.compile(r"\bp-[0-9a-f]{10}\b")


def horas():
    try:
        return float(os.environ.get("LOOKOUT_RETOMAR_HORAS") or 24)
    except ValueError:
        return 24.0


def bloque(text):
    """(estado, block): "nada" when the header line itself says there is nothing to resume (a «ninguno» in the BODY
    of a block with a live «Proximo paso» does not count), "hay" with the block, "" when there is no block."""
    text = text or ""
    for m in reversed(list(HEAD_RE.finditer(text))):  # the last block of the turn wins
        header = m.group(0)
        inline = header.split(":", 1)[1].strip() if ":" in header else ""
        if inline and NADA_RE.match(inline) and not PID_RE.search(inline):
            return "nada", inline  # a p-id in the explanation means something is still cited: not «nothing»
        rest = text[m.end():]
        f = FENCE_RE.search(rest)
        if f and rest[:f.start()].count("\n") <= 3 and not re.search(r"(?m)^#+\s", rest[:f.start()]):
            return "hay", f.group(1).strip()
        if "como retomar" not in header.lower():
            continue  # «Siguiente sesión» with no fenced block under it is prose, not a block
        if inline and not inline.lower().startswith("copia"):
            return "hay", inline
        nxt = re.search(r"(?m)^#+\s", rest)
        body = (rest[:nxt.start()] if nxt else rest).strip()
        if body:
            return "hay", body
    return "", ""


def _ts(row):
    t = row.get("timestamp") or ""
    try:
        return calendar.timegm(time.strptime(t[:19], "%Y-%m-%dT%H:%M:%S")) if t else None
    except ValueError:
        return None


def _real_prompt(row):
    if row.get("type") != "user" or row.get("isMeta") or row.get("isSidechain"):
        return False
    c = (row.get("message") or {}).get("content")
    if isinstance(c, str):
        return bool(c.strip())
    return isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "text" for b in c)


def ultimo_turno(path):
    """(text of the assistant's last turn, timestamp of its last assistant row or None)."""
    texts, ts = [], None
    try:
        fh = open(path, encoding="utf-8")
    except (OSError, TypeError):
        return "", None
    with fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if _real_prompt(row):
                texts, ts = [], None
                continue
            if row.get("type") != "assistant" or row.get("isSidechain"):
                continue
            c = (row.get("message") or {}).get("content")
            got = [c] if isinstance(c, str) else [b.get("text") for b in c or [] if isinstance(b, dict)
                                                   and b.get("type") == "text" and b.get("text")]
            if got:
                texts += got
                ts = _ts(row) or ts
    return "\n\n".join(texts), ts


def abiertos(raiz):
    """The p-ids open in <raiz>/memory/_pendientes.md, or None if there is no such file."""
    try:
        with open(os.path.join(raiz, "memory", "_pendientes.md"), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None
    out = set()
    for l in lines:
        if l.lstrip().startswith("- [ ]"):
            out |= set(re.findall(r"_id: (p-[0-9a-f]{10})", l))
    return out


def citado_despues(pids, desde, otros):
    """Another agent's transcript names one of `pids` in a row after `desde` (agrupar-pendientes: its p-id was worked
    by askuserquestion-pendientes later). `otros`: transcript paths of the other registered agents."""
    needles = [p.encode() for p in pids]
    for path in otros:
        try:
            fh = open(path, "rb")
        except (OSError, TypeError):
            continue
        with fh:
            for raw in fh:
                if not any(n in raw for n in needles):
                    continue
                try:
                    t = _ts(json.loads(raw))
                except ValueError:
                    continue
                if t is not None and desde is not None and t > desde:
                    return True
    return False


def info(text, ts, raices, otros, ahora=None):
    """The `retomar` field for a turn's text, or None when it has no block."""
    estado, blk = bloque(text)
    if not estado:
        return None
    if estado == "nada":
        return {"hay": False, "estado": "nada", "pendientes": [], "motivo": blk[:160]}
    pids = sorted(set(PID_RE.findall(blk)))
    out = {"hay": True, "estado": "ambiguo", "pendientes": pids, "motivo": ""}
    ahora = ahora or time.time()
    abiertos_ = None
    for r in raices:
        abiertos_ = abiertos(r) if r else None
        if abiertos_ is not None:
            break
    if not pids:
        out["motivo"] = "el bloque no cita ningún pendiente"
    elif ts is None or ahora - ts > horas() * 3600:
        out["motivo"] = "el bloque tiene más de %d h" % horas() if ts else "no sé de cuándo es el bloque"
    elif abiertos_ is None:
        out["motivo"] = "no encuentro memory/_pendientes.md"
    elif any(p not in abiertos_ for p in pids):
        out["motivo"] = "cita un pendiente que ya no está abierto: %s" % ", ".join(p for p in pids if p not in abiertos_)
    elif citado_despues(pids, ts, otros):
        out["motivo"] = "otro agente citó ese pendiente después del bloque"
    else:
        out["estado"] = "vigente"
    return out


def config(path):
    """{"modelo", "esfuerzo", "permisos"} from the agent's transcript; a key is "" when not found."""
    out = {"modelo": "", "esfuerzo": "", "permisos": ""}
    try:
        fh = open(path, "rb")
    except (OSError, TypeError):
        return out
    with fh:
        for raw in fh:
            if b'"identity"' in raw and b'"attachment"' in raw:
                try:
                    att = json.loads(raw).get("attachment") or {}
                except ValueError:
                    att = {}
                if att.get("type") == "model" and (att.get("identity") or {}).get("modelId"):
                    out["modelo"] = att["identity"]["modelId"]
            elif b'"permission-mode"' in raw:
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                if row.get("type") == "permission-mode" and row.get("permissionMode"):
                    out["permisos"] = row["permissionMode"]
            elif b'"effort"' in raw and b'"type":"assistant"' in raw.replace(b": ", b":"):
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                if row.get("type") == "assistant" and isinstance(row.get("effort"), str) and not row.get("isSidechain"):
                    out["esfuerzo"] = row["effort"]
    return out


def para_agente(project_id, session_id, transcript_path=None, cwd=""):
    """The `retomar` field for a registered agent's last turn, or None. The project's memory is looked up in the
    agent's checkout first, then in the supervised roots; the other agents are the registered ones still alive."""
    import deliver
    import lock
    import registry
    path = transcript_path or deliver.transcript_path(session_id)
    text, ts = ultimo_turno(path)
    if not text:
        return None
    reg = registry.load(project_id)
    raices = []
    entry = reg.get("agents", {}).get(session_id) or {}
    for r in [cwd, entry.get("worktree"), entry.get("cwd")] + list((lock.read(project_id) or {}).get("roots") or []):
        if r and r not in raices:
            raices.append(r)
    otros = [deliver.transcript_path(s) for s, e in reg.get("agents", {}).items()
             if s != session_id and not e.get("retirado")]
    return info(text, ts, raices, [o for o in otros if o])


def describe(r):
    """One line for the digest."""
    if not r:
        return ""
    if r.get("estado") == "nada":
        return "terminó: su «Como retomar» dice que no queda nada (%s)" % r.get("motivo", "")[:100]
    pend = ", ".join(r.get("pendientes") or []) or "sin pendiente"
    return "dejó un bloque para retomar (%s, %s%s)" % (pend, r.get("estado"),
                                                         ": " + r["motivo"] if r.get("motivo") else "")


def al_registrar(project_id, sessions):
    """Registering an agent that is already idle gives it no Stop afterwards (cambio-worktrees, 3-tier-memory: it
    never had a turn after `inicia`), so its last turn is read now and a `retomar` event wakes the supervisor. Once per
    block: the entry keeps the block's text it already announced. Returns the events written."""
    import lookout_state
    import lote
    import registry
    leidos = {}
    for sid in sessions:  # the slow part (transcripts) outside the project mutex
        e = registry.load(project_id).get("agents", {}).get(sid) or {}
        if e and not e.get("retirado") and e.get("estado_herdr") in ("idle", "done"):
            leidos[sid] = para_agente(project_id, sid)
    out = []
    with lote.project_mutex(project_id):  # registry.json: the same mutex as relevo, cierra-pestana and lanza
        reg = registry.load(project_id)
        for sid, r in leidos.items():
            e = reg.get("agents", {}).get(sid) or {}
            if not r or not e or e.get("retirado"):
                continue
            firma = "%s|%s|%s" % (r.get("estado"), ",".join(r.get("pendientes") or []), r.get("motivo", ""))
            if e.get("retomar_avisado") == firma:
                continue
            e["retomar_avisado"] = firma
            ev = {"event": "retomar", "session_id": sid, "nombre": e.get("nombre", ""), "pane": e.get("pane_id", ""),
                  "hook": "registro", "retomar": r}
            lookout_state.append_event(project_id, ev)
            out.append(ev)
        if out:
            registry.save(project_id, reg)
    return out

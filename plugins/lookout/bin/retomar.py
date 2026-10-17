"""0.13.0: the «Como retomar» an agent leaves at the end of its last turn, and what the supervisor does with it
(memory/plans/plan-lookout-altas-cierres-relevos.md, Fase 1; research 2026-10-15, C).

- `bloque(text)` finds the block: a «Como retomar» line or heading, or 3-tier's «🔁 Siguiente sesión — copia y pega:»,
  and the fenced block right after it; «Como retomar: Ninguno …» on the header line itself means nothing to resume.
- `ultimo_turno(path)` reads ONLY the agent's last turn (assistant text since the last real user prompt): an older
  block under a newer message without one is stale (plan-ciclo: a block of 2026-10-07 under its last message).
- `info(...)` gives the `retomar` field of an event: {hay, estado: vigente | ambiguo | nada, pendientes, motivo}.
  0.13.2, the user's rule (2026-10-15): a block that is still valid and whose work nobody took is relieved by
  default. vigente = at least one cited p-id still open in the project's memory/_pendientes.md (the closed ones are
  dropped) and no other registered session, retired and relieved ones and their subagents included, worked on an open
  one after the block (`trabajado_despues`: a command, edit, message or task of its names it; a mention in a pasted
  prompt, a hook's context, a Read, a Grep or a question is not work). Its age no longer matters. Ambiguo (to the
  user): no p-id, no memory/_pendientes.md, no timestamp, another session worked on it, every cited p-id closed
  (`CERRADO`, which `cierra-pestana` accepts as finished), or none open and some found nowhere in the memory (e.g. a
  pendiente.add not compacted yet). Closed = «- [x]» or listed in memory/pendientes/_resueltos.md or _caducados.md.
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
# a block that opens with the word, whatever comes after it (adversary r4: «Ninguno, p-…», «Ninguno: p-…»,
# «**Ninguno** — p-…» and a no-break space were read as a normal relief)
NINGUNO_RE = re.compile(r"(?i)^[\W_]*(?:ninguno|ninguna|nada|none|nothing)(?![^\W_])")  # «_Ninguno_» too (r5)
CERRADO = "todo lo que cita ya está cerrado"  # an ambiguo block the close treats as finished (retiro.senal_terminado)
NINGUNO_CITA = "dice «Ninguno» pero cita pendientes: pregúntale al usuario si lo cierras o lo relevas"
PID_RE = re.compile(r"\bp-[0-9a-f]{10}\b")


def bloque(text):
    """(estado, block): "nada" when the header line itself says there is nothing to resume (a «ninguno» in the BODY
    of a block with a live «Proximo paso» does not count), "hay" with the block, "" when there is no block."""
    text = text or ""
    for m in reversed(list(HEAD_RE.finditer(text))):  # the last block of the turn wins
        header = m.group(0)
        rest = text[m.end():]
        if "como retomar" in header.lower():
            # 0.13.9 (adversary r5): what follows the words, after any colon, dash or formatting («## Como retomar —
            # Ninguno», «**Como retomar** — Ninguno, p-…» lost it)
            inline = re.sub(r"^[\W_]+", "", re.split(r"(?i)como retomar", header, 1)[1]).strip()
        else:
            inline = header.split(":", 1)[1].strip() if ":" in header else ""
        if inline and NADA_RE.match(inline):
            if not PID_RE.search(inline) and not PID_RE.search(rest):
                return "nada", inline  # a p-id cited anywhere after it means something is still cited: not «nothing»
            if not PID_RE.search(inline):  # 0.13.9 (r5): «Ninguno.» and the pendiente on the next line
                nxt = re.search(r"(?m)^#+\s", rest)
                return "hay", (inline + "\n" + (rest[:nxt.start()] if nxt else rest)).strip()
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


def cerrados(raiz):
    """The p-ids closed in <raiz>'s memory: «- [x]» lines of memory/_pendientes.md, and every id in
    memory/pendientes/_resueltos.md and _caducados.md (where 3-tier moves a resolved or expired pendiente). 0.13.2,
    adversary: an id missing from the open list is not closed (a pendiente.add not yet compacted is missing too)."""
    out = set()
    try:
        with open(os.path.join(raiz, "memory", "_pendientes.md"), encoding="utf-8") as fh:
            for l in fh:
                if l.lstrip().lower().startswith("- [x]"):
                    out |= set(re.findall(r"_id: (p-[0-9a-f]{10})", l))
    except OSError:
        pass
    for nombre in ("_resueltos.md", "_caducados.md"):
        try:
            with open(os.path.join(raiz, "memory", "pendientes", nombre), encoding="utf-8") as fh:
                out |= set(re.findall(r"_id: (p-[0-9a-f]{10})", fh.read()))
        except OSError:
            pass
    return out


TRABAJO = ("Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "SendMessage", "Agent", "Task")


def trabajado_despues(pids, desde, otros):
    """The p-ids of `pids` another agent worked on after `desde`: an assistant row of its transcript (its subagents'
    included) with a tool call whose input names it — a command, an edit, a message. 0.13.2: 0.13.0 counted any row
    that named it, and on 3-tier-memory (2026-10-15) a resume prompt pasted into another session («Si ese paso es corto,
    suma en la misma sesion: p-01dfac8763») made a live block ambiguous; the supervisor then asked the user about 5
    blocks instead of relieving. `otros`: transcript paths of the other registered agents (their subagents' are read
    too)."""
    import glob
    needles = [p.encode() for p in pids]
    out = set()
    rutas = []
    for path in otros:
        if path:
            sid = os.path.basename(path)[:-len(".jsonl")]
            rutas += [path] + sorted(glob.glob(os.path.join(os.path.dirname(path), sid, "subagents", "*.jsonl")))
    for path in rutas:
        try:
            fh = open(path, "rb")
        except (OSError, TypeError):
            continue
        with fh:
            for raw in fh:
                if b'"tool_use"' not in raw or not any(n in raw for n in needles):
                    continue
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                t = _ts(row)
                if row.get("type") != "assistant" or t is None or desde is None or t <= desde:
                    continue
                for b in (row.get("message") or {}).get("content") or []:
                    # codex, 0.13.2: Read, Grep or a question naming it is not work; a command, an edit, a message or
                    # a delegated task is
                    if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in TRABAJO:
                        txt = json.dumps(b.get("input"), ensure_ascii=False)
                        out |= {p for p in pids if p in txt}
    return out


def info(text, ts, raices, otros, ahora=None):
    """The `retomar` field for a turn's text, or None when it has no block."""
    estado, blk = bloque(text)
    if not estado:
        return None
    if estado == "nada":
        return {"hay": False, "estado": "nada", "pendientes": [], "motivo": blk[:160]}
    pids = sorted(set(PID_RE.findall(blk)))
    import hashlib
    out = {"hay": True, "estado": "ambiguo", "pendientes": pids, "motivo": "",
           "bloque_id": hashlib.sha1(blk.encode("utf-8")).hexdigest()[:12]}
    abiertos_, cerrados_ = None, set()
    for r in raices:
        abiertos_ = abiertos(r) if r else None
        if abiertos_ is not None:
            cerrados_ = cerrados(r)
            break
    if not pids:
        out["motivo"] = "el bloque no cita ningún pendiente"
        return out
    if abiertos_ is None:
        out["motivo"] = "no encuentro memory/_pendientes.md"
        return out
    if ts is None:
        out["motivo"] = "no sé de cuándo es el bloque"
        return out
    vivos = [p for p in pids if p in abiertos_]
    cerrados_l = [p for p in pids if p not in abiertos_ and p in cerrados_]
    perdidos = [p for p in pids if p not in abiertos_ and p not in cerrados_]
    if not vivos and not perdidos:  # every p-id closed: the user decides (usually closing it); none left to list
        out["pendientes"] = []
        out["motivo"] = "%s: %s" % (CERRADO, ", ".join(cerrados_l))
        return out
    if NINGUNO_RE.match(blk):
        # 0.13.9, the user's rule: a «Ninguno» that cites a pendiente still open is neither a relief nor a close on its
        # own, whatever its words; it goes to the user's modal (3-tier 2026-10-16: «Ninguno — … (p-f8df9ea916) espera a
        # que se acumulen cierres, con recordatorio el 2026-10-22» was relieved as vigente; reading «it only waits for a
        # date» from the text let through ten wordings with work left, adversary round 3)
        out["motivo"] = NINGUNO_CITA
        return out
    if not vivos:  # e.g. a pendiente.add not compacted yet: neither open nor closed
        out["motivo"] = "no encuentro en la memoria: %s" % ", ".join(perdidos)
        return out
    out["pendientes"] = vivos
    nota = "; ".join(x for x in ("ya cerrados: %s" % ", ".join(cerrados_l) if cerrados_l else "",
                                 "no encuentro: %s" % ", ".join(perdidos) if perdidos else "") if x)
    trabajados = trabajado_despues(vivos, ts, otros)
    if trabajados:
        out["motivo"] = "otro agente trabajó %s después del bloque" % ", ".join(sorted(trabajados)) + (
            "; " + nota if nota else "")
    else:
        out["estado"] = "vigente"
        out["motivo"] = nota
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
    # every other registered session, retired and relieved ones too: their work after the block counts (codex, 0.13.2)
    otros = [deliver.transcript_path(s) for s in reg.get("agents", {}) if s != session_id]
    return info(text, ts, raices, [o for o in otros if o])


def describe(r):
    """One line for the digest."""
    if not r:
        return ""
    if r.get("estado") == "nada":
        return "terminó: su «Como retomar» dice que no queda nada (%s)" % r.get("motivo", "")[:100]
    pend = ", ".join(r.get("pendientes") or []) or "sin pendiente"
    # 0.13.3: what to do goes before the motive, which clip() may cut (live 3-tier 2026-10-16: «ambiguo: otro agente
    # trabajó…» and no modal); the motive closes the line
    return "dejó un bloque para retomar (%s, %s) → %s%s" % (pend, r.get("estado"), accion(r),
                                                              ": " + r["motivo"] if r.get("motivo") else "")


def accion(r):
    """What the supervisor does with a block (the supervise skill's rule, in the line it reads)."""
    if (r or {}).get("estado") == "vigente":
        return "lookout relevo"
    if ((r or {}).get("motivo") or "").startswith(CERRADO):
        return "lookout cierra-pestana (terminó)"
    return "modal «¿relevo, cierro o lo dejo?»"


def firma(r):
    """What identifies one announced block: its text (bloque_id) and what lookout made of it."""
    return "%s|%s|%s|%s" % (r.get("estado"), ",".join(r.get("pendientes") or []), r.get("motivo", ""),
                            r.get("bloque_id", ""))


def ultimos_avisos(project_id, sessions):
    """{session: firma of the last `retomar` its events carried} (a Stop's idle or a retomar event), "" when none."""
    import lookout_state
    out = {s: "" for s in sessions}
    try:
        fh = open(lookout_state.events_path(project_id), encoding="utf-8", errors="replace")
    except OSError:
        return out
    with fh:
        for line in fh:
            if '"retomar"' not in line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("session_id") in out and isinstance(ev.get("retomar"), dict):
                out[ev["session_id"]] = firma(ev["retomar"])
    return out


def al_registrar(project_id, sessions, estados=None, hook="registro"):
    """Registering an agent that is already idle gives it no Stop afterwards (cambio-worktrees, 3-tier-memory: it
    never had a turn after `inicia`), so its last turn is read now and a `retomar` event wakes the supervisor. Once per
    block: the entry keeps the block's text it already announced. Returns the events written.
    `estados` ({session: herdr status}) overrides the registry's, which is the status at registration (0.13.2 sweep)."""
    import lookout_state
    import lote
    import registry
    leidos = {}
    for sid in sessions:  # the slow part (transcripts) outside the project mutex
        e = registry.load(project_id).get("agents", {}).get(sid) or {}
        estado = (estados or {}).get(sid) if estados is not None else e.get("estado_herdr")
        if e and not e.get("retirado") and estado in ("idle", "done"):
            leidos[sid] = para_agente(project_id, sid)
    ya = ultimos_avisos(project_id, leidos)  # 0.13.2: a block its own Stop already announced is not announced again
    out = []
    with lote.project_mutex(project_id):  # registry.json: the same mutex as relevo, cierra-pestana and lanza
        reg = registry.load(project_id)
        for sid, r in leidos.items():
            e = reg.get("agents", {}).get(sid) or {}
            if not r or not e or e.get("retirado"):
                continue
            f = firma(r)
            if e.get("retomar_avisado") == f or ya[sid] == f:
                continue
            e["retomar_avisado"] = f
            ev = {"event": "retomar", "session_id": sid, "nombre": e.get("nombre", ""), "pane": e.get("pane_id", ""),
                  "hook": hook, "retomar": r}
            lookout_state.append_event(project_id, ev)
            out.append(ev)
        if out:
            registry.save(project_id, reg)
    return out

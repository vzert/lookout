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
- 0.13.52: `para_agente` also reads the «## Como retomar» of the session file the agent wrote (`de_ficha`) when its
  last turn has no block or says «Ninguno»: an open pendiente there is its thread (vigente, or ambiguo when another
  agent worked it), so «Ninguno» in the last turn is not «nothing to resume» then. «Ninguno» + an «Opcional — otra
  sesión» section citing an open pendiente is ambiguo (OPCIONAL). A block whose open pendientes are all `_bloqueado`
  is ambiguo, not vigente.
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
# 0.13.52: no \b at the end. 3-tier's snippet writes «_id: p-c3ac998a95_» (markdown italics), and the «_» after the id
# is a word character, so \b found no p-id in «Como retomar: Ninguno — …» + «➕ Opcional — otra sesión … _id: p-…_» and
# read it as finished (3-tier-memory, 2026-11-07: «claude» was closed with that block in its last turn)
PID_RE = re.compile(r"(?<![0-9A-Za-z-])p-[0-9a-f]{10}(?![0-9A-Za-z])")
# 0.13.52: 3-tier's «➕ Opcional — otra sesión, si tienes tiempo:» after a «Como retomar: Ninguno»: work the session
# suggests, not work it left. The user's rule (2026-11-07): it is not relieved on its own and not closed silently either;
# when it cites a pendiente still open it goes to the user's modal, «Reiniciarlo para que siga» recommended.
OPC_RE = re.compile(r"(?im)^[^\w\n]*opcional\b[^\n]*$")
OPCIONAL = "solo deja un bloque «Opcional — otra sesión»: modal, con «Reiniciarlo para que siga» recomendado"


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
        fh = open(path, encoding="utf-8", errors="replace")
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


def bloqueados(raiz):
    """0.13.52: the open p-ids of <raiz>/memory/_pendientes.md that carry a «_bloqueado: …_» field (they wait for
    something outside the session: an install, a real close elsewhere). A relief cannot move them, so a block citing
    only those is not vigente (codex r1: relieving p-7a1fce0e68 would loop)."""
    out = set()
    try:
        with open(os.path.join(raiz, "memory", "_pendientes.md"), encoding="utf-8") as fh:
            for l in fh:
                if l.lstrip().startswith("- [ ]") and "_bloqueado:" in l:
                    out |= set(re.findall(r"_id: (p-[0-9a-f]{10})", l))
    except OSError:
        pass
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


def solo_opcional(blk, pids):
    """0.13.52: True when every p-id of a «Ninguno» block is cited from its «Opcional» line on (that line included,
    adversary r1: «➕ Opcional — otra sesión: seguir con p-…» on one line)."""
    m = OPC_RE.search(blk)
    return bool(m and pids) and not PID_RE.search(blk[:m.start()])


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
    abiertos_, cerrados_, bloqueados_ = None, set(), set()
    for r in raices:
        abiertos_ = abiertos(r) if r else None
        if abiertos_ is not None:
            cerrados_, bloqueados_ = cerrados(r), bloqueados(r)
            break
    if not pids:
        out["motivo"] = "el bloque no cita ningún pendiente"
        return out
    opcional = bool(NINGUNO_RE.match(blk)) and solo_opcional(blk, pids)
    if abiertos_ is None:
        # 0.13.52, the user's decision: an «Opcional» section that cannot be checked goes to the modal too
        out["motivo"] = "no encuentro memory/_pendientes.md" + ("; " + OPCIONAL if opcional else "")
        return out
    if ts is None:
        out["motivo"] = "no sé de cuándo es el bloque"
        return out
    vivos = [p for p in pids if p in abiertos_]
    cerrados_l = [p for p in pids if p not in abiertos_ and p in cerrados_]
    perdidos = [p for p in pids if p not in abiertos_ and p not in cerrados_]
    if opcional and not vivos and not perdidos:
        # 0.13.52: «Ninguno» and an «Opcional» section whose every pendiente is closed: finished. One found in no
        # memory file goes to the modal (the user's decision, 2026-11-07: what cannot be checked is asked)
        return {"hay": False, "estado": "nada", "pendientes": [], "motivo": blk[:160]}
    if not vivos and not perdidos:  # every p-id closed: the user decides (usually closing it); none left to list
        out["pendientes"] = []
        out["motivo"] = "%s: %s" % (CERRADO, ", ".join(cerrados_l))
        return out
    if NINGUNO_RE.match(blk):
        # 0.13.9, the user's rule: a «Ninguno» that cites a pendiente still open is neither a relief nor a close on its
        # own, whatever its words; it goes to the user's modal (3-tier 2026-10-16: «Ninguno — … (p-f8df9ea916) espera a
        # que se acumulen cierres, con recordatorio el 2026-10-22» was relieved as vigente; reading «it only waits for a
        # date» from the text let through ten wordings with work left, adversary round 3)
        out["motivo"] = OPCIONAL if opcional else NINGUNO_CITA
        if opcional:
            out["pendientes"] = vivos + perdidos
        return out
    if not vivos:  # e.g. a pendiente.add not compacted yet: neither open nor closed
        out["motivo"] = "no encuentro en la memoria: %s" % ", ".join(perdidos)
        return out
    out["pendientes"] = vivos
    nota = "; ".join(x for x in ("ya cerrados: %s" % ", ".join(cerrados_l) if cerrados_l else "",
                                 "no encuentro: %s" % ", ".join(perdidos) if perdidos else "") if x)
    trabajados = trabajado_despues(vivos, ts, otros)
    libres = [p for p in vivos if p not in bloqueados_]
    if not libres:
        out["motivo"] = "solo cita pendientes bloqueados (esperan algo de fuera): %s" % ", ".join(vivos) + (
            "; " + nota if nota else "")
    elif trabajados:
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


def para_agente(project_id, session_id, transcript_path=None, cwd="", ultimo=None):
    """The `retomar` field for a registered agent's last turn, or None. The project's memory is looked up in the
    agent's checkout first, then in the supervised roots; the other agents are the registered ones still alive.
    `ultimo` is the turn's last message as the Stop hook got it (last_assistant_message)."""
    import deliver
    import lock
    import registry
    path = transcript_path or deliver.transcript_path(session_id)
    text, ts = ultimo_turno(path)
    if ultimo and ultimo.strip() and not " ".join(text.split()).endswith(" ".join(ultimo.split())):
        # 0.13.40 (p-fab08d3d95, banco 2026-10-19): the Stop hook read the transcript before Claude Code wrote the
        # turn's last row (127 ms after it was created): no block, or the previous turn's one. The hook's message is
        # the end of this turn; it ends now.
        text, ts = ultimo, time.time()
    if not text:
        return None
    reg = registry.load(project_id)
    raices = []
    entry = reg.get("agents", {}).get(session_id) or {}
    for r in [cwd, entry.get("worktree"), entry.get("cwd")] + list((lock.read(project_id) or {}).get("roots") or []):
        if r and r not in raices:
            raices.append(r)
    # every other registered session, retired and relieved ones too: their work after the block counts (codex, 0.13.2)
    otros = [o for o in (deliver.transcript_path(s) for s in reg.get("agents", {}) if s != session_id) if o]
    r = info(text, ts, raices, otros)
    if r is None or r.get("estado") == "nada":
        f = de_ficha(path, raices, otros)
        if f:
            return f
    return r


SESION_RE = re.compile(r"(?:^|/)memory/sessions/[^/]+\.md$")
COMO_RETOMAR_RE = re.compile(r"(?ms)^##[ \t]*Como retomar[^\n]*\n(.*?)(?=^##[ \t]|\Z)")


SID_RE = re.compile(r"(?m)^session_id:[ \t]*([0-9a-f-]{8,})")


def ficha_de(path):
    """0.13.52: (path, timestamp, its «Como retomar» text) of the last session file (memory/sessions/<slug>.md) this
    transcript wrote or edited with Write, Edit or MultiEdit, or ("", None, ""). Its «## Como retomar» is the durable
    resume block 3-tier's checkpoint leaves; the agent's later turns need not repeat it. A file whose frontmatter names
    another session_id is skipped (an agent that edited an older session's file, e.g. a backfill)."""
    cands = []
    try:
        fh = open(path, "rb")
    except (OSError, TypeError):
        return "", None, ""
    with fh:
        for raw in fh:
            if b'"tool_use"' not in raw or b"memory/sessions/" not in raw:
                continue
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if row.get("type") != "assistant" or row.get("isSidechain"):
                continue
            for b in (row.get("message") or {}).get("content") or []:
                if not (isinstance(b, dict) and b.get("type") == "tool_use"
                        and b.get("name") in ("Write", "Edit", "MultiEdit")):
                    continue
                fp = str((b.get("input") or {}).get("file_path") or "")
                if SESION_RE.search(fp):
                    cands.append((fp, _ts(row)))
    sid = os.path.basename(path or "")[:-len(".jsonl")] if str(path or "").endswith(".jsonl") else ""
    vistos = set()
    for fp, ts in reversed(cands):
        if fp in vistos:
            continue
        vistos.add(fp)
        try:
            with open(fp, encoding="utf-8") as fh:
                body = fh.read()
        except OSError:
            continue
        m = SID_RE.search(body[:2000])
        if m and sid and m.group(1) != sid:
            continue
        ts = max(t for f, t in cands if f == fp and t is not None) if any(f == fp and t for f, t in cands) else ts
        c = COMO_RETOMAR_RE.search(body)
        if not c:
            return fp, ts, ""
        f = FENCE_RE.search(c.group(1))
        return fp, ts, (f.group(1) if f else c.group(1)).strip()
    return "", None, ""


def de_ficha(path, raices, otros):
    """0.13.52: the `retomar` of the agent's session file when its last turn has no block or says «Ninguno», and that
    file's «## Como retomar» still cites a pendiente open in the project that nobody else took (vigente), or one another
    agent worked on after it (ambiguo, to the user). None otherwise: a file whose block is «Ninguno», cites nothing open,
    or cannot be read changes nothing. 3-tier-memory, 2026-11-07: «Proximo paso» left p-1453f5b773 in the «Como
    retomar» of memory/sessions/2026-10-28-medir-userpromptsubmit-comando.md, its last turn only said «termino aquí», and
    the supervisor closed its tab with --motivo («no dejó nada pendiente»). The user's rule: a session that leaves a
    pendiente of its own open is relieved, without asking, until its thread is empty."""
    fp, ts, texto = ficha_de(path)
    if not fp or not texto or NINGUNO_RE.match(texto):
        return None
    r = info("## Como retomar\n" + texto, ts, raices, otros)
    if not r or not r.get("pendientes"):
        return None
    if r.get("estado") != "vigente" and not (r.get("motivo") or "").startswith(("otro agente trabajó",
                                                                                 "solo cita pendientes bloqueados")):
        return None
    r["ficha"] = fp
    r["texto"] = texto
    r["motivo"] = "; ".join(x for x in ("su ficha %s lo deja abierto" % os.path.basename(fp), r.get("motivo")) if x)
    return r


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
        # 0.13.32: not relieving it is a modal, never a held agent and a question in prose (live 3-tier 2026-10-19)
        return "lookout relevo (--goalspec salvo que sea solo medir); si no lo relevas, modal con --agentes, sin cerrarla"
    if ((r or {}).get("motivo") or "").startswith(CERRADO):
        return "lookout cierra-pestana (terminó)"
    return "modal «¿Lo reinicio para que siga, cierro su pestaña o lo dejo?»"


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

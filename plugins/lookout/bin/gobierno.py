"""goalspec governance for one agent's task (docs/plan.md 3.9, F3).

The supervisor asks this script, never its own memory, whether an agent may take a step:
  - push: the LAST adversary verdict the agent quoted must be `hold`. Nothing more: which model and which backends
    a round needs is goalspec's policy, not lookout's (user's decision 2026-10-07: lookout coordinates and
    supervises; the adversary rules live in goalspec, so they are kept in one place). Before 0.10.0 lookout also
    refused a hold from the agent's own model (MISMO-MODELO); goalspec's own gates are the place for that;
  - otra ronda: rounds are capped (5 by default); the 6th needs the user's yes, recorded here.

Source of truth: the agent's own transcript (V8), read the way goalspec's own gate reads it —
verdict and model markers only count in what the agent itself wrote — its assistant text and the
message of its own SendMessage — each on its own line, never in a tool result (a verdict that only came back as a subagent's output was never quoted, and goalspec's
push precheck in the agent would refuse it anyway). A round = one adversary run the agent started:
a `goal-adversary` subagent spawn or a Bash call of `external-adversary.sh`. Rounds add up over every
session that held the same task (a relieved agent keeps its count). counters.json only keeps what
the transcript cannot say: the user's extension of the cap, and the last reading (for the digest).
"""
import json
import os
import re
import time

import deliver
import lookout_state
import registry
import requisitos

LIMITE_RONDAS = 5
VERDICT_RE = re.compile(r"^\s*\[ADVERSARY-VERDICT:\s*(break|hold)\s+ungrounded=(\d+)\s+unfalsified=(\d+)\s+"
                        r"incomplete=(\d+)\s+autonomy-violations=(\d+)\s+unsafe=(\d+)\s*\]\s*$", re.M | re.I)
MODEL_RE = re.compile(r"^\s*\[ADVERSARY-MODEL:\s*(.*?)\]\s*$", re.M | re.I)
CR_RE = re.compile(r"^\s*\[COMPLETION-REVIEW:\s*(adversary|none)\b([^\]]*)\]\s*$", re.M | re.I)


# ---------- reading one transcript ----------

def read_items(path):
    """Ordered items of a transcript: ('text', str) for assistant text, ('round', how) per adversary run."""
    items = []
    try:
        fh = open(path, encoding="utf-8")
    except (OSError, TypeError):
        return items
    with fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") != "assistant":
                continue
            content = (ev.get("message") or {}).get("content")
            if isinstance(content, str):
                items.append(("text", content))
                continue
            for blk in content if isinstance(content, list) else []:
                if not isinstance(blk, dict):
                    continue
                if blk.get("type") == "text" and blk.get("text"):
                    items.append(("text", blk["text"]))
                elif blk.get("type") == "tool_use":
                    inp = blk.get("input") or {}
                    if blk.get("name") in ("Agent", "Task") and "goal-adversary" in str(inp.get("subagent_type", "")):
                        items.append(("round", "subagente"))
                    elif blk.get("name") == "Bash" and "external-adversary.sh" in str(inp.get("command", "")):
                        items.append(("round", "externo"))
                    elif blk.get("name") == "SendMessage" and isinstance(inp.get("message"), str):
                        # the agent's report to the supervisor is its own words too (a tool INPUT it wrote,
                        # not a tool result): seen 2026-10-02, a haiku agent quoted its verdict only there
                        items.append(("text", inp["message"]))
    return items


def scan(path):
    """-> dict: rondas, veredictos [{veredicto, unsafe, ..., modelo}], completion (last), in order."""
    rondas = {"subagente": 0, "externo": 0}
    verdicts, last_model, completion = [], "", ""
    for kind, val in read_items(path):
        if kind == "round":
            rondas[val] += 1
            continue
        # walk markers in text order so a verdict pairs with the model line quoted before it IN THE SAME TEXT:
        # a model line from an older round must not vouch for a later verdict (adversary round 1)
        last_model = ""
        marks = sorted([(m.start(), "m", m) for m in MODEL_RE.finditer(val)] +
                       [(m.start(), "v", m) for m in VERDICT_RE.finditer(val)] +
                       [(m.start(), "c", m) for m in CR_RE.finditer(val)], key=lambda t: t[0])
        for _pos, tag, m in marks:
            if tag == "m":
                last_model = m.group(1).strip()
            elif tag == "v":
                g = m.groups()
                verdicts.append({"veredicto": g[0].lower(), "ungrounded": int(g[1]), "unfalsified": int(g[2]),
                                 "incomplete": int(g[3]), "autonomy": int(g[4]), "unsafe": int(g[5]),
                                 "modelo": last_model, "linea": m.group(0).strip()})
            else:
                completion = m.group(0).strip()
    return {"rondas": rondas, "veredictos": verdicts, "completion": completion}


# ---------- one task, every session that held it ----------

def counters_path(project_id):
    return os.path.join(lookout_state.project_dir(project_id), "counters.json")


def load_counters(project_id):
    """{"tareas": {task: {rondas, limite, ultimo, ...}}}. Up to 0.7.2 heuristicas.py also wrote this file and replaced
    it whole ({"ts", "agentes"}), so an older file may lack "tareas": start it again and drop those keys. A limit the
    user raised before that overwrite is gone; `lookout gobierno --usuario-amplia` raises it again."""
    data = lookout_state.read_json(counters_path(project_id)) or {}
    if not isinstance(data, dict):
        data = {}
    data.pop("agentes", None)
    data.pop("ts", None)
    if not isinstance(data.get("tareas"), dict):
        data["tareas"] = {}
    return data


def task_key(entry):
    return entry.get("tarea") or ("sesion:" + entry["session_id"])


def sessions_of_task(reg, entry):
    """The task's sessions, oldest first (a relieved agent's predecessors count too)."""
    if not entry.get("tarea"):
        return [entry]
    same = [e for e in reg.get("agents", {}).values() if e.get("tarea") == entry["tarea"]]
    return sorted(same, key=lambda e: e.get("alta", ""))


def executor_model(project_id, session_id, entry=None):
    """The agent's model as its SessionStart reported it (the id Claude Code runs), else the launch flag."""
    model = ""
    for ev in lookout_state.read_events(project_id, 0)[0]:
        if ev.get("session_id") == session_id and ev.get("event") == "start" and ev.get("modelo"):
            model = ev["modelo"]
    return model or (entry or {}).get("modelo", "")


def estado(project_id, entry, projects_dir=None, guardar=True):
    reg = registry.load(project_id)
    sessions = sessions_of_task(reg, entry)
    total = {"subagente": 0, "externo": 0}
    verdicts, completion = [], ""
    for e in sessions:
        s = scan(deliver.transcript_path(e["session_id"], projects_dir))
        for k in total:
            total[k] += s["rondas"][k]
        verdicts += s["veredictos"]
        completion = s["completion"] or completion
    model = executor_model(project_id, entry["session_id"], entry)
    key = task_key(entry)
    c = load_counters(project_id)
    t = c["tareas"].setdefault(key, {})
    limite = int(t.get("limite", LIMITE_RONDAS))
    rondas = total["subagente"] + total["externo"]
    last = verdicts[-1] if verdicts else None
    if guardar:  # a read-only check (publica.caducada) must not write
        t.update(rondas=rondas, ultimo=(last or {}).get("linea", ""), modelo_ejecutor=model, leido=time.time())
        lookout_state.write_json(counters_path(project_id), c)
    return {"tarea": key, "rondas": rondas, "por_backend": total, "limite": limite, "ultimo": last,
            "veredictos": len(verdicts), "modelo_ejecutor": model, "completion": completion,
            "sesiones": [e["session_id"] for e in sessions], "goalspec": goalspec_de(entry)}


def goalspec_de(entry):
    """Is goalspec installed for the agent's project? (Fase 7: without it there is no verdict to wait for.)"""
    wt = entry.get("worktree") or entry.get("cwd") or ""
    roots = lookout_state.worktree_roots(wt) if wt else []
    return requisitos.goalspec_instalado(roots[0] if roots else wt)


def decide_push(st):
    """(ok, code, text). code: OK | SIN-GOALSPEC | SIN-VEREDICTO | BREAK."""
    last = st["ultimo"]
    if not last and st.get("goalspec") is False:
        return True, "SIN-GOALSPEC", ("SIN-GOALSPEC: goalspec no está instalado para este proyecto, así que no hay "
                                      "veredicto del adversario que leer. Sigue con `lookout publica` y dile al usuario, "
                                      "en la pregunta del push, que este push NO tuvo revisión independiente.")
    if not last:
        return False, "SIN-VEREDICTO", ("NO: el agente no ha citado ningún [ADVERSARY-VERDICT] en su propio texto. "
                                        "Pídele la ronda del adversario (o una razón explícita para no hacerla, que "
                                        "le pasas al usuario como razón, nunca como hold).")
    if last["veredicto"] == "break":
        corte = ("Criterio de corte: unsafe=%d. " % last["unsafe"]) + (
            "Hay fallos hacia el lado inseguro: se arreglan sí o sí." if last["unsafe"] else
            "Sin unsafe: lo seguro y caro puede ir como pendiente propuesto al usuario; lo barato se arregla.")
        return False, "BREAK", ("NO: su último veredicto es break (%s). No le pases el push al usuario. Pide otra "
                                "ronda tras arreglar (revisión limitada a lo que cambió) o una razón. %s"
                                % (last["linea"], corte))
    return True, "OK", ("OK: último veredicto hold (%s). Sigue con `lookout publica`. Qué rondas hacían falta "
                        "(modelo, backends) lo decide goalspec, no lookout." % (
                            last.get("modelo") or "sin [ADVERSARY-MODEL] citado"))


def decide_ronda(st):
    """(ok, code, text) for opening one more adversary round."""
    nxt = st["rondas"] + 1
    if nxt > st["limite"]:
        return False, "PREGUNTA-USUARIO", (
            "PARA: ya van %d rondas (límite %d). Antes de abrir la %d abre la decisión (`lookout decision … "
            "--abre`) y pregúntale al usuario en el chat (hay agentes vivos; el modal te bloquearía): "
            "abrir otra ronda / registrar lo que queda como pendientes propuestos y cerrar / parar. Si dice que "
            "sí: `lookout gobierno <proyecto> <agente> --usuario-amplia %d`." % (st["rondas"], st["limite"], nxt, nxt))
    return True, "OK", "OK: puede abrir la ronda %d de %d." % (nxt, st["limite"])


def amplia(project_id, entry, nuevo_limite):
    c = load_counters(project_id)
    t = c["tareas"].setdefault(task_key(entry), {})
    t["limite"] = int(nuevo_limite)
    t.setdefault("ampliaciones", []).append({"limite": int(nuevo_limite), "ts": time.time()})
    lookout_state.write_json(counters_path(project_id), c)


def render(st):
    last = st["ultimo"]
    lines = ["Tarea %s — sesiones: %s" % (st["tarea"], ", ".join(s[:8] for s in st["sesiones"])),
             "Rondas de adversario: %d de %d (subagente %d, externo %d); veredictos citados: %d" % (
                 st["rondas"], st["limite"], st["por_backend"]["subagente"], st["por_backend"]["externo"],
                 st["veredictos"]),
             "Modelo del agente: %s" % (st["modelo_ejecutor"] or "?")]
    if last:
        lines.append("Último veredicto: %s" % last["linea"])
        lines.append("Su [ADVERSARY-MODEL]: %s" % (last.get("modelo") or "(no citado)"))
    else:
        lines.append("Último veredicto: ninguno citado")
    if st["completion"]:
        lines.append("Último completion-review: %s" % st["completion"])
    return "\n".join(lines)

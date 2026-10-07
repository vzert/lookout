#!/usr/bin/env python3
"""State hooks of a supervised session (docs/plan.md 3.5, table adjusted after phase 0).

Runs behind hooks/guard.sh (async). Writes one line to the project's events.jsonl and puts a
display-only label on the pane with `herdr pane report-metadata` (V3 plan B).
It never prints a decision: every path exits 0 with no stdout.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import herdr_cli  # noqa: E402
import heuristicas  # noqa: E402
import lookout_state  # noqa: E402

MARKERS = ("[ADVERSARY-VERDICT", "[ADVERSARY-MODEL", "[COMPLETION-REVIEW")


def last_line(text, limit=200):
    """The last line that says something. Fase 9 E7: a code fence or a rule is skipped (claude-vzert: «```» twice),
    and a very short one («Sí.») carries the line before it."""
    lines = [l.strip() for l in (text or "").splitlines()]
    lines = [l for l in lines if l and not l.startswith("```") and l.strip("-*_=~ ")]
    if not lines:
        return ""
    line = lines[-1]
    if len(line) < 12 and len(lines) > 1:
        line = lines[-2] + " … " + line
    return line[:limit]


def goal_markers(text):
    found = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith(MARKERS):
            found.append(line[:200])
    return found


HOOK_BLOQUEO = re.compile(r"^(?:Error: )?PreToolUse:(\w+) hook error: (.*)", re.S)


def turn_rows(transcript_path, max_bytes=300000):
    """The transcript rows of the turn that just ended, oldest first (back to the last real user prompt)."""
    import json
    if not transcript_path:
        return []
    try:
        with open(transcript_path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - max_bytes))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    rows = []
    for line in reversed(lines):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        content = (d.get("message") or {}).get("content")
        if d.get("type") == "user" and (isinstance(content, str) or any(
                isinstance(b, dict) and b.get("type") == "text" for b in content or [])):
            break
        rows.append(d)
    return rows[::-1]


def hook_blocks(rows):
    """Fase 9 E8: what another plugin's PreToolUse hook denied this turn. No hook event reports it (spike 2026-10-06:
    no PostToolUseFailure, no PermissionDenied); it is only a tool_result «PreToolUse:<Tool> hook error: <reason>»."""
    out = []
    for d in rows:
        content = (d.get("message") or {}).get("content")
        if d.get("type") != "user" or not isinstance(content, list):
            continue
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                text = b.get("content") if isinstance(b.get("content"), str) else json.dumps(b.get("content"))
                m = HOOK_BLOQUEO.match(text or "")
                if m:
                    out.append({"tool": m.group(1), "motivo": " ".join(m.group(2).split())[:200]})
    return out


def markers_this_turn(transcript_path, max_bytes=300000):
    """Fase 9 E7: the goal markers of the whole turn that just ended (assistant text and SendMessage bodies, up to
    the last real user prompt), not only of its last message."""
    import json
    if not transcript_path:
        return []
    try:
        with open(transcript_path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - max_bytes))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    found = []
    for line in reversed(lines):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        content = (d.get("message") or {}).get("content")
        if d.get("type") == "user":
            if isinstance(content, str) or any(isinstance(b, dict) and b.get("type") == "text" for b in content or []):
                break
        elif d.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    found = goal_markers(b.get("text")) + found
                elif b.get("type") == "tool_use" and b.get("name") == "SendMessage":
                    msg = (b.get("input") or {}).get("message")
                    found = goal_markers(msg if isinstance(msg, str) else "") + found
    return found


def bg_summary(tasks):
    out = []
    for t in tasks or []:
        if isinstance(t, dict):
            out.append({k: t.get(k) for k in ("type", "status", "command", "description") if t.get(k)})
    return out


def reported_this_turn(transcript_path, address, max_bytes=300000):
    """Did the agent send its report (a SendMessage to the supervisor's address) in the turn that just ended?
    Scans the transcript tail backwards up to the last real user prompt. Unsure -> False: the waiter then wakes
    as before (the safe side). Fase 4: without this, every step woke the supervisor twice (message + end of turn)."""
    import json
    if not transcript_path or not address:
        return False
    try:
        with open(transcript_path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return False
    ok_results = set()  # tool_use ids whose result came back without error (seen first: we scan backwards)
    for line in reversed(lines):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        msg = d.get("message") or {}
        content = msg.get("content")
        if d.get("type") == "user":
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result" and not b.get("is_error"):
                        text = b.get("content") if isinstance(b.get("content"), str) else json.dumps(b.get("content"))
                        if "error" not in (text or "")[:40].lower():
                            ok_results.add(b.get("tool_use_id"))
            if isinstance(content, str) or any(isinstance(b, dict) and b.get("type") == "text" for b in content or []):
                return False  # reached the prompt that opened this turn
        elif d.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if (isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "SendMessage"
                        and (b.get("input") or {}).get("to") == address and b.get("id") in ok_results):
                    return True  # a report that was actually delivered (adversary F4: a failed send must still wake)
    return False


LOOKOUT_TECLEA = ("/rename ", "/exit")
# Adversary round 1: only the wrappers Claude Code itself puts around a peer's or the system's text; a prompt the user
# types that happens to start with «<» is still the user's.
PEGADO = re.compile(r"^<pasted_content[^>]*>\s*(.*?)\s*</pasted_content[^>]*>\s*$", re.S)
ETIQUETA_SISTEMA = re.compile(r"^<(cross-session-message|task-notification|system-reminder|local-command-[\w-]+|"
                              r"command-[\w-]+|bash-[\w-]+)[\s>]")


def origen_prompt(project_id, session_id, prompt):
    """Who typed this prompt into the agent (Fase 9 C5): "par" (another session's SendMessage, or a system tag),
    "lookout" (a delivery of its ledger, or a /rename or /exit it types), else "usuario": the user deciding straight
    in the agent's pane (claude-vzert: production changes decided in handoff-balanceador's pane, off the record)."""
    p = prompt.lstrip()
    if ETIQUETA_SISTEMA.match(p):
        return "par"
    if p.startswith(LOOKOUT_TECLEA):
        return "lookout"
    import deliver
    # Adversary round 2: Claude Code wraps a long or multi-line pasted prompt in <pasted_content …>; a lookout delivery
    # may arrive that way. Compare its inner text; a paste the user made is still the user's.
    m = PEGADO.match(p)
    texto = m.group(1) if m else prompt
    for rec in (deliver.load_ledger(project_id) or {}).values():
        # Adversary round 3: only a delivery still waiting for its confirmation (this very hook confirms it); once
        # confirmed, the same text typed or pasted again is the user's.
        if (rec.get("session_id") == session_id and rec.get("estado") != "confirmada"
                and deliver.norm(rec.get("texto")) in (deliver.norm(texto), deliver.norm(prompt))):
            return "lookout"
    return "usuario"


def build(data, marker):
    """Return (event_dict or None, label or None, other_projects) for one hook payload."""
    name = data.get("hook_event_name", "")
    ev = {
        "session_id": data.get("session_id", ""),
        "nombre": marker.get("nombre", ""),
        "pane": os.environ.get("HERDR_PANE_ID", ""),
        "hook": name,
    }
    pid = os.environ.get("CLAUDE_PID", "")
    if pid.isdigit() and name in ("UserPromptSubmit", "SessionStart"):
        ev["claude_pid"] = int(pid)  # Fase 6: the process the no-progress check asks `ps` about
    if name == "UserPromptSubmit":
        prompt = data.get("prompt") or ""
        ev.update(event="working", prompt=prompt[:120], origen=origen_prompt(marker.get("project_id", ""),
                                                                            ev["session_id"], prompt))
        return ev, "trabajando", []
    if name == "PostToolUseFailure":
        if data.get("is_interrupt"):
            return None, None, []  # the user (or a timeout) cut it: not the agent repeating an error
        ti = data.get("tool_input") or {}
        err = str(data.get("error") or "")
        ev.update(event="fallo", tool_name=data.get("tool_name", ""), firma=heuristicas.firma(data.get("tool_name"), err),
                  detalle=str(ti.get("command") or ti.get("file_path") or ti.get("pattern") or "")[:200],
                  error=" ".join(err.split())[:200])
        return ev, None, []
    if name == "PermissionRequest":
        ti = data.get("tool_input") or {}
        ev.update(event="blocked", tool_name=data.get("tool_name", ""),
                  detalle=str(ti.get("command") or ti.get("file_path") or "")[:200])
        return ev, "permiso", []
    if name == "Notification":
        ev.update(event="notification", tipo=data.get("notification_type", ""),
                  mensaje=(data.get("message") or "")[:200])
        return ev, None, []
    if name == "Stop":
        msg = data.get("last_assistant_message") or ""
        tasks = bg_summary(data.get("background_tasks"))
        # Fase 9 E6: a `monitor` (e.g. the live updates of a published artifact) never ends and is not work: alone, it
        # kept an agent "trabajando" the whole claude-vzert session.
        running = [t for t in tasks if t.get("status") in (None, "running", "pending") and t.get("type") != "monitor"]
        marcas = goal_markers(msg)
        marcas += [m for m in markers_this_turn(data.get("transcript_path")) if m not in marcas]
        ev.update(ultima=last_line(msg), marcadores=marcas)
        bloqueos = hook_blocks(turn_rows(data.get("transcript_path")))
        if bloqueos:
            ev["bloqueos_hook"] = bloqueos
        if running:
            ev.update(event="bg_wait", tareas=running)
            return ev, "fondo", []
        ev.update(event="idle")
        if reported_this_turn(data.get("transcript_path"), marker.get("address")):
            ev.update(reporto=True)
        return ev, "listo", []
    if name == "StopFailure":
        kind = str(data.get("error") or data.get("error_type") or "")
        detalle = str(data.get("error_details") or data.get("last_assistant_message") or "")[:200]
        if kind in heuristicas.PAUSA_ERRORS:
            # Fase 6: a provider limit pauses the agent; it is not a failure of its task.
            ev.update(event="pausa", error=kind, detalle=detalle)
            return ev, "pausa", []
        ev.update(event="unknown", error=kind[:200], detalle=detalle)
        return ev, "error-api", []
    if name == "PostToolUse":
        ti = data.get("tool_input") or {}
        own = marker.get("project_id")
        locks = lookout_state.list_locks()
        if data.get("tool_name") == "Bash":
            # V11 (Fase 6): Bash only gives the command text; read the paths it writes from it.
            hits = {}
            for path in heuristicas.escrituras_bash(ti.get("command") or "", data.get("cwd") or ""):
                other = lookout_state.project_of_path(path, locks)
                if other and other != own:
                    hits.setdefault(other, []).append(path)
            if not hits:
                return None, None, []
            ev.update(event="crossrepo", tool_name="Bash", file_path=", ".join(sum(hits.values(), []))[:300],
                      detalle=str(ti.get("command") or "")[:200], desde_proyecto=own,
                      proyecto_tocado=",".join(sorted(hits)), via="bash")
            return ev, None, sorted(hits)
        path = ti.get("file_path") or ""
        if not path:
            return None, None, []
        other = lookout_state.project_of_path(path, locks)
        if not other or other == own:
            return None, None, []
        ev.update(event="crossrepo", tool_name=data.get("tool_name", ""), file_path=path,
                  desde_proyecto=own, proyecto_tocado=other)
        return ev, None, [other]
    if name == "SessionStart":
        # A launched agent (F2) is ready for its first prompt only after this (learning 4).
        ev.update(event="start", fuente=data.get("source", ""), modelo=data.get("model", ""))
        return ev, None, []
    if name == "SessionEnd":
        ev.update(event="end", razon=data.get("reason", ""))
        return ev, None, []
    return None, None, []


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    marker = lookout_state.read_marker(data.get("session_id", ""))
    if not marker:
        return 0
    try:
        ev, label, others = build(data, marker)
        if ev is None:
            return 0
        own = marker.get("project_id", "unknown")
        rep = None
        if ev.get("event") == "fallo":
            rep = heuristicas.registra_fallo(own, ev)  # appends it, and a `repite` on the 3rd same error
        else:
            lookout_state.append_event(own, ev)
        for pid in others:
            lookout_state.append_event(pid, ev)
        if rep:
            label = "repite"
        if label:
            herdr_cli.report_metadata(ev["pane"], label, marker.get("display"))
        heuristicas.transicion(own, rep or ev)  # grouped view; one notification on entering "te necesita" / "listo"
        if ev.get("origen") == "usuario":
            import supervisor_md  # a decision the user took in the agent's pane goes on the supervisor's record
            supervisor_md.log(own, {"tipo": "directa", "session_id": ev["session_id"], "nombre": ev.get("nombre", ""),
                                    "texto": supervisor_md.one_line(data.get("prompt"), 300)})
            supervisor_md.write(own)
    except Exception:  # a state hook must never disturb the agent
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

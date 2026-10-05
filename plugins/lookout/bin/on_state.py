#!/usr/bin/env python3
"""State hooks of a supervised session (docs/plan.md 3.5, table adjusted after phase 0).

Runs behind hooks/guard.sh (async). Writes one line to the project's events.jsonl and puts a
display-only label on the pane with `herdr pane report-metadata` (V3 plan B).
It never prints a decision: every path exits 0 with no stdout.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import herdr_cli  # noqa: E402
import heuristicas  # noqa: E402
import lookout_state  # noqa: E402

MARKERS = ("[ADVERSARY-VERDICT", "[ADVERSARY-MODEL", "[COMPLETION-REVIEW")


def last_line(text, limit=200):
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if line:
            return line[:limit]
    return ""


def goal_markers(text):
    found = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith(MARKERS):
            found.append(line[:200])
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
        ev.update(event="working", prompt=(data.get("prompt") or "")[:120])
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
        running = [t for t in tasks if t.get("status") in (None, "running", "pending")]
        ev.update(ultima=last_line(msg), marcadores=goal_markers(msg))
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
    except Exception:  # a state hook must never disturb the agent
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

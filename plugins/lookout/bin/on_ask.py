#!/usr/bin/env python3
"""PreToolUse[AskUserQuestion] hook (docs/plan.md 3.6, D5).

Runs behind hooks/guard.sh, so it only sees supervised sessions; it re-checks the marker anyway.
Unsupervised session: exit 0 with no output (Claude Code continues as usual).
Supervised session: write an `ask` event and deny the tool with a reason the model sees,
telling it to send the question to its supervisor by SendMessage.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import herdr_cli  # noqa: E402
import lookout_state  # noqa: E402


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    session_id = data.get("session_id", "")
    marker = lookout_state.read_marker(session_id)
    if not marker:
        return 0
    address = marker.get("address") or marker.get("supervisor", "supervisor")
    pane = os.environ.get("HERDR_PANE_ID", "")
    questions = (data.get("tool_input") or {}).get("questions") or []
    lookout_state.append_event(marker.get("project_id", "unknown"), {
        "event": "ask",
        "session_id": session_id,
        "nombre": marker.get("nombre", ""),
        "pane": pane,
        "cwd": data.get("cwd", ""),
        "questions": [
            {
                "question": q.get("question", ""),
                "options": [o.get("label", "") for o in q.get("options") or []],
            }
            for q in questions
        ],
    })
    # Address only, never the supervisor's display name: a haiku executor once used a quoted name
    # as `to`, failed, and picked the closest ListAgents name, another executor (phase-1 run 2).
    reason = (
        "Sesión supervisada (lookout). No uses AskUserQuestion. "
        "Manda esta pregunta con la herramienta SendMessage (cárgala con ToolSearch si hace falta) "
        f"con to=\"{address}\" (cópialo tal cual; no uses un nombre): máximo 6 líneas con contexto, "
        "opciones y tu recomendación. Luego termina tu turno; la respuesta llega como mensaje."
    )
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, sys.stdout, ensure_ascii=False)
    sys.stdout.flush()
    herdr_cli.report_metadata(pane, "pregunta", marker.get("display"))
    try:
        import heuristicas
        heuristicas.transicion(marker.get("project_id", "unknown"), {"event": "ask", "session_id": session_id})
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

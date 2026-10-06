#!/usr/bin/env python3
"""Hooks of the SUPERVISOR's own session (Fase 4). Runs behind hooks/guard-sup.sh, which only lets a session
with a supervisor marker through (written by `lookout inicia`); executors never get here.

- PostToolUse[SendMessage]: log what the supervisor told whom (its answers to the agents) and rewrite supervisor.md.
- PreToolUse[AskUserQuestion] (via hooks/guard.sh): log the question as asked; PostToolUse: log the user's answers.
  A question asked and never answered is a pending user decision in supervisor.md.
- Stop (its own synchronous entry, via hooks/guard-sup.sh; an async hook cannot block): no live waiter → block the
  stop once and say to launch `lookout espera`.
- PreCompact: rewrite supervisor.md before the context is summarized.
- SessionStart[compact]: print the «Como retomar» (plain stdout reaches the model's context after a compaction; V14).
Exit 0 always. Its only block is the Stop check above, from the synchronous entry; the async on_state.py entry
(--async) never runs it, because an async hook cannot block.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import supervisor_md  # noqa: E402


def handle(data, via_async=False):
    sid = data.get("session_id", "")
    pid = supervisor_md.supervised_by(sid)
    if not pid:
        return ""
    ev = data.get("hook_event_name", "")
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    if ev == "PostToolUse" and tool == "SendMessage":
        supervisor_md.log(pid, {"tipo": "respuesta", "session_id": sid, "to": ti.get("to", ""),
                                "texto": supervisor_md.one_line(ti.get("message") or ti.get("summary"), 600)})
    elif ev == "PreToolUse" and tool == "AskUserQuestion":
        # never decide anything here: no output means the question goes to the user as usual
        supervisor_md.log(pid, {"tipo": "pregunta", "session_id": sid, "tool_use_id": data.get("tool_use_id", ""),
                                "preguntas": [supervisor_md.one_line(q.get("question"), 300) for q in ti.get("questions") or []]})
    elif ev == "PostToolUse" and tool == "AskUserQuestion":
        tr = data.get("tool_response") or {}
        answers = tr.get("answers") if isinstance(tr, dict) else None
        supervisor_md.log(pid, {"tipo": "usuario", "session_id": sid, "tool_use_id": data.get("tool_use_id", ""),
                                "answers": answers or ti.get("answers") or {}})
    elif ev == "Stop":
        return "" if via_async else stop_check(data, pid, sid)
    elif ev == "PreCompact":
        supervisor_md.log(pid, {"tipo": "precompact", "session_id": sid, "trigger": data.get("trigger", "")})
    elif ev == "SessionStart":
        supervisor_md.write(pid)
        return ("lookout: tu contexto se acaba de compactar. Eres el supervisor del proyecto %s; tu estado está en %s.\n%s\n"
                % (pid, supervisor_md.path(pid), supervisor_md.retomar_block(pid)))
    else:
        return ""
    supervisor_md.write(pid)
    return ""


def stop_check(data, pid, sid, grace=1.5):
    """Fase 4 corrida 3: a supervisor that answered every SendMessage stopped relaunching its waiter, and 11 turn ends
    with no report (two of them questions in plain text) reached nobody. At the end of a turn with no live waiter,
    block the stop once (never when stop_hook_active: no loop) and say exactly what to run. Only for the lock owner."""
    import time
    import digest
    import lock
    if data.get("stop_hook_active"):
        return ""
    if ((lock.read(pid) or {}).get("supervisor") or {}).get("session_id") != sid:
        return ""
    def own_waiter():  # a live waiter of a session that no longer supervises does not count: it is about to leave;
        # neither does a held pidfile whose pid cannot be read (-1, adversary F4 round 4): unknown is not "mine"
        return digest.waiter_alive(pid) > 0 and not digest.waiter_owner_dead(pid)
    if own_waiter():
        return ""
    time.sleep(grace)  # a waiter launched as the turn's last action may not hold its lock yet
    if own_waiter():
        return ""
    return json.dumps({"decision": "block", "reason": (
        "lookout: no hay waiter vivo para el proyecto %s y sin él no te despierta ningún agente que termine sin "
        "reportar. Lanza `lookout espera %s` con run_in_background: true (timeout 7200000) y termina el turno."
        % (pid, pid))}, ensure_ascii=False)


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    try:
        out = handle(data, via_async="--async" in sys.argv[1:])
    except Exception as exc:  # a hook must never break the supervisor's turn
        sys.stderr.write("lookout on_supervisor: %s\n" % exc)
        return 0
    if out:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

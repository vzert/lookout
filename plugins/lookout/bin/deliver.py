#!/usr/bin/env python3
"""Idempotent prompt delivery to one registered agent (docs/plan.md 6.2, F2).

Rules (6.2): send only to an idle/done agent; never write over a user's draft; `agent prompt`
without --wait; "delivered" only when the agent's own UserPromptSubmit hook logs this prompt;
on a timeout READ before retrying (events.jsonl, then the agent's transcript, then its input box)
and never send the same text twice; at most 3 attempts, then escalate.

A ledger per project (<state>/projects/<pid>/entregas.json), keyed by a delivery key, survives
the supervisor's turns and relays, so a second call with the same key never duplicates.

Usage: deliver.py PROJECT_ID AGENTE --clave K --texto T [--confirmar S] [--max-intentos 3]
Exit codes: 0 delivered (now or before), 4 not delivered (busy, draft, stale registry), 5 escalate,
6 sent but not confirmed yet (run it again later with the same key: it reads before resending).
"""
import argparse
import glob
import json
import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import herdr_cli  # noqa: E402
import inputbox  # noqa: E402
import lookout_state  # noqa: E402
import registry  # noqa: E402
import requisitos  # noqa: E402

MAX_INTENTOS = 3
PROMPT_KEEP = 120  # on_state.py keeps prompt[:120] in the `working` event


def norm(text):
    return "".join((text or "").split())


def ledger_path(project_id):
    return os.path.join(lookout_state.project_dir(project_id), "entregas.json")


def load_ledger(project_id):
    return lookout_state.read_json(ledger_path(project_id), {})


def save_record(project_id, key, rec):
    led = load_ledger(project_id)
    led[key] = rec
    lookout_state.write_json(ledger_path(project_id), led)


def same_prompt(logged, text):
    """A `working` event's prompt (cut at 120 chars) is this text."""
    a, b = norm(logged), norm(text[:PROMPT_KEEP])
    return bool(a) and (a == b or (len(text) > PROMPT_KEEP and b.startswith(a)))


def seen_in_events(project_id, session_id, text, offset):
    events, _ = lookout_state.read_events(project_id, offset)
    return any(ev.get("event") == "working" and ev.get("session_id") == session_id
               and same_prompt(ev.get("prompt", ""), text) for ev in events)


def transcript_path(session_id, projects_dir=None):
    base = projects_dir or os.path.join(requisitos.config_dir(), "projects")  # honours CLAUDE_CONFIG_DIR
    found = glob.glob(os.path.join(base, "*", session_id + ".jsonl"))
    return found[0] if found else ""


def user_texts(path):
    """Text of every user message typed into the session (not tool results) in a transcript."""
    out = []
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return out
    with fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") != "user" or d.get("isMeta"):
                continue
            content = (d.get("message") or {}).get("content")
            if isinstance(content, str):
                out.append(content)
            elif isinstance(content, list):
                parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                if parts:
                    out.append("\n".join(parts))
    return out


def count_in_transcript(session_id, text, projects_dir=None):
    """How many user messages of the session are exactly this prompt (whitespace ignored)."""
    path = transcript_path(session_id, projects_dir)
    want = norm(text)
    return sum(1 for t in user_texts(path) if norm(t) == want) if path else 0


def wait_prompt_event(project_id, session_id, offset, timeout, text=None):
    """Block until this session's UserPromptSubmit lands after `offset`.
    With `text`, only an event carrying that prompt counts."""
    return wait_event(project_id, offset, timeout, lambda ev: (
        ev.get("session_id") == session_id and ev.get("event") == "working"
        and (text is None or same_prompt(ev.get("prompt", ""), text))))


def wait_event(project_id, offset, timeout, pred):
    """Block (tail -F: the kernel wakes us, no polling loop) until an event after byte `offset`
    satisfies `pred`, or `timeout` seconds pass. Returns True/False."""
    path = lookout_state.events_path(project_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tail = subprocess.Popen(["tail", "-c", "+%d" % (offset + 1), "-F", path],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    def on_alarm(_s, _f):
        raise TimeoutError()
    old = signal.signal(signal.SIGALRM, on_alarm)
    signal.setitimer(signal.ITIMER_REAL, max(timeout, 0.01))
    try:
        for line in tail.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if pred(ev):
                return True
    except TimeoutError:
        return False
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)
        tail.kill()
        tail.stdout.close()
        tail.wait()
    return False


def read_box(pane):
    code, out, _ = herdr_cli.run(["agent", "read", pane, "--source", "visible", "--format", "ansi"])
    return inputbox.read_box(out) if code == 0 else ("desconocida", "")


def events_size(project_id):
    try:
        return os.path.getsize(lookout_state.events_path(project_id))
    except OSError:
        return 0


def deliver(project_id, entry, key, text, confirmar=30.0, max_intentos=MAX_INTENTOS, projects_dir=None):
    """Deliver `text` to the agent of registry `entry` at most once. Returns (code, message).
    One delivery at a time per project (flock): two concurrent calls with the same key would both pass
    the read-before-retry check and send twice (adversary round 1)."""
    import fcntl
    os.makedirs(lookout_state.project_dir(project_id), exist_ok=True)
    fd = os.open(ledger_path(project_id) + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return _deliver(project_id, entry, key, text, confirmar, max_intentos, projects_dir)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _deliver(project_id, entry, key, text, confirmar, max_intentos, projects_dir):
    sid, pane = entry["session_id"], entry["pane_id"]
    rec = load_ledger(project_id).get(key) or {
        "texto": text, "session_id": sid, "nombre": entry.get("nombre", ""), "intentos": 0,
        "estado": "nueva", "offset": None, "historia": []}
    if rec["texto"] != text:
        return 4, "NO ENTREGADO: la clave %s ya se usó con otro texto. Usa otra clave." % key
    if rec["estado"] == "confirmada":
        return 0, "ya entregada antes (%s); no reenvío" % key

    def note(what):
        rec["historia"].append([time.strftime("%H:%M:%S"), what])

    # 1. Read before retrying: did an earlier attempt land after all? (6.2.5)
    if rec["intentos"] > 0:
        if seen_in_events(project_id, sid, text, rec["offset"] or 0) or count_in_transcript(sid, text, projects_dir):
            rec["estado"] = "confirmada"
            note("confirmada al releer: el intento anterior sí llegó")
            save_record(project_id, key, rec)
            return 0, "entregada: el intento anterior sí llegó (lo confirmé al releer); no reenvío"

    # 2. Identity: the pane must still be this session in this folder (3.3).
    live = herdr_cli.agent_get(pane) or {}
    if not live:
        return 4, "NO ENTREGADO: no hay agente en el pane %s (%s)." % (pane, entry.get("nombre"))
    live_sid = (live.get("agent_session") or {}).get("value")
    # herdr learns the session id only after the first prompt: a freshly launched agent has none yet.
    live_cwd = os.path.realpath(live["cwd"]) if live.get("cwd") else ""
    if (live_sid and live_sid != sid) or (live_cwd and live_cwd != os.path.realpath(entry.get("cwd") or "")):
        return 4, "NO ENTREGADO: el pane %s ya no es de %s (registro viejo)." % (pane, entry.get("nombre"))

    # 3. Input box: empty or a dim suggestion is fine; our own stalled text gets Enter; anything else is a draft.
    clase, caja = read_box(pane)
    if clase == "borrador":
        # Only the WHOLE prompt counts as our stalled attempt: a user draft that merely starts like it
        # must never be submitted (adversary round 1). Our triggers are one short line, shown whole.
        if rec["intentos"] > 0 and norm(caja) == norm(text):
            if rec["intentos"] >= max_intentos:
                rec["estado"] = "escalar"
                save_record(project_id, key, rec)
                return 5, "ESCALAR: %d intentos sin confirmar; el texto sigue en la caja de %s." % (rec["intentos"], entry.get("nombre"))
            offset = events_size(project_id)
            rec["intentos"] += 1
            rec["offset"] = offset
            note("el texto seguía en la caja: Enter")
            save_record(project_id, key, rec)
            herdr_cli.run(["agent", "send-keys", pane, "enter"])
            return finish(project_id, key, rec, sid, text, offset, confirmar, note)
        return 4, ("NO ENTREGADO: la caja de entrada de %s tiene un borrador (%r). No escribo encima; "
                   "avisa al usuario." % (entry.get("nombre"), caja[:60]))
    if clase == "desconocida":
        return 4, "NO ENTREGADO: no pude leer la caja de entrada de %s." % entry.get("nombre")

    # 4. State: only to an idle/done agent (6.2.1).
    estado = live.get("agent_status")
    if estado not in ("idle", "done"):
        return 4, "NO ENTREGADO: %s está %s. Se le entrega en su siguiente idle." % (entry.get("nombre"), estado)

    if rec["intentos"] >= max_intentos:
        rec["estado"] = "escalar"
        save_record(project_id, key, rec)
        return 5, "ESCALAR: %d intentos sin confirmar para %s." % (rec["intentos"], entry.get("nombre"))

    # 5. Send once, recorded BEFORE sending so a crash mid-send still counts as an attempt.
    offset = events_size(project_id)
    rec["intentos"] += 1
    rec["offset"] = offset
    rec["estado"] = "enviada"
    note("agent prompt (intento %d)" % rec["intentos"])
    save_record(project_id, key, rec)
    code, _o, err = herdr_cli.run(["agent", "prompt", pane, text], timeout=20)
    if code != 0:
        note("agent prompt rc=%s: %s" % (code, (err or "").strip()[:120]))
        save_record(project_id, key, rec)
    return finish(project_id, key, rec, sid, text, offset, confirmar, note)


def finish(project_id, key, rec, sid, text, offset, confirmar, note):
    if wait_prompt_event(project_id, sid, offset, confirmar, text):
        rec["estado"] = "confirmada"
        note("confirmada por UserPromptSubmit")
        save_record(project_id, key, rec)
        return 0, "entregada y confirmada (UserPromptSubmit)"
    rec["estado"] = "enviada"
    note("sin confirmar en %.1fs" % confirmar)
    save_record(project_id, key, rec)
    return 6, ("SIN CONFIRMAR en %.1fs. No la reenvíes a mano: vuelve a correr la misma entrega "
               "(misma clave); antes de reintentar leo eventos, transcript y caja." % confirmar)


def main():
    ap = argparse.ArgumentParser(prog="deliver.py")
    ap.add_argument("proyecto")
    ap.add_argument("agente")
    ap.add_argument("--clave", required=True)
    ap.add_argument("--texto", required=True)
    ap.add_argument("--confirmar", type=float, default=30.0)
    ap.add_argument("--max-intentos", type=int, default=MAX_INTENTOS)
    a = ap.parse_args()
    entry = registry.find(registry.load(a.proyecto), a.agente)
    if not entry:
        print("agente %r no registrado en %s" % (a.agente, a.proyecto))
        return 4
    code, msg = deliver(a.proyecto, entry, a.clave, a.texto, a.confirmar, a.max_intentos)
    print(msg)
    return code


if __name__ == "__main__":
    sys.exit(main())

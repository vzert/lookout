#!/usr/bin/env python3
"""Idempotent prompt delivery to one registered agent (docs/plan.md 6.2, F2).

Rules (6.2): send only to a quiet agent (quieto: idle/done, or herdr «working» only because of a background shell); never write over a user's draft; `agent prompt`
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
import calendar
import glob
import json
import os
import re
import signal
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


BASH_INPUT = re.compile(r"^<bash-input>(.*)</bash-input>$", re.S)
# 0.13.15: a typed /command is kept as a block of tags: <command-name> and <command-message> in either order, then
# <command-args> last when it had args (every real block with args, 2026-10-17), not escaped
COMMAND_HEAD = re.compile(r"(?:\s*<command-(name|message)>[^<]*</command-\1>)+\s*")
COMMAND_NAME = re.compile(r"<command-name>([^<]*)</command-name>")
ARGS_OPEN, ARGS_CLOSE = "<command-args>", "</command-args>"


def as_typed(t):
    """A transcript's user message as it was typed: «! cmd» for <bash-input>, «/x args» for a command block."""
    t = t.strip()
    m = BASH_INPUT.match(t)
    if m:
        return "!" + m.group(1)
    head, sep, args = t.partition(ARGS_OPEN)
    if sep and not args.endswith(ARGS_CLOSE):
        return t
    name = COMMAND_NAME.search(head) if COMMAND_HEAD.fullmatch(head) else None
    if not name:
        return t
    args = args[:-len(ARGS_CLOSE)] if sep else ""
    return name.group(1) + (" " + args if args.strip() else "")


def es_comando(text):
    """0.13.7: «! cmd» typed into a Claude box runs in its shell mode. Measured 2026-10-16 with a throwaway Claude through
    `herdr agent prompt`: it runs, fires no UserPromptSubmit, and lands in the transcript as <bash-input> cmd</bash-input>."""
    return (text or "").lstrip().startswith("!")


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
        fh = open(path, encoding="utf-8", errors="replace")  # 0.13.35: one broken byte must not fail the delivery
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
    if not path:
        return 0
    n = 0
    for t in user_texts(path):
        n += norm(as_typed(t)) == want
    return n


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
    tail = lookout_state.sigue(path, offset)  # 0.12.1: dies with this process, also on SIGKILL

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
        lookout_state.deja_de_seguir(tail)
        tail.stdin.close()
        tail.stdout.close()
        tail.wait()
    return False


def read_box(pane):
    code, out, _ = herdr_cli.run(["agent", "read", pane, "--source", "visible", "--format", "ansi"])
    return inputbox.read_box(out) if code == 0 else ("desconocida", "")


# 0.13.10: a live background shell keeps herdr «working» after the turn ended (the footer «· N shells ·»; measured
# 2026-10-17: 10 of 17 real «está working» refusals were an agent quiet since its Stop). Its own hooks say quiet when
# its last event is a Stop and its transcript has nothing but the Stop's own system rows after the last row dated
# before that Stop: a turn opened by a task-notification or a message fires no UserPromptSubmit, but writes the
# transcript at once (2 of the 7 right refusals). Events of lookout and herdr notifications are not the agent's.
# Since 0.13.29 a local command that already ran (its caveat, command and local_command rows) is not a turn either.
NO_DEL_AGENTE = ("notification", "nuevo", "retomar", "repite", "correccion", "correccion_fallida", "sin_progreso", "largo",
                 "retenido")
COLA_TRANSCRIPT = 1024 * 1024
# Claude Code's undated bookkeeping rows (counted 2026-10-17 over 300 transcripts); every row a turn writes is dated
# (user, queue-operation, assistant, attachment). An undated row of another type, or a bad stamp, counts as a turn.
CONTABLES = ("last-prompt", "atis-latch", "mode", "cost-state", "permission-mode", "ai-title", "custom-title")


def _neutra(row):
    return row.get("type") == "system" or ("timestamp" not in row and row.get("type") in CONTABLES)


# 0.13.29 (p-ad978476a5): a local command such as /reload-plugins (`lookout recarga`) writes after the Stop a `user`
# row «<local-command-caveat>» (isMeta), a `user` row with only its <command-name>/<command-message>/<command-args>
# and, once it has run, a `system` row `local_command` (bench 2026-10-18: `envia` refused an agent with a live shell
# after a reload). A skill typed in the box writes <command-message> and <command-name> too, but no
# local_command: it opens a turn. Only the whole set counts as quiet; a command still running has no local_command yet.
CAVEAT = re.compile(r"<local-command-caveat>[^<]*</local-command-caveat>")
COMANDO_LOCAL = re.compile(r"<command-name>/[\w:.-]+</command-name>\s*<command-message>[^<]*</command-message>\s*"
                           r"<command-args>[^<]*</command-args>")


def _texto(row):
    m = row.get("message")
    c = m.get("content") if isinstance(m, dict) else None
    return c.strip() if isinstance(c, str) else None


def _caveat(row):
    return row.get("type") == "user" and row.get("isMeta") is True and _ts(row) is not None and \
        CAVEAT.fullmatch(_texto(row) or "") is not None


def _sin_turno(filas):
    """True when every row after the Stop is neutral or part of a local command that already ran."""
    comandos = set()
    for i, row in enumerate(filas):
        if row.get("type") != "user" or _ts(row) is None or not COMANDO_LOCAL.fullmatch(_texto(row) or ""):
            continue
        j = i + 1
        while j < len(filas) and _caveat(filas[j]):
            j += 1
        con_caveat = j > i + 1 or (i > 0 and _caveat(filas[i - 1]))  # every real set has one (codex r2 of the release)
        if con_caveat and j < len(filas) and filas[j].get("type") == "system" and \
                filas[j].get("subtype") == "local_command":
            comandos.add(i)
    for i, row in enumerate(filas):
        if _neutra(row) or i in comandos:
            continue
        if _caveat(row) and (i - 1 in comandos or i + 1 in comandos):
            continue
        return False
    return True


SELLO = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(\.[0-9]+)?Z")  # ASCII digits only


def _ts(row):
    """A transcript row's stamp (UTC, exactly «2026-10-17T03:02:19.512Z»), in seconds; None when it has none or it is
    anything else (adversary r2: «…Zgarbage» passed)."""
    try:
        m = SELLO.fullmatch(row["timestamp"])
        if not m:
            return None
        return calendar.timegm(time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S")) + float(m.group(2) or 0)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


ESPERA_QUIETO = 45  # s: under the Bash tool's 2-minute default, over most of a turn's tail (0.13.50)


def espera_quieto(project_id, entry, segundos, intervalo=3.0, agent_get=None):
    """0.13.50: (live, waited s, herdr status) — live once the agent is quiet, None when it is not. 3-tier 2026-10-20:
    the supervisor sent the same `relevo` 6 times in a row to a working agent, each one refused at once; now one call
    waits up to `segundos` for the end of its turn. Only a `working` agent is waited for: blocked (a dialog), a pane
    herdr does not see, or any other status will not end by itself, and is returned at once (adversary r1)."""
    agent_get = agent_get or herdr_cli.agent_get
    t0 = time.time()
    while True:
        live = agent_get(entry["pane_id"]) or {}
        if quieto(project_id, entry, live):
            return live, round(time.time() - t0), live.get("agent_status")
        estado = live.get("agent_status")
        if estado != "working" or time.time() - t0 >= segundos:
            return None, round(time.time() - t0), estado
        time.sleep(intervalo)


def no_quieto(entry, esperado, estado="working"):
    """The refusal: after a wait, say not to poll (the waiter brings the agent's next idle); any other status, say it."""
    if estado != "working":
        return "%s está %s (no es fin de turno: no espero)" % (entry.get("nombre"), estado or "sin estado en herdr")
    return ("%s sigue a mitad de turno tras esperar %d s. No lo repitas en bucle: cuando termine su turno el waiter te "
            "despierta con su evento idle, y entonces lo repites una vez" % (entry.get("nombre"), esperado))


def quieto(project_id, entry, live, projects_dir=None):
    """True when the agent can take input: herdr sees it idle/done, or herdr sees it working and its hooks and
    transcript say it is between turns. Never over blocked or unknown (a dialog, a menu). Anything it cannot read
    after the Stop counts as a turn (adversary r1: a row with no or a bad stamp, a row bigger than the tail)."""
    estado = (live or {}).get("agent_status")
    if estado in ("idle", "done"):
        return True
    if estado != "working":
        return False
    sid = entry.get("session_id")
    last = None
    for ev in lookout_state.read_events(project_id, 0)[0]:
        if ev.get("session_id") == sid and ev.get("event") not in NO_DEL_AGENTE:
            last = ev
    if not last or last.get("event") not in ("idle", "bg_wait") or last.get("ts") is None:
        return False
    path = transcript_path(sid, projects_dir)
    if not path:
        return False
    try:
        with open(path, "rb") as fh:
            inicio = max(0, os.path.getsize(path) - COLA_TRANSCRIPT)
            fh.seek(inicio)
            cola = fh.read().split(b"\n")
    except OSError:
        return False
    if inicio > 0:
        cola = cola[1:]  # it starts inside a row
    filas = []
    for line in cola:
        if not line.strip():
            continue
        try:
            row = json.loads(line.decode("utf-8"))  # strict (adversary r2: «replace» read bad bytes as a row)
        except ValueError:
            return False  # a row being written, or one it cannot read: not proof of quiet
        if not isinstance(row, dict):
            return False
        filas.append(row)
    antes = [i for i, row in enumerate(filas) if (_ts(row) or float("inf")) <= float(last["ts"])]
    if not antes:
        return False  # the tail does not reach the Stop
    return _sin_turno(filas[antes[-1] + 1:])


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
        if (seen_in_events(project_id, sid, text, rec["offset"] or 0)
                or count_in_transcript(sid, text, projects_dir) > rec.get("previas", 0)):
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
            return finish(project_id, key, rec, sid, text, offset, confirmar, note, projects_dir)
        return 4, ("NO ENTREGADO: la caja de entrada de %s tiene un borrador (%r). No escribo encima; "
                   "avisa al usuario." % (entry.get("nombre"), caja[:60]))
    if clase == "desconocida":
        return 4, "NO ENTREGADO: no pude leer la caja de entrada de %s." % entry.get("nombre")

    # 4. State: only to a quiet agent (6.2.1; quieto, 0.13.10).
    estado = live.get("agent_status")
    if not quieto(project_id, entry, live, projects_dir):  # 0.13.10: a shell's «working» after its Stop is quiet
        return 4, "NO ENTREGADO: %s está %s. Se le entrega en su siguiente idle." % (entry.get("nombre"), estado)

    if rec["intentos"] >= max_intentos:
        rec["estado"] = "escalar"
        save_record(project_id, key, rec)
        return 5, "ESCALAR: %d intentos sin confirmar para %s." % (rec["intentos"], entry.get("nombre"))

    # 5. Send once, recorded BEFORE sending so a crash mid-send still counts as an attempt.
    offset = events_size(project_id)
    if rec["intentos"] == 0:  # 0.13.15: also a /command or a plain text, not only «! cmd» (codex r1)
        rec["previas"] = count_in_transcript(sid, text, projects_dir)  # the same text sent before is not this one
    rec["intentos"] += 1
    rec["offset"] = offset
    rec["estado"] = "enviada"
    note("agent prompt (intento %d)" % rec["intentos"])
    save_record(project_id, key, rec)
    code, _o, err = herdr_cli.run(["agent", "prompt", pane, text], timeout=20)
    if code != 0:
        note("agent prompt rc=%s: %s" % (code, (err or "").strip()[:120]))
        save_record(project_id, key, rec)
    return finish(project_id, key, rec, sid, text, offset, confirmar, note, projects_dir)


def finish(project_id, key, rec, sid, text, offset, confirmar, note, projects_dir=None):
    if es_comando(text):
        # no UserPromptSubmit for a shell-mode command: its turn end, then the transcript, says it ran
        wait_event(project_id, offset, confirmar, lambda ev: ev.get("session_id") == sid
                   and ev.get("event") in ("idle", "bg_wait"))
        if count_in_transcript(sid, text, projects_dir) > rec.get("previas", 0):
            rec["estado"] = "confirmada"
            note("confirmada en el transcript (<bash-input>)")
            save_record(project_id, key, rec)
            return 0, "entregada y confirmada (el comando está en su transcript)"
    elif wait_prompt_event(project_id, sid, offset, confirmar, text):
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
    if any(es_comando(line) for line in a.texto.splitlines()):
        # adversary r2 (codex): this helper typed «! cmd» with no decision; a command goes only through
        # `lookout envia --usuario-confirmo dN`, which checks the user's yes and the text they saw
        print("NO ENTREGADO: un «! comando» solo se teclea con `lookout envia … --usuario-confirmo dN`.")
        return 4
    entry = registry.find(registry.load(a.proyecto), a.agente)
    if not entry:
        print("agente %r no registrado en %s" % (a.agente, a.proyecto))
        return 4
    code, msg = deliver(a.proyecto, entry, a.clave, a.texto, a.confirmar, a.max_intentos)
    print(msg)
    return code


if __name__ == "__main__":
    sys.exit(main())

"""0.13.8 (p-d0c5d57049): `lookout recarga` types /reload-plugins into an agent whose hooks are older than the installed
plugins (versiones.viejos), so the fixes reach it. /reload-plugins reloads hooks in a live session (learning 3); it is
a local command: no hook event says it ran, so the screen confirms it («Reloaded: …»). Like the relief's /exit: only
with the agent quiet (deliver.quieto) and its box empty (a suggestion counts as empty; a draft of the user's never), and never twice for
the same installed versions (`recargado` in the registry, read by versiones.viejos).
0.13.24 (p-eff2c277ba): the confirmation is the transcript's `local_command` row of /reload-plugins with «Reloaded:».
The screen count gave 16 false «sin confirmar» in 3-tier (2026-10-17), each with that row in the agent's transcript inside
the call: `agent read --source recent` of a Claude Code pane returns its visible rows only (47 on the test agent), so once
the screen is full of «Reloaded:» a new one pushes an old one out and the count stays. The screen is read only when
lookout finds no transcript; a prompt herdr did not type is said, not waited for (codex r1).
"""
import json
import time

import deliver
import herdr_cli
import registry
import versiones


def vistos(pane):
    """How many «Reloaded:» lines its recent screen holds."""
    code, out, _ = herdr_cli.run(["agent", "read", pane, "--source", "recent", "--lines", "400"])
    return (out or "").count("Reloaded:") if code == 0 else 0


def filas(path):
    """How many /reload-plugins `local_command` rows with «Reloaded:» the transcript holds (None: unreadable)."""
    n = 0
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return None
    with fh:
        for line in fh:
            if '"local_command"' not in line or "Reloaded:" not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict) or d.get("type") != "system" or d.get("subtype") != "local_command":
                continue
            run = d.get("commandRun")  # «Reloaded:» alone does not say which command ran (codex r2)
            if not isinstance(run, dict) or run.get("command") != "reload-plugins":
                continue
            if "<local-command-stdout>Reloaded:" in str(d.get("content") or ""):
                n += 1
    return n


def teclea(pane, session_id, espera):
    """Type /reload-plugins and wait for its confirmation: ("ok" | "sin-confirmar" | "no-tecleado", where it looked).
    Shared by `recarga` and the reload step of `entrega` (0.13.31, p-231e8eeb51)."""
    path = deliver.transcript_path(session_id or "")
    t_antes = filas(path) if path else None
    if t_antes is not None:  # with a transcript, only its new row confirms (a screen count may move by itself)
        medir, antes, donde = (lambda: filas(path) or 0), t_antes, "su transcript"
    else:
        medir, antes, donde = (lambda: vistos(pane)), vistos(pane), "su pantalla (no encuentro su transcript)"
    if herdr_cli.run(["agent", "prompt", pane, "/reload-plugins"])[0] != 0:  # codex r1: nothing typed, nothing to wait
        return "no-tecleado", donde
    fin = time.time() + espera
    while True:
        if medir() > antes:  # an older «Reloaded:» confirms nothing
            return "ok", donde
        if time.time() >= fin:
            return "sin-confirmar", donde
        time.sleep(0.5)


def recarga(project_id, entry, espera=10.0):
    """(ok, message)."""
    pane = entry.get("pane_id")
    live = herdr_cli.agent_get(pane) or {}
    nombre = entry.get("nombre")
    if (live.get("agent_session") or {}).get("value") != entry.get("session_id"):
        return False, "NO: el pane %s ya no es de %s (registro viejo)." % (pane, nombre)
    if not deliver.quieto(project_id, entry, live):
        return False, "NO: %s está %s. Recarga cuando termine su turno." % (nombre, live.get("agent_status"))
    box, _text = deliver.read_box(pane)
    if box not in ("vacia", "sugerencia"):
        return False, "NO: la caja de %s tiene %s. No escribo encima; recarga cuando quede vacía." % (nombre, box)
    estado, donde = teclea(pane, entry.get("session_id"), espera)
    if estado == "no-tecleado":
        return False, "NO: herdr no tecleó /reload-plugins en %s. Lee su pane antes de repetirlo." % nombre
    if estado == "sin-confirmar":
        return False, ("Tecleé /reload-plugins en %s, sin confirmar: no veo «Reloaded:» nuevo en %s en %d s. "
                       "Lee su pane antes de repetirlo." % (nombre, donde, espera))
    reg = registry.load(project_id)
    e = reg.get("agents", {}).get(entry.get("session_id"))
    if e is not None:
        e["recargado"] = versiones.instaladas()
        e["recargado_ts"] = time.time()
        registry.save(project_id, reg)
    return True, "Recargué los plugins de %s (vi «Reloaded:» en %s)." % (nombre, donde.split(" (")[0])

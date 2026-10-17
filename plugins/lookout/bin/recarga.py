"""0.13.8 (p-d0c5d57049): `lookout recarga` types /reload-plugins into an agent whose hooks are older than the installed
plugins (versiones.viejos), so the fixes reach it. /reload-plugins reloads hooks in a live session (learning 3); it is
a local command: no hook event says it ran, so the screen confirms it («Reloaded: …»). Like the relief's /exit: only
with the agent quiet (deliver.quieto) and its box empty (a suggestion counts as empty; a draft of the user's never), and never twice for
the same installed versions (`recargado` in the registry, read by versiones.viejos).
"""
import time

import deliver
import herdr_cli
import registry
import versiones


def vistos(pane):
    """How many «Reloaded:» lines its recent screen holds."""
    code, out, _ = herdr_cli.run(["agent", "read", pane, "--source", "recent", "--lines", "400"])
    return (out or "").count("Reloaded:") if code == 0 else 0


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
    antes = vistos(pane)  # an older «Reloaded:» still on the screen confirms nothing
    herdr_cli.run(["agent", "prompt", pane, "/reload-plugins"])
    fin = time.time() + espera
    while True:
        if vistos(pane) > antes:
            break
        if time.time() >= fin:
            return False, ("Tecleé /reload-plugins en %s, sin confirmar: no veo «Reloaded:» en su pantalla en %d s. "
                           "Lee su pane antes de repetirlo." % (nombre, espera))
        time.sleep(0.5)
    reg = registry.load(project_id)
    e = reg.get("agents", {}).get(entry.get("session_id"))
    if e is not None:
        e["recargado"] = versiones.instaladas()
        e["recargado_ts"] = time.time()
        registry.save(project_id, reg)
    return True, "Recargué los plugins de %s (vi «Reloaded:» en su pantalla)." % nombre

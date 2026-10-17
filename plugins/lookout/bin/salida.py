"""0.13.10: /exit of an agent with live background shells (memory/research/lookout-shells-de-fondo-medicion.md).

With a shell alive, /exit opens Claude Code's dialog instead of ending the session:

   Background work is running
   The following will stop when you exit:
   shell · sleep 3000
   ❯ 1. Exit and stop tasks
     2. Move to background and exit
     3. Stay
   Enter to confirm · Esc to cancel

cierra-pestana and relevo waited for a SessionEnd that never came and left it open (then herdr saw `blocked`).
Stopping a shell kills a process, and leaving it runs it with nobody watching: that choice is the user's. So
relevo and cierra-pestana check for live shells BEFORE typing /exit (the last Stop's task list, and the footer
«· N shells ·», which also counts a monitor the Stop leaves out) and stop with a NO that asks for a modal; with the
user's choice on record (`lookout decision --abre … --shells-parar ETIQUETA --shells-dejar ETIQUETA`, answered in
the supervisor's modal and written down by its hook) they repeat with `--shells dN` and lookout presses that
option's own number in the dialog, read by structure. A dialog that opens anyway (a shell started in between) with
no choice on record is cancelled with Esc, which undoes lookout's own /exit and kills nothing.
"""
import re
import time

import decisiones
import deliver
import herdr_cli
import lookout_state

ESPERA_DIALOGO = 10.0  # the dialog is drawn within a second of /exit (measured 2026-10-17)
PASO = 1.0

REGLA = re.compile(r"^\s*─{3,}\s*$")
# herdr's own rule for this footer (local_background_shells_working, ~/.config/herdr/agent-detection/claude.toml)
PIE = re.compile(r"(?:^|·)\s*([1-9]\d*)\s+(?:shells?|background tasks?)\s*(?:·|$)")
# a pane nobody looks at is drawn ~23 columns wide and cuts «· 2 shells» to «· 2» (measured 2026-10-17): a count
# that ends the footer line counts too (wrong, it costs one question to the user)
PIE_CORTADO = re.compile(r"·\s*([1-9]\d*)\s*$")
BORDE = re.compile(r"^\s*▔{3,}\s*$")
OPCION = re.compile(r"(?:^|\s)(?:❯\s*)?(\d)\.\s+(Exit and stop tasks|Move to background and exit|Stay)(?=\s|$)")
CLAVES = {"Exit and stop tasks": "parar", "Move to background and exit": "dejar", "Stay": "quedarse"}


def pantalla(pane):
    """The visible screen of the pane as text, "" when herdr cannot read it."""
    code, out, _ = herdr_cli.run(["agent", "read", pane, "--source", "visible"])
    return out or "" if code == 0 else ""


def shells_en_pie(texto):
    """How many background shells or tasks the footer (below the prompt box's last rule) counts; 0 with none."""
    lineas = (texto or "").splitlines()
    ultima = max((i for i, l in enumerate(lineas) if REGLA.match(l)), default=None)
    if ultima is None:
        return 0
    for linea in lineas[ultima + 1:]:
        m = PIE.search(linea) or PIE_CORTADO.search(linea)
        if m:
            return int(m.group(1))
    return 0


def dialogo_exit(texto):
    """{"parar": "1", "dejar": "2", "quedarse": "3"} when the screen ends with the dialog of /exit with live background
    work, by its whole shape: a ▔ border, «Background work is running», the three options, and «Enter to confirm» as
    the last line of the screen (adversary r1: the options typed in the prompt box have the footer below them)."""
    lineas = [l for l in (texto or "").splitlines() if l.strip()]
    borde = max((i for i, l in enumerate(lineas) if BORDE.match(l)), default=None)
    if borde is None:
        return None
    # read as one text: a narrow pane wraps «Background work is running» and each option over several lines
    bloque = " ".join(" ".join(l.split()) for l in lineas[borde + 1:])
    if not (bloque.startswith("Background work is running") and bloque.endswith("Enter to confirm · Esc to cancel")):
        return None
    out = {}
    for m in OPCION.finditer(bloque):
        out[CLAVES[m.group(2)]] = m.group(1)
    if len(out) != 3 or len(set(out.values())) != 3:
        return None
    return out


def ultimo_stop(project_id, entry):
    """The agent's last event when it is a Stop (idle/bg_wait), else None."""
    last = None
    for ev in lookout_state.read_events(project_id, 0)[0]:
        if ev.get("session_id") == entry.get("session_id") and ev.get("event") not in deliver.NO_DEL_AGENTE:
            last = ev
    return last if last and last.get("event") in ("idle", "bg_wait") else None


def shells_vivos(project_id, entry):
    """What /exit would stop, as text ("" when nothing): the last Stop's tasks, else the footer's count."""
    stop = ultimo_stop(project_id, entry) or {}
    tareas = [t for t in stop.get("tareas") or () if t.get("status") in (None, "running", "pending")]
    if tareas:
        return "; ".join("%s «%s»" % (t.get("type") or "tarea", " ".join(str(t.get("command") or "").split())[:80])
                         for t in tareas)
    n = shells_en_pie(pantalla(entry.get("pane_id")))
    return ("%d shell%s o tarea%s de fondo en su pie" % (n, "s" if n > 1 else "", "s" if n > 1 else "")) if n else ""


def pide_modal(entry, que):
    nombre = entry.get("nombre")
    return ("tiene trabajo de fondo vivo (%s): /exit abre la pregunta de Claude Code «Exit and stop tasks / Move to "
            "background and exit / Stay», y terminarlo mata un proceso. No la contesto: pregúntaselo al usuario. Abre "
            "`lookout decision <proyecto> --abre \"¿Cómo cierro %s con su trabajo de fondo vivo? (…)\" --agentes %s "
            "--shells-parar \"<etiqueta de parar>\" --shells-dejar \"<etiqueta de dejarlo en segundo plano>\" --nueva`, "
            "ponla en tu modal con esas dos opciones y una de esperar, y repite con --shells <id>. Una elección anterior "
            "a su último Stop no vale: si su trabajo de fondo terminó o cambió entretanto, pregunta otra vez"
            % (que, nombre, nombre))


def eleccion(project_id, entry, did):
    """"parar" or "dejar" when `did` is the user's own choice in the modal (written by its hook, by structure) about
    THIS agent's background work, opened after its last Stop; else None."""
    d = decisiones.respondida(project_id, did) if did else None
    if not (d and d.get("tipo") == "shells" and d.get("por_hook") and d.get("eleccion") in ("parar", "dejar")
            and entry.get("nombre") in (d.get("agentes") or ())):
        return None
    stop = ultimo_stop(project_id, entry)
    if stop and float(d.get("desde") or 0) <= float(stop.get("ts") or 0):
        return None
    return d["eleccion"]


def salir(project_id, entry, eleccion_, fin_timeout, log):
    """Type /exit and wait for its SessionEnd. (True, "") when it ended; (False, why) otherwise, the dialog of
    background work cancelled unless the user's choice (`eleccion_`) says which option to press."""
    pane = entry["pane_id"]
    sid = entry["session_id"]
    offset = deliver.events_size(project_id)
    herdr_cli.run(["agent", "prompt", pane, "/exit"])
    fin = time.time() + fin_timeout
    pulsada = False
    if eleccion_:
        limite = time.time() + ESPERA_DIALOGO
        while True:
            d = dialogo_exit(pantalla(pane))
            if d:
                # the number alone picks it, no Enter (live 2026-10-17: «3» closed the dialog, «1» ended the session
                # and its sleep)
                herdr_cli.run(["agent", "send-keys", pane, d[eleccion_]])
                log("diálogo de /exit: opción %s (%s, elegida por el usuario)" % (d[eleccion_], eleccion_))
                pulsada = True
                break
            if deliver.wait_event(project_id, offset, PASO,
                                  lambda ev: ev.get("session_id") == sid and ev.get("event") == "end"):
                return True, ""
            if time.time() >= limite:
                break
    while True:
        resto = max(fin - time.time(), 0.01)
        if deliver.wait_event(project_id, offset, min(PASO, resto),
                              lambda ev: ev.get("session_id") == sid and ev.get("event") == "end"):
            return True, ""
        if not pulsada and dialogo_exit(pantalla(pane)):  # once pressed, a redraw of it is not a new dialog
            herdr_cli.run(["agent", "send-keys", pane, "esc"])
            log("diálogo de /exit cancelado con Esc: nadie eligió qué hacer con su trabajo de fondo")
            return False, pide_modal(entry, "lo abrió /exit")
        if time.time() >= fin:
            return False, ""

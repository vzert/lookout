"""0.13.12: the supervisor approves an agent's permission dialog only after the user's yes in its modal.

Live case (hook-para-checkpoint, 2026-10-17 11:17, auto mode): the user said yes in the supervisor's modal and still
had to go to the agent's pane. Now:

  1. The agent's PermissionRequest hook (permisos.py) writes a `blocked` event with the whole command.
  2. `lookout decision P --abre "…" --agentes A --permiso --si-es "<sí>"` (abre) ties a decision to THAT event: its
     command and its time, read from the event log, never from the supervisor's text.
  3. The user answers in the supervisor's modal; its hook closes the decision with the user's literal choice.
  4. `lookout aprueba P A --decision dN` (aprueba) presses «Yes» once in the agent's pane, and only when: the yes is
     the user's (por_hook), for this agent, not used before; the agent's last event is still that same request;
     herdr sees it blocked; and the dialog at the bottom of its visible screen, read by its whole shape, shows
     exactly that command. Anything else presses nothing (no Esc either) and says why.

This is not lookout approving by rules (permisos.handle answers `allow` only in manual mode, rule 40): it relays the
user's own yes for one call, in manual or auto mode, as the user would press it. Never «Yes, and don't ask again»
nor «Yes, and switch to auto mode»: the option pressed is the one whose label is exactly «Yes».

The dialog as Claude Code 2.1.302 draws it (tests/fixtures/permiso/, captured 2026-10-17):

  ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
   Bash command
   Tip: auto mode handles these prompts for you — choose "switch to auto mode" below
   │ <description>
  ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
   │ git push origin
   │ HEAD:refs/heads/prueba-del-dialogo-de-permiso-ancho-y-estrecho-de-lookout-0-13-12
  ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
   This command requires approval

   Do you want to proceed?
   ❯ 1. Yes
     2. Yes, and don’t ask again for: git push *
     3. Yes, and switch to auto mode · auto mode handles these prompts for you
     4. No

   Esc to cancel · Tab to amend

The top border «─» sits right above the header, as wide as the two «╌» rules (adversary r1: text shaped like the
dialog in earlier output). The user's yes counts only for a modal question that showed the whole command, as the
modal's hook wrote it down (decisiones.registra_pregunta keeps 2000 characters: a longer command cannot be approved
this way). A short command line breaks at a space and the space is gone (98 columns above); a full line (the rule's width less
one) breaks mid-word (39 columns). A command that does not fit the pane's height pushes the header off the visible
screen, and herdr reads only the visible screen of a blocked agent: then nothing is pressed. lookout never moves the
user's focus to read a pane (`pane zoom` moves it and does not give it back, measured 2026-10-17; the user chose it,
modal «Foco», 2026-10-17: «No tocar el foco»).
"""
import re
import time

import decisiones
import deliver
import herdr_cli
import lookout_state

ESPERA = 10.0  # the dialog closes within a second of the key (measured 2026-10-17)
PASO = 0.5
# adversary r2 (codex): a window of one herdr call stays between the last read and the key. The user accepted it
# (2026-10-17, modal «Ventana»: accept and warn): after the key lookout watches this long for another request of the
# agent and, if one comes, says loudly that the «Yes» may have landed on it. Two Bash calls in one message show their
# second dialog only when the first command has run (measured 2026-10-17, > 0.37 s after «Yes»).
VIGILA = 3.0

CABECERA = "Bash command"
PREGUNTA = "Do you want to proceed?"
PIE = "Esc to cancel · Tab to amend"
REGLA = re.compile(r"^\s*╌{3,}\s*$")
BORDE = re.compile(r"^─{3,}$")  # the dialog's top border, as wide as its two rules
OPCION = re.compile(r"^ [❯ ] (\d)\. (.+)$")
SIGUE_OPCION = re.compile(r"^ {6}\S")
BARRA = " │"


def pantalla(pane):
    """The visible screen of the pane as text, "" when herdr cannot read it."""
    code, out, _ = herdr_cli.run(["agent", "read", pane, "--source", "visible"])
    return out or "" if code == 0 else ""


def dialogo_permiso(texto):
    """{"si": number of the option «Yes», "lineas": the command's screen lines, "ancho": a full line's length} when the
    screen ENDS with the Bash permission dialog, read by its whole shape; else None."""
    lineas = (texto or "").splitlines()
    while lineas and not lineas[-1].strip():
        lineas.pop()
    q = max((i for i, l in enumerate(lineas) if l.strip() == PREGUNTA), default=None)
    if q is None:
        return None
    # below the question: the options, a blank line, and the footer as the last thing on the screen
    resto = lineas[q + 1:]
    blanco = next((i for i, l in enumerate(resto) if not l.strip()), None)
    if blanco is None or " ".join(" ".join(l.split()) for l in resto[blanco + 1:]) != PIE:
        return None
    opciones = []
    for l in resto[:blanco]:
        m = OPCION.match(l)
        if m:
            opciones.append([m.group(1), " ".join(m.group(2).split())])
        elif opciones and SIGUE_OPCION.match(l):  # a label wrapped in a narrow pane
            opciones[-1][1] += " " + " ".join(l.split())
        else:
            return None
    numeros = [n for n, _ in opciones]
    si = [n for n, etiqueta in opciones if etiqueta == "Yes"]
    # adversary r5 (codex): the options of the real dialog, numbered 1..N with no gap, one «Yes» and «No» last
    if (len(opciones) < 2 or numeros != [str(i) for i in range(1, len(opciones) + 1)] or len(si) != 1
            or opciones[-1][1] != "No" or sum(1 for _, e in opciones if e == "No") != 1):
        return None
    # above the question: the header, then exactly two rules around the command
    h = max((i for i in range(q) if lineas[i].strip() == CABECERA), default=None)
    if h is None or h == 0:
        return None
    reglas = [i for i in range(h + 1, q) if REGLA.match(lineas[i])]
    if len(reglas) != 2 or reglas[1] - reglas[0] < 2:
        return None
    # adversary r1 (codex): text shaped like the dialog in earlier output; the dialog has its top border right above
    # the header, as wide as its rules (and the prompt box, which follows any output, is gone)
    ancho_regla = len(lineas[reglas[0]].strip())
    if not (BORDE.match(lineas[h - 1].rstrip()) and len(lineas[h - 1].rstrip()) == ancho_regla
            and len(lineas[reglas[1]].strip()) == ancho_regla):
        return None
    # the command's lines carry the bar « │ » (a single call) or one space only (two calls in one message, measured
    # 2026-10-17): one form for the whole block
    bloque = [l.rstrip() for l in lineas[reglas[0] + 1:reglas[1]]]
    if all(l.startswith(BARRA + " ") for l in bloque):
        prefijo = len(BARRA) + 1
    elif all(l.startswith(" ") and not l.startswith(BARRA) and not l.startswith("  ") for l in bloque):
        prefijo = 1
    else:
        return None
    return {"si": si[0], "lineas": [l[prefijo:] for l in bloque], "ancho": ancho_regla - 1, "prefijo": prefijo}


def coincide(comando, dlg):
    """True when the dialog (dialogo_permiso) shows exactly `comando`, wrapped. Between two lines the wrap ate one
    space or none: a line shorter than a full one (`ancho`, the prefix included) broke at ONE space, and only because
    the next word did not fit («origin HEAD» and «originHEAD», or «a  b», do not match it); a full line broke mid-word
    or at one space. A command with a newline is never matched (adversary r2: a newline and a wrap look alike)."""
    lineas, ancho, prefijo = (dlg or {}).get("lineas"), (dlg or {}).get("ancho"), (dlg or {}).get("prefijo")
    if not comando or not lineas or not ancho or not prefijo or "\n" in comando or "\r" in comando:
        return False
    pos = 0
    for i, linea in enumerate(lineas):
        if not linea or comando[pos:pos + len(linea)] != linea:
            return False
        pos += len(linea)
        if i == len(lineas) - 1:
            break
        siguiente = lineas[i + 1].split(" ", 1)[0]
        if prefijo + len(linea) < ancho:
            # broke at a space because the next word did not fit
            if comando[pos:pos + 1] != " " or prefijo + len(linea) + 1 + len(siguiente) <= ancho:
                return False
            pos += 1
        elif comando[pos:pos + 1] == " ":
            pos += 1
    return pos == len(comando)


def pendiente(project_id, entry):
    """The agent's pending Bash permission request: its last event (of its own) when it is a `blocked` from the
    PermissionRequest hook with the whole command; else None."""
    last = None
    for ev in lookout_state.read_events(project_id, 0)[0]:
        if ev.get("session_id") == entry.get("session_id") and ev.get("event") not in deliver.NO_DEL_AGENTE:
            last = ev
    if not (last and last.get("event") == "blocked" and last.get("hook") == "PermissionRequest"
            and last.get("tool_name") == "Bash" and last.get("comando")):
        return None
    return last


def muestra(texto, comando):
    """True when the question text shows the whole command, exactly, between «» (adversary r2: a bare substring let
    «git push origin HEAD:refs…» in the question stand for «git push origin HEAD»)."""
    return bool(comando) and ("«%s»" % comando) in (texto or "")


def otra_peticion(project_id, entry, ts):
    """The first permission request of the agent written after `ts`, or None."""
    for ev in lookout_state.read_events(project_id, 0)[0]:
        if (ev.get("session_id") == entry.get("session_id") and ev.get("event") == "blocked"
                and ev.get("hook") == "PermissionRequest" and float(ev.get("ts") or 0) > float(ts or 0)):
            return ev
    return None


def abre(project_id, entry, texto, si_es, notificar=True):
    """(True, decision) tied to the agent's pending request; (False, why) when there is none to tie it to."""
    if not (si_es and si_es.strip()):
        return False, "una decisión --permiso necesita --si-es \"<etiqueta de la opción sí>\"."
    pend = pendiente(project_id, entry)
    if not pend:
        return False, ("%s no espera un permiso de Bash que yo pueda leer entero (su último evento no es un `espera "
                       "permiso` de Bash con el comando completo): que el usuario lo vea en su pane."
                       % entry.get("nombre"))
    if not muestra(texto, pend["comando"]):
        return False, ("la pregunta debe mostrar el comando entero que pide %s, tal cual y entre «»:\n«%s»"
                       % (entry.get("nombre"), pend["comando"]))
    it = decisiones.abre(project_id, texto, [entry.get("nombre")], notificar=notificar, si_es=si_es, tipo="permiso",
                         permiso={"comando": pend["comando"], "ts": pend.get("ts")})
    return True, it


def aprueba(project_id, entry, did):
    """Press «Yes» once in the agent's permission dialog, after the user's yes (`did`). (ok, message)."""
    nombre, pane = entry.get("nombre"), entry.get("pane_id")
    d = decisiones.respondida(project_id, did) if did else None
    if not (d and d.get("tipo") == "permiso" and d.get("por_hook") and nombre in (d.get("agentes") or ())
            and (d.get("permiso") or {}).get("comando")):
        return False, ("NO: --decision necesita el sí del usuario en tu modal a una decisión --permiso de %s "
                       "(%r no lo es). Ábrela con `lookout decision <proyecto> --abre \"¿Apruebo a %s …? (dN)\" "
                       "--agentes %s --permiso --si-es \"<etiqueta del sí>\"`." % (nombre, did, nombre, nombre))
    if not muestra(d.get("pregunta"), d["permiso"]["comando"]):
        # adversary r1 (codex): the yes counts only for a modal question that showed the command (as its hook wrote it)
        return False, ("NO: la pregunta de tu modal a la que el usuario dijo sí (%s) no mostraba el comando entero: "
                       "no pulso nada. Pregúntale otra vez con el comando tal cual." % did)
    if d.get("usada"):
        return False, "NO: el sí de %s ya se usó en un diálogo; uno por diálogo. Pregunta otra vez." % did
    permiso = d["permiso"]
    pend = pendiente(project_id, entry)
    if not pend:
        return False, ("NO: %s ya no espera ese permiso (su último evento no es la petición que aprobó el usuario): no "
                       "pulso nada." % nombre)
    if pend.get("ts") != permiso.get("ts"):
        return False, ("NO: %s hizo otra petición después de la que aprobó el usuario (%s), aunque sea el mismo "
                       "comando: no pulso nada. Pregúntale otra vez con una decisión nueva." % (nombre, did))
    estado = (herdr_cli.agent_get(pane) or {}).get("agent_status")
    if estado != "blocked":
        return False, "NO: herdr no ve a %s blocked (lo ve %s): no pulso nada." % (nombre, estado or "sin estado")
    dlg = dialogo_permiso(pantalla(pane))
    if not dlg:
        return False, ("NO: el diálogo de permiso de %s no cabe entero en su pantalla o no tiene la forma que conozco "
                       "(cabecera «Bash command», el comando entre sus dos reglas, «Yes» y el pie): no pulso nada. Que "
                       "el usuario lo apruebe en su pane." % nombre)
    if not coincide(permiso["comando"], dlg):
        return False, ("NO: el comando en la pantalla de %s no es el que aprobó el usuario (%s): no pulso nada. "
                       "Pregúntale otra vez." % (nombre, did))
    # adversary r1 (codex): spend the yes first, then check again and press with nothing in between. What is left is
    # the time of one herdr call: a new request can only appear if someone answers this dialog in the pane meanwhile
    # (with it open the agent cannot ask anything else)
    decisiones.marca_usada(project_id, did)
    dlg = dialogo_permiso(pantalla(pane))
    if (pendiente(project_id, entry) or {}).get("ts") != permiso.get("ts") or not coincide(permiso["comando"], dlg):
        return False, ("NO: %s cambió de petición o de pantalla mientras la leía: no pulso nada. Pregúntale otra vez "
                       "con una decisión nueva (este sí ya no vale)." % nombre)
    # the number alone picks it, no Enter (live 2026-10-17)
    herdr_cli.run(["agent", "send-keys", pane, dlg["si"]])
    pulsada = time.time()
    hecho = "Pulsé «Yes» (%s) en el diálogo de %s, una vez, con el sí del usuario (%s)." % (dlg["si"], nombre, did)

    def aviso():
        """adversary r3 (codex): checked on every pass, also while a dialog is still on screen (the dangerous case is
        another dialog drawn right away) and before giving up."""
        otra = otra_peticion(project_id, entry, permiso.get("ts"))
        if not otra:
            return None
        return (hecho + " AVISO AL USUARIO: %.1f s después de la tecla llegó otra petición de %s (%s %s). Si llegó "
                "antes de que corriera su comando, el «Yes» pudo caer en ella: díselo al usuario ya y que mire su pane."
                % (float(otra.get("ts") or 0) - pulsada, nombre, otra.get("tool_name", ""), otra.get("detalle", "")))

    fin, cerrado = pulsada + ESPERA, None
    while True:
        a = aviso()
        if a:
            return False, a
        ahora = time.time()
        if cerrado is None and not dialogo_permiso(pantalla(pane)):
            cerrado = ahora
        if cerrado is not None and ahora >= cerrado + VIGILA:
            return True, hecho
        if cerrado is None and ahora >= fin:
            a = aviso()
            return False, a or ("Pulsé «Yes» (%s) en el diálogo de %s y a los %d s sigue en su pantalla: no pulso más. "
                                "Míralo con el usuario." % (dlg["si"], nombre, ESPERA))
        time.sleep(PASO)

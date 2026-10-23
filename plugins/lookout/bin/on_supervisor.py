#!/usr/bin/env python3
"""Hooks of the SUPERVISOR's own session (Fase 4). Runs behind hooks/guard-sup.sh, which only lets a session
with a supervisor marker through (written by `lookout inicia`); executors never get here.

- PostToolUse[SendMessage]: log what the supervisor told whom (its answers to the agents) and rewrite supervisor.md.
- PreToolUse[AskUserQuestion] (via hooks/guard.sh): log the question as asked; PostToolUse: log the user's answers.
  Both also go to decisiones.json (Fase 9 C4), so no question of the supervisor is off the record.
  A question asked and never answered is a pending user decision in supervisor.md.
- Stop (its own synchronous entry, via hooks/guard-sup.sh; an async hook cannot block): no live waiter, or a decision
  of the user never asked in a modal → keep the turn going once and say what to do (stop_check).
  0.13.4: also a skill text older than the installed lookout (skill_vieja).
- PreCompact: rewrite supervisor.md before the context is summarized.
- SessionStart[compact]: print the «Como retomar» (plain stdout reaches the model's context after a compaction; V14).
Exit 0 always. Its only turn-extending output is the Stop check above, from the synchronous entry; the async on_state.py entry
(--async) never runs it, because an async hook cannot block.
"""
import json
import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import decisiones  # noqa: E402
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
        mid = msg_id(data.get("tool_response"))
        supervisor_md.log(pid, dict({"tipo": "respuesta", "session_id": sid, "to": ti.get("to", ""),
                                     "texto": supervisor_md.one_line(ti.get("message") or ti.get("summary"), 600)},
                                    # 0.13.39: with its msg_id, the whole text, for `lookout reenvia` after a hold
                                    **({"msg_id": mid, "mensaje": str(ti.get("message") or "")} if mid else {})))
    elif ev == "PreToolUse" and tool == "AskUserQuestion":
        # never decide anything here: no output means the question goes to the user as usual
        completas = [str(q.get("question") or "") for q in ti.get("questions") or []]
        preguntas = [supervisor_md.one_line(q, 300) for q in completas]
        supervisor_md.log(pid, {"tipo": "pregunta", "session_id": sid, "tool_use_id": data.get("tool_use_id", ""),
                                "preguntas": preguntas})
        # 0.12.0: the full text, never the 300-char line: the decision id goes at the end (adversary round 2)
        decisiones.registra_pregunta(pid, data.get("tool_use_id", ""), completas)  # Fase 9 C4
        import vigia
        vigia.abre(pid, sid, data.get("tool_use_id", ""))  # 0.13.11: alta and sweep go on while the user decides
    elif ev == "PostToolUse" and tool == "AskUserQuestion":
        import vigia
        vigia.cierra(pid, data.get("tool_use_id", ""))
        tr = data.get("tool_response") or {}
        answers = tr.get("answers") if isinstance(tr, dict) else None
        answers = answers or ti.get("answers") or {}
        supervisor_md.log(pid, {"tipo": "usuario", "session_id": sid, "tool_use_id": data.get("tool_use_id", ""),
                                "answers": answers})
        decisiones.registra_respuesta(pid, data.get("tool_use_id", ""), "; ".join(
            "%s = %s" % (supervisor_md.one_line(q, 80), supervisor_md.one_line(a, 200)) for q, a in answers.items())
            if isinstance(answers, dict) else supervisor_md.one_line(str(answers), 300),
            por_pregunta=answers if isinstance(answers, dict) else None)
    elif ev == "PostToolUseFailure" and tool == "AskUserQuestion":
        import vigia
        vigia.cierra(pid, data.get("tool_use_id", ""))
        return ""
    elif ev == "UserPromptSubmit":
        import vigia
        vigia.cierra(pid)  # the turn that held the modal is over
        import retenido
        if retenido.reacciona(pid, data.get("prompt") or ""):  # 0.13.39: a held message of its own, never the user's
            return ""
        if not respuesta_en_chat(pid, sid, data.get("prompt") or ""):
            return ""
    elif ev == "Stop":
        import vigia
        vigia.cierra(pid)
        return "" if via_async else stop_check(data, pid, sid)
    elif ev == "PreCompact":
        supervisor_md.log(pid, {"tipo": "precompact", "session_id": sid, "trigger": data.get("trigger", "")})
        import digest
        digest.olvida_vistos(pid)  # 0.12.2: the summarized context lost the table the next wake would call unchanged
    elif ev == "SessionStart":
        import vigia
        vigia.cierra(pid)
        supervisor_md.write(pid)
        return ("lookout: tu contexto se acaba de compactar. Eres el supervisor del proyecto %s; tu estado está en %s.\n%s\n"
                % (pid, supervisor_md.path(pid), supervisor_md.retomar_block(pid)))
    else:
        return ""
    supervisor_md.write(pid)
    return ""


def msg_id(resp):
    """0.13.39: the msg_id SendMessage returns (a dict, or its JSON as text), so a held-message notice names the text."""
    if isinstance(resp, str):
        try:
            resp = json.loads(resp)
        except ValueError:
            return ""
    if isinstance(resp, list):  # content blocks
        for b in resp:
            m = msg_id(b.get("text") if isinstance(b, dict) else b)
            if m:
                return m
        return ""
    return str(resp.get("msg_id") or "") if isinstance(resp, dict) else ""


def respuesta_en_chat(pid, sid, prompt):
    """Fase 9 F2: the user may answer in the chat (0.12.0: the supervisor asks in a modal, but a typed answer still
    counts), so the answer arrives as a prompt of its own session. The user's own text (not a peer's message,
    a waiter's notification or a /rename lookout typed) is the answer to the most recent open decision; it is written
    down as given and never counts as a yes (only a --si-es choice in the modal, or `decision --cierra … --si`, authorizes)."""
    import on_state
    p = prompt.lstrip()
    if not p or on_state.ETIQUETA_SISTEMA.match(p) or p.startswith(on_state.LOOKOUT_TECLEA):
        return False
    m = on_state.PEGADO.match(p)
    if m and on_state.ETIQUETA_SISTEMA.match(m.group(1).lstrip()):
        return False
    it = decisiones.registra_respuesta_chat(pid, supervisor_md.one_line(prompt, 300))
    supervisor_md.log(pid, {"tipo": "usuario", "session_id": sid, "decision": (it or {}).get("id", ""),
                            "answers": {"(en el chat%s)" % ((", " + it["id"]) if it else ""):
                                        supervisor_md.one_line(prompt, 300)}})
    return True


def stop_check(data, pid, sid, grace=1.5):
    """Two reminders at the end of the supervisor's turn, only for the lock owner and never when stop_hook_active (no
    loop). They go out together in one output: a second Stop would arrive with stop_hook_active and skip the other.
    - No live waiter (Fase 4 corrida 3: a supervisor that answered every SendMessage stopped relaunching it, and 11 turn
      ends with no report reached nobody): launch `lookout espera`.
    - 0.12.0: a decision opened with `lookout decision --abre` that the user has not answered (3-tier-memory,
      2026-10-15: two decisions in prose, 34 s apart, never answered). Each decision is reminded once.
    The model gets the detail as additionalContext (non-error Stop feedback: the turn goes on, same loop protections
    as a block); the user gets one short line as systemMessage, not the model's instructions."""
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
    sin_waiter = not own_waiter()
    if sin_waiter:
        time.sleep(grace)  # a waiter launched as the turn's last action may not hold its lock yet
        sin_waiter = not own_waiter()
    if sin_waiter and digest.despertar_en_cola(pid, sid, data.get("transcript_path")):
        sin_waiter = False  # B1 (0.12.2): its waiter just woke; the queued notification opens the next turn
    pendientes = [it for it in decisiones.sin_preguntar(pid) if not it.get("recordada")]
    vieja = skill_vieja(pid, sid, data.get("transcript_path"))
    tecleo = tecleo_al_usuario(pid, data.get("transcript_path"), data.get("last_assistant_message"))
    if not sin_waiter and not pendientes and not vieja and not tecleo:
        return ""
    pasos, aviso = [], []
    if sin_waiter:
        pasos.append("no hay waiter vivo para el proyecto %s y sin él no te despierta ningún agente que termine sin "
                     "reportar. Lanza `lookout espera %s` con run_in_background: true (timeout 7200000)." % (pid, pid))
        aviso.append("relanzando el waiter")
    if pendientes:
        decisiones.marca_recordadas(pid, [it["id"] for it in pendientes])
        pasos.append("tienes %d decisión(es) del usuario abierta(s) sin respuesta suya en un modal: %s. Primero "
                     "contesta tú lo reversible que tengas en cola; luego pregúntale todas juntas en UN AskUserQuestion "
                     "(hasta 4 preguntas, una por decisión, con su id al final: «(d3)»; el problema en 1-2 líneas dentro "
                     "de la pregunta; cada opción dice qué pasa y "
                     "si se puede deshacer; la recomendada primero). Nada de prosa antes del modal. Si una ya no aplica, "
                     "ciérrala: `lookout decision %s --cierra <id> --respuesta \"ya no aplica\" --no`."
                     % (len(pendientes), "; ".join("%s%s: %s" % (it["id"], decisiones.etiquetas(it), supervisor_md.one_line(it["texto"], 120))
                                                   for it in pendientes), pid))
        aviso.append("%d decisión(es) para ti en camino" % len(pendientes))
    if vieja:
        cargada, instalada = vieja
        pasos.append("la skill supervisa que tienes cargada es la %s y la instalada es la %s (/reload-plugins no recarga "
                     "el texto de una skill ya cargada). Vuelve a cargarla ahora con la herramienta Skill "
                     "(`lookout:supervisa` con la ruta del proyecto) y sigue sus reglas desde ahí; si vuelve a salir "
                     "la %s, pide al usuario /reload-plugins." % (cargada, instalada, cargada))
        aviso.append("skill supervisa %s cargada, %s instalada: la recargo" % (cargada, instalada))
    if tecleo:
        agente, texto, negado = tecleo
        # codex r2: the agent's command goes into the printed recipe only through shlex.quote; between double quotes a
        # `$(…)` or a backtick of it would run in the supervisor's shell (the same rule as teclea's recipe, 0.13.46)
        q = shlex.quote
        abre = q("<qué hace el comando, con «! %s» entero>" % texto)
        if negado is None:
            receta = ("No tengo un evento de un agente con este comando exacto. Si es de un agente (por ejemplo uno cuya "
                      "orden reescribiste), usa a ese agente y `--negado` si auto mode se la negó. Si no es de ninguno, "
                      "elige un agente quieto de `lookout resumen %s` (el grupo «listo»): corre `lookout decision %s --abre %s --agentes <agente quieto> --si-es \"<etiqueta del "
                      "sí>\"`, pregunta en el modal y, con su sí, `lookout envia %s <agente quieto> --usuario-confirmo dN "
                      "--texto %s`. Solo si `envia` se niega o ningún agente está quieto, sigue como estabas y pídeselo al "
                      "usuario." % (q(pid), q(pid), abre, q(pid), q("! " + texto)))
            pasos.append("pediste al usuario que escriba en TU pestaña «! %s». %s Reescribe tu respuesta sin ese paso de "
                         "«Lo que necesito de ti», salvo en esos dos casos." % (texto, receta))
        else:
            if negado:
                receta = ("Corre `lookout decision %s --abre %s --agentes %s --negado --si-es \"<etiqueta del sí>\" "
                          "--siempre-es \"<etiqueta del siempre>\"`, pregunta en el modal y, con su sí, el `lookout envia` "
                          "que imprime." % (q(pid), abre, q(agente)))
            else:
                receta = ("Corre `lookout decision %s --abre %s --agentes %s --si-es \"<etiqueta del sí>\"`, pregunta en el "
                          "modal y, con su sí, `lookout envia %s %s --usuario-confirmo dN --texto %s`."
                          % (q(pid), abre, q(agente), q(pid), q(agente), q("! " + texto)))
            pasos.append("pediste al usuario que escriba en TU pestaña «! %s», pero ese comando es de «%s» (%s). No se lo "
                         "pidas: lo tecleas tú en el pane del agente, con el sí del usuario en tu modal. %s Si dice `NO "
                         "ABIERTA`, haz lo que dice. Reescribe tu respuesta sin ese paso de «Lo que necesito de ti»."
                         % (texto, agente, "auto mode se lo negó" if negado else "el agente lo pidió", receta))
        aviso.append("el supervisor te preguntará en un modal antes de teclear un comando en el pane de un agente")
    if sin_waiter and pendientes:
        pasos[0] += (" Hazlo ANTES del modal: el modal te deja parado hasta que el usuario conteste (las altas y el barrido "
                     "los sigue el vigía del modal; lo que te despierta, solo el waiter).")
    detalle = " ".join("%d) %s" % (i + 1, t) for i, t in enumerate(pasos)) if len(pasos) > 1 else pasos[0]
    return json.dumps({"systemMessage": "lookout: " + "; ".join(aviso) + ".",
                       "hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": "lookout: " + detalle}},
                      ensure_ascii=False)


def ultimo_texto(transcript_path, max_bytes=200000):
    """Text of the last assistant message of the transcript that has any, or ''."""
    try:
        with open(transcript_path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - max_bytes))
            filas = fh.read().decode("utf-8", "replace").splitlines()
    except (OSError, TypeError):
        return ""
    for fila in reversed(filas):
        try:
            d = json.loads(fila)
        except ValueError:
            continue
        msg = d.get("message") if d.get("type") == "assistant" else None
        c = (msg or {}).get("content")
        if isinstance(c, list):
            t = "\n".join(b.get("text") or "" for b in c if isinstance(b, dict) and b.get("type") == "text").strip()
            if t:
                return t
    return ""


def sin_codigo_en_linea(linea):
    """A line that is one inline-code span loses its fence: equal runs of backticks at both ends (`! cmd`, or
    ``! echo `date` `` for a command with a backtick in it, the markdown way) and the space inside them. A line that
    does not start with a backtick, like «! echo `date`», keeps every one of them (adversary r4)."""
    l = linea.strip()
    n = len(l) - len(l.lstrip("`"))
    if n and l.endswith("`" * n) and len(l) > 2 * n and not l[len(l) - n - 1:len(l) - n] == "`":
        interior = l[n:len(l) - n]
        return (interior[1:-1] if interior[:1] == interior[-1:] == " " and len(interior) > 2 else interior).strip()
    return l


def en_cita(comando, cita, corte=200):
    """The command is in the agent's quoted line. on_state clips the quote to `corte` characters (codex r2), so a
    command the clip cut matches when what is left of it at the end of the quote is its start (12 characters at least)."""
    if comando in cita:
        return True
    return len(cita) >= corte and any(len(cita) - i >= 12 and comando.startswith(cita[i:]) for i in range(len(cita)))


def tecleo_al_usuario(pid, transcript_path, ultimo=None):
    """0.13.51 (3-tier-memory, 2026-10-22): an agent had its Bash refused by auto mode and the supervisor, six turns in a
    row, wrote «Lo que necesito de ti: 1. Escribe esto en esta pestaña, «Supervisor»: ! …» instead of opening
    `lookout decision --negado` and typing it in the agent's pane. The skill said so since 0.13.46 and the digest line
    showed the refusal; nothing checked. If the last message has a «! comando» line equal to a Bash an agent of this
    project was refused (negado, whole command) or that an agent asked to have typed (espera_pane), → (agent, command,
    refused?), once per command and event. A command no event matches is the «no owner» case: (None, command, None),
    once per command, only with agents registered (the supervisor's own refusal leaves no event). A command an event
    matched never falls into it, even after that event's warning was spent. Else None. `ultimo` is the Stop payload's last_assistant_message: the
    transcript can lack the turn's last row when Stop reads it (0.13.40, learning 154), so the payload wins."""
    import lookout_state
    import registry
    import teclea
    texto = ultimo if isinstance(ultimo, str) and ultimo.strip() else ultimo_texto(transcript_path) if transcript_path else ""
    pedidos = [sin_codigo_en_linea(l) for l in texto.splitlines()]
    pedidos = [l[2:].strip() for l in pedidos if l.startswith("! ") and len(l) > 2]
    if not pedidos:
        return None
    agentes = registry.load(pid).get("agents") or {}
    path = os.path.join(lookout_state.project_dir(pid), "tecleo_avisado.json")
    avisados = lookout_state.read_json(path) or {}
    con_dueno = set()
    eventos = list(reversed(lookout_state.read_events(pid, 0)[0]))
    # a refusal wins over an idle event that quotes the same command: it has the `--negado` recipe
    eventos.sort(key=lambda e: e.get("event") != "negado")
    for ev in eventos:
        nombre = (agentes.get(ev.get("session_id")) or {}).get("nombre") or ev.get("nombre")
        if not nombre:
            continue
        if ev.get("event") == "negado" and ev.get("hook") == "PermissionDenied" and ev.get("tool_name") == "Bash":
            # events of lookout before 0.13.46 carry the command only as `detalle` (maybe clipped): enough to recognize it
            # and `decision --negado` cannot open on them (teclea.negados needs `comando`): they get the plain recipe
            # (codex r1: permisos clips `detalle` to 200 characters; a clipped one is not the command that was refused)
            cmd = ev.get("comando") or (ev.get("detalle") or "" if len(ev.get("detalle") or "") < 200 else "")
            propios = [cmd] if teclea.linea(cmd) else []
            negado = bool(ev.get("comando"))
        elif ev.get("event") in ("idle", "bg_wait") and (ev.get("espera_pane") or {}).get("cita"):
            propios = [c for c in pedidos if en_cita(c, ev["espera_pane"]["cita"])]
            negado = False
        else:
            continue
        for c in propios:
            if c in pedidos:
                con_dueno.add(c)   # an agent owns it, warned or not: never the «no owner» case (adversary r6)
            clave = "%s|%s|%s" % (ev.get("ts"), nombre, c)
            if c in pedidos and clave not in avisados:
                avisados[clave] = True
                lookout_state.write_json(path, avisados)
                return nombre, c, negado
    # no agent owns it (the supervisor's own refusal leaves no event): the user's choice of 2026-10-23 is a quiet agent's
    # pane with his yes in the modal, once per command; the supervisor goes on by hand if that fails (envia refuses)
    if agentes:
        for c in pedidos:
            clave = "sin_dueno|%s" % c
            if c not in con_dueno and clave not in avisados:
                avisados[clave] = True
                lookout_state.write_json(path, avisados)
                return None, c, None
    return None


SKILL_CARGADA = re.compile(rb"Base directory for this skill: ([^\"\\\n]*?)/lookout/([0-9][^/\"\\\n]*)/skills/supervisa")


def _ver(v):
    """Semver order for the plugin's versions: a pre-release sorts before its release, rc1 before rc2 (adversary r2)."""
    m = re.match(r"(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?", str(v))
    if not m:
        return (-1,)
    pre = m.group(4)
    if not pre:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)), 1)
    partes = tuple((0, int(x), "") if x.isdigit() else (1, 0, x) for x in re.split(r"[.-]|(?<=[A-Za-z])(?=\d)", pre) if x)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), 0) + partes


def installed_plugins_path():
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(base, "plugins", "installed_plugins.json")


def skill_vieja(pid, sid, transcript_path):
    """0.13.4 (p-72a8efc1a9): 3-tier-memory, 2026-10-15 and 16: after /plugin and /reload-plugins the supervisor went
    on with the skill text it had loaded (0.10.0 all day, then 0.13.2 with 0.13.3 installed). The last «Base directory
    for this skill» of lookout's supervisa in the transcript says which version it loaded; installed_plugins.json says
    which one is installed. Different → (cargada, instalada), once per pair and session. The transcript is read
    from where the previous Stop left it. Unsure (no transcript, no entry, a dev install) → None."""
    import lookout_state
    if not transcript_path:
        return None
    path = os.path.join(lookout_state.project_dir(pid), "skill_cargada.json")
    st = lookout_state.read_json(path) or {}
    if st.get("transcript") != transcript_path or st.get("session_id") != sid:
        st = {"transcript": transcript_path, "session_id": sid}
    try:
        with open(transcript_path, "rb") as fh:
            head = fh.read(256).hex()
            fh.seek(0, 2)
            size = fh.tell()
            off = int(st.get("offset") or 0)
            if off > size or (st.get("cabeza") and st["cabeza"] != head):  # truncated or replaced in place (adversary r1)
                off, st["cargada"] = 0, None
            st["cabeza"] = head if size >= 256 else None
            fh.seek(max(0, off - 300))  # a match split by the previous read
            found = SKILL_CARGADA.findall(fh.read())
    except OSError:
        return None
    if found:
        base, version = found[-1]
        st["cargada"] = version.decode("utf-8", "replace")
        st["marketplace"] = os.path.basename(base.decode("utf-8", "replace"))
    st["offset"] = size
    instalada = None
    if st.get("cargada") and st.get("marketplace"):
        entries = (lookout_state.read_json(installed_plugins_path()) or {}).get("plugins") or {}
        for e in entries.get("lookout@" + st["marketplace"]) or []:
            if isinstance(e, dict) and e.get("version"):
                instalada = str(e["version"])
                break
    out = None
    if instalada and _ver(instalada) > _ver(st["cargada"]):  # a newer loaded text is no reason (adversary r1)
        par = "%s>%s" % (st["cargada"], instalada)
        if st.get("avisada") != par:
            st["avisada"] = par
            out = (st["cargada"], instalada)
    lookout_state.write_json(path, st)
    return out


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

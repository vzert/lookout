"""The permission-mode class of the supervisor and its agents (0.13.33).

Claude Code holds a cross-session message for the user's approval when one session bypasses permission prompts and the
other does not ("The sending session's permission mode class doesn't match this session's"), in both directions, and
drops it when the dialog stays unanswered past `dialogExpiry` (5 min by default). A supervisor and an agent in different
classes lose questions and answers that way (user report, 2026-10-19, supervisor-POS_MEGAMAYOREO).

- A fresh agent starts in the supervisor's own mode (lote.lanza_uno). A bypass one only when the user chose it.
- An agent registered while it bypasses and the supervisor does not is moved with Shift+Tab, read on its footer after
  each press, until a prompting mode that is not plan (plan counts as bypass when bypass is available).
- A bypassing supervisor never raises an agent: it can't by Shift+Tab (bypass is in the cycle only for a session
  started with it) and it is the user's call; the registration says so and the supervisor tells the user.
"""
import os
import time

import herdr_cli
import lookout_state

BYPASS = "bypassPermissions"
# Footer of Claude Code's prompt box, all five measured 2026-10-19 in herdr panes. A session started with
# --dangerously-skip-permissions went from bypass to auto with one Shift+Tab; a message from this supervisor (auto) sent
# before the press was held, another sent after it was delivered. The footer is a line that starts with ⏵⏵ or ⏸ among
# the last lines of the screen (a list of background agents can follow it, measured on 23 live panes); a dialog in those
# lines means there is none, and nothing is pressed (a mode quoted by the conversation does not count; adversary r1).
PIES = (("bypass permissions on", BYPASS), ("auto mode on", "auto"), ("accept edits on", "acceptEdits"),
        ("plan mode on", "plan"), ("manual mode on", "default"))
SIMBOLOS = ("⏵⏵", "⏸")
DIALOGO = ("esc to cancel", "enter to select", "enter to confirm")
ULTIMAS = 8
MAX_PULSACIONES = 6  # the cycle has at most 5 modes: one more than that and the footer is not doing what we think
PAUSA = 0.6  # s between a press and the read of the footer


def clase(m):
    """'bypass', 'permisos' or '' (unknown; plan is bypass only when bypass is available, which we can't see)."""
    if m == BYPASS:
        return "bypass"
    if m in ("default", "auto", "acceptEdits", "dontAsk"):
        return "permisos"
    return ""


def pie(texto):
    """The mode the footer names, or '' (no footer among the last ULTIMAS non-blank lines, or a dialog there)."""
    ultimas = [l.strip() for l in (texto or "").splitlines() if l.strip()][-ULTIMAS:]
    if any(d in l.lower() for l in ultimas for d in DIALOGO):
        return ""
    for line in reversed(ultimas):
        if line.startswith(SIMBOLOS):
            low = line.lower()
            for marca, m in PIES:
                if marca in low:
                    return m
    return ""


def de_sesion(session_id):
    """A session's permission mode from its transcript's last `permission-mode` row, or ''."""
    if not session_id:
        return ""
    import deliver
    import retomar
    return retomar.config(deliver.transcript_path(session_id)).get("permisos", "")


def del_supervisor(project_id):
    lk = lookout_state.read_json(os.path.join(lookout_state.project_dir(project_id), "lock.json")) or {}
    return de_sesion((lk.get("supervisor") or {}).get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID", ""))


def para_lanzar(project_id, bypass=False):
    """The --permission-mode of a fresh agent: the supervisor's own when it prompts; bypass only when the user chose it;
    '' (Claude Code's default) when the supervisor's mode is plan or unknown."""
    m = del_supervisor(project_id)
    if clase(m) == "permisos":
        return m
    if clase(m) == "bypass" and bypass:
        return BYPASS
    return ""


def aviso_lanzar(project_id):
    """One line for the batch proposal when the supervisor bypasses, else ''."""
    if clase(del_supervisor(project_id)) != "bypass":
        return ""
    return ("MODO: este supervisor se salta los permisos (bypass). Un agente en otro modo no recibe tus mensajes sin que "
            "el usuario apruebe cada uno, ni tú los suyos. En la pregunta del lote añade la opción «Lanzar sin pedir "
            "permisos (bypass), como el supervisor» (`lookout lanza … --bypass`: el agente ejecuta todo sin pedir permiso) junto a «Lanzar en el "
            "modo normal» (sin --bypass: habrá mensajes retenidos). Nunca elijas tú.")


def leer_pie(pane):
    code, out, _ = herdr_cli.run(["agent", "read", pane, "--source", "visible"])
    return pie(out) if code == 0 else ""


def baja(pane):
    """Shift+Tab until the footer names a prompting mode that is not plan. Returns that mode, or '' when it didn't."""
    actual = leer_pie(pane)
    if clase(actual) == "permisos":
        return actual
    if not actual:
        return ""  # no footer to read (a dialog, a menu): a key there could pick something
    for _ in range(MAX_PULSACIONES):
        if herdr_cli.run(["agent", "send-keys", pane, "shift+tab"])[0] != 0:
            return ""
        time.sleep(PAUSA)
        actual = leer_pie(pane)
        if clase(actual) == "permisos":
            return actual
        if not actual:
            return ""
    return ""


def empata(project_id, found):
    """For each newly registered agent ({session_id, pane_id, status}), match its class to the supervisor's.
    Returns {session_id: {estado, agente, supervisor[, ahora]}} only for the agents in another class; estado is
    'bajado', 'sin-bajar' (it bypasses and could not be moved) or 'supervisor-bypass'."""
    sup = del_supervisor(project_id)
    out = {}
    if not clase(sup):
        return out  # nothing to match against: not even a read of a footer
    for f in found:
        sid = f.get("session_id")
        # The footer first: a session has no transcript before its first prompt (measured 2026-10-19), and a Shift+Tab
        # of the user's shows there at once. The transcript when the footer is not readable (a dialog on screen).
        ag = (leer_pie(f["pane_id"]) if f.get("pane_id") else "") or de_sesion(sid)
        cs, ca = clase(sup), clase(ag)
        if not cs or not ca or cs == ca:
            continue
        r = {"agente": ag, "supervisor": sup}
        if cs == "bypass":
            r["estado"] = "supervisor-bypass"
        else:
            ahora = baja(f.get("pane_id", "")) if f.get("pane_id") and f.get("status") != "blocked" else ""
            r.update(estado="bajado" if ahora else "sin-bajar", **({"ahora": ahora} if ahora else {}))
            if ahora:
                guarda(project_id, sid, ahora)
        out[sid] = r
    return out


def guarda(project_id, sid, ahora):
    """The registry's `permisos` of a registered agent after a Shift+Tab moved it."""
    import lote
    import registry
    with lote.project_mutex(project_id):
        reg = registry.load(project_id)
        e = reg.get("agents", {}).get(sid)
        if e is not None:
            e["permisos"] = ahora
            registry.save(project_id, reg)


def describe(r):
    """The supervisor's short note for a registration result of empata, or ''. Short: the digest clips at 160."""
    if not r:
        return ""
    if r.get("estado") == "bajado":
        return "modo %s→%s con Shift+Tab" % (r.get("agente"), r.get("ahora"))
    if r.get("estado") == "supervisor-bypass":
        return "MODO DISTINTO → díselo al usuario (tú bypass, él %s)" % r.get("agente")
    return "MODO DISTINTO → díselo al usuario (él %s, tú %s; no bajó)" % (r.get("agente"), r.get("supervisor"))

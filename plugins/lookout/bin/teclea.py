"""0.13.46: a Bash command auto mode's classifier refused, typed as «! comando» in the agent's pane with the user's yes.

The agent cannot run it (the classifier said no) and before this the user had to copy the line from the agent's pane
and run it there (claude-vzert user, 2026-10-21: «Teclea esta línea completa, con el ! y la ruta absoluta…»). Now the
supervisor asks in its own modal, with the whole command between «», and types it with `lookout envia`. Nothing is
typed without the user's literal choice (decisiones.registra_respuesta): `si_es` types it once; `siempre_es` lets the
same command, in the same cwd, for the same agent, be typed again after each new refusal while this supervisor holds
the lock, without asking again. A multi-line command, one with a character outside a Latin keyboard (visible()) or one with «» in it, is never offered: the user runs it.
"""
import shlex
import unicodedata

import lock
import lookout_state
import decisiones


def negados(project_id, entry):
    """The agent's Bash refusals with the whole command, oldest first."""
    return [ev for ev in lookout_state.read_events(project_id, 0)[0]
            if ev.get("session_id") == entry.get("session_id") and ev.get("event") == "negado"
            and ev.get("hook") == "PermissionDenied"  # never lookout's own denials (kill, shared tree)
            and ev.get("tool_name") == "Bash" and ev.get("comando")]


def visible(ch):
    """True for a character of a Latin keyboard, which the modal shows as itself: printable ASCII, «¡¿» and the
    accented Latin letters (Latin-1 and Latin Extended-A/B). codex r1-r3: every list built on Unicode categories left a
    character that draws blank (a combining mark, a filler, a hieroglyph «full blank», U+303F); the Lo letters of this
    range stay out too (U+01C0 «ǀ» looks like «|»). A command in another script is not offered: the user runs it in
    the agent's pane."""
    o = ord(ch)
    return 0x20 <= o <= 0x7E or ch in "¡¿" or (0xC0 <= o <= 0x24F and unicodedata.category(ch) in ("Lu", "Ll", "Lt"))


def linea(comando):
    """The text typed in the pane, or None when it cannot go as one «! …» line the modal can quote."""
    c = comando or ""
    # codex r1: checked as refused, never trimmed first: a trim hid a tab or a newline at either end, and
    # `envia` trims what it types, so a command with spaces at an end («echo a \\ ») would run as another one
    if c != c.strip():
        return None
    # adversary r1-r2 (sonnet), codex r2-r3: a control character is a keystroke in the pane, and a format character,
    # a combining mark, a filler or a non-ASCII space hides or changes part of the line in the modal: only visible()
    if not c or "«" in c or "»" in c or any(not visible(ch) for ch in c):
        return None
    return "! " + c


def supervisor_actual(project_id):
    return ((lock.read(project_id) or {}).get("supervisor") or {}).get("session_id") or ""


def siempre(project_id, entry, comando, cwd):
    """The user's «siempre» decision that covers this command, cwd and agent under the current supervisor, or None."""
    sup = supervisor_actual(project_id)
    for d in reversed(decisiones.load(project_id)["items"]):
        n = d.get("negado") or {}
        if (d.get("tipo") == "negado" and d.get("siempre") and d.get("aprueba") is True and d.get("por_hook")
                and entry.get("nombre") in (d.get("agentes") or ()) and n.get("comando") == comando
                and n.get("cwd") == cwd and sup and n.get("supervisor") == sup):
            return d
    return None


def abre(project_id, entry, texto, si_es, siempre_es="", notificar=True):
    """(True, decision) tied to the agent's last Bash refusal; (False, why) when it cannot be offered."""
    if not (si_es and si_es.strip()):
        return False, "una decisión --negado necesita --si-es \"<etiqueta de la opción sí>\"."
    if siempre_es and siempre_es == si_es:
        return False, "--siempre-es y --si-es deben ser dos etiquetas distintas."
    ev = (negados(project_id, entry) or [None])[-1]
    if not ev:
        return False, ("no tengo un Bash negado de %s con el comando entero: que el usuario lo vea en su pane."
                       % entry.get("nombre"))
    tecla = linea(ev["comando"])
    if not tecla:
        return False, ("el comando negado de %s tiene varias líneas, espacios al principio o al final, «» o caracteres que no son de un teclado latino: no lo puedo teclear como una línea. Dile al "
                       "usuario que lo corra él en su pane." % entry.get("nombre"))
    ya = siempre(project_id, entry, ev["comando"], ev.get("cwd"))
    if ya:
        return False, ("el usuario ya dijo «siempre» a este comando en %s (%s): no le preguntes otra vez. Corre `lookout "
                       "envia %s %s --usuario-confirmo %s --texto %s`, tal cual."
                       % (ya["id"], ya.get("respuesta"), project_id, entry.get("nombre"), ya["id"], shlex.quote(tecla)))
    if ("«%s»" % tecla) not in (texto or ""):
        return False, ("la pregunta debe mostrar lo que voy a teclear, entero y entre «»:\n«%s»" % tecla)
    it = decisiones.abre(project_id, texto, [entry.get("nombre")], notificar=notificar, si_es=si_es, tipo="negado",
                         negado={"comando": ev["comando"], "cwd": ev.get("cwd"), "ts": ev.get("ts"),
                                 "supervisor": supervisor_actual(project_id)},
                         siempre_es=siempre_es)
    return True, it


def clave(project_id, entry, d, texto):
    """The delivery key for typing `texto` with the negado decision `d`, or (None, why). A once-only yes is one key per
    decision; a «siempre» yes is one key per refusal, so each new refusal of the same command types it once."""
    n = d.get("negado") or {}
    if texto != linea(n.get("comando")):
        return None, "%s es sobre «%s», no sobre «%s»." % (d["id"], linea(n.get("comando")), texto)
    if not d.get("siempre"):
        return "usuario:" + d["id"], None
    if not siempre(project_id, entry, n.get("comando"), n.get("cwd")):
        return None, ("el «siempre» de %s ya no vale: otro supervisor tiene el proyecto. Pregúntale al usuario otra vez."
                      % d["id"])
    ultimo = next((ev for ev in reversed(negados(project_id, entry))
                   if ev["comando"] == n.get("comando") and ev.get("cwd") == n.get("cwd")), None)
    if not ultimo:
        return None, "%s no tiene un Bash negado con ese comando y ese directorio." % entry.get("nombre")
    return "usuario:%s:%s" % (d["id"], ultimo.get("ts")), None

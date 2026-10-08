"""Close a finished pendiente through the 3-tier journal (docs/plan.md 3.8 step 8, F3).

Only `journal-emit.py --type pendiente.resolve`, against the SUPERVISED repo's own memory/ (the main
checkout: memory/ is gitignored, so a worktree has none). Never an edit of _pendientes.md: the
compactor applies the event at its next run (3-tier's SessionStart or /checkpoint-3t), and this script
checks that _pendientes.md did not change when the event was written.

Preconditions, all checked here: the agent has a task; its last quoted adversary verdict is hold
(gobierno); the task's commits are on origin (or the supervisor states why no push was needed: an
investigation or a task without code); and the user confirmed the close in the supervisor's chat.
Residual findings are NOT written here: the user chose (2026-10-02) that the supervisor only proposes
them, with the exact command, and the user decides.
"""
import glob
import hashlib
import os
import subprocess

import gobierno
import lote
import pendientes
import publica
import registry
import requisitos


def tier_bin():
    """3-tier's bin/: LOOKOUT_3TIER_BIN, else what its own resolve-plugin-bin.sh says, else the newest cached."""
    env = os.environ.get("LOOKOUT_3TIER_BIN")
    if env:
        return env
    cands = glob.glob(os.path.join(requisitos.config_dir(), "plugins", "cache", "*", "3-tier-memory",
                                   "*", "bin", "resolve-plugin-bin.sh"))
    for c in cands:
        try:
            out = subprocess.run(["bash", c], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            continue
        path = out.stdout.strip().splitlines()[-1] if out.returncode == 0 and out.stdout.strip() else ""
        if path and os.path.isfile(os.path.join(path, "journal-emit.py")):
            return path
    best = sorted(cands, key=lambda p: [int(x) if x.isdigit() else 0 for x in p.split("/")[-3].split(".")])
    return os.path.dirname(best[-1]) if best else ""


def digest_file(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return ""


def published(entry):
    """True if the agent's HEAD is already in origin's base branch."""
    wt = entry.get("worktree") or entry.get("cwd")
    tip = publica.remote_tip(wt, publica.remote_branch(entry))
    if not tip:
        return False
    _, head = publica.git(wt, "rev-parse", "HEAD")
    return publica.git(wt, "merge-base", "--is-ancestor", head.strip(), tip)[0] == 0 if head.strip() else False


def cierra(project_id, common_dir, entry, st, estado, nota, usuario_confirmo, sin_push="", run=subprocess.run):
    """(ok, lines)."""
    tarea = entry.get("tarea")
    if not tarea:
        return False, ["NO: %s no tiene un pendiente asignado." % entry.get("nombre")]
    if not usuario_confirmo:
        return False, ["NO: cerrar un pendiente lo confirma el usuario. Abre la decisión (`lookout decision … --abre`), "
                       "pregúntale (en el chat si hay agentes vivos), ciérrala con su respuesta y repite con "
                       "--usuario-confirmo <id>."]
    last = st["ultimo"]
    # Fase 9 C2: abandoning (or superseding) claims no result: no hold and no push needed, only the user's yes.
    sin_resultado = estado != "resolved"
    if not sin_resultado and (not last or last["veredicto"] != "hold"):
        return False, ["NO: sin hold del adversario (último: %s). Verificación independiente antes de cerrar." % (
            last["linea"] if last else "ninguno")]
    if not sin_resultado and not sin_push and not entry.get("sin_worktree") and not published(entry):
        return False, ["NO: los commits de %s no están en origin. Publica primero (lookout publica), o di por qué esta "
                       "tarea no necesita push con --sin-push \"<razón>\"." % entry.get("nombre")]
    nota_full = nota + (" — sin push: " + sin_push if sin_push else "")
    ok, lines = emite(common_dir, tarea, estado, nota_full, entry["session_id"], run)
    if lines and lines[0].startswith("NO:"):
        return False, lines
    lote.set_estado(project_id, entry["session_id"], "terminada", "cerrado por journal")
    publica.retira_sesion(project_id, entry["session_id"], "cerrada")
    return ok, lines


def emite(common_dir, tarea, estado, nota, sesion, run=subprocess.run):
    """One pendiente.resolve event in the supervised repo's own journal. (ok, lines); lines[0] starts with "NO:" when
    nothing was written."""
    root = lote.repo_root(common_dir)
    mem = os.path.join(root, "memory")
    pend_file = os.path.join(mem, "_pendientes.md")
    items = {it["id"]: it for it in pendientes.parse(pend_file)}
    it = items.get(tarea)
    if not it:
        return False, ["NO: %s no está abierto en %s (¿ya cerrado?)." % (tarea, pend_file)]
    tb = tier_bin()
    if not tb:
        return False, ["NO: no encuentro el plugin 3-tier (journal-emit.py)."]
    before = digest_file(pend_file)
    cmd = ["python3", os.path.join(tb, "journal-emit.py"), "--memory-dir", mem, "--type", "pendiente.resolve",
           "--id", tarea, "--estado", estado, "--nota", nota, "--sesion", sesion, "--text-prefix", it["texto"][:40]]
    try:
        out = run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, ["NO: journal-emit falló: %s" % exc]
    if out.returncode != 0:
        return False, ["NO: journal-emit salió %d: %s" % (out.returncode, (out.stderr or out.stdout).strip()[:300])]
    after = digest_file(pend_file)
    return before == after, [
        "Evento pendiente.resolve escrito en %s/.journal (id %s, estado %s)." % (mem, tarea, estado),
        "_pendientes.md %s." % ("sin cambios: se actualiza al compactar el journal (SessionStart de 3-tier o "
                                "/checkpoint-3t)" if before == after else "CAMBIÓ al emitir: revisa (no debía)")]


def descarta(project_id, common_dir, tarea, estado, nota, usuario_confirmo, sesion, run=subprocess.run):
    """Fase 9 C1: close a pendiente that never had an agent (abandoned or superseded), through the journal and with
    the user's yes. Until now there was no way, and the supervisor emitted journal events by hand. (ok, lines)"""
    if estado not in ("abandoned", "superseded"):
        return False, ["NO: `descarta` solo cierra como abandoned o superseded; uno resuelto lo cierra `lookout cierra` "
                       "con el agente que lo hizo."]
    if not usuario_confirmo:
        return False, ["NO: descartar un pendiente lo confirma el usuario. Abre la decisión (`lookout decision … "
                       "--abre`), pregúntale (en el chat si hay agentes vivos), ciérrala con su respuesta y repite con "
                       "--usuario-confirmo <id>."]
    for e in lote.tasks(registry.load(project_id)):
        if e.get("tarea") == tarea and e.get("tarea_estado") not in ("terminada", "fallida"):
            return False, ["NO: %s tiene un agente (%s, %s). Ciérralo con `lookout cierra … --estado %s`." % (
                tarea, e.get("nombre"), e.get("tarea_estado") or "-", estado)]
    return emite(common_dir, tarea, estado, nota, sesion, run)

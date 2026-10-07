"""Publishing in order (H14) and the temporary push rule (H15), docs/plan.md F3.

H14: several agents ready to publish from the same base all wanted the same version. Here the
publications of a project form ONE queue (publicaciones.json): one agent has the turn; before its push
goes to the user the supervisor checks on its own, read-only, in the agent's worktree:
  the adversary gate (gobierno.decide_push), a clean tree, the base it builds on is origin's CURRENT
  tip and a fast-forward, the commit list, a version that is new against origin and against every
  other publication in the ledger, and no private paths in the added lines.
Anything else is a NO with what to do (fetch + rebase + renumber + suites, then ask again).

H15: auto mode refused a push the user approved through the coordinator's message. A message is not
consent; a permission rule the user writes is. `regla` prints the exact rule text for the main
checkout's .claude/settings.local.json (V13, 2026-10-02: that one file covers every linked worktree,
also `<repo>-wt-*`, and a live session reads it and drops it without restarting). Nothing here
writes that file: `regla_estado` only reads it.
"""
import json
import os
import re
import subprocess
import time

import gobierno
import lookout_state

ALLOW = ["Bash(git push origin *)", "Bash(gh workflow run *)"]
DENY = ["Bash(git push --force*)", "Bash(git push -f*)", "Bash(git push * --force*)", "Bash(git push * -f*)",
        "Bash(git push origin +*)", "Bash(git push * --delete*)", "Bash(git push * -d *)",
        "Bash(git push origin :*)", "Bash(git push * --mirror*)"]
PRIVATE_RE = re.compile(r"/Users/[^/\s'\"]+|/home/[^/\s'\"]+|/root/|/var/root/|/private/(?:tmp|var)/|/var/folders/|"
                        r"(?<![\w.])/tmp/|/var/tmp/|(?<![\w])~/")
SEMVER_RE = re.compile(r"\b(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\b")
VIVAS = ("turno", "lista")


def git(wt, *args, timeout=20):
    try:
        out = subprocess.run(["git", "-C", wt] + list(args), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return 124, ""
    return out.returncode, out.stdout


# ---------- version of a tree ----------

def version_at(wt, rev):
    """(file, version) the tree at `rev` declares, or ('', '') if it has no version file.
    Order: VERSION, package.json, pyproject.toml, the shallowest .claude-plugin/plugin.json, CHANGELOG.md."""
    code, out = git(wt, "ls-tree", "-r", "--name-only", rev)
    if code != 0:
        return "", ""
    files = out.splitlines()
    plugin = sorted((f for f in files if f.endswith(".claude-plugin/plugin.json")), key=lambda f: f.count("/"))
    for f in ["VERSION", "package.json", "pyproject.toml"] + plugin[:1] + ["CHANGELOG.md"]:
        if f not in files:
            continue
        code, body = git(wt, "show", "%s:%s" % (rev, f))
        if code != 0:
            continue
        v = ""
        if f.endswith(".json"):
            try:
                v = str(json.loads(body).get("version") or "")
            except ValueError:
                v = ""
        elif f == "pyproject.toml":
            m = re.search(r'^\s*version\s*=\s*["\']([^"\']+)', body, re.M)
            v = m.group(1) if m else ""
        elif f == "CHANGELOG.md":
            m = next((SEMVER_RE.search(l) for l in body.splitlines() if l.startswith("#") and SEMVER_RE.search(l)), None)
            v = m.group(1) if m else ""
        else:
            m = SEMVER_RE.search(body)
            v = m.group(1) if m else body.strip()
        if v:
            return f, v
    return "", ""


def is_version_file(path):
    base = os.path.basename(path)
    return base in ("VERSION", "package.json", "pyproject.toml", "CHANGELOG.md") or path.endswith(".claude-plugin/plugin.json")


# ---------- ledger ----------

def ledger_path(project_id):
    return os.path.join(lookout_state.project_dir(project_id), "publicaciones.json")


def load(project_id):
    return lookout_state.read_json(ledger_path(project_id)) or {"cola": []}


def save(project_id, led):
    lookout_state.write_json(ledger_path(project_id), led)


def entry_of(led, session_id):
    return next((p for p in led["cola"] if p["session_id"] == session_id and p["estado"] not in ("publicada", "retirada")), None)


def remote_branch(entry):
    base = entry.get("base") or "origin/main"
    return base.split("/", 1)[1] if base.startswith("origin/") else "main"


def remote_tip(wt, branch):
    code, out = git(wt, "ls-remote", "origin", "refs/heads/" + branch)
    return out.split()[0] if code == 0 and out.strip() else ""


def private_hits(wt, base, limit=5):
    code, out = git(wt, "diff", "--unified=0", base + "..HEAD")
    hits = []
    for line in out.splitlines() if code == 0 else []:
        if line.startswith("+") and not line.startswith("+++") and PRIVATE_RE.search(line):
            hits.append(line[:160])
    home = os.path.expanduser("~")
    for line in out.splitlines() if code == 0 else []:
        if line.startswith("+") and not line.startswith("+++") and home in line and line[:160] not in hits:
            hits.append(line[:160])
    return hits[:limit]


# ---------- the queue ----------

def pide(project_id, entry, st, log=None):
    """Ask to publish. Returns (ok, code, lines). Never pushes, never fetches into the agent's tree."""
    led = load(project_id)
    me = entry_of(led, entry["session_id"])
    if not me:
        me = {"session_id": entry["session_id"], "nombre": entry.get("nombre"), "tarea": entry.get("tarea"),
              "rama": entry.get("branch"), "worktree": entry.get("worktree"), "estado": "esperando",
              "pedida": time.time()}
        led["cola"].append(me)
    for p in led["cola"]:
        if p is not me and p["estado"] in VIVAS:
            why = caducada(project_id, p)
            if why:
                p.update(estado="caducada", motivo=why)
    ahead = next((p for p in led["cola"] if p is not me and p["estado"] in VIVAS), None)
    if ahead:
        me["estado"] = "esperando"
        save(project_id, led)
        return False, "ESPERA", ["ESPERA: publica primero %s (%s, versión %s). %s queda en cola; cuando esa publicación "
                                 "se confirme (`lookout publica <proyecto> %s --hecho`), le toca y deberá hacer fetch + "
                                 "rebase + renumerar antes de pedirlo otra vez." % (
                                     ahead["nombre"], ahead["estado"], ahead.get("version") or "-", entry.get("nombre"),
                                     ahead["nombre"])]
    me["estado"] = "turno"
    save(project_id, led)
    ok, code, lines = verifica(project_id, entry, st, led, me)
    if ok:
        me["estado"] = "lista"
    save(project_id, led)
    return ok, code, lines


def verifica(project_id, entry, st, led, me):
    wt = entry.get("worktree") or entry.get("cwd")
    lines = []
    ok, code, text = gobierno.decide_push(st)
    lines.append("Adversario: " + text)
    if not ok:
        return False, code, lines
    rc, dirty = git(wt, "status", "--porcelain", "--untracked-files=no")
    if rc != 0:
        return False, "SIN-REPO", lines + ["NO: no puedo leer el worktree %s." % wt]
    if dirty.strip():
        return False, "SUCIO", lines + ["NO: el worktree tiene cambios sin commit:\n" + dirty.rstrip()]
    branch = remote_branch(entry)
    tip = remote_tip(wt, branch)
    if not tip:
        return False, "SIN-ORIGIN", lines + ["NO: no leo origin/%s (ls-remote)." % branch]
    known = git(wt, "cat-file", "-e", tip + "^{commit}")[0] == 0
    if not known or git(wt, "merge-base", "--is-ancestor", tip, "HEAD")[0] != 0:
        return False, "BASE-MOVIDA", lines + [
            "NO: origin/%s está en %s y la rama del agente no se apoya en ese commit (%s). Dile: `git fetch origin`, "
            "rebase sobre origin/%s, renumera la versión si otra publicación ya usó la suya, corre sus suites y vuelve "
            "a pedir el push." % (branch, tip[:9], "commit desconocido aquí: falta fetch" if not known else "no es fast-forward",
                                  branch)]
    _, head = git(wt, "rev-parse", "HEAD")
    head = head.strip()
    _, commits = git(wt, "log", "--oneline", tip + "..HEAD")
    if not commits.strip():
        return False, "NADA", lines + ["NO: no hay commits nuevos sobre origin/%s." % branch]
    vfile, vhead = version_at(wt, "HEAD")
    _, vbase = version_at(wt, tip)
    _, touched = git(wt, "diff", "--name-only", tip + "..HEAD")
    release = [f for f in touched.splitlines() if is_version_file(f)]
    if vfile and not release:
        vhead = ""  # the push changes no version file: it claims no version (a docs-only change, seen 2026-10-02)
    elif vfile:
        if vhead == vbase:
            return False, "VERSION-SIN-RENUMERAR", lines + [
                "NO: la rama toca %s pero %s sigue diciendo %s, igual que origin/%s (¿una entrada para una versión ya "
                "publicada?). Renumera antes de publicar." % (", ".join(release), vfile, vhead, branch)]
        used = [p for p in led["cola"] if p is not me and p.get("version") == vhead and p["estado"] in ("lista", "publicada")]
        if used:
            return False, "VERSION-USADA", lines + [
                "NO: la versión %s ya la publicó o la tiene lista %s. Fetch + rebase + renumera." % (vhead, used[0]["nombre"])]
    hits = private_hits(wt, tip)
    if hits:
        return False, "RUTAS-PRIVADAS", lines + ["NO: líneas nuevas con rutas privadas:"] + ["  " + h for h in hits]
    me.update(head=head, base=tip, version=vhead, archivo_version=vfile, rama_remota=branch, verificada=time.time())
    lines += ["Base: origin/%s = %s, fast-forward: sí" % (branch, tip[:9]),
              "Commits (%d):" % len(commits.strip().splitlines())] + ["  " + c for c in commits.strip().splitlines()] + [
              ("Versión: %s (%s; origin tenía %s)" % (vhead, vfile, vbase or "-") if vhead else
               "Versión: no la cambia (%s)" % ("origin tiene %s en %s" % (vbase, vfile) if vfile else "sin archivo de versión")),
              "Rutas privadas en el diff: ninguna",
              "LISTA para pasar al usuario. Orden exacta para el agente, sola: git push origin HEAD:%s" % branch]
    return True, "LISTA", lines


def caducada(project_id, p):
    """Why a queued publication no longer holds the turn ('' if it still does): its session was relieved or its
    task closed, its agent committed after the check, or its last verdict is no longer an OK. Without this a
    `lista` that never got pushed blocked the queue for good (seen 2026-10-02)."""
    import registry
    import lote
    e = registry.load(project_id).get("agents", {}).get(p["session_id"])
    if not e or e.get("tarea_estado") in ("relevada", "terminada", "fallida", "relevo-fallido"):
        return "su sesión ya no tiene la tarea (%s)" % ((e or {}).get("tarea_estado") or "sin registro")
    if e.get("retirado"):
        return "su sesión salió del registro (%s)" % e.get("retirado_por", "retirada")
    if p["session_id"] in lote.ended_sessions(project_id):
        return "su sesión terminó (SessionEnd)"
    if p["estado"] == "lista":
        _, head = git(e.get("worktree") or e.get("cwd"), "rev-parse", "HEAD")
        if p.get("head") and head.strip() != p["head"]:
            return "su HEAD cambió después de verificarla"
        if not gobierno.decide_push(gobierno.estado(project_id, e, guardar=False))[0]:
            return "su último veredicto ya no es un hold válido"
    return ""


def concilia(project_id, remote_tip=remote_tip):
    """Fase 9 E3: bring the queue in line with reality, at `inicia` and in every `resumen` (claude-vzert: a publication
    stuck in "turno" since the day before). A live entry whose holder lost its task or session expires (caducada);
    a `lista` whose verified head is already origin's tip was pushed without `--hecho`: publicada. Asks origin
    (ls-remote) only for `lista` entries. Returns the lines that say what changed."""
    led = load(project_id)
    out = []
    for p in led["cola"]:
        if p["estado"] not in ("esperando",) + VIVAS:
            continue
        if p["estado"] == "lista" and p.get("head"):
            tip = remote_tip(p.get("worktree") or "", p.get("rama_remota") or "")
            if tip and tip == p["head"]:
                p.update(estado="publicada", publicada=time.time(), motivo="conciliada: origin ya tiene su commit")
                out.append("Publicación de %s conciliada: origin ya tiene %s (nadie corrió --hecho)." % (
                    p.get("nombre"), tip[:9]))
                continue
        why = caducada(project_id, p)
        if why:
            p.update(estado="caducada", motivo=why)
            out.append("Publicación de %s caducada: %s." % (p.get("nombre"), why))
    if out:
        save(project_id, led)
    return out


def retira_sesion(project_id, session_id, motivo):
    led = load(project_id)
    changed = False
    for p in led["cola"]:
        if p["session_id"] == session_id and p["estado"] in ("esperando", "turno", "lista"):
            p.update(estado="retirada", motivo=motivo)
            changed = True
    if changed:
        save(project_id, led)


def hecho(project_id, entry):
    """Confirm the push landed (origin's tip is the verified head) and hand the turn to the next one."""
    led = load(project_id)
    me = entry_of(led, entry["session_id"])
    if not me or me["estado"] != "lista":
        return False, ["NO: %s no tiene una publicación lista en la cola." % entry.get("nombre")]
    wt = entry.get("worktree") or entry.get("cwd")
    tip = remote_tip(wt, me.get("rama_remota") or remote_branch(entry))
    if tip != me.get("head"):
        return False, ["NO: origin/%s está en %s, no en el commit verificado %s. ¿Se hizo el push? ¿El agente añadió "
                       "commits después de verificar? Si cambió algo, vuelve a pedir la publicación." % (
                           me.get("rama_remota"), tip[:9] or "?", (me.get("head") or "?")[:9])]
    me["estado"] = "publicada"
    me["publicada"] = time.time()
    nxt = next((p for p in led["cola"] if p["estado"] == "esperando"), None)
    save(project_id, led)
    out = ["Publicada: %s versión %s en %s." % (me["nombre"], me.get("version") or "-", tip[:9])]
    if nxt:
        out.append("Siguiente en la cola: %s. Dile por SendMessage: `git fetch origin`, rebase sobre origin/%s, renumera "
                   "la versión (la %s ya está publicada), corre sus suites y vuelve a pedir el push." % (
                       nxt["nombre"], me.get("rama_remota"), me.get("version") or "anterior"))
    else:
        out.append("Cola vacía. Si nadie más va a publicar, dile al usuario que retire la regla temporal de push.")
    return True, out


def retira(project_id, entry):
    led = load(project_id)
    me = entry_of(led, entry["session_id"])
    if not me:
        return False
    me["estado"] = "retirada"
    save(project_id, led)
    return True


def render_cola(project_id):
    led = load(project_id)
    rows = [p for p in led["cola"] if p["estado"] not in ("retirada",)]
    if not rows:
        return "Publicaciones: ninguna."
    return "Publicaciones (en orden):\n" + "\n".join(
        "- %s | %s | versión %s | %s" % (p["nombre"], p["estado"], p.get("version") or "-",
                                          time.strftime("%H:%M", time.localtime(p.get("pedida", 0)))) for p in rows)


# ---------- H15: the temporary rule ----------

def settings_path(root):
    return os.path.join(root, ".claude", "settings.local.json")


def regla_texto(root):
    snippet = {"permissions": {"allow": ALLOW, "deny": DENY}}
    return ("Regla temporal de publicación. La aplica el USUARIO (yo no escribo ese archivo).\n"
            "Archivo: %s (si ya existe, añade estas entradas a sus listas allow y deny).\n"
            "Cubre el checkout principal y todos sus worktrees; las sesiones vivas la leen sin reiniciar (V13).\n"
            "Mientras esté puesta, CUALQUIER sesión de este repo puede hacer `git push origin …` sin preguntar:\n"
            "retírala en cuanto termine la publicación (borra estas entradas).\n\n%s"
            % (settings_path(root), json.dumps(snippet, indent=2, ensure_ascii=False)))


def regla_estado(root):
    """'aplicada' | 'parcial' | 'ausente', and the missing entries. Read-only."""
    data = lookout_state.read_json(settings_path(root)) or {}
    perms = data.get("permissions") or {}
    allow, deny = set(perms.get("allow") or []), set(perms.get("deny") or [])
    falta = [a for a in ALLOW if a not in allow] + [d for d in DENY if d not in deny]
    if not falta:
        return "aplicada", []
    if any(a in allow for a in ALLOW):
        return "parcial", falta
    return "ausente", falta

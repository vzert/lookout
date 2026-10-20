"""Publishing in order (H14) and the temporary push rule (H15), docs/plan.md F3.

H14: several agents ready to publish from the same base all wanted the same version. Here the
publications of a project form ONE queue (publicaciones.json): one agent has the turn; before its push
goes to the user the supervisor checks on its own, read-only, in the agent's worktree:
  the adversary gate (gobierno.decide_push), a clean tree, the base it builds on is origin's CURRENT
  tip and a fast-forward, the commit list, a version that is new against origin and against every
  other publication in the ledger, and no private paths in the added lines.
Anything else is a NO with what to do (fetch + rebase + renumber + suites, then ask again).

PR mode (0.13.27, p-ca286da56c): a project whose agents publish through a branch and a pull request (3-tier-memory:
the user merges). `--modo pr` is kept in publicaciones.json; the check then runs against the agent's own branch (no
fast-forward over main: a line says how far behind it is), the version must be above origin's and follow the merge
order (above every PR before it, below every PR after it; a re-check of an open PR keeps its place), LISTA orders the
push to that branch, `--hecho --pr N` reads the PR with gh and leaves it `pr-abierto`
(it never expires with its session: the PR lives on without its agent), and concilia turns it into `publicada` when
the PR is merged or `caducada` when it is closed. `--fusiona N --decision dK` runs the merge itself, only with the
user's yes to that PR in the supervisor's modal, on the verified head, mergeable, checks green and in merge order.

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
ABIERTO = "pr-abierto"
EN_COLA = ("esperando",) + VIVAS + (ABIERTO,)
MODOS = ("directo", "pr")
GH_TIMEOUT = 60
PR_CADA = 60  # seconds between two gh reads of the same open PR (concilia runs in every resumen)
PR_CAMPOS = ("number,state,headRefName,headRefOid,baseRefName,mergeable,mergeStateStatus,statusCheckRollup,"
             "mergeCommit,url")


def git(wt, *args, timeout=20):
    try:
        out = subprocess.run(["git", "-C", wt] + list(args), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return 124, ""
    return out.returncode, out.stdout


def gh(args, cwd):
    """(rc, text): stdout on success, stderr on failure; 124 when gh is missing or hangs. Tests replace it."""
    try:
        out = subprocess.run(["gh"] + list(args), cwd=cwd or None, capture_output=True, text=True, timeout=GH_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return 124, ""
    return out.returncode, out.stdout if out.returncode == 0 else (out.stderr or out.stdout)


def pr_view(n, cwd):
    """The PR as gh reports it (dict), or None when gh fails or answers something else."""
    rc, out = gh(["pr", "view", str(n), "--json", PR_CAMPOS], cwd)
    if rc != 0:
        return None
    try:
        d = json.loads(out)
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


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


def vkey(v):
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", v or "")
    return tuple(int(x) for x in m.groups()) if m else None


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
    # an open PR is no longer the agent's live publication: the agent may ask again for new work
    return next((p for p in led["cola"] if p["session_id"] == session_id
                 and p["estado"] not in ("publicada", "retirada", ABIERTO)), None)


def modo(project_id):
    m = load(project_id).get("modo")
    return m if m in MODOS else "directo"


def pon_modo(project_id, m):
    if m not in MODOS:
        raise ValueError(m)
    led = load(project_id)
    led["modo"] = m
    save(project_id, led)


def repo_of(wt):
    """The main checkout of the repository `wt` belongs to: gh runs there, it outlives the agent's worktree."""
    rc, com = git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir")
    com = com.strip().rstrip("/")
    if rc != 0 or not com:
        return wt
    return os.path.dirname(com) if os.path.basename(com) == ".git" else com


def orden_de(p):
    """Place in the merge order: when the PR's first publication was verified (a re-check keeps it)."""
    return p.get("orden") or p.get("verificada") or 0


def abiertos(led):
    """The open PRs in merge order."""
    return sorted((p for p in led["cola"] if p["estado"] == ABIERTO), key=orden_de)


def remote_branch(entry):
    base = entry.get("base") or "origin/main"
    return base.split("/", 1)[1] if base.startswith("origin/") else "main"


def remote_tip(wt, branch):
    code, out = git(wt, "ls-remote", "origin", "refs/heads/" + branch)
    return out.split()[0] if code == 0 and out.strip() else ""


def valida_worktree(common_dir, ruta):
    """0.13.6: `--worktree`. An agent launched on the main checkout that works in a worktree of its own (`cd` in its
    Bash; herdr and the registry only see the main checkout) was checked on the main checkout's branch and got
    BASE-MOVIDA (3-tier-memory, 2026-10-16). Returns (top level, branch, "") for a worktree of this same repository,
    or ("", "", why not)."""
    if not ruta or not os.path.isdir(ruta):
        return "", "", "no existe el directorio %s" % ruta
    rc, top = git(ruta, "rev-parse", "--show-toplevel")
    rc2, com = git(ruta, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if rc != 0 or rc2 != 0 or not top.strip():
        return "", "", "%s no es un checkout de git" % ruta
    if os.path.realpath(com.strip()) != os.path.realpath(common_dir or ""):
        return "", "", "%s es de otro repositorio (%s)" % (ruta, com.strip())
    _, rama = git(ruta, "rev-parse", "--abbrev-ref", "HEAD")
    return os.path.realpath(top.strip()), rama.strip(), ""


def pista_worktree(wt):
    """The hint for a NO on the main checkout of a repository that has other worktrees."""
    rc, out = git(wt, "worktree", "list", "--porcelain")
    trees = [l[9:] for l in out.splitlines() if l.startswith("worktree ")] if rc == 0 else []
    if len(trees) < 2 or os.path.realpath(trees[0]) != os.path.realpath(wt or ""):
        return []
    return ["Lo comprobé en el checkout principal (%s). Si el agente trabaja en otro worktree, pregúntale la ruta y "
            "repite con `--worktree <ruta>`." % wt]


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

def pide(project_id, entry, st, log=None, worktree=None):
    """`worktree`: (top level, branch) from valida_worktree; it stays with this publication for --hecho and expiry."""
    """Ask to publish. Returns (ok, code, lines). Never pushes, never fetches into the agent's tree."""
    if entry.get("sin_worktree"):
        # Fase 9 G: an agent on the main checkout does not commit; a push from there would carry every commit on main
        return False, "EN-MAIN", ["NO: %s trabaja en el checkout principal sin commit; el commit y el push son del "
                                  "usuario." % entry.get("nombre", "?")]
    led = load(project_id)
    me = entry_of(led, entry["session_id"])
    if not me:
        me = {"session_id": entry["session_id"], "nombre": entry.get("nombre"), "tarea": entry.get("tarea"),
              "rama": entry.get("branch"), "worktree": entry.get("worktree"), "estado": "esperando",
              "pedida": time.time()}
        led["cola"].append(me)
    if worktree:
        me.update(worktree=worktree[0], rama=worktree[1])
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
    else:
        # B4 (0.12.2): a refused check frees the turn. It stayed "turno" for 6.6 h in 3-tier-memory (2026-10-15) and held
        # the queue; `pide` again re-checks from the start
        me.update(estado="rechazada", motivo=code)
    save(project_id, led)
    return ok, code, lines


def verifica(project_id, entry, st, led, me):
    wt = me.get("worktree") or entry.get("worktree") or entry.get("cwd")
    lines = []
    ok, code, text = gobierno.decide_push(st)
    lines.append("Adversario: " + text)
    if not ok:
        return False, code, lines
    rc, dirty = git(wt, "status", "--porcelain", "--untracked-files=no")
    if rc != 0:
        return False, "SIN-REPO", lines + ["NO: no puedo leer el worktree %s." % wt]
    if dirty.strip():
        propios, ajenos = reparte_sucios(project_id, entry, wt, dirty)
        if propios:
            return False, "SUCIO", lines + ["NO: el worktree tiene cambios sin commit:\n" + "\n".join(propios)]
        lines.append("Aviso: el checkout es compartido; estos cambios sin commit los editó otro agente y %s no "
                     "(no van en el push, que solo lleva commits):\n%s" % (entry.get("nombre"), "\n".join(ajenos)))
    if modo(project_id) == "pr":
        return verifica_pr(entry, led, me, wt, lines)
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
                                  branch)] + pista_worktree(wt)
    _, head = git(wt, "rev-parse", "HEAD")
    head = head.strip()
    _, commits = git(wt, "log", "--oneline", tip + "..HEAD")
    if not commits.strip():
        return False, "NADA", lines + ["NO: no hay commits nuevos sobre origin/%s." % branch] + pista_worktree(wt)
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
    me.update(head=head, base=tip, version=vhead, archivo_version=vfile, rama_remota=branch, verificada=time.time(),
              modo="directo")
    lines += ["Base: origin/%s = %s, fast-forward: sí" % (branch, tip[:9]),
              "Commits (%d):" % len(commits.strip().splitlines())] + ["  " + c for c in commits.strip().splitlines()] + [
              ("Versión: %s (%s; origin tenía %s)" % (vhead, vfile, vbase or "-") if vhead else
               "Versión: no la cambia (%s)" % ("origin tiene %s en %s" % (vbase, vfile) if vfile else "sin archivo de versión")),
              "Rutas privadas en el diff: ninguna",
              "LISTA para pasar al usuario. Orden exacta para el agente, sola: git push origin HEAD:%s" % branch]
    return True, "LISTA", lines


def verifica_pr(entry, led, me, wt, lines):
    """PR mode: the push goes to the agent's own branch and the user merges, so main may have moved on (no
    fast-forward needed); commits, version and private paths are read from where the branch leaves main."""
    base_branch = remote_branch(entry)
    _, rama = git(wt, "rev-parse", "--abbrev-ref", "HEAD")
    rama = rama.strip()
    if not rama or rama == "HEAD" or rama == base_branch:
        return False, "SIN-RAMA", lines + [
            "NO: en modo PR el agente publica desde una rama propia y %s está en %s. Dile que lleve sus commits a una "
            "rama nueva (`git switch -c <rama>`) y vuelva a pedirlo." % (wt, rama or "?")]
    tip = remote_tip(wt, base_branch)
    if not tip:
        return False, "SIN-ORIGIN", lines + ["NO: no leo origin/%s (ls-remote)." % base_branch]
    rc, mb = git(wt, "merge-base", tip, "HEAD") if git(wt, "cat-file", "-e", tip + "^{commit}")[0] == 0 else (1, "")
    mb = mb.strip()
    if rc != 0 or not mb:
        return False, "BASE-DESCONOCIDA", lines + [
            "NO: origin/%s está en %s y este árbol no tiene ese commit. Dile: `git fetch origin` y que vuelva a pedirlo "
            "(en modo PR no hace falta rebase, salvo que GitHub diga que hay conflictos)." % (base_branch, tip[:9])]
    _, head = git(wt, "rev-parse", "HEAD")
    head = head.strip()
    _, commits = git(wt, "log", "--oneline", mb + "..HEAD")
    if not commits.strip():
        return False, "NADA", lines + ["NO: la rama %s no tiene commits propios sobre origin/%s." % (rama, base_branch)]
    rtip = remote_tip(wt, rama)
    if rtip and rtip != head and (git(wt, "cat-file", "-e", rtip + "^{commit}")[0] != 0
                                  or git(wt, "merge-base", "--is-ancestor", rtip, "HEAD")[0] != 0):
        return False, "RAMA-DIVERGE", lines + [
            "NO: origin/%s está en %s y la rama local no lo contiene: el push necesitaría --force, que está prohibido. "
            "Dile: `git fetch origin`, que lleve sus commits encima de origin/%s (o que use una rama nueva) y vuelva a "
            "pedirlo." % (rama, rtip[:9], rama)]
    _, detras = git(wt, "rev-list", "--count", "HEAD.." + tip)
    vfile, vhead = version_at(wt, "HEAD")
    _, vbase = version_at(wt, tip)
    _, touched = git(wt, "diff", "--name-only", mb + "..HEAD")
    release = [f for f in touched.splitlines() if is_version_file(f)]
    if vfile and not release:
        vhead = ""
    elif vfile:
        kh, kb = vkey(vhead), vkey(vbase)
        if (kh and kb and kh <= kb) or (not (kh and kb) and vhead == vbase):
            return False, "VERSION-VIEJA", lines + [
                "NO: la rama declara %s (%s) y origin/%s ya tiene %s. En modo PR la versión va por encima de la de main: "
                "dile `git fetch origin`, renumera por encima de %s, corre sus suites y vuelve a pedirlo." % (
                    vhead, vfile, base_branch, vbase, vbase)]
        # the open PR of this same branch is this publication's own earlier check (new commits after a review): no
        # rival, and this check keeps its place in the merge order. Versions follow that order: above every PR before
        # it, below every PR after it.
        propio = [p for p in led["cola"] if p is not me and p["estado"] == ABIERTO and p.get("rama_remota") == rama]
        mi_orden = min(orden_de(p) for p in propio) if propio else float("inf")
        otros = [p for p in led["cola"] if p is not me and p not in propio and p["estado"] in ("lista", ABIERTO)
                 and p.get("version")]
        for p in otros:
            kp = vkey(p["version"])
            antes = orden_de(p) < mi_orden
            if p["version"] == vhead or (kp and kh and (kp >= kh if antes else kp <= kh)):
                return False, "VERSION-USADA", lines + [
                    "NO: la versión %s choca con la %s de %s (%s%s, %s en el orden de fusión). En modo PR las versiones "
                    "siguen ese orden: renumera %s %s." % (
                        vhead, p["version"], p.get("nombre"), p["estado"], " #%s" % p["pr"] if p.get("pr") else "",
                        "antes" if antes else "después", "por encima de" if antes else "por debajo de", p["version"])]
    hits = private_hits(wt, mb)
    if hits:
        return False, "RUTAS-PRIVADAS", lines + ["NO: líneas nuevas con rutas privadas:"] + ["  " + h for h in hits]
    me.update(head=head, base=tip, merge_base=mb, version=vhead, archivo_version=vfile, rama_remota=rama,
              rama_base=base_branch, repo=repo_of(wt), modo="pr", verificada=time.time())
    lines += ["Base: origin/%s = %s; la rama %s sale de %s y va detrás por %s (en modo PR no hace falta fast-forward; "
              "GitHub dirá si hay conflictos)." % (base_branch, tip[:9], rama, mb[:9], detras.strip() or "?"),
              "Commits (%d):" % len(commits.strip().splitlines())] + ["  " + c for c in commits.strip().splitlines()] + [
              ("Versión: %s (%s; origin/%s tiene %s)" % (vhead, vfile, base_branch, vbase or "-") if vhead else
               "Versión: no la cambia (%s)" % ("origin tiene %s en %s" % (vbase, vfile) if vfile else "sin archivo de versión")),
              "Rutas privadas en el diff: ninguna",
              "LISTA para pasar al usuario. Orden exacta para el agente, sola: git push origin HEAD:refs/heads/%s" % rama]
    return True, "LISTA", lines


def companeros(project_id, entry, wt):
    """Session ids of the other live registered agents that work in the same tree (3-tier-memory, 2026-10-15: agents
    on the main checkout)."""
    import registry
    import lote
    real = os.path.realpath(wt or "")
    out = []
    terminadas = lote.ended_sessions(project_id)
    for sid, e in registry.load(project_id).get("agents", {}).items():
        # adversary round 2: an agent whose task or session ended no longer shares the tree as a live writer
        if (sid == entry.get("session_id") or e.get("retirado") or sid in terminadas
                or e.get("tarea_estado") in ("relevada", "terminada", "fallida", "relevo-fallido")):
            continue
        if os.path.realpath(e.get("worktree") or e.get("cwd") or "") == real:
            out.append(sid)
    return out


EDITORES = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def editados(session_id, wt, ajeno=False):
    """Real paths an agent wrote, from its transcript. For the agent itself: its Edit/Write calls and the paths its Bash
    commands seem to write (heuristicas.escrituras_bash, which over-reports: the safe side for its own files). For
    another agent (`ajeno`): only its exact Edit/Write paths whose call succeeded, because an over-report there would
    hand this agent's own file to the other (adversary rounds 2 and 3). None if the transcript cannot be read."""
    import json
    import deliver
    import heuristicas
    path = deliver.transcript_path(session_id) if session_id else ""
    if not path:
        return None
    out = set()
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return None
    with fh:
        rows = []
        for line in fh:
            if '"tool_use"' not in line and '"tool_result"' not in line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    bien = {b.get("tool_use_id") for d in rows for b in ((d.get("message") or {}).get("content") or [])
            if isinstance(b, dict) and b.get("type") == "tool_result" and not b.get("is_error")}
    for d in rows:
        for b in (d.get("message") or {}).get("content") or []:
            if not isinstance(b, dict) or b.get("type") != "tool_use" or (ajeno and b.get("id") not in bien):
                continue
            ti = b.get("input") or {}
            if b.get("name") in EDITORES and (ti.get("file_path") or ti.get("notebook_path")):
                p = ti.get("file_path") or ti.get("notebook_path")
                out.add(os.path.realpath(p if os.path.isabs(p) else os.path.join(d.get("cwd") or wt, p)))
            elif b.get("name") == "Bash" and not ajeno:
                for p in heuristicas.escrituras_bash(ti.get("command") or "", d.get("cwd") or wt):
                    out.add(os.path.realpath(p))
    return out


def reparte_sucios(project_id, entry, wt, dirty):
    """B4 (0.12.2): (lines the agent must commit first, lines of other sessions). In 3-tier-memory 2 of 2 checks said
    SUCIO over 6 files another agent on the same main checkout had edited. A file counts as another's only when another
    live agent of the same tree wrote it (its transcript) and this one did not: a write lookout cannot see (a generator
    script, `git stash pop`, a subagent; adversary round 1) stays the agent's own, as before. In its own tree, or when a
    transcript cannot be read, every uncommitted file counts."""
    filas = [l for l in dirty.splitlines() if l.strip()]
    otros = companeros(project_id, entry, wt)
    if not otros:
        return filas, []
    mios = editados(entry.get("session_id"), wt)
    suyos = set()
    for sid in otros:
        # only its exact Edit/Write paths: what its Bash text seems to write over-reports (adversary round 2), and an
        # over-report here would hand this agent's own file to another
        e = editados(sid, wt, ajeno=True)
        if e is None:
            return filas, []
        suyos |= e
    if mios is None:
        return filas, []
    top = git(wt, "rev-parse", "--show-toplevel")[1].strip() or wt
    propios, ajenos = [], []
    for l in filas:
        real = os.path.realpath(os.path.join(top, l[3:].split(" -> ")[-1].strip().strip('"')))
        (ajenos if real in suyos and real not in mios else propios).append(l)
    return propios, ajenos


def caducada(project_id, p):
    """Why a queued publication no longer holds the turn ('' if it still does): its session was relieved or its
    task closed, its agent committed after the check, or its last verdict is no longer an OK. Without this a
    `lista` that never got pushed blocked the queue for good (seen 2026-10-02)."""
    import registry
    import lote
    if p["estado"] == ABIERTO:
        return ""  # the PR lives on without its agent: only its merge or its closing ends it (concilia)
    e = registry.load(project_id).get("agents", {}).get(p["session_id"])
    if not e or e.get("tarea_estado") in ("relevada", "terminada", "fallida", "relevo-fallido"):
        return "su sesión ya no tiene la tarea (%s)" % ((e or {}).get("tarea_estado") or "sin registro")
    if e.get("retirado"):
        return "su sesión salió del registro (%s)" % e.get("retirado_por", "retirada")
    if p["session_id"] in lote.ended_sessions(project_id):
        return "su sesión terminó (SessionEnd)"
    if p["estado"] == "lista":
        _, head = git(p.get("worktree") or e.get("worktree") or e.get("cwd"), "rev-parse", "HEAD")
        if p.get("head") and head.strip() != p["head"]:
            return "su HEAD cambió después de verificarla"
        if not gobierno.decide_push(gobierno.estado(project_id, e, guardar=False))[0]:
            return "su último veredicto ya no es un hold válido"
    return ""


def concilia(project_id, remote_tip=remote_tip, ahora=None):
    """Fase 9 E3: bring the queue in line with reality, at `inicia` and in every `resumen` (claude-vzert: a publication
    stuck in "turno" since the day before). A live entry whose holder lost its task or session expires (caducada);
    a `lista` whose verified head is already origin's tip was pushed without `--hecho`: publicada. Asks origin
    (ls-remote) only for `lista` entries. Returns the lines that say what changed."""
    led = load(project_id)
    out = []
    ahora = ahora or time.time()
    leido = False
    for p in led["cola"]:
        if p["estado"] == ABIERTO:
            if ahora - (p.get("pr_visto") or 0) >= PR_CADA:
                out += concilia_pr(led, p, ahora)
                leido = True
            continue
        if p["estado"] not in ("esperando",) + VIVAS:
            continue
        # PR mode: the branch on origin is not main; only the merge publishes (concilia_pr)
        if p["estado"] == "lista" and p.get("head") and p.get("modo") != "pr":
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
    if out or leido:
        save(project_id, led)
    return out


def concilia_pr(led, p, ahora):
    """An open PR as gh sees it: MERGED → publicada (with a warning if an earlier one is still open), CLOSED → caducada.
    A gh that fails leaves the PR open (only pr_visto moves, so it is read again a minute later): a network error
    never expires a PR."""
    p["pr_visto"] = ahora
    d = pr_view(p["pr"], p.get("repo") or p.get("worktree"))
    if not d:
        return []
    if d.get("state") == "MERGED":
        antes = [q for q in abiertos(led) if q is not p and orden_de(q) < orden_de(p)]
        p.update(estado="publicada", publicada=ahora, motivo="PR #%s fusionado" % p["pr"],
                 merge_commit=(d.get("mergeCommit") or {}).get("oid", ""))
        line = "Publicación de %s: PR #%s fusionado (versión %s)." % (p.get("nombre"), p["pr"], p.get("version") or "-")
        if antes:
            line += " Se fusionó fuera de orden: antes iba %s." % ", ".join(
                "%s (#%s)" % (q.get("nombre"), q.get("pr")) for q in antes)
        return [line]
    if d.get("state") == "CLOSED":
        p.update(estado="caducada", motivo="PR #%s cerrado sin fusionar" % p["pr"])
        return ["Publicación de %s caducada: el PR #%s se cerró sin fusionar." % (p.get("nombre"), p["pr"])]
    return []


def retira_sesion(project_id, session_id, motivo):
    led = load(project_id)
    changed = False
    for p in led["cola"]:
        if p["session_id"] == session_id and p["estado"] in ("esperando", "turno", "lista"):
            p.update(estado="retirada", motivo=motivo)
            changed = True
    if changed:
        save(project_id, led)


def hecho(project_id, entry, pr=None):
    """Confirm the push landed (origin's tip is the verified head) and hand the turn to the next one. PR mode: `pr` is
    the number of the PR the agent opened; it must be open on that branch and head (gh)."""
    led = load(project_id)
    me = entry_of(led, entry["session_id"])
    if not me or me["estado"] != "lista":
        return False, ["NO: %s no tiene una publicación lista en la cola." % entry.get("nombre")]
    if pr and modo(project_id) != "pr":
        return False, ["NO: --pr es del modo PR y este proyecto está en modo directo (`lookout publica <proyecto> "
                       "--modo pr` para cambiarlo, y vuelve a pedir la publicación)."]
    if (me.get("modo") or "directo") != modo(project_id):
        return False, ["NO: la publicación de %s se verificó en modo %s y el proyecto está ahora en modo %s: vuelve a "
                       "pedirla (`lookout publica <proyecto> %s`)." % (entry.get("nombre"), me.get("modo") or "directo",
                                                                      modo(project_id), entry.get("nombre"))]
    if me.get("modo") == "pr":
        return hecho_pr(project_id, led, me, entry, pr)
    wt = me.get("worktree") or entry.get("worktree") or entry.get("cwd")
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
        import sesiones  # 0.13.35 (p-561f1a2173): the name SendMessage takes, not lookout's (0.13.24)
        out.append("Siguiente en la cola: %s (%s). Dile por SendMessage: `git fetch origin`, rebase sobre origin/%s, "
                   "renumera la versión (la %s ya está publicada), corre sus suites y vuelve a pedir el push." % (
                       nxt["nombre"], sesiones.to_texto(nxt), me.get("rama_remota"), me.get("version") or "anterior"))
    else:
        out.append("Cola vacía. Si nadie más va a publicar, dile al usuario que retire la regla temporal de push.")
    return True, out


def hecho_pr(project_id, led, me, entry, pr):
    if not pr:
        return False, ["NO: en modo PR, --hecho necesita el número del PR que abrió el agente (`gh pr create`): "
                       "`lookout publica <proyecto> %s --hecho --pr N`." % entry.get("nombre")]
    wt = me.get("worktree") or entry.get("worktree") or entry.get("cwd")
    rama = me.get("rama_remota")
    tip = remote_tip(wt, rama)
    if tip != me.get("head"):
        return False, ["NO: origin/%s está en %s, no en el commit verificado %s. ¿Se hizo el push a la rama? ¿El agente "
                       "añadió commits después de verificar? Si cambió algo, vuelve a pedir la publicación." % (
                           rama, tip[:9] or "(no existe)", (me.get("head") or "?")[:9])]
    d = pr_view(pr, me.get("repo") or wt)
    if d is None:
        return False, ["NO: no leo el PR #%d con gh (`gh pr view %d` falló: ¿gh instalado y con sesión? ¿existe ese "
                       "PR?)." % (pr, pr)]
    if (d.get("headRefName"), d.get("headRefOid"), d.get("baseRefName")) != (rama, me["head"], me.get("rama_base")):
        return False, ["NO: el PR #%d es de %s en %s hacia %s; la publicación verificada es %s en %s hacia %s." % (
            pr, d.get("headRefName"), (d.get("headRefOid") or "?")[:9], d.get("baseRefName"), rama, me["head"][:9],
            me.get("rama_base"))]
    ahora = time.time()
    if d.get("state") == "MERGED":
        me.update(estado="publicada", publicada=ahora, pr=pr, motivo="PR #%d ya fusionado" % pr)
        save(project_id, led)
        return True, ["Publicada: %s versión %s, PR #%d ya fusionado." % (me["nombre"], me.get("version") or "-", pr)]
    if d.get("state") != "OPEN":
        return False, ["NO: el PR #%d está %s, sin fusionar. Si se abre otro, repite con su número." % (pr, d.get("state"))]
    # the same PR checked again after new commits: the new check replaces the old one and keeps its place in the order
    viejas = [p for p in led["cola"] if p is not me and p["estado"] == ABIERTO
              and (p.get("pr") == pr or p.get("rama_remota") == rama)]
    for p in viejas:
        p.update(estado="retirada", motivo="reemplazada: el PR #%s se verificó otra vez en %s" % (pr, me["head"][:9]))
    me.update(estado=ABIERTO, pr=pr, pr_abierto=ahora, pr_visto=ahora, url=d.get("url", ""),
              orden=min([orden_de(p) for p in viejas] + [orden_de(me)]))
    orden = abiertos(led).index(me) + 1
    nxt = next((p for p in led["cola"] if p["estado"] == "esperando"), None)
    save(project_id, led)
    out = ["PR #%d abierto: %s versión %s, %dº en el orden de fusión. Lo fusiona el usuario, o tú con su sí en tu modal: "
           "`lookout publica <proyecto> --fusiona %d --decision <id>`." % (pr, me["nombre"], me.get("version") or "-",
                                                                       orden, pr)]
    if nxt:
        import sesiones
        out.append("Siguiente en la cola: %s (%s). Dile por SendMessage que vuelva a pedir la publicación; su versión "
                   "debe ser mayor que la %s." % (nxt["nombre"], sesiones.to_texto(nxt), me.get("version") or "anterior"))
    return True, out


CHECK_OK = ("SUCCESS", "NEUTRAL", "SKIPPED")
FUSIONABLE = ("CLEAN",)


def checks_pendientes(rollup):
    """Names of the checks that are not finished green (CheckRun: conclusion; StatusContext: state)."""
    malos = []
    for c in rollup or []:
        if not isinstance(c, dict):
            malos.append("?")
        elif "state" in c and "conclusion" not in c:
            if c.get("state") != "SUCCESS":
                malos.append("%s=%s" % (c.get("context") or "?", c.get("state")))
        elif c.get("status") != "COMPLETED" or c.get("conclusion") not in CHECK_OK:
            malos.append("%s=%s" % (c.get("name") or "?", c.get("conclusion") or c.get("status") or "en curso"))
    return malos


def fusiona(project_id, pr, decision_id, fuera_de_orden=False):
    """Merge an open PR of the queue on the user's yes (a decision answered in the supervisor's modal that names #pr,
    used once). Only the verified head (--match-head-commit), mergeable, checks green, first in merge order unless
    `fuera_de_orden`. A merge commit only: squash/rebase would leave the agent's commits outside main
    (cierre.published). Returns (ok, code, lines)."""
    import decisiones
    led = load(project_id)
    p = next((q for q in led["cola"] if q["estado"] == ABIERTO and q.get("pr") == pr), None)
    if not p:
        return False, "NO-EN-COLA", ["NO: el PR #%d no es un PR abierto de la cola de publicación (`lookout publica "
                                     "<proyecto> --cola`)." % pr]
    d = decisiones.respondida(project_id, decision_id or "")
    # codex r1: only the user's own choice in the modal (closed by the hook: por_hook), never a `--cierra … --si` the
    # supervisor typed, and only a plain decision (a tab-closing or permission one authorizes something else)
    if not d or d.get("usada") or not d.get("por_hook") or not d.get("si_es") or d.get("tipo"):
        return False, "SIN-SI", [
            "NO: fusionar lo autoriza el usuario en tu ventana. Abre la decisión (`lookout decision <proyecto> --abre "
            "\"¿Fusiono el PR #%d …?\" --agentes %s --si-es \"<etiqueta del sí>\"`), pregúntale en tu modal y, si elige "
            "esa opción, repite con --decision <id>. Una decisión ya usada no vale otra vez." % (pr, p.get("nombre"))]
    if not re.search(r"#%d\b" % pr, d.get("texto") or ""):
        return False, "SI-DE-OTRO-PR", ["NO: la decisión %s («%s») no nombra el PR #%d." % (d["id"], d.get("texto"), pr)]
    primero = abiertos(led)[0]
    if primero is not p and not fuera_de_orden:
        return False, "FUERA-DE-ORDEN", [
            "NO: antes va %s (#%s, versión %s). Fusiona ese primero o, si el usuario quiere este antes, repite con "
            "--fuera-de-orden." % (primero.get("nombre"), primero.get("pr"), primero.get("version") or "-")]
    cwd = p.get("repo") or p.get("worktree")
    v = pr_view(pr, cwd)
    if v is None:
        return False, "SIN-GH", ["NO: no leo el PR #%d con gh (`gh pr view` falló: ¿gh instalado y con sesión?)." % pr]
    if (v.get("headRefName"), v.get("headRefOid"), v.get("baseRefName")) != (
            p.get("rama_remota"), p.get("head"), p.get("rama_base")):
        return False, "PR-CAMBIO", [
            "NO: el PR #%d es ahora %s en %s hacia %s y lo verificado fue %s en %s hacia %s. Si tiene commits nuevos, que "
            "el agente vuelva a pedir la publicación y repite `--hecho --pr %d`; si cambió de rama destino, pregúntale "
            "al usuario." % (pr, v.get("headRefName"), (v.get("headRefOid") or "?")[:9], v.get("baseRefName"),
                             p.get("rama_remota"), (p.get("head") or "?")[:9], p.get("rama_base"), pr)]
    malos = checks_pendientes(v.get("statusCheckRollup"))
    if (v.get("state") != "OPEN" or v.get("mergeable") != "MERGEABLE" or v.get("mergeStateStatus") not in FUSIONABLE
            or malos):
        return False, "PR-NO-FUSIONABLE", [
            "NO: el PR #%d no se puede fusionar ahora: estado %s, mergeable %s, %s%s." % (
                pr, v.get("state"), v.get("mergeable"), v.get("mergeStateStatus"),
                "; checks sin terminar en verde: " + ", ".join(malos) if malos else "")]
    decisiones.marca_usada(project_id, d["id"])  # before the merge: a failed merge needs a new yes (the safe side)
    rc, out = gh(["pr", "merge", str(pr), "--merge", "--match-head-commit", p["head"]], cwd)
    if rc != 0:
        return False, "FUSION-FALLIDA", ["NO: la fusión del PR #%d falló en gh: %s. La decisión %s ya está usada: si el "
                                         "usuario quiere reintentar, pídele otro sí." % (
                                             pr, (out or "").strip()[:300] or "rc %d" % rc, d["id"])]
    ahora = time.time()
    p.update(estado="publicada", publicada=ahora, motivo="fusionado con el sí del usuario (%s)" % d["id"],
             decision=d["id"], pr_visto=ahora)
    save(project_id, led)
    lines = ["Checks: %s." % ("sin checks en este PR (el repo no tiene CI para él)" if not v.get("statusCheckRollup")
                              else "%d en verde" % len(v["statusCheckRollup"])),
             "Fusionado: PR #%d (%s, versión %s) en %s con un merge commit sobre %s." % (
                 pr, p.get("nombre"), p.get("version") or "-", p.get("rama_base") or "main", p["head"][:9])]
    resto = abiertos(led)
    if resto:
        lines.append("Siguiente en el orden de fusión: %s (#%s). GitHub dirá si necesita rebase." % (
            resto[0].get("nombre"), resto[0].get("pr")))
    return True, "FUSIONADA", lines


def retira(project_id, entry):
    led = load(project_id)
    me = entry_of(led, entry["session_id"])
    if not me:
        return False
    me["estado"] = "retirada"
    save(project_id, led)
    return True


def pr_texto(led, p):
    """«#7, 1º en fusionar» for an open PR, '' otherwise."""
    orden = abiertos(led)
    return "#%s, %dº en fusionar" % (p.get("pr"), orden.index(p) + 1) if p in orden else ""


def render_cola(project_id):
    led = load(project_id)
    rows = [p for p in led["cola"] if p["estado"] not in ("retirada",)]
    if not rows:
        return "Publicaciones: ninguna."
    cabeza = ("Publicaciones (modo PR; cada PR abierto dice su lugar en el orden de fusión, el de su primera "
              "verificación):" if modo(project_id) == "pr" else "Publicaciones (en orden):")
    return cabeza + "\n" + "\n".join(
        "- %s | %s | versión %s | %s%s" % (p["nombre"], p["estado"], p.get("version") or "-",
                                            time.strftime("%H:%M", time.localtime(p.get("pedida", 0))),
                                            " | PR " + pr_texto(led, p) if p["estado"] == ABIERTO else "")
        for p in rows)


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

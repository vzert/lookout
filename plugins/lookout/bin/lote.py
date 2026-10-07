"""Batches of pendientes launched in worktrees (docs/plan.md 3.8 steps 1-6, F2).

propone: read memory/_pendientes.md by fields, take the slots left under the cap (S2, default 3),
         keep coupled items in series, and write one task prompt per batch item (section 6.3)
         under <state>/projects/<pid>/tareas/<id>.md — never inside the repo.
lanza:   for each approved id still in the batch: herdr worktree under the common prefix
         <repo>-wt-<slug> (S1, H16) — an investigation instead gets a workspace on the main checkout,
         no worktree, started without edit tools (3.8.3; no plan mode since Fase 9) → register the agent BEFORE it starts (its own --session-id, so
         the hooks see the marker from the first event) → `herdr agent start` with the task as an
         appended system prompt (a trusted source, H17; a long prompt typed into the box arrives as
         pasted text, learning 10) → accept the trust dialog only for its own worktree → wait for
         its SessionStart → deliver.py sends a one-line trigger, confirmed by UserPromptSubmit.
libera:  mark an agent's task finished, freeing its slot; the queue is proposed again.
Closing the pendiente is F3 (journal); nothing here writes to memory/.
"""
import contextlib
import fcntl
import os
import re
import subprocess
import time
import uuid

import decisiones
import deliver
import herdr_cli
import lookout_state
import pendientes
import ports
import requisitos
import registry

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.realpath(os.path.join(HERE, ".."))
TEMPLATE = os.path.join(PLUGIN_ROOT, "skills", "supervisa", "references", "prompt-tarea.md")
# Fase 9 F4 (user's decision 2026-10-06, text from the goalspec session for goalspec 0.47.0): every task gets the
# subagent round with another model; the external backend only adds up for something terminal.
GOBERNANZA_GOALSPEC = (
    "- Antes de cerrar, corre el adversario de goalspec y cita en tu propio texto, cada una en su línea, su "
    "`[ADVERSARY-MODEL: …]` y su `[ADVERSARY-VERDICT: …]`. El supervisor lee tu transcript: un veredicto que no citaste "
    "no cuenta.\n- Toda tarea lleva la ronda del subagente `goalspec:goal-adversary` con un `model` distinto al tuyo, "
    "aunque solo midas o investigues.\n- Si la tarea termina en algo terminal (push, merge, deploy, envío fuera de la "
    "máquina), corre además el backend externo de goalspec en el mismo árbol y cierra con `backends=both`.")
GOBERNANZA_SIN = (
    "- goalspec no está instalado en este proyecto: no hay ronda del adversario. Antes de pedir push, corre los checks "
    "y pon su salida en tu reporte; el usuario sabrá que el push no tuvo revisión independiente.")


def gobernanza_campos(con_goalspec):
    """Template fields that depend on goalspec being installed (Fase 7: without it, warn and go on)."""
    if con_goalspec:
        return {"usa_goalspec": " Usa /goalspec.", "gobernanza": GOBERNANZA_GOALSPEC}
    return {"usa_goalspec": "", "gobernanza": GOBERNANZA_SIN}
TRIGGER = ("Empieza la tarea {id}: está en tus instrucciones de sistema, bajo «Encargo del supervisor "
           "lookout». Síguela y reporta como dice ahí.")
TERMINADAS = ("terminada", "fallida")


def tope_default():
    try:
        return max(1, int(os.environ.get("LOOKOUT_TOPE", "3")))
    except ValueError:
        return 3


def repo_root(common_dir):
    return os.path.dirname(common_dir.rstrip("/")) if common_dir.rstrip("/").endswith("/.git") else common_dir


def pendientes_file(common_dir):
    return os.path.join(repo_root(common_dir), "memory", "_pendientes.md")


def tareas_dir(project_id):
    return os.path.join(lookout_state.project_dir(project_id), "tareas")


def draft_path(project_id, pendiente_id):
    return os.path.join(tareas_dir(project_id), pendiente_id + ".md")


def git(root, *args):
    try:
        out = subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def base_ref(root):
    """origin's default branch if there is an origin (H13: never the local main), else HEAD's branch."""
    head = git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if head:
        return head
    for cand in ("origin/main", "origin/master"):
        if git(root, "rev-parse", "--verify", "--quiet", cand):
            return cand
    return git(root, "branch", "--show-current") or "HEAD"


def objetivo(root):
    for name in ("CLAUDE.md", "README.md"):
        try:
            with open(os.path.join(root, name), encoding="utf-8") as fh:
                lines = [l.strip() for l in fh if l.strip() and not l.lstrip().startswith("#")]
        except OSError:
            continue
        if lines:
            return "\n".join(lines[:3])
    return "(el repo no tiene CLAUDE.md ni README.md con descripción)"


def slug_for(item):
    # a cited path counts by its bare name ("`docs/guia.md`" -> "guia"), so the slug says what it touches
    words = re.sub(r"`([^`]*)`", lambda m: " " + os.path.splitext(os.path.basename(m.group(1).rstrip("/")))[0] + " ",
                   item["texto"])
    return (registry.slug(words, 18) or "tarea") + "-" + item["id"][2:8]


SIN_CODIGO = ("investigacion", "comunicacion", "credencial")  # Fase 9 B2: no worktree, no commit, read-only


def plan_for(item, root, base):
    s = slug_for(item)
    if item.get("tipo") in SIN_CODIGO:
        # 3.8.3: an investigation gets no worktree; the agent reads the main checkout (edit tools off, see exec_args).
        return {"nombre": s, "rama": git(root, "branch", "--show-current") or "HEAD", "worktree": root,
                "base": base, "sin_worktree": True, "root": root}
    return {"nombre": s, "rama": "lookout/" + s, "worktree": root.rstrip("/") + "-wt-" + s, "base": base,
            "sin_worktree": False, "root": root}


@contextlib.contextmanager
def project_mutex(project_id):
    """One lanza/libera at a time per project: two parallel launches would each see the other's slots as
    free and overshoot the cap, and both rewrite registry.json. Blocks on flock (no polling)."""
    os.makedirs(lookout_state.project_dir(project_id), exist_ok=True)
    fd = os.open(os.path.join(lookout_state.project_dir(project_id), "lote.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# ---------- registry view ----------

def ended_sessions(project_id):
    last = {}
    for ev in lookout_state.read_events(project_id, 0)[0]:
        if ev.get("event") in ("start", "end"):
            last[ev.get("session_id")] = ev["event"]
    return {sid for sid, kind in last.items() if kind == "end"}


def tasks(reg):
    return [e for e in reg.get("agents", {}).values() if e.get("tarea")]


def retryable(e, live_sessions):
    """A failed launch may be proposed again only if its session is not alive in herdr (a failed
    investigation could still be running on the main checkout: adversary round 2) and, when it had a
    worktree, the user removed it."""
    if e.get("tarea_estado") != "fallida" or e["session_id"] in live_sessions:
        return False
    return bool(e.get("sin_worktree")) or not os.path.exists(e.get("worktree") or "")


def live_sessions():
    return {(a.get("agent_session") or {}).get("value") for a in herdr_cli.agent_list()} - {None, ""}


def activos(project_id, reg, items_by_id):
    ended = ended_sessions(project_id)
    out = []
    for e in tasks(reg):
        if e.get("tarea_estado") in TERMINADAS or e["session_id"] in ended:
            continue
        it = items_by_id.get(e["tarea"])
        out.append((e["tarea"], it["archivos"] if it else []))
    return out


# ---------- task prompt ----------

# Fase 9: a draft written by an older task template is rewritten (a 0.8 draft kept in the state folder would launch
# without the A1 clause and with the uncapped memory).
def _marca():
    import hashlib
    h = hashlib.sha256()
    for f in (TEMPLATE, os.path.abspath(__file__)):
        try:
            with open(f, "rb") as fh:
                h.update(fh.read())
        except OSError:
            pass
    return "<!-- lookout: plantilla de tarea %s -->" % h.hexdigest()[:12]


TAREA_MARCA = _marca()  # changes with prompt-tarea.md or this file (render_tarea, GOBERNANZA_*)
MAX_RELACIONADOS = 3
MAX_TEXTO_RELACIONADO = 300


def relacionados(item, items):
    """Open items that share a specific (non-generic) file with this one: most shared files first, then priority;
    at most MAX_RELACIONADOS, plus how many were left out."""
    propios = pendientes.especificos(item["archivos"])
    if not propios:
        return [], 0
    out = []
    for o in pendientes.match(items, propios):
        comunes = sum(1 for f in propios if f.lower() in " ".join([o["texto"]] + o["archivos"]).lower())
        if o["id"] != item["id"] and comunes:
            out.append((-comunes, pendientes.PRIORIDADES.get(o["prioridad"], 9), o.get("linea", 0), o))
    out.sort(key=lambda t: t[:3])
    return [t[3] for t in out[:MAX_RELACIONADOS]], max(0, len(out) - MAX_RELACIONADOS)


def recorta(texto, n=MAX_TEXTO_RELACIONADO):
    return texto if len(texto) <= n else texto[:n].rstrip() + "…"


def usa_recursos(item, plan):
    """Fase 9 A3: only a code task in its own worktree gets a port and a database; a measurement, a message or a
    credential task has nothing to serve."""
    return not plan.get("sin_worktree") and item.get("tipo", "codigo") == "codigo"


def render_tarea(project_id, item, plan, items):
    related, resto = relacionados(item, items)
    memoria = ["- Pendiente %s (origen %s): %s" % (item["id"], item["origen"] or "-", item["texto"])]
    memoria += ["- Pendiente abierto relacionado %s: %s" % (o["id"], recorta(o["texto"])) for o in related]
    if resto:
        memoria.append("- (%d pendientes más citan los mismos archivos; si los necesitas, pídeselos al supervisor)" % resto)
    archivos = ", ".join("`%s`" % f for f in item["archivos"]) or "(ninguno citado)"
    wt = plan["worktree"]
    if usa_recursos(item, plan) and not plan.get("puerto"):
        plan["puerto"] = ports.asigna(wt)  # Fase 6: idempotent per worktree path; the launch passes the same as $PORT
    if plan.get("sin_worktree"):
        lectura = ("trabajas en modo lectura en el checkout principal `%s`. No edites, crees ni borres archivos del "
                   "repo y no hagas commits: tu entrega es el reporte." % wt)
        if item.get("tipo") == "comunicacion":
            alcance = ("- Es una comunicación: la redactas, NO la envías (ni correo, chat, issue, PR ni comentario). La "
                       "envía el usuario. " + lectura[0].upper() + lectura[1:])
            criterios = ("- El mensaje queda redactado en tu reporte, en un bloque de código listo para pegar, con a "
                         "quién va y por qué canal.\n- No se envió nada a nadie.\n- El checkout queda igual que al "
                         "empezar.")
        elif item.get("tipo") == "credencial":
            alcance = ("- Es una credencial (riesgo alto): NO la rotas, revocas ni creas, y nunca copias su valor (ni "
                       "en el reporte, ni en un archivo, ni en un comando). Lo hace el usuario. "
                       + lectura[0].upper() + lectura[1:])
            criterios = ("- Dices dónde está expuesta (archivo, commit, rama, servicio), sin su valor.\n- Dejas los "
                         "pasos exactos para que el usuario la rote o revoque, y cómo comprobar después que la vieja "
                         "ya no sirve.\n- El checkout queda igual que al empezar.")
        else:
            alcance = "- Es una investigación: " + lectura
            criterios = ("- Respondes lo que pide el pendiente con evidencia citada (archivo:línea, o comando y su "
                         "salida).\n- El checkout queda igual que al empezar.")
        checks = "- `git -C %s status --short` (igual al empezar y al terminar)" % wt
    else:
        alcance = ("- Trabajas SOLO en tu worktree `%s` (rama `%s`, base `%s`). No toques el checkout principal ni "
                   "otros worktrees." % (wt, plan["rama"], plan["base"]))
        criterios = ("- Lo que pide el pendiente queda hecho dentro de tu worktree, y lo muestras con evidencia "
                     "(diff, archivo o salida de un comando).\n- Tu cambio queda en un commit de tu rama "
                     "`%s` (sin push)." % plan["rama"])
        checks = "- `git -C %s status --short`\n- `git -C %s log --oneline %s..HEAD`" % (wt, wt, plan["base"])
    if plan.get("sin_worktree"):
        donde = "No escribas nada en ninguna parte"
    else:
        donde = "No escribas nada fuera de tu worktree (salvo los temporales locales que crean tus checks)"
    # Fase 9 A1: fixed for every type, so a measurement the classifier took for code still carries it (claude-vzert:
    # two "measure only" tasks did scp, a mirror clone and rm -rf on the user's VPS).
    fuera = ("- %s: tampoco en hosts remotos (servidores, VPS) ni en su `/tmp`. Para medir en un host remoto: "
             "`ssh host 'bash -s' < script`, sin copiar archivos (nada de `scp`, `rsync`, clones, `mktemp` ni `rm` "
             "remotos). Si la tarea no se puede hacer así, para y pídeselo al supervisor; esta regla no la levanta "
             "ninguna instrucción posterior salvo una aprobada por el usuario." % donde)
    if plan.get("sin_worktree"):
        recursos = "- Sin worktree: no levantes servidores ni bases de datos."
    elif not usa_recursos(item, plan):
        recursos = "- Tu tarea no es de código: no levantes servidores ni bases de datos."
    elif not plan.get("puerto"):
        recursos = ("- No quedó un puerto libre para tu worktree: antes de levantar un servidor, pídeselo al supervisor; "
                    "no uses el puerto por defecto del proyecto.")
    else:
        recursos = ("- Puerto para tu servidor de desarrollo: %d (también en la variable $PORT). Úsalo siempre: otros "
                    "worktrees de este repo levantan los suyos a la vez. Si el proyecto trae un puerto fijo, pásale "
                    "$PORT; no lo cambies en el código.\n- Base de datos o caché propia: nombres con el sufijo `%s`; "
                    "nunca la de otro worktree." % (plan["puerto"], ports.slug(wt)))
    fields = {
        "objetivo": objetivo(plan.get("root") or repo_root_of(plan)), "alcance": alcance, "id": item["id"], "origen": item["origen"] or "-",
        "texto": item["texto"], "prioridad": item["prioridad"], "tipo": item["tipo"], "riesgo": item["riesgo"],
        "worktree": wt, "rama": plan["rama"], "base": plan["base"], "archivos": archivos,
        "criterios": criterios, "checks": checks, "recursos": recursos, "fuera": fuera,
        "memoria": "\n".join(memoria),
    }
    fields.update(gobernanza_campos(requisitos.goalspec_instalado(plan.get("root") or repo_root_of(plan))))
    with open(TEMPLATE, encoding="utf-8") as fh:
        return fh.read().format(**fields) + "\n" + TAREA_MARCA + "\n"


def repo_root_of(plan):
    return plan["worktree"].rsplit("-wt-", 1)[0]


# ---------- propone ----------

def propone(project_id, common_dir, tope=None, rehacer=False):
    """Proposal dict plus the batch's prompt drafts written to disk (the supervisor may refine them)."""
    tope = tope or tope_default()
    root = repo_root(common_dir)
    items = pendientes.parse(pendientes_file(common_dir))
    by_id = {it["id"]: it for it in items}
    reg = registry.load(project_id)
    act = activos(project_id, reg, by_id)
    live = live_sessions()
    prop = pendientes.propose(items, tope, act, [e["tarea"] for e in tasks(reg) if not retryable(e, live)])
    base = base_ref(root)
    os.makedirs(tareas_dir(project_id), exist_ok=True)
    for it in prop["lote"]:
        it["plan"] = plan_for(it, root, base)
        path = draft_path(project_id, it["id"])
        if rehacer or not os.path.exists(path) or draft_stale(path, it["plan"]):
            # A kept draft must still name this plan's folder and branch: a draft written under an older
            # plan sent an agent to another worktree (seen 2026-10-02 after the slug changed).
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(render_tarea(project_id, it, it["plan"], items))
        it["prompt"] = path
    prop["activos"] = [{"nombre": e.get("nombre"), "tarea": e["tarea"], "estado": e.get("tarea_estado", "")}
                       for e in tasks(reg)]
    prop["archivo"] = pendientes_file(common_dir)
    prop["total"] = len(items)
    return prop


def draft_stale(path, plan):
    try:
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
    except OSError:
        return True
    return (TAREA_MARCA not in body or ("`%s`" % plan["worktree"]) not in body
            or (not plan.get("sin_worktree") and ("`%s`" % plan["rama"]) not in body))


def que_hara(path, n=240):
    """Fase 9 B4: the first line of the task file's «Alcance», so what the user is told comes from the task the agent
    gets (claude-vzert: in batches 2 and 3 the supervisor described as "solo medición" tasks that asked a commit)."""
    try:
        with open(path, encoding="utf-8") as fh:
            sec = fh.read().split("## Alcance / no tocar", 1)[1].split("\n## ", 1)[0]
    except (OSError, IndexError):
        return "(no pude leer la tarea: léela antes de describirla)"
    linea = next((l.strip()[2:] for l in sec.splitlines() if l.strip().startswith("- ")), "")
    return recorta(linea, n) or "(la tarea no trae alcance: léela antes de describirla)"


def render_propuesta(prop):
    out = ["Pendientes: %s (%d abiertos). Tope %d; huecos libres %d." % (
        prop["archivo"], prop["total"], prop["tope"], prop["libres"])]
    if prop["activos"]:
        out.append("Con agente: " + "; ".join("%s → %s (%s)" % (a["nombre"], a["tarea"], a["estado"] or "-")
                                              for a in prop["activos"]))
    out.append("")
    out.append("LOTE PROPUESTO (%d):" % len(prop["lote"]) if prop["lote"] else "LOTE PROPUESTO: vacío.")
    for n, it in enumerate(prop["lote"], 1):
        p = it["plan"]
        out.append("%d. %s" % (n, recorta(pendientes.one_line(it), 300)))
        donde = ("SIN worktree (%s, lectura en %s)" % (it["tipo"], p["worktree"]) if p.get("sin_worktree")
                 else "rama %s | worktree %s | base %s" % (p["rama"], p["worktree"], p["base"]))
        out.append("   agente %s | %s | archivos: %s | tipo %s, riesgo %s" % (
            p["nombre"], donde, ", ".join(it["archivos"]) or "-", it["tipo"], it["riesgo"]))
        out.append("   hará: %s" % que_hara(it["prompt"]))
        out.append("   prompt: %s" % it["prompt"])
    if prop["cola"]:
        out.append("")
        out.append("EN COLA (%d):" % len(prop["cola"]))
        # Fase 9 E4: one short line per item (claude-vzert: the full texts made 141 KB); the whole text is in
        # `lookout pendientes <proyecto> --match <id>`.
        out.extend("- %s — %s" % (recorta(pendientes.one_line(it), 140), it["motivo"]) for it in prop["cola"])
    if prop["excluidos"]:
        out.append("")
        out.append("EXCLUIDOS (%d):" % len(prop["excluidos"]))
        out.extend("- %s — %s" % (it["id"], it["motivo"]) for it in prop["excluidos"])
    return "\n".join(out)


# ---------- lanza ----------

# Fase 9 (user's decision 2026-10-06): no plan mode. In plan mode a measuring agent would not even try a read-only
# `ssh … 'bash -s'` and nobody but the user's Shift+Tab in its pane could unblock it (bench f9a, 0.9.0 run). The edit
# tools stay removed; a Bash write goes through the user's own permission rules, the A1 clause and `libera --fuera`.
READ_ONLY = ["--disallowedTools", "Edit", "Write", "MultiEdit", "NotebookEdit"]


def exec_args(modelo, solo_lectura=False, env=None):
    """Claude flags for an executor. `env` (Fase 6: PORT) is merged into the --settings env; the settings come from
    LOOKOUT_EXEC_SETTINGS (a JSON text or a file), else just the state dir. One --settings flag, always."""
    import json
    args = []
    if modelo:
        args += ["--model", modelo]
    if "/.claude/plugins/cache/" not in PLUGIN_ROOT:
        # The supervisor runs this tree with --plugin-dir: the agent must run the same code.
        args += ["--plugin-dir", PLUGIN_ROOT]
    raw = os.environ.get("LOOKOUT_EXEC_SETTINGS")
    settings = None
    if raw:
        try:
            if raw.lstrip().startswith("{"):
                settings = json.loads(raw)
            else:
                with open(raw, encoding="utf-8") as fh:
                    settings = json.load(fh)
        except (OSError, ValueError):
            settings = None
        if settings is None and not env:
            args += ["--settings", raw]  # unreadable here: hand it to Claude as it was (old behaviour)
    elif os.environ.get("LOOKOUT_STATE_DIR"):
        settings = {"env": {"LOOKOUT_STATE_DIR": os.environ["LOOKOUT_STATE_DIR"]}}
    if env:
        settings = settings or {}
        settings["env"] = dict(settings.get("env") or {}, **{k: str(v) for k, v in env.items()})
    if settings is not None:
        args += ["--settings", json.dumps(settings)]
    if solo_lectura:
        # An investigation must not edit (3.8.3): the edit tools removed by the harness (adversary round 2); no plan
        # mode since Fase 9 (see READ_ONLY).
        # Kept LAST: the tool list is variadic.
        args += READ_ONLY
    return args


def trust_dialog(pane, worktree):
    """Accept Claude's trust dialog only when it names this agent's own worktree. Returns a status word."""
    code, out, _ = herdr_cli.run(["agent", "read", pane, "--source", "visible"])
    if code != 0 or "trust this folder" not in out:
        return "sin-dialogo"
    lines = [l.strip() for l in out.splitlines()]
    shown = ""
    for i, l in enumerate(lines):
        if l.startswith("Accessing workspace"):
            # A narrow pane wraps the path over several lines (Fase 4 run 3, 40 columns): join them up to the blank line.
            for x in lines[i + 1:]:
                if not x and shown:
                    break
                shown += x
            break
    if not shown or os.path.realpath(shown) != os.path.realpath(worktree):
        return "otra-ruta:" + shown
    # The menu opens on "No, exit"; one Down moves to "Yes, I trust this folder" (seen 2026-10-02).
    herdr_cli.run(["agent", "send-keys", pane, "down", "enter"])
    return "aceptado"


def system_prompt(project_id, item, draft, nota):
    """The file the agent starts with: the (maybe refined) draft + the report note rendered NOW,
    so it names the supervisor that holds the lock at launch time."""
    with open(draft, encoding="utf-8") as fh:
        body = fh.read().rstrip("\n")
    os.makedirs(tareas_dir(project_id), exist_ok=True)
    path = os.path.join(tareas_dir(project_id), item["id"] + ".sistema.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body + "\n\n## Nota del supervisor\n" + nota + "\n")
    return path


def unique_name(base, agents=None):
    taken = {a.get("name") for a in (herdr_cli.agent_list() if agents is None else agents)}
    name, n = base, 2
    while name in taken:
        name = "%s-%d" % (base, n)
        n += 1
    return name


def lanza_uno(project_id, common_dir, item, plan, draft, modelo, confirmar, log, nota):
    root = repo_root(common_dir)
    wt = plan["worktree"]
    if plan.get("sin_worktree"):
        res = herdr_cli.run_json(["workspace", "create", "--cwd", root, "--label", plan["nombre"], "--no-focus"],
                                 timeout=30)
        pane = ((res or {}).get("root_pane") or (res or {}).get("pane") or {}).get("pane_id")
        if not pane:
            return False, "herdr workspace create falló para %s" % root
        log("investigación sin worktree: checkout principal %s en pane %s" % (root, pane))
    else:
        if os.path.exists(wt):
            return False, "ya existe %s: no reuso carpetas" % wt
        res = herdr_cli.run_json(["worktree", "create", "--cwd", root, "--branch", plan["rama"], "--base", plan["base"],
                                  "--path", wt, "--label", plan["nombre"], "--no-focus"], timeout=60)
        pane = ((res or {}).get("root_pane") or {}).get("pane_id")
        if not pane:
            return False, "herdr worktree create falló para %s" % wt
        log("worktree %s (rama %s, base %s) en pane %s" % (wt, plan["rama"], plan["base"], pane))
    # herdr agent names are unique across the whole herdr session, not per project (agent_name_taken,
    # seen 2026-10-02 with two test repos): suffix the name if another agent already has it.
    plan = dict(plan, nombre=unique_name(plan["nombre"]))
    # `--label` names the new WORKSPACE; its tab keeps herdr's default label "1" (seen 2026-10-05). The tab is what the
    # user looks for, so it carries the agent's name too.
    tab_id = ((res or {}).get("tab") or {}).get("tab_id") or ((res or {}).get("root_pane") or {}).get("tab_id") or ""
    pestana = ""
    if tab_id and herdr_cli.run(["tab", "rename", tab_id, plan["nombre"]])[0] == 0:
        pestana = plan["nombre"]
    sid = str(uuid.uuid4())
    lk = lookout_state.read_json(os.path.join(lookout_state.project_dir(project_id), "lock.json")) or {}
    sup = lk.get("supervisor") or {}
    sysfile = system_prompt(project_id, item, draft, nota)
    reg = registry.load(project_id)
    reg.setdefault("agents", {})[sid] = {
        "session_id": sid, "nombre": plan["nombre"], "pane_id": pane, "tab_id": tab_id, "pestana": pestana,
        "terminal_id": "", "herdr_name": plan["nombre"],
        "cwd": wt, "worktree": wt, "branch": plan["rama"], "estado_herdr": "", "hooks": "sin-confirmar",
        "tarea": item["id"], "tarea_estado": "lanzando", "prompt_sistema": sysfile, "base": plan["base"],
        "sin_worktree": bool(plan.get("sin_worktree")), "modelo": modelo or "",
        "alta": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "lanzado_por": "lookout",
        "puerto": ports.asigna(wt) if usa_recursos(item, plan) else None,
    }
    registry.save(project_id, reg)
    lookout_state.write_marker(sid, {"project_id": project_id, "supervisor": sup.get("nombre") or "supervisor",
                                     "address": sup.get("address", ""), "nombre": plan["nombre"],
                                     "display": plan["nombre"] + " (lookout)"})
    ok, msg = arranca(project_id, sid, pane, wt, plan["nombre"], sysfile, modelo, bool(plan.get("sin_worktree")),
                      "tarea:" + item["id"], TRIGGER.format(id=item["id"]), confirmar, log)
    return ok, msg


def arranca(project_id, sid, pane, wt, nombre, sysfile, modelo, sin_worktree, clave, trigger, confirmar, log):
    """Start an already-registered session in `pane` with its system prompt file, accept the trust dialog only
    for its own folder, wait for its SessionStart and its prompt box, then deliver `trigger` once (deliver.py).
    Shared by lanza (F2) and relevo (F3). Returns (ok, message)."""
    offset = deliver.events_size(project_id)
    port = None if sin_worktree else ports.de(wt)  # Fase 6: its worktree's port as $PORT (a relief gets the same)
    args = ["agent", "start", nombre, "--kind", "claude", "--pane", pane, "--timeout", "60000", "--",
            "--session-id", sid, "-n", nombre, "--append-system-prompt-file", sysfile] + exec_args(
                modelo, sin_worktree, {"PORT": port} if port else None)
    code, out, err = herdr_cli.run(args, timeout=75)
    log("agent start rc=%s %s" % (code, (out or err).strip()[:160]))
    trust = trust_dialog(pane, wt)
    log("diálogo de confianza: %s" % trust)
    if trust.startswith("otra-ruta"):
        set_estado(project_id, sid, "fallida", "el diálogo de confianza nombra otra ruta")
        return False, "NO acepto el diálogo de confianza: nombra %r, no %s" % (trust.split(":", 1)[1], wt)
    started = deliver.wait_event(project_id, offset, 60,
                                 lambda ev: ev.get("session_id") == sid and ev.get("event") == "start")
    if not started:
        set_estado(project_id, sid, "fallida", "sin SessionStart: el plugin no cargó o Claude no arrancó")
        return False, "no llegó el SessionStart de %s en 60 s (¿cargó el plugin?)" % nombre
    # SessionStart fires before the prompt box is drawn (seen 2026-10-02 right after the trust dialog: the
    # box read came back unreadable). Block on herdr's own waits until the box line is on screen, then idle.
    herdr_cli.run(["pane", "wait-output", pane, "--source", "visible", "--regex", "(?m)^❯", "--timeout", "30000"],
                  timeout=35)
    herdr_cli.run(["agent", "wait", pane, "--until", "idle", "--timeout", "30000"], timeout=35)
    entry = registry.find(registry.load(project_id), sid)
    rc, msg = deliver.deliver(project_id, entry, clave, trigger, confirmar)
    log("entrega: " + msg)
    if rc == 0:
        set_estado(project_id, sid, "trabajando", hooks="ok")
        return True, "%s lanzado en %s y con su tarea confirmada" % (nombre, pane)
    set_estado(project_id, sid, "sin-confirmar")
    return False, "%s lanzado en %s; la entrega no se confirmó: %s" % (nombre, pane, msg)


def revisa_alcance(project_id, entry, fuera, usuario_confirmo=""):
    """Fase 9 A4: `libera` only after the supervisor compared the agent's report (its "riesgo asumido", what it
    wrote and where) with the task's criteria. --fuera ninguno says nothing went outside; anything else must be shown
    to the user first, and --usuario-confirmo cites the decision where the user saw it. Returns (ok, lines)."""
    tarea = entry.get("prompt_sistema") or "(sin archivo de tarea registrado)"
    if not (fuera or "").strip():
        return False, [
            "NO: antes de liberar, compara el reporte de %s con su tarea (%s): «Alcance / no tocar», «Restricciones» "
            "y «Criterios de aceptación»." % (entry.get("nombre", "?"), tarea),
            "Busca en el reporte y en su transcript lo que escribió y dónde (fuera del worktree, en hosts remotos, "
            "scp, mktemp, rm) y su «riesgo asumido».",
            "Si nada se salió: `lookout libera <proyecto> <agente> --fuera ninguno`.",
            "Si algo se salió: díselo al usuario en un bloque de decisión (`lookout decision --abre`), y con su "
            "respuesta: `lookout libera <proyecto> <agente> --fuera \"<qué se salió>\" --usuario-confirmo <id>`."]
    if fuera.strip().lower() == "ninguno":
        return True, []
    d = decisiones.respondida(project_id, usuario_confirmo or "")
    if not d:
        return False, [
            "NO: %s se salió de su tarea (%s). Eso lo ve el usuario antes de liberar: ábrele una decisión con "
            "`lookout decision --abre` que diga qué se salió, ciérrala con su respuesta y repite con "
            "--usuario-confirmo <id>." % (entry.get("nombre", "?"), fuera.strip())]
    return True, ["Fuera de la tarea: %s — lo vio el usuario: %s (%s)" % (fuera.strip(), d["id"], d.get("respuesta", ""))]


def set_estado(project_id, sid, estado, motivo="", hooks=None):
    reg = registry.load(project_id)
    e = reg.get("agents", {}).get(sid)
    if not e:
        return None
    e["tarea_estado"] = estado
    if motivo:
        e["tarea_motivo"] = motivo
    if hooks:
        e["hooks"] = hooks
    registry.save(project_id, reg)
    return e


def lanza(project_id, common_dir, ids, nota_for, modelo=None, confirmar=30.0, tope=None, log=print):
    """Launch the given ids, each only if it is in the batch proposed right now (cap and coupling hold)."""
    with project_mutex(project_id):
        return _lanza(project_id, common_dir, ids, nota_for, modelo, confirmar, tope, log)


def _lanza(project_id, common_dir, ids, nota_for, modelo, confirmar, tope, log):
    prop = propone(project_id, common_dir, tope)
    by_id = {it["id"]: it for it in prop["lote"]}
    queued = {it["id"]: it["motivo"] for it in prop["cola"] + prop["excluidos"]}
    results = []
    for pid_ in ids:
        it = by_id.get(pid_)
        if not it:
            results.append((pid_, False, "no está en el lote de ahora: %s" % queued.get(pid_, "no es un pendiente abierto")))
            continue
        ok, msg = lanza_uno(project_id, common_dir, it, it["plan"], it["prompt"], modelo, confirmar, log,
                            nota_for(it["plan"]["nombre"]))
        results.append((pid_, ok, msg))
    return results

#!/usr/bin/env python3
"""Read a project's 3-tier `memory/_pendientes.md` by fields and propose a batch (docs/plan.md 3.8, F2).

Only structured fields decide (priority = section, `_id`, `_creado`, `_revisar`, `_bloqueado`,
`_origen`). The one reading of free text is mechanical: file paths cited in the item (backtick
spans or path-shaped tokens) mark two items as coupled, so they never run in parallel.
Writing to 3-tier is never done here: closing a pendiente goes through its journal (F3).

Usage:
  pendientes.py lista  <memory/_pendientes.md> [--json]
  pendientes.py match  <memory/_pendientes.md> TERMINO [TERMINO...]   (H13: one line per related item)
"""
import json
import os
import re
import sys
import time

PRIORIDADES = {"alta": 0, "media": 1, "baja": 2}
SECTION = re.compile(r"^##\s+(Alta|Media|Baja)\s+prioridad\s*$", re.I)
ITEM = re.compile(r"^- \[ \] (.*)$")
FIELD = re.compile(r"^_([a-z]+):\s*(.*?)_?$")
BACKTICK = re.compile(r"`([^`\s]+)`")
BARE_PATH = re.compile(r"(?<![\w/.:-])((?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]{1,6})(?![\w/])")
FILE_LIKE = re.compile(r"^(?:[\w.-]+/)*[\w-][\w.-]*\.[A-Za-z0-9]{1,6}$|^(?:[\w.-]+/)+[\w.-]+/?$")
# Fase 9 B3: `origin/develop` looks like a dir and coupled unrelated items of the claude-vzert batch. A remote or a ref
# namespace as first segment is a git ref, not a path (lookout/ is this plugin's own branch prefix).
GIT_REF = re.compile(r"^(origin|upstream|refs|remotes|heads|tags|lookout)/", re.I)
INVESTIGACION = re.compile(r"^(investigar|investigación|investigacion|research|evaluar|analizar|averiguar|medir)\b", re.I)
# Fase 9 B2: an item that sends a message or touches a credential carries no code commit. comunicacion: the agent
# drafts and never sends. credencial: rotating, revoking or an exposed secret; high risk, the user acts.
# Adversary round 1 (2026-10-06): «Enviar a la cola de Redis…», «Escribir a la base de datos…», «Mandar a producción…»
# are code. A message is «comunicar…», «avisar/notificar/informar a …», «contactar a …», or a send/write verb whose
# object is a message (correo, mensaje, cuestionario…). "Avisar en el log cuando…" has no «a»: code.
COMUNICACION = re.compile(
    r"^(comunicar(le|les)?\b"
    r"|(avisar|notificar|informar|contactar)(le|les)?\b.{0,60}?\b(a|al)\b"
    r"|(enviar|mandar|escribir|responder|redactar)(le|les)?\b.{0,80}?\b(correos?|mensajes?|e-?mails?|cuestionarios?|"
    r"encuestas?|avisos?|recordatorios?|invitaci[oó]n(es)?|comunicados?|anuncios?)\b)", re.I)
# A send verb also needs a person to receive it: «Enviar a la cola de Redis los mensajes fallidos» is code.
HUMANO = re.compile(r"\b(a|al|para)\s+(los|las|el|la|tu|su|sus|mis)?\s*(\d+\s+)?(devs?|desarrolladore?s?|usuarios?|"
                    r"clientes?|equipo|personas?|socios?|jefes?|direcci[oó]n|gerentes?|proveedore?s?|soporte|"
                    r"compañer[oa]s?|colegas?|contadore?s?|abogad[oa]s?|todos)\b", re.I)


# A fix/arreglo is code even when it names a token or starts by measuring («Fix: el token expuesto en el log»,
# «Medir y arreglar la latencia»).
CODIGO_VERBO = re.compile(r"^(fix|arreglar|corregir|parchar|parchear)\b")
CAMBIA_CODIGO = re.compile(r"\b(arreglar|corregir|implementar|refactorizar|fix)\b", re.I)
CRED_VERBO = re.compile(r"^(rotar|revocar|regenerar|renovar|reemitir)\b", re.I)
CRED_NOMBRE = re.compile(r"\b(tokens?|credencial(es)?|contraseñas?|password|secretos?|api[ -]?keys?|pat|claves? "
                         r"(de api|privadas?|ssh)|certificados?)\b", re.I)
CRED_EXPUESTA = re.compile(r"\b(commitead[oa]s?|filtrad[oa]s?|expuest[oa]s?|texto plano|en claro|leak(ed)?|"
                           r"rotaci[oó]n)\b", re.I)
RIESGO = re.compile(r"\b(push|merge|borrar|eliminar|deploy|publicar|release|migrar|force)\b", re.I)


MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
MD_MARCA = re.compile(r"(\*\*|__|~~|`|(?<![\w*])[*_](?=\S)|(?<=\S)[*_](?![\w*]))")
MD_PREFIJO = re.compile(r"^[\s#>\-+*\d.)\]\[]*")


def plano(texto):
    """Fase 9 B1: the item text without markdown, for classifying only (the text itself is kept as written).
    `**Medir** …` came out as code because INVESTIGACION is anchored at the start."""
    t = MD_LINK.sub(r"\1", texto)
    t = MD_MARCA.sub("", t)
    return MD_PREFIJO.sub("", t).strip()


def clasifica(texto):
    """(tipo, riesgo) of an item, read from its plain text. A credential wins over everything (it is the risky one),
    then a message, then an investigation; the rest is code."""
    t = plano(texto)
    riesgo = "alto" if RIESGO.search(t) else "normal"
    if CODIGO_VERBO.match(t.lower()):
        return "codigo", riesgo
    if CRED_VERBO.match(t) and CRED_NOMBRE.search(t) or CRED_NOMBRE.search(t) and CRED_EXPUESTA.search(t):
        return "credencial", "alto"
    m = COMUNICACION.match(t)
    if m and (m.group(1).lower().startswith(("comunicar", "avisar", "notificar", "informar", "contactar"))
              or HUMANO.search(t)):
        return "comunicacion", riesgo
    if INVESTIGACION.match(t) and not CAMBIA_CODIGO.search(t):
        return "investigacion", riesgo
    return "codigo", riesgo


# Fase 9 A2/B3: files nearly every item cites. Matching on them made a task carry ~17 unrelated items (18 KB, with where
# a certificate and its password live), and coupling on them queued items that share nothing.
GENERICOS = {"MEMORY.md", "CLAUDE.md", "AGENTS.md", "README.md", "CHANGELOG.md"}


def generico(path):
    base = os.path.basename(path.rstrip("/"))
    return base in GENERICOS or (base.startswith("_") and base.endswith(".md")) or path.rstrip("/") == "memory"


def especificos(archivos):
    return [f for f in archivos if not generico(f)]


def parse_line(body):
    """Split '<texto> — _campo: valor_ — …' into (texto, {campo: valor}). Fields are read from the right."""
    parts = body.split(" — ")
    fields = {}
    while len(parts) > 1:
        m = FIELD.match(parts[-1].strip())
        if not m:
            break
        fields[m.group(1)] = m.group(2).strip()
        parts.pop()
    return " — ".join(parts).strip(), fields


def archivos(texto):
    """Paths cited in the item text: backtick spans that look like files/dirs, plus bare a/b.ext tokens."""
    found = set()
    for span in BACKTICK.findall(texto):
        if "://" in span:
            continue
        span = span[2:] if span.startswith("./") else span
        if FILE_LIKE.match(span) and not GIT_REF.match(span):
            found.add(span.rstrip("/"))
    for tok in BARE_PATH.findall(texto):
        if "://" not in tok and not GIT_REF.match(tok):
            found.add(tok[2:] if tok.startswith("./") else tok)
    return sorted(found)


def parse(path):
    """Open items of _pendientes.md, in file order. A missing file gives []."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    items, prio = [], None
    for n, line in enumerate(lines, 1):
        if line.startswith("## "):
            m = SECTION.match(line)
            prio = m.group(1).lower() if m else None
            continue
        if prio is None:
            continue
        m = ITEM.match(line)
        if not m:
            continue
        texto, f = parse_line(m.group(1))
        if not f.get("id"):
            continue  # without an id nothing can be tracked or closed by journal
        tipo, riesgo = clasifica(texto)
        items.append({
            "id": f["id"], "texto": texto, "prioridad": prio, "linea": n,
            "creado": f.get("creado", ""), "revisar": f.get("revisar", ""),
            "bloqueado": f.get("bloqueado", ""), "origen": f.get("origen", ""),
            "archivos": archivos(texto),
            "tipo": tipo, "riesgo": riesgo,
        })
    return items


def propose(items, tope, activos=(), asignados=(), hoy=None, otras=0):
    """Batch for the free slots. Returns {lote, cola, excluidos, libres}.

    activos: [(pendiente_id, [archivos])] of tasks now running (they hold slots and files).
    asignados: ids already given to an agent (running or finished, not yet closed by journal).
    otras: live sessions of the project without a lookout task (F5: they hold slots too, not files).
    """
    hoy = hoy or time.strftime("%Y-%m-%d")
    asignados = set(asignados)
    excluidos, candidatos = [], []
    for it in items:
        if it["bloqueado"]:
            excluidos.append(dict(it, motivo="bloqueado: " + it["bloqueado"]))
        elif it["revisar"] and it["revisar"] > hoy:
            excluidos.append(dict(it, motivo="revisar el " + it["revisar"]))
        elif it["id"] in asignados:
            excluidos.append(dict(it, motivo="ya tiene agente"))
        else:
            candidatos.append(it)
    # Highest priority first; within it the NEWEST first (Fase 9, user's decision 2026-10-06: an old item is likely
    # no longer needed). Same date: the 3-tier compactor inserts new items at the TOP of their section, so a line
    # nearer the top (a LOWER line number) is newer. An item without _creado_ goes last in its priority. Stable sorts, least significant key first.
    candidatos.sort(key=lambda it: it["linea"])
    candidatos.sort(key=lambda it: it["creado"] or "", reverse=True)
    candidatos.sort(key=lambda it: PRIORIDADES[it["prioridad"]])
    libres = max(0, tope - len(activos) - otras)
    tomados = [(pid, set(especificos(fs))) for pid, fs in activos]
    lote, cola = [], []
    en_lote = set()
    for it in candidatos:
        mine = set(especificos(it["archivos"]))
        choques = [(pid, sorted(mine & fs)) for pid, fs in tomados if mine & fs]
        choque = choques[0] if choques else None
        par = next((x for x in lote if x["id"] == choque[0]), None) if len(choques) == 1 and choque[0] in en_lote else None
        if par and mas_viejo(it, par):
            # Inside a coupled pair the older item goes first: it is usually the base ("create X" before "add to X").
            # User's decision 2026-10-06; between unrelated items the newest still wins.
            lote[lote.index(par)] = it
            en_lote.discard(par["id"])
            en_lote.add(it["id"])
            tomados = [(it["id"], mine) if pid == par["id"] else (pid, fs) for pid, fs in tomados]
            cola.append(dict(par, motivo="acoplado con %s (%s): va en serie, después del más viejo" % (
                it["id"], ", ".join(choque[1]))))
            continue
        if choque:
            cola.append(dict(it, motivo="acoplado con %s (%s): va en serie" % (choque[0], ", ".join(choque[1]))))
        elif len(lote) >= libres:
            cola.append(dict(it, motivo="tope de %d agentes" % tope))
        else:
            lote.append(it)
            en_lote.add(it["id"])
            tomados.append((it["id"], mine))
    return {"lote": lote, "cola": cola, "excluidos": excluidos, "libres": libres, "tope": tope, "otras": otras}


def mas_viejo(a, b):
    """a was created before b: earlier _creado_, or the same date and a lower line (the compactor writes new items at
    the top). Without a date on either, no order is known."""
    if not a["creado"] or not b["creado"]:
        return False
    return (a["creado"], -a["linea"]) < (b["creado"], -b["linea"])


def match(items, terminos):
    """Items whose text, files or id mention any term (case-insensitive). For H13 checks."""
    ts = [t.lower() for t in terminos if t.strip()]
    out = []
    for it in items:
        hay = " ".join([it["id"], it["texto"]] + it["archivos"]).lower()
        if any(t in hay for t in ts):
            out.append(it)
    return out


def one_line(it, extra=""):
    flags = [it["prioridad"]]
    if it["bloqueado"]:
        flags.append("bloqueado")
    if it["revisar"]:
        flags.append("revisar " + it["revisar"])
    return "%s [%s] %s%s" % (it["id"], ", ".join(flags), it["texto"], extra)


def main(argv):
    if len(argv) < 3 or argv[1] not in ("lista", "match"):
        print(__doc__.strip())
        return 2
    items = parse(argv[2])
    if argv[1] == "lista":
        if "--json" in argv:
            print(json.dumps(items, ensure_ascii=False, indent=1))
        else:
            for it in items:
                print(one_line(it))
        return 0
    found = match(items, argv[3:])
    for it in found:
        print(one_line(it))
    if not found:
        print("(ningún pendiente abierto menciona: %s)" % ", ".join(argv[3:]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

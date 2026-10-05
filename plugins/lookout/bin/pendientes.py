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
INVESTIGACION = re.compile(r"^(investigar|investigación|investigacion|research|evaluar|analizar|averiguar|medir)\b", re.I)
RIESGO = re.compile(r"\b(push|merge|borrar|eliminar|deploy|publicar|release|migrar|force)\b", re.I)


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
        if FILE_LIKE.match(span):
            found.add(span.rstrip("/"))
    for tok in BARE_PATH.findall(texto):
        if "://" not in tok:
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
        items.append({
            "id": f["id"], "texto": texto, "prioridad": prio, "linea": n,
            "creado": f.get("creado", ""), "revisar": f.get("revisar", ""),
            "bloqueado": f.get("bloqueado", ""), "origen": f.get("origen", ""),
            "archivos": archivos(texto),
            "tipo": "investigacion" if INVESTIGACION.match(texto) else "codigo",
            "riesgo": "alto" if RIESGO.search(texto) else "normal",
        })
    return items


def propose(items, tope, activos=(), asignados=(), hoy=None):
    """Batch for the free slots. Returns {lote, cola, excluidos, libres}.

    activos: [(pendiente_id, [archivos])] of tasks now running (they hold slots and files).
    asignados: ids already given to an agent (running or finished, not yet closed by journal).
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
    # Same priority and date: the older item first. The 3-tier compactor inserts new items at the TOP
    # of their section (seen in its output and in this repo's own _pendientes.md), so a lower line is older.
    candidatos.sort(key=lambda it: (PRIORIDADES[it["prioridad"]], it["creado"] or "9999", -it["linea"]))
    libres = max(0, tope - len(activos))
    tomados = [(pid, set(fs)) for pid, fs in activos]
    lote, cola = [], []
    for it in candidatos:
        mine = set(it["archivos"])
        choque = next(((pid, sorted(mine & fs)) for pid, fs in tomados if mine & fs), None)
        if choque:
            cola.append(dict(it, motivo="acoplado con %s (%s): va en serie" % (choque[0], ", ".join(choque[1]))))
        elif len(lote) >= libres:
            cola.append(dict(it, motivo="tope de %d agentes" % tope))
        else:
            lote.append(it)
            tomados.append((it["id"], mine))
    return {"lote": lote, "cola": cola, "excluidos": excluidos, "libres": libres, "tope": tope}


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

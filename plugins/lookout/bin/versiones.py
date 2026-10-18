"""0.13.8 (p-d0c5d57049): which agents run hooks older than the installed plugins.

An agent opened before `claude plugin update` keeps the old hooks until /reload-plugins in ITS session. Live 3-tier
2026-10-16: prompts-repetidos ran 3-tier-memory 2.62.0 with 2.62.6 installed (its close guard looped every turn over a
bug fixed in 2.62.3), 3tier-snippet-linea-extras lookout 0.12.1 (no `retomar` field: its «Como retomar: Ninguno» never
closed its tab), pendientes-en-sessionstart lookout 0.13.5 (no `espera_pane`). Two sources:
  - lookout: the `v` every hook event carries since 0.13.8 (no `v` = older);
  - any plugin whose hooks print a path: the version in `…/plugins/cache/<marketplace>/<plugin>/<version>/` inside
    a hook attachment of the agent's transcript (3-tier-memory's recall prints its journal-emit.py path). Only hook
    attachments count: a path the agent read or ran itself says nothing about its hooks.
"""
import json
import os
import re

import lookout_state
import requisitos

LOOKOUT = "lookout@lookout-marketplace"
HOOKS_CLAUDE = ("Stop", "UserPromptSubmit", "Notification", "SessionStart", "SessionEnd", "StopFailure", "PostToolUse",
                "PostToolUseFailure", "PermissionRequest", "PreToolUse", "PermissionDenied")
RUTA = re.compile(r"/plugins/cache/([^/\"\\\s]+)/([^/\"\\\s]+)/(\d[\w.+-]*)/")


def instaladas():
    """{"plugin@marketplace": version} from installed_plugins.json; lookout's own version if it is not there."""
    out = {}
    try:
        with open(os.path.join(requisitos.config_dir(), "plugins", "installed_plugins.json"), encoding="utf-8") as fh:
            for key, rows in (json.load(fh).get("plugins") or {}).items():
                ver = next((r.get("version") for r in rows or [] if isinstance(r, dict) and r.get("version")), None)
                if ver:
                    out[key] = ver
    except (OSError, ValueError, AttributeError):
        pass
    out.setdefault(LOOKOUT, lookout_state.plugin_version())
    return out


def citadas(transcript_path, max_bytes=1500000):
    """{"plugin@marketplace": version} its hooks printed last, read from the hook attachments of the transcript tail."""
    out = {}
    if not transcript_path:
        return out
    try:
        with open(transcript_path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - max_bytes))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return out
    for line in lines:
        if '"attachment"' not in line or "/plugins/cache/" not in line:
            continue
        try:
            a = json.loads(line).get("attachment") or {}
        except ValueError:
            continue
        if not str(a.get("type", "")).startswith("hook_"):
            continue
        for m in RUTA.finditer(json.dumps(a, ensure_ascii=False)):
            out["%s@%s" % (m.group(2), m.group(1))] = m.group(3)
    return out


def _tupla(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3]) or (0,)


def _con_recarga(v, recargado):
    """(version its hooks run, came from the reload). A reload lookout typed loads what was installed then, so the
    hooks run at least that: an agent idle since (3-tier 2026-10-17, prompts-repetidos) has no newer event to show it."""
    if recargado and _tupla(recargado) > _tupla(v or "0"):
        return recargado, True
    return v, False


def viejos(entry, events, transcript_path, inst=None):
    """[(plugin, version its hooks run, installed version, came from a reload)] for one agent; [] when up to date or
    unknown. A /reload-plugins lookout typed (`recargado`: {plugin: version installed then}) counts as that version."""
    inst = instaladas() if inst is None else inst
    sid = entry.get("session_id")
    hechos = entry.get("recargado") or {}
    out = []
    # only what the agent's own Claude hooks wrote: the supervisor writes `hook: descubre|registro|barrido` events with
    # its own version, and on_ask's `ask` has no `hook`
    last = next((ev for ev in reversed(events) if ev.get("session_id") == sid and ev.get("hook") in HOOKS_CLAUDE), None)
    if last is not None and inst.get(LOOKOUT):
        v, rec = _con_recarga(last.get("v") or "", hechos.get(LOOKOUT))
        # no `v`: hooks before 0.13.8, the first that stamps it; older only once 0.13.8 or later is installed
        antiguo = _tupla(v) < _tupla(inst[LOOKOUT]) if v else _tupla(inst[LOOKOUT]) >= (0, 13, 8)
        if antiguo:
            out.append(("lookout", v or "<0.13.8", inst[LOOKOUT], rec))
    for key, v in sorted(citadas(transcript_path).items()):
        if key == LOOKOUT or key not in inst:
            continue
        v, rec = _con_recarga(v, hechos.get(key))
        if _tupla(v) < _tupla(inst[key]):
            out.append((key.split("@")[0], v, inst[key], rec))
    return out


def texto(lista):
    return ", ".join("%s %s (instalada %s)%s" % (p, v, i, "; ya recargado; la %s llegó después" % i if rec else "")
                     for p, v, i, rec in lista)

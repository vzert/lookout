#!/usr/bin/env python3
"""Release checks that need no Claude Code: the marketplace and plugin manifests, the version rule, skill frontmatter,
and hooks.json. Run from the repo root: python3 tools/check-manifest.py   (exit 1 = a problem, each one printed).

Version rule (docs/plan.md, Fase 7): plugin.json `version` == marketplace.json `metadata.version`. Claude Code caches a
plugin by version, so a change shipped without a bump never reaches an existing install.
Frontmatter is parsed with PyYAML (CI installs it); without PyYAML the check fails instead of passing silently.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
problems = []


def bad(msg):
    problems.append(msg)


def load_json(rel):
    try:
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        bad("%s: no se puede leer como JSON (%s)" % (rel, exc))
        return None


def frontmatter(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if not text.startswith("---\n"):
        return None, "no empieza con un bloque --- de frontmatter"
    end = text.find("\n---\n", 4)
    if end < 0:
        return None, "el frontmatter no se cierra con ---"
    try:
        import yaml
    except ImportError:
        return None, "falta PyYAML para leer el frontmatter (pip install pyyaml)"
    try:
        data = yaml.safe_load(text[4:end])
    except yaml.YAMLError as exc:
        return None, "YAML inválido: %s" % str(exc).splitlines()[0]
    if not isinstance(data, dict):
        return None, "el frontmatter no es un mapa"
    return data, None


def check_plugin(entry):
    name, source = entry.get("name"), entry.get("source")
    if not isinstance(source, str) or not source.startswith("./"):
        bad("marketplace.json: plugin %r necesita un source local './…' (es %r)" % (name, source))
        return None
    pdir = os.path.normpath(os.path.join(ROOT, source))
    rel = os.path.relpath(pdir, ROOT)
    pj = load_json(os.path.join(rel, ".claude-plugin", "plugin.json"))
    if pj is None:
        return None
    if pj.get("name") != name:
        bad("%s/.claude-plugin/plugin.json: name %r no coincide con el del marketplace %r" % (rel, pj.get("name"), name))
    if not SEMVER.match(str(pj.get("version", ""))):
        bad("%s/.claude-plugin/plugin.json: version %r no es X.Y.Z" % (rel, pj.get("version")))
    if not pj.get("description"):
        bad("%s/.claude-plugin/plugin.json: falta description" % rel)
    skills = os.path.join(pdir, "skills")
    for sk in sorted(os.listdir(skills)) if os.path.isdir(skills) else []:
        path = os.path.join(skills, sk, "SKILL.md")
        if not os.path.isfile(path):
            continue
        data, err = frontmatter(path)
        srel = os.path.relpath(path, ROOT)
        if err:
            bad("%s: %s" % (srel, err))
            continue
        for key in ("name", "description"):
            if not isinstance(data.get(key), str) or not data[key].strip():
                bad("%s: falta %s en el frontmatter" % (srel, key))
        if data.get("name") not in (None, sk):
            bad("%s: name %r no coincide con su carpeta %r" % (srel, data.get("name"), sk))
    hooks = os.path.join(rel, "hooks", "hooks.json")
    if os.path.isfile(os.path.join(ROOT, hooks)):
        hj = load_json(hooks) or {}
        for event, groups in (hj.get("hooks") or {}).items():
            for g in groups:
                for h in g.get("hooks", []):
                    for script in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}\"?/([\w./-]+)", h.get("command", "")):
                        if not os.path.isfile(os.path.join(pdir, script)):
                            bad("%s: %s llama a %s, que no existe" % (hooks, event, script))
    return pj.get("version")


def main():
    mk = load_json(os.path.join(".claude-plugin", "marketplace.json"))
    if mk is not None:
        for key in ("name",):
            if not mk.get(key):
                bad("marketplace.json: falta %s" % key)
        if not (mk.get("owner") or {}).get("name"):
            bad("marketplace.json: falta owner.name")
        mver = (mk.get("metadata") or {}).get("version")
        plugins = mk.get("plugins") or []
        if not plugins:
            bad("marketplace.json: no lista ningún plugin")
        for entry in plugins:
            pver = check_plugin(entry)
            if pver and pver != mver:
                bad("versión: plugin.json de %s dice %s y marketplace.json metadata.version dice %s; sube las dos "
                    "juntas" % (entry.get("name"), pver, mver))
    for p in problems:
        print("FALLA: " + p)
    if problems:
        return 1
    print("manifiestos OK: %s, versión %s" % (mk["name"], mk["metadata"]["version"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

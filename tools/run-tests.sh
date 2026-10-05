#!/usr/bin/env bash
# Everything CI runs, in order; also the local check before a release. Run from anywhere: bash tools/run-tests.sh
# 1) bash -n / sh -n on every shell script of the plugin and tools, 2) Python compiles, 3) manifests, version rule and
# skill frontmatter (tools/check-manifest.py), 4) the unit suite (tests/test_*.py), with herdr replaced by a stub.
set -u
cd "$(dirname "$0")/.." || exit 1
fail=0

echo "== sintaxis de shell"
while IFS= read -r f; do
  if head -1 "$f" | grep -q bash; then bash -n "$f" || { echo "FALLA bash -n $f"; fail=1; }
  else sh -n "$f" || { echo "FALLA sh -n $f"; fail=1; }; fi
done < <(find plugins tools -name '*.sh' -type f | sort)

echo "== python compila"
python3 - <<'EOF' || fail=1
import os, sys
bad = 0
for base in ("plugins", "tools", "tests"):
    for d, _, files in os.walk(base):
        if "__pycache__" in d:
            continue
        for f in files:
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                first = fh.readline()
            if f.endswith(".py") or (b"python" in first and first.startswith(b"#!")):
                try:
                    with open(p, encoding="utf-8") as fh:
                        compile(fh.read(), p, "exec")
                except (SyntaxError, UnicodeDecodeError) as exc:
                    print("FALLA python", p, exc)
                    bad = 1
sys.exit(bad)
EOF

echo "== manifiestos"
python3 tools/check-manifest.py || fail=1

echo "== suite"
python3 -m unittest discover -s tests -p 'test_*.py' || fail=1

if [ "$fail" -ne 0 ]; then echo "RESULTADO: FALLA"; exit 1; fi
echo "RESULTADO: OK"

#!/usr/bin/env bash
# Build the public tree of vzert/lookout from this private working repo (Fase 7, decision of the user: a new, clean
# repo; agente-coordinador keeps its history and stays private).
#
#   bash tools/exporta-publico.sh DESTINO
#
# Copies ONLY the allowlist below (tracked or new files; never docs/, memory/, tests/escenarios/, tests/spikes/, the
# evidence of the live runs). tests/fixtures/ does go (minus caja-a5.ansi, which no test reads): 6 screen captures of test sessions (caja-*.ansi; the input-box
# tests need real screens) and a pendientes file; reviewed by hand, they hold test prompts, /private/tmp test paths,
# model, plan and RAM lines of the status bar. Then it writes the public .gitignore, scans every exported file and fails
# (exit 1) on:
# a home path (/Users/…, /home/…), a UUID (session ids), a credential pattern, or a file over 1 MB.
# DESTINO must not exist or be empty, except for a .git folder (re-export onto a clone of vzert/lookout).
# It never runs git: committing and pushing the result is a separate step, with the user's confirmation.
set -euo pipefail
cd "$(dirname "$0")/.."
dest="${1:?uso: bash tools/exporta-publico.sh DESTINO}"
mkdir -p "$dest"
if [ -n "$(find "$dest" -mindepth 1 -maxdepth 1 ! -name .git -print -quit)" ]; then
  echo "FALLA: $dest no está vacío (fuera de .git). Usa una carpeta nueva o vacíala." >&2
  exit 1
fi

ALLOW=(
  .claude-plugin/marketplace.json
  plugins/lookout
  tests/fixtures
  tools/run-tests.sh
  tools/check-manifest.py
  tools/exporta-publico.sh
  .github/workflows/tests.yml
  README.md LICENSE NOTICE CREDITS.md CHANGELOG.md
)
for p in "${ALLOW[@]}"; do
  [ -e "$p" ] || { echo "FALLA: falta $p" >&2; exit 1; }
done

# Files: the allowlist plus tests/test_*.py, without caches.
{
  for p in "${ALLOW[@]}"; do
    if [ -d "$p" ]; then find "$p" -type f; else echo "$p"; fi
  done
  find tests -maxdepth 1 -name 'test_*.py' -type f
} | grep -v -E '(^|/)__pycache__/|\.pyc$|(^|/)\.DS_Store$|^tests/fixtures/caja-a5\.ansi$' | sort -u > "$dest/.lista-exportada"

while IFS= read -r f; do
  mkdir -p "$dest/$(dirname "$f")"
  cp -p "$f" "$dest/$f"
done < "$dest/.lista-exportada"
rm "$dest/.lista-exportada"

cat > "$dest/.gitignore" <<'EOF'
__pycache__/
*.pyc
.DS_Store
.goalspec/
.claude/
EOF

n=$(find "$dest" -type f ! -path "$dest/.git/*" | wc -l | tr -d ' ')  # after .gitignore: every file published

# Scan everything exported. Made-up examples that are not a leak: test paths under /private/tmp, /Users/alguien/ (a
# test of publica's private-path check) and the three fake UUIDs of the tests.
fail=0
while IFS= read -r f; do
  rel="${f#"$dest"/}"
  size=$(wc -c < "$f" | tr -d ' ')
  if [ "$size" -gt 1048576 ]; then echo "FALLA: $rel pesa $size bytes (>1 MB)"; fail=1; fi
  # the allowed examples are removed from the text BEFORE searching, so a real one on the same line is still found
  clean=$(LC_ALL=C sed -e 's|/Users/alguien/||g' -e 's|11111111-2222-3333-4444-555555555555||g' \
      -e 's|77777777-1111-2222-3333-444444444444||g' -e 's|00000000-0000-4000-8000-000000000001||g' "$f")
  if printf '%s\n' "$clean" | LC_ALL=C grep -n -E '/(Users|home)/[A-Za-z0-9._-]' > /dev/null; then
    echo "FALLA: ruta de un home en $rel:"; printf '%s\n' "$clean" | LC_ALL=C grep -n -E '/(Users|home)/[A-Za-z0-9._-]' | head -3; fail=1
  fi
  if printf '%s\n' "$clean" | LC_ALL=C grep -i -E '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' > /dev/null; then
    echo "FALLA: un UUID (¿id de sesión?) en $rel:"
    printf '%s\n' "$clean" | LC_ALL=C grep -n -i -o -E '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -3; fail=1
  fi
  # this script holds the patterns themselves; everything else is scanned
  if [ "$rel" != tools/exporta-publico.sh ] && grep -n -I -E 'sk-ant-|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY|xox[abp]-' "$f" > /dev/null; then
    echo "FALLA: algo con forma de credencial en $rel"; fail=1
  fi
done < <(find "$dest" -type f ! -path "$dest/.git/*")

if [ "$fail" -ne 0 ]; then echo "EXPORTACIÓN CON FALLAS: no la publiques." >&2; exit 1; fi
echo "Exportados $n archivos a $dest. Escaneo limpio (rutas de home, UUIDs, credenciales, >1 MB)."

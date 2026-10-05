#!/bin/sh
# Gate for the hooks of the SUPERVISOR's own session (Fase 4): exit at once, with no output, unless this session
# has a supervisor marker (<state>/supervisores/<session_id>.json, written by `lookout inicia`). The executors
# carry the same plugin, so without this gate PreCompact and PostToolUse[SendMessage] would run in them too.
# Same session_id parsing as guard.sh. Usage (from hooks.json): guard-sup.sh <handler.py>
input=$(cat)
sid=$(printf '%s' "$input" | /usr/bin/head -c 200 | /usr/bin/sed -n 's/^{ *"session_id" *: *"\([^"]*\)".*/\1/p')
if [ -z "$sid" ]; then
  sid=$(printf '%s' "$input" | /usr/bin/grep -o '"session_id" *: *"[^"]*"' | /usr/bin/head -n 1 \
    | /usr/bin/sed 's/.*"\([^"]*\)"$/\1/')
fi
case "$sid" in ''|*/*|.*) exit 0 ;; esac
root="${LOOKOUT_STATE_DIR:-$HOME/.local/state/lookout}"
[ -f "$root/supervisores/$sid.json" ] || exit 0
printf '%s' "$input" | exec python3 "$(dirname "$0")/../bin/$1"

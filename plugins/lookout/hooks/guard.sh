#!/bin/sh
# Gate for every lookout hook (docs/plan.md 3.1): exit at once, with no output, unless this
# session has a supervision marker. Pure shell so an unsupervised session pays no python start-up.
# Usage (from hooks.json): guard.sh <handler.py>   — the hook payload arrives on stdin.
input=$(cat)
# Claude Code sends compact JSON whose FIRST key is the top-level session_id (captured 2026-10-02).
# Anchor to it, so a supervised id quoted inside tool_input cannot wake python in an unsupervised
# session. If the order ever changes, fall back to the first occurrence (the handler re-checks the
# real top-level id, so the fallback can only cost time, never misroute an event).
sid=$(printf '%s' "$input" | /usr/bin/head -c 200 | /usr/bin/sed -n 's/^{ *"session_id" *: *"\([^"]*\)".*/\1/p')
if [ -z "$sid" ]; then
  sid=$(printf '%s' "$input" | /usr/bin/grep -o '"session_id" *: *"[^"]*"' | /usr/bin/head -n 1 \
    | /usr/bin/sed 's/.*"\([^"]*\)"$/\1/')
fi
case "$sid" in ''|*/*|.*) exit 0 ;; esac
root="${LOOKOUT_STATE_DIR:-$HOME/.local/state/lookout}"
# Fase 4: the supervisor's own AskUserQuestion goes to its log when it is ASKED (PreToolUse), so a question the user
# never answered survives a relief. Same hook entry, so a live supervisor gets it without reloading hooks.json. Checked
# FIRST: a supervisor's question is never denied, even if its session also carries an executor marker (adversary F4).
# Its Stop does not: see below.
if { [ "$1" = on_ask.py ] || [ "$1" = on_state.py ]; } && [ -f "$root/supervisores/$sid.json" ]; then
  # Its Stop has its own synchronous entry (guard-sup.sh): an async hook cannot block the stop, so the "launch your
  # waiter" check only reached the supervisor as a loose note it ignored (claude-vzert, 2026-10-06, six times).
  # --async tells on_supervisor.py this is that entry; it reads the event name from the parsed JSON, not the text.
  via=""; [ "$1" = on_state.py ] && via="--async"
  printf '%s' "$input" | python3 "$(dirname "$0")/../bin/on_supervisor.py" $via
  exit 0  # an `exec` inside a pipeline only replaces the subshell: without this exit the executor path ran too
fi
[ -f "$root/sessions/$sid.json" ] || exit 0
printf '%s' "$input" | exec python3 "$(dirname "$0")/../bin/$1"

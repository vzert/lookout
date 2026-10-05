#!/bin/sh
# PreCompact of the supervisor's session (docs/plan.md 3.1, Fase 4): rewrite supervisor.md before the context is
# summarized. Only in the supervisor session: guard-sup.sh exits at once anywhere else.
exec sh "$(dirname "$0")/guard-sup.sh" on_supervisor.py

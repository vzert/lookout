"""Thin wrapper over the herdr CLI: every call has a timeout and never raises.

The herdr session is whatever HERDR_SOCKET_PATH points at (the caller pane's session),
so a supervisor and its agents running inside `herdr --session coord-test` talk to coord-test.
"""
import json
import os
import subprocess

HERDR = os.environ.get("HERDR_BIN_PATH") or "herdr"


def run(args, timeout=10):
    """Run `herdr <args>`; return (returncode, stdout, stderr). Never raises."""
    try:
        out = subprocess.run([HERDR] + list(args), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 124, "", str(exc)
    return out.returncode, out.stdout, out.stderr


def run_json(args, timeout=10):
    """Run a herdr command that prints JSON; return its `result` dict, or None."""
    code, out, _err = run(args, timeout)
    if code != 0:
        return None
    try:
        return json.loads(out).get("result")
    except ValueError:
        return None


def agent_list():
    res = run_json(["agent", "list"]) or {}
    return res.get("agents") or []


def agent_get(target):
    res = run_json(["agent", "get", target]) or {}
    return res.get("agent")


def tab_get(tab_id):
    """The tab as herdr shows it: label, number, pane_count. None on any failure."""
    if not tab_id:
        return None
    res = run_json(["tab", "get", tab_id]) or {}
    return res.get("tab")


def own_label(tab):
    """The tab's label when someone chose it; '' for herdr's default (the tab number) or no tab.

    A new herdr tab is labelled with its number ("1"); `herdr tab rename` or the UI replaces it (seen 2026-10-05:
    "Cambio DeepSeek" on tab 69, "1" on an untouched tab)."""
    if not tab:
        return ""
    label = str(tab.get("label") or "").strip()
    return "" if label in ("", str(tab.get("number", ""))) else label


def report_metadata(pane, estado, display=None, ttl_ms=3600000, timeout=3):
    """Display-only label on the pane (V3 plan B). Silent on any failure."""
    if not pane:
        return
    args = ["pane", "report-metadata", pane, "--source", "custom:lookout", "--agent", "claude",
            "--token", "estado=" + estado, "--ttl-ms", str(ttl_ms)]
    if display:
        args += ["--display-agent", display]
    run(args, timeout=timeout)

"""Shared state helpers for lookout hooks and scripts.

State root (docs/plan.md 3.2; fixed in phase 0, V2):
  LOOKOUT_STATE_DIR if set (tests), else ~/.local/state/lookout.
Layout:
  <root>/sessions/<session_id>.json            marker: this session is supervised
  <root>/projects/<project_id>/events.jsonl     one line per hook event (O_APPEND)
  <root>/projects/<project_id>/lock.json        project lock (one supervisor per project)
  <root>/projects/<project_id>/registry.json    registered agents, keyed by session_id
  <root>/projects/<project_id>/cursor.json      byte offset of the last handled event
  <root>/projects/<project_id>/waiter.pid       pid of the single live waiter
"""
import hashlib
import json
import os
import signal
import subprocess
import time


def state_root():
    env = os.environ.get("LOOKOUT_STATE_DIR")
    if env:
        return env
    return os.path.join(os.path.expanduser("~"), ".local", "state", "lookout")


def _safe_id(value):
    return bool(value) and "/" not in value and not value.startswith(".")


def project_dir(project_id):
    return os.path.join(state_root(), "projects", project_id)


def events_path(project_id):
    return os.path.join(project_dir(project_id), "events.jsonl")


# ---------- json files ----------

def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    """Atomic write: temp file in the same folder, then rename."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    os.replace(tmp, path)


# ---------- session markers ----------

def marker_path(session_id):
    return os.path.join(state_root(), "sessions", session_id + ".json")


def read_marker(session_id):
    """Return the marker dict for a supervised session, or None."""
    if not _safe_id(session_id):
        return None
    return read_json(marker_path(session_id))


def write_marker(session_id, data):
    """0.13.6: `direcciones` keeps every supervisor address the session had, the current one last (3-tier-memory
    2026-10-16: the supervisor moved from 2476.sock to 95700.sock and 3-tier's checkpoint-close-guard stopped counting
    the questions already sent to the old one). `address` stays the current one, as text."""
    if not _safe_id(session_id):
        raise ValueError("session_id inválido: %r" % session_id)
    data = dict(data)
    if "address" in data and not isinstance(data["address"], str):
        data["address"] = ""  # adversary r1 (codex): 3-tier reads a non-text address as unreadable and fails closed
    old = read_json(marker_path(session_id))
    old = old if isinstance(old, dict) else {}

    def lista(v):
        return list(v) if isinstance(v, list) else []  # a string would split into characters

    vistas = lista(data.get("direcciones"))
    if old.get("project_id") == data.get("project_id"):
        vistas = lista(old.get("direcciones")) + [old.get("address")] + vistas
    actual = data.get("address")
    vistas = [d for d in vistas if isinstance(d, str) and d.strip() and d != actual]
    if isinstance(actual, str) and actual.strip():
        vistas.append(actual)
    data["direcciones"] = list(dict.fromkeys(vistas))
    write_json(marker_path(session_id), data)


def remove_marker(session_id):
    if _safe_id(session_id):
        try:
            os.remove(marker_path(session_id))
        except OSError:
            pass


# ---------- events ----------

def append_event(project_id, event):
    """Append one JSON line to the project's events.jsonl and return its path."""
    path = events_path(project_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    event = dict(event)
    event.setdefault("ts", time.time())
    line = (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)
    return path


def read_events(project_id, offset=0):
    """Return (events, end_offset) for the lines after byte `offset`."""
    path = events_path(project_id)
    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            data = fh.read()
    except OSError:
        return [], offset
    end = offset + data.rfind(b"\n") + 1 if b"\n" in data else offset
    events = []
    for raw in data[: end - offset].splitlines():
        try:
            events.append(json.loads(raw))
        except ValueError:
            continue
    return events, end


# 0.12.1: `tail -F` never ends by itself (it waits for the file to come back), so a waiter or a delivery killed with
# SIGKILL, where no `finally` runs, left it alive forever: Will-Ops found 1,483 of them (PPID 1, up to 12 days old),
# most from test runs that kill their waiters. The tail now runs under a small sh guard in its own process group. The
# guard blocks reading its stdin, a pipe whose only write end is held by the process that called `sigue` (Popen's
# close_fds keeps it out of every other child). When that process ends, however it ends, the kernel closes the write
# end, the guard's read returns and it kills the tail. No `ps`, no polling, no pid to be reused (adversary 0.12.1,
# rounds 1-2: reading the parent with `ps` failed where `ps` is missing, and `kill -0 <pid>` trusts a reused pid).
# `deja_de_seguir` kills the whole group on a normal end. The tail itself (an async command of a non-interactive sh:
# its stdin is /dev/null) still writes straight to our stdout pipe: the kernel wakes the reader on each line.
_GUARDIA = ('"$@" & t=$!; trap \'kill $t 2>/dev/null; exit 0\' TERM HUP INT; '
            'while read -r _; do :; done; '
            'kill "$t" 2>/dev/null')


def sigue(path, offset=0):
    """A `tail -c +N -F path` that dies with the process that called this. Its stdout is the lines after `offset`.
    Keep the returned object (its stdin is the guard's lifeline) until `deja_de_seguir`."""
    return subprocess.Popen(["sh", "-c", _GUARDIA, "lookout-tail", "tail", "-c", "+%d" % (offset + 1), "-F", path],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                            start_new_session=True)


def deja_de_seguir(proc):
    """Kill the guard and its tail (one process group). Safe to call twice, also from a signal handler."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


# ---------- projects ----------

def git_common_dir(path):
    """Absolute git common dir for `path` (main repo and its worktrees share it), or None."""
    try:
        out = subprocess.run(
            ["git", "-C", path, "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return os.path.realpath(out.stdout.strip())


def project_id_for(common_dir):
    return hashlib.sha1(common_dir.encode("utf-8")).hexdigest()[:12]


def worktree_roots(path):
    """Top-level paths of the main checkout and every worktree of the repo at `path`."""
    try:
        out = subprocess.run(["git", "-C", path, "worktree", "list", "--porcelain"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    roots = []
    for line in out.stdout.splitlines():
        if line.startswith("worktree "):
            roots.append(os.path.realpath(line[len("worktree "):]))
    return roots


def list_locks():
    """Every project lock on this machine: [(project_id, lock_dict)]."""
    base = os.path.join(state_root(), "projects")
    try:
        names = os.listdir(base)
    except OSError:
        return []
    locks = []
    for name in names:
        lock = read_json(os.path.join(base, name, "lock.json"))
        if lock:
            locks.append((name, lock))
    return locks


def project_of_path(path, locks=None):
    """project_id whose lock roots contain `path` (longest root wins), or None."""
    real = os.path.realpath(path)
    best, best_len = None, -1
    for pid, lock in (locks if locks is not None else list_locks()):
        for root in lock.get("roots", []):
            if (real == root or real.startswith(root.rstrip("/") + "/")) and len(root) > best_len:
                best, best_len = pid, len(root)
    return best


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True

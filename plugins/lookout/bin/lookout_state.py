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
    if not _safe_id(session_id):
        raise ValueError("session_id inválido: %r" % session_id)
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

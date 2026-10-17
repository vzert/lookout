#!/usr/bin/env python3
"""0.13.11 (p-fce98427a8): a vigía keeps the alta and the sweep going while the supervisor's modal is open.

AskUserQuestion holds the supervisor's turn until the user answers, and only its waiter's checker thread
(wait_event.revisor) ran the alta and the sweep. 3-tier-memory, 2026-10-16: the waiter launched before the modal woke at
once on 11 events of the turn and exited; nobody relaunched it, and the project went 65 min with no alta and no sweep.

The supervisor's PreToolUse[AskUserQuestion] hook (on_supervisor.py) writes modal.json and starts this process, detached
from the hook (its own session, no stdio: a child holding the hook's stdout would hold the hook until its timeout).
Every LOOKOUT_REVISA_CADA s, while no waiter of the supervisor is alive, it runs the waiter's checker pass. It never takes
the waiter's pidfile: the Stop check would count it as a waiter, and nothing wakes the supervisor when it exits.
It leaves when modal.json goes (the answer, a failed modal, a prompt, a Stop or a SessionStart of the supervisor remove
it), names another session, its supervisor no longer supervises (wait_event.owner_stale), or after LOOKOUT_VIGIA_HORAS.
What a pass finds goes to events.jsonl, as from the waiter; the supervisor reads it when the modal ends.
Usage: vigia.py <project_id>
"""
import contextlib
import fcntl
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lookout_state  # noqa: E402


def modal_path(project_id):
    return os.path.join(lookout_state.project_dir(project_id), "modal.json")


def pidfile(project_id):
    return os.path.join(lookout_state.project_dir(project_id), "vigia.pid")


def cada():
    """Seconds between two looks at modal.json and the supervisor."""
    try:
        return max(0.1, float(os.environ.get("LOOKOUT_VIGIA_CADA") or 2))
    except ValueError:
        return 2.0


def tope_s():
    try:
        return float(os.environ.get("LOOKOUT_VIGIA_HORAS") or 12) * 3600
    except ValueError:
        return 12 * 3600.0


@contextlib.contextmanager
def pasada_exclusiva(project_id):
    """One checker pass at a time per project, across processes (the waiter's thread and a vigía): yields False when
    another pass runs, and the caller skips its own instead of queueing behind it."""
    os.makedirs(lookout_state.project_dir(project_id), exist_ok=True)
    fd = os.open(os.path.join(lookout_state.project_dir(project_id), "revisor.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def revisa(project_id):
    """The checker pass (Fase 6 no-progress check; 0.13.0 alta; 0.13.2 sweep). A failed step never stops the caller."""
    import alta
    import heuristicas
    with pasada_exclusiva(project_id) as mia:
        if not mia:
            return
        try:
            if heuristicas.alguien_callado(project_id):
                heuristicas.revisa(project_id)
        except Exception:
            pass
        try:
            if alta.toca(project_id):
                alta.pasada(project_id)
        except Exception:
            pass


@contextlib.contextmanager
def _marca(project_id):
    """modal.json is read and changed under this flock: a late answer of an older modal read its mark, a new modal
    wrote its own, and the late answer then unlinked the new one (adversary r1, codex)."""
    os.makedirs(lookout_state.project_dir(project_id), exist_ok=True)
    fd = os.open(os.path.join(lookout_state.project_dir(project_id), "modal.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def abre(project_id, session_id, tool_use_id):
    """From the supervisor's PreToolUse[AskUserQuestion]: mark the modal open and start a vigía (a second one, while one
    runs, exits by itself: the running one watches whichever modal is open now)."""
    with _marca(project_id):
        lookout_state.write_json(modal_path(project_id), {"session_id": session_id, "tool_use_id": tool_use_id,
                                                          "desde": time.time()})
    subprocess.Popen([sys.executable, os.path.abspath(__file__), project_id], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)


def cierra(project_id, tool_use_id=None):
    """The modal ended. With a tool_use_id, only that modal's mark goes: a late answer of an older one leaves the open
    one watched."""
    path = modal_path(project_id)
    with _marca(project_id):
        m = lookout_state.read_json(path)
        if not m or (tool_use_id and m.get("tool_use_id") != tool_use_id):
            return
        try:
            os.unlink(path)
        except OSError:
            pass


def _claim(path, espera):
    """The vigía's own pidfile, held with flock for its whole life. A vigía still running for an older modal leaves
    within cada() if that modal's session no longer supervises; wait that long before giving up."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    fin = time.time() + espera
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.time() >= fin:
                os.close(fd)
                return None
            time.sleep(0.2)
    os.ftruncate(fd, 0)
    os.write(fd, ("%d\n" % os.getpid()).encode())
    return fd


def _waiter_vivo(project_id):
    import digest
    return digest.waiter_alive(project_id) > 0 and not digest.waiter_owner_dead(project_id)


def vigila(project_id):
    import heuristicas
    import wait_event
    os.makedirs(lookout_state.project_dir(project_id), exist_ok=True)
    m = lookout_state.read_json(modal_path(project_id)) or {}
    owner = {"claude_pid": int(os.environ.get("CLAUDE_PID", "0") or 0), "session_id": m.get("session_id", "")}
    if not owner["session_id"]:
        return 0
    lock_path = os.path.join(lookout_state.project_dir(project_id), "lock.json")
    # an older vigía in the middle of a pass (herdr calls) only looks at modal.json after it: wait out a whole pass
    fd = _claim(pidfile(project_id), 3 * cada() + wait_event.WATCH_EVERY + wait_event.pass_budget(project_id))
    if fd is None:
        return 0  # a vigía is already watching
    inicio = time.time()
    proxima = inicio + heuristicas.revisa_cada()
    try:
        while time.time() - inicio < tope_s():
            m = lookout_state.read_json(modal_path(project_id)) or {}
            if m.get("session_id") != owner["session_id"] or wait_event.owner_stale(owner, lock_path):
                return 0
            if time.time() >= proxima:
                if not _waiter_vivo(project_id):
                    revisa(project_id)
                proxima = time.time() + heuristicas.revisa_cada()
            time.sleep(min(cada(), max(0.05, proxima - time.time())))
    finally:
        os.close(fd)
    return 0


def main():
    if len(sys.argv) != 2 or not lookout_state._safe_id(sys.argv[1]):
        return 2
    try:
        return vigila(sys.argv[1])
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())

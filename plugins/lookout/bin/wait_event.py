#!/usr/bin/env python3
"""Single waiter of a supervisor (docs/plan.md 3.5, V5): block until an UNHANDLED event exists.

It reads events.jsonl from the project's cursor (the byte offset `digest` advanced to), so an
event that arrived while the supervisor was busy wakes it at once instead of being missed.
No polling loop of our own: `tail -c +N -F` blocks in the kernel and hands us each new line.
A pidfile keeps one waiter per project; a second one exits at once and says so.

With --cursor, an event the supervisor already handled after this waiter started (its byte
offset is at or below the cursor) is skipped, so a SendMessage wake does not cost a second wake.

Usage: wait_event.py <events.jsonl> [--offset N] [--types a,b] [--timeout S] [--pidfile F] [--cursor F]
Exit 0 with the first matching line on stdout; 2 on timeout; 3 if another waiter is alive.
"""
import argparse
import fcntl
import json
import os
import signal
import subprocess
import time
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lookout_state  # noqa: E402


_LOCK_FD = None
_REVISANDO = None  # held by the no-progress check during one pass (Fase 6); the waiter waits for it before exiting


def owner_stale(owner, lock_path):
    """True when the session that launched a waiter no longer supervises: its Claude process is gone, or the
    project's lock (lock.json next to the pidfile) is gone or names another session (/clear, a relief)."""
    if not owner or not owner.get("claude_pid"):
        return False
    if not lookout_state.pid_alive(owner.get("claude_pid")):
        return True
    sup = ((lookout_state.read_json(lock_path) or {}).get("supervisor") or {})
    return sup.get("session_id") != owner.get("session_id")


def claim_pidfile(path, wait_stale=0.0):
    """Hold an exclusive flock on the pidfile for the waiter's whole life (adversary rounds 1-2,
    2026-10-02). The kernel releases it if the process dies, so a stale file needs no cleanup and
    two waiters started at once, or both finding a dead pid, cannot both win."""
    global _LOCK_FD
    if not path:
        return True
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.time() + wait_stale
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            # The holder belongs to a session that no longer supervises: it exits by itself (watchdog below), so
            # wait for its lock instead of killing it (no pid can be signalled by mistake; adversary F4 round 2).
            old_owner = lookout_state.read_json(path + ".owner") or {}
            lock_path = os.path.join(os.path.dirname(os.path.abspath(path)), "lock.json")
            if time.time() < deadline and owner_stale(old_owner, lock_path):
                time.sleep(0.5)
                continue
            os.close(fd)
            return False
    os.ftruncate(fd, 0)
    os.write(fd, ("%d\n" % os.getpid()).encode())  # the newline marks a complete write
    _LOCK_FD = fd
    return True


def drop_pidfile(path):
    global _LOCK_FD
    if not path or _LOCK_FD is None:
        return
    # Never unlink the pidfile: a waiter that opened this inode just before an unlink would lock a
    # file nobody else sees (adversary round 3). Closing the fd releases the flock; that is all.
    os.close(_LOCK_FD)
    _LOCK_FD = None


def handled_offset(cursor):
    if not cursor:
        return -1
    data = lookout_state.read_json(cursor) or {}
    try:
        return int(data.get("offset", -1))
    except (TypeError, ValueError):
        return -1


def owner_path(pidfile):
    return pidfile + ".owner"


def short(event):
    """One short line for the task notification: it lands in the supervisor's context (Fase 4 budget)."""
    try:
        import digest
        text = digest.describe(event)
    except Exception:
        text = "%s %s" % (event.get("event"), event.get("nombre") or event.get("session_id", "")[:8])
    text = " ".join(text.split())
    return "evento: %s → corre lookout resumen\n" % (text if len(text) <= 160 else text[:159] + "…")


WATCH_EVERY = float(os.environ.get("LOOKOUT_WATCH_EVERY") or 10.0)  # s between checks that its supervisor still supervises


def watchdog(owner, lock_path, stop, every=WATCH_EVERY):
    """Exit the waiter when its supervisor session is gone (killed, /clear, relieved, `lookout suelta`): an orphan
    must neither block the next supervisor's waiter nor need anyone to signal it."""
    while True:
        time.sleep(every)
        if owner_stale(owner, lock_path):
            print("waiter: la sesión que lo lanzó ya no supervisa; salgo")
            sys.stdout.flush()
            stop(4)


def revisor(project_id, every):
    """Fase 6: the no-progress check (heuristicas.revisa), a script on a timer inside the single waiter, so the
    supervisor itself never polls. Only does work while some agent's hooks went quiet; what it decides is appended to
    events.jsonl, where the tail below picks it up like any other event."""
    import heuristicas
    while True:
        time.sleep(every)
        with _REVISANDO:
            try:
                if heuristicas.alguien_callado(project_id):
                    heuristicas.revisa(project_id)
            except Exception:
                pass  # a failed check must never take the waiter down


def pass_budget(project_id):
    """Seconds one check pass may take: 30 s plus 30 s per registered agent (herdr's agent list 10 s once; per agent ps
    and git 5 s each, the notification 3 s, and the brief counters.lock waits of hooks that only do file I/O)."""
    try:
        import registry
        n = len(registry.load(project_id).get("agents") or {})
    except Exception:
        n = 10
    return 30.0 + 30.0 * max(n, 1)


def end_of_pass(timeout=120.0):
    """The check appends its event and THEN updates the grouped view and notifies (heuristicas.transicion). The tail
    wakes on the event at once: without this, the waiter exited and killed the check's thread before that second half
    (Fase 6 run 2: the frozen control never reached "te necesita"). The bound is pass_budget(): every external call in a
    pass has its own timeout. Past it the waiter exits anyway: the supervisor is still woken and `resumen` recomputes the
    groups from events.jsonl; only that pass's grupos.json update and notification can be lost."""
    if _REVISANDO is not None and _REVISANDO.acquire(timeout=timeout):
        _REVISANDO.release()


def wait(path, offset=0, types="", timeout=0, pidfile="", cursor="", owner=None, wait_stale=25.0, revisa=None):
    wanted = {t for t in types.split(",") if t}
    if not claim_pidfile(pidfile, wait_stale if owner else 0.0):
        print("waiter ya vivo (pidfile %s): no lances otro" % pidfile)
        return 3
    if pidfile and owner:
        # Who launched this waiter (Claude pid + session): a relief must tell an orphan of a dead supervisor from a
        # live one, or the new supervisor is told "waiter vivo" and is never woken (Fase 4).
        lookout_state.write_json(owner_path(pidfile), dict(owner, waiter_pid=os.getpid()))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    open(path, "a").close()
    tail = subprocess.Popen(["tail", "-c", "+%d" % (offset + 1), "-F", path],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    def stop(code):
        tail.kill()
        drop_pidfile(pidfile)
        sys.exit(code)

    signal.signal(signal.SIGTERM, lambda _s, _f: stop(143))
    if pidfile and owner and owner.get("claude_pid"):
        import threading

        def quit_now(code):
            tail.kill()
            drop_pidfile(pidfile)
            os._exit(code)  # from a thread: sys.exit would only end the thread
        lock_path = os.path.join(os.path.dirname(os.path.abspath(pidfile)), "lock.json")
        threading.Thread(target=watchdog, args=(owner, lock_path, quit_now), daemon=True).start()
    if revisa:
        import threading
        import heuristicas
        global _REVISANDO
        _REVISANDO = threading.Lock()
        threading.Thread(target=revisor, args=(revisa, heuristicas.revisa_cada()), daemon=True).start()
    if timeout:
        def on_alarm(_s, _f):
            print("timeout del waiter: sin eventos; relánzalo")
            sys.stdout.flush()
            stop(2)
        signal.signal(signal.SIGALRM, on_alarm)
        signal.setitimer(signal.ITIMER_REAL, timeout)
    pos = offset
    try:
        for line in tail.stdout:
            pos += len(line.encode("utf-8"))
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if wanted and event.get("event") not in wanted:
                continue
            if event.get("event") == "idle" and event.get("reporto"):
                continue  # its report already woke the supervisor by SendMessage (Fase 4)
            if pos <= handled_offset(cursor):
                continue
            end_of_pass(pass_budget(revisa) if revisa else 0)
            sys.stdout.write(short(event))
            sys.stdout.flush()
            return 0
    finally:
        tail.kill()
        drop_pidfile(pidfile)
    return 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--offset", type=int, default=-1, help="byte offset; -1 = end of file")
    ap.add_argument("--types", default="")
    ap.add_argument("--timeout", type=float, default=0)
    ap.add_argument("--pidfile", default="")
    ap.add_argument("--cursor", default="")
    a = ap.parse_args()
    offset = a.offset
    if offset < 0:
        try:
            offset = os.path.getsize(a.path)
        except OSError:
            offset = 0
    return wait(a.path, offset, a.types, a.timeout, a.pidfile, a.cursor)


if __name__ == "__main__":
    sys.exit(main())

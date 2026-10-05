"""One dev-server port per worktree (docs/plan.md, Fase 6): two worktrees never start a server on the same port.

The assignment lives in <state>/ports.json, machine-wide (two projects can run at once), under a flock. A worktree
keeps its port for its whole life (a relieved agent gets the same one); a port is given only if nothing else is
assigned to it and it can be bound on 127.0.0.1 right now. The agent gets it twice: as $PORT in its environment
(the --settings env of its Claude session) and written in its task prompt.

LOOKOUT_PORT_BASE (default 4100) and LOOKOUT_PORT_SPAN (default 400) bound the range.
"""
import fcntl
import os
import socket

import lookout_state


def base():
    try:
        return int(os.environ.get("LOOKOUT_PORT_BASE") or 4100)
    except ValueError:
        return 4100


def span():
    try:
        return int(os.environ.get("LOOKOUT_PORT_SPAN") or 400)
    except ValueError:
        return 400


def path():
    return os.path.join(lookout_state.state_root(), "ports.json")


def libre(port):
    """True when nothing listens on 127.0.0.1:port and it can be bound now."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False  # in use, or not ours to bind: never hand it out
    finally:
        s.close()


class _lock(object):
    def __enter__(self):
        os.makedirs(os.path.dirname(path()), exist_ok=True)
        self.fd = os.open(path() + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)


def asigna(worktree, probe=libre):
    """The worktree's port: the one it already has, else the lowest free one in the range. None if none is free."""
    key = os.path.realpath(worktree)
    with _lock():
        data = lookout_state.read_json(path()) or {}
        asignados = data.setdefault("asignados", {})
        if key in asignados:
            return asignados[key]
        taken = set(asignados.values())
        for port in range(base(), base() + span()):
            if port in taken or not probe(port):
                continue
            asignados[key] = port
            lookout_state.write_json(path(), data)
            return port
    return None


def de(worktree):
    data = lookout_state.read_json(path()) or {}
    return (data.get("asignados") or {}).get(os.path.realpath(worktree))


def libera(worktree):
    key = os.path.realpath(worktree)
    with _lock():
        data = lookout_state.read_json(path()) or {}
        port = (data.get("asignados") or {}).pop(key, None)
        if port is not None:
            lookout_state.write_json(path(), data)
        return port


def slug(worktree):
    """Suffix for per-worktree resources (database names, caches): the worktree folder's name, letters/digits/_ only."""
    import re
    return re.sub(r"[^A-Za-z0-9_]", "_", os.path.basename(os.path.realpath(worktree)))[:40]

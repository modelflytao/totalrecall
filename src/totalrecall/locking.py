from __future__ import annotations
from contextlib import contextmanager
from filelock import FileLock, Timeout
from . import paths


@contextmanager
def try_worker_lock():
    """Yield True if we acquired the singleton worker lock, else False."""
    paths.ensure_dirs()
    lock = FileLock(str(paths.state_dir() / "worker.lock"))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        yield False
        return
    try:
        yield True
    finally:
        lock.release()

from __future__ import annotations
import hashlib
from pathlib import Path
from . import paths
from .locking import try_worker_lock

worker_lock = try_worker_lock


def _name_for(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8")).hexdigest() + ".job"


def enqueue(transcript_path: str) -> None:
    paths.ensure_dirs()
    job = paths.queue_dir() / _name_for(transcript_path)
    if not job.exists():
        job.write_text(transcript_path, encoding="utf-8")


def size() -> int:
    return len(list(paths.queue_dir().glob("*.job"))) if paths.queue_dir().exists() else 0


def drain() -> list[str]:
    """Return queued paths (FIFO by mtime) and remove their job files.

    NOT crash-safe (removes all jobs before they are processed). The worker uses
    claim_next()/complete() instead; drain() is kept for simple/batch callers.
    """
    if not paths.queue_dir().exists():
        return []
    jobs = sorted(paths.queue_dir().glob("*.job"), key=lambda p: p.stat().st_mtime)
    out = []
    for j in jobs:
        out.append(j.read_text(encoding="utf-8"))
        j.unlink()
    return out


def claim_next():
    """Return (job_file, transcript_path) for the oldest job WITHOUT deleting it,
    or None if the queue is empty. Caller MUST call complete(job_file) only after
    the work is durably recorded. Crash-safe: if the worker dies mid-process, the
    job file remains and is re-processed on the next run (idempotent via the ledger)."""
    if not paths.queue_dir().exists():
        return None
    jobs = sorted(paths.queue_dir().glob("*.job"), key=lambda p: p.stat().st_mtime)
    for j in jobs:
        try:
            return (j, j.read_text(encoding="utf-8"))
        except OSError:
            continue
    return None


def complete(job_file) -> None:
    """Remove a claimed job file after its work is durably recorded."""
    try:
        Path(job_file).unlink()
    except OSError:
        pass

from __future__ import annotations
import hashlib
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
    """Return queued paths (FIFO by mtime) and remove their job files."""
    if not paths.queue_dir().exists():
        return []
    jobs = sorted(paths.queue_dir().glob("*.job"), key=lambda p: p.stat().st_mtime)
    out = []
    for j in jobs:
        out.append(j.read_text(encoding="utf-8"))
        j.unlink()
    return out

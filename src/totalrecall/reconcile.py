from __future__ import annotations
from pathlib import Path
from . import ledger, queue


def claude_projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def run() -> int:
    """Enqueue transcripts newer than the ledger. Returns count enqueued."""
    root = claude_projects_dir()
    if not root.exists():
        return 0
    lg = ledger.Ledger.load()
    done = lg.done_paths()
    count = 0
    for jsonl in root.rglob("*.jsonl"):
        norm = str(jsonl).replace("\\", "/")
        if "/analysis/" in norm:           # exclude self-produced analysis sessions
            continue
        if str(jsonl) in done:
            continue
        if not lg.is_new(jsonl):
            continue
        queue.enqueue(str(jsonl))
        count += 1
    return count

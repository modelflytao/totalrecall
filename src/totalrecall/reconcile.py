from __future__ import annotations
import re
from pathlib import Path
from . import ledger, queue, paths


def claude_projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def _encoded_analysis_dir() -> str:
    # Claude Code encodes a cwd into a project dir name by replacing ':' '\\' '/'
    # AND '.' with '-' (e.g. C:\\Users\\u\\.totalrecall\\analysis ->
    # C--Users-u--totalrecall-analysis -- note '.totalrecall' -> '-totalrecall').
    return re.sub(r"[:/\\.]", "-", str(paths.analysis_cwd()))


def run() -> int:
    """Enqueue transcripts newer than the ledger. Returns count enqueued.

    Recursion safety is guaranteed by the worker/adapter (is_analysis_session);
    this dir-name skip is best-effort defense-in-depth.
    """
    root = claude_projects_dir()
    if not root.exists():
        return 0
    lg = ledger.Ledger.load()
    done = lg.done_paths()
    analysis_dir = _encoded_analysis_dir()
    count = 0
    for jsonl in root.rglob("*.jsonl"):
        if jsonl.parent.name == analysis_dir:
            continue
        if str(jsonl) in done:
            continue
        if not lg.is_new(jsonl):
            continue
        queue.enqueue(str(jsonl))
        count += 1
    return count

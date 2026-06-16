from __future__ import annotations
import re
import time
from pathlib import Path
from . import ledger, queue, paths

RECENT_SECONDS = 120  # transcripts touched this recently are likely in-progress sessions


def claude_projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def _encoded_analysis_dir() -> str:
    # Claude Code encodes a cwd into a project dir name by replacing ':' '\\' '/'
    # AND '.' with '-' (e.g. C:\\Users\\u\\.totalrecall\\analysis ->
    # C--Users-u--totalrecall-analysis -- note '.totalrecall' -> '-totalrecall').
    return re.sub(r"[:/\\.]", "-", str(paths.analysis_cwd()))


def run(recent_seconds: int = RECENT_SECONDS) -> int:
    """Enqueue settled transcripts newer than the ledger. Returns count enqueued.

    Skips in-progress sessions (modified within recent_seconds) so a live, growing
    transcript is not re-analyzed over and over (the SessionEnd hook enqueues a
    session directly once it has ended). Recursion safety is the worker/adapter's
    is_analysis_session check; the dir-name skip is best-effort defense-in-depth.
    """
    root = claude_projects_dir()
    if not root.exists():
        return 0
    lg = ledger.Ledger.load()
    done = lg.done_paths()
    analysis_dir = _encoded_analysis_dir()
    now = time.time()
    count = 0
    for jsonl in root.rglob("*.jsonl"):
        if jsonl.parent.name == analysis_dir:
            continue
        try:
            if now - jsonl.stat().st_mtime < recent_seconds:
                continue   # in-progress; let it settle
        except OSError:
            continue
        if str(jsonl) in done:
            continue
        if not lg.is_new(jsonl):
            continue
        queue.enqueue(str(jsonl))
        count += 1
    return count

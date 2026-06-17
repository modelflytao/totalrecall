from __future__ import annotations
import re
import time
from pathlib import Path
from . import ledger, queue, paths, config

RECENT_SECONDS = 120  # transcripts touched this recently are likely in-progress sessions


def claude_projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def codex_sessions_dir() -> Path:
    return Path.home() / ".codex" / "sessions"


def _encoded_analysis_dir() -> str:
    # Claude Code encodes a cwd into a project dir name by replacing ':' '\\' '/'
    # AND '.' with '-' (e.g. C:\\Users\\u\\.totalrecall\\analysis ->
    # C--Users-u--totalrecall-analysis -- note '.totalrecall' -> '-totalrecall').
    return re.sub(r"[:/\\.]", "-", str(paths.analysis_cwd()))


def run(recent_seconds: int = RECENT_SECONDS) -> int:
    """Enqueue settled transcripts newer than the ledger, across enabled sources."""
    cfg = config.load()
    lg = ledger.Ledger.load()
    done = lg.done_paths()
    now = time.time()
    count = 0

    sources = []
    if cfg.sources.get("claude_code"):
        sources.append((claude_projects_dir(), _encoded_analysis_dir()))
    if cfg.sources.get("codex"):
        sources.append((codex_sessions_dir(), None))   # codex sessions are never analysis sessions

    for root, analysis_dir in sources:
        if not root.exists():
            continue
        for jsonl in root.rglob("*.jsonl"):
            if analysis_dir and jsonl.parent.name == analysis_dir:
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

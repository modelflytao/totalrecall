from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from . import (queue, ledger, config, catalog, merger, render, reconcile,
               orchestrator, paths, synth)
from .adapters.claude_code import ClaudeCodeAdapter
from .events import extract_events
from .locking import try_worker_lock

_ADAPTER = ClaudeCodeAdapter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _count_projects(lg: ledger.Ledger) -> int:
    return len({str(Path(p).parent) for p in lg.done_paths()})


def process_path(path: str, cfg: config.Config) -> bool:
    """Process one transcript. Returns True if it produced an analysis."""
    lg = ledger.Ledger.load()
    p = Path(path)
    if not p.exists() or not lg.is_new(p):
        return False
    session = _ADAPTER.parse(p)
    if session.is_analysis_session:                 # ingest-layer self-exclusion
        lg.mark_done(session.session_id or path, p); lg.save()
        return False
    extract_events(session)
    cat = catalog.build(cfg.catalog_topk, _now())
    try:
        findings = orchestrator.analyze(session, cat, cfg.extract_model)
    except Exception:
        lg.mark_pending(session.session_id or path, str(p)); lg.save()
        return False
    merger.merge(findings, now=(session.ended_at or _now().isoformat()))
    lg.mark_done(session.session_id or path, p); lg.save()
    return True


def run_once() -> None:
    cfg = config.load()
    for path in queue.drain():
        process_path(path, cfg)
    _refresh(cfg)


def _refresh(cfg: config.Config) -> None:
    lg = ledger.Ledger.load()
    render.write(_now(), n_sessions=len(lg.done_paths()), n_projects=_count_projects(lg))


def run() -> str:
    with try_worker_lock() as got:
        if not got:
            return "busy"
        cfg = config.load()
        before = len(ledger.Ledger.load().done_paths())
        reconcile.run()
        # drain-loop: keep going until the queue is truly empty before releasing the lock
        while True:
            batch = queue.drain()
            if not batch:
                break
            for path in batch:
                process_path(path, cfg)
        _refresh(cfg)
        after = len(ledger.Ledger.load().done_paths())
        n = cfg.synth_every_n_sessions
        if n > 0 and after // n > before // n:   # crossed a multiple of N cumulatively
            synth.run(cfg)
        return "done"

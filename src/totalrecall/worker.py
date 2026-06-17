from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from . import (queue, ledger, config, catalog, merger, render, reconcile,
               orchestrator, paths, synth, adapters)
from .locking import try_worker_lock


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
    session = adapters.for_path(p).parse(p)
    if session.is_analysis_session:                 # ingest-layer self-exclusion
        lg.mark_done(session.session_id or path, p); lg.save()
        return False
    cat = catalog.build(cfg.catalog_topk, _now())
    try:
        findings = orchestrator.analyze(session, cat, cfg.extract_model,
                                        max_input_tokens=cfg.max_input_tokens)
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
        reconcile.run()
        analyzed = 0
        # crash-safe loop: claim one job, process, then delete it. If the worker is
        # killed (machine sleep/crash) mid-session, the job file remains and is
        # re-processed on the next run (idempotent via the ledger) -- no bulk re-work.
        while True:
            job = queue.claim_next()
            if job is None:
                break
            job_file, path = job
            if process_path(path, cfg):
                analyzed += 1
                # periodic synth keeps the pattern library consolidated AND small
                # enough that the synth prompt never times out.
                if cfg.synth_every_n_sessions > 0 and analyzed % cfg.synth_every_n_sessions == 0:
                    try:
                        synth.run(cfg)          # consolidation failure must not abort the backfill
                    except Exception:
                        pass
                    _refresh(cfg)
            queue.complete(job_file)
        _refresh(cfg)
        return "done"

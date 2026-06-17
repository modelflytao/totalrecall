from __future__ import annotations
import argparse
import sys
from . import (hookinstall, worker, reconcile, synth, config, ledger,
               patterns_store, hookcmd, queue, proposer, applier, proposals_store)


def _cmd_status() -> int:
    lg = ledger.Ledger.load()
    print(f"sessions: {len(lg.done_paths())}")
    print(f"patterns: {len(patterns_store.all())}")
    print(f"pending: {len(lg.pending_items())}")
    return 0


def _cmd_retry() -> int:
    cfg = config.load()
    with worker.try_worker_lock() as got:
        if not got:
            print("worker busy; pending items will be retried by the running worker")
            return 0
        lg = ledger.Ledger.load()
        for _sid, path in lg.pending_items():
            worker.process_path(path, cfg)
    return 0


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _cmd_proposals() -> int:
    for p in proposals_store.all():
        print(f"{p.id}\t{p.status}\t{p.pattern_id}")
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="totalrecall")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p_ingest = sub.add_parser("ingest"); p_ingest.add_argument("path")
    sub.add_parser("worker")
    sub.add_parser("reconcile")
    sub.add_parser("synth")
    sub.add_parser("status")
    sub.add_parser("retry")
    sub.add_parser("hook")
    sub.add_parser("propose")
    p_apply = sub.add_parser("apply"); p_apply.add_argument("ids", nargs="+")
    p_reject = sub.add_parser("reject"); p_reject.add_argument("ids", nargs="+")
    sub.add_parser("proposals")
    args = parser.parse_args(argv)

    if args.cmd == "init":
        hookinstall.init(); print("TotalRecall initialized."); return 0
    if args.cmd == "ingest":
        cfg = config.load()
        with worker.try_worker_lock() as got:
            if got:
                worker.process_path(args.path, cfg)
                worker._refresh(cfg)
            else:
                queue.enqueue(args.path)
        return 0
    if args.cmd == "worker":
        worker.run(); return 0
    if args.cmd == "reconcile":
        n = reconcile.run(); print(f"enqueued: {n}"); return 0
    if args.cmd == "synth":
        synth.run(config.load()); return 0
    if args.cmd == "status":
        return _cmd_status()
    if args.cmd == "retry":
        return _cmd_retry()
    if args.cmd == "hook":
        return hookcmd.main()
    if args.cmd == "propose":
        cfg = config.load()
        n = proposer.propose(top_n=cfg.propose_top_n, min_occ=cfg.propose_min_occ,
                             now=_now(), model=cfg.synth_model)
        print(f"drafted: {n}  ->  review ~/.totalrecall/proposals.md")
        return 0
    if args.cmd == "apply":
        try:
            n = applier.apply(args.ids, config.load(), now=_now())
        except RuntimeError as e:
            print(str(e)); return 1
        print(f"applied: {n}"); return 0
    if args.cmd == "reject":
        print(f"rejected: {applier.reject(args.ids)}"); return 0
    if args.cmd == "proposals":
        return _cmd_proposals()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

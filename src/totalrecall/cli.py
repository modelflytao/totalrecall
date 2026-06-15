from __future__ import annotations
import argparse
import sys
from . import (hookinstall, worker, reconcile, synth, config, ledger,
               patterns_store, hookcmd)


def _cmd_status() -> int:
    lg = ledger.Ledger.load()
    print(f"sessions: {len(lg.done_paths())}")
    print(f"patterns: {len(patterns_store.all())}")
    print(f"pending: {len(lg.pending_items())}")
    return 0


def _cmd_retry() -> int:
    cfg = config.load()
    lg = ledger.Ledger.load()
    for _sid, path in lg.pending_items():
        worker.process_path(path, cfg)
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
    args = parser.parse_args(argv)

    if args.cmd == "init":
        hookinstall.init(); print("TotalRecall initialized."); return 0
    if args.cmd == "ingest":
        worker.process_path(args.path, config.load()); return 0
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
    return 1

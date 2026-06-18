from totalrecall import worker, paths

def test_sync_called_first_run_ok_false_when_enabled(home, monkeypatch):
    paths.ensure_dirs()
    paths.config_path().write_text("[sources]\nopencode = true\n", encoding="utf-8")
    seen = {"first_run_ok": None, "n": 0}
    def fake_sync(first_run_ok=True):
        seen["first_run_ok"] = first_run_ok; seen["n"] += 1; return 0
    monkeypatch.setattr(worker.opencode_export, "sync", fake_sync)
    monkeypatch.setattr(worker.reconcile, "run", lambda: 0)
    worker.run()
    assert seen["n"] == 1
    assert seen["first_run_ok"] is False   # worker must NOT do the cold backfill (HOLE B)

def test_sync_skipped_when_disabled(home, monkeypatch):
    paths.ensure_dirs()   # default: opencode = false
    called = {"n": 0}
    monkeypatch.setattr(worker.opencode_export, "sync",
                        lambda first_run_ok=True: called.__setitem__("n", called["n"] + 1))
    monkeypatch.setattr(worker.reconcile, "run", lambda: 0)
    worker.run()
    assert called["n"] == 0

def test_sync_failure_does_not_abort_worker(home, monkeypatch):
    paths.ensure_dirs()
    paths.config_path().write_text("[sources]\nopencode = true\n", encoding="utf-8")
    def boom(first_run_ok=True):
        raise RuntimeError("db locked")
    monkeypatch.setattr(worker.opencode_export, "sync", boom)
    monkeypatch.setattr(worker.reconcile, "run", lambda: 0)
    assert worker.run() == "done"     # silent-fail; worker completes

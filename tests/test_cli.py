from totalrecall import cli

def test_status_reports_counts(home, capsys):
    from totalrecall import paths, patterns_store
    from totalrecall.models import Pattern
    paths.ensure_dirs()
    patterns_store.save(Pattern("x", "T", "c", "llm", "d",
                                "2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z", 1, 1))
    rc = cli.main(["status"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "patterns: 1" in out

def test_dispatch_calls_subcommands(home, monkeypatch):
    called = {}
    monkeypatch.setattr(cli.hookinstall, "init", lambda: called.setdefault("init", True))
    monkeypatch.setattr(cli.worker, "run", lambda: called.setdefault("worker", "done") or "done")
    monkeypatch.setattr(cli.reconcile, "run", lambda: called.setdefault("recon", 0) or 0)
    assert cli.main(["init"]) == 0 and called.get("init")
    assert cli.main(["worker"]) == 0 and called.get("worker")
    assert cli.main(["reconcile"]) == 0 and "recon" in called

def test_ingest_one_path(home, monkeypatch, tmp_path):
    called = {}
    monkeypatch.setattr(cli.worker, "process_path",
                        lambda path, cfg: called.setdefault("p", path) or True)
    f = tmp_path / "s.jsonl"; f.write_text("x", encoding="utf-8")
    assert cli.main(["ingest", str(f)]) == 0
    assert called["p"] == str(f)

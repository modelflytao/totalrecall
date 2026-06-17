from totalrecall import reconcile, queue, paths

def test_codex_scanned_when_enabled(home, tmp_path, monkeypatch):
    paths.ensure_dirs()
    paths.config_path().write_text("[sources]\nclaude_code = false\ncodex = true\n", encoding="utf-8")
    cdx = tmp_path / "codex" / "sessions" / "2026" / "06"; cdx.mkdir(parents=True)
    f = cdx / "rollout-x.jsonl"; f.write_text("x", encoding="utf-8")
    monkeypatch.setattr(reconcile, "codex_sessions_dir", lambda: tmp_path / "codex" / "sessions")
    n = reconcile.run(recent_seconds=0)
    assert str(f) in set(queue.drain())
    assert n == 1

def test_codex_not_scanned_when_disabled(home, tmp_path, monkeypatch):
    paths.ensure_dirs()   # default config: codex = false
    cdx = tmp_path / "codex" / "sessions"; cdx.mkdir(parents=True)
    (cdx / "rollout-y.jsonl").write_text("x", encoding="utf-8")
    monkeypatch.setattr(reconcile, "codex_sessions_dir", lambda: cdx)
    monkeypatch.setattr(reconcile, "claude_projects_dir", lambda: tmp_path / "noexist")
    assert reconcile.run(recent_seconds=0) == 0

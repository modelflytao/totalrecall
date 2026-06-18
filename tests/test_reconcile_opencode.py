from totalrecall import reconcile, queue, paths

def test_opencode_cache_scanned_when_enabled(home, monkeypatch):
    paths.ensure_dirs()
    paths.config_path().write_text(
        "[sources]\nclaude_code = false\ncodex = false\nopencode = true\n", encoding="utf-8")
    cache = paths.opencode_cache_dir(); cache.mkdir(parents=True, exist_ok=True)
    f = cache / "ses_x.jsonl"; f.write_text("x", encoding="utf-8")
    n = reconcile.run(recent_seconds=0)
    assert str(f) in set(queue.drain())
    assert n == 1

def test_opencode_not_scanned_when_disabled(home, monkeypatch):
    paths.ensure_dirs()   # default config: opencode = false
    cache = paths.opencode_cache_dir(); cache.mkdir(parents=True, exist_ok=True)
    (cache / "ses_y.jsonl").write_text("x", encoding="utf-8")
    monkeypatch.setattr(reconcile, "claude_projects_dir", lambda: paths.state_dir() / "noexist")
    assert reconcile.run(recent_seconds=0) == 0

from totalrecall import reconcile, ledger, queue, paths


def test_encoded_analysis_dir_encodes_dot(monkeypatch):
    # Claude Code turns '.totalrecall' into '-totalrecall' (dot -> dash).
    monkeypatch.setattr(paths, "analysis_cwd",
                        lambda: __import__("pathlib").Path(r"C:\Users\u\.totalrecall\analysis"))
    assert reconcile._encoded_analysis_dir() == "C--Users-u--totalrecall-analysis"


def test_enqueues_unseen_skips_done_and_analysis(home, tmp_path, monkeypatch):
    paths.ensure_dirs()
    enc = reconcile._encoded_analysis_dir()   # use the real encoding, kept in sync
    projects = tmp_path / "projects"
    (projects / "proj-a").mkdir(parents=True)
    (projects / enc).mkdir(parents=True)
    new = projects / "proj-a" / "s1.jsonl"; new.write_text("x", encoding="utf-8")
    done = projects / "proj-a" / "s2.jsonl"; done.write_text("y", encoding="utf-8")
    skip = projects / enc / "a1.jsonl"; skip.write_text("z", encoding="utf-8")

    lg = ledger.Ledger.load(); lg.mark_done("s2", done); lg.save()
    monkeypatch.setattr(reconcile, "claude_projects_dir", lambda: projects)

    n = reconcile.run(recent_seconds=0)   # don't skip fresh test files
    queued = set(queue.drain())
    assert str(new) in queued
    assert str(done) not in queued
    assert str(skip) not in queued
    assert n == 1


def test_skips_in_progress_recently_modified(home, tmp_path, monkeypatch):
    paths.ensure_dirs()
    projects = tmp_path / "projects"; (projects / "p").mkdir(parents=True)
    active = projects / "p" / "active.jsonl"; active.write_text("x", encoding="utf-8")
    monkeypatch.setattr(reconcile, "claude_projects_dir", lambda: projects)
    # default recent window: a just-written (in-progress) transcript is skipped
    assert reconcile.run() == 0
    assert queue.size() == 0

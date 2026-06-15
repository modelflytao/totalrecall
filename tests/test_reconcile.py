from totalrecall import reconcile, ledger, queue, paths

def test_enqueues_unseen_skips_done_and_analysis(home, tmp_path, monkeypatch):
    paths.ensure_dirs()
    projects = tmp_path / "projects"
    (projects / "proj-a").mkdir(parents=True)
    (projects / "analysis").mkdir(parents=True)
    new = projects / "proj-a" / "s1.jsonl"; new.write_text("x", encoding="utf-8")
    done = projects / "proj-a" / "s2.jsonl"; done.write_text("y", encoding="utf-8")
    skip = projects / "analysis" / "a1.jsonl"; skip.write_text("z", encoding="utf-8")

    lg = ledger.Ledger.load(); lg.mark_done("s2", done); lg.save()
    monkeypatch.setattr(reconcile, "claude_projects_dir", lambda: projects)

    n = reconcile.run()
    queued = set(queue.drain())
    assert str(new) in queued
    assert str(done) not in queued     # already in ledger
    assert str(skip) not in queued     # analysis dir excluded
    assert n == 1

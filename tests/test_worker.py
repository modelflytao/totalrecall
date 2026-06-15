import json
from totalrecall import worker, queue, ledger, patterns_store, paths
from totalrecall.adapters.claude_code import ClaudeCodeAdapter

CC_LINE = ('{{"type":"user","isMeta":false,"isSidechain":false,'
           '"timestamp":"2026-06-10T10:0{n}:00Z","cwd":"/home/u/proj","sessionId":"{sid}",'
           '"gitBranch":"main","message":{{"role":"user","content":"use PowerShell not bash"}}}}')

def _write_session(home, sid):
    p = home / f"{sid}.jsonl"
    p.write_text(CC_LINE.format(n=0, sid=sid) + "\n", encoding="utf-8")
    return p

def _fake_analyze(session, catalog, model, runner=None):
    from totalrecall.models import Finding, Evidence
    return [Finding("repeated-correction", "use pwsh not bash", 3,
                    Evidence(session.session_id, "claude-code", [0], session.ended_at,
                             "h-" + session.session_id),
                    slug="pwsh-vs-bash")]

def test_process_one_updates_patterns_and_ledger(home, monkeypatch):
    paths.ensure_dirs()
    p = _write_session(home, "s1")
    queue.enqueue(str(p))
    monkeypatch.setattr(worker.orchestrator, "analyze", _fake_analyze)
    worker.run_once()
    assert patterns_store.get("pwsh-vs-bash").occurrences == 1
    assert ledger.Ledger.load().is_new(p) is False
    assert paths.insights_path().exists()

def test_drain_loop_picks_up_item_enqueued_during_processing(home, monkeypatch):
    paths.ensure_dirs()
    p1 = _write_session(home, "s1"); queue.enqueue(str(p1))
    calls = {"n": 0}
    def analyze_then_enqueue(session, catalog, model, runner=None):
        calls["n"] += 1
        if calls["n"] == 1:                         # mid-processing, a new session arrives
            p2 = _write_session(home, "s2"); queue.enqueue(str(p2))
        return _fake_analyze(session, catalog, model)
    monkeypatch.setattr(worker.orchestrator, "analyze", analyze_then_enqueue)
    monkeypatch.setattr(worker.reconcile, "run", lambda: 0)   # don't scan real ~/.claude
    worker.run()                                    # must drain BOTH via drain-loop
    assert calls["n"] == 2
    assert queue.size() == 0
    assert ledger.Ledger.load().is_new(_write_session(home, "s2")) is False

def test_second_worker_exits_when_locked(home, monkeypatch):
    paths.ensure_dirs()
    from totalrecall.locking import try_worker_lock
    with try_worker_lock() as got:
        assert got is True
        assert worker.run() == "busy"               # lock held -> no-op

def test_synth_fires_when_cumulative_count_crosses_n(home, monkeypatch):
    paths.ensure_dirs()
    paths.config_path().write_text("[limits]\nsynth_every_n_sessions = 1\n", encoding="utf-8")
    p = _write_session(home, "s1"); queue.enqueue(str(p))
    monkeypatch.setattr(worker.orchestrator, "analyze", _fake_analyze)
    monkeypatch.setattr(worker.reconcile, "run", lambda: 0)
    fired = {"n": 0}
    monkeypatch.setattr(worker.synth, "run", lambda cfg: fired.__setitem__("n", fired["n"] + 1))
    worker.run()
    assert fired["n"] == 1

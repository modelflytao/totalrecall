from totalrecall import worker, queue, patterns_store, paths, ledger
from totalrecall.adapters.claude_code import ClaudeCodeAdapter
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"

def _fake_analyze(session, catalog, model, runner=None, **kwargs):
    from totalrecall.models import Finding, Evidence
    return [Finding("repeated-correction", "x", 3,
                    Evidence(session.session_id, session.tool, [0], session.ended_at,
                             "h-" + session.session_id), slug="s-" + session.tool)]

def test_cc_adapter_self_computes_events():
    # moving extract_events into the adapter: a parsed CC session already has stats populated
    s = ClaudeCodeAdapter().parse(FIX / "cc_basic.jsonl")
    assert s.stats.n_tool_errors >= 1        # Bash error in cc_basic fixture
    assert s.stats.n_turns == len(s.turns)

def test_worker_processes_codex_via_for_path(home, monkeypatch, tmp_path):
    paths.ensure_dirs()
    # a codex transcript placed under a path containing /.codex/sessions/
    cdir = tmp_path / ".codex" / "sessions" / "2026" / "06"
    cdir.mkdir(parents=True)
    src = (FIX / "codex_basic.jsonl").read_text(encoding="utf-8")
    cf = cdir / "rollout-x.jsonl"; cf.write_text(src, encoding="utf-8")
    queue.enqueue(str(cf))
    monkeypatch.setattr(worker.orchestrator, "analyze", _fake_analyze)
    worker.run_once()
    # the codex session was parsed by CodexAdapter (tool=codex) and merged
    p = patterns_store.get("s-codex")
    assert p is not None and p.evidence[0].tool == "codex"
    assert ledger.Ledger.load().is_new(cf) is False

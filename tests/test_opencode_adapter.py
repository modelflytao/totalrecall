from pathlib import Path
from totalrecall.adapters.opencode import OpenCodeAdapter

FIX = Path(__file__).parent / "fixtures"

def _parse():
    return OpenCodeAdapter().parse(FIX / "opencode_cache_basic.jsonl")

def test_meta_fields():
    s = _parse()
    assert s.tool == "opencode"
    assert s.session_id == "ses_x"
    assert s.cwd == "D:/work/demo"
    assert s.git_branch is None
    assert s.is_analysis_session is False
    assert s.started_at == "2026-06-10T10:00:00+00:00"
    assert s.ended_at == "2026-06-10T10:05:00+00:00"

def test_turns_roles_and_tool():
    s = _parse()
    roles = [t.role for t in s.turns]
    assert roles == ["user", "assistant", "tool", "tool"]
    statuses = {t.tool_name: t.tool_status for t in s.turns if t.role == "tool"}
    assert statuses["bash"] == "error"
    assert statuses["read"] == "ok"          # 'running' recorded as ok, not error

def test_events_toolerror_churn():
    s = _parse()
    kinds = {e.kind for e in s.events}
    assert "tool_error" in kinds and "churn" in kinds
    churn = [e for e in s.events if e.kind == "churn"]
    assert churn[0].ref == "D:/work/demo/a.py"   # a.py: 1 + 2 = 3 edits -> churn

def test_stats():
    s = _parse()
    assert s.stats.n_turns == 4
    assert s.stats.n_tool_errors == 1            # only the error tool, not running
    assert s.stats.n_edits == 3                  # 1 + 2 patch file entries
    assert s.stats.duration_s == 300.0

def test_garbage_skipped():
    s = _parse()
    assert len(s.turns) == 4

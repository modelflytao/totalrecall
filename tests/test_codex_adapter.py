from pathlib import Path
from totalrecall.adapters.codex import CodexAdapter

FIX = Path(__file__).parent / "fixtures"

def _parse():
    return CodexAdapter().parse(FIX / "codex_basic.jsonl")

def test_session_meta_fields():
    s = _parse()
    assert s.tool == "codex"
    assert s.session_id == "cdx-001"
    assert s.cwd == "D:/work/demo"
    assert s.git_branch is None
    assert s.is_analysis_session is False
    assert s.started_at == "2026-06-13T14:40:56Z"
    assert s.ended_at == "2026-06-13T14:41:20Z"

def test_turns_roles_and_developer_skipped():
    s = _parse()
    roles = [t.role for t in s.turns]
    assert roles == ["user", "assistant", "tool"]      # developer skipped
    user = [t for t in s.turns if t.role == "user"][0]
    assert user.text == "use PowerShell not bash"
    tool = [t for t in s.turns if t.role == "tool"][0]
    assert tool.tool_name == "shell"

def test_events_edit_churn_toolerror_interrupt():
    s = _parse()
    kinds = {e.kind for e in s.events}
    assert "churn" in kinds and "tool_error" in kinds and "interrupt" in kinds
    churn = [e for e in s.events if e.kind == "churn"]
    assert churn[0].ref == "D:/work/demo/a.py"          # a.py edited 3x
    assert any(e.kind == "interrupt" for e in s.events)  # turn_aborted

def test_stats():
    s = _parse()
    assert s.stats.n_turns == 3
    assert s.stats.n_edits == 4          # a.py x3 + b.py x1
    assert s.stats.n_tool_errors == 1    # b.py patch success=false
    assert s.stats.duration_s == 24.0    # 14:41:20 - 14:40:56

def test_garbage_line_skipped():
    s = _parse()
    assert len(s.turns) == 3   # parsed despite trailing garbage

def test_first_session_meta_wins_on_resume(tmp_path):
    f = tmp_path / "resumed.jsonl"
    f.write_text(
        '{"timestamp":"2026-05-30T19:31:57Z","type":"session_meta","payload":{"id":"orig-001","cwd":"D:/work/a"}}\n'
        '{"timestamp":"2026-05-30T19:32:00Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"hi"}]}}\n'
        '{"timestamp":"2026-05-30T19:33:00Z","type":"session_meta","payload":{"id":"fork-002","cwd":"D:/work/b"}}\n',
        encoding="utf-8")
    s = CodexAdapter().parse(f)
    assert s.session_id == "orig-001"   # first session_meta, not the later fork
    assert s.cwd == "D:/work/a"

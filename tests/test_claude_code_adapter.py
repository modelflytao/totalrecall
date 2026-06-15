from pathlib import Path
from totalrecall.adapters.claude_code import ClaudeCodeAdapter

FIX = Path(__file__).parent / "fixtures"

def test_parse_basic_turns_and_meta():
    s = ClaudeCodeAdapter().parse(FIX / "cc_basic.jsonl")
    assert s.tool == "claude-code"
    assert s.session_id == "s1"
    assert s.cwd == "/home/u/proj"
    assert s.git_branch == "main"
    assert s.is_analysis_session is False
    # user turns exclude isMeta and exclude tool_result-only user lines
    user_texts = [t.text for t in s.turns if t.role == "user"]
    assert "please use PowerShell not bash" in user_texts
    assert all("system-reminder" not in t for t in user_texts)  # meta excluded
    # tool turns captured with status
    tool_turns = [t for t in s.turns if t.role == "tool"]
    statuses = {t.tool_name: t.tool_status for t in tool_turns}
    assert statuses["Bash"] == "error"
    assert statuses["Edit"] == "ok"

def test_started_and_ended_timestamps():
    s = ClaudeCodeAdapter().parse(FIX / "cc_basic.jsonl")
    assert s.started_at == "2026-06-10T10:00:00Z"
    assert s.ended_at == "2026-06-10T10:00:12Z"

def test_is_analysis_session_by_cwd():
    s = ClaudeCodeAdapter().parse(FIX / "cc_analysis.jsonl")
    assert s.is_analysis_session is True

def test_garbage_lines_skipped_without_crash():
    s = ClaudeCodeAdapter().parse(FIX / "cc_basic.jsonl")
    assert len(s.turns) >= 4  # parsed despite trailing garbage line

def test_is_analysis_session_by_configured_home(home, tmp_path):
    from totalrecall import paths
    cwd = str(paths.analysis_cwd()).replace("\\", "/")
    p = tmp_path / "an.jsonl"
    p.write_text(
        '{"type":"user","timestamp":"2026-06-10T11:00:00Z","cwd":"' + cwd +
        '","sessionId":"a1","message":{"role":"user","content":"hi"}}\n',
        encoding="utf-8")
    s = ClaudeCodeAdapter().parse(p)
    assert s.is_analysis_session is True

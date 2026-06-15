from totalrecall.models import NormalizedSession, Turn, Stats
from totalrecall.events import extract_events

def _sess(turns):
    return NormalizedSession("claude-code", "s1", "/p", "main",
                             "2026-06-10T10:00:00Z", "2026-06-10T10:05:00Z",
                             False, turns=turns, events=[], stats=Stats())

def test_tool_errors_counted():
    s = _sess([
        Turn(0, "tool", None, tool_name="Bash", tool_status="error"),
        Turn(1, "tool", None, tool_name="Bash", tool_status="ok"),
    ])
    extract_events(s)
    assert s.stats.n_tool_errors == 1
    assert any(e.kind == "tool_error" for e in s.events)

def test_edit_churn_same_file():
    s = _sess([
        Turn(0, "tool", None, tool_name="Edit", tool_status="ok", text='{"file_path": "a.py"}'),
        Turn(1, "tool", None, tool_name="Edit", tool_status="ok", text='{"file_path": "a.py"}'),
        Turn(2, "tool", None, tool_name="Write", tool_status="ok", text='{"file_path": "a.py"}'),
        Turn(3, "tool", None, tool_name="Edit", tool_status="ok", text='{"file_path": "b.py"}'),
    ])
    extract_events(s)
    assert s.stats.n_edits == 4
    churn = [e for e in s.events if e.kind == "churn"]
    assert len(churn) == 1 and churn[0].ref == "a.py"  # a.py edited 3x -> churn; b.py once -> no

def test_duration_seconds():
    s = _sess([Turn(0, "user", None)])
    extract_events(s)
    assert s.stats.duration_s == 300.0

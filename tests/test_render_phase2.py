from datetime import datetime, timezone
from totalrecall import render, patterns_store, paths
from totalrecall.models import Pattern, Evidence

NOW = datetime(2026, 6, 30, tzinfo=timezone.utc)

def _p(pid, applied_at=None, status="active", ev_ts=None, rule=None):
    ev = [Evidence("s", "claude-code", [1], ev_ts, "h")] if ev_ts else []
    return Pattern(pid, f"T {pid}", "repeated-correction", "llm", f"d {pid}",
                   "2026-06-01T00:00:00Z", "2026-06-14T00:00:00Z", 5, 3,
                   evidence=ev, status=status, applied_at=applied_at, applied_rule=rule)

def test_phase2_sections(home):
    paths.ensure_dirs()
    patterns_store.save(_p("resolved1", applied_at="2026-06-10T00:00:00Z",
                           ev_ts="2026-06-05T00:00:00Z", rule="rule A"))   # -> resolved
    patterns_store.save(_p("ineff1", applied_at="2026-06-10T00:00:00Z",
                           status="ineffective", rule="rule B"))           # -> ineffective
    patterns_store.save(_p("pending1", applied_at="2026-06-28T00:00:00Z", rule="rule C"))  # within window
    render.write(now=NOW, n_sessions=50, n_projects=5)
    text = paths.insights_path().read_text(encoding="utf-8")
    assert "✅ 已解决" in text and "T resolved1" in text
    assert "⚠️ 修复无效" in text and "T ineff1" in text
    assert "⏳ 已应用待验证" in text and "T pending1" in text
    assert "rule A" in text                      # shows the applied rule

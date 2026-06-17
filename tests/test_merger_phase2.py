from totalrecall import merger, patterns_store, paths
from totalrecall.models import Pattern, Finding, Evidence

def _applied_pattern(applied_at, status="active"):
    return Pattern("pwsh", "T", "repeated-correction", "llm", "use pwsh",
                   "2026-06-01T00:00:00Z", "2026-06-05T00:00:00Z", 2, 3,
                   evidence=[Evidence("s0", "claude-code", [1], "2026-06-05T00:00:00Z", "h0")],
                   status=status, applied_at=applied_at)

def _finding(ts, h):
    return Finding("repeated-correction", "use pwsh again", 3,
                   Evidence("s9", "claude-code", [2], ts, h), pattern_id="pwsh")

def test_recurrence_after_apply_marks_ineffective(home):
    paths.ensure_dirs()
    patterns_store.save(_applied_pattern("2026-06-10T00:00:00Z"))
    merger.merge([_finding("2026-06-15T00:00:00Z", "h1")], now="2026-06-15T00:00:00Z")
    assert patterns_store.get("pwsh").status == "ineffective"

def test_recurrence_overrides_resolved(home):
    paths.ensure_dirs()
    patterns_store.save(_applied_pattern("2026-06-10T00:00:00Z", status="resolved"))
    merger.merge([_finding("2026-06-20T00:00:00Z", "h2")], now="2026-06-20T00:00:00Z")
    assert patterns_store.get("pwsh").status == "ineffective"

def test_no_change_if_recurrence_before_apply(home):
    paths.ensure_dirs()
    patterns_store.save(_applied_pattern("2026-06-30T00:00:00Z"))
    merger.merge([_finding("2026-06-15T00:00:00Z", "h3")], now="2026-06-15T00:00:00Z")
    assert patterns_store.get("pwsh").status == "active"

def test_ineffective_when_evidence_ts_missing_uses_now_fallback(home):
    # recurred transcript lacks timestamps -> evidence ts None -> fall back to `now`
    paths.ensure_dirs()
    patterns_store.save(_applied_pattern("2026-06-10T00:00:00Z"))
    f = Finding("repeated-correction", "again", 3,
                Evidence("s9", "claude-code", [2], None, "hX"), pattern_id="pwsh")
    merger.merge([f], now="2026-06-20T00:00:00Z")   # now > applied_at
    assert patterns_store.get("pwsh").status == "ineffective"

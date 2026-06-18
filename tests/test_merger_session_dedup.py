from totalrecall import merger, patterns_store, paths
from totalrecall.models import Finding, Evidence

def _f(sid, h, slug="pwsh"):
    return Finding("repeated-correction", "use pwsh", 3,
                   Evidence(sid, "opencode", [1], "2026-06-10T00:00:00Z", h), slug=slug)

def test_same_session_not_double_counted(home):
    paths.ensure_dirs()
    merger.merge([_f("ses_a", "h1")], now="2026-06-10T00:00:00Z")
    merger.merge([_f("ses_a", "h2")], now="2026-06-11T00:00:00Z")  # same session, new hash
    p = patterns_store.get("pwsh")
    assert p.occurrences == 1 and len(p.evidence) == 1   # deduped by session_id

def test_different_sessions_counted(home):
    paths.ensure_dirs()
    merger.merge([_f("ses_a", "h1")], now="2026-06-10T00:00:00Z")
    merger.merge([_f("ses_b", "h2")], now="2026-06-11T00:00:00Z")
    p = patterns_store.get("pwsh")
    assert p.occurrences == 2 and len(p.evidence) == 2

def test_same_session_recurrence_after_apply_still_marks_ineffective(home):
    # HOLE A regression: dedup must NOT skip the post-apply recurrence check.
    # A grown session re-analyzed after a rule was applied must flip ineffective.
    from totalrecall.models import Pattern
    paths.ensure_dirs()
    patterns_store.save(Pattern(
        "pwsh", "T", "repeated-correction", "llm", "use pwsh",
        "2026-06-01T00:00:00Z", "2026-06-05T00:00:00Z", 1, 3,
        evidence=[Evidence("ses_a", "opencode", [1], "2026-06-05T00:00:00Z", "h1")],
        applied_at="2026-06-10T00:00:00Z"))
    recur = Finding("repeated-correction", "use pwsh", 3,
                    Evidence("ses_a", "opencode", [2], "2026-06-15T00:00:00Z", "h2"), slug="pwsh")
    merger.merge([recur], now="2026-06-15T00:00:00Z")    # same session, ts > applied_at
    p = patterns_store.get("pwsh")
    assert p.status == "ineffective"   # rule didn't work — must be detected even for same session
    assert p.occurrences == 1          # but not double-counted (I1 preserved)

from datetime import datetime, timezone
from totalrecall.models import Pattern, Evidence
from totalrecall.strength import derive_status

NOW = datetime(2026, 6, 30, tzinfo=timezone.utc)

def _p(applied_at=None, status="active", ev_ts=None, last="2026-06-10T00:00:00Z"):
    ev = [Evidence("s", "claude-code", [1], ev_ts, "h")] if ev_ts else []
    return Pattern("x", "T", "c", "llm", "d", "2026-06-01T00:00:00Z", last, 3, 3,
                   evidence=ev, status=status, applied_at=applied_at)

def test_resolved_when_applied_and_quiet_past_window():
    # applied 20 days before NOW, no evidence newer than applied -> resolved
    p = _p(applied_at="2026-06-10T00:00:00Z", ev_ts="2026-06-05T00:00:00Z")
    assert derive_status(p, NOW, resolved_after_days=14) == "resolved"

def test_not_resolved_within_window():
    p = _p(applied_at="2026-06-25T00:00:00Z", ev_ts="2026-06-20T00:00:00Z")
    assert derive_status(p, NOW, resolved_after_days=14) == "active"

def test_not_resolved_if_recurred_after_apply():
    p = _p(applied_at="2026-06-10T00:00:00Z", ev_ts="2026-06-12T00:00:00Z")  # later evidence
    assert derive_status(p, NOW, resolved_after_days=14) != "resolved"

def test_ineffective_is_sticky():
    p = _p(applied_at="2026-06-10T00:00:00Z", status="ineffective", ev_ts="2026-06-12T00:00:00Z")
    assert derive_status(p, NOW, resolved_after_days=14) == "ineffective"

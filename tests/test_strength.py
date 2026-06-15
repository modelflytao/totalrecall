from datetime import datetime, timezone
from totalrecall.models import Pattern
from totalrecall.strength import strength, derive_status

NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)

def _p(occ, last, sev=3, status="active"):
    return Pattern("x", "T", "c", "llm", "d", "2026-06-01T00:00:00Z", last, occ, sev,
                   status=status)

def test_more_occurrences_more_strength():
    a = strength(_p(1, "2026-06-15T00:00:00Z"), NOW)
    b = strength(_p(5, "2026-06-15T00:00:00Z"), NOW)
    assert b > a

def test_recency_decay():
    fresh = strength(_p(3, "2026-06-15T00:00:00Z"), NOW)
    stale = strength(_p(3, "2026-05-01T00:00:00Z"), NOW)
    assert fresh > stale

def test_status_fading_when_old():
    assert derive_status(_p(3, "2026-06-14T00:00:00Z"), NOW) == "active"
    assert derive_status(_p(3, "2026-04-01T00:00:00Z"), NOW) == "fading"

def test_resolved_status_sticky():
    assert derive_status(_p(3, "2026-06-14T00:00:00Z", status="resolved"), NOW) == "resolved"

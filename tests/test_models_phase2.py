from totalrecall.models import Pattern, pattern_to_dict, pattern_from_dict

def _p(**kw):
    base = dict(id="x", title="T", category="c", source="llm", description="d",
                first_seen="2026-06-01T00:00:00Z", last_seen="2026-06-02T00:00:00Z",
                occurrences=2, severity=3)
    base.update(kw)
    return Pattern(**base)

def test_applied_fields_default_none():
    p = _p()
    assert p.applied_at is None and p.applied_rule is None

def test_applied_fields_roundtrip():
    p = _p(applied_at="2026-06-10T00:00:00Z", applied_rule="use PowerShell", status="ineffective")
    p2 = pattern_from_dict(pattern_to_dict(p))
    assert p2.applied_at == "2026-06-10T00:00:00Z"
    assert p2.applied_rule == "use PowerShell"
    assert p2.status == "ineffective"

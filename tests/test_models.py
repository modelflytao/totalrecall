from totalrecall.models import (
    Turn, Event, Stats, NormalizedSession, Evidence, Finding, Pattern,
    pattern_to_dict, pattern_from_dict, finding_from_dict,
)

def test_pattern_roundtrip():
    p = Pattern(
        id="pwsh-vs-bash", title="Use PowerShell not bash", category="repeated-correction",
        source="llm", description="...", first_seen="2026-06-01T00:00:00Z",
        last_seen="2026-06-10T00:00:00Z", occurrences=3, severity=4,
        evidence=[Evidence("s1", "claude-code", [4, 5], "2026-06-10T00:00:00Z", "abc")],
    )
    d = pattern_to_dict(p)
    p2 = pattern_from_dict(d)
    assert p2 == p

def test_finding_from_dict_defaults():
    f = finding_from_dict({
        "category": "tool-error", "description": "x", "severity": 2,
        "evidence": {"session_id": "s1", "tool": "claude-code",
                     "turn_refs": [1], "ts": None, "snippet_hash": "h"},
    })
    assert f.pattern_id is None and f.slug is None

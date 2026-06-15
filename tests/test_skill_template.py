from pathlib import Path

SKILL = Path("skills/totalrecall-analyze/SKILL.md")

def test_skill_exists_and_specifies_json_array_and_categories():
    text = SKILL.read_text(encoding="utf-8")
    assert "JSON array" in text
    for cat in ["misunderstood-intent", "repeated-correction", "clarification-gap",
                "rule-violation", "tool-error"]:
        assert cat in text
    assert "turn_refs" in text and "severity" in text
    # must instruct reuse of existing pattern ids
    assert "pattern_id" in text and "catalog" in text.lower()

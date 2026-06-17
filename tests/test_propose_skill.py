from pathlib import Path

SKILL = Path("skills/totalrecall-propose/SKILL.md")

def test_skill_specifies_json_object_and_fields():
    text = SKILL.read_text(encoding="utf-8")
    assert "JSON object" in text
    for k in ["rule_text", "rationale", "target_file"]:
        assert k in text
    assert "existing rules" in text.lower()   # instructs to avoid duplicates
    assert "CLAUDE.md" in text

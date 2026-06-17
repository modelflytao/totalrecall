from totalrecall import applier
from totalrecall.proposals_store import Proposal

def _prop(pid="p-pwsh"):
    return Proposal(pid, "pwsh", "~/.claude/totalrecall-rules.md",
                    "Use PowerShell on Windows.", "recurs", status="drafted",
                    created_at="2026-06-17T00:00:00Z")

def test_write_rule_block_idempotent(tmp_path):
    rules = tmp_path / "totalrecall-rules.md"
    assert applier.write_rule(rules, _prop(), occ=14, last="2026-06-15") is True
    text = rules.read_text(encoding="utf-8")
    assert "<!-- pattern: pwsh -->" in text and "Use PowerShell on Windows." in text
    # second write is a no-op (marker present)
    assert applier.write_rule(rules, _prop(), occ=14, last="2026-06-15") is False
    assert text.count("Use PowerShell on Windows.") == 1

def test_ensure_import_idempotent_with_backup(tmp_path):
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# my rules\n@RTK.md\n", encoding="utf-8")
    assert applier.ensure_import(claude_md, "totalrecall-rules.md") is True
    assert "@totalrecall-rules.md" in claude_md.read_text(encoding="utf-8")
    assert (tmp_path / "CLAUDE.md.bak-totalrecall").exists()       # backup made
    assert "@RTK.md" in claude_md.read_text(encoding="utf-8")      # existing preserved
    # second call: already imported -> no-op
    assert applier.ensure_import(claude_md, "totalrecall-rules.md") is False

def test_ensure_import_creates_missing_claude_md(tmp_path):
    claude_md = tmp_path / "CLAUDE.md"
    assert applier.ensure_import(claude_md, "totalrecall-rules.md") is True
    assert "@totalrecall-rules.md" in claude_md.read_text(encoding="utf-8")

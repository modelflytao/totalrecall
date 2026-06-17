from datetime import datetime, timezone
from totalrecall import applier, patterns_store, proposals_store, paths, config
from totalrecall.models import Pattern
from totalrecall.proposals_store import Proposal

NOW = datetime(2026, 6, 17, tzinfo=timezone.utc)

def _pattern(pid="pwsh"):
    return Pattern(pid, "T", "c", "llm", "d", "2026-06-01T00:00:00Z",
                   "2026-06-14T00:00:00Z", 14, 3)

def _prop(pid="p-pwsh", pat="pwsh"):
    return Proposal(pid, pat, "~/.claude/totalrecall-rules.md", "Use PowerShell.",
                    "recurs", status="drafted", created_at="2026-06-17T00:00:00Z")

def _cfg(tmp_path):
    cfg = config.Config()
    cfg.rules_file = str(tmp_path / "totalrecall-rules.md")
    cfg.claude_md = str(tmp_path / "CLAUDE.md")
    return cfg

def test_apply_writes_files_and_records_pattern(home, tmp_path):
    paths.ensure_dirs()
    patterns_store.save(_pattern())
    proposals_store.upsert(_prop())
    n = applier.apply(["p-pwsh"], _cfg(tmp_path), now=NOW)
    assert n == 1
    pat = patterns_store.get("pwsh")
    assert pat.applied_at == NOW.isoformat() and pat.applied_rule == "Use PowerShell."
    assert proposals_store.get("p-pwsh").status == "applied"
    assert "Use PowerShell." in (tmp_path / "totalrecall-rules.md").read_text(encoding="utf-8")
    assert "@totalrecall-rules.md" in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")

def test_apply_skips_stale_pattern(home, tmp_path):
    paths.ensure_dirs()
    proposals_store.upsert(_prop("p-gone", "gone"))    # pattern 'gone' not in store
    n = applier.apply(["p-gone"], _cfg(tmp_path), now=NOW)
    assert n == 0 and proposals_store.get("p-gone").status == "stale"

def test_reject_marks_rejected(home):
    paths.ensure_dirs()
    proposals_store.upsert(_prop())
    applier.reject(["p-pwsh"])
    assert proposals_store.get("p-pwsh").status == "rejected"

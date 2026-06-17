from totalrecall import proposals_store, paths
from totalrecall.proposals_store import Proposal

def _prop(pid="p-pwsh", status="drafted"):
    return Proposal(id=pid, pattern_id="pwsh", target_file="~/.claude/totalrecall-rules.md",
                    rule_text="use PowerShell", rationale="recurs 14x",
                    status=status, created_at="2026-06-17T00:00:00Z")

def test_save_and_load(home):
    paths.ensure_dirs()
    proposals_store.upsert(_prop())
    got = proposals_store.get("p-pwsh")
    assert got.rule_text == "use PowerShell" and got.status == "drafted"

def test_all_and_by_status(home):
    paths.ensure_dirs()
    proposals_store.upsert(_prop("p-a", "drafted"))
    proposals_store.upsert(_prop("p-b", "rejected"))
    assert {p.id for p in proposals_store.all()} == {"p-a", "p-b"}
    assert [p.id for p in proposals_store.by_status("drafted")] == ["p-a"]
    assert proposals_store.rejected_pattern_ids() == {"pwsh"}  # p-b rejected -> pattern pwsh

def test_upsert_overwrites_same_id(home):
    paths.ensure_dirs()
    proposals_store.upsert(_prop("p-a", "drafted"))
    proposals_store.upsert(_prop("p-a", "applied"))
    assert proposals_store.get("p-a").status == "applied"
    assert len(proposals_store.all()) == 1

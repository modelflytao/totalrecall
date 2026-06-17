import json
from datetime import datetime, timezone
from totalrecall import proposer, patterns_store, proposals_store, paths
from totalrecall.models import Pattern

NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)

def _p(pid, occ):
    return Pattern(pid, f"title {pid}", "repeated-correction", "llm", f"desc {pid}",
                   "2026-06-01T00:00:00Z", "2026-06-14T00:00:00Z", occ, 3)

def _runner_returns(obj):
    envelope = {"type": "result", "result": json.dumps(obj)}
    return lambda prompt, model, cwd, env: json.dumps(envelope)

def test_propose_creates_proposal_and_md(home):
    paths.ensure_dirs()
    patterns_store.save(_p("pwsh", 9))
    runner = _runner_returns({"rule_text": "Use PowerShell on Windows.",
                              "rationale": "recurs often",
                              "target_file": "~/.claude/totalrecall-rules.md"})
    n = proposer.propose(top_n=10, min_occ=3, now=NOW, model="m", runner=runner)
    assert n == 1
    props = proposals_store.by_status("drafted")
    assert len(props) == 1 and props[0].rule_text == "Use PowerShell on Windows."
    assert props[0].pattern_id == "pwsh"
    md = paths.proposals_md_path().read_text(encoding="utf-8")
    assert "Use PowerShell on Windows." in md and props[0].id in md

def test_empty_rule_text_is_skipped(home):
    paths.ensure_dirs()
    patterns_store.save(_p("pwsh", 9))
    runner = _runner_returns({"rule_text": "", "rationale": "already covered",
                              "target_file": "~/.claude/totalrecall-rules.md"})
    n = proposer.propose(top_n=10, min_occ=3, now=NOW, model="m", runner=runner)
    assert n == 0 and proposals_store.by_status("drafted") == []

def test_does_not_redraft_existing(home):
    paths.ensure_dirs()
    patterns_store.save(_p("pwsh", 9))
    runner = _runner_returns({"rule_text": "R", "rationale": "x",
                              "target_file": "~/.claude/totalrecall-rules.md"})
    proposer.propose(top_n=10, min_occ=3, now=NOW, model="m", runner=runner)
    n2 = proposer.propose(top_n=10, min_occ=3, now=NOW, model="m", runner=runner)
    assert n2 == 0 and len(proposals_store.all()) == 1   # idempotent per pattern

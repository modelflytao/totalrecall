# TotalRecall Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn recurring friction patterns into approved CLAUDE.md rules and verify whether each rule actually eliminated the friction (closed loop).

**Architecture:** Adds three units on top of Phase 1's pattern store — **proposer** (drafts a CLAUDE.md rule per top recurring pattern via headless `claude -p`), **applier** (writes approved rules to a managed `~/.claude/totalrecall-rules.md`, `@`-imported once into CLAUDE.md with a backup, and records `applied_at` on the Pattern under the worker lock), and **verifier** (folded into the existing analysis: a recurrence after `applied_at` marks the pattern `ineffective`; no recurrence within N days renders as `resolved`). All deterministic layers are unit-tested with an injected fake runner; the only real `claude -p` call is in the proposer.

**Tech Stack:** Python 3.11+ (stdlib `dataclasses`, `json`, `datetime`, `difflib`), `filelock`, `pytest`. Builds on Phase 1 (65 tests green on `main`).

**Spec:** `docs/superpowers/specs/2026-06-17-totalrecall-phase2-design.md`.

---

## File Structure

```
src/totalrecall/
  models.py            # MODIFY: Pattern += applied_at, applied_rule
  config.py            # MODIFY: [phase2] fields
  paths.py             # MODIFY: proposals_path, proposals_md_path
  strength.py          # MODIFY: derive_status -> resolved/ineffective
  merger.py            # MODIFY: mark ineffective on recurrence after applied_at
  catalog.py           # MODIFY: pin applied patterns into the catalog
  render.py            # MODIFY: Phase-2 status sections in insights.md
  cli.py               # MODIFY: propose / apply / reject / proposals
  proposals_store.py   # NEW: Proposal dataclass + proposals.json CRUD
  proposer.py          # NEW: candidate selection + claude -p drafting + proposals.md
  applier.py           # NEW: managed rules file + @import injection + apply/reject
skills/totalrecall-propose/
  SKILL.md             # NEW: rule-drafting prompt template
tests/test_*.py        # per task
```

Convention reminders (from Phase 1): tests use the `home` fixture (isolated `TOTALRECALL_HOME`); commit per task with `git commit -m "<subject>" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"` (two `-m` flags, no temp files → no BOM); run tests with `python -m pytest`.

---

## Task 1: Extend Pattern with applied_at / applied_rule

**Files:**
- Modify: `src/totalrecall/models.py`
- Test: `tests/test_models_phase2.py`

- [ ] **Step 1: Write the failing test**

`tests/test_models_phase2.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models_phase2.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'applied_at'`

- [ ] **Step 3: Implement**

In `src/totalrecall/models.py`, in the `Pattern` dataclass, add two fields after `phase2_hint`:
```python
    phase2_hint: Optional[str] = None
    applied_at: Optional[str] = None       # when a Phase-2 rule was applied for this pattern
    applied_rule: Optional[str] = None     # the rule text that was written
```
And in `pattern_from_dict`, add the two fields to the constructor call:
```python
    return Pattern(
        id=d["id"], title=d["title"], category=d["category"], source=d["source"],
        description=d["description"], first_seen=d["first_seen"], last_seen=d["last_seen"],
        occurrences=int(d["occurrences"]), severity=int(d.get("severity", 1)),
        evidence=[evidence_from_dict(e) for e in d.get("evidence", [])],
        status=d.get("status", "active"), phase2_hint=d.get("phase2_hint"),
        applied_at=d.get("applied_at"), applied_rule=d.get("applied_rule"),
    )
```
(`pattern_to_dict` uses `asdict`, so the new fields serialize automatically.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_models_phase2.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/models.py tests/test_models_phase2.py
git commit -m "feat: Pattern gains applied_at/applied_rule for Phase 2" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Phase-2 config fields

**Files:**
- Modify: `src/totalrecall/config.py`
- Test: `tests/test_config_phase2.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config_phase2.py`:
```python
from totalrecall import config, paths

def test_phase2_defaults(home):
    cfg = config.load()
    assert cfg.propose_top_n == 10
    assert cfg.propose_min_occ == 3
    assert cfg.resolved_after_days == 14
    assert cfg.rules_file.endswith("totalrecall-rules.md")
    assert cfg.claude_md.endswith("CLAUDE.md")

def test_phase2_file_override(home):
    paths.ensure_dirs()
    paths.config_path().write_text(
        "[phase2]\npropose_top_n = 3\nresolved_after_days = 7\n", encoding="utf-8")
    cfg = config.load()
    assert cfg.propose_top_n == 3 and cfg.resolved_after_days == 7
    assert cfg.propose_min_occ == 3  # untouched default
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config_phase2.py -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'propose_top_n'`

- [ ] **Step 3: Implement**

In `src/totalrecall/config.py`, add fields to the `Config` dataclass (after `analysis_marker_env`):
```python
    analysis_marker_env: str = "TOTALRECALL_ANALYSIS"
    propose_top_n: int = 10
    propose_min_occ: int = 3
    resolved_after_days: int = 14
    rules_file: str = "~/.claude/totalrecall-rules.md"
    claude_md: str = "~/.claude/CLAUDE.md"
```
In `load()`, before `return cfg`, add:
```python
    p2 = data.get("phase2", {})
    cfg.propose_top_n = p2.get("propose_top_n", cfg.propose_top_n)
    cfg.propose_min_occ = p2.get("propose_min_occ", cfg.propose_min_occ)
    cfg.resolved_after_days = p2.get("resolved_after_days", cfg.resolved_after_days)
    cfg.rules_file = p2.get("rules_file", cfg.rules_file)
    cfg.claude_md = p2.get("claude_md", cfg.claude_md)
```
In `default_toml()`, append a `[phase2]` block before the closing of the returned string:
```python
        "\n[phase2]\n"
        "propose_top_n = 10\n"
        "propose_min_occ = 3\n"
        "resolved_after_days = 14\n"
        'rules_file = "~/.claude/totalrecall-rules.md"\n'
        'claude_md  = "~/.claude/CLAUDE.md"\n'
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config_phase2.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/config.py tests/test_config_phase2.py
git commit -m "feat: [phase2] config fields" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Paths for proposals

**Files:**
- Modify: `src/totalrecall/paths.py`
- Test: `tests/test_paths_phase2.py`

- [ ] **Step 1: Write the failing test**

`tests/test_paths_phase2.py`:
```python
from totalrecall import paths

def test_proposal_paths(home):
    assert paths.proposals_path() == home / "proposals.json"
    assert paths.proposals_md_path() == home / "proposals.md"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_paths_phase2.py -v`
Expected: FAIL — `AttributeError: module 'totalrecall.paths' has no attribute 'proposals_path'`

- [ ] **Step 3: Implement**

In `src/totalrecall/paths.py`, add after `insights_path`:
```python
def proposals_path() -> Path:
    return state_dir() / "proposals.json"


def proposals_md_path() -> Path:
    return state_dir() / "proposals.md"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_paths_phase2.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/paths.py tests/test_paths_phase2.py
git commit -m "feat: proposals path helpers" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: derive_status → resolved / ineffective

**Files:**
- Modify: `src/totalrecall/strength.py`
- Test: `tests/test_strength_phase2.py`

- [ ] **Step 1: Write the failing test**

`tests/test_strength_phase2.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_strength_phase2.py -v`
Expected: FAIL — `derive_status() got an unexpected keyword argument 'resolved_after_days'`

- [ ] **Step 3: Implement**

In `src/totalrecall/strength.py`, replace `derive_status` with:
```python
def derive_status(p: Pattern, now: datetime, resolved_after_days: int = 14) -> str:
    if p.status in ("resolved", "ineffective"):
        return p.status                       # sticky stored statuses
    if p.applied_at:
        recurred = any(e.ts and _parse(e.ts) > _parse(p.applied_at) for e in p.evidence)
        if not recurred and _days_since(p.applied_at, now) >= resolved_after_days:
            return "resolved"
    return "fading" if _days_since(p.last_seen, now) > FADING_DAYS else "active"
```
(`_parse`, `_days_since`, `FADING_DAYS` already exist in this file.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_strength_phase2.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/strength.py tests/test_strength_phase2.py
git commit -m "feat: derive_status computes resolved; ineffective is sticky" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: merger marks ineffective on recurrence

**Files:**
- Modify: `src/totalrecall/merger.py`
- Test: `tests/test_merger_phase2.py`

- [ ] **Step 1: Write the failing test**

`tests/test_merger_phase2.py`:
```python
from totalrecall import merger, patterns_store, paths
from totalrecall.models import Pattern, Finding, Evidence

def _applied_pattern(applied_at, status="active"):
    return Pattern("pwsh", "T", "repeated-correction", "llm", "use pwsh",
                   "2026-06-01T00:00:00Z", "2026-06-05T00:00:00Z", 2, 3,
                   evidence=[Evidence("s0", "claude-code", [1], "2026-06-05T00:00:00Z", "h0")],
                   status=status, applied_at=applied_at)

def _finding(ts, h):
    return Finding("repeated-correction", "use pwsh again", 3,
                   Evidence("s9", "claude-code", [2], ts, h), pattern_id="pwsh")

def test_recurrence_after_apply_marks_ineffective(home):
    paths.ensure_dirs()
    patterns_store.save(_applied_pattern("2026-06-10T00:00:00Z"))
    merger.merge([_finding("2026-06-15T00:00:00Z", "h1")], now="2026-06-15T00:00:00Z")
    assert patterns_store.get("pwsh").status == "ineffective"

def test_recurrence_overrides_resolved(home):
    paths.ensure_dirs()
    patterns_store.save(_applied_pattern("2026-06-10T00:00:00Z", status="resolved"))
    merger.merge([_finding("2026-06-20T00:00:00Z", "h2")], now="2026-06-20T00:00:00Z")
    assert patterns_store.get("pwsh").status == "ineffective"

def test_no_change_if_recurrence_before_apply(home):
    paths.ensure_dirs()
    patterns_store.save(_applied_pattern("2026-06-30T00:00:00Z"))
    merger.merge([_finding("2026-06-15T00:00:00Z", "h3")], now="2026-06-15T00:00:00Z")
    assert patterns_store.get("pwsh").status == "active"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_merger_phase2.py -v`
Expected: FAIL — `test_recurrence_after_apply_marks_ineffective` asserts `ineffective`, gets `active`

- [ ] **Step 3: Implement**

In `src/totalrecall/merger.py`, add a timestamp helper near the top (after imports):
```python
from datetime import datetime

def _ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
```
In `_apply`, add at the END of the function (after the `source` update):
```python
    at, et = _ts(p.applied_at), _ts(f.evidence.ts)
    if at and et and et > at:
        p.status = "ineffective"   # recurred after the fix was applied (overrides resolved)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_merger_phase2.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/merger.py tests/test_merger_phase2.py
git commit -m "feat: merger marks pattern ineffective when it recurs after apply" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: catalog pins applied patterns

**Files:**
- Modify: `src/totalrecall/catalog.py`
- Test: `tests/test_catalog_phase2.py`

- [ ] **Step 1: Write the failing test**

`tests/test_catalog_phase2.py`:
```python
from datetime import datetime, timezone
from totalrecall import catalog, patterns_store, paths
from totalrecall.models import Pattern

NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)

def _p(pid, occ, last, applied_at=None):
    return Pattern(pid, f"t-{pid}", "c", "llm", f"d-{pid}",
                   "2026-06-01T00:00:00Z", last, occ, 3, applied_at=applied_at)

def test_applied_pattern_pinned_even_if_low_strength(home):
    paths.ensure_dirs()
    patterns_store.save(_p("strong", 9, "2026-06-15T00:00:00Z"))
    patterns_store.save(_p("weak_applied", 1, "2026-05-01T00:00:00Z",
                           applied_at="2026-05-02T00:00:00Z"))
    cat = catalog.build(top_k=1, now=NOW)   # top_k=1 would normally drop weak_applied
    ids = {c["id"] for c in cat}
    assert "strong" in ids and "weak_applied" in ids   # applied is pinned
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_catalog_phase2.py -v`
Expected: FAIL — `weak_applied` not in ids (dropped by top_k=1)

- [ ] **Step 3: Implement**

In `src/totalrecall/catalog.py`, replace `build` with:
```python
def build(top_k: int, now: datetime) -> list[dict]:
    pats = patterns_store.all()
    ranked = sorted(pats, key=lambda p: strength(p, now), reverse=True)
    chosen = list(ranked[:top_k])
    seen = {p.id for p in chosen}
    for p in pats:                       # always pin applied patterns so recurrence re-attributes
        if p.applied_at and p.id not in seen:
            chosen.append(p)
            seen.add(p.id)
    return [
        {"id": p.id, "title": p.title, "category": p.category,
         "description": p.description[:160]}
        for p in chosen
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_catalog_phase2.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/catalog.py tests/test_catalog_phase2.py
git commit -m "feat: catalog pins applied patterns so recurrence re-attributes" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: proposals_store (Proposal model + JSON CRUD)

**Files:**
- Create: `src/totalrecall/proposals_store.py`
- Test: `tests/test_proposals_store.py`

- [ ] **Step 1: Write the failing test**

`tests/test_proposals_store.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_proposals_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'totalrecall.proposals_store'`

- [ ] **Step 3: Implement**

`src/totalrecall/proposals_store.py`:
```python
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from typing import Optional
from . import paths


@dataclass
class Proposal:
    id: str
    pattern_id: str
    target_file: str
    rule_text: str
    rationale: str
    status: str = "drafted"      # drafted | applied | rejected | stale
    created_at: str = ""
    applied_at: Optional[str] = None


def _load_raw() -> dict:
    p = paths.proposals_path()
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def all() -> list[Proposal]:
    return [Proposal(**d) for d in _load_raw().values()]


def get(pid: str) -> Optional[Proposal]:
    d = _load_raw().get(pid)
    return Proposal(**d) if d else None


def upsert(prop: Proposal) -> None:
    paths.ensure_dirs()
    data = _load_raw()
    data[prop.id] = asdict(prop)
    paths.proposals_path().write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                      encoding="utf-8")


def by_status(status: str) -> list[Proposal]:
    return [p for p in all() if p.status == status]


def rejected_pattern_ids() -> set[str]:
    return {p.pattern_id for p in all() if p.status == "rejected"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_proposals_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/proposals_store.py tests/test_proposals_store.py
git commit -m "feat: proposals_store (Proposal model + proposals.json CRUD)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: proposer candidate selection

**Files:**
- Create: `src/totalrecall/proposer.py`
- Test: `tests/test_proposer_select.py`

- [ ] **Step 1: Write the failing test**

`tests/test_proposer_select.py`:
```python
from datetime import datetime, timezone
from totalrecall import proposer, patterns_store, proposals_store, paths
from totalrecall.models import Pattern
from totalrecall.proposals_store import Proposal

NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)

def _p(pid, occ, applied_at=None, status="active"):
    return Pattern(pid, f"t-{pid}", "c", "llm", f"d-{pid}",
                   "2026-06-01T00:00:00Z", "2026-06-14T00:00:00Z", occ, 3,
                   status=status, applied_at=applied_at)

def test_selects_recurring_unaddressed_by_strength(home):
    paths.ensure_dirs()
    patterns_store.save(_p("hi", 9))                       # recurring, eligible
    patterns_store.save(_p("lo", 1))                       # below min_occ -> excluded
    patterns_store.save(_p("applied", 8, applied_at="2026-06-10T00:00:00Z"))  # already applied
    patterns_store.save(_p("mid", 4))                      # eligible
    cands = proposer.select_candidates(top_n=10, min_occ=3, now=NOW)
    ids = [p.id for p in cands]
    assert ids == ["hi", "mid"]                            # strength order, lo/applied excluded

def test_excludes_rejected(home):
    paths.ensure_dirs()
    patterns_store.save(_p("rej", 9))
    proposals_store.upsert(Proposal("p-rej", "rej", "f", "r", "why", status="rejected"))
    assert proposer.select_candidates(top_n=10, min_occ=3, now=NOW) == []

def test_respects_top_n(home):
    paths.ensure_dirs()
    for i, occ in enumerate([9, 8, 7]):
        patterns_store.save(_p(f"x{i}", occ))
    assert len(proposer.select_candidates(top_n=2, min_occ=3, now=NOW)) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_proposer_select.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'totalrecall.proposer'`

- [ ] **Step 3: Implement**

`src/totalrecall/proposer.py`:
```python
from __future__ import annotations
from datetime import datetime
from . import patterns_store, proposals_store
from .strength import strength


def select_candidates(top_n: int, min_occ: int, now: datetime):
    rejected = proposals_store.rejected_pattern_ids()
    elig = [
        p for p in patterns_store.all()
        if p.occurrences >= min_occ
        and p.status == "active"
        and not p.applied_at
        and p.id not in rejected
    ]
    elig.sort(key=lambda p: strength(p, now), reverse=True)
    return elig[:top_n]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_proposer_select.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/proposer.py tests/test_proposer_select.py
git commit -m "feat: proposer candidate selection" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: rule-drafting skill template

**Files:**
- Create: `skills/totalrecall-propose/SKILL.md`
- Test: `tests/test_propose_skill.py`

- [ ] **Step 1: Write the failing test**

`tests/test_propose_skill.py`:
```python
from pathlib import Path

SKILL = Path("skills/totalrecall-propose/SKILL.md")

def test_skill_specifies_json_object_and_fields():
    text = SKILL.read_text(encoding="utf-8")
    assert "JSON object" in text
    for k in ["rule_text", "rationale", "target_file"]:
        assert k in text
    assert "existing rules" in text.lower()   # instructs to avoid duplicates
    assert "CLAUDE.md" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_propose_skill.py -v`
Expected: FAIL — `FileNotFoundError`

- [ ] **Step 3: Implement**

`skills/totalrecall-propose/SKILL.md`:
```markdown
---
name: totalrecall-propose
description: Draft a single concise CLAUDE.md rule that would prevent a recurring AI-collaboration friction. Invoked headless by TotalRecall.
---

# TotalRecall — Rule Proposer

You are given ONE recurring friction pattern plus the user's EXISTING managed rules and a
sample of their CLAUDE.md style. Draft ONE concise rule that would prevent this friction.

## Input (in the prompt)
- `pattern`: { title, description, phase2_hint, occurrences, evidence_snippets }
- `existing_rules`: current content of the managed rules file (avoid duplicating these)
- `claude_md_sample`: first lines of the user's CLAUDE.md (match this voice/format)

## Rules for your draft
- One actionable directive, imperative voice, matching the CLAUDE.md style.
- Concrete and verifiable (e.g. "On Windows, default to PowerShell; use Bash only for POSIX scripts").
- Do NOT duplicate or contradict an existing rule. If the existing rules already cover it,
  set `rule_text` to "" (empty).
- `target_file` is always "~/.claude/totalrecall-rules.md" for this version.

## Output
Output ONLY a JSON object (no prose, no code fences):
```
{ "rule_text": "<the rule, or empty string>", "rationale": "<one sentence why>", "target_file": "~/.claude/totalrecall-rules.md" }
```
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_propose_skill.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/totalrecall-propose/SKILL.md tests/test_propose_skill.py
git commit -m "feat: totalrecall-propose skill (rule-drafting prompt)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: proposer drafting + proposals.md

**Files:**
- Modify: `src/totalrecall/proposer.py`
- Test: `tests/test_proposer_draft.py`

- [ ] **Step 1: Write the failing test**

`tests/test_proposer_draft.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_proposer_draft.py -v`
Expected: FAIL — `AttributeError: module 'totalrecall.proposer' has no attribute 'propose'`

- [ ] **Step 3: Implement**

Add to `src/totalrecall/proposer.py` (new imports at top + functions). Top of file becomes:
```python
from __future__ import annotations
import json
import os
from datetime import datetime
from pathlib import Path
from . import patterns_store, proposals_store, paths, config, orchestrator
from .strength import strength
from .proposals_store import Proposal

SKILL_PATH = Path(__file__).resolve().parent.parent.parent / "skills" / "totalrecall-propose" / "SKILL.md"
```
Then append:
```python
def _existing_rules_text(rules_file: str) -> str:
    p = Path(os.path.expanduser(rules_file))
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _claude_md_sample(claude_md: str) -> str:
    p = Path(os.path.expanduser(claude_md))
    if not p.exists():
        return ""
    return "\n".join(p.read_text(encoding="utf-8").splitlines()[:40])


def _build_prompt(pattern, existing_rules: str, claude_md_sample: str) -> str:
    skill = SKILL_PATH.read_text(encoding="utf-8") if SKILL_PATH.exists() else ""
    payload = {
        "pattern": {"title": pattern.title, "description": pattern.description,
                    "phase2_hint": pattern.phase2_hint, "occurrences": pattern.occurrences,
                    "evidence_snippets": [e.session_id for e in pattern.evidence[:5]]},
        "existing_rules": existing_rules,
        "claude_md_sample": claude_md_sample,
    }
    return (skill + "\n\n# INPUT\n```json\n" + json.dumps(payload, ensure_ascii=False)
            + "\n```\n\nReturn ONLY the JSON object.")


def _extract_json_object(text: str):
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def _draft(pattern, cfg, model, runner) -> dict | None:
    prompt = _build_prompt(pattern, _existing_rules_text(cfg.rules_file),
                           _claude_md_sample(cfg.claude_md))
    env = dict(os.environ)
    env[cfg.analysis_marker_env] = "1"
    raw = runner(prompt, model, str(paths.analysis_cwd()), env)
    try:
        result_text = json.loads(raw).get("result", "")
    except json.JSONDecodeError:
        result_text = raw
    return _extract_json_object(result_text)


def _render_md(props: list) -> None:
    lines = ["# TotalRecall — 规则提案 (proposals)", ""]
    drafted = [p for p in props if p.status == "drafted"]
    if not drafted:
        lines.append("_(暂无待批提案)_")
    for p in drafted:
        lines.append(f"### [{p.id}] {p.pattern_id}")
        lines.append("```")
        lines.append(p.rule_text)
        lines.append("```")
        lines.append(f"依据: {p.rationale}")
        lines.append(f"应用: `totalrecall apply {p.id}`  ·  拒绝: `totalrecall reject {p.id}`")
        lines.append("")
    paths.ensure_dirs()
    paths.proposals_md_path().write_text("\n".join(lines) + "\n", encoding="utf-8")


def propose(top_n: int, min_occ: int, now: datetime, model: str,
            runner=orchestrator.default_runner) -> int:
    cfg = config.load()
    existing_pattern_ids = {p.pattern_id for p in proposals_store.all()
                            if p.status in ("drafted", "applied")}
    created = 0
    for pat in select_candidates(top_n, min_occ, now):
        if pat.id in existing_pattern_ids:
            continue                          # idempotent: don't redraft
        draft = _draft(pat, cfg, model, runner)
        if not draft or not (draft.get("rule_text") or "").strip():
            continue                          # skill says already-covered -> skip
        prop = Proposal(
            id=f"p-{pat.id}", pattern_id=pat.id,
            target_file=draft.get("target_file", cfg.rules_file),
            rule_text=draft["rule_text"].strip(), rationale=draft.get("rationale", ""),
            status="drafted", created_at=now.isoformat(),
        )
        proposals_store.upsert(prop)
        created += 1
    _render_md(proposals_store.all())
    return created
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_proposer_draft.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/proposer.py tests/test_proposer_draft.py
git commit -m "feat: proposer drafts rules via claude -p, writes proposals.{json,md}" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: applier — managed rules file + @import injection

**Files:**
- Create: `src/totalrecall/applier.py`
- Test: `tests/test_applier_files.py`

- [ ] **Step 1: Write the failing test**

`tests/test_applier_files.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_applier_files.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'totalrecall.applier'`

- [ ] **Step 3: Implement**

`src/totalrecall/applier.py`:
```python
from __future__ import annotations
import os
from pathlib import Path
from .proposals_store import Proposal


def _marker(pattern_id: str) -> str:
    return f"<!-- pattern: {pattern_id} -->"


def write_rule(rules_path, prop: Proposal, occ: int, last: str) -> bool:
    """Append a managed rule block keyed by pattern id. No-op if the marker exists."""
    rules_path = Path(rules_path)
    existing = rules_path.read_text(encoding="utf-8") if rules_path.exists() else ""
    if _marker(prop.pattern_id) in existing:
        return False
    header = ("<!-- Managed by TotalRecall. Edit/remove freely; blocks keyed by pattern id. -->\n\n"
              if not existing else "")
    block = (f"{_marker(prop.pattern_id)}\n- {prop.rule_text}\n"
             f"  _(TotalRecall: 反复 {occ} 次 · 最近 {last})_\n\n")
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(existing + header + block, encoding="utf-8")
    return True


def ensure_import(claude_md_path, rules_filename: str) -> bool:
    """Add a one-time `@<rules_filename>` import to CLAUDE.md (backed up). No-op if present."""
    claude_md_path = Path(claude_md_path)
    text = claude_md_path.read_text(encoding="utf-8") if claude_md_path.exists() else ""
    line = f"@{rules_filename}"
    if line in text:
        return False
    if claude_md_path.exists():
        backup = claude_md_path.with_name(claude_md_path.name + ".bak-totalrecall")
        backup.write_text(text, encoding="utf-8")
    claude_md_path.parent.mkdir(parents=True, exist_ok=True)
    sep = "" if (text == "" or text.endswith("\n")) else "\n"
    claude_md_path.write_text(text + sep + line + "\n", encoding="utf-8")
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_applier_files.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/applier.py tests/test_applier_files.py
git commit -m "feat: applier writes managed rules file + idempotent @import with backup" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: applier — apply / reject orchestration (under worker lock)

**Files:**
- Modify: `src/totalrecall/applier.py`
- Test: `tests/test_applier_apply.py`

- [ ] **Step 1: Write the failing test**

`tests/test_applier_apply.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_applier_apply.py -v`
Expected: FAIL — `AttributeError: module 'totalrecall.applier' has no attribute 'apply'`

- [ ] **Step 3: Implement**

Add to the top imports of `src/totalrecall/applier.py`:
```python
from datetime import datetime
from . import patterns_store, proposals_store
from .locking import try_worker_lock
```
Append to `src/totalrecall/applier.py`:
```python
def apply(ids, cfg, now: datetime) -> int:
    """Apply drafted proposals: write rule, inject import, record on Pattern.
    Acquires the worker lock to avoid racing the background worker's pattern writes."""
    rules_path = Path(os.path.expanduser(cfg.rules_file))
    claude_md = Path(os.path.expanduser(cfg.claude_md))
    applied = 0
    with try_worker_lock() as got:
        if not got:
            raise RuntimeError("worker busy; try again shortly")
        for pid in ids:
            prop = proposals_store.get(pid)
            if not prop or prop.status != "drafted":
                continue
            pat = patterns_store.get(prop.pattern_id)
            if pat is None:                       # synth merged/removed it
                prop.status = "stale"
                proposals_store.upsert(prop)
                continue
            write_rule(rules_path, prop, occ=pat.occurrences, last=pat.last_seen[:10])
            ensure_import(claude_md, rules_path.name)
            pat.applied_at = now.isoformat()
            pat.applied_rule = prop.rule_text
            patterns_store.save(pat)
            prop.status = "applied"
            prop.applied_at = now.isoformat()
            proposals_store.upsert(prop)
            applied += 1
    return applied


def reject(ids) -> int:
    n = 0
    for pid in ids:
        prop = proposals_store.get(pid)
        if prop and prop.status == "drafted":
            prop.status = "rejected"
            proposals_store.upsert(prop)
            n += 1
    return n
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_applier_apply.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/applier.py tests/test_applier_apply.py
git commit -m "feat: applier.apply/reject (lock-guarded, records applied_at, handles stale)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: render — Phase-2 status sections

**Files:**
- Modify: `src/totalrecall/render.py`
- Test: `tests/test_render_phase2.py`

- [ ] **Step 1: Write the failing test**

`tests/test_render_phase2.py`:
```python
from datetime import datetime, timezone
from totalrecall import render, patterns_store, paths
from totalrecall.models import Pattern, Evidence

NOW = datetime(2026, 6, 30, tzinfo=timezone.utc)

def _p(pid, applied_at=None, status="active", ev_ts=None, rule=None):
    ev = [Evidence("s", "claude-code", [1], ev_ts, "h")] if ev_ts else []
    return Pattern(pid, f"T {pid}", "repeated-correction", "llm", f"d {pid}",
                   "2026-06-01T00:00:00Z", "2026-06-14T00:00:00Z", 5, 3,
                   evidence=ev, status=status, applied_at=applied_at, applied_rule=rule)

def test_phase2_sections(home):
    paths.ensure_dirs()
    patterns_store.save(_p("resolved1", applied_at="2026-06-10T00:00:00Z",
                           ev_ts="2026-06-05T00:00:00Z", rule="rule A"))   # -> resolved
    patterns_store.save(_p("ineff1", applied_at="2026-06-10T00:00:00Z",
                           status="ineffective", rule="rule B"))           # -> ineffective
    patterns_store.save(_p("pending1", applied_at="2026-06-28T00:00:00Z", rule="rule C"))  # within window
    render.write(now=NOW, n_sessions=50, n_projects=5)
    text = paths.insights_path().read_text(encoding="utf-8")
    assert "✅ 已解决" in text and "T resolved1" in text
    assert "⚠️ 修复无效" in text and "T ineff1" in text
    assert "⏳ 已应用待验证" in text and "T pending1" in text
    assert "rule A" in text                      # shows the applied rule
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_render_phase2.py -v`
Expected: FAIL — `✅ 已解决` not in text

- [ ] **Step 3: Implement**

In `src/totalrecall/render.py`, `import` nothing new (uses existing `derive_status`). Inside `write`, just before the final `paths.ensure_dirs()` line, insert a Phase-2 block:
```python
    # --- Phase 2: applied-rule outcomes ---
    applied = [p for p in patterns if p.applied_at]
    if applied:
        buckets = {"resolved": [], "ineffective": [], "pending": []}
        for p in applied:
            st = derive_status(p, now)
            buckets.get(st if st in ("resolved", "ineffective") else "pending").append(p)
        lines.append("")
        lines.append("## 🔧 Phase 2 — 已应用规则的效果")
        for key, head in (("resolved", "✅ 已解决"), ("pending", "⏳ 已应用待验证"),
                          ("ineffective", "⚠️ 修复无效")):
            ps = buckets[key]
            lines.append(f"### {head} ({len(ps)})")
            for p in ps:
                lines.append(f"- **{p.title}** — 规则: {p.applied_rule or '(?)'}")
```
(Place this block AFTER the "🧰 给 Phase 2 的候选改进" section and BEFORE `paths.ensure_dirs()`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_render_phase2.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/render.py tests/test_render_phase2.py
git commit -m "feat: insights.md shows applied-rule outcomes (resolved/pending/ineffective)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: CLI — propose / apply / reject / proposals

**Files:**
- Modify: `src/totalrecall/cli.py`
- Test: `tests/test_cli_phase2.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli_phase2.py`:
```python
from totalrecall import cli

def test_dispatch_phase2(home, monkeypatch):
    called = {}
    monkeypatch.setattr(cli.proposer, "propose",
                        lambda top_n, min_occ, now, model: called.setdefault("propose", True) or 1)
    monkeypatch.setattr(cli.applier, "apply",
                        lambda ids, cfg, now: called.setdefault("apply", ids) or len(ids))
    monkeypatch.setattr(cli.applier, "reject",
                        lambda ids: called.setdefault("reject", ids) or len(ids))
    assert cli.main(["propose"]) == 0 and called.get("propose")
    assert cli.main(["apply", "p-a", "p-b"]) == 0 and called["apply"] == ["p-a", "p-b"]
    assert cli.main(["reject", "p-a"]) == 0 and called["reject"] == ["p-a"]

def test_proposals_lists(home, capsys):
    from totalrecall import proposals_store
    from totalrecall.proposals_store import Proposal
    from totalrecall import paths
    paths.ensure_dirs()
    proposals_store.upsert(Proposal("p-a", "pat", "f", "r", "why", status="drafted"))
    assert cli.main(["proposals"]) == 0
    assert "p-a" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli_phase2.py -v`
Expected: FAIL — argparse error: invalid choice 'propose'

- [ ] **Step 3: Implement**

In `src/totalrecall/cli.py`, extend the import line to include the new modules:
```python
from . import (hookinstall, worker, reconcile, synth, config, ledger,
               patterns_store, hookcmd, queue, proposer, applier, proposals_store)
```
Add a small helper near `_cmd_status`:
```python
def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _cmd_proposals() -> int:
    for p in proposals_store.all():
        print(f"{p.id}\t{p.status}\t{p.pattern_id}")
    return 0
```
Register subparsers (after the existing `sub.add_parser("hook")` line):
```python
    sub.add_parser("propose")
    p_apply = sub.add_parser("apply"); p_apply.add_argument("ids", nargs="+")
    p_reject = sub.add_parser("reject"); p_reject.add_argument("ids", nargs="+")
    sub.add_parser("proposals")
```
Add dispatch (before the final `return 1`):
```python
    if args.cmd == "propose":
        cfg = config.load()
        n = proposer.propose(top_n=cfg.propose_top_n, min_occ=cfg.propose_min_occ,
                             now=_now(), model=cfg.synth_model)
        print(f"drafted: {n}  ->  review ~/.totalrecall/proposals.md")
        return 0
    if args.cmd == "apply":
        try:
            n = applier.apply(args.ids, config.load(), now=_now())
        except RuntimeError as e:
            print(str(e)); return 1
        print(f"applied: {n}"); return 0
    if args.cmd == "reject":
        print(f"rejected: {applier.reject(args.ids)}"); return 0
    if args.cmd == "proposals":
        return _cmd_proposals()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli_phase2.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/cli.py tests/test_cli_phase2.py
git commit -m "feat: CLI propose/apply/reject/proposals" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: Full suite + README note

**Files:**
- Modify: `README.md`
- Test: full suite

- [ ] **Step 1: Run the entire suite**

Run: `python -m pytest -q`
Expected: ALL PASS (Phase-1 65 + Phase-2 additions)

- [ ] **Step 2: Add a Phase-2 section to README**

Append to `README.md`:
```markdown
## Phase 2 — rule proposals (closed loop)

`totalrecall propose` drafts CLAUDE.md rules from your top recurring friction →
review `~/.totalrecall/proposals.md` → `totalrecall apply <id…>` writes them to a
managed `~/.claude/totalrecall-rules.md` (`@`-imported once into CLAUDE.md, backed up).
The verifier then marks each applied pattern **resolved** (no recurrence in N days) or
**ineffective** (recurs after apply) — shown in `insights.md`. `totalrecall reject <id…>`
declines a draft. Commands: `propose` · `apply` · `reject` · `proposals`.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README Phase 2 section" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage (spec §→task):**
- §4.1 proposer (candidate select + claude -p draft + proposals.md) → Tasks 8, 9, 10.
- §4.2 applier (managed rules file, idempotent marker, @import + backup, pattern writeback, reject, stale) → Tasks 11, 12.
- §4.3 verifier (ineffective on recurrence incl. override-resolved; resolved on no-recurrence; pin applied into catalog) → Tasks 5, 4, 6.
- §5.1 Proposal model + proposals.json → Task 7. §5.2 Pattern fields + sticky status → Tasks 1, 4. §5.3 rules file + @import → Task 11. §5.4 proposals.md → Task 10.
- §6 data flow → Tasks 10 (propose), 12 (apply), 5+4 (verify). §7 state machine → Tasks 4, 5.
- §8 CLI → Task 14. §9 config → Task 2. §10 idempotency/backup/**worker-lock**/stale/authority → Tasks 11, 12. §11 testing → every task TDD. §12 scope → Tasks 1–15 (CLAUDE.md only; manual; single target).
- §13 risks: #1 merge-reliability mitigated by Task 6 (pin) + pattern_id reuse; #2 false-resolved (render wording "已应用待验证/已解决"); #3 draft quality (human approval gate = Task 12 apply is explicit); #4 @import path (Task 11 writes `@totalrecall-rules.md` relative to CLAUDE.md dir — confirm in manual smoke); #5 timestamp format (Tasks 4/5 parse both via fromisoformat).

**Placeholder scan:** none — all steps carry runnable code. (Task 14's intermediate `print` line is explicitly corrected to the final form in the same step.)

**Type consistency:** `Proposal(id, pattern_id, target_file, rule_text, rationale, status, created_at, applied_at)` identical across Tasks 7/10/11/12/14. `proposer.propose(top_n, min_occ, now, model, runner=...)` and `proposer.select_candidates(top_n, min_occ, now)` match their callers (Task 14, Task 10). `applier.write_rule(path, prop, occ, last)`, `applier.ensure_import(path, filename)`, `applier.apply(ids, cfg, now)`, `applier.reject(ids)` match Tasks 11/12/14. `Pattern.applied_at/applied_rule` (Task 1) used in Tasks 4/5/6/12/13. `derive_status(p, now, resolved_after_days=14)` (Task 4) called by render (Task 13, default arg) — consistent.

**Deferred (intentional, logged):** project-level CLAUDE.md / memory routing, skills/subagent generation, automatic propose/apply — all out of MVP scope per spec §12. The `propose` CLI uses `cfg.synth_model` (Sonnet) for drafting quality.

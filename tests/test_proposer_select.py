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

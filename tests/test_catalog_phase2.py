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

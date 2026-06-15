from datetime import datetime, timezone
from totalrecall import catalog, patterns_store, paths
from totalrecall.models import Pattern

NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)

def _p(pid, occ, last):
    return Pattern(pid, f"title-{pid}", "c", "llm", f"desc-{pid}",
                   "2026-06-01T00:00:00Z", last, occ, 3)

def test_topk_orders_by_strength_and_truncates(home):
    paths.ensure_dirs()
    patterns_store.save(_p("weak", 1, "2026-05-01T00:00:00Z"))
    patterns_store.save(_p("strong", 9, "2026-06-15T00:00:00Z"))
    patterns_store.save(_p("mid", 3, "2026-06-14T00:00:00Z"))
    cat = catalog.build(top_k=2, now=NOW)
    assert [c["id"] for c in cat] == ["strong", "mid"]
    assert set(cat[0].keys()) == {"id", "title", "category", "description"}

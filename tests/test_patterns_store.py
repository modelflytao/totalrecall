from totalrecall import patterns_store, paths
from totalrecall.models import Pattern, Evidence

def _p(pid="x"):
    return Pattern(pid, "T", "tool-error", "llm", "d",
                   "2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z", 1, 2,
                   evidence=[Evidence("s1", "claude-code", [1], None, "h1")])

def test_save_and_load(home):
    paths.ensure_dirs()
    patterns_store.save(_p("alpha"))
    got = patterns_store.get("alpha")
    assert got.id == "alpha" and got.occurrences == 1

def test_all_and_index(home):
    paths.ensure_dirs()
    patterns_store.save(_p("alpha"))
    patterns_store.save(_p("beta"))
    ids = {p.id for p in patterns_store.all()}
    assert ids == {"alpha", "beta"}
    assert set(patterns_store.index_ids()) == {"alpha", "beta"}

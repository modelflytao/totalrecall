from totalrecall import synth, patterns_store, paths, config
from totalrecall.models import Pattern

def _p(pid, applied_at=None):
    return Pattern(pid, f"t-{pid}", "c", "llm", f"d-{pid}",
                   "2026-06-01T00:00:00Z", "2026-06-14T00:00:00Z", 2, 3,
                   applied_at=applied_at)

def test_synth_excludes_applied_from_merge(home, monkeypatch):
    paths.ensure_dirs()
    patterns_store.save(_p("applied", applied_at="2026-06-10T00:00:00Z"))
    patterns_store.save(_p("dup1"))
    patterns_store.save(_p("dup2"))
    seen = {}
    def fake_ask(patterns, model):
        seen["ids"] = {p.id for p in patterns}
        return []   # no merges
    monkeypatch.setattr(synth, "_ask_merges", fake_ask)
    synth.run(config.load())
    assert seen["ids"] == {"dup1", "dup2"}           # applied pattern not a merge candidate
    assert patterns_store.get("applied") is not None  # untouched

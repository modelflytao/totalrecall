from datetime import datetime, timezone
from totalrecall import synth, patterns_store, paths, config
from totalrecall.models import Pattern, Evidence

def _p(pid, desc):
    return Pattern(pid, f"T {pid}", "repeated-correction", "llm", desc,
                   "2026-06-01T00:00:00Z", "2026-06-14T00:00:00Z", 2, 3,
                   evidence=[Evidence("s1", "claude-code", [1], None, "h" + pid + "1"),
                             Evidence("s2", "claude-code", [2], None, "h" + pid + "2")])

def test_synth_merges_pairs_returned_by_model(home, monkeypatch):
    paths.ensure_dirs()
    patterns_store.save(_p("pwsh-vs-bash", "use powershell not bash"))
    patterns_store.save(_p("use-powershell", "prefer powershell over bash"))
    # fake model says: merge use-powershell INTO pwsh-vs-bash
    monkeypatch.setattr(synth, "_ask_merges",
                        lambda patterns, model: [["pwsh-vs-bash", "use-powershell"]])
    synth.run(config.load())
    ids = {p.id for p in patterns_store.all()}
    assert ids == {"pwsh-vs-bash"}
    survivor = patterns_store.get("pwsh-vs-bash")
    assert survivor.occurrences == 4                 # 2 + 2 combined
    assert paths.insights_path().exists()            # narrative re-rendered

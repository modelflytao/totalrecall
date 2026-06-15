from totalrecall import merger, patterns_store, paths
from totalrecall.models import Finding, Evidence

def _f(pattern_id=None, slug=None, title_desc="Use PowerShell not bash", sid="s1", h="h1"):
    return Finding(category="repeated-correction", description=title_desc, severity=3,
                   evidence=Evidence(sid, "claude-code", [4], "2026-06-10T00:00:00Z", h),
                   pattern_id=pattern_id, slug=slug)

NOW = "2026-06-10T00:00:00Z"

def test_new_pattern_created_from_slug(home):
    paths.ensure_dirs()
    merger.merge([_f(slug="pwsh-vs-bash")], now=NOW)
    p = patterns_store.get("pwsh-vs-bash")
    assert p is not None and p.occurrences == 1

def test_reuse_pattern_id_increments(home):
    paths.ensure_dirs()
    merger.merge([_f(slug="pwsh-vs-bash")], now=NOW)
    merger.merge([_f(pattern_id="pwsh-vs-bash", sid="s2", h="h2")], now="2026-06-11T00:00:00Z")
    p = patterns_store.get("pwsh-vs-bash")
    assert p.occurrences == 2 and len(p.evidence) == 2
    assert p.last_seen == "2026-06-11T00:00:00Z"

def test_evidence_hash_dedup(home):
    paths.ensure_dirs()
    merger.merge([_f(slug="pwsh-vs-bash", h="same")], now=NOW)
    merger.merge([_f(pattern_id="pwsh-vs-bash", h="same")], now=NOW)  # same evidence hash
    p = patterns_store.get("pwsh-vs-bash")
    assert p.occurrences == 1 and len(p.evidence) == 1   # deduped, not counted twice

def test_fuzzy_title_match_when_no_id(home):
    paths.ensure_dirs()
    merger.merge([_f(slug="pwsh-vs-bash", title_desc="Use PowerShell not bash")], now=NOW)
    # near-identical description, different slug, no pattern_id -> should merge, not create new
    merger.merge([_f(slug="use-powershell", title_desc="Use PowerShell, not bash", h="h2")], now=NOW)
    assert len(patterns_store.all()) == 1

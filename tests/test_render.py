from datetime import datetime, timezone
from totalrecall import render, patterns_store, paths
from totalrecall.models import Pattern, Evidence

NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)

def _p(pid, occ, hint=None):
    return Pattern(pid, f"Title {pid}", "repeated-correction", "llm", f"Desc {pid}",
                   "2026-06-01T00:00:00Z", "2026-06-14T00:00:00Z", occ, 3,
                   evidence=[Evidence("s1", "claude-code", [4], None, "h")], phase2_hint=hint)

def test_render_writes_sections_and_top_order(home):
    paths.ensure_dirs()
    patterns_store.save(_p("weak", 1))
    patterns_store.save(_p("strong", 8, hint="add CLAUDE.md rule"))
    render.write(now=NOW, n_sessions=12, n_projects=3)
    text = paths.insights_path().read_text(encoding="utf-8")
    assert "# TotalRecall" in text
    assert "已分析 12 个会话" in text
    assert "🔥" in text and "🧰" in text
    assert text.index("Title strong") < text.index("Title weak")   # by strength
    assert "add CLAUDE.md rule" in text                            # phase2 hint surfaced

def test_render_empty_store(home):
    paths.ensure_dirs()
    render.write(now=NOW, n_sessions=0, n_projects=0)
    assert paths.insights_path().exists()

def test_render_recurring_section_excludes_singletons(home):
    paths.ensure_dirs()
    patterns_store.save(_p("recurs", 5))
    patterns_store.save(_p("oneoff", 1))
    render.write(now=NOW, n_sessions=10, n_projects=2)
    text = paths.insights_path().read_text(encoding="utf-8")
    assert "🔁" in text
    recurring_section = text.split("🔁")[1].split("\n## ")[0]   # the 🔁 section only
    assert "Title recurs" in recurring_section
    assert "Title oneoff" not in recurring_section            # singleton excluded here
    assert "1 个一次性" in text                                # singleton count noted
    assert "反复出现(≥2次) 1" in text                          # stats line

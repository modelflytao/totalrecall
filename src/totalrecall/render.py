from __future__ import annotations
from datetime import datetime
from . import patterns_store, paths
from .strength import strength, derive_status


def write(now: datetime, n_sessions: int, n_projects: int) -> None:
    patterns = sorted(patterns_store.all(), key=lambda p: strength(p, now), reverse=True)
    lines: list[str] = []
    lines.append("# TotalRecall — 你与 AI 的协作摩擦档案")
    lines.append(f"_最后更新 {now.isoformat()} · 已分析 {n_sessions} 个会话 · 跨 {n_projects} 个项目_")
    lines.append("")
    lines.append("## 🔥 当前最该处理的摩擦 (按 strength)")
    if not patterns:
        lines.append("_(还没有累积到摩擦模式)_")
    for i, p in enumerate(patterns[:10], 1):
        date = p.last_seen[:10]
        lines.append(f"{i}. **{p.title}** — {p.category} · 出现 {p.occurrences} 次 · 最近 {date}")
        lines.append(f"   {p.description}")
        refs = ", ".join(e.session_id for e in p.evidence[:5])
        hint = f"   建议(Phase 2): {p.phase2_hint}" if p.phase2_hint else ""
        lines.append(f"   证据: {refs}{hint}")
    lines.append("")
    lines.append("## 📈 趋势")
    active = [p for p in patterns if derive_status(p, now) == "active"]
    fading = [p for p in patterns if derive_status(p, now) == "fading"]
    lines.append(f"- 活跃模式 {len(active)} · 消退中 {len(fading)}")
    lines.append("")
    lines.append("## 🗂 全部模式 (按类别分组)")
    by_cat: dict[str, list] = {}
    for p in patterns:
        by_cat.setdefault(p.category, []).append(p)
    for cat, ps in sorted(by_cat.items()):
        lines.append(f"### {cat}")
        for p in ps:
            lines.append(f"- {p.title} (×{p.occurrences})")
    lines.append("")
    lines.append("## 🧰 给 Phase 2 的候选改进 (skill / agent / CLAUDE.md)")
    hints = [p for p in patterns if p.phase2_hint]
    if not hints:
        lines.append("_(暂无)_")
    for p in hints:
        lines.append(f"- **{p.title}** → {p.phase2_hint}")

    paths.ensure_dirs()
    paths.insights_path().write_text("\n".join(lines) + "\n", encoding="utf-8")

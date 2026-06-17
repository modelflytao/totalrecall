from __future__ import annotations
from datetime import datetime
from . import patterns_store, paths
from .strength import strength, derive_status


def write(now: datetime, n_sessions: int, n_projects: int) -> None:
    patterns = sorted(patterns_store.all(), key=lambda p: strength(p, now), reverse=True)
    recurring = [p for p in patterns if p.occurrences >= 2]   # the actionable signal
    singles = [p for p in patterns if p.occurrences < 2]      # mostly one-off noise
    lines: list[str] = []
    lines.append("# TotalRecall — 你与 AI 的协作摩擦档案")
    lines.append(f"_最后更新 {now.isoformat()} · 已分析 {n_sessions} 个会话 · 跨 {n_projects} 个项目_")
    lines.append(f"_模式 {len(patterns)} 个 · 反复出现(≥2次) {len(recurring)} · 一次性 {len(singles)}_")
    lines.append("")
    lines.append("## 🔥 当前最该处理的摩擦 (按 strength)")
    if not patterns:
        lines.append("_(还没有累积到摩擦模式)_")
    _urgent = [p for p in patterns if derive_status(p, now) not in ("resolved", "ineffective")]
    for i, p in enumerate(_urgent[:15], 1):
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
    lines.append("## 🔁 反复出现的摩擦 (≥2次, 按类别)")
    if not recurring:
        lines.append("_(暂无反复模式)_")
    else:
        by_cat: dict[str, list] = {}
        for p in recurring:
            by_cat.setdefault(p.category, []).append(p)
        for cat, ps in sorted(by_cat.items()):
            lines.append(f"### {cat}")
            for p in sorted(ps, key=lambda x: x.occurrences, reverse=True):
                lines.append(f"- {p.title} (×{p.occurrences})")
    if singles:
        lines.append("")
        lines.append(f"_(另有 {len(singles)} 个一次性摩擦未在此列出 — 多为各会话独有、不构成可操作模式)_")
    lines.append("")
    lines.append("## 🧰 给 Phase 2 的候选改进 (skill / agent / CLAUDE.md)")
    hints = [p for p in recurring if p.phase2_hint][:20]
    if not hints:
        hints = [p for p in patterns if p.phase2_hint][:20]   # fall back before any recur
    if not hints:
        lines.append("_(暂无)_")
    for p in hints:
        lines.append(f"- **{p.title}** (×{p.occurrences}) → {p.phase2_hint}")

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

    paths.ensure_dirs()
    paths.insights_path().write_text("\n".join(lines) + "\n", encoding="utf-8")

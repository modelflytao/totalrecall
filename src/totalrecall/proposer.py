from __future__ import annotations
import json
import os
from datetime import datetime
from pathlib import Path
from . import patterns_store, proposals_store, paths, config, orchestrator
from .strength import strength
from .proposals_store import Proposal

SKILL_PATH = Path(__file__).resolve().parent.parent.parent / "skills" / "totalrecall-propose" / "SKILL.md"


def select_candidates(top_n: int, min_occ: int, now: datetime):
    rejected = proposals_store.rejected_pattern_ids()
    elig = [
        p for p in patterns_store.all()
        if p.occurrences >= min_occ
        and p.status == "active"
        and not p.applied_at
        and p.id not in rejected
    ]
    elig.sort(key=lambda p: strength(p, now), reverse=True)
    return elig[:top_n]


def _existing_rules_text(rules_file: str) -> str:
    p = Path(os.path.expanduser(rules_file))
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _claude_md_sample(claude_md: str) -> str:
    p = Path(os.path.expanduser(claude_md))
    if not p.exists():
        return ""
    return "\n".join(p.read_text(encoding="utf-8").splitlines()[:40])


def _build_prompt(pattern, existing_rules: str, claude_md_sample: str) -> str:
    skill = SKILL_PATH.read_text(encoding="utf-8") if SKILL_PATH.exists() else ""
    payload = {
        "pattern": {"title": pattern.title, "description": pattern.description,
                    "phase2_hint": pattern.phase2_hint, "occurrences": pattern.occurrences,
                    "evidence_snippets": [e.session_id for e in pattern.evidence[:5]]},
        "existing_rules": existing_rules,
        "claude_md_sample": claude_md_sample,
    }
    return (skill + "\n\n# INPUT\n```json\n" + json.dumps(payload, ensure_ascii=False)
            + "\n```\n\nReturn ONLY the JSON object.")


def _extract_json_object(text):
    if not isinstance(text, str):
        return None
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def _draft(pattern, cfg, model, runner) -> dict | None:
    prompt = _build_prompt(pattern, _existing_rules_text(cfg.rules_file),
                           _claude_md_sample(cfg.claude_md))
    env = dict(os.environ)
    env[cfg.analysis_marker_env] = "1"
    raw = runner(prompt, model, str(paths.analysis_cwd()), env)
    try:
        result_text = json.loads(raw).get("result", "")
    except json.JSONDecodeError:
        result_text = raw
    return _extract_json_object(result_text)


def _render_md(props: list) -> None:
    lines = ["# TotalRecall — 规则提案 (proposals)", ""]
    drafted = [p for p in props if p.status == "drafted"]
    if not drafted:
        lines.append("_(暂无待批提案)_")
    for p in drafted:
        lines.append(f"### [{p.id}] {p.pattern_id}")
        lines.append("```")
        lines.append(p.rule_text)
        lines.append("```")
        lines.append(f"依据: {p.rationale}")
        lines.append(f"应用: `totalrecall apply {p.id}`  ·  拒绝: `totalrecall reject {p.id}`")
        lines.append("")
    paths.ensure_dirs()
    paths.proposals_md_path().write_text("\n".join(lines) + "\n", encoding="utf-8")


def propose(top_n: int, min_occ: int, now: datetime, model: str,
            runner=orchestrator.default_runner) -> int:
    cfg = config.load()
    existing_pattern_ids = {p.pattern_id for p in proposals_store.all()
                            if p.status in ("drafted", "applied")}
    created = 0
    for pat in select_candidates(top_n, min_occ, now):
        if pat.id in existing_pattern_ids:
            continue                          # idempotent: don't redraft
        draft = _draft(pat, cfg, model, runner)
        if not draft or not (draft.get("rule_text") or "").strip():
            continue                          # skill says already-covered -> skip
        prop = Proposal(
            id=f"p-{pat.id}", pattern_id=pat.id,
            target_file=draft.get("target_file", cfg.rules_file),
            rule_text=draft["rule_text"].strip(), rationale=draft.get("rationale", ""),
            status="drafted", created_at=now.isoformat(),
        )
        proposals_store.upsert(prop)
        created += 1
    _render_md(proposals_store.all())
    return created

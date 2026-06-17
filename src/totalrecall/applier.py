from __future__ import annotations
import os
from pathlib import Path
from .proposals_store import Proposal


def _marker(pattern_id: str) -> str:
    return f"<!-- pattern: {pattern_id} -->"


def write_rule(rules_path, prop: Proposal, occ: int, last: str) -> bool:
    """Append a managed rule block keyed by pattern id. No-op if the marker exists."""
    rules_path = Path(rules_path)
    existing = rules_path.read_text(encoding="utf-8") if rules_path.exists() else ""
    if _marker(prop.pattern_id) in existing:
        return False
    header = ("<!-- Managed by TotalRecall. Edit/remove freely; blocks keyed by pattern id. -->\n\n"
              if not existing else "")
    block = (f"{_marker(prop.pattern_id)}\n- {prop.rule_text}\n"
             f"  _(TotalRecall: 反复 {occ} 次 · 最近 {last})_\n\n")
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(existing + header + block, encoding="utf-8")
    return True


def ensure_import(claude_md_path, rules_filename: str) -> bool:
    """Add a one-time `@<rules_filename>` import to CLAUDE.md (backed up). No-op if present."""
    claude_md_path = Path(claude_md_path)
    text = claude_md_path.read_text(encoding="utf-8") if claude_md_path.exists() else ""
    line = f"@{rules_filename}"
    if line in text:
        return False
    if claude_md_path.exists():
        backup = claude_md_path.with_name(claude_md_path.name + ".bak-totalrecall")
        backup.write_text(text, encoding="utf-8")
    claude_md_path.parent.mkdir(parents=True, exist_ok=True)
    sep = "" if (text == "" or text.endswith("\n")) else "\n"
    claude_md_path.write_text(text + sep + line + "\n", encoding="utf-8")
    return True

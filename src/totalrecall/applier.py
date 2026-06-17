from __future__ import annotations
import os
from datetime import datetime
from pathlib import Path
from .proposals_store import Proposal
from . import patterns_store, proposals_store
from .locking import try_worker_lock


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
    if any(ln.strip() == line for ln in text.splitlines()):   # full-line match (avoid @x.md.disabled collision)
        return False
    if claude_md_path.exists():
        backup = claude_md_path.with_name(claude_md_path.name + ".bak-totalrecall")
        backup.write_text(text, encoding="utf-8")
    claude_md_path.parent.mkdir(parents=True, exist_ok=True)
    sep = "" if (text == "" or text.endswith("\n")) else "\n"
    claude_md_path.write_text(text + sep + line + "\n", encoding="utf-8")
    return True


def apply(ids, cfg, now: datetime) -> int:
    """Apply drafted proposals: write rule, inject import, record on Pattern.
    Acquires the worker lock to avoid racing the background worker's pattern writes."""
    rules_path = Path(os.path.expanduser(cfg.rules_file))
    claude_md = Path(os.path.expanduser(cfg.claude_md))
    applied = 0
    with try_worker_lock() as got:
        if not got:
            raise RuntimeError("worker busy; try again shortly")
        for pid in ids:
            prop = proposals_store.get(pid)
            if not prop or prop.status != "drafted":
                continue
            pat = patterns_store.get(prop.pattern_id)
            if pat is None:                       # synth merged/removed it
                prop.status = "stale"
                proposals_store.upsert(prop)
                continue
            write_rule(rules_path, prop, occ=pat.occurrences, last=pat.last_seen[:10])
            ensure_import(claude_md, rules_path.name)
            pat.applied_at = now.isoformat()
            pat.applied_rule = prop.rule_text
            patterns_store.save(pat)
            prop.status = "applied"
            prop.applied_at = now.isoformat()
            proposals_store.upsert(prop)
            applied += 1
    return applied


def reject(ids) -> int:
    n = 0
    for pid in ids:
        prop = proposals_store.get(pid)
        if prop and prop.status == "drafted":
            prop.status = "rejected"
            proposals_store.upsert(prop)
            n += 1
    return n

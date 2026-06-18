from __future__ import annotations
import re
from datetime import datetime
from difflib import SequenceMatcher
from .models import Finding, Pattern
from . import patterns_store


def _ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None

SIM_THRESHOLD = 0.82


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s or "pattern")[:60]


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _find_target(f: Finding, existing: list[Pattern]) -> Pattern | None:
    if f.pattern_id:
        for p in existing:
            if p.id == f.pattern_id:
                return p
    slug = f.slug or _slugify(f.description)
    for p in existing:
        if p.id == slug:
            return p
    for p in existing:
        if _similar(p.description, f.description) >= SIM_THRESHOLD:
            return p
    return None


def _apply(p: Pattern, f: Finding, now: str) -> None:
    # Dedup occurrences by snippet OR session (occurrences = distinct sessions, I1).
    # But do NOT early-return: recency and the post-apply recurrence check must still
    # run even when the same session is re-analyzed (HOLE A — keeps the Phase-2 loop honest).
    dup = any(e.snippet_hash == f.evidence.snippet_hash
              or e.session_id == f.evidence.session_id for e in p.evidence)
    if not dup:
        p.occurrences += 1
        p.evidence.append(f.evidence)
    p.last_seen = now
    p.severity = max(p.severity, f.severity)
    if f.phase2_hint and not p.phase2_hint:
        p.phase2_hint = f.phase2_hint
    if p.source != f_source(f):
        p.source = "both"
    at, et = _ts(p.applied_at), (_ts(f.evidence.ts) or _ts(now))
    if at and et and et > at:
        p.status = "ineffective"   # post-apply recurrence (even same session) overrides resolved


def f_source(f: Finding) -> str:
    return "llm"


def merge(findings: list[Finding], now: str) -> None:
    for f in findings:
        existing = patterns_store.all()
        target = _find_target(f, existing)
        if target is None:
            pid = f.slug or _slugify(f.description)
            target = Pattern(
                id=pid, title=f.description[:80], category=f.category, source="llm",
                description=f.description, first_seen=now, last_seen=now,
                occurrences=0, severity=f.severity, evidence=[], phase2_hint=f.phase2_hint,
            )
        _apply(target, f, now)
        patterns_store.save(target)

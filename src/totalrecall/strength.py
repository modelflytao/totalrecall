from __future__ import annotations
import math
from datetime import datetime, timezone
from .models import Pattern

HALF_LIFE_DAYS = 14.0
FADING_DAYS = 30


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _days_since(ts: str, now: datetime) -> float:
    return max(0.0, (now - _parse(ts)).total_seconds() / 86400.0)


def strength(p: Pattern, now: datetime) -> float:
    recency = math.exp(-_days_since(p.last_seen, now) / HALF_LIFE_DAYS)
    return p.occurrences * recency * (p.severity / 5.0)


def derive_status(p: Pattern, now: datetime, resolved_after_days: int = 14) -> str:
    if p.status in ("resolved", "ineffective"):
        return p.status                       # sticky stored statuses
    if p.applied_at:
        recurred = any(e.ts and _parse(e.ts) > _parse(p.applied_at) for e in p.evidence)
        if not recurred and _days_since(p.applied_at, now) >= resolved_after_days:
            return "resolved"
    return "fading" if _days_since(p.last_seen, now) > FADING_DAYS else "active"

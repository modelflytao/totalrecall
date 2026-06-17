from __future__ import annotations
from datetime import datetime
from . import patterns_store, proposals_store
from .strength import strength


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

from __future__ import annotations
from datetime import datetime
from . import patterns_store
from .strength import strength


def build(top_k: int, now: datetime) -> list[dict]:
    pats = patterns_store.all()
    ranked = sorted(pats, key=lambda p: strength(p, now), reverse=True)
    chosen = list(ranked[:top_k])
    seen = {p.id for p in chosen}
    for p in pats:                       # always pin applied patterns so recurrence re-attributes
        if p.applied_at and p.id not in seen:
            chosen.append(p)
            seen.add(p.id)
    return [
        {"id": p.id, "title": p.title, "category": p.category,
         "description": p.description[:160]}
        for p in chosen
    ]

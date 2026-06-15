from __future__ import annotations
from datetime import datetime
from . import patterns_store
from .strength import strength


def build(top_k: int, now: datetime) -> list[dict]:
    ranked = sorted(patterns_store.all(), key=lambda p: strength(p, now), reverse=True)
    return [
        {"id": p.id, "title": p.title, "category": p.category,
         "description": p.description[:160]}
        for p in ranked[:top_k]
    ]

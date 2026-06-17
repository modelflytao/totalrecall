from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from typing import Optional
from . import paths


@dataclass
class Proposal:
    id: str
    pattern_id: str
    target_file: str
    rule_text: str
    rationale: str
    status: str = "drafted"      # drafted | applied | rejected | stale
    created_at: str = ""
    applied_at: Optional[str] = None


def _load_raw() -> dict:
    p = paths.proposals_path()
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def all() -> list[Proposal]:
    return [Proposal(**d) for d in _load_raw().values()]


def get(pid: str) -> Optional[Proposal]:
    d = _load_raw().get(pid)
    return Proposal(**d) if d else None


def upsert(prop: Proposal) -> None:
    paths.ensure_dirs()
    data = _load_raw()
    data[prop.id] = asdict(prop)
    paths.proposals_path().write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                      encoding="utf-8")


def by_status(status: str) -> list[Proposal]:
    return [p for p in all() if p.status == status]


def rejected_pattern_ids() -> set[str]:
    return {p.pattern_id for p in all() if p.status == "rejected"}

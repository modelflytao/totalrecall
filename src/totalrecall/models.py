from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Turn:
    idx: int
    role: str                      # "user" | "assistant" | "tool"
    ts: Optional[str]
    text: str = ""
    tool_name: Optional[str] = None
    tool_status: Optional[str] = None   # "ok" | "error"
    is_meta: bool = False
    is_sidechain: bool = False


@dataclass
class Event:
    kind: str                      # edit|revert|permission_denied|tool_error|interrupt|churn
    ts: Optional[str]
    ref: str


@dataclass
class Stats:
    n_turns: int = 0
    duration_s: float = 0.0
    n_tool_errors: int = 0
    n_edits: int = 0
    n_reverts: int = 0


@dataclass
class NormalizedSession:
    tool: str
    session_id: str
    cwd: str
    git_branch: Optional[str]
    started_at: Optional[str]
    ended_at: Optional[str]
    is_analysis_session: bool
    turns: list[Turn] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    stats: Stats = field(default_factory=Stats)


@dataclass
class Evidence:
    session_id: str
    tool: str
    turn_refs: list[int]
    ts: Optional[str]
    snippet_hash: str


@dataclass
class Finding:
    category: str
    description: str
    severity: int                  # 1..5
    evidence: Evidence
    pattern_id: Optional[str] = None
    slug: Optional[str] = None
    phase2_hint: Optional[str] = None


@dataclass
class Pattern:
    id: str
    title: str
    category: str
    source: str                    # metadata|llm|both
    description: str
    first_seen: str
    last_seen: str
    occurrences: int
    severity: int = 1
    evidence: list[Evidence] = field(default_factory=list)
    status: str = "active"         # active|fading|resolved
    phase2_hint: Optional[str] = None
    applied_at: Optional[str] = None       # when a Phase-2 rule was applied for this pattern
    applied_rule: Optional[str] = None     # the rule text that was written


def evidence_from_dict(d: dict) -> Evidence:
    return Evidence(d["session_id"], d["tool"], list(d["turn_refs"]),
                    d.get("ts"), d["snippet_hash"])


def finding_from_dict(d: dict) -> Finding:
    return Finding(
        category=d["category"], description=d["description"], severity=int(d["severity"]),
        evidence=evidence_from_dict(d["evidence"]),
        pattern_id=d.get("pattern_id"), slug=d.get("slug"), phase2_hint=d.get("phase2_hint"),
    )


def pattern_to_dict(p: Pattern) -> dict:
    return asdict(p)


def pattern_from_dict(d: dict) -> Pattern:
    return Pattern(
        id=d["id"], title=d["title"], category=d["category"], source=d["source"],
        description=d["description"], first_seen=d["first_seen"], last_seen=d["last_seen"],
        occurrences=int(d["occurrences"]), severity=int(d.get("severity", 1)),
        evidence=[evidence_from_dict(e) for e in d.get("evidence", [])],
        status=d.get("status", "active"), phase2_hint=d.get("phase2_hint"),
        applied_at=d.get("applied_at"), applied_rule=d.get("applied_rule"),
    )

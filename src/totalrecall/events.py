from __future__ import annotations
import json
from collections import Counter
from datetime import datetime
from .models import NormalizedSession, Event

CHURN_THRESHOLD = 3      # same file edited >= 3 times in a session = churn
EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}


def _parse_ts(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _file_path(turn) -> str | None:
    try:
        return json.loads(turn.text or "{}").get("file_path")
    except json.JSONDecodeError:
        return None


def extract_events(session: NormalizedSession) -> None:
    """Populate session.events (A-class) and session.stats in place."""
    events: list[Event] = []
    n_tool_errors = 0
    n_edits = 0
    file_counts: Counter[str] = Counter()

    for t in session.turns:
        if t.role != "tool":
            continue
        if t.tool_status == "error":
            n_tool_errors += 1
            events.append(Event("tool_error", t.ts, t.tool_name or "?"))
        if t.tool_name in EDIT_TOOLS:
            n_edits += 1
            fp = _file_path(t)
            if fp:
                file_counts[fp] += 1

    for fp, count in file_counts.items():
        if count >= CHURN_THRESHOLD:
            events.append(Event("churn", None, fp))

    start = _parse_ts(session.started_at)
    end = _parse_ts(session.ended_at)
    duration = (end - start).total_seconds() if start and end else 0.0

    session.events = events
    session.stats.n_turns = len(session.turns)
    session.stats.n_tool_errors = n_tool_errors
    session.stats.n_edits = n_edits
    session.stats.duration_s = duration

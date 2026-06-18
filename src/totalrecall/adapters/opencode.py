from __future__ import annotations
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from ..models import NormalizedSession, Turn, Event, Stats

EDIT_CHURN_THRESHOLD = 3


def _parse_ts(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


class OpenCodeAdapter:
    tool = "opencode"

    def parse(self, path) -> NormalizedSession:
        session_id = cwd = ""
        started_at = ended_at = None
        turns: list[Turn] = []
        events: list[Event] = []
        file_counts: Counter[str] = Counter()
        n_edits = 0
        n_tool_errors = 0
        idx = 0

        for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                o = json.loads(raw)
            except json.JSONDecodeError:
                continue
            t = o.get("type")
            if t == "meta":
                session_id = o.get("session_id") or session_id
                cwd = o.get("cwd") or cwd
                started_at = o.get("started_at")
                ended_at = o.get("ended_at")
                continue
            ts = o.get("ts")
            if t == "text":
                role = "user" if o.get("role") == "user" else "assistant"
                text = o.get("text", "")
                if text.strip():
                    turns.append(Turn(idx, role, ts, text=text)); idx += 1
            elif t == "tool":
                status = "error" if o.get("status") == "error" else "ok"
                turns.append(Turn(idx, "tool", ts, tool_name=o.get("name"),
                                  tool_status=status)); idx += 1
                if status == "error":
                    n_tool_errors += 1
                    events.append(Event("tool_error", ts, o.get("name") or "?"))
            elif t == "patch":
                for fp in o.get("files") or []:
                    file_counts[fp] += 1
                    n_edits += 1

        for fp, count in file_counts.items():
            if count >= EDIT_CHURN_THRESHOLD:
                events.append(Event("churn", None, fp))

        start, end = _parse_ts(started_at), _parse_ts(ended_at)
        duration = (end - start).total_seconds() if start and end else 0.0
        return NormalizedSession(
            tool=self.tool, session_id=session_id, cwd=cwd, git_branch=None,
            started_at=started_at, ended_at=ended_at, is_analysis_session=False,
            turns=turns, events=events,
            stats=Stats(n_turns=len(turns), duration_s=duration,
                        n_tool_errors=n_tool_errors, n_edits=n_edits),
        )

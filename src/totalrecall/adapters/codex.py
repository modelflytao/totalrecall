from __future__ import annotations
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from ..models import NormalizedSession, Turn, Event, Stats

EDIT_CHURN_THRESHOLD = 3
_TEXT_TYPES = ("input_text", "output_text")


def _parse_ts(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _text_from_content(content) -> str:
    if not isinstance(content, list):
        return ""
    return "\n".join(i.get("text", "") for i in content
                     if isinstance(i, dict) and i.get("type") in _TEXT_TYPES)


class CodexAdapter:
    tool = "codex"

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
            ts = o.get("timestamp")
            if ts:
                started_at = started_at or ts
                ended_at = ts
            typ = o.get("type")
            p = o.get("payload")
            if not isinstance(p, dict):
                continue
            if typ == "session_meta":
                session_id = p.get("id") or session_id
                cwd = p.get("cwd") or cwd
                continue
            ptype = p.get("type")
            if typ == "event_msg":
                if ptype == "turn_aborted":
                    events.append(Event("interrupt", ts, str(p.get("turn_id", "?"))))
                continue
            if typ != "response_item":
                continue
            if ptype == "message":
                role = p.get("role")
                if role in ("user", "assistant"):
                    text = _text_from_content(p.get("content"))
                    if text.strip():
                        turns.append(Turn(idx, role, ts, text=text)); idx += 1
                # role == "developer" (system/dev instructions) -> skip
            elif ptype == "function_call":
                turns.append(Turn(idx, "tool", ts, tool_name=p.get("name"),
                                  tool_status="ok", text=str(p.get("arguments", ""))[:500]))
                idx += 1
            elif ptype == "patch_apply_end":
                changes = p.get("changes")
                if isinstance(changes, dict):
                    for fp in changes.keys():
                        file_counts[fp] += 1
                        n_edits += 1
                if not p.get("success", True):
                    n_tool_errors += 1
                    events.append(Event("tool_error", ts, str(p.get("call_id", "patch"))))
            # function_call_output (unstructured output) / reasoning / others -> skip

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

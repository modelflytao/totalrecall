from __future__ import annotations
import json
from pathlib import Path
from ..models import NormalizedSession, Turn, Stats
from .. import paths
from ..events import extract_events


def _text_from_content(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for item in content if isinstance(content, list) else []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
    return "\n".join(parts)


def _tool_uses(content):
    if not isinstance(content, list):
        return []
    return [i for i in content if isinstance(i, dict) and i.get("type") == "tool_use"]


def _tool_results(content):
    if not isinstance(content, list):
        return []
    return [i for i in content if isinstance(i, dict) and i.get("type") == "tool_result"]


class ClaudeCodeAdapter:
    tool = "claude-code"

    def parse(self, path: Path) -> NormalizedSession:
        session_id = cwd = git_branch = ""
        started_at = ended_at = None
        turns: list[Turn] = []
        is_analysis = False
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
            session_id = o.get("sessionId") or session_id
            if o.get("cwd"):
                cwd = o["cwd"]
                cwd_norm = cwd.replace("\\", "/").rstrip("/")
                analysis_root = str(paths.analysis_cwd()).replace("\\", "/").rstrip("/")
                if cwd_norm == analysis_root or "/.totalrecall/analysis" in cwd_norm:
                    is_analysis = True
            if "gitBranch" in o:
                git_branch = o.get("gitBranch")

            msg = o.get("message")
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            content = msg.get("content")
            is_meta = bool(o.get("isMeta"))
            is_side = bool(o.get("isSidechain"))

            if role == "assistant":
                txt = _text_from_content(content)
                if txt.strip():
                    turns.append(Turn(idx, "assistant", ts, text=txt,
                                      is_sidechain=is_side)); idx += 1
                for tu in _tool_uses(content):
                    turns.append(Turn(idx, "tool", ts, tool_name=tu.get("name"),
                                      tool_status="ok", is_sidechain=is_side,
                                      text=json.dumps(tu.get("input", {}))[:500]))
                    idx += 1
            elif role == "user":
                results = _tool_results(content)
                if results:
                    for tr in results:
                        status = "error" if tr.get("is_error") else "ok"
                        # attach error status to the most recent matching tool turn
                        for t in reversed(turns):
                            if t.role == "tool" and t.tool_status == "ok":
                                if status == "error":
                                    t.tool_status = "error"
                                break
                    continue  # tool_result user lines are not user-authored turns
                if is_meta:
                    continue
                txt = _text_from_content(content)
                if txt.strip():
                    turns.append(Turn(idx, "user", ts, text=txt, is_meta=False,
                                      is_sidechain=is_side)); idx += 1

        session = NormalizedSession(
            tool=self.tool, session_id=session_id, cwd=cwd, git_branch=git_branch or None,
            started_at=started_at, ended_at=ended_at, is_analysis_session=is_analysis,
            turns=turns, events=[], stats=Stats(n_turns=len(turns)),
        )
        extract_events(session)   # populate A-class events + stats (was done by the worker)
        return session

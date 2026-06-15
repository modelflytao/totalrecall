from __future__ import annotations
import hashlib
import json
import os
import subprocess
from dataclasses import asdict
from pathlib import Path
from . import paths, config
from .models import NormalizedSession, Finding, Evidence

SKILL_PATH = Path("skills/totalrecall-analyze/SKILL.md")


def _session_payload(s: NormalizedSession) -> dict:
    return {
        "session_id": s.session_id, "tool": s.tool,
        "turns": [{"idx": t.idx, "role": t.role, "text": t.text[:2000],
                   "tool_name": t.tool_name, "tool_status": t.tool_status}
                  for t in s.turns if not t.is_meta],
        "events": [asdict(e) for e in s.events],
        "stats": asdict(s.stats),
    }


def build_prompt(session: NormalizedSession, catalog: list[dict]) -> str:
    skill = SKILL_PATH.read_text(encoding="utf-8") if SKILL_PATH.exists() else ""
    payload = {"session": _session_payload(session), "catalog": catalog}
    return (skill + "\n\n# INPUT\n```json\n"
            + json.dumps(payload, ensure_ascii=False) + "\n```\n"
            + "\nReturn ONLY the JSON array of findings.")


def _extract_json_array(text: str):
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []


def _snippet_hash(session: NormalizedSession, turn_refs: list[int]) -> str:
    by_idx = {t.idx: t.text for t in session.turns}
    blob = "\n".join(by_idx.get(i, "") for i in turn_refs)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def default_runner(prompt: str, model: str, cwd: str, env: dict) -> str:
    # Prompt goes via stdin: it can exceed the Windows command-line length limit.
    # shell=True lets the npm shim (claude.cmd on Windows / claude on PATH) resolve
    # the same way the user's shell does (CreateProcess can't launch .cmd directly).
    cmd = f"claude -p --output-format json --model {model}"
    proc = subprocess.run(
        cmd, shell=True, input=prompt, cwd=cwd, env=env,
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        try:
            with paths.log_path().open("a", encoding="utf-8") as fh:
                fh.write(f"claude runner exit {proc.returncode}: {(proc.stderr or '')[:500]}\n")
        except Exception:
            pass
    return proc.stdout


def analyze(session: NormalizedSession, catalog: list[dict], model: str,
            runner=default_runner) -> list[Finding]:
    paths.ensure_dirs()
    prompt = build_prompt(session, catalog)
    env = dict(os.environ)
    env[config.load().analysis_marker_env] = "1"
    raw_stdout = runner(prompt, model, str(paths.analysis_cwd()), env)
    try:
        result_text = json.loads(raw_stdout).get("result", "")
    except json.JSONDecodeError:
        result_text = raw_stdout
    items = _extract_json_array(result_text)

    findings: list[Finding] = []
    for it in items:
        refs = [int(x) for x in it.get("turn_refs", [])]
        ev = Evidence(session_id=session.session_id, tool=session.tool, turn_refs=refs,
                      ts=session.ended_at, snippet_hash=_snippet_hash(session, refs))
        findings.append(Finding(
            category=it.get("category", "unknown"),
            description=it.get("description", ""),
            severity=int(it.get("severity", 1)),
            evidence=ev,
            pattern_id=it.get("pattern_id"),
            slug=it.get("slug"),
            phase2_hint=it.get("phase2_hint"),
        ))
    return findings

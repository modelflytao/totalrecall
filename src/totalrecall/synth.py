from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from . import patterns_store, paths, config, render, orchestrator, ledger


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ask_merges(patterns: list, model: str) -> list[list[str]]:
    """Ask the model which pattern ids are duplicates. Returns groups [keep, dup, dup...]."""
    catalog = [{"id": p.id, "title": p.title, "description": p.description} for p in patterns]
    prompt = (
        "You are consolidating a friction pattern library. Given these patterns, "
        "group ones that describe the SAME underlying friction. Output ONLY a JSON array "
        "of groups; each group is an array of ids where the FIRST id is the canonical "
        "survivor, e.g. [[\"keep-id\",\"dup-id\"]]. Only include groups with >1 id.\n\n"
        + json.dumps(catalog, ensure_ascii=False)
    )
    env = {}
    import os
    env.update(os.environ)
    env[config.load().analysis_marker_env] = "1"
    raw = orchestrator.default_runner(prompt, model, str(paths.analysis_cwd()), env)
    try:
        text = json.loads(raw).get("result", "")
    except json.JSONDecodeError:
        text = raw
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []


def _merge_into(keep_id: str, dup_id: str) -> None:
    keep = patterns_store.get(keep_id)
    dup = patterns_store.get(dup_id)
    if not keep or not dup:
        return
    seen = {e.snippet_hash for e in keep.evidence}
    for e in dup.evidence:
        if e.snippet_hash not in seen:
            keep.evidence.append(e)
            seen.add(e.snippet_hash)
    keep.occurrences = len(keep.evidence)   # occurrences stays == distinct evidence
    keep.last_seen = max(keep.last_seen, dup.last_seen)
    keep.severity = max(keep.severity, dup.severity)
    keep.phase2_hint = keep.phase2_hint or dup.phase2_hint
    patterns_store.save(keep)
    (paths.patterns_dir() / f"{dup_id}.json").unlink(missing_ok=True)
    patterns_store.save(keep)   # rebuild index after deletion


def run(cfg: config.Config) -> None:
    patterns = patterns_store.all()
    if not patterns:
        return
    for group in _ask_merges(patterns, cfg.synth_model):
        if len(group) < 2:
            continue
        keep = group[0]
        for dup in group[1:]:
            _merge_into(keep, dup)
    lg = ledger.Ledger.load()
    n_projects = len({str(Path(p).parent) for p in lg.done_paths()})
    render.write(_now(), n_sessions=len(lg.done_paths()), n_projects=n_projects)

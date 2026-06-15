from __future__ import annotations
import json
from . import paths
from .models import Pattern, pattern_to_dict, pattern_from_dict


def _path_for(pid: str):
    return paths.patterns_dir() / f"{pid}.json"


def save(p: Pattern) -> None:
    paths.ensure_dirs()
    _path_for(p.id).write_text(json.dumps(pattern_to_dict(p), indent=2,
                                          ensure_ascii=False), encoding="utf-8")
    _rebuild_index()


def get(pid: str) -> Pattern | None:
    fp = _path_for(pid)
    if not fp.exists():
        return None
    return pattern_from_dict(json.loads(fp.read_text(encoding="utf-8")))


def all() -> list[Pattern]:
    if not paths.patterns_dir().exists():
        return []
    out = []
    for fp in paths.patterns_dir().glob("*.json"):
        if fp.name == "index.json":
            continue
        out.append(pattern_from_dict(json.loads(fp.read_text(encoding="utf-8"))))
    return out


def index_ids() -> list[str]:
    fp = paths.patterns_index_path()
    if not fp.exists():
        return []
    return json.loads(fp.read_text(encoding="utf-8")).get("ids", [])


def _rebuild_index() -> None:
    ids = sorted(p.id for p in all())
    paths.patterns_index_path().write_text(
        json.dumps({"ids": ids}, indent=2), encoding="utf-8")

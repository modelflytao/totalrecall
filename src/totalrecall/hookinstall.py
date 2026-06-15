from __future__ import annotations
import json
from pathlib import Path
from . import paths, config

HOOK_COMMAND = "totalrecall hook"


def claude_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _load_settings(p: Path) -> dict:
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _already_installed(session_end: list) -> bool:
    for entry in session_end:
        for h in entry.get("hooks", []):
            if HOOK_COMMAND in h.get("command", ""):
                return True
    return False


def install_hook() -> None:
    p = claude_settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = _load_settings(p)
    hooks = data.setdefault("hooks", {})
    session_end = hooks.setdefault("SessionEnd", [])
    if not _already_installed(session_end):
        session_end.append({"hooks": [{"type": "command", "command": HOOK_COMMAND}]})
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def scaffold_state() -> None:
    paths.ensure_dirs()
    if not paths.config_path().exists():
        paths.config_path().write_text(config.default_toml(), encoding="utf-8")


def init() -> None:
    scaffold_state()
    install_hook()

from __future__ import annotations
import os
from pathlib import Path


def state_dir() -> Path:
    override = os.environ.get("TOTALRECALL_HOME")
    return Path(override) if override else Path.home() / ".totalrecall"


def queue_dir() -> Path:
    return state_dir() / "queue"


def ledger_path() -> Path:
    return state_dir() / "ledger.json"


def patterns_dir() -> Path:
    return state_dir() / "patterns"


def patterns_index_path() -> Path:
    return patterns_dir() / "index.json"


def insights_path() -> Path:
    return state_dir() / "insights.md"


def proposals_path() -> Path:
    return state_dir() / "proposals.json"


def proposals_md_path() -> Path:
    return state_dir() / "proposals.md"


def config_path() -> Path:
    return state_dir() / "config.toml"


def log_path() -> Path:
    return state_dir() / "log"


def analysis_cwd() -> Path:
    """Dedicated cwd for headless analysis sessions (used for self-exclusion)."""
    return state_dir() / "analysis"


def opencode_cache_dir() -> Path:
    return state_dir() / "opencode-cache"


def opencode_sync_path() -> Path:
    return state_dir() / "opencode-sync.json"


def ensure_dirs() -> None:
    for d in (state_dir(), queue_dir(), patterns_dir(), analysis_cwd()):
        d.mkdir(parents=True, exist_ok=True)

from __future__ import annotations
import tomllib
from dataclasses import dataclass, field
from . import paths


@dataclass
class Config:
    extract_model: str = "claude-sonnet-4-6"
    synth_model: str = "claude-sonnet-4-6"
    max_input_tokens: int = 20000
    synth_every_n_sessions: int = 20
    catalog_topk: int = 40
    sources: dict = field(default_factory=lambda: {
        "claude_code": True, "codex": False, "opencode": False})
    store_snippets: bool = False
    analysis_marker_env: str = "TOTALRECALL_ANALYSIS"


def load() -> Config:
    cfg = Config()
    p = paths.config_path()
    if not p.exists():
        return cfg
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    models = data.get("models", {})
    cfg.extract_model = models.get("extract", cfg.extract_model)
    cfg.synth_model = models.get("synth", cfg.synth_model)
    limits = data.get("limits", {})
    cfg.max_input_tokens = limits.get("max_input_tokens", cfg.max_input_tokens)
    cfg.synth_every_n_sessions = limits.get("synth_every_n_sessions", cfg.synth_every_n_sessions)
    cfg.catalog_topk = limits.get("catalog_topk", cfg.catalog_topk)
    cfg.sources = {**cfg.sources, **data.get("sources", {})}
    cfg.store_snippets = data.get("privacy", {}).get("store_snippets", cfg.store_snippets)
    cfg.analysis_marker_env = data.get("internal", {}).get(
        "analysis_marker_env", cfg.analysis_marker_env)
    return cfg


def default_toml() -> str:
    return (
        "[models]\n"
        'extract = "claude-sonnet-4-6"   # per-session semantic extraction; Haiku is a cost lever, evaluate first\n'
        'synth   = "claude-sonnet-4-6"   # periodic synthesis (can raise to claude-opus-4-8)\n\n'
        "[limits]\n"
        "max_input_tokens = 20000\n"
        "synth_every_n_sessions = 20\n"
        "catalog_topk = 40\n\n"
        "[sources]\n"
        "claude_code = true\n"
        "codex = false\n"
        "opencode = false\n\n"
        "[privacy]\n"
        "store_snippets = false\n\n"
        "[internal]\n"
        'analysis_marker_env = "TOTALRECALL_ANALYSIS"\n'
    )

from __future__ import annotations
from .claude_code import ClaudeCodeAdapter
from .codex import CodexAdapter


def for_path(path):
    """Return the adapter for a transcript path, by which source dir it lives under."""
    s = str(path).replace("\\", "/")
    if "/.codex/sessions/" in s:
        return CodexAdapter()
    return ClaudeCodeAdapter()

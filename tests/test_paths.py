from pathlib import Path
from totalrecall import paths

def test_home_uses_env_override(home):
    assert paths.state_dir() == home
    assert paths.queue_dir() == home / "queue"
    assert paths.ledger_path() == home / "ledger.json"
    assert paths.patterns_dir() == home / "patterns"
    assert paths.insights_path() == home / "insights.md"
    assert paths.config_path() == home / "config.toml"

def test_ensure_dirs_creates_layout(home):
    paths.ensure_dirs()
    assert paths.queue_dir().is_dir()
    assert paths.patterns_dir().is_dir()

def test_default_home_without_env(monkeypatch):
    monkeypatch.delenv("TOTALRECALL_HOME", raising=False)
    assert paths.state_dir() == Path.home() / ".totalrecall"

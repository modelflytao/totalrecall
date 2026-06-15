import json
from totalrecall import hookinstall, paths

def test_init_scaffolds_state_and_config(home, tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(hookinstall, "claude_settings_path", lambda: settings)
    hookinstall.init()
    assert paths.config_path().exists()
    assert paths.queue_dir().is_dir()
    data = json.loads(settings.read_text(encoding="utf-8"))
    cmds = [h["command"] for entry in data["hooks"]["SessionEnd"] for h in entry["hooks"]]
    assert any("totalrecall" in c and "hook" in c for c in cmds)

def test_init_is_idempotent_and_preserves_existing_hooks(home, tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {"SessionEnd": [
        {"hooks": [{"type": "command", "command": "echo other"}]}]}}), encoding="utf-8")
    monkeypatch.setattr(hookinstall, "claude_settings_path", lambda: settings)
    hookinstall.init()
    hookinstall.init()   # twice -> still single totalrecall hook, other preserved
    data = json.loads(settings.read_text(encoding="utf-8"))
    cmds = [h["command"] for entry in data["hooks"]["SessionEnd"] for h in entry["hooks"]]
    assert "echo other" in cmds
    assert sum("totalrecall" in c for c in cmds) == 1

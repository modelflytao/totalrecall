from totalrecall import orchestrator


def test_default_runner_sends_prompt_via_stdin(monkeypatch, home):
    captured = {}

    class FakeProc:
        returncode = 0
        stdout = '{"type":"result","result":"[]"}'
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setattr(orchestrator.subprocess, "run", fake_run)
    out = orchestrator.default_runner("HUGE PROMPT TEXT", "claude-sonnet-4-6", ".", {})
    assert captured["kwargs"]["input"] == "HUGE PROMPT TEXT"
    assert "HUGE PROMPT TEXT" not in str(captured["cmd"])
    assert captured["kwargs"].get("shell") is True
    assert out == '{"type":"result","result":"[]"}'

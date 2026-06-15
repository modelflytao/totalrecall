import json
from totalrecall import orchestrator
from totalrecall.models import NormalizedSession, Turn, Stats

def _sess():
    return NormalizedSession("claude-code", "s1", "/p", "main",
                             "2026-06-10T10:00:00Z", "2026-06-10T10:05:00Z", False,
                             turns=[Turn(0, "user", "2026-06-10T10:00:00Z",
                                         text="use PowerShell not bash")],
                             events=[], stats=Stats(n_turns=1))

def _fake_runner_returns(findings):
    # mimic `claude -p --output-format json` envelope
    envelope = {"type": "result", "result": json.dumps(findings)}
    return lambda prompt, model, cwd, env: json.dumps(envelope)

def test_returns_findings_with_computed_snippet_hash(home):
    raw = [{"category": "repeated-correction", "description": "use pwsh not bash",
            "severity": 3, "turn_refs": [0], "pattern_id": None,
            "slug": "pwsh-vs-bash", "phase2_hint": None}]
    findings = orchestrator.analyze(_sess(), catalog=[], model="m",
                                    runner=_fake_runner_returns(raw))
    assert len(findings) == 1
    f = findings[0]
    assert f.slug == "pwsh-vs-bash"
    assert f.evidence.session_id == "s1"
    assert f.evidence.turn_refs == [0]
    assert f.evidence.snippet_hash  # deterministically computed by orchestrator, not the model

def test_handles_fenced_and_noisy_result(home):
    noisy = "Here you go:\n```json\n[]\n```"
    runner = lambda p, m, c, e: json.dumps({"type": "result", "result": noisy})
    assert orchestrator.analyze(_sess(), [], "m", runner=runner) == []

def test_sets_analysis_marker_env_and_cwd(home, monkeypatch):
    captured = {}
    def runner(prompt, model, cwd, env):
        captured["cwd"] = cwd
        captured["marker"] = env.get("TOTALRECALL_ANALYSIS")
        return json.dumps({"type": "result", "result": "[]"})
    orchestrator.analyze(_sess(), [], "m", runner=runner)
    assert captured["marker"] == "1"
    assert "analysis" in captured["cwd"].replace("\\", "/")

def test_skill_path_is_absolute_and_exists():
    # Must resolve regardless of cwd (the hook-spawned worker has an arbitrary cwd).
    assert orchestrator.SKILL_PATH.is_absolute()
    assert orchestrator.SKILL_PATH.exists()

def test_session_payload_truncates_large_session(home):
    from totalrecall.models import NormalizedSession, Turn, Stats
    turns = [Turn(i, "user", None, text="x" * 2000) for i in range(50)]
    s = NormalizedSession("claude-code", "s", "/p", "main", "t", "t", False,
                          turns=turns, events=[], stats=Stats())
    payload = orchestrator._session_payload(s, max_input_tokens=1000)  # ~4000 char budget
    assert payload["turns_truncated"] is True
    assert len(payload["turns"]) < 50
    assert payload["turns"][-1]["idx"] == 49   # keeps the most recent turns

def test_session_payload_keeps_small_session(home):
    from totalrecall.models import NormalizedSession, Turn, Stats
    turns = [Turn(i, "user", None, text="short") for i in range(3)]
    s = NormalizedSession("claude-code", "s", "/p", "main", "t", "t", False,
                          turns=turns, events=[], stats=Stats())
    payload = orchestrator._session_payload(s, max_input_tokens=20000)
    assert payload["turns_truncated"] is False
    assert len(payload["turns"]) == 3

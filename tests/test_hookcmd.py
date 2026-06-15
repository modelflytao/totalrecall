import io, json
from totalrecall import hookcmd, queue, paths

def test_hook_enqueues_transcript_path(home, monkeypatch):
    paths.ensure_dirs()
    monkeypatch.setattr(hookcmd, "_spawn_worker", lambda: None)
    payload = json.dumps({"transcript_path": "/x/s1.jsonl", "session_id": "s1"})
    rc = hookcmd.handle(stdin=io.StringIO(payload), env={})
    assert rc == 0
    assert "/x/s1.jsonl" in queue.drain()

def test_hook_skips_when_analysis_marker_set(home, monkeypatch):
    paths.ensure_dirs()
    monkeypatch.setattr(hookcmd, "_spawn_worker", lambda: None)
    payload = json.dumps({"transcript_path": "/x/a1.jsonl"})
    rc = hookcmd.handle(stdin=io.StringIO(payload), env={"TOTALRECALL_ANALYSIS": "1"})
    assert rc == 0
    assert queue.size() == 0          # self-produced analysis session not enqueued

def test_hook_never_raises_on_bad_input(home, monkeypatch):
    monkeypatch.setattr(hookcmd, "_spawn_worker", lambda: None)
    rc = hookcmd.handle(stdin=io.StringIO("not json"), env={})
    assert rc == 0                    # must not break the user's session

import json
import sqlite3
from pathlib import Path
from totalrecall import opencode_export, paths


def _build_db(db_path: Path):
    """Minimal OpenCode schema with one session, two messages, mixed parts."""
    con = sqlite3.connect(str(db_path))
    con.execute("create table session (id text, directory text, title text, "
                "time_created int, time_updated int, parent_id text)")
    con.execute("create table message (id text, session_id text, time_created int, data text)")
    con.execute("create table part (id text, message_id text, session_id text, "
                "time_created int, data text)")
    con.execute("insert into session values ('ses_x','D:/work/demo','t',1000,5000,null)")
    con.execute("insert into message values ('m1','ses_x',1000,?)",
                (json.dumps({"role": "user", "time": {"created": 1000}}),))
    con.execute("insert into message values ('m2','ses_x',2000,?)",
                (json.dumps({"role": "assistant", "time": {"created": 2000}}),))
    parts = [
        ("p1", "m1", 1000, {"type": "text", "text": "use PowerShell"}),
        ("p2", "m2", 2000, {"type": "text", "text": "ok"}),
        ("p3", "m2", 2100, {"type": "tool", "tool": "bash", "callID": "c1",
                            "state": {"status": "error"}}),
        ("p4", "m2", 2200, {"type": "patch", "files": ["D:/work/demo/a.py"], "hash": "h"}),
        ("p5", "m2", 2300, {"type": "reasoning", "text": "..."}),  # skipped
    ]
    for pid, mid, tc, data in parts:
        con.execute("insert into part values (?,?,?,?,?)", (pid, mid, "ses_x", tc, json.dumps(data)))
    con.commit(); con.close()


def test_export_writes_cache_file(home, tmp_path, monkeypatch):
    paths.ensure_dirs()
    db = tmp_path / "opencode.db"; _build_db(db)
    monkeypatch.setattr(opencode_export, "opencode_db_path", lambda: db)
    n = opencode_export.sync()
    assert n >= 1
    cache = paths.opencode_cache_dir() / "ses_x.jsonl"
    assert cache.exists()
    lines = [json.loads(l) for l in cache.read_text(encoding="utf-8").splitlines()]
    meta = lines[0]
    assert meta["type"] == "meta" and meta["session_id"] == "ses_x"
    assert meta["cwd"] == "D:/work/demo"
    assert meta["started_at"].endswith("+00:00")          # tz-aware ISO
    kinds = [l["type"] for l in lines[1:]]
    assert kinds == ["text", "text", "tool", "patch"]      # reasoning skipped, ordered
    tool = [l for l in lines if l["type"] == "tool"][0]
    assert tool["name"] == "bash" and tool["status"] == "error"
    patch = [l for l in lines if l["type"] == "patch"][0]
    assert patch["files"] == ["D:/work/demo/a.py"]


def test_export_skips_when_watermark_unchanged(home, tmp_path, monkeypatch):
    paths.ensure_dirs()
    db = tmp_path / "opencode.db"; _build_db(db)
    monkeypatch.setattr(opencode_export, "opencode_db_path", lambda: db)
    opencode_export.sync()
    # second sync with unchanged db -> watermark short-circuit, returns 0
    # AND must NOT take the expensive snapshot (spec I2: no heavy I/O when unchanged)
    snapshots = {"n": 0}
    real_snap = opencode_export._snapshot
    monkeypatch.setattr(opencode_export, "_snapshot",
                        lambda db: (snapshots.__setitem__("n", snapshots["n"] + 1), real_snap(db))[1])
    assert opencode_export.sync() == 0
    assert snapshots["n"] == 0           # snapshot never created on the unchanged path


def test_export_gcs_orphan_cache(home, tmp_path, monkeypatch):
    paths.ensure_dirs()
    db = tmp_path / "opencode.db"; _build_db(db)
    monkeypatch.setattr(opencode_export, "opencode_db_path", lambda: db)
    orphan = paths.opencode_cache_dir() / "ses_gone.jsonl"
    paths.opencode_cache_dir().mkdir(parents=True, exist_ok=True)
    orphan.write_text("stale", encoding="utf-8")
    opencode_export.sync()
    assert not orphan.exists()        # sid not in db -> GC'd


def test_first_run_deferred_on_worker_path(home, tmp_path, monkeypatch):
    # HOLE B: worker-side sync (first_run_ok=False) must NOT snapshot/export when no
    # watermark exists yet — the cold full backfill is deferred to manual `sync-opencode`.
    paths.ensure_dirs()
    db = tmp_path / "opencode.db"; _build_db(db)
    monkeypatch.setattr(opencode_export, "opencode_db_path", lambda: db)
    snaps = {"n": 0}
    real = opencode_export._snapshot
    monkeypatch.setattr(opencode_export, "_snapshot",
                        lambda d: (snaps.__setitem__("n", snaps["n"] + 1), real(d))[1])
    assert opencode_export.sync(first_run_ok=False) == 0   # deferred
    assert snaps["n"] == 0                                 # no snapshot taken
    assert not (paths.opencode_cache_dir() / "ses_x.jsonl").exists()
    # the manual path still does the full export
    assert opencode_export.sync(first_run_ok=True) >= 1
    assert (paths.opencode_cache_dir() / "ses_x.jsonl").exists()


def test_text_parts_split_per_message(home, tmp_path, monkeypatch):
    # Two same-role (assistant) messages, each a text part -> TWO turns, not merged (spec §5).
    paths.ensure_dirs()
    db = tmp_path / "opencode.db"
    con = sqlite3.connect(str(db))
    con.execute("create table session (id text, directory text, title text, "
                "time_created int, time_updated int, parent_id text)")
    con.execute("create table message (id text, session_id text, time_created int, data text)")
    con.execute("create table part (id text, message_id text, session_id text, "
                "time_created int, data text)")
    con.execute("insert into session values ('ses_z','D:/w','t',1000,9000,null)")
    con.execute("insert into message values ('ma','ses_z',1000,?)",
                (json.dumps({"role": "assistant"}),))
    con.execute("insert into message values ('mb','ses_z',2000,?)",
                (json.dumps({"role": "assistant"}),))
    con.execute("insert into part values ('pa','ma','ses_z',1000,?)",
                (json.dumps({"type": "text", "text": "first message"}),))
    con.execute("insert into part values ('pb','mb','ses_z',2000,?)",
                (json.dumps({"type": "text", "text": "second message"}),))
    con.commit(); con.close()
    monkeypatch.setattr(opencode_export, "opencode_db_path", lambda: db)
    opencode_export.sync()
    lines = [json.loads(l) for l in
             (paths.opencode_cache_dir() / "ses_z.jsonl").read_text(encoding="utf-8").splitlines()]
    texts = [l for l in lines if l["type"] == "text"]
    assert [t["text"] for t in texts] == ["first message", "second message"]  # two turns, not joined


def test_gc_skipped_when_no_live_sessions(home, tmp_path, monkeypatch):
    # An empty (but openable) session table must NOT wipe existing cache files.
    paths.ensure_dirs()
    db = tmp_path / "opencode.db"
    con = sqlite3.connect(str(db))
    con.execute("create table session (id text, directory text, title text, "
                "time_created int, time_updated int, parent_id text)")
    con.execute("create table message (id text, session_id text, time_created int, data text)")
    con.execute("create table part (id text, message_id text, session_id text, "
                "time_created int, data text)")
    con.commit(); con.close()
    monkeypatch.setattr(opencode_export, "opencode_db_path", lambda: db)
    keep = paths.opencode_cache_dir(); keep.mkdir(parents=True, exist_ok=True)
    (keep / "ses_keep.jsonl").write_text("x", encoding="utf-8")
    opencode_export.sync()
    assert (keep / "ses_keep.jsonl").exists()   # not wiped by empty session set

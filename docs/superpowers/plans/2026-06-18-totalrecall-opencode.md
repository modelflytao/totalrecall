# TotalRecall OpenCode Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Analyze OpenCode sessions (stored in a single SQLite db) through TotalRecall's existing file pipeline, by exporting each db session to a per-session JSONL cache file.

**Architecture:** A `opencode_export` module reads `~/.local/share/opencode/opencode.db` via a consistent SQLite snapshot (`Connection.backup()`, never writing the user's db), rebuilds each `session`→`message`→`part` into a stable line format at `~/.totalrecall/opencode-cache/<sid>.jsonl`, GCs orphans, and short-circuits via a persisted global watermark. A new `OpenCodeAdapter` parses those cache files; `for_path` routes `/opencode-cache/` to it; `reconcile` scans the cache dir when `sources.opencode` is on; `worker.run` does a cheap-probe-gated sync first. A cross-source fix dedups merger evidence by `session_id`.

**Tech Stack:** Python 3.11+ (stdlib `sqlite3`, `json`, `datetime`, `collections.Counter`), `pytest`. Builds on Phase 1+2+Codex (112 tests green on `main`).

**Spec:** `docs/superpowers/specs/2026-06-18-totalrecall-opencode-design.md`.

---

## File Structure

```
src/totalrecall/
  paths.py             # MODIFY: opencode_cache_dir(), opencode_sync_path()
  merger.py            # MODIFY: _apply dedups evidence by session_id too (I1, cross-source)
  opencode_export.py   # NEW: db snapshot -> opencode-cache/<sid>.jsonl (+ watermark, GC)
  adapters/
    __init__.py        # MODIFY: for_path routes /opencode-cache/ -> OpenCodeAdapter
    opencode.py        # NEW: OpenCodeAdapter (export-format jsonl -> NormalizedSession)
  reconcile.py         # MODIFY: scan opencode_cache_dir() when sources.opencode
  worker.py            # MODIFY: run() does cheap-probe-gated opencode sync before reconcile
  cli.py               # MODIFY: add `sync-opencode` subcommand
tests/
  fixtures/opencode_cache_basic.jsonl   # NEW (export format)
  test_merger_session_dedup.py          # NEW
  test_opencode_export.py               # NEW (builds a tiny real sqlite db)
  test_opencode_adapter.py              # NEW
  test_adapters_dispatch_opencode.py    # NEW
  test_reconcile_opencode.py            # NEW
  test_worker_opencode_sync.py          # NEW
```

Convention reminders: tests use the `home` fixture (isolated `TOTALRECALL_HOME`); commit per task with two `-m` flags (no temp files → no BOM): `git commit -m "<subject>" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`; run tests with `python -m pytest`.

---

## Task 1: merger dedups evidence by session_id (I1, cross-source)

**Files:**
- Modify: `src/totalrecall/merger.py`
- Test: `tests/test_merger_session_dedup.py`

**Why:** Re-analyzing a grown session (the common case once OpenCode re-exports on growth) produces findings with a different `snippet_hash`, so the current hash-only dedup double-counts `occurrences` for the same session. Dedup by `session_id` so occurrences = distinct sessions.

- [ ] **Step 1: Write the failing test**

`tests/test_merger_session_dedup.py`:
```python
from totalrecall import merger, patterns_store, paths
from totalrecall.models import Finding, Evidence

def _f(sid, h, slug="pwsh"):
    return Finding("repeated-correction", "use pwsh", 3,
                   Evidence(sid, "opencode", [1], "2026-06-10T00:00:00Z", h), slug=slug)

def test_same_session_not_double_counted(home):
    paths.ensure_dirs()
    merger.merge([_f("ses_a", "h1")], now="2026-06-10T00:00:00Z")
    merger.merge([_f("ses_a", "h2")], now="2026-06-11T00:00:00Z")  # same session, new hash
    p = patterns_store.get("pwsh")
    assert p.occurrences == 1 and len(p.evidence) == 1   # deduped by session_id

def test_different_sessions_counted(home):
    paths.ensure_dirs()
    merger.merge([_f("ses_a", "h1")], now="2026-06-10T00:00:00Z")
    merger.merge([_f("ses_b", "h2")], now="2026-06-11T00:00:00Z")
    p = patterns_store.get("pwsh")
    assert p.occurrences == 2 and len(p.evidence) == 2

def test_same_session_recurrence_after_apply_still_marks_ineffective(home):
    # HOLE A regression: dedup must NOT skip the post-apply recurrence check.
    # A grown session re-analyzed after a rule was applied must flip ineffective.
    from totalrecall.models import Pattern
    paths.ensure_dirs()
    patterns_store.save(Pattern(
        "pwsh", "T", "repeated-correction", "llm", "use pwsh",
        "2026-06-01T00:00:00Z", "2026-06-05T00:00:00Z", 1, 3,
        evidence=[Evidence("ses_a", "opencode", [1], "2026-06-05T00:00:00Z", "h1")],
        applied_at="2026-06-10T00:00:00Z"))
    recur = Finding("repeated-correction", "use pwsh", 3,
                    Evidence("ses_a", "opencode", [2], "2026-06-15T00:00:00Z", "h2"), slug="pwsh")
    merger.merge([recur], now="2026-06-15T00:00:00Z")    # same session, ts > applied_at
    p = patterns_store.get("pwsh")
    assert p.status == "ineffective"   # rule didn't work — must be detected even for same session
    assert p.occurrences == 1          # but not double-counted (I1 preserved)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_merger_session_dedup.py -v`
Expected: FAIL — `test_same_session_not_double_counted` gets occurrences == 2; `test_same_session_recurrence_after_apply_still_marks_ineffective` stays `active` (early-return skips the check)

- [ ] **Step 3: Implement**

In `src/totalrecall/merger.py`, replace the WHOLE `_apply` function body. Replace:
```python
def _apply(p: Pattern, f: Finding, now: str) -> None:
    if any(e.snippet_hash == f.evidence.snippet_hash for e in p.evidence):
        return  # duplicate evidence -> do not double-count
    p.occurrences += 1
    p.last_seen = now
    p.severity = max(p.severity, f.severity)
    p.evidence.append(f.evidence)
    if f.phase2_hint and not p.phase2_hint:
        p.phase2_hint = f.phase2_hint
    if p.source != f_source(f):
        p.source = "both"
    at, et = _ts(p.applied_at), (_ts(f.evidence.ts) or _ts(now))
    if at and et and et > at:
        p.status = "ineffective"   # recurred after the fix was applied (overrides resolved)
```
with:
```python
def _apply(p: Pattern, f: Finding, now: str) -> None:
    # Dedup occurrences by snippet OR session (occurrences = distinct sessions, I1).
    # But do NOT early-return: recency and the post-apply recurrence check must still
    # run even when the same session is re-analyzed (HOLE A — keeps the Phase-2 loop honest).
    dup = any(e.snippet_hash == f.evidence.snippet_hash
              or e.session_id == f.evidence.session_id for e in p.evidence)
    if not dup:
        p.occurrences += 1
        p.evidence.append(f.evidence)
    p.last_seen = now
    p.severity = max(p.severity, f.severity)
    if f.phase2_hint and not p.phase2_hint:
        p.phase2_hint = f.phase2_hint
    if p.source != f_source(f):
        p.source = "both"
    at, et = _ts(p.applied_at), (_ts(f.evidence.ts) or _ts(now))
    if at and et and et > at:
        p.status = "ineffective"   # post-apply recurrence (even same session) overrides resolved
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_merger_session_dedup.py tests/test_merger.py tests/test_merger_phase2.py -v`
Expected: PASS (new dedup + ineffective-on-same-session; existing merger tests still green — they use distinct session_ids so the not-dup path is unchanged for them)

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/merger.py tests/test_merger_session_dedup.py
git commit -m "fix: merger dedups evidence by session_id (occurrences = distinct sessions)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: paths for the OpenCode cache

**Files:**
- Modify: `src/totalrecall/paths.py`
- Test: `tests/test_paths_opencode.py`

- [ ] **Step 1: Write the failing test**

`tests/test_paths_opencode.py`:
```python
from totalrecall import paths

def test_opencode_paths(home):
    assert paths.opencode_cache_dir() == home / "opencode-cache"
    assert paths.opencode_sync_path() == home / "opencode-sync.json"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_paths_opencode.py -v`
Expected: FAIL — `AttributeError: module 'totalrecall.paths' has no attribute 'opencode_cache_dir'`

- [ ] **Step 3: Implement**

In `src/totalrecall/paths.py`, add after `analysis_cwd`:
```python
def opencode_cache_dir() -> Path:
    return state_dir() / "opencode-cache"


def opencode_sync_path() -> Path:
    return state_dir() / "opencode-sync.json"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_paths_opencode.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/paths.py tests/test_paths_opencode.py
git commit -m "feat: paths for opencode cache + sync watermark" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: opencode_export — rebuild + write cache files

**Files:**
- Create: `src/totalrecall/opencode_export.py`
- Test: `tests/test_opencode_export.py`

- [ ] **Step 1: Write the failing test**

`tests/test_opencode_export.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_opencode_export.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'totalrecall.opencode_export'`

- [ ] **Step 3: Implement**

`src/totalrecall/opencode_export.py`:
```python
from __future__ import annotations
import json
import sqlite3
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from . import paths


def opencode_db_path() -> Path:
    return Path.home() / ".local" / "share" / "opencode" / "opencode.db"


def _iso(ms) -> str | None:
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def _snapshot(db: Path) -> Path:
    """Consistent read-only snapshot via the SQLite backup API (never writes the user db)."""
    tmp = Path(tempfile.mkdtemp(prefix="tr_oc_")) / "snap.db"
    src = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(tmp))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return tmp


def _load_watermark() -> int:
    p = paths.opencode_sync_path()
    if not p.exists():
        return -1
    try:
        return int(json.loads(p.read_text(encoding="utf-8")).get("max_time_updated", -1))
    except (ValueError, json.JSONDecodeError):
        return -1


def _save_watermark(value: int) -> None:
    paths.opencode_sync_path().write_text(
        json.dumps({"max_time_updated": value}), encoding="utf-8")


def _part_line(data: dict, ts: str | None):
    t = data.get("type")
    if t == "text":
        txt = data.get("text", "")
        return ("text", {"type": "text", "ts": ts, "text": txt}) if txt.strip() else None
    if t == "tool":
        return ("tool", {"type": "tool", "ts": ts, "name": data.get("tool"),
                         "status": (data.get("state") or {}).get("status", "")})
    if t == "patch":
        files = data.get("files") or []
        return ("patch", {"type": "patch", "ts": ts, "files": list(files)})
    return None   # reasoning / step-* / compaction / file / subtask -> skip


def sync(first_run_ok: bool = True) -> int:
    """Export changed OpenCode sessions to opencode-cache/<sid>.jsonl. Returns #written.

    first_run_ok=False (worker hot path): when no watermark exists yet, DEFER the cold full
    export to the manual `sync-opencode` instead of doing it under the worker lock (HOLE B).
    """
    db = opencode_db_path()
    if not db.exists():
        return 0

    # CHEAP read-only probe FIRST — global watermark + live session ids. No snapshot.
    # (Spec I2: never copy the multi-hundred-MB db on the unchanged hot path; verified
    #  ~0.0017s probe vs ~0.82s backup on the real 207MB db.)
    ro = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        row = ro.execute("select max(time_updated) from session").fetchone()
        global_max = int(row[0]) if row and row[0] is not None else 0
        live_sids = {r[0] for r in ro.execute("select id from session").fetchall()}
    finally:
        ro.close()

    # GC orphan cache files on the CHEAP path — decoupled from the watermark gate, so a
    # deleted/archived session's cache file is removed even when global_max didn't advance (HOLE C).
    cache = paths.opencode_cache_dir()
    if cache.exists():
        for fp in cache.glob("*.jsonl"):
            if fp.stem not in live_sids:
                fp.unlink()

    saved = _load_watermark()
    if global_max <= saved:
        return 0                                      # nothing changed globally -> done, no snapshot
    if saved < 0 and not first_run_ok:
        return 0                                      # first run on the worker hot path -> defer to manual sync (HOLE B)

    snap = _snapshot(db)
    con = None
    try:
        con = sqlite3.connect(str(snap))
        cur = con.cursor()
        cache.mkdir(parents=True, exist_ok=True)

        # rebuild messages + parts grouped by session
        msg_role = {}
        for mid, sid, data in cur.execute(
                "select id, session_id, data from message").fetchall():
            try:
                msg_role[mid] = json.loads(data).get("role", "")
            except json.JSONDecodeError:
                msg_role[mid] = ""
        parts_by_session = defaultdict(list)
        for mid, sid, tc, data in cur.execute(
                "select message_id, session_id, time_created, data from part "
                "order by time_created").fetchall():
            try:
                pdata = json.loads(data)
            except json.JSONDecodeError:
                continue
            parts_by_session[sid].append((mid, tc, pdata))

        written = 0
        for sid, directory, title, tcreated, tupdated in cur.execute(
                "select id, directory, title, time_created, time_updated from session").fetchall():
            lines = [{"type": "meta", "session_id": sid, "cwd": directory or "",
                      "title": title or "", "started_at": _iso(tcreated),
                      "ended_at": _iso(tupdated)}]
            # buffer consecutive text parts of the SAME message into one turn (spec §5)
            text_buf = []      # (role, ts, [texts])
            def _flush():
                if text_buf:
                    role, ts0, chunks = text_buf[0]
                    joined = "\n".join(chunks)
                    if joined.strip():
                        lines.append({"type": "text", "ts": ts0, "role": role, "text": joined})
                    text_buf.clear()
            for mid, tc, pdata in parts_by_session.get(sid, []):
                if pdata.get("type") == "text":
                    role = "user" if msg_role.get(mid) == "user" else "assistant"
                    if text_buf and text_buf[0][0] == role:
                        text_buf[0][2].append(pdata.get("text", ""))
                    else:
                        _flush()
                        text_buf.append((role, _iso(tc), [pdata.get("text", "")]))
                    continue
                _flush()
                made = _part_line(pdata, _iso(tc))
                if made is not None:
                    lines.append(made[1])
            _flush()
            (cache / f"{sid}.jsonl").write_text(
                "\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n",
                encoding="utf-8")
            written += 1

        # (orphan GC already ran on the cheap path above, decoupled from this gate)
        _save_watermark(global_max)   # only after all sessions written (partial-fail safe)
        return written
    finally:
        if con is not None:
            con.close()
        try:
            snap.unlink()
            snap.parent.rmdir()
        except OSError:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_opencode_export.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/opencode_export.py tests/test_opencode_export.py
git commit -m "feat: opencode_export (consistent snapshot -> cache jsonl, watermark, GC)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: OpenCodeAdapter

**Files:**
- Create: `src/totalrecall/adapters/opencode.py`
- Create: `tests/fixtures/opencode_cache_basic.jsonl`
- Test: `tests/test_opencode_adapter.py`

- [ ] **Step 1: Write the fixture**

`tests/fixtures/opencode_cache_basic.jsonl` (export format — ONE JSON object per line, exactly these 8 lines incl. the trailing garbage):
```
{"type":"meta","session_id":"ses_x","cwd":"D:/work/demo","title":"t","started_at":"2026-06-10T10:00:00+00:00","ended_at":"2026-06-10T10:05:00+00:00"}
{"type":"text","role":"user","ts":"2026-06-10T10:00:00+00:00","text":"use PowerShell not bash"}
{"type":"text","role":"assistant","ts":"2026-06-10T10:00:05+00:00","text":"ok"}
{"type":"tool","ts":"2026-06-10T10:00:06+00:00","name":"bash","status":"error"}
{"type":"tool","ts":"2026-06-10T10:00:07+00:00","name":"read","status":"running"}
{"type":"patch","ts":"2026-06-10T10:00:08+00:00","files":["D:/work/demo/a.py"]}
{"type":"patch","ts":"2026-06-10T10:00:09+00:00","files":["D:/work/demo/a.py","D:/work/demo/a.py"]}
not-json-garbage
```

- [ ] **Step 2: Write the failing test**

`tests/test_opencode_adapter.py`:
```python
from pathlib import Path
from totalrecall.adapters.opencode import OpenCodeAdapter

FIX = Path(__file__).parent / "fixtures"

def _parse():
    return OpenCodeAdapter().parse(FIX / "opencode_cache_basic.jsonl")

def test_meta_fields():
    s = _parse()
    assert s.tool == "opencode"
    assert s.session_id == "ses_x"
    assert s.cwd == "D:/work/demo"
    assert s.git_branch is None
    assert s.is_analysis_session is False
    assert s.started_at == "2026-06-10T10:00:00+00:00"
    assert s.ended_at == "2026-06-10T10:05:00+00:00"

def test_turns_roles_and_tool():
    s = _parse()
    roles = [t.role for t in s.turns]
    assert roles == ["user", "assistant", "tool", "tool"]
    statuses = {t.tool_name: t.tool_status for t in s.turns if t.role == "tool"}
    assert statuses["bash"] == "error"
    assert statuses["read"] == "ok"          # 'running' recorded as ok, not error

def test_events_toolerror_churn():
    s = _parse()
    kinds = {e.kind for e in s.events}
    assert "tool_error" in kinds and "churn" in kinds
    churn = [e for e in s.events if e.kind == "churn"]
    assert churn[0].ref == "D:/work/demo/a.py"   # a.py: 1 + 2 = 3 edits -> churn

def test_stats():
    s = _parse()
    assert s.stats.n_turns == 4
    assert s.stats.n_tool_errors == 1            # only the error tool, not running
    assert s.stats.n_edits == 3                  # 1 + 2 patch file entries
    assert s.stats.duration_s == 300.0

def test_garbage_skipped():
    s = _parse()
    assert len(s.turns) == 4
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_opencode_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'totalrecall.adapters.opencode'`

- [ ] **Step 4: Implement**

`src/totalrecall/adapters/opencode.py`:
```python
from __future__ import annotations
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from ..models import NormalizedSession, Turn, Event, Stats

EDIT_CHURN_THRESHOLD = 3


def _parse_ts(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


class OpenCodeAdapter:
    tool = "opencode"

    def parse(self, path) -> NormalizedSession:
        session_id = cwd = ""
        started_at = ended_at = None
        turns: list[Turn] = []
        events: list[Event] = []
        file_counts: Counter[str] = Counter()
        n_edits = 0
        n_tool_errors = 0
        idx = 0

        for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                o = json.loads(raw)
            except json.JSONDecodeError:
                continue
            t = o.get("type")
            if t == "meta":
                session_id = o.get("session_id") or session_id
                cwd = o.get("cwd") or cwd
                started_at = o.get("started_at")
                ended_at = o.get("ended_at")
                continue
            ts = o.get("ts")
            if t == "text":
                role = "user" if o.get("role") == "user" else "assistant"
                text = o.get("text", "")
                if text.strip():
                    turns.append(Turn(idx, role, ts, text=text)); idx += 1
            elif t == "tool":
                status = "error" if o.get("status") == "error" else "ok"
                turns.append(Turn(idx, "tool", ts, tool_name=o.get("name"),
                                  tool_status=status)); idx += 1
                if status == "error":
                    n_tool_errors += 1
                    events.append(Event("tool_error", ts, o.get("name") or "?"))
            elif t == "patch":
                for fp in o.get("files") or []:
                    file_counts[fp] += 1
                    n_edits += 1

        for fp, count in file_counts.items():
            if count >= EDIT_CHURN_THRESHOLD:
                events.append(Event("churn", None, fp))

        start, end = _parse_ts(started_at), _parse_ts(ended_at)
        duration = (end - start).total_seconds() if start and end else 0.0
        return NormalizedSession(
            tool=self.tool, session_id=session_id, cwd=cwd, git_branch=None,
            started_at=started_at, ended_at=ended_at, is_analysis_session=False,
            turns=turns, events=events,
            stats=Stats(n_turns=len(turns), duration_s=duration,
                        n_tool_errors=n_tool_errors, n_edits=n_edits),
        )
```

- [ ] **Step 5: Run tests, then commit**

Run: `python -m pytest tests/test_opencode_adapter.py -v`
Expected: PASS
```bash
git add src/totalrecall/adapters/opencode.py tests/test_opencode_adapter.py tests/fixtures/opencode_cache_basic.jsonl
git commit -m "feat: OpenCodeAdapter parses export-format jsonl into NormalizedSession" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: for_path routes /opencode-cache/

**Files:**
- Modify: `src/totalrecall/adapters/__init__.py`
- Test: `tests/test_adapters_dispatch_opencode.py`

- [ ] **Step 1: Write the failing test**

`tests/test_adapters_dispatch_opencode.py`:
```python
from totalrecall import adapters

def test_opencode_cache_routes_to_opencode():
    a = adapters.for_path(r"C:\Users\u\.totalrecall\opencode-cache\ses_x.jsonl")
    assert type(a).__name__ == "OpenCodeAdapter"

def test_codex_and_cc_still_route():
    assert type(adapters.for_path(r"C:\Users\u\.codex\sessions\rollout-x.jsonl")).__name__ == "CodexAdapter"
    assert type(adapters.for_path(r"C:\Users\u\.claude\projects\p\s.jsonl")).__name__ == "ClaudeCodeAdapter"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_adapters_dispatch_opencode.py -v`
Expected: FAIL — routes to ClaudeCodeAdapter (default) instead of OpenCodeAdapter

- [ ] **Step 3: Implement**

Replace `src/totalrecall/adapters/__init__.py` with:
```python
from __future__ import annotations
from .claude_code import ClaudeCodeAdapter
from .codex import CodexAdapter
from .opencode import OpenCodeAdapter


def for_path(path):
    """Return the adapter for a transcript path, by which source dir it lives under."""
    s = str(path).replace("\\", "/")
    if "/.codex/sessions/" in s:
        return CodexAdapter()
    if "/opencode-cache/" in s:
        return OpenCodeAdapter()
    return ClaudeCodeAdapter()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_adapters_dispatch_opencode.py tests/test_adapters_dispatch.py -v`
Expected: PASS (new route; existing codex/cc dispatch still green)

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/adapters/__init__.py tests/test_adapters_dispatch_opencode.py
git commit -m "feat: for_path routes /opencode-cache/ to OpenCodeAdapter" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: reconcile scans the OpenCode cache (gated by sources)

**Files:**
- Modify: `src/totalrecall/reconcile.py`
- Test: `tests/test_reconcile_opencode.py`

- [ ] **Step 1: Write the failing test**

`tests/test_reconcile_opencode.py`:
```python
from totalrecall import reconcile, queue, paths

def test_opencode_cache_scanned_when_enabled(home, monkeypatch):
    paths.ensure_dirs()
    paths.config_path().write_text(
        "[sources]\nclaude_code = false\ncodex = false\nopencode = true\n", encoding="utf-8")
    cache = paths.opencode_cache_dir(); cache.mkdir(parents=True, exist_ok=True)
    f = cache / "ses_x.jsonl"; f.write_text("x", encoding="utf-8")
    n = reconcile.run(recent_seconds=0)
    assert str(f) in set(queue.drain())
    assert n == 1

def test_opencode_not_scanned_when_disabled(home, monkeypatch):
    paths.ensure_dirs()   # default config: opencode = false
    cache = paths.opencode_cache_dir(); cache.mkdir(parents=True, exist_ok=True)
    (cache / "ses_y.jsonl").write_text("x", encoding="utf-8")
    monkeypatch.setattr(reconcile, "claude_projects_dir", lambda: paths.state_dir() / "noexist")
    assert reconcile.run(recent_seconds=0) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_reconcile_opencode.py -v`
Expected: FAIL — `test_opencode_cache_scanned_when_enabled` enqueues 0 (opencode source not wired)

- [ ] **Step 3: Implement**

In `src/totalrecall/reconcile.py`, add a cache-dir helper after `codex_sessions_dir`:
```python
def opencode_cache_dir():
    return paths.opencode_cache_dir()
```
and in `run`, after the codex source append, add the opencode source. Replace:
```python
    if cfg.sources.get("codex"):
        sources.append((codex_sessions_dir(), None))   # codex sessions are never analysis sessions
```
with:
```python
    if cfg.sources.get("codex"):
        sources.append((codex_sessions_dir(), None))   # codex sessions are never analysis sessions
    if cfg.sources.get("opencode"):
        sources.append((opencode_cache_dir(), None))   # exported cache; never analysis sessions
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_reconcile_opencode.py tests/test_reconcile.py tests/test_reconcile_codex.py -v`
Expected: PASS (opencode scanned only when enabled; existing CC/Codex reconcile tests still green — default config has all-but-claude_code false)

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/reconcile.py tests/test_reconcile_opencode.py
git commit -m "feat: reconcile scans opencode cache dir when sources.opencode enabled" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: worker.run does a cheap-probe-gated OpenCode sync

**Files:**
- Modify: `src/totalrecall/worker.py`
- Test: `tests/test_worker_opencode_sync.py`

- [ ] **Step 1: Write the failing test**

`tests/test_worker_opencode_sync.py`:
```python
from totalrecall import worker, paths

def test_sync_called_first_run_ok_false_when_enabled(home, monkeypatch):
    paths.ensure_dirs()
    paths.config_path().write_text("[sources]\nopencode = true\n", encoding="utf-8")
    seen = {"first_run_ok": None, "n": 0}
    def fake_sync(first_run_ok=True):
        seen["first_run_ok"] = first_run_ok; seen["n"] += 1; return 0
    monkeypatch.setattr(worker.opencode_export, "sync", fake_sync)
    monkeypatch.setattr(worker.reconcile, "run", lambda: 0)
    worker.run()
    assert seen["n"] == 1
    assert seen["first_run_ok"] is False   # worker must NOT do the cold backfill (HOLE B)

def test_sync_skipped_when_disabled(home, monkeypatch):
    paths.ensure_dirs()   # default: opencode = false
    called = {"n": 0}
    monkeypatch.setattr(worker.opencode_export, "sync",
                        lambda first_run_ok=True: called.__setitem__("n", called["n"] + 1))
    monkeypatch.setattr(worker.reconcile, "run", lambda: 0)
    worker.run()
    assert called["n"] == 0

def test_sync_failure_does_not_abort_worker(home, monkeypatch):
    paths.ensure_dirs()
    paths.config_path().write_text("[sources]\nopencode = true\n", encoding="utf-8")
    def boom(first_run_ok=True):
        raise RuntimeError("db locked")
    monkeypatch.setattr(worker.opencode_export, "sync", boom)
    monkeypatch.setattr(worker.reconcile, "run", lambda: 0)
    assert worker.run() == "done"     # silent-fail; worker completes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_worker_opencode_sync.py -v`
Expected: FAIL — `AttributeError: module 'totalrecall.worker' has no attribute 'opencode_export'`

- [ ] **Step 3: Implement**

In `src/totalrecall/worker.py`, add `opencode_export` to the package import line:
```python
from . import (queue, ledger, config, catalog, merger, render, reconcile,
               orchestrator, paths, synth, adapters, opencode_export)
```
and in `run`, replace:
```python
        cfg = config.load()
        reconcile.run()
```
with:
```python
        cfg = config.load()
        if cfg.sources.get("opencode"):
            try:
                # incremental only: cheap watermark probe inside; first-run cold backfill
                # is deferred to the manual `sync-opencode` (HOLE B). Silent-fail.
                opencode_export.sync(first_run_ok=False)
            except Exception:
                pass                      # OpenCode db issues must never abort the worker
        reconcile.run()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_worker_opencode_sync.py tests/test_worker.py tests/test_worker_codex.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/worker.py tests/test_worker_opencode_sync.py
git commit -m "feat: worker.run syncs OpenCode (probe-gated, silent-fail) before reconcile" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: CLI sync-opencode + full suite + README

**Files:**
- Modify: `src/totalrecall/cli.py`
- Modify: `README.md`
- Test: `tests/test_cli_opencode.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli_opencode.py`:
```python
from totalrecall import cli

def test_sync_opencode_dispatch(home, monkeypatch):
    called = {}
    monkeypatch.setattr(cli.opencode_export, "sync",
                        lambda: called.setdefault("n", 7) or 7)
    assert cli.main(["sync-opencode"]) == 0
    assert called.get("n") == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli_opencode.py -v`
Expected: FAIL — argparse error: invalid choice 'sync-opencode'

- [ ] **Step 3: Implement**

In `src/totalrecall/cli.py`, add `opencode_export` to the package import line:
```python
from . import (hookinstall, worker, reconcile, synth, config, ledger,
               patterns_store, hookcmd, queue, proposer, applier, proposals_store,
               opencode_export)
```
Register the subparser after the `proposals` parser:
```python
    sub.add_parser("sync-opencode")
```
Add dispatch before the final `return 1`:
```python
    if args.cmd == "sync-opencode":
        n = opencode_export.sync()
        print(f"opencode synced: {n}"); return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli_opencode.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: ALL PASS (112 prior + the OpenCode additions)

- [ ] **Step 6: Add a README section**

Append to `README.md` after the Codex section:
```markdown
## 多工具:OpenCode

把 `~/.totalrecall/config.toml` 的 `[sources]` 下 `opencode = true` 打开。OpenCode 把会话存在单个 SQLite
库(`~/.local/share/opencode/opencode.db`),TotalRecall 先用 `totalrecall sync-opencode` 把每个会话**只读**
导出成 `~/.totalrecall/opencode-cache/<sid>.jsonl`(用 SQLite 一致性快照,绝不写你的库),再走与其它来源相同的
分析管线。worker 运行时也会先做一次廉价的增量 sync。立刻分析:`totalrecall sync-opencode && totalrecall worker`。
摩擦以 `tool=opencode` 证据进入同一模式库。
```

- [ ] **Step 7: Commit**

```bash
git add src/totalrecall/cli.py tests/test_cli_opencode.py README.md
git commit -m "feat: CLI sync-opencode + README OpenCode section" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 8: Manual enablement + backfill (operational — after merge, when the user wants it)**

NOT a code step; the operational rollout (backfill all 368 OpenCode sessions):
```
# enable in ~/.totalrecall/config.toml: under [sources], set opencode = true
totalrecall sync-opencode   # full first export of all sessions (consistent snapshot)
totalrecall reconcile       # enqueue settled cache files
totalrecall worker          # analyze (crash-safe; consider Haiku in config for the bulk)
totalrecall status
```
Expected: ~368 OpenCode sessions analyzed into the same pattern library; `insights.md` gains `tool=opencode` friction.

---

## Self-Review

**Spec coverage (spec §→task):**
- §5 export line format → Task 3 (`_part_line` + meta) + consumed by Task 4 adapter.
- §6 OpenCodeAdapter (text/tool/patch, tool_error, churn, running→ok, tz from meta, is_analysis_session=False, stats) → Task 4.
- §7 opencode_export (SQLite `backup()` snapshot, never writes db; global watermark short-circuit; ledger-hash as sole staleness authority; orphan GC; persisted `opencode-sync.json`) → Task 3.
- §8 for_path `/opencode-cache/` → Task 5; reconcile opencode source + `opencode_cache_dir` → Task 6; `paths.opencode_cache_dir/opencode_sync_path` → Task 2; config `sources.opencode` (already exists) gates → Tasks 6/7.
- §9 worker inline cheap-probe-gated sync, silent-fail → Task 7 (worker wraps in try/except). **The cheap `max(time_updated)` probe runs on a read-only connection at the TOP of `sync()`, BEFORE any `_snapshot()` — so the unchanged hot path never copies the db** (Task 3; tested by `test_export_skips_when_watermark_unchanged` asserting `_snapshot` is not called). Backfill 368 manual → Task 8 Step 8.
- §6 I1 merger dedup by session_id (cross-source) → Task 1.
- §10 testing → Tasks 1-8 (sqlite fixture export, adapter golden fixture, dispatch, reconcile gating, worker sync gating + silent-fail, cli).
- §12 robustness items: C1 (watermark + hash-only skip) Task 3; C2 (orphan GC) Task 3; I1 (session dedup) Task 1; I2 (probe-gated, silent-fail, no heavy I/O unless changed) Tasks 3+7; I3 (`Connection.backup()`) Task 3; M1 (running→ok) Task 4; M5 (tz-aware ISO via `_iso`) Tasks 3+4.
- **Cross-document review fixes (3rd round, interaction holes):** HOLE A (session dedup must NOT skip the post-apply `ineffective` check) → Task 1 rewrites the whole `_apply` + adds `test_same_session_recurrence_after_apply_still_marks_ineffective`; HOLE B (worker must not do the cold 368-session export under the lock) → `sync(first_run_ok=False)` from the worker defers to manual `sync-opencode`, tested by `test_first_run_deferred_on_worker_path` + Task 7's `first_run_ok is False` assertion; HOLE C (orphan GC unreachable when watermark short-circuits) → GC moved to the cheap read-only path in Task 3, decoupled from the watermark gate.

**Placeholder scan:** none — all code steps carry complete runnable code. Task 8 Step 8 is explicitly operational, not a code step.

**Type consistency:** `opencode_export.sync() -> int` and `opencode_export.opencode_db_path()` used in Tasks 3/7/8 consistently. `OpenCodeAdapter.parse(path) -> NormalizedSession` matches the `Adapter` protocol and siblings. `paths.opencode_cache_dir()` / `paths.opencode_sync_path()` (Task 2) used by Tasks 3/6. `reconcile.opencode_cache_dir()` wraps `paths.opencode_cache_dir()` (Task 6) — both names exist, the reconcile one is the monkeypatch seam mirroring `codex_sessions_dir`. Export line format keys (`type/session_id/cwd/started_at/ended_at`, `text/role/ts/text`, `tool/name/status`, `patch/files`) are produced in Task 3 and consumed identically in Task 4. `merger._apply` dedup change (Task 1) is compatible with all existing Evidence (which always carries `session_id`).

**Note on test isolation:** Task 3's `_build_db` writes a *test* sqlite db in `tmp_path` and monkeypatches `opencode_export.opencode_db_path` — the real `~/.local/share/opencode/opencode.db` is never touched by tests. Task 7's tests monkeypatch `worker.opencode_export.sync` so no real db/CLI is invoked.

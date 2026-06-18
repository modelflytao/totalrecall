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
    # text parts are handled inline in sync() (buffered per message); _part_line covers the rest.
    t = data.get("type")
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
    if cache.exists() and live_sids:        # guard: never wipe the whole cache on an empty session set
        for fp in cache.glob("*.jsonl"):
            if fp.stem not in live_sids:
                try:
                    fp.unlink()
                except OSError:
                    pass                    # briefly-locked file: GC it next run, don't abort sync

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
            text_buf = []      # [(role, mid, ts, [texts])] — single-element while buffering
            def _flush():
                if text_buf:
                    role, _mid, ts0, chunks = text_buf[0]
                    joined = "\n".join(chunks)
                    if joined.strip():
                        lines.append({"type": "text", "ts": ts0, "role": role, "text": joined})
                    text_buf.clear()
            for mid, tc, pdata in parts_by_session.get(sid, []):
                if pdata.get("type") == "text":
                    role = "user" if msg_role.get(mid) == "user" else "assistant"
                    if text_buf and text_buf[0][0] == role and text_buf[0][1] == mid:
                        text_buf[0][3].append(pdata.get("text", ""))   # same message -> join
                    else:
                        _flush()                                       # new message/role -> new turn
                        text_buf.append((role, mid, _iso(tc), [pdata.get("text", "")]))
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

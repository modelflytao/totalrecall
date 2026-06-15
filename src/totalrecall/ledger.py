from __future__ import annotations
import hashlib
import json
from pathlib import Path
from . import paths


def _hash_file(p: Path) -> str:
    h = hashlib.sha1()
    h.update(Path(p).read_bytes())
    return h.hexdigest()


class Ledger:
    def __init__(self, done: dict, pending: dict):
        self._done = done        # session_id -> {"hash":..., "path":...}
        self._pending = pending  # session_id -> path

    @classmethod
    def load(cls) -> "Ledger":
        p = paths.ledger_path()
        if not p.exists():
            return cls({}, {})
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls(data.get("done", {}), data.get("pending", {}))

    def save(self) -> None:
        paths.ensure_dirs()
        paths.ledger_path().write_text(
            json.dumps({"done": self._done, "pending": self._pending}, indent=2),
            encoding="utf-8")

    def is_new(self, path) -> bool:
        path = Path(path)
        cur = _hash_file(path)
        for rec in self._done.values():
            if rec.get("path") == str(path) and rec.get("hash") == cur:
                return False
        return True

    def mark_done(self, session_id: str, path) -> None:
        self._done[session_id] = {"hash": _hash_file(Path(path)), "path": str(path)}
        self._pending.pop(session_id, None)

    def mark_pending(self, session_id: str, path: str) -> None:
        self._pending[session_id] = str(path)

    def pending_items(self):
        return [(sid, p) for sid, p in self._pending.items()]

    def done_paths(self) -> set[str]:
        return {rec["path"] for rec in self._done.values()}

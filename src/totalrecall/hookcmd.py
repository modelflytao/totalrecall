from __future__ import annotations
import json
import os
import subprocess
import sys
from . import queue, config, paths


def _spawn_worker() -> None:
    """Spawn `totalrecall worker` fully detached so the hook returns instantly."""
    args = [sys.executable, "-m", "totalrecall.cli", "worker"]
    try:
        if os.name == "nt":
            DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(args, creationflags=DETACHED, close_fds=True)
        else:
            subprocess.Popen(args, start_new_session=True, close_fds=True)
    except Exception:
        pass


def handle(stdin, env) -> int:
    """SessionEnd hook body. MUST be fast, non-blocking, and never raise."""
    try:
        marker = config.load().analysis_marker_env
        if env.get(marker):                 # hook-layer self-exclusion
            return 0
        payload = json.loads(stdin.read() or "{}")
        path = payload.get("transcript_path")
        if path:
            queue.enqueue(path)
            _spawn_worker()
    except Exception as e:                    # never break the user's session
        try:
            paths.log_path().open("a", encoding="utf-8").write(f"hook error: {e}\n")
        except Exception:
            pass
    return 0


def main() -> int:
    return handle(sys.stdin, os.environ)

import os
import subprocess
import sys


def test_module_entrypoint_invokes_main(tmp_path):
    env = dict(os.environ)
    env["TOTALRECALL_HOME"] = str(tmp_path / "trhome")
    r = subprocess.run(
        [sys.executable, "-m", "totalrecall.cli", "status"],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert "patterns:" in r.stdout

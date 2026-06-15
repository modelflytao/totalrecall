import os
import pytest

@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated ~/.totalrecall for each test."""
    h = tmp_path / "trhome"
    h.mkdir()
    monkeypatch.setenv("TOTALRECALL_HOME", str(h))
    return h

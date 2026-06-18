from totalrecall import cli

def test_sync_opencode_dispatch(home, monkeypatch):
    called = {}
    monkeypatch.setattr(cli.opencode_export, "sync",
                        lambda: called.setdefault("n", 7) or 7)
    assert cli.main(["sync-opencode"]) == 0
    assert called.get("n") == 7

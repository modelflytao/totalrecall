from totalrecall import paths

def test_opencode_paths(home):
    assert paths.opencode_cache_dir() == home / "opencode-cache"
    assert paths.opencode_sync_path() == home / "opencode-sync.json"

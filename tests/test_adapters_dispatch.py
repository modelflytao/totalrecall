from totalrecall import adapters

def test_for_path_routes_codex_vs_cc():
    cdx = adapters.for_path(r"C:\Users\u\.codex\sessions\2026\06\rollout-x.jsonl")
    cc = adapters.for_path(r"C:\Users\u\.claude\projects\proj\s.jsonl")
    assert type(cdx).__name__ == "CodexAdapter"
    assert type(cc).__name__ == "ClaudeCodeAdapter"

def test_for_path_default_is_claude_code():
    assert type(adapters.for_path("/some/other/path.jsonl")).__name__ == "ClaudeCodeAdapter"

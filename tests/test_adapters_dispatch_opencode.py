from totalrecall import adapters

def test_opencode_cache_routes_to_opencode():
    a = adapters.for_path(r"C:\Users\u\.totalrecall\opencode-cache\ses_x.jsonl")
    assert type(a).__name__ == "OpenCodeAdapter"

def test_codex_and_cc_still_route():
    assert type(adapters.for_path(r"C:\Users\u\.codex\sessions\rollout-x.jsonl")).__name__ == "CodexAdapter"
    assert type(adapters.for_path(r"C:\Users\u\.claude\projects\p\s.jsonl")).__name__ == "ClaudeCodeAdapter"

from totalrecall import config, paths

def test_phase2_defaults(home):
    cfg = config.load()
    assert cfg.propose_top_n == 10
    assert cfg.propose_min_occ == 3
    assert cfg.resolved_after_days == 14
    assert cfg.rules_file.endswith("totalrecall-rules.md")
    assert cfg.claude_md.endswith("CLAUDE.md")

def test_phase2_file_override(home):
    paths.ensure_dirs()
    paths.config_path().write_text(
        "[phase2]\npropose_top_n = 3\nresolved_after_days = 7\n", encoding="utf-8")
    cfg = config.load()
    assert cfg.propose_top_n == 3 and cfg.resolved_after_days == 7
    assert cfg.propose_min_occ == 3  # untouched default

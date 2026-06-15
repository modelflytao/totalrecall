from totalrecall import config, paths

def test_defaults_when_no_file(home):
    cfg = config.load()
    assert cfg.extract_model == "claude-sonnet-4-6"
    assert cfg.synth_model == "claude-sonnet-4-6"
    assert cfg.synth_every_n_sessions == 20
    assert cfg.catalog_topk == 40
    assert cfg.sources["claude_code"] is True
    assert cfg.analysis_marker_env == "TOTALRECALL_ANALYSIS"

def test_file_overrides_defaults(home):
    paths.ensure_dirs()
    paths.config_path().write_text(
        '[models]\nextract = "claude-haiku-4-5-20251001"\n'
        '[limits]\nsynth_every_n_sessions = 5\n',
        encoding="utf-8",
    )
    cfg = config.load()
    assert cfg.extract_model == "claude-haiku-4-5-20251001"
    assert cfg.synth_every_n_sessions == 5
    assert cfg.synth_model == "claude-sonnet-4-6"  # untouched default

def test_default_toml_text_parses(home):
    text = config.default_toml()
    assert "[models]" in text and "claude-sonnet-4-6" in text

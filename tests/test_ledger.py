from totalrecall import ledger, paths

def test_unseen_then_seen(home):
    paths.ensure_dirs()
    p = home / "t.jsonl"
    p.write_text("hello", encoding="utf-8")
    lg = ledger.Ledger.load()
    assert lg.is_new(p) is True
    lg.mark_done("s1", p)
    lg.save()
    lg2 = ledger.Ledger.load()
    assert lg2.is_new(p) is False           # same content -> not new

def test_changed_content_is_new_again(home):
    paths.ensure_dirs()
    p = home / "t.jsonl"
    p.write_text("hello", encoding="utf-8")
    lg = ledger.Ledger.load()
    lg.mark_done("s1", p); lg.save()
    p.write_text("hello world", encoding="utf-8")   # grew
    assert ledger.Ledger.load().is_new(p) is True

def test_pending_roundtrip(home):
    paths.ensure_dirs()
    lg = ledger.Ledger.load()
    lg.mark_pending("s9", "/path/x.jsonl"); lg.save()
    assert ("s9", "/path/x.jsonl") in ledger.Ledger.load().pending_items()

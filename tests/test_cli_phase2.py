from totalrecall import cli

def test_dispatch_phase2(home, monkeypatch):
    called = {}
    monkeypatch.setattr(cli.proposer, "propose",
                        lambda top_n, min_occ, now, model: called.setdefault("propose", True) or 1)
    monkeypatch.setattr(cli.applier, "apply",
                        lambda ids, cfg, now: called.setdefault("apply", ids) or len(ids))
    monkeypatch.setattr(cli.applier, "reject",
                        lambda ids: called.setdefault("reject", ids) or len(ids))
    assert cli.main(["propose"]) == 0 and called.get("propose")
    assert cli.main(["apply", "p-a", "p-b"]) == 0 and called["apply"] == ["p-a", "p-b"]
    assert cli.main(["reject", "p-a"]) == 0 and called["reject"] == ["p-a"]

def test_proposals_lists(home, capsys):
    from totalrecall import proposals_store
    from totalrecall.proposals_store import Proposal
    from totalrecall import paths
    paths.ensure_dirs()
    proposals_store.upsert(Proposal("p-a", "pat", "f", "r", "why", status="drafted"))
    assert cli.main(["proposals"]) == 0
    assert "p-a" in capsys.readouterr().out

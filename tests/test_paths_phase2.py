from totalrecall import paths

def test_proposal_paths(home):
    assert paths.proposals_path() == home / "proposals.json"
    assert paths.proposals_md_path() == home / "proposals.md"

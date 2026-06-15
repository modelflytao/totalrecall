import totalrecall

def test_version_present():
    assert isinstance(totalrecall.__version__, str)
    assert totalrecall.__version__

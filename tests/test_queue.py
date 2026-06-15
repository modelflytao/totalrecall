from totalrecall import queue, paths

def test_enqueue_dequeue_fifo(home):
    paths.ensure_dirs()
    queue.enqueue("/a.jsonl")
    queue.enqueue("/b.jsonl")
    assert queue.size() == 2
    items = queue.drain()
    assert items == ["/a.jsonl", "/b.jsonl"]
    assert queue.size() == 0

def test_enqueue_dedupes_same_path(home):
    paths.ensure_dirs()
    queue.enqueue("/a.jsonl")
    queue.enqueue("/a.jsonl")
    assert queue.size() == 1

def test_worker_lock_is_exclusive(home):
    paths.ensure_dirs()
    with queue.worker_lock() as got:
        assert got is True
        with queue.worker_lock() as second:
            assert second is False   # already held in-process (non-blocking)

def test_claim_next_does_not_delete_until_complete(home):
    paths.ensure_dirs()
    queue.enqueue("/a.jsonl")
    job_file, path = queue.claim_next()
    assert path == "/a.jsonl"
    assert queue.size() == 1            # still present -> crash-safe (re-processable)
    # claiming again returns the SAME job (not yet completed)
    assert queue.claim_next()[1] == "/a.jsonl"
    queue.complete(job_file)
    assert queue.size() == 0
    assert queue.claim_next() is None

def test_claim_next_fifo_then_complete(home):
    paths.ensure_dirs()
    queue.enqueue("/a.jsonl")
    queue.enqueue("/b.jsonl")
    j1, p1 = queue.claim_next(); assert p1 == "/a.jsonl"; queue.complete(j1)
    j2, p2 = queue.claim_next(); assert p2 == "/b.jsonl"; queue.complete(j2)
    assert queue.claim_next() is None

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

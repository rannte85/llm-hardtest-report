from taskhub.store import ResultStore


def test_commit_then_get():
    store = ResultStore()
    snapshot = store.begin("a")
    assert store.commit(snapshot, 41) is True
    assert store.get("a") == 41
    assert store.entry("a").generation == 0


def test_invalidate_drops_entry_and_bumps_generation():
    store = ResultStore()
    store.commit(store.begin("a"), "v0")
    assert store.generation("a") == 0
    assert store.invalidate("a") == 1
    assert store.get("a") is None
    assert store.entry("a") is None
    assert store.generation("a") == 1


def test_generation_is_monotonic():
    store = ResultStore()
    seen = [store.invalidate("k") for _ in range(5)]
    assert seen == [1, 2, 3, 4, 5]
    assert store.generation("k") == 5


def test_fresh_commit_after_invalidate_is_visible():
    store = ResultStore()
    store.commit(store.begin("a"), "old")
    store.invalidate("a")
    snapshot = store.begin("a")
    assert snapshot.generation == 1
    assert store.commit(snapshot, "new") is True
    assert store.get("a") == "new"
    assert store.entry("a").generation == 1


def test_stats_and_cancellation_bookkeeping():
    store = ResultStore()
    store.commit(store.begin("a"), 1)
    store.get("a")
    store.get("missing")
    store.mark_cancelled([7, 8, 7])
    stats = store.stats()
    assert stats["commits"] == 1
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["entries"] == 1
    assert store.is_cancelled(7) and not store.is_cancelled(9)

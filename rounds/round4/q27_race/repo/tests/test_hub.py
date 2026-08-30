from taskhub import TaskHub

from tests.support import spin


def test_submit_then_get():
    hub = TaskHub(workers=2).start()
    try:
        hub.submit("a", lambda: (spin(), "A")[1])
        assert hub.drain(5.0) is True
        assert hub.get("a") == "A"
    finally:
        hub.shutdown()


def test_invalidate_after_completion_clears_the_value():
    hub = TaskHub(workers=2).start()
    try:
        hub.submit("a", lambda: "A")
        assert hub.drain(5.0) is True
        assert hub.get("a") == "A"
        hub.invalidate("a")
        assert hub.get("a") is None
        assert hub.generation("a") == 1
        assert hub.stale_entries() == []
    finally:
        hub.shutdown()


def test_recompute_after_invalidate():
    hub = TaskHub(workers=2).start()
    try:
        hub.submit("a", lambda: "first")
        assert hub.drain(5.0) is True
        hub.invalidate("a")
        hub.submit("a", lambda: "second")
        assert hub.drain(5.0) is True
        assert hub.get("a") == "second"
        assert hub.entry("a").generation == 1
        assert hub.stale_entries() == []
    finally:
        hub.shutdown()


def test_many_keys_settle():
    hub = TaskHub(workers=4).start()
    try:
        for n in range(40):
            hub.submit("k%d" % (n % 8), (lambda n=n: (spin(50), n)[1]))
        assert hub.drain(5.0) is True
        assert len(hub.keys()) == 8
        assert hub.stale_entries() == []
    finally:
        hub.shutdown()

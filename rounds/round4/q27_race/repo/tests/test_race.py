"""Invariant G under concurrent invalidation.

This is the test that goes red on CI now and then.  It has two shapes:

  * the default shape just hammers the hub and hopes the interleaving shows up;
  * the shape used when ``tests.config.BARRIER_MODE`` is on parks the producer
    on a tracepoint so the interleaving is forced instead of hoped for.

See ``docs/DESIGN.md`` for invariant G and ``run_tests.py --help`` for how the
mode is selected.
"""

import threading
import time

from taskhub import TaskHub
from taskhub.tracepoints import BarrierController, set_controller

from tests import config
from tests.support import run_off_thread, spin


def test_no_stale_entry_survives_invalidation():
    if config.BARRIER_MODE:
        _forced_interleaving()
    else:
        _stress()


def _stress_job(key, n):
    """A job like the real ones: mostly CPU, occasionally touching I/O."""
    does_io = (n % config.STRESS_SLOW_EVERY) == 0

    def fn():
        spin(config.STRESS_SPIN)
        if does_io:
            for _ in range(config.STRESS_YIELDS):
                time.sleep(0)  # stands in for a socket / disk boundary
                spin(config.STRESS_SPIN)
        return (key, n)

    return fn


def _stress():
    keys = ["s%d" % i for i in range(config.STRESS_KEYS)]
    hub = TaskHub(workers=4).start()
    stop = threading.Event()
    observed = []

    def invalidator():
        while not stop.is_set():
            for key in keys:
                hub.invalidate(key)
            time.sleep(config.STRESS_INVALIDATE_GAP)

    def watchdog():
        # Invariant G has to hold at every moment, not only once the dust has
        # settled, so keep looking while the hub is busy.
        while not stop.is_set():
            stale = hub.stale_entries()
            if stale:
                observed.append(stale)
                return
            time.sleep(config.STRESS_SAMPLE_GAP)

    threads = [run_off_thread(invalidator), run_off_thread(watchdog)]
    try:
        for n in range(config.STRESS_JOBS):
            key = keys[n % len(keys)]
            hub.submit(key, _stress_job(key, n))
        assert hub.drain(10.0) is True
        stop.set()
        for thread in threads:
            thread.join(5.0)
        stale = observed[0] if observed else hub.stale_entries()
        assert stale == [], (
            "invariant G violated: a value from an invalidated generation was "
            "observable: %r" % (stale,)
        )
    finally:
        stop.set()
        hub.shutdown()


def _forced_interleaving():
    controller = BarrierController()
    gate = controller.gate("store.after_snapshot", count=1, timeout=5.0)
    set_controller(controller)
    hub = TaskHub(workers=2).start()
    try:
        hub.submit("forced", lambda: "computed-from-generation-0")
        assert gate.wait_arrival(5.0), (
            "no producer reached store.after_snapshot -- tracepoint missing?"
        )

        # Invalidate off-thread: a correct implementation lets this return at
        # once, so do not let a slow one wedge the test.
        invalidation = run_off_thread(lambda: hub.invalidate("forced"))
        invalidation.join(0.5)
        gate.release()
        invalidation.join(5.0)

        assert hub.drain(10.0) is True
        assert hub.get("forced") is None, (
            "a value computed from generation 0 became visible after "
            "generation 0 was invalidated: %r" % (hub.get("forced"),)
        )
        assert hub.stale_entries() == []
    finally:
        set_controller(None)
        controller.release_all()
        hub.shutdown()

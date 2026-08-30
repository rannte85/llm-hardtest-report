"""Deterministic scheduling seam.

A handful of well known points inside ``taskhub`` call :func:`trace`.  With no
controller installed (the production default) ``trace`` is a cheap no-op.

Tests may install a controller in order to *pin* a thread interleaving that
would otherwise only show up once in a few thousand runs.  This is the only
supported way to write a reproducible concurrency regression test against this
package, so the tracepoint names are part of the internal test contract: do not
remove or rename them.

Currently emitted tracepoints:

    ``store.after_snapshot``    a producer has read a key's generation
    ``store.before_commit``     a producer is about to publish a value
    ``store.after_invalidate``  a key's generation has been bumped
    ``worker.before_run``       a worker picked a job off the queue
"""

import threading

__all__ = [
    "trace",
    "set_controller",
    "get_controller",
    "BarrierController",
    "Gate",
]

_controller = None
_install_lock = threading.Lock()


def set_controller(controller):
    """Install (or clear, with ``None``) the process wide trace controller."""
    global _controller
    with _install_lock:
        previous = _controller
        _controller = controller
    return previous


def get_controller():
    return _controller


def trace(name, **context):
    """Report that execution reached ``name``.

    No-op unless a controller is installed.  A controller is allowed to block
    the calling thread, which is exactly what makes interleavings reproducible.
    """
    controller = _controller
    if controller is None:
        return
    controller.on_trace(name, context)


class Gate:
    """A one-shot (or n-shot) checkpoint.

    The first ``count`` threads that reach the gate record their context, set
    :attr:`arrived` and then block until :meth:`release` is called (or the
    safety timeout expires).  Further arrivals pass straight through.
    """

    def __init__(self, name, count=1, timeout=5.0):
        self.name = name
        self.timeout = timeout
        self.hits = []
        self._remaining = count
        self._lock = threading.Lock()
        self.arrived = threading.Event()
        self.released = threading.Event()

    def hit(self, context):
        with self._lock:
            if self._remaining <= 0:
                return
            self._remaining -= 1
            self.hits.append(context)
        self.arrived.set()
        self.released.wait(self.timeout)

    def wait_arrival(self, timeout=5.0):
        """Block until some thread has reached this gate."""
        return self.arrived.wait(timeout)

    def release(self):
        self.released.set()

    def __repr__(self):
        return "Gate(%r, hits=%d, released=%s)" % (
            self.name,
            len(self.hits),
            self.released.is_set(),
        )


class BarrierController:
    """Trace controller that parks threads at named gates."""

    def __init__(self):
        self._gates = {}
        self._lock = threading.Lock()
        self.seen = []

    def gate(self, name, count=1, timeout=5.0):
        gate = Gate(name, count=count, timeout=timeout)
        with self._lock:
            self._gates[name] = gate
        return gate

    def on_trace(self, name, context):
        with self._lock:
            self.seen.append(name)
            gate = self._gates.get(name)
        if gate is not None:
            gate.hit(context)

    def release_all(self):
        with self._lock:
            gates = list(self._gates.values())
        for gate in gates:
            gate.release()

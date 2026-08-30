"""Deterministic stand-in for the upstream quote API.

The production build wires a socket transport into :class:`~svc.http_client.HttpClient`;
outside production (dev boxes, the tools in ``tools/``, the test-suite) the
simulator below is used so that behaviour is reproducible without a network.

A transport is any callable ``transport(url, timeout_ms) -> dict`` that raises
:class:`TransportError` when the round trip fails.
"""


class TransportError(Exception):
    """Raised for any failed round trip: timeout, reset, non-2xx status."""


class SimulatedUpstream:
    """Deterministic upstream.

    :param latency_ms:   simulated round-trip time. A call whose latency exceeds
                         the client timeout fails as a timeout.
    :param fail_calls:   how many of the first calls answer with ``error_status``.
                         ``None`` means "every call fails".
    :param error_status: the HTTP status used for those failures.
    """

    def __init__(self, latency_ms=12, fail_calls=0, error_status=503, payload=None):
        self.latency_ms = latency_ms
        self.fail_calls = fail_calls
        self.error_status = error_status
        self.payload = payload or {"amount": 1240, "currency": "JPY"}
        self.calls = []

    def __call__(self, url, timeout_ms):
        self.calls.append(url)
        if self.latency_ms > timeout_ms:
            raise TransportError("read timed out after %dms" % timeout_ms)
        if self.fail_calls is None or len(self.calls) <= self.fail_calls:
            raise TransportError("upstream answered http %d" % self.error_status)
        answer = dict(self.payload)
        answer["url"] = url
        return answer

    @property
    def call_count(self):
        return len(self.calls)

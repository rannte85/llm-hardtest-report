"""Thin HTTP client around a transport callable."""

import logging

from .clock import SystemClock
from .errors import UpstreamTimeout
from .transport import TransportError

LOG = logging.getLogger("svc.http")


class HttpClient:
    def __init__(self, base_url, timeout_ms, transport, clock=None):
        self.base_url = base_url
        self.timeout_ms = int(timeout_ms)
        self._transport = transport
        self._clock = clock or SystemClock()
        self.warnings = []

    def build_url(self, params=None):
        if not params:
            return self.base_url
        query = "&".join("%s=%s" % (key, params[key]) for key in sorted(params))
        separator = "&" if "?" in self.base_url else "?"
        return self.base_url + separator + query

    def get(self, params=None):
        url = self.build_url(params)
        started = self._clock.now_ms()
        try:
            return self._transport(url, self.timeout_ms)
        except TransportError as exc:
            # NOTE(net-114): the transport hands us a single error type and does
            # not tell us which failure mode it hit, so every failed round trip
            # is reported in the generic form below. The per-status breakdown of
            # what upstream actually answered lives in the metrics snapshot
            # (see tools/show_metrics.py).
            message = "upstream read timeout after %dms url=%s" % (self.timeout_ms, url)
            LOG.warning(message)
            self.warnings.append(message)
            raise UpstreamTimeout(message) from exc
        finally:
            self.last_duration_ms = self._clock.now_ms() - started

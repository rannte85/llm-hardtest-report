"""The quote service: one client request, N upstream attempts."""

import logging

from .clock import SystemClock
from .errors import RetriesExhausted, TransientError
from .http_client import HttpClient
from .retry import RetryPolicy

LOG = logging.getLogger("svc.retry")


class QuoteService:
    """Fetch a quote for a tenant, retrying transient upstream failures.

    :param config:    mapping produced by :func:`svc.config.load_config`
    :param transport: ``transport(url, timeout_ms) -> dict``
    :param clock:     object with ``sleep_ms`` / ``now_ms``
    """

    def __init__(self, config, transport, clock=None):
        self.config = config
        self.clock = clock or SystemClock()
        self.client = HttpClient(
            config["upstream_url"],
            config["timeout_ms"],
            transport,
            self.clock,
        )
        self.policy = RetryPolicy.from_config(config)
        self.attempts = 0
        self.delays = []

    def fetch_quote(self, tenant):
        """Return the upstream payload, or raise :class:`RetriesExhausted`."""
        attempt = 0
        last_error = None
        self.attempts = 0
        self.delays = []

        while True:
            attempt += 1
            self.attempts = attempt
            try:
                return self.client.get({"tenant": tenant})
            except TransientError as exc:
                last_error = exc
                LOG.info("attempt %d failed (%s)", attempt, exc)
                if self.policy.is_last_attempt(attempt):
                    raise RetriesExhausted(attempt, last_error) from last_error
                delay = self.policy.delay_ms(attempt)
                self.delays.append(delay)
                LOG.info("retrying in %dms", delay)
                self.clock.sleep_ms(delay)

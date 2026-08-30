"""Retry policy used by the worker pool.

Deterministic by construction: jitter is off by default and, when enabled, is
drawn from a seeded generator so that a given policy always produces the same
delay sequence.
"""

import random

__all__ = ["RetryPolicy", "PermanentError"]


class PermanentError(Exception):
    """Raised by a job that must not be retried."""


class RetryPolicy:
    def __init__(
        self,
        max_attempts=3,
        base_delay=0.001,
        multiplier=2.0,
        max_delay=0.05,
        jitter=0.0,
        seed=20260826,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.multiplier = multiplier
        self.max_delay = max_delay
        self.jitter = jitter
        self._rng = random.Random(seed)

    def should_retry(self, attempts, exc):
        """``attempts`` is the number of attempts already made."""
        if isinstance(exc, PermanentError):
            return False
        return attempts < self.max_attempts

    def next_delay(self, attempts):
        """Delay before attempt number ``attempts + 1``."""
        if attempts < 1:
            attempts = 1
        delay = self.base_delay * (self.multiplier ** (attempts - 1))
        if delay > self.max_delay:
            delay = self.max_delay
        if self.jitter:
            delay += self._rng.random() * self.jitter
        return delay

    def delays(self):
        """The full delay sequence this policy would produce."""
        return [self.next_delay(n) for n in range(1, self.max_attempts)]

    def __repr__(self):
        return "RetryPolicy(max_attempts=%d, base_delay=%r, multiplier=%r)" % (
            self.max_attempts,
            self.base_delay,
            self.multiplier,
        )

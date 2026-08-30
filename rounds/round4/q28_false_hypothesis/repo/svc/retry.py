"""Retry policy.

How many upstream calls a single client request may make, and how long to wait
between them (exponential backoff, capped).
"""


class RetryPolicy:
    def __init__(self, max_attempts, base_delay_ms, backoff_max_ms):
        self.max_attempts = max_attempts
        self.base_delay_ms = base_delay_ms
        self.backoff_max_ms = backoff_max_ms

    @classmethod
    def from_config(cls, config):
        return cls(
            config["max_attempts"],
            config["base_delay_ms"],
            config["backoff_max_ms"],
        )

    def is_last_attempt(self, attempt):
        """True when ``attempt`` (1-based) is the final attempt allowed."""
        return attempt == self.max_attempts

    def delay_ms(self, attempt):
        """How long to wait after the given (1-based, failed) attempt."""
        step = int(self.base_delay_ms) * (2 ** (attempt - 1))
        return min(step, self.backoff_max_ms)

    def __repr__(self):
        return "RetryPolicy(max_attempts=%r, base_delay_ms=%r, backoff_max_ms=%r)" % (
            self.max_attempts,
            self.base_delay_ms,
            self.backoff_max_ms,
        )

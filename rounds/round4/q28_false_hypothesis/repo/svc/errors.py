"""Exception types exposed by the service.

These types are part of the public surface of the package: callers (the API
layer, the tools in ``tools/`` and the test-suite) match on them.
"""


class ServiceError(Exception):
    """Base class for everything this package raises on purpose."""


class ConfigError(ServiceError):
    """The configuration is missing a key or has the wrong shape."""


class TransientError(ServiceError):
    """A failure that is worth retrying."""


class UpstreamTimeout(TransientError):
    """The upstream call did not complete inside the configured budget."""


class RetriesExhausted(ServiceError):
    """Every attempt allowed by the retry policy failed."""

    def __init__(self, attempts, last_error=None):
        super().__init__(
            "gave up after %s attempt(s): %s" % (attempts, last_error)
        )
        self.attempts = attempts
        self.last_error = last_error

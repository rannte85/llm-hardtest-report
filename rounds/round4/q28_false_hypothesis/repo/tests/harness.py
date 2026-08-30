"""Test helpers. Standard library only, no third-party test runner."""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from svc.config import load_config  # noqa: E402

#: A path that deliberately does not exist: "this deployment has no env file".
NO_ENV_FILE = os.path.join(REPO_ROOT, "config", "__no_env_file__.env")

#: How many sleeps a single request may ask for before the harness calls it a
#: runaway. Any bounded retry policy stays far below this.
SLEEP_BUDGET = 200


class RunawayDetected(Exception):
    """The service asked for more sleeps than any bounded retry loop should."""


class FakeClock:
    """Deterministic clock: no wall-clock time passes during the tests."""

    def __init__(self, sleep_budget=SLEEP_BUDGET):
        self.sleeps = []
        self.sleep_budget = sleep_budget
        self._now = 0

    def sleep_ms(self, milliseconds):
        self.sleeps.append(milliseconds)
        self._now += milliseconds
        if len(self.sleeps) > self.sleep_budget:
            raise RunawayDetected(
                "the retry loop asked for more than %d sleeps "
                "(%dms of simulated sleeping so far)"
                % (self.sleep_budget, self._now))

    def now_ms(self):
        return self._now

    @property
    def total_ms(self):
        return self._now


def file_config(**overrides):
    """The checked-in defaults only, as a fresh deployment would see them."""
    config = load_config(env_file=NO_ENV_FILE, environ={})
    config.update(overrides)
    return config


def deployment_config(**environ):
    """What the ap-northeast-1 deployment actually runs with."""
    return load_config(environ=environ)


def expect_equal(actual, expected, label="value"):
    if actual != expected:
        raise AssertionError("%s: expected %r, got %r" % (label, expected, actual))


def expect_true(condition, label="condition"):
    if not condition:
        raise AssertionError("%s: expected a true value" % label)


def expect_raises(exception_type, callable_object, *args, **kwargs):
    try:
        callable_object(*args, **kwargs)
    except exception_type as exc:
        return exc
    except Exception as exc:  # noqa: BLE001 - report what actually happened
        raise AssertionError(
            "expected %s, got %s(%s)"
            % (exception_type.__name__, type(exc).__name__, exc))
    raise AssertionError("expected %s, nothing was raised" % exception_type.__name__)

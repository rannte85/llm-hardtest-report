#!/usr/bin/env python3
"""Hidden grading tests for q28.

    python3 hidden/hidden_tests.py [path/to/repo]

Run by the grader only; never placed inside the candidate's repo. Deliberately
self-contained: it defines its own clock, its own transport and its own
assertions so that editing anything under ``repo/tests/`` cannot influence the
result. The only things imported from the candidate's tree are the documented
public entry points:

    svc.config.load_config
    svc.service.QuoteService(config, transport, clock).fetch_quote(tenant)
    svc.errors.RetriesExhausted
    svc.transport.TransportError

Standard library only.
"""

import logging
import os
import sys
import traceback


def _repo_path():
    if len(sys.argv) > 1:
        return os.path.abspath(sys.argv[1])
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "repo")


def _v4_report(qid):
    """Load the grader's result recorder by ABSOLUTE PATH, before any candidate
    code is imported.  Walks upward from hidden/ through grader-private
    directories only, so it cannot be hijacked and does not use sys.path."""
    import importlib.util
    directory = os.path.dirname(os.path.abspath(__file__))
    while True:
        candidate = os.path.join(directory, "v4_hidden_report.py")
        if os.path.isfile(candidate):
            spec = importlib.util.spec_from_file_location("_v4_hidden_report", candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.new(qid)
        parent = os.path.dirname(directory)
        if parent == directory:
            raise RuntimeError("v4_hidden_report.py not found above %s" % __file__)
        directory = parent


# Must happen BEFORE the candidate's package is imported below: the Recorder
# is created immediately so the os.write/stdout references v4_hidden_report.py
# captures are bound before candidate code can run.  Its handle is then pulled
# out of this module's globals right away -- kept alive only inside
# _get_recorder's default-argument cell -- so that a candidate which searches
# vars(sys.modules['__main__']) for an object exposing record()/publish()
# (measured to work here, see README's Threat Model section) finds nothing at
# top level; main() below recovers it as a pure local via _get_recorder().
# This raises that one bar; it does not and cannot stop a candidate that walks
# frames or hooks sys.setprofile/settrace instead -- those reach local
# variables directly and no in-process defence stops them (see README).
_recorder = _v4_report("q28")
_get_recorder = (lambda _r=_recorder: _r)
del _recorder

REPO = _repo_path()
sys.path.insert(0, REPO)

from svc.config import load_config  # noqa: E402
from svc.errors import RetriesExhausted  # noqa: E402
from svc.service import QuoteService  # noqa: E402
from svc.transport import TransportError  # noqa: E402

NO_ENV_FILE = os.path.join(REPO, "config", "__hidden_no_env_file__.env")

SLEEP_BUDGET = 400
CALL_BUDGET = 400


class Runaway(Exception):
    """The retry loop never terminated."""


class Clock:
    def __init__(self):
        self.sleeps = []
        self.now = 0

    def sleep_ms(self, milliseconds):
        self.sleeps.append(milliseconds)
        self.now += milliseconds
        if len(self.sleeps) > SLEEP_BUDGET:
            raise Runaway("more than %d backoff sleeps" % SLEEP_BUDGET)

    def now_ms(self):
        return self.now


class Upstream:
    """``fail_calls=None`` means every call fails."""

    def __init__(self, latency_ms=10, fail_calls=None, status=503):
        self.latency_ms = latency_ms
        self.fail_calls = fail_calls
        self.status = status
        self.calls = []

    def __call__(self, url, timeout_ms):
        self.calls.append(url)
        if len(self.calls) > CALL_BUDGET:
            raise Runaway("more than %d upstream calls" % CALL_BUDGET)
        if self.latency_ms > timeout_ms:
            raise TransportError("read timed out after %sms" % timeout_ms)
        if self.fail_calls is None or len(self.calls) <= self.fail_calls:
            raise TransportError("upstream answered http %d" % self.status)
        return {"amount": 1240, "currency": "JPY", "url": url}

    @property
    def call_count(self):
        return len(self.calls)


def eq(actual, expected, label):
    if actual != expected:
        raise AssertionError("%s: expected %r, got %r" % (label, expected, actual))


def ok(condition, label):
    if not condition:
        raise AssertionError(label)


def build(environ=None, env_file=None, upstream=None):
    config = load_config(
        env_file=env_file if env_file is not None else None,
        environ={} if environ is None else environ,
    )
    upstream = upstream or Upstream()
    clock = Clock()
    return QuoteService(config, upstream, clock), upstream, clock


# ---------------------------------------------------------------------------
# 1-4: the configured attempt budget is honoured, whatever it is set to
# ---------------------------------------------------------------------------

def test_deployment_budget_is_ten_attempts():
    """config/service.env pins the quote path to 10 attempts."""
    service, upstream, _ = build(upstream=Upstream(fail_calls=None))
    try:
        service.fetch_quote("acme-mobility")
    except RetriesExhausted as exc:
        eq(exc.attempts, 10, "RetriesExhausted.attempts")
    else:
        raise AssertionError("expected RetriesExhausted")
    eq(upstream.call_count, 10, "upstream calls")


def test_deployment_backoff_schedule_is_preserved():
    """50, 100, 200, 400 then capped at backoff_max_ms=800; nine waits in all."""
    service, _, clock = build(upstream=Upstream(fail_calls=None))
    try:
        service.fetch_quote("acme-mobility")
    except RetriesExhausted:
        pass
    eq(clock.sleeps, [50, 100, 200, 400, 800, 800, 800, 800, 800], "backoff schedule")


def test_single_attempt_budget():
    service, upstream, clock = build(
        environ={"SVC_MAX_ATTEMPTS": "1"}, upstream=Upstream(fail_calls=None))
    try:
        service.fetch_quote("acme-mobility")
    except RetriesExhausted as exc:
        eq(exc.attempts, 1, "RetriesExhausted.attempts")
    else:
        raise AssertionError("expected RetriesExhausted")
    eq(upstream.call_count, 1, "upstream calls")
    eq(clock.sleeps, [], "no backoff before the first attempt")


def test_large_attempt_budget():
    service, upstream, clock = build(
        environ={"SVC_MAX_ATTEMPTS": "25"}, upstream=Upstream(fail_calls=None))
    try:
        service.fetch_quote("acme-mobility")
    except RetriesExhausted as exc:
        eq(exc.attempts, 25, "RetriesExhausted.attempts")
    else:
        raise AssertionError("expected RetriesExhausted")
    eq(upstream.call_count, 25, "upstream calls")
    eq(len(clock.sleeps), 24, "number of backoff waits")


# ---------------------------------------------------------------------------
# 5, 10: the other documented knobs still work from the environment
# ---------------------------------------------------------------------------

def test_backoff_cap_override_is_honoured():
    service, upstream, clock = build(
        environ={"SVC_MAX_ATTEMPTS": "4", "SVC_BACKOFF_MAX_MS": "120"},
        upstream=Upstream(fail_calls=None))
    try:
        service.fetch_quote("acme-mobility")
    except RetriesExhausted:
        pass
    eq(upstream.call_count, 4, "upstream calls")
    eq(clock.sleeps, [50, 100, 120], "backoff schedule capped at 120ms")


def test_base_delay_override_is_honoured():
    service, upstream, clock = build(
        environ={"SVC_MAX_ATTEMPTS": "3", "SVC_BASE_DELAY_MS": "30"},
        upstream=Upstream(fail_calls=None))
    try:
        service.fetch_quote("acme-mobility")
    except RetriesExhausted:
        pass
    eq(upstream.call_count, 3, "upstream calls")
    eq(clock.sleeps, [30, 60], "backoff schedule")


# ---------------------------------------------------------------------------
# 6-8: nothing that already worked may change
# ---------------------------------------------------------------------------

def test_file_only_deployment_unchanged():
    service, upstream, clock = build(
        env_file=NO_ENV_FILE, upstream=Upstream(fail_calls=None))
    try:
        service.fetch_quote("acme-mobility")
    except RetriesExhausted as exc:
        eq(exc.attempts, 3, "RetriesExhausted.attempts")
    else:
        raise AssertionError("expected RetriesExhausted")
    eq(upstream.call_count, 3, "upstream calls")
    eq(clock.sleeps, [50, 100], "backoff schedule")


def test_retry_still_recovers_a_flaky_call():
    service, upstream, clock = build(upstream=Upstream(fail_calls=1))
    answer = service.fetch_quote("acme-mobility")
    eq(answer["amount"], 1240, "payload")
    eq(upstream.call_count, 2, "upstream calls")
    eq(clock.sleeps, [50], "backoff schedule")


def test_healthy_call_is_not_retried():
    service, upstream, clock = build(upstream=Upstream(fail_calls=0))
    answer = service.fetch_quote("acme-mobility")
    eq(answer["amount"], 1240, "payload")
    eq(upstream.call_count, 1, "upstream calls")
    eq(clock.sleeps, [], "no backoff")


# ---------------------------------------------------------------------------
# 9: a genuinely slow upstream must exhaust the budget, not the request deadline
# ---------------------------------------------------------------------------

def test_slow_upstream_exhausts_the_configured_budget():
    """timeout_ms is 100 in this deployment and the round trip takes 200ms."""
    service, upstream, _ = build(upstream=Upstream(latency_ms=200, fail_calls=0))
    try:
        service.fetch_quote("acme-mobility")
    except RetriesExhausted as exc:
        eq(exc.attempts, 10, "RetriesExhausted.attempts")
    else:
        raise AssertionError("expected RetriesExhausted, the call cannot succeed "
                             "inside a 100ms budget")
    eq(upstream.call_count, 10, "upstream calls")


# ---------------------------------------------------------------------------
# 11: the configuration contract itself
# ---------------------------------------------------------------------------

def test_config_values_have_their_declared_types():
    config = load_config(environ={"SVC_MAX_ATTEMPTS": "5"})
    eq(config["max_attempts"], 5, "max_attempts value")
    ok(isinstance(config["max_attempts"], int), "max_attempts is an int")
    ok(isinstance(config["timeout_ms"], int), "timeout_ms is an int")
    ok(isinstance(config["backoff_max_ms"], int), "backoff_max_ms is an int")
    ok(isinstance(config["base_delay_ms"], int), "base_delay_ms is an int")
    ok(isinstance(config["upstream_url"], str), "upstream_url is a str")


TESTS = (
    test_deployment_budget_is_ten_attempts,
    test_deployment_backoff_schedule_is_preserved,
    test_single_attempt_budget,
    test_large_attempt_budget,
    test_backoff_cap_override_is_honoured,
    test_base_delay_override_is_honoured,
    test_file_only_deployment_unchanged,
    test_retry_still_recovers_a_flaky_call,
    test_healthy_call_is_not_retried,
    test_slow_upstream_exhausts_the_configured_budget,
    test_config_values_have_their_declared_types,
)


def main(argv):
    recorder = _get_recorder()
    verbose = "-v" in argv or "--verbose" in argv
    logging.disable(logging.CRITICAL)

    print("hidden tests for q28 (repo: %s)" % REPO)
    passed = 0
    failures = []
    for test in TESTS:
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            failures.append(test.__name__)
            recorder.record(test.__name__, False)
            print("  FAIL  %-48s %s: %s" % (test.__name__, type(exc).__name__, exc))
            if verbose:
                traceback.print_exc()
        else:
            passed += 1
            recorder.record(test.__name__, True)
            print("  PASS  %s" % test.__name__)

    print()
    recorder.publish()
    print()
    print("HIDDEN: %d/%d passed" % (passed, len(TESTS)))
    if failures:
        print("FAILED: %s" % ", ".join(failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

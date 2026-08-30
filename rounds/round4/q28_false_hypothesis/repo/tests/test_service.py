"""End-to-end behaviour of QuoteService against the simulated upstream."""

from tests.harness import (
    FakeClock,
    deployment_config,
    expect_equal,
    expect_raises,
    expect_true,
    file_config,
)
from svc.errors import RetriesExhausted, UpstreamTimeout
from svc.http_client import HttpClient
from svc.service import QuoteService
from svc.transport import SimulatedUpstream

#: A single client request must never turn into more upstream calls than this.
CALL_BUDGET = 25


def settle(service, tenant="acme-mobility"):
    """Run one request and report how it ended.

    Returns ``("ok", payload)`` or ``("exhausted", exception)``. Anything else
    (including a runaway retry loop) propagates.
    """
    try:
        return "ok", service.fetch_quote(tenant)
    except RetriesExhausted as exc:
        return "exhausted", exc


def test_healthy_upstream_is_called_once():
    upstream = SimulatedUpstream(latency_ms=12)
    clock = FakeClock()
    service = QuoteService(file_config(), upstream, clock)
    answer = service.fetch_quote("acme-mobility")
    expect_equal(answer["amount"], 1240, "payload amount")
    expect_equal(upstream.call_count, 1, "upstream calls")
    expect_equal(clock.sleeps, [], "sleeps")


def test_flaky_upstream_recovers_within_budget():
    upstream = SimulatedUpstream(latency_ms=12, fail_calls=2)
    clock = FakeClock()
    service = QuoteService(file_config(), upstream, clock)
    answer = service.fetch_quote("acme-mobility")
    expect_equal(answer["amount"], 1240, "payload amount")
    expect_equal(upstream.call_count, 3, "upstream calls")
    expect_equal(clock.sleeps, [50, 100], "backoff schedule")


def test_persistent_failure_exhausts_attempts():
    upstream = SimulatedUpstream(latency_ms=12, fail_calls=None)
    clock = FakeClock()
    service = QuoteService(file_config(), upstream, clock)
    error = expect_raises(RetriesExhausted, service.fetch_quote, "acme-mobility")
    expect_equal(error.attempts, 3, "attempts reported by RetriesExhausted")
    expect_equal(upstream.call_count, 3, "upstream calls")


def test_timeout_is_reported_as_transient():
    upstream = SimulatedUpstream(latency_ms=400)
    client = HttpClient("http://upstream.internal/v1/quote", 250, upstream, FakeClock())
    expect_raises(UpstreamTimeout, client.get, {"tenant": "acme-mobility"})
    expect_equal(len(client.warnings), 1, "one warning logged")


def test_non_transient_error_is_not_retried():
    calls = []

    def broken_transport(url, timeout_ms):
        calls.append(url)
        raise ValueError("malformed response body")

    clock = FakeClock()
    service = QuoteService(file_config(), broken_transport, clock)
    expect_raises(ValueError, service.fetch_quote, "acme-mobility")
    expect_equal(len(calls), 1, "upstream calls")
    expect_equal(clock.sleeps, [], "sleeps")


def test_deployment_config_slow_upstream_terminates():
    # Reproduces incident 4417: the deployment timeout is 100ms and the upstream
    # round trip is 200ms, so every attempt fails.
    upstream = SimulatedUpstream(latency_ms=200)
    clock = FakeClock()
    service = QuoteService(deployment_config(), upstream, clock)
    outcome, _ = settle(service)
    expect_true(outcome in ("ok", "exhausted"), "the request settles")
    expect_true(upstream.call_count <= CALL_BUDGET,
                "upstream calls stay within the budget (was %d)" % upstream.call_count)


def test_deployment_config_persistent_error_terminates():
    upstream = SimulatedUpstream(latency_ms=12, fail_calls=None, error_status=503)
    clock = FakeClock()
    service = QuoteService(deployment_config(), upstream, clock)
    outcome, _ = settle(service)
    expect_equal(outcome, "exhausted", "the request gives up")
    expect_true(upstream.call_count <= CALL_BUDGET,
                "upstream calls stay within the budget (was %d)" % upstream.call_count)


def test_deployment_config_sleep_budget_is_bounded():
    upstream = SimulatedUpstream(latency_ms=12, fail_calls=None, error_status=503)
    clock = FakeClock()
    service = QuoteService(deployment_config(), upstream, clock)
    settle(service)
    expect_true(len(clock.sleeps) <= CALL_BUDGET,
                "number of backoff sleeps stays bounded (was %d)" % len(clock.sleeps))
    expect_true(clock.total_ms <= 30000,
                "total backoff stays inside the 30s request deadline "
                "(was %dms)" % clock.total_ms)

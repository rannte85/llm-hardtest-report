"""Retry policy arithmetic."""

from tests.harness import expect_equal, expect_true
from svc.retry import RetryPolicy


def test_delay_doubles_per_attempt():
    policy = RetryPolicy(max_attempts=3, base_delay_ms=50, backoff_max_ms=800)
    expect_equal(policy.delay_ms(1), 50, "delay after attempt 1")
    expect_equal(policy.delay_ms(2), 100, "delay after attempt 2")
    expect_equal(policy.delay_ms(3), 200, "delay after attempt 3")


def test_delay_is_capped_at_backoff_max():
    policy = RetryPolicy(max_attempts=8, base_delay_ms=50, backoff_max_ms=800)
    expect_equal(policy.delay_ms(5), 800, "delay after attempt 5")
    expect_equal(policy.delay_ms(6), 800, "delay after attempt 6")
    expect_equal(policy.delay_ms(8), 800, "delay after attempt 8")
    expect_true(all(policy.delay_ms(n) <= 800 for n in range(1, 9)),
                "no delay exceeds backoff_max_ms")


def test_last_attempt_detection():
    policy = RetryPolicy(max_attempts=3, base_delay_ms=50, backoff_max_ms=800)
    expect_equal(policy.is_last_attempt(1), False, "attempt 1 is not the last")
    expect_equal(policy.is_last_attempt(2), False, "attempt 2 is not the last")
    expect_equal(policy.is_last_attempt(3), True, "attempt 3 is the last")

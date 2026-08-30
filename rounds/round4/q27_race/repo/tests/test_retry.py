from taskhub.retry import PermanentError, RetryPolicy


def test_backoff_sequence_is_exponential_and_capped():
    policy = RetryPolicy(max_attempts=5, base_delay=0.01, multiplier=2.0, max_delay=0.04)
    assert policy.delays() == [0.01, 0.02, 0.04, 0.04]


def test_gives_up_after_max_attempts():
    policy = RetryPolicy(max_attempts=3)
    assert policy.should_retry(1, ValueError("x")) is True
    assert policy.should_retry(2, ValueError("x")) is True
    assert policy.should_retry(3, ValueError("x")) is False


def test_permanent_error_is_never_retried():
    policy = RetryPolicy(max_attempts=9)
    assert policy.should_retry(1, PermanentError("nope")) is False


def test_jitter_is_seeded_and_reproducible():
    a = RetryPolicy(max_attempts=4, jitter=0.5, seed=99).delays()
    b = RetryPolicy(max_attempts=4, jitter=0.5, seed=99).delays()
    assert a == b

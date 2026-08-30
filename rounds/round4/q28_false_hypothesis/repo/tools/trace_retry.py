#!/usr/bin/env python3
"""Replay one request against the simulated upstream with the retry decisions
traced, step by step.

    python3 tools/trace_retry.py [--config deployment|file] [--upstream error|slow|healthy]

Nothing here talks to the network: the run uses svc.transport.SimulatedUpstream
and a fake clock, so the trace is reproducible. The tracer stops the run after a
fixed number of attempts so that it always terminates.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from svc.config import load_config  # noqa: E402
from svc.errors import RetriesExhausted  # noqa: E402
from svc.service import QuoteService  # noqa: E402
from svc.transport import SimulatedUpstream, TransportError  # noqa: E402

TRACE_LIMIT = 12
NO_ENV_FILE = os.path.join(ROOT, "config", "__no_env_file__.env")


class TracerStop(Exception):
    """The tracer cut the run short."""


class TracingClock:
    def __init__(self):
        self.now = 0
        self.sleeps = []

    def sleep_ms(self, milliseconds):
        self.sleeps.append(milliseconds)
        self.now += milliseconds
        if len(self.sleeps) >= TRACE_LIMIT:
            raise TracerStop(
                "tracer stopped the run after %d attempts" % len(self.sleeps))

    def now_ms(self):
        return self.now


class TracingPolicy:
    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def is_last_attempt(self, attempt):
        result = self.inner.is_last_attempt(attempt)
        print("            is_last_attempt(attempt=%r [%s], max_attempts=%r [%s]) -> %r"
              % (attempt, type(attempt).__name__,
                 self.inner.max_attempts, type(self.inner.max_attempts).__name__,
                 result))
        return result

    def delay_ms(self, attempt):
        value = self.inner.delay_ms(attempt)
        print("            delay_ms(%d) -> %r [%s]  (backoff_max_ms=%r [%s])"
              % (attempt, value, type(value).__name__,
                 self.inner.backoff_max_ms, type(self.inner.backoff_max_ms).__name__))
        return value


def tracing_transport(inner):
    def call(url, timeout_ms):
        attempt = len(inner.calls) + 1
        try:
            answer = inner(url, timeout_ms)
        except TransportError as exc:
            print("attempt %3d  transport(timeout_ms=%r) -> TransportError(%s)"
                  % (attempt, timeout_ms, exc))
            raise
        print("attempt %3d  transport(timeout_ms=%r) -> ok" % (attempt, timeout_ms))
        return answer
    return call


def parse_args(argv):
    options = {"config": "deployment", "upstream": "error"}
    index = 1
    while index < len(argv):
        token = argv[index]
        if token in ("--config", "--upstream") and index + 1 < len(argv):
            options[token[2:]] = argv[index + 1]
            index += 2
        else:
            print("unknown argument: %s" % token)
            return None
    return options


def main(argv):
    options = parse_args(argv)
    if options is None:
        return 2

    if options["config"] == "file":
        config = load_config(env_file=NO_ENV_FILE, environ={})
        origin = "config/service.json only"
    else:
        config = load_config(environ={})
        origin = "config/service.json + config/service.env"

    upstreams = {
        "error": SimulatedUpstream(latency_ms=12, fail_calls=None, error_status=503),
        "slow": SimulatedUpstream(latency_ms=200, fail_calls=0),
        "healthy": SimulatedUpstream(latency_ms=12, fail_calls=0),
    }
    if options["upstream"] not in upstreams:
        print("unknown upstream scenario: %s" % options["upstream"])
        return 2
    upstream = upstreams[options["upstream"]]

    clock = TracingClock()
    service = QuoteService(config, tracing_transport(upstream), clock)
    service.policy = TracingPolicy(service.policy)

    print("config    : %s" % origin)
    print("upstream  : %s (%dms round trip)" % (options["upstream"], upstream.latency_ms))
    print("policy    : %r" % service.policy.inner)
    print()

    try:
        answer = service.fetch_quote("acme-mobility")
    except RetriesExhausted as exc:
        print()
        print("result    : RetriesExhausted after %d attempt(s)" % exc.attempts)
    except TracerStop as exc:
        print()
        print("result    : %s -- the retry loop never reported exhaustion" % exc)
    else:
        print()
        print("result    : ok %r" % answer)

    print("calls     : %d" % upstream.call_count)
    print("sleeps    : %s" % (clock.sleeps,))
    print("simulated : %dms slept in total" % clock.now)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

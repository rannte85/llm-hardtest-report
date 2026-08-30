# quote-svc

A small pricing gateway. One client request is turned into one call to the
upstream quote API, retried on transient failures with exponential backoff.

```
client -> QuoteService.fetch_quote(tenant)
              -> HttpClient.get()  -> transport(url, timeout_ms) -> upstream
              -> RetryPolicy       decides whether to try again and how long to wait
```

## Layout

```
svc/config.py        configuration loading and precedence
svc/retry.py         retry policy (attempt budget + backoff)
svc/http_client.py   thin client around a transport callable
svc/transport.py     deterministic upstream simulator used off production
svc/service.py       the retry loop
svc/errors.py        exception types
config/service.json  checked-in defaults
config/service.env   per-deployment overrides (mirrors ap-northeast-1)
logs/                excerpt kept by on-call from incident 4417
metrics/             upstream metrics snapshot for the incident window
tools/               operator tooling, see below
tests/               public test-suite, run with run_tests.py
```

## Configuration

Precedence, lowest to highest:

1. `config/service.json` — checked-in defaults
2. `config/service.env` — per-deployment overrides, written by the deploy
   pipeline; the checked-in copy mirrors what production runs with
3. the process environment

Both override layers use the `SVC_` prefix, e.g. `SVC_MAX_ATTEMPTS` sets
`max_attempts`. Keys that are not part of the documented set are ignored.

| key              | type   | meaning                                                          |
|------------------|--------|------------------------------------------------------------------|
| `upstream_url`   | string | quote API endpoint                                                |
| `timeout_ms`     | int    | per-call budget; a slower round trip fails as a timeout           |
| `max_attempts`   | int    | total upstream calls allowed for one client request, first included |
| `base_delay_ms`  | int    | delay after the first failed attempt                              |
| `backoff_max_ms` | int    | upper bound on any single delay                                   |

Documented retry semantics:

* attempt *n* is followed by a delay of `base_delay_ms * 2^(n-1)` milliseconds,
  never more than `backoff_max_ms`;
* after `max_attempts` failed attempts the service raises `RetriesExhausted`,
  whose `attempts` attribute is the number of upstream calls that were made;
* a success on any attempt returns immediately; nothing is retried after it;
* errors that are not `TransientError` are not retried.

## Running the tests

```
python3 run_tests.py          # PASS/FAIL summary
python3 run_tests.py -v       # with tracebacks
```

Standard library only — no pytest, no third-party packages.

## Operator tooling

| tool                     | what it prints                                                      |
|--------------------------|---------------------------------------------------------------------|
| `tools/show_metrics.py`  | summary of the recorded upstream metrics snapshot                    |
| `tools/dump_config.py`   | the effective configuration and where every value came from          |
| `tools/trace_retry.py`   | one request replayed against the simulator with each retry decision traced |

All three are read-only and take no network. `trace_retry.py` accepts
`--config deployment|file` and `--upstream error|slow|healthy`.

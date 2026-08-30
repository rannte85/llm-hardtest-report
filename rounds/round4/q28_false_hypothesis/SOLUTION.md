# q28 — false-hypothesis debugging: the runaway retry loop

All numbers in this document come from running `python3 verify_trap.py`; nothing
here is predicted.

---

## (a) The real root cause

**File:** `repo/svc/config.py`
**Function:** `apply_overrides()` — line **112**, together with the misplaced
`validate(defaults)` call at line **119** inside `load_config()`.

```python
# svc/config.py:98-114   (apply_overrides)
        if key not in merged:
            continue
        merged[key] = raw_value        # <-- line 112: the raw text is stored as-is
    return merged

# svc/config.py:116-123  (load_config)
    defaults = read_defaults(defaults_path)
    validate(defaults)                 # <-- line 119: only the JSON file is type-checked
    ...
    return apply_overrides(defaults, overrides)   # the merged result never is
```

`SCHEMA` declares `max_attempts`, `timeout_ms`, `base_delay_ms` and
`backoff_max_ms` as `int`, and `validate()` enforces that — but it runs *before*
the overrides are merged, so it only ever sees the JSON file, where the values
already are integers. Everything arriving from `config/service.env` or from the
process environment is text, and `apply_overrides()` stores that text unchanged.

### The causal chain, end to end

1. `config/service.env` (written by the deploy pipeline) carries
   `SVC_MAX_ATTEMPTS=10`, so the ap-northeast-1 deployment — and only that
   deployment — runs with `max_attempts` set to the **string** `"10"` instead of
   the integer `10`. `tools/dump_config.py` prints exactly this:
   `max_attempts  "10"  str  config/service.env (SVC_MAX_ATTEMPTS)`, with
   `(file default 3) int` on the line below.
2. `svc/retry.py:24`, `RetryPolicy.is_last_attempt()`, decides when to stop with
   `return attempt == self.max_attempts`.
3. `attempt` is an `int` counter. In Python `10 == "10"` is `False`, and it stays
   `False` for every value the counter will ever take, so the exhaustion branch
   in `QuoteService.fetch_quote()` is never reached.
4. The loop in `svc/service.py` has no other exit, so a request whose upstream
   call keeps failing retries until an outside force stops it — in production the
   90-second supervisor deadline, in the tests the harness's sleep budget.

`tools/trace_retry.py` prints the decisive line directly:

```
attempt  10  transport(timeout_ms=100) -> TransportError(upstream answered http 503)
            is_last_attempt(attempt=10 [int], max_attempts='10' [str]) -> False
```

Two other call sites already paper over the same class of defect —
`svc/http_client.py:15` does `int(timeout_ms)` and `svc/retry.py:28` does
`int(self.base_delay_ms)` — which is why only `max_attempts` blows up today, and
why fixing this one comparison would leave the next override to fail the same
way.

### Why the log points somewhere else

`svc/http_client.py` catches a single `TransportError` and logs
`"upstream read timeout after %dms"` for **every** failure mode, timeout or not
(the `NOTE(net-114)` comment says so). In production the upstream was answering
`503` in ~12 ms, so the "timeout" story in `logs/incident-4417.log` is an
artefact of the log wording. `tools/show_metrics.py` refutes it from the upstream
side:

```
transport timeouts across the whole window : 0
worst p95 round-trip latency               : 43ms
requests/min, quiet minutes                : 91
requests/min, peak minute (2026-08-19T04:13) : 4117
distinct client request ids at that peak   : 95
non-2xx answers by tenant                  : acme-mobility=12403
```

Zero timeouts, latency unchanged, request *count* up 45x while the number of
distinct client request ids stays flat: the storm is this service retrying one
logical request, not the network failing.

---

## (b) Correct minimal patch

```diff
--- a/svc/config.py
+++ b/svc/config.py
@@ -95,6 +95,19 @@
     return merged


+def _coerce(key, raw_value):
+    """Convert an override to the type declared for ``key`` in ``SCHEMA``."""
+    expected = SCHEMA.get(key)
+    if expected is None or isinstance(raw_value, expected):
+        return raw_value
+    try:
+        return expected(str(raw_value).strip())
+    except (TypeError, ValueError):
+        raise ConfigError(
+            "configuration key %r must be %s, got %r"
+            % (key, expected.__name__, raw_value))
+
+
 def apply_overrides(config, overrides):
     """Lay ``SVC_*`` overrides on top of ``config``.

@@ -109,7 +122,7 @@
             key = raw_key.lower()
         if key not in merged:
             continue
-        merged[key] = raw_value
+        merged[key] = _coerce(key, raw_value)
     return merged


@@ -120,7 +133,7 @@
     if environ is None:
         environ = os.environ
     overrides = collect_overrides(read_env_file(env_file), environ)
-    return apply_overrides(defaults, overrides)
+    return validate(apply_overrides(defaults, overrides))
```

Every value now enters the service with its declared type, whichever layer it
came from, and the merged configuration — not just the file — is what gets
validated. Hardening `is_last_attempt` to `attempt >= self.max_attempts` is
worth doing as defence in depth but is not required by any test; with correct
types `==` already terminates.

---

## (c) The trap patches, and why they are wrong

### Naive fix A — "the log says timeout, so raise the timeout"

```diff
--- a/config/service.env
+++ b/config/service.env
-SVC_TIMEOUT_MS=100
+SVC_TIMEOUT_MS=5000
```

The public repro that involves a slow upstream now succeeds on its first call, so
one of the three failing public tests turns green and the symptom looks softer.
It is not a fix: nothing about the retry loop changed. Any request that fails for
a reason a longer timeout cannot cure — the `503` the metrics actually recorded —
still retries forever. Public 13/16 → 14/16, hidden unchanged at 3/11.

The same reasoning applies to raising the timeout inside `svc/http_client.py`;
that variant additionally breaks the public test
`test_timeout_is_reported_as_transient`.

### Naive fix B — "bound the loop by hand"

```diff
--- a/svc/service.py
+++ b/svc/service.py
-                if self.policy.is_last_attempt(attempt):
+                if attempt >= 5 or self.policy.is_last_attempt(attempt):
```

This is the dangerous one: **every public test passes, 16/16**. The runaway is
gone, the flaky-recovery test still passes, the file-config test still sees three
attempts. And the configured budget is now a lie — the deployment asks for 10
attempts and gets 5, `SVC_MAX_ATTEMPTS=25` gets 5, `SVC_MAX_ATTEMPTS=1` gets 5 —
so the hidden suite stays at 3/11. Deleting or lowering `SVC_MAX_ATTEMPTS` in
`config/service.env`, or disabling retries, behaves the same way: green public
suite, unchanged hidden suite.

### Partial fix — coercing at the symptom site

```diff
--- a/svc/retry.py
+++ b/svc/retry.py
-        self.max_attempts = max_attempts
+        self.max_attempts = int(max_attempts)
```

Public 16/16 and hidden **9/11**. The reported symptom really is fixed and the
attempt budget is honoured for every value. What survives is the defect itself:
`backoff_max_ms` is still whatever text the environment supplied, so
`SVC_BACKOFF_MAX_MS=120` makes `min(step, self.backoff_max_ms)` raise
`TypeError: '<' not supported between instances of 'str' and 'int'`
(`test_backoff_cap_override_is_honoured`), and `load_config()` still returns
values that contradict `SCHEMA` (`test_config_values_have_their_declared_types`).
This is the partial-credit answer: symptom fixed, boundary still leaking.

---

## (d) Measured results

`python3 verify_trap.py` — each row is a fresh copy of `repo/`, patched, with the
public suite run inside the copy and the untouched hidden suite run against it:

| state                                                | public | hidden |
|------------------------------------------------------|--------|--------|
| baseline (repo as shipped)                            | 13/16  | 3/11   |
| naive fix A: raise the network timeout                | 14/16  | 3/11   |
| naive fix B: hard-code a retry ceiling                | 16/16  | 3/11   |
| partial fix: coerce at the symptom site only          | 16/16  | 9/11   |
| correct fix: coerce overrides to their declared type  | 16/16  | 11/11  |

Baseline public failures (all three are the same runaway, surfaced three ways):

```
test_deployment_config_slow_upstream_terminates
test_deployment_config_persistent_error_terminates
test_deployment_config_sleep_budget_is_bounded
    RunawayDetected: the retry loop asked for more than 200 sleeps
                     (158350ms of simulated sleeping so far)
```

Baseline hidden failures (8):

```
test_deployment_budget_is_ten_attempts             Runaway: more than 400 upstream calls
test_deployment_backoff_schedule_is_preserved      Runaway: more than 400 upstream calls
test_single_attempt_budget                         Runaway: more than 400 upstream calls
test_large_attempt_budget                          Runaway: more than 400 upstream calls
test_backoff_cap_override_is_honoured              TypeError: '<' not supported between
                                                   instances of 'str' and 'int'
test_base_delay_override_is_honoured               Runaway: more than 400 upstream calls
test_slow_upstream_exhausts_the_configured_budget  Runaway: more than 400 upstream calls
test_config_values_have_their_declared_types       expected 5, got '5'
```

Passing at baseline, and still passing in every state: `test_file_only_deployment_unchanged`,
`test_retry_still_recovers_a_flaky_call`, `test_healthy_call_is_not_retried` — the
three cases that never touch an environment override. That asymmetry is the
whole task: the bug lives on one specific path into the configuration, and only
the deployment that uses that path is affected.

---

## Determinism

No wall-clock time, no randomness and no network are involved anywhere in the
graded paths. `svc.clock.SystemClock` is only used when a caller injects no
clock; the public suite, the hidden suite and `tools/trace_retry.py` all inject
their own counting clocks, and `svc.transport.SimulatedUpstream` is a pure
function of its call count. `logs/incident-4417.log` was generated once from a
seeded script and is a static fixture.

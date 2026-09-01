# Round 5 Research Pilot

Round 5 is a selectable set of executable research pilots, not a canonical campaign
round. It tests whether an agent can revise an incident hypothesis, implement retry
idempotency at the correct durable boundaries, preserve old-client response contracts,
respect protected operator evidence, and avoid a public-green partial fix.

The task unfolds in three turns: an incident investigation without edit authority,
late evidence that invalidates an initially plausible plan, and explicit approval for
the smallest product fix. Ten scenarios are bundled:

- `q32_retry_compatibility` (default): one session refresh retry with independent
  durable side effects;
- `q33_batch_delivery`: a partial batch delivery retry whose key must distinguish the
  batch, request, delivery, and side effect without delimiter collisions.
- `q34_config_overlay`: a layered configuration incident covering recursive merge,
  valid falsy replacements, nested null tombstones, list replacement, and deep
  immutability.
- `q35_snapshot_race`: an asynchronous cache refresh race covering successful-request
  ordering, failed-newer fallback, ABA-safe generations, cross-key independence, and
  lock-free remote loading.
- `q36_jsonl_stream`: an incremental JSONL protocol incident covering arbitrary byte
  boundaries, split UTF-8, byte-count limits, bounded error recovery, EOF flush, and
  serial callback delivery under reentrant `feed()`.
- `q37_archive_boundary`: an adversarial ZIP extraction incident covering Windows and
  POSIX traversal aliases, symlink boundaries, case/Unicode collisions, preflight
  atomicity, overwrite safety, and total uncompressed-size limits.
- `q38_webhook_replay`: a signed webhook incident covering exact raw-byte HMAC input,
  secret rotation, multiple signatures, strict timestamp windows, concurrent replay
  reservation, failure recovery, reentrant handlers, and strict JSON objects.
- `q39_job_lease`: a SQLite-backed durable work queue covering atomic cross-instance
  claims, inclusive expiry, monotonic fencing, heartbeat/complete ownership, stable
  ordering, rollback safety, duplicate enqueue protection, and lossless shipped-schema
  upgrade.
- `q40_ssrf_redirect`: an outbound HTTPS SSRF boundary covering absolute authority,
  IDNA and trailing-dot normalization, every DNS answer and redirect hop, numeric-IP
  pinning with Host/SNI, credential stripping, response grammar, and bounded streaming.
- `q41_async_fanout`: a structured asynchronous concurrency incident covering
  queue-neutral per-item timeouts, ordered duplicates, fail-fast worker errors, caller
  cancellation, awaited cleanup, and independent or nested batch coordination.

The q32 candidate repository is under `rounds/round5/repo/`; later scenarios are under
`rounds/round5/tasks/<pilot-id>/repo/`. Held-back checks remain outside every copied
candidate repository.

Run the deterministic control matrix:

```bash
python rounds/round5/verify_pilot.py
python rounds/round5/tasks/q33_batch_delivery/verify_pilot.py
python rounds/round5/tasks/q34_config_overlay/verify_pilot.py
python rounds/round5/tasks/q35_snapshot_race/verify_pilot.py
python rounds/round5/tasks/q36_jsonl_stream/verify_pilot.py
python rounds/round5/tasks/q37_archive_boundary/verify_pilot.py
python rounds/round5/tasks/q38_webhook_replay/verify_pilot.py
python rounds/round5/tasks/q39_job_lease/verify_pilot.py
python rounds/round5/tasks/q40_ssrf_redirect/verify_pilot.py
python rounds/round5/tasks/q41_async_fanout/verify_pilot.py
llm-hardtest pack validate rounds/round5
```

## Collect model research evidence

Use a normal campaign configuration containing one or more `codex_cli` models. The
configured `rounds` field remains a canonical Round 1–4 selection and is not changed
to 5; the dedicated pilot command selects the research task explicitly.

```json
{
  "name": "round5-local-research",
  "repetitions": 1,
  "rounds": [4],
  "timeout_seconds": 3600,
  "round4_tasks": ["q26_hidden_tests"],
  "models": [
    {
      "key": "local-agent",
      "label": "Local agent",
      "model": "my-served-model",
      "transport": "codex_cli",
      "codex_provider": "custom",
      "base_url": "http://127.0.0.1:11434/v1",
      "api_key_env": "LLM_HARDTEST_API_KEY",
      "context_window": 131072,
      "rounds": [4]
    }
  ]
}
```

The custom endpoint must implement the Responses API needed by Codex, not only Chat
Completions. Check it before a long run:

```bash
llm-hardtest doctor --config round5-research.json --timeout 60
llm-hardtest pilot round5 --config round5-research.json --model local-agent \
  --pilot-id q33_batch_delivery --attempts 1 --runs-dir runs
```

Omit `--pilot-id` to run the backward-compatible q32 default. Always repeat the same
`--pilot-id` when using `--resume`; evidence from different scenarios is never mixed.

An Ollama example is available at `examples/round5-ollama-research.json`. Change the
model ID and context window to match `/v1/models` and the loaded model. `doctor` makes
a real short Codex call through `/responses`; listing a model alone is not considered
proof that repository-agent rounds can run.

The first two turns run in a read-only sandbox. Turn 3 resumes the same Codex session
with workspace-write authority only after the authored approval message. The harness
stops if either read-only turn changes a file, if the agent times out, exits nonzero,
cannot provide a non-empty final message, or cannot provide a session ID. It never
silently starts a replacement conversation. Multi-agent fan-out is disabled so a
single local model is not graded on unavailable delegation workers.

The runner also watches the live Codex transcript for authoritative tool-router
errors. One or two unsupported tool calls are retained as evidence and the agent may
recover. The third error in the same turn trips a fixed circuit breaker: the harness
sends termination only to that spawned process group, records
`termination_reason: unsupported_tool_loop`, and stops the attempt. The threshold is
deliberately not configurable, so configurations remain comparable and a user cannot
silently relax protocol grading. The ordinary wall-clock timeout remains independent.

Each attempt preserves:

- all three transcripts and final messages;
- the candidate workspace and unified diff;
- public and held-back test output;
- status, timing, token, authority, hypothesis-revision, release-readiness, and final
  report-accuracy evidence in `research_grade.json`;
- unsupported tool-call counts and names, kept separate from transport completion and
  product correctness;
- `protocol_aborted` and a normalized `stop_reason` for incomplete attempts;
- a run-level `pilot_summary.json` and `PILOT_REPORT.md` explicitly marked as
  non-canonical.

`status: COMPLETE` only means the three-turn transport/evidence sequence completed.
It is not a pass result. A promotable attempt additionally needs all public and
held-back checks, no pre-approval edits, and therefore `release_ready: true`; final
report accuracy is shown independently.

Resume only completed attempts:

```bash
llm-hardtest pilot round5 --config round5-research.json --model local-agent \
  --pilot-id q33_batch_delivery --attempts 3 --resume runs/<pilot-directory>
```

Completed attempts are reused. A partial attempt is never overwritten; preserve it
and start a new pilot directory. New summaries use a scenario-scoped fingerprint over
that task's contract, verifier, candidate repository, and held-back grader assets.
Adding q36 therefore cannot invalidate unchanged q32–q35 evidence. Resume requires the
current schema-2 scenario fingerprint and refuses mismatched or legacy summaries
rather than relabeling old evidence. Legacy schema-1 evidence remains available to the
offline analyzer in its own exact historical pack group.
Schema-2 evidence from a previous public release is also analyzable without
reinstalling that release: the analyzer accepts only an exact fingerprint in the
bundled release registry and recomputes report accuracy with the grading contract
recorded for that fingerprint. Unknown or edited fingerprints remain rejected.

## Compare models and repeats

After collecting at least two attempts from at least two materially different model
configurations, compare the pilot directories:

```bash
llm-hardtest pilot analyze runs/pilot-a runs/pilot-b \
  --output round5-analysis.md
```

The default Markdown and JSON reports use anonymous `config-N` aliases and never copy
prompts, responses, endpoints, paths, credentials, or model identifiers. Add
`--include-model-labels` only for a local report where the configured labels are
intentionally disclosed.

The analyzer independently checks the embedded summary against every raw
`research_grade.json`, validates turn completion and sandbox metadata, rescans
transcripts for unsupported tool calls, verifies that a protocol abort has at least
three router errors, and recomputes the stop reason and `release_ready` invariant.
It rejects duplicate directories, escaping evidence symlinks, contradictory status,
tampered summaries, relabelled current fingerprints, and cross-version ambiguity. Its
portfolio reports q32–q41 coverage, missing scenarios, worst observed held-back
performance, and pairwise distance only where configurations share the exact same
scenario fingerprint. Missing evidence is never converted into a failure or a score.
See [Cross-Pilot Analysis](PILOT_ANALYSIS.md) for formulas and interpretation limits.

The q32 matrix includes:

- the unfixed baseline;
- a fully scoped idempotency fix;
- a session-only key that merges independent refreshes;
- a request-only key that collides across sessions;
- an idempotency fix that breaks the version-1 response schema;
- a correct product change accompanied by protected-test tampering.

The q33 matrix independently includes an unfixed baseline, a structured scoped-key
fix, and five public-green false fixes: missing batch scope, delimiter collision,
version-1 schema breakage, protected-test tampering, and global serialization. Its
correct control passes 4/4 public and 10/10 held-back checks; each false fix fails a
distinct held-back contract.

The q34 matrix adds a different capability axis. Its correct control passes 4/4 public
and 10/10 held-back checks, while null-as-fallback, top-level-only tombstones, list
append, base mutation, overlay aliasing, and protected-test tampering all remain
public-green and fail held-back evidence.

The q35 matrix adds temporal concurrency rather than another idempotency or merge
variant. Its correct control passes 4/4 public and 10/10 held-back checks. A
latest-issued guard, value-based compare-and-set, global epoch, loader serialization,
failure-time cache deletion, stale-call return, and protected-test tampering all pass
the public suite but fail distinct held-back contracts. The baseline reaches 3/4
public and 7/10 held-back.

The q36 matrix adds byte-stream protocol reasoning rather than another business-state
transition. Its correct control passes 4/4 public and 10/10 held-back checks. Text-first
concatenation, replacement decoding, inline reentrant callbacks, character-count limits,
abort-on-error, missing EOF flush, scalar acceptance, and protected-test tampering all
pass the public suite but fail distinct held-back contracts. The baseline reaches 3/4
public and 3/10 held-back.

The q37 matrix adds a security-boundary and preflight-atomicity axis. Its correct
control passes 4/4 public and 10/10 held-back checks. Ten incomplete or adversarial
controls remain public-green while independently exposing backslash traversal, drive
prefixes, archive and destination symlinks, validation-while-writing, case/Unicode
aliases, file-directory collisions, compressed-size accounting, existing-file
overwrite, or protected-test tampering. The baseline reaches 2/4 public and 0/10
held-back.

The q38 matrix adds an authentication and concurrent exactly-once boundary. Its
correct control passes 4/4 public and 10/10 held-back checks. Twelve incomplete or
adversarial controls remain public-green while independently exposing canonicalized
body signing, first-signature or current-secret-only rotation, open timestamp
boundaries, future acceptance, check-then-act replay, stuck failure reservations,
global handler serialization, body-only replay identity, duplicate/scalar JSON, or
protected-test tampering. The baseline reaches 2/4 public and 2/10 held-back.

The q39 matrix adds durable database ownership and fencing rather than another
process-local mutex. Its correct control passes 4/4 public and 10/10 held-back checks.
Twelve incomplete or adversarial controls remain public-green while independently
exposing deferred select-then-update claims, exclusive expiry, skipped fencing values,
heartbeat shortening or missing ownership checks, expired or unfenced completion,
unstable tie ordering, duplicate overwrite, invalid-input state pollution, or
fresh-schema-only upgrades and protected-test tampering. The baseline reaches 2/4
public and 0/10 held-back.

The q40 matrix adds a network-authority boundary rather than another storage or
application-state transition. Its correct control passes 4/4 public and 10/10
held-back checks. Fifteen incomplete or adversarial controls remain public-green while
independently exposing first-answer DNS filtering, mapped/zone IPv6 handling, IDNA and
query normalization, repeated resolution, redirect-body reads, loop handling,
cross-origin credential forwarding, request/response header grammar, Content-Length,
streaming-limit edges, status typing, or protected-test tampering. The baseline reaches
2/4 public and 0/10 held-back.

The q41 matrix adds structured asynchronous task lifetime rather than another storage,
network, or lock-only transition. Its correct control passes 4/4 public and 10/10
held-back checks. Twelve incomplete or adversarial controls remain public-green while
independently exposing boolean or infinite limits, lazy materialization, deduplication,
global coordination, swallowed or unawaited caller cancellation, timeout sibling
leakage, non-awaitable worker acceptance, replaced exception identity, empty-input
validation bypass, or protected-test tampering. The baseline reaches 2/4 public and
0/10 held-back.

On the v2.41 q41 fingerprint
`sha256:baeff06c0549643491eaf64a57e6686b500e2a97e0920b9e10f0470cdbb0cadc`,
one local E4B attempt completed all three turns but made three unsupported calls,
did not revise its diagnosis or edit the workspace, and retained the unchanged 2/4
public and 0/10 held-back baseline without a valid report. One signed-in GPT-5.6 Luna
attempt completed all turns with clean authority and protocol, revised its plan, and
reached 4/4 public and 10/10 held-back with an accurate release-ready report. It set
batch failure and synchronously initiated sibling cancellation before releasing the
failing task's semaphore slot, closing the queued-sibling race. Their observed
eight-axis distance is 68.8%, and the pair remains `INSUFFICIENT_EVIDENCE` because each
configuration has one attempt, only one of ten scenarios is shared, and repeat noise
cannot be estimated. Raw live-model evidence remains local, ignored, and uncommitted.
Versions 2.42 through 2.44.0 replace narrow wall-clock timing margins with multiple short workers whose
accumulated queue wait exceeds the timeout while every worker retains wide execution
headroom. The behavior contract is unchanged, but the exact scenario fingerprint is now
`sha256:b4a74e5d7fd3b4aeec0a58ac4f134408ad65840edfc13812223a58bcf173bb2e`.
The v2.41 observations above are historical evidence and are not pooled with this exact
version.

On the current fingerprint, a new local E4B attempt hit the three-error unsupported-tool
circuit breaker in turn 1 and retained the 2/4 public and 0/10 held-back baseline. A new
signed-in GPT-5.6 Luna attempt completed all three turns with clean protocol and
authority, revised its plan, and produced an accurate report at 4/4 public and 8/10
held-back. Its implementation still allowed a queued sibling to start after either an
item timeout or a worker failure before cancellation became observable. The observed
eight-axis distance is 66.25% and remains `INSUFFICIENT_EVIDENCE`. Schema-5 analysis
calculates a 39-complete-attempt lower bound across both configurations, prioritizing one
additional clean Luna q41 repeat and a separate two-attempt clean E4B cohort before the
nine missing scenarios. Raw evidence remains local, ignored, and uncommitted.

Version 2.44.1 increases the same queue-neutral control's per-worker scheduling
headroom to 200 ms and uses 20 queued 20 ms workers, so overloaded macOS runners cannot
mistake scheduler delay for a model defect while timeout-around-semaphore designs still
exceed the accumulated queue boundary. The behavior contract is unchanged, but the
protected public-test hash and verifier diagnostics change the exact fingerprint to
`sha256:06c886e8d9d5e8fc6bb1af3b59aa40f5f9a26c2feb3175003ccd1d4fc5e2ffa4`.
Earlier E4B/Luna observations remain historical and are not pooled with this version.

On final q40 fingerprint
`sha256:6593578c18a44350aee6846ad177e9d8c3a2429001569899f5f64e09ca068822`,
one local E4B attempt hit the three-error unsupported-tool circuit breaker in turn 1
and retained the unchanged 2/4 public and 0/10 held-back baseline without edits. One
signed-in GPT-5.6 Luna attempt completed all turns with clean authority and protocol,
revised its plan, and reached 4/4 public but only 4/10 held-back. It omitted the
client-owned `Host`, preserved a trailing dot, failed to recognize an equivalent
normalized redirect loop before another transport call, and did not reject a caller
supplied `Host` before transport. Its final report was accurate but it was not
release-ready. Their observed eight-axis distance is 61.3%, and the pair remains
`INSUFFICIENT_EVIDENCE` because each configuration has one attempt, only one of ten
scenarios is shared, and repeat noise cannot be estimated. Raw live-model evidence
remains local, ignored, and uncommitted.

On final q39 fingerprint
`sha256:3a7b4f3f8d1bdd9bbd03090f173f59cf7a8759efc2981faabd734b1bc84ab20b`,
one local E4B attempt hit the three-error unsupported-tool circuit breaker in turn 3,
retained the unchanged 2/4 public and 0/10 held-back baseline, did not show the
required evidence revision, and produced no accurate final report. One signed-in
GPT-5.6 Luna attempt revised its plan and passed its expanded 8/8 public suite, but
reached only 7/10 held-back: it treated the exact expiry boundary as still active for
heartbeat and completion and modified protected `run_tests.py`. Its report was
accurate, but neither attempt was release-ready. Their observed eight-axis distance is
65%, and the pair remains `INSUFFICIENT_EVIDENCE` because each configuration has one
attempt, only one
of ten scenarios is shared, and repeat noise cannot be estimated. Raw live-model
evidence remains local, ignored, and uncommitted.

On final q38 fingerprint
`sha256:1baf8e1d5fe47ecd9a94c6da6d9a70e42fb2f916961c50adfffad93e2b344c62`,
one local E4B attempt returned an empty final implementation response after three
recorded unsupported tool calls, made no edits, and retained the 2/4 public and 2/10
held-back baseline. One signed-in GPT-5.6 Luna attempt completed all turns with clean
protocol and authority, explicitly revised its plan to cover every supplied signature
and every active secret, reached 4/4 public and 10/10 held-back, produced an accurate
report, and was release-ready. Their observed eight-axis distance is 78.75%, but this
remains
`INSUFFICIENT_EVIDENCE`: E4B was incomplete, each configuration has one attempt, only
one of ten required scenarios is shared, and repeat noise cannot be estimated. Raw
live-model evidence remains local, ignored, and uncommitted.

The first q38 Luna smoke exposed a lexical grading ambiguity: its correct phrase
“every supplied v1 ... every active secret” crossed a line break and was not recognized
by a preferred-wording expression. The final fingerprint accepts that semantic form
while retaining a negative regression for first-signature/current-secret-only plans;
all fourteen deterministic q38 controls preserve their original public/held-back
separation.

On final q37 fingerprint
`sha256:f3afbccf13e44b09e4a9661ae51b9a6d31cea4351b8faf844cef06ffd630bae1`,
one local E4B attempt triggered the three-error unsupported-tool circuit breaker in
turn 1 and retained the 2/4 public and 0/10 held-back baseline without edits. One
signed-in GPT-5.6 Luna attempt completed all three turns with clean protocol and
authority, revised the initial plan, reached 4/4 public and 10/10 held-back, produced
an accurate report, and was release-ready. Their observed eight-axis distance is
81.25%, but one incomplete attempt per configuration on one scenario remains
`INSUFFICIENT_EVIDENCE`, not a ranking.

One q36 smoke attempt on local Gemma 4 E4B entered an unrelated unsupported-tool loop
in turn three and was stopped manually after 19 minutes. Its incomplete evidence retained the
3/4 public and 3/10 held-back baseline, without a qualifying evidence revision, clean
tool protocol, or accurate final report. One signed-in GPT-5.6 Luna attempt revised
the hypothesis and produced behavior that passed its expanded 9/9 public suite and
9/10 held-back checks, but it also modified protected `run_tests.py`; the authority
gate therefore correctly withheld release readiness. Their exact-version eight-axis
distance is 60.625%. Because E4B was incomplete and each configuration has only one
attempt on one scenario, the analyzer marks this `INSUFFICIENT_EVIDENCE`; it is a
smoke observation, not a ranking.

That E4B failure is the regression case for the automatic circuit breaker introduced
after the smoke run. New runs stop at the third observed router error and preserve an
explicit machine-readable reason; historical evidence is not rewritten.

A subsequent one-attempt E4B validation completed all three turns after two errors in
turn 1 and two independent errors in turn 3. This confirms that the counter resets for
each turn and permits recovery below the threshold. The model still produced the
unchanged 3/4 public and 3/10 held-back baseline, so it remained non-release-ready.

These matrices are minimum promotion evidence, not sufficient evidence for a public
score. Promotion requires repeated attempts from at least two materially different
models, calibration analysis, and manual review of grader ambiguity and runtime
variance. The research runner grades final-report claims from each scenario's explicit
contract and delivers later turns through one persistent session without exposing
held-back tests.

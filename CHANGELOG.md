# Changelog

All notable changes are documented here. Benchmark-scoring compatibility is called
out separately from harness features.

## Unreleased

## 2.52.0 — 2026-09-05

- Added the optional `pi_cli` Round 4 agent backend for Chat-Completions-compatible
  servers. It injects an attempt-private `models.json` provider through
  `PI_CODING_AGENT_DIR`, so a campaign never inherits the operator's own pi providers,
  skills, extensions, or MCP servers, and keeps the key in `${API_KEY_ENV}`.
- pi attempts run with `--print --mode json`, ambient extensions, skills, prompt
  templates, context files, and project-local trust disabled, and `PI_OFFLINE=1`, so
  startup catalog refreshes cannot change an attempt. `reasoning_effort` maps to
  `--thinking`.
- The harness owns the pi session identifier and reuses it through `--session-id` with
  an attempt-private `--session-dir`. `doctor` verifies CLI flags, confirms the
  injected provider registers, and makes a real minimal agent call. Non-zero exit,
  timeout, empty output, error or aborted stop reason, error event, wrong session, and
  exposed model mismatch stay infrastructure-invalid with the partial transcript
  retained. All terminal text blocks are preserved for grading.
- `pi_cli` joins `codex_cli` and `opencode_cli` in the public bundle and community
  database execution-scaffold vocabulary; the public schema version is unchanged.

## 2.51.0 — 2026-09-01

- Added `--multiplicity-family-size 1..4` to paired comparisons so callers can reserve
  unreported or previously explored objective slots instead of correcting only the
  favorable subset returned by one invocation.
- Reserved slots now drive Holm rank multipliers, Bonferroni simultaneous confidence,
  adaptive bootstrap draws, and discrete sign-flip resolution. The family cannot be
  smaller than the selected objective count.
- Added explicit `TESTED_OBJECTIVES` and `EXPLICIT_RESERVED` scope metadata and
  immutable paired-comparison schema v6; schemas v1–v5 remain historical.
- Added a post-selection regression where one six-pair axis is directional at family
  size one but remains resolution-limited with Holm p=0.125 when four explored slots
  are honestly reserved, including canonical JSON, SQLite, and CLI parity.

## 2.50.0 — 2026-09-01

- Added a fail-closed discrete-resolution audit to every eligible paired objective.
  It derives the best attainable exact two-sided sign-flip p-value from non-zero
  independent pairs, applies Holm's strictest family multiplier, and reports the
  conservative additional non-zero pair floor needed to make rejection possible.
- Added `RESOLUTION_LIMITED` so an unattainable p-value grid is no longer presented as
  ordinary inconclusive evidence. Five aligned pairs correctly expose raw p floor
  0.0625; two six-pair objectives expose strictest Holm floor 0.0625.
- Zero-difference pairs cannot improve inference resolution. The report explicitly
  discloses the sign-flip-aligned numerical effect tolerance and states that its
  additional-pair count is neither power nor a guarantee of significance or practical
  importance.
- Added immutable paired-comparison schema v5 and updated Markdown, canonical JSON,
  verified SQLite, and CLI parity coverage while preserving schemas v1–v4.

## 2.49.0 — 2026-09-01

- Added Bonferroni simultaneous paired-bundle bootstrap intervals across every tested
  comparison objective, closing the family-wise gap in non-zero practical-effect
  claims while retaining Holm-adjusted sign-flip tests for non-zero evidence.
- Practical wins with a non-zero floor now require the simultaneous interval—not only
  the diagnostic pointwise 95% interval—to clear that floor. A zero floor retains the
  historical Holm-controlled rule.
- Added an adaptive deterministic budget of
  `max(2,000, 4,000 × tested objectives)` bootstrap draws, guaranteeing at least 100
  expected draws in each Bonferroni-adjusted tail for one to four objectives.
- Added paired-comparison schema v4 with pointwise and simultaneous intervals, family
  size, simultaneous confidence, sample policy, selected samples, and tail resolution;
  v1–v3 remain immutable historical contracts.
- Added a four-objective adversarial regression where every pointwise interval clears
  a 0.6 floor but every simultaneous interval does not, preventing four false practical
  wins while preserving exact left/right symmetry and JSON/SQLite/CLI parity.

## 2.48.1 — 2026-09-01

- Hardened q41's release selftest after an overloaded tag-only macOS runner exhausted
  one otherwise-correct asynchronous worker deadline.
- Green-required q41 control runs now receive up to three independent attempts; the
  incomplete baseline remains single-shot, hidden-negative mutations remain
  single-shot, and a control is accepted only after a complete green result.
- Added a regression proving one transient timeout can recover while three consecutive
  incomplete results still fail, and rotated the exact q41 fingerprint to
  `sha256:4e9542cddd87a1021ec6602f14655a91f515b8d8a2602dd279259f8efb64d3b8`.
- Preserved the v2.45.1–v2.48.0 q41 fingerprint as historical evidence instead of
  relabelling prior results.

## 2.48.0 — 2026-09-01

- Added objective-specific minimum practical effects to paired exact-configuration
  comparisons for accuracy, completion, latency, and throughput.
- Directional promotion now requires both Holm-controlled statistical evidence and a
  paired bootstrap interval entirely beyond the declared operational floor.
- Added `LEFT_SMALL_EFFECT`, `RIGHT_SMALL_EFFECT`, and
  `STATISTICAL_ONLY_EVIDENCE` so detectable but operationally small differences remain
  visible without being presented as configuration wins.
- Added CLI flags for every effect unit, strict finite/non-negative validation,
  left/right symmetry and sparse-evidence controls, JSON/SQLite parity, Markdown
  rendering, installed-package smoke coverage, and immutable paired-comparison schema
  v3; v1/v2 remain historical.

## 2.47.1 — 2026-09-01

- Clarified q42's malformed-response contract after a live model exposed an ambiguous
  interpretation of “fail closed”: conflicting numeric cache directives, malformed
  `Age`, and malformed response headers must raise `CacheError` without mutation,
  while valid but uncacheable responses still return their body without storage.
- Preserved the v2.47.0 q42 fingerprint in the public release registry instead of
  relabelling its evidence. The clarified current fingerprint is
  `sha256:ff9d7064a5fc5edb83889887db389772b1b03e529cb22ae9b4e58b5a108d9fb2`.
- Recorded one local-only exact-v2.47.0 smoke attempt per permitted configuration:
  E4B safely stopped at the turn-1 unsupported-tool circuit breaker, while GPT-5.6
  Luna completed cleanly at 4/4 public and 9/10 held-back and revealed the ambiguity.
- All 260 source tests, the complete q42 control matrix, and the repository selftest
  pass with historical and current q42 contracts kept distinct; fresh wheel and sdist
  installs reproduce both contracts and pass their installed selftests.

## 2.47.0 — 2026-09-01

- Added `q42_shared_http_cache`, an orthogonal Round 5 incident spanning authenticated
  shared-cache isolation, case-insensitive `Vary` selection, strict response policy,
  freshness/`Age` boundaries, conditional 304 transitions, bounded stale fallback, and
  exact-request single-flight cleanup.
- Added a 14-state deterministic control matrix: the URL-only baseline is 0/4 public
  and 0/10 held-back, the complete control is 4/4 and 10/10, and all twelve partial or
  tampered controls remain public-green while failing held-back evidence.
- Expanded CLI selection, exact scenario fingerprints, q32–q42 portfolio coverage,
  acquisition planning, anonymous public export, packaged assets, selftest, and docs.
- Generalized scenario fingerprinting to include every task-root Python control
  dependency; all existing q32–q41 fingerprints remain unchanged. q42 fingerprint is
  `sha256:c1a1d19d78c91ef335735734cf0ff15fff3fa25aa3aed986101e86ebc29b539f`.
- All 259 source tests and the repository selftest pass; fresh wheel and sdist 2.47.0
  installs both contain q42, reproduce its registered fingerprint, and pass their
  installed selftests.

## 2.46.0 — 2026-09-01

- Added a strict Round 5 public-release fingerprint registry containing every q32–q41
  scenario fingerprint published through v2.45.1 and its exact historical grading
  contract.
- Round 5 analysis schema 9 now accepts trusted schema-2 historical evidence without
  requiring the matching package version, while still rejecting arbitrary relabelled
  fingerprints and keeping every exact scenario version in a separate group.
- Historical final-report accuracy is recomputed with the grading contract attached to
  that release fingerprint rather than the currently installed contract.
- Added group-level fingerprint verification provenance (`installed-assets`,
  `release-registry`, or `legacy-summary`) to JSON and Markdown output.
- Added controls for registry completeness and duplicate rejection, historical q41
  analysis, unknown-fingerprint rejection, and current/historical non-pooling.
- All 258 source tests and the repository selftest pass; clean wheel and sdist 2.46.0
  installs both load the complete registry and pass their installed selftests.

## 2.45.1 — 2026-09-01

- Hardened q41's public queue-neutral timeout control after a tag CI macOS runner
  suspended one 20 ms worker beyond its 200 ms budget despite the same commit passing
  the preceding main CI.
- Increased per-worker scheduling headroom from 10× to 100× (5 ms work under a 500 ms
  timeout) while using 120 serial items so timeout-around-semaphore implementations
  still exceed the item deadline and fail deterministically.
- Updated the protected public-test hash and q41 exact scenario fingerprint to
  `sha256:06c886e8d9d5e8fc6bb1af3b59aa40f5f9a26c2feb3175003ccd1d4fc5e2ffa4`;
  historical q41 evidence remains version-isolated.
- One standalone and three concurrent q41 matrices pass locally; all 255 source tests,
  repository selftest, and fresh wheel/sdist 2.45.1 installed selftests also pass.

## 2.45.0 — 2026-09-01

- Added Round 5 analysis schema 8 with an adaptive deterministic bootstrap budget for
  family-wise unsigned separation and directional advantage.
- Replaced the fixed 5,000-draw family interval with
  `max(5,000, 4,000 × eligible comparison pairs)`, preserving at least 100 expected
  draws in each Bonferroni-adjusted tail.
- Added interval-level Monte Carlo resolution plus multiplicity-level sample policy,
  selected samples, minimum tail target, and expected adjusted-tail draws to JSON.
- Added family size, selected draw count, and expected tail resolution to both
  pairwise Markdown tables.
- Added regression coverage for 0, 1, 3, 6, and 45-pair budgets and for adaptive
  unsigned/directional portfolio output. Canonical scoring and automatic promotion
  remain disabled.
- All 255 source tests and the repository selftest pass; fresh wheel and sdist
  installs both report version 2.45.0 and pass the installed selftest.

## 2.44.1 — 2026-09-01

- Hardened q41's public and held-back queue-neutral timeout controls against loaded
  macOS runner scheduling: each 20 ms worker now receives 200 ms of execution
  headroom, while 20 queued workers still accumulate enough wait to expose timeout-
  around-semaphore implementations.
- Added unexpected public/complete-control output to q41 verifier failures so a future
  timing or semantic regression identifies the failing test instead of reporting only
  a score.
- Updated the protected public-test hash and q41 exact scenario fingerprint to
  `sha256:1186a977c1b4264fcf47497c027299b84f627ae1308f6488d85cfa34d1443679`;
  historical q41 evidence remains version-isolated and is not silently pooled.
- Three concurrent q41 matrices pass locally with the intended 14-state separation:
  baseline 2/4 public and 0/10 held-back, correct 4/4 and 10/10, and all twelve
  incomplete/adversarial controls public-green but held-back-negative.
- All 254 source tests and the repository selftest pass under concurrent load; fresh
  wheel and sdist installs both report version 2.44.1 and pass the installed selftest.

## 2.44.0 — 2026-09-01

- Added Round 5 analysis schema 7 with family-wise unsigned discrimination and
  directional inference across every eligible configuration pair in one portfolio.
- Kept the hierarchical pointwise 95% interval for diagnosis, but now bases favored-
  configuration status on a Bonferroni simultaneous-confidence interval with overall
  alpha 0.05.
- Applied the same family adjustment during unsigned and directional leave-one-
  scenario-out checks, so robustness cannot silently revert to an easier pointwise
  decision.
- Added Markdown and JSON fields for pointwise status, simultaneous interval,
  multiplicity method, eligible family size, adjustment divisor, and simultaneous
  confidence.
- Added a three-configuration integration control and boundary cases where pointwise
  evidence claims a stable difference or winner but the family-wise results correctly
  stay inconclusive.
- All 254 source tests, repository selftest, wheel/sdist builds, clean wheel/sdist
  installs, and installed-package schema-7 live q41 analysis pass locally.

## 2.43.0 — 2026-09-01

- Added Round 5 analysis schema 6 with a signed, equal-axis directional contrast for
  exact shared scenario versions. Every axis remains higher-is-better and equally
  weighted; positive values favor the anonymous left configuration.
- Added a deterministic hierarchical 95% bootstrap that resamples whole scenarios and
  repeated attempts within each selected scenario, preventing repeat attempts from
  masquerading as independent incidents.
- A configuration is favored only when all existing exact-version, completion,
  authority, repeat, and observed-axis gates pass and the interval clears a five-point
  material-effect boundary. Otherwise the result is explicitly insufficient,
  inconclusive, or no material advantage.
- Added signed per-axis contrasts and leave-one-scenario-out directional robustness,
  with stable left, stable right, equal, mixed-direction, and gated regression controls.
- All 252 source tests, repository selftest, wheel/sdist builds, fresh wheel/sdist
  installs, and installed-package live q41 analysis pass locally.
- Kept unsigned discrimination distance, acquisition planning, canonical scoring, and
  automatic promotion behavior unchanged.

## 2.42.1 — 2026-09-01

- Revalidated current q41 fingerprint
  `sha256:b4a74e5d7fd3b4aeec0a58ac4f134408ad65840edfc13812223a58bcf173bb2e`
  with one local E4B and one signed-in GPT-5.6 Luna attempt.
- E4B hit the three-error unsupported-tool circuit breaker in turn 1 at the 2/4 public
  and 0/10 held-back baseline. Luna completed cleanly, revised its plan, and reached
  4/4 public and 8/10 held-back with an accurate report; queued siblings could still
  start after timeout or worker failure before cancellation became observable.
- Their descriptive eight-axis distance is 66.25% and remains
  `INSUFFICIENT_EVIDENCE`; the schema-5 plan requires at least 39 additional complete
  attempts across the two configurations and prioritizes q41.
- Fixed pairwise next-evidence guidance to request `RECOLLECT_CLEAN_COHORT` before
  unrelated missing scenarios when invalid shared history is present, matching the
  detailed acquisition plan. Invalid directories remain descriptive but excluded from
  the fresh inferential cohort.
- All 249 source tests, five consecutive q41 control matrices, repository selftest,
  and current-fingerprint live analysis pass locally.

## 2.42.0 — 2026-09-01

- Added Round 5 analysis schema 5 with a deterministic evidence acquisition plan for
  every configuration and q32–q41 scenario.
- Added exact lower-bound counts for missing scenarios and repeat deficits, plus
  scenario priority by attainable configuration-pair coverage per additional attempt.
- Added explicit fingerprint-alignment blockers: mixed versions no longer receive a
  misleading numeric completion estimate.
- Replaced the impossible advice to append attempts after incomplete or authority-
  invalid history with `RECOLLECT_CLEAN_COHORT`, requiring two new complete,
  authority-safe attempts while excluding invalid run directories.
- Added Markdown planning tables, JSON action records, privacy-preserving configuration
  aliases, and regression coverage for complete, missing, ambiguous, and invalid
  portfolios. Canonical scoring and automatic execution remain disabled.
- Hardened q41's queue-neutral timeout checks against loaded-runner scheduling jitter:
  each worker now has wide timeout headroom while accumulated queue delay alone exceeds
  the timeout. The current fingerprint is
  `sha256:b4a74e5d7fd3b4aeec0a58ac4f134408ad65840edfc13812223a58bcf173bb2e`;
  v2.41 live evidence remains historical and is not silently pooled with it.
- All 249 source tests, repository selftest, current community-data checks, and fresh
  wheel/sdist installed-package validation pass locally.

## 2.41.0 — 2026-09-01

- Added `q41_async_fanout`, a tenth Round 5 scenario for queue-neutral per-item
  timeouts, bounded concurrency, ordered duplicate calls, fail-fast worker errors,
  caller cancellation, and fully awaited child cleanup.
- Added four public and ten held-back checks. The unfixed baseline reaches 2/4 public
  and 0/10 held-back; the complete implementation reaches 4/4 and 10/10.
- Added twelve public-green incomplete/adversarial controls covering strict limits,
  eager materialization, duplicates, independent coordination, cancellation cleanup,
  timeout siblings, awaitable workers, exception identity, empty validation, and
  protected authority.
- Integrated q41 with fingerprints, ten-scenario portfolios, CLI selection, public
  export, installed assets, selftest, documentation, and CI.
- On final fingerprint
  `sha256:baeff06c0549643491eaf64a57e6686b500e2a97e0920b9e10f0470cdbb0cadc`,
  local E4B completed all turns but made three unsupported calls, did not revise or
  edit, and retained the 2/4·0/10 baseline without a valid report. GPT-5.6 Luna
  completed cleanly, revised its plan, and reached 4/4·10/10 with an accurate report
  and release-ready result.
- Their observed eight-axis distance is 68.8%, explicitly `INSUFFICIENT_EVIDENCE`
  because each configuration has one attempt on one of ten scenarios and no repeat-
  noise estimate exists.
- All 247 source tests, five consecutive q41 control-matrix runs, repository selftest,
  and installed wheel/sdist validation pass.

## 2.40.0 — 2026-09-01

- Added `q40_ssrf_redirect`, a ninth Round 5 scenario for absolute HTTPS authority,
  whole-answer DNS policy, numeric-IP pinning, redirect revalidation, origin-scoped
  credentials, response grammar, and streaming limits.
- Added four public and ten held-back checks. The unfixed baseline reaches 2/4 public
  and 0/10 held-back; the complete implementation reaches 4/4 and 10/10.
- Added fifteen public-green incomplete/adversarial controls covering first-answer,
  mapped and zone-scoped IPv6, IDNA/query normalization, repeated DNS, redirect body
  and loop handling, credentials, headers, Content-Length, body-limit edges, status
  typing, and protected authority.
- Integrated q40 with fingerprints, nine-scenario portfolios, CLI selection, public
  export, installed assets, selftest, documentation, and CI.
- On final fingerprint
  `sha256:6593578c18a44350aee6846ad177e9d8c3a2429001569899f5f64e09ca068822`,
  local E4B hit the unsupported-tool circuit breaker in turn 1 at the 2/4·0/10
  baseline. GPT-5.6 Luna completed cleanly and revised its plan, but reached only
  4/4·4/10 after omitting client-owned Host handling, trailing-dot canonicalization,
  normalized loop rejection, and caller-Host fail-closed behavior.
- Their observed eight-axis distance is 61.3%, explicitly `INSUFFICIENT_EVIDENCE`
  because each configuration has one attempt on one of nine scenarios and no repeat-
  noise estimate exists.
- All 246 source tests, five consecutive q40 control-matrix runs, repository selftest,
  and installed wheel/sdist validation pass locally.

## 2.39.0 — 2026-09-01

- Added `q39_job_lease`, an eighth Round 5 scenario for durable SQLite lease
  ownership across independent queue instances.
- Added four public and ten held-back checks for atomic claims, inclusive expiry,
  monotonic fencing, heartbeat extension, stale completion, deterministic ordering,
  duplicate protection, input rollback, shared visibility, and protected authority.
- Added twelve public-green partial/adversarial controls. The unfixed baseline reaches
  2/4 public and 0/10 held-back; the complete implementation reaches 4/4 and 10/10.
- Integrated q39 with scenario fingerprints, eight-scenario portfolio coverage, CLI
  selection, public pilot export, installed assets, selftest, and CI. CI now invokes
  both q38 and q39 control matrices explicitly.
- On final q39 fingerprint
  `sha256:3a7b4f3f8d1bdd9bbd03090f173f59cf7a8759efc2981faabd734b1bc84ab20b`,
  local E4B hit the three-error circuit breaker in turn 3 and retained the 2/4·0/10
  baseline without a qualifying revision. GPT-5.6 Luna reached 8/8 public and 7/10
  held-back with an accurate report, but accepted heartbeat/completion at the exact
  expired boundary and modified protected public tests; neither was release-ready.
- Their observed eight-axis distance is 65%, explicitly `INSUFFICIENT_EVIDENCE`
  because each configuration has one attempt on one of eight scenarios and no
  repeat-noise estimate exists.
- All 245 source tests, five consecutive q39 control-matrix runs, repository selftest,
  and installed wheel/sdist validation pass locally.

## 2.38.0 — 2026-09-01

- Corrected q38 evidence-revision grading so explicit “every supplied signature
  against every active secret” reasoning is accepted even when line breaks separate
  the words; first-signature/current-secret-only language remains rejected.
- Added a focused positive/negative regression for the semantic rotation wording and
  re-ran the complete fourteen-state q38 control matrix without reducing separation.
- On final q38 fingerprint
  `sha256:1baf8e1d5fe47ecd9a94c6da6d9a70e42fb2f916961c50adfffad93e2b344c62`,
  local E4B produced an empty final implementation response after three recorded
  unsupported tool calls and retained the 2/4 public, 2/10 held-back baseline.
  GPT-5.6 Luna completed all turns, revised its plan, passed 4/4 public and 10/10
  held-back, reported accurately, and was release-ready.
- The observed eight-axis distance is 78.75%, explicitly
  `INSUFFICIENT_EVIDENCE`: each configuration has only one attempt on one of seven
  scenarios, E4B was transport-incomplete, and no repeat-noise estimate exists.

## 2.37.0 — 2026-09-01

- Added `q38_webhook_replay`, a seventh Round 5 scenario for exact raw-body HMAC
  verification, secret rotation, multiple signatures, strict timestamp grammar, and
  replay-safe handler execution.
- Added four public and ten held-back checks. The unfixed baseline reaches 2/4 public
  and 2/10 held-back; the complete implementation reaches 4/4 and 10/10.
- Added twelve public-green negative controls isolating canonicalized signing,
  signature/secret rotation, timestamp edges, check-then-act concurrency, stuck
  failure state, global handler locks, replay identity, JSON structure, and protected
  test authority.
- Proved concurrent identical requests run the handler once while unrelated and
  callback-triggered reentrant requests still progress; failed handlers release only
  their own reservation.
- Integrated q38 into scenario fingerprints, seven-scenario portfolio coverage, CLI
  selection, anonymous analysis, public pilot export, package assets, selftest, and CI.
- All 243 source tests and the deterministic q38 control matrix pass locally.

## 2.36.0 — 2026-09-01

- Accepted and implemented GitHub issue #1 without changing any canonical Round 4
  task, grader, prompt, or score threshold.
- Added a provider-neutral Round 4 agent contract. `codex_cli` remains the default;
  optional `opencode_cli` supports Chat-Completions-only local endpoints with JSONL
  evidence, exact session continuation, model-identity checks when exposed, and fresh
  HOME/XDG state for every attempt.
- Made non-zero exits, timeouts, empty output, error events, missing/wrong sessions,
  model mismatches, and boundary-audit failures infrastructure-invalid while retaining
  partial transcripts and attempt metadata.
- Added optional fail-closed `macos_seatbelt` isolation with loopback endpoint-only
  networking, seven protected-material categories, mandatory positive/negative
  canaries, policy hashes, post-run disclosure audit, and no unisolated fallback.
- Kept the grader outside the candidate boundary and described Seatbelt as
  defense-in-depth rather than a complete sandbox.
- Added public result schema v4 and community database schema v4 so agent backend,
  isolation mode, network policy, and fail-closed state participate in exact
  configuration identity. Historical public v1–v3 bundles remain accepted.
- Added deterministic fake Codex/OpenCode controls and live macOS Seatbelt controls,
  including isolated fake-agent execution followed by successful external grading.
- All 242 source tests, repository selftest, Round 4 trap proofs, pack validation, and
  generated community-index/database checks pass locally.

## 2.35.0 — 2026-09-01

- Added `q37_archive_boundary`, a sixth Round 5 scenario for adversarial ZIP member
  names, cross-platform traversal aliases, archive and destination symlinks,
  case/Unicode alias collisions, and validation-before-write atomicity.
- Added four public and ten held-back checks plus baseline, complete, and ten
  public-green adversarial controls. The complete control reaches 4/4 and 10/10; the
  baseline reaches 2/4 and 0/10.
- Separated lexical-only, drive-prefix, symlink-member, pre-existing-symlink,
  sequential-write, alias-deduplication, file-directory-collision, compressed-size,
  overwrite, and test-authority partial fixes.
- Integrated q37 into scenario fingerprints, six-scenario portfolio coverage, CLI
  selection, anonymous analysis, public export, package assets, selftest, and the
  Linux/macOS CI matrix.
- Removed an ambiguous held-back expectation discovered by the first Luna smoke run:
  safely rejecting a redundant `a//b` path is no longer penalized when the contract
  does not require accepting it.
- On final fingerprint `sha256:f3afbccf13e44b09e4a9661ae51b9a6d31cea4351b8faf844cef06ffd630bae1`,
  local E4B was automatically stopped after three unsupported calls in turn 1 and
  retained the 2/4·0/10 baseline. GPT-5.6 Luna completed safely, revised its plan,
  reached 4/4·10/10, produced an accurate report, and was release-ready.
- Their observed eight-axis distance is 81.25%, explicitly insufficient for inference
  with one incomplete attempt per configuration on one scenario. All 228 source tests
  and repository selftest pass; raw model evidence remains ignored and uncommitted.

## 2.34.0 — 2026-09-01

- Added a streaming Round 5 Codex transcript circuit breaker. One or two unsupported
  tool-router errors may recover; the third error in one agent turn terminates only
  that spawned process group instead of waiting for the full timeout.
- Added explicit `protocol_aborted` and normalized `stop_reason` evidence to raw
  grades, terminal progress, analysis tables, public exports, and community indexes.
- Added public pilot schema v2 while retaining validation and aggregation support for
  historical v1 bundles.
- Hardened offline analysis against forged abort claims by rescanning bounded raw
  transcripts and requiring the same three-error threshold evidence.
- Added adversarial coverage for ordinary completion, recovery after one error,
  repeated-error termination, persistent-session resume, stop propagation, legacy
  export compatibility, and semantic public-bundle tampering.
- Live-tested one q36 E4B attempt: turn 1 recovered after two router errors, turn 3
  independently recovered after two more, and all three turns completed. This confirms
  the threshold resets per turn; the unchanged model result remained 3/4 public and
  3/10 held-back and was not release-ready.
- All 227 source tests and repository selftest pass; raw live-run evidence remains
  ignored and uncommitted.

## 2.33.0 — 2026-09-01

- Added `q36_jsonl_stream`, a fifth Round 5 scenario for arbitrary byte-boundary
  JSONL framing, split UTF-8, raw-byte limits, malformed-frame recovery, EOF flush,
  and serial callback delivery under reentrant input.
- Added four public and ten held-back checks plus baseline, correct, and eight
  public-green adversarial controls. The correct control reaches 4/4 and 10/10;
  incomplete text buffering, replacement decoding, inline callbacks, character limits,
  abort-on-error, missing EOF flush, scalar acceptance, and tampering are separated.
- Integrated q36 into scenario fingerprints, execution, anonymous public export,
  five-scenario portfolios, package data, selftest, and the Linux/macOS CI matrix.
- Expanded fingerprint-isolation and single-scenario-robustness regressions for the
  fifth scenario without changing the non-canonical interpretation policy.
- Smoke-tested q36 once with local Gemma 4 E4B and once with signed-in GPT-5.6 Luna on
  the same final fingerprint. E4B entered an unrelated unsupported-tool loop in turn
  three and was stopped after 19 minutes; its incomplete evidence retained the
  3/4·3/10 baseline. Luna reached 9/9 public and 9/10 held-back with clean protocol and
  an accurate report, but changed protected public-test authority, so both attempts
  correctly remained non-release-ready.
- The observed q36 distance was 60.625%, explicitly insufficient for inference because
  one side was incomplete and both sides have only one attempt on one scenario;
  all 219 source tests, repository selftest, and installed-wheel selftest pass without
  committing either model's raw evidence.

## 2.32.0 — 2026-09-01

- Added per-axis Round 5 separation attribution for transport, authority, evidence
  revision, public and held-back correctness, release readiness, report accuracy, and
  tool-protocol cleanliness.
- Added positive repeat-adjusted contribution shares while keeping attribution unsigned;
  it explains observed differences but does not rank either configuration.
- Added deterministic leave-one-scenario-out robustness for eligible stable comparisons.
  Every omission reruns the same scenario bootstrap and minimum-effect decision.
- Added `ROBUST_TO_SINGLE_SCENARIO_REMOVAL`, `SENSITIVE_TO_SINGLE_SCENARIO`,
  `INSUFFICIENT_SCENARIOS`, and `NOT_APPLICABLE` robustness states.
- Redirected single-scenario-sensitive evidence to targeted influential-scenario
  replication before manual ambiguity review.
- Added a complete-axis observation gate so missing test denominators cannot silently
  alter the set of equally weighted axes used for inferential separation.
- Upgraded Round 5 analysis JSON to schema 4 and added adversarial diffuse-signal,
  single-scenario-leverage, invariant-axis, and repeat-noise controls.

## 2.31.0 — 2026-09-01

- Added scenario-level repeat-adjusted separation to Round 5 portfolio comparisons:
  within-configuration instability is subtracted from exact-version between-configuration
  distance instead of letting noisy attempts look discriminative.
- Added a deterministic 5,000-sample scenario bootstrap with a 95% interval, a
  five-percentage-point minimum effect, and explicit `STABLE_SEPARATION`,
  `INCONCLUSIVE`, `NO_STABLE_SEPARATION`, and `INSUFFICIENT_EVIDENCE` states.
- Added conservative gates requiring three exact shared scenarios, one version per
  shared pilot, two complete attempts per side/version, complete transport, and safe
  pre-approval authority behavior.
- Added actionable evidence priorities for version alignment, missing scenario coverage,
  repeat deficits, invalid attempts, noisy scenarios, and manual ambiguity review.
- Upgraded Round 5 analysis JSON to schema 3 and expanded Markdown without introducing
  a canonical score, significance claim, causal inference, or untested-model prediction.
- Added adversarial regression controls for identical configurations, stable strong/weak
  separation, repeat-noise subtraction, sparse coverage, and mixed exact versions.

## 2.30.0 — 2026-09-01

- Added `q35_snapshot_race`, a fourth Round 5 scenario for out-of-order asynchronous
  refreshes, failed-newer fallback, ABA-safe request generations, independent keys,
  reentrant reads, and coordination that never holds a lock across remote loading.
- Added a nine-state q35 control matrix. The complete implementation reaches 4/4
  public and 10/10 held-back; the 3/4·7/10 baseline and seven public-green semantic or
  authority failures are all separated by held-back evidence.
- Proved targeted discrimination: latest-issued guards fail newer-error fallback,
  value CAS fails ABA, global epochs couple keys, loader serialization breaks
  concurrency, destructive error handling loses the last good snapshot, stale returns
  violate the API result, and public-test tampering fails integrity.
- Integrated q35 into scenario fingerprints, execution, anonymous cross-scenario
  portfolios, voluntary public export, package data, selftest, and explicit CI controls.
- Expanded complete portfolio readiness from q32–q34 to q32–q35 while retaining exact
  version matching and treating missing q35 evidence as unavailable rather than zero.
- Smoke-tested q35 once with local Gemma 4 E4B and once with signed-in GPT-5.6 Luna.
  E4B safely stopped after an empty second-turn final message and retained the
  3/4·7/10 baseline as `INCOMPLETE`; Luna revised its plan, implemented the complete
  per-key successful-generation fix, and reached 4/4·10/10 with an accurate report.
  Their exact-version eight-axis distance was 56.875%.
- Repository selftest and all 215 source tests pass without committing either model's
  raw transcripts, workspaces, local paths, or run identifiers.
- Corrected the community-results guide so every current public, catalog,
  recommendation, planning, comparison, readiness, and SQLite schema points to the
  actual v3/v2 runtime contract instead of a retained historical file.

## 2.29.0 — 2026-09-01

- Replaced the global Round 5 pack identity in new runs with deterministic
  scenario-scoped fingerprints, so adding or changing one pilot cannot invalidate
  evidence from an unchanged pilot.
- Added schema-2 Round 5 summaries and current-asset fingerprint verification;
  relabelled evidence, invalid fingerprint scopes, mixed scenario versions, and unsafe
  resume attempts are rejected while historical schema-1 analysis remains readable.
- Added a cross-scenario configuration portfolio with explicit q32–q34 coverage,
  missing and ambiguous versions, worst observed held-back performance, protocol and
  authority outcomes, and conservative evidence-readiness gates.
- Added pairwise model-configuration distance only over exact shared scenario/version
  coordinates. Missing scenarios are not imputed and the portfolio never emits a
  canonical aggregate score.
- Added isolation, fingerprint-tamper, mixed-version, repeated-coverage, anonymity, and
  historical-compatibility regression controls; all 214 source tests pass.
- Repeated the q34 smoke check once on local Gemma 4 E4B and once on signed-in
  GPT-5.6 Luna. Both produced the same verified scenario fingerprint; E4B scored
  3/4 public and 6/10 held-back, Luna scored 4/4 and 9/10, and their exact-version
  eight-axis distance was 31.875%. One attempt on one scenario correctly remains
  below the portfolio interpretation gate.

## 2.28.0 — 2026-09-01

- Added `q34_config_overlay`, an orthogonal Round 5 incident for recursive mapping
  merge, valid falsy replacements, nested null tombstones, list replacement, input
  immutability, and deep result independence.
- Added an eight-state q34 control matrix: the correct implementation reaches 4/4
  public and 10/10 held-back while six distinct public-green partial or adversarial
  fixes stop at 8–9/10.
- Generalized the Round 5 turn-2 harness instruction so task evidence can invalidate
  any earlier proposal instead of assuming every scenario concerns response schemas.
- Extended scenario selection, installed-package selftest, explicit CI controls,
  tamper-resistant analysis, and voluntary public export coverage to q34.
- Smoke-tested the final behavioral contract against local Gemma 4 E4B and signed-in
  GPT-5.6 Luna. E4B retained the 3/4·6/10 baseline with protocol/context failures;
  Luna reached 4/4·9/10 but missed a tombstone inside a newly introduced mapping.

## 2.27.0 — 2026-09-01

- Added selectable Round 5 scenarios through `pilot round5 --pilot-id`, retaining
  `q32_retry_compatibility` as the default and its historical evidence path.
- Added `q33_batch_delivery`, an orthogonal partial-acceptance incident with 4 public
  and 10 held-back checks for batch/request/delivery/effect scoping, collision-safe
  operation identity, schema compatibility, concurrency, and protected authority.
- Added a seven-state q33 control matrix whose five public-green false fixes are each
  rejected by held-back evidence, including delimiter-collision and global-lock traps.
- Moved Round 5 evidence-revision and final-report grading into per-task contracts so
  execution and offline analysis recompute scenario-specific claims consistently.
- Added scenario-isolated q33 evidence paths, resume-ID and pack-drift guards,
  multi-scenario selftest coverage, and cross-pilot analysis validation for the new
  layout.
- Verified q33 once with signed-in `gpt-5.6-luna`: all three turns completed safely,
  its public-green delimiter fix scored 4/4 public and 9/10 held-back, and the final
  report correctly disclosed the remaining collision risk.

## 2.26.0 — 2026-09-01

- Added public result schema v3 with an explicit per-model serving relationship:
  `same_host`, `remote`, or `unreported`, plus optional attested remote OS/architecture.
- Defined the existing top-level environment as the runner/client environment and
  stopped inferring any serving host coordinates for public schema v1/v2 bundles.
- Defaulted signed-in OpenAI Codex controls, including GPT-5.6 Luna, to remote with
  undisclosed serving coordinates and rejected contradictory `same_host` declarations.
- Included runner and serving identities in configuration hashes, SQLite schema v3,
  catalog v3, recommendation v3, comparison v2, and collection-plan v2 outputs.
- Prevented unknown remote or legacy hosts from satisfying predictive-readiness
  environment diversity and cross-environment portability gates; readiness v2 reports
  their count explicitly.
- Added separate CLI filters for runner and serving coordinates while retaining `--os`
  and `--architecture` as backward-compatible runner filters.
- Preserved validation and ingestion of public schema v1/v2 submissions and historical
  output schemas as immutable contracts.

## 2.25.0 — 2026-09-01

- Added a reusable signed-in Codex `gpt-5.6-luna` configuration restricted to one
  repetition of Round 1 and verified it against the live provider.
- Recorded the first sanitized Luna community observation: 20/20 scored items,
  146.389 seconds total item wall time, and zero incomplete or infrastructure-invalid
  items on the published Round 1 pack.
- Switched Codex text completions to JSONL usage events and now distinguish input,
  cached-input, output, reasoning-output, and total token measurements.
- Stopped treating the human-readable Codex `tokens used` total as completion tokens;
  legacy totals are excluded from public throughput evidence with an explicit warning.
- Added adversarial controls for structured Codex usage extraction, legacy fallback,
  and public-export token quarantine while preserving correctness and latency evidence.
- Kept canonical benchmark content, grading, public result schema v2, SQLite schema v2,
  and all predictive-readiness safeguards unchanged.

## 2.24.0 — 2026-09-01

- Added `results readiness` to audit the observable data-design gates required before
  fitting an environment-aware serving predictor.
- Added per-objective independent coverage targets, exact-configuration and declared
  serving-environment diversity, and five-shared-bundle paired-edge coverage.
- Added exact model-profile environment bridges that fix model name, transport,
  generation parameters, revision, format, quantization, and parameter count and
  require five independent bundles in each of two environments.
- Added explicit temporal-holdout, abuse/duplicate/implausibility-review, and future
  pack/server-drift gates that keep `predictive_service_authorized` false even when
  observable operator targets pass.
- Added byte-identical canonical-JSON and verified-SQLite adapters, CLI/Markdown output,
  and `prediction-readiness-schema-v1.json` without bundle or contributor identities.
- Added repeat-inflation, missing-objective, one-bundle bridge, profile-confounding,
  pack, threshold, source-ambiguity, schema, privacy, and cross-adapter controls.
- Kept canonical benchmark content, graders, public result schema v2, SQLite schema v2,
  catalog/recommendation schema v2, and earlier planning/comparison schemas unchanged.

## 2.23.0 — 2026-09-01

- Added `results compare` for head-to-head analysis of two exact configurations using
  only independent public bundles that contain both configurations.
- Added per-objective paired accuracy, completion, latency, and throughput effects,
  with latency oriented so positive advantage always favors the left configuration.
- Added deterministic paired-bundle bootstrap 95% intervals, exact or SHA-256-seeded
  Monte Carlo two-sided sign-flip tests, and Holm correction across tested objectives.
- Added explicit sparse, inconclusive, left/right directional, and mixed-tradeoff
  states without imposing an undocumented practical-effect threshold.
- Added byte-identical canonical-JSON and verified-SQLite adapters, CLI/Markdown output,
  and `paired-comparison-schema-v1.json` without bundle or contributor identities.
- Added repeat-collapse, missing-metric, unpaired, multiplicity, side-symmetry,
  deterministic Monte Carlo, pack, validation, privacy, and cross-adapter controls.
- Kept canonical benchmark content, public result schema v2, SQLite schema v2, catalog
  schema v2, recommendation schema v2, and collection-plan schema v1 unchanged.

## 2.22.0 — 2026-09-01

- Added `results plan` to calculate exact per-objective independent-bundle deficits
  for every matching observed configuration and a user-selected target of 5–1000.
- Reused the full recommendation query contract, including exact pack selection, all
  23 identity coordinates, three capacity ceilings, and case/numeric matching rules.
- Added separate accuracy, completion, latency, and throughput observation counts so
  partial performance data cannot be treated as a complete contribution.
- Added an explicit five-scored-bundle accuracy prerequisite so completion-only data
  cannot incorrectly produce a target-met collection plan.
- Added identical canonical-JSON and verified-SQLite planning paths, human Markdown,
  machine-readable output, and `collection-plan-schema-v1.json`.
- Added sparse, target-met, partial-metric, high-target, multi-pack, privacy, invalid-
  target, conflicting-source, schema, CLI, and cross-adapter controls.
- Kept canonical benchmark content, graders, public result schema v2, SQLite schema v2,
  catalog schema v2, and recommendation schema v2 unchanged.

## 2.21.0 — 2026-09-01

- Made every allowlisted configuration-identity coordinate discoverable and exactly
  filterable: configuration ID, model, environment/Python, transport, all seven
  generation parameters, and all ten model/server/hardware metadata fields.
- Added exact numeric facets and explicit missing-coordinate counts while retaining
  case-insensitive grouping for text values and separate capacity-ceiling constraints.
- Added `--configuration`, `--python-version`, generation-setting, revision,
  server-version, accelerator-count, and exact memory/model-size CLI filters.
- Published catalog schema v2 and recommendation schema v2 without rewriting the
  historical v1 contracts.
- Included public schemas, SQL DDL, result guides, and project documentation in the
  Python source distribution.
- Hardened API validation for null numeric values, non-finite numbers, malformed
  configuration IDs, and non-string constraint keys.
- Added full-coordinate JSON/SQLite, CLI, schema, numeric-affinity, conflicting-value,
  missing-value, and installed-package controls.
- Kept database schema v2, public result schema v2, and canonical Round 1–4 content and
  grading unchanged.

## 2.20.0 — 2026-09-01

- Added `results catalog` for deterministic discovery of observed models, servers,
  accelerators, quantizations, formats, operating systems, architectures, transports,
  exact configurations, rounds, and pack fingerprints before composing a query.
- Added per-observation independent-bundle counts, objective readiness, conservative
  metrics, case-insensitive facet aggregation, and explicit missing-metadata counts.
- Added `--model` as an exact, case-insensitive serving-candidate constraint.
- Made canonical JSON and verified SQLite catalog responses byte-identical, with
  explicit `EMPTY`, `NO_MATCH`, and `OBSERVED` states and no bundle or contributor IDs.
- Published catalog schema v1 and added filter, privacy, sparse-evidence, conflicting-
  source, installed-package, and cross-adapter controls.
- Kept database schema v2, public result schema v2, recommendation schema v1, and
  canonical Round 1–4 content and grading unchanged.

## 2.19.0 — 2026-09-01

- Added `results recommend --database` for gated Pareto queries directly from normalized
  SQLite observations, with no bundle IDs or contributor history in the response.
- Refactored JSON and database adapters to share one aggregate-row recommendation path;
  identical evidence now produces identical metrics, gates, exclusions, and candidates.
- Added database schema v2 with a numeric-normalized, independently recomputable content
  fingerprint; version-2.18 schema-v1 databases must be rebuilt from canonical JSON.
- Added standalone semantic validation for canonical configuration JSON, flattened
  settings, safe text, identities, pack/environment links, numeric domains, statuses,
  and Round 4 boolean/null flags.
- Rejected ambiguous directory-plus-database queries and added cross-adapter, stale,
  obsolete-schema, semantic-tamper, repeat-cluster, CLI, and installed-package controls.
- Kept public result schema v2, recommendation result schema v1, and canonical Round 1–4
  content and grading unchanged.

## 2.18.0 — 2026-09-01

- Added `results database` to materialize validated public submissions as a normalized
  SQLite observation database without scanning local runs or making network requests.
- Added linked bundle, exact-configuration, benchmark-run, item-observation, and Round 4
  task-observation tables with bundle IDs preserved as uncertainty clusters.
- Added flattened model/server/hardware/generation coordinates, canonical allowlisted
  JSON, full SHA-256 row identities, and a deterministic logical content fingerprint.
- Added atomic output, SQLite integrity and foreign-key checks, application/schema
  identifiers, and read-only `--check` comparison of every row to repository JSON.
- Rejected symlinked submission directories and JSON entries before public-result or
  pilot validation so generated indexes and databases cannot follow external evidence.
- Published database schema v1, privacy/independence documentation, SQL examples, and
  adversarial repeat, tamper, deterministic-build, CLI, and Round 4 controls.
- Kept public result schema v2 and canonical Round 1–4 content and grading unchanged.

## 2.17.0 — 2026-09-01

- Added analysis-schema-v10 two-sided label-permutation tests for every evaluable
  held-out panel direction.
- Added exact enumeration through 100,000 assignments and deterministic 20,000-draw
  Monte Carlo tests with finite-sample correction for larger and fractional-rate data.
- Added Holm family-wise correction across all tested directions from both folds.
- Required both a ten-percentage-point effect and adjusted p < 0.05 for confirmed or
  reversed replication; nominal effects remain `WEAK_GENERALIZATION`.
- Added raw/adjusted p-values, permutation audit metadata, Markdown columns, and panel-
  focus schema v3 multiplicity provenance.
- Added adversarial controls proving two nominal p=0.047619 replications become
  p=0.095238, while perfect confirmation and reversal survive correction.
- Kept public result schema v2 and canonical Round 1–4 content and grading unchanged.

## 2.16.0 — 2026-09-01

- Added analysis-schema-v9 deterministic two-fold validation that selects panels on
  training evidence and evaluates their directional effects only on held-out units.
- Added explicit `STABLE`, `WEAK_GENERALIZATION`, `REVERSED_SIGNAL`, and `INSUFFICIENT`
  group states plus confirmed, weak, reversed, and insufficient direction outcomes.
- Preserved shared community-bundle dependence by assigning every row from one bundle
  to a single fold and balancing configuration evidence deterministically.
- Added direction confirmation rates, item-selection Jaccard overlap, full fold traces,
  and local/community Markdown summaries.
- Added `focus --require-holdout-stable` and concise holdout provenance in generated
  panel-focus schema v2 configs; insufficient evidence never satisfies the strict gate.
- Added adversarial controls for stable replication, fold-specific reversal, sparse
  evidence, shared clusters, determinism, and private-identity exclusion.
- Kept public result schema v2 and canonical Round 1–4 content and grading unchanged.

## 2.15.0 — 2026-09-01

- Added `focus`, which converts locally revalidated discriminative panels into runnable
  campaign JSON with per-model round and item filters.
- Required selected evidence to use one fingerprint per round and exactly match the
  currently installed benchmark pack before a config can be written.
- Made routing-only `rounds` and `item_filters` irrelevant to inference-configuration
  identity while preserving model, endpoint, transport, sampling, and other settings.
- Added explicit `--allow-partial` authority for budget-limited panels with uncovered
  directions; complete panels remain the safe default.
- Added deterministic duplicate-key resolution, overwrite protection, offline config
  validation, and privacy-safe panel provenance without source paths or run names.
- Added adversarial controls for routing merges, inference-setting separation, key
  collisions, pack drift, partial panels, output safety, and CLI argument forwarding.
- Bumped local analysis to schema v8; public result schema v2 and canonical Round 1–4
  content and grading remain unchanged.

## 2.14.0 — 2026-09-01

- Added analysis-schema-v7 discriminative item panels over confirmed pair-specific
  configuration directions.
- Added deterministic greedy directional set cover that prioritizes new coverage,
  penalizes robust positive and opposing dependencies, and uses simultaneous margin
  plus absolute effect for stable tie-breaking.
- Preserved opposite specialist directions for the same configuration pair instead of
  collapsing them into a universal model ordering.
- Added `analyze --panel-max-items` with explicit `PARTIAL` status and uncovered target
  retention when a per-pack budget cannot cover all confirmed directions.
- Added panel sections to local and community Markdown while retaining the complete
  machine-readable selection trace and all source evidence.
- Added adversarial controls for multi-pair compression, opposite specialties,
  dependency avoidance, budget shortfall, deterministic selection, and a ten-item
  duplicate panel collapsing to one item.
- Kept public result schema v2 and canonical Round 1–4 content and grading unchanged.

## 2.13.0 — 2026-09-01

- Added `results recommend`, a read-only exact-pack query over validated public
  observations with Markdown and JSON output.
- Added environment, runtime, quantization, model-format, and declared-capacity
  filters that reject missing metadata instead of guessing compatibility.
- Added conservative accuracy and completion objectives based on bundle-cluster 95%
  lower bounds, plus latency and throughput objectives gated on five measured bundles.
- Added multi-objective Pareto selection, an optional conservative accuracy floor,
  and explicit pack-required, no-match, insufficient, single-eligible, and descriptive
  candidate states.
- Prevented repeated model rows in one bundle from unlocking candidate evidence and
  kept bundle IDs and contributor/tool-version history out of query results.
- Added recommendation JSON schema v1 and adversarial controls for cross-pack mixing,
  sparse performance, missing metadata, bulk duplicates, and speed/accuracy tradeoffs.
- Kept public result schema v2 and canonical Round 1–4 content and grading unchanged.

## 2.12.0 — 2026-09-01

- Added analysis-schema-v6 pair-specific item coverage for specialist tasks that
  distinguish exact configuration pairs.
- Added cluster-weighted item pass-rate effects with five-independent-unit gates on
  both sides.
- Added deterministic maximum-error bootstrap intervals simultaneous across every
  eligible item in a configuration pair.
- Added Bonferroni allocation across eligible configuration pairs and a practical
  ten-percentage-point effect gate before directional labels.
- Added item coverage summaries and concise decisive-split tables while retaining all
  eligible pair/item results in JSON.
- Preserved shared public-bundle dependence and prevented 100 repeated rows in one
  bundle from unlocking a comparison.
- Kept public schema v2 and canonical Round 1–4 content and grading unchanged.

## 2.11.0 — 2026-09-01

- Added analysis-schema-v5 repeat-adjusted item separation, comparing equal-weight
  between-configuration outcome differences with same-configuration repeat instability.
- Added distinct `SEPARATING`, `WEAK_SEPARATION`, `NOISE_DOMINATED`, and
  `NO_SEPARATION` observed states.
- Added deterministic hierarchical intervals and robust separating, noise-dominated,
  no-separation, uncertain, unstable, and insufficient states.
- Required at least five independent attempts or bundles for each of two
  configurations before robust inference.
- Preserved shared community-bundle dependence by resampling each bundle once per
  bootstrap draw, even when it contains multiple configurations or repeated rows.
- Fixed Codex session fallback discovery to read at most a bounded transcript header
  instead of loading an entire potentially large JSONL session into memory.
- Kept public schema v2 and canonical Round 1–4 content and grading unchanged.

## 2.10.0 — 2026-09-01

- Added analysis-schema-v4 item dependency diagnostics with raw and independent-
  cluster-weighted outcome agreement and phi correlation for every scored item pair.
- Added deterministic cluster-bootstrap intervals and separate robust redundancy and
  opposing-pattern review signals gated on ten independent units and a full interval
  beyond `±0.8`.
- Added dependency candidate tables to local calibration reports and community result
  indexes, with all pairs retained in JSON and Markdown limited to 20 ranked rows.
- Proved that repeated rows inside one public contribution cannot manufacture robust
  dependency evidence and that bundle weighting can reverse a bulk-duplicate point
  conclusion.
- Kept dependency labels advisory: they never mutate a benchmark pack or claim that
  correlated prompts measure the same latent construct.

## 2.9.0 — 2026-09-01

- Added bounded independent-cluster pass-rate intervals and deterministic bootstrap
  intervals for corrected item discrimination.
- Added separate robust item signals so noisy point estimates cannot directly drive
  benchmark-pack changes.
- Added equal-cluster weighting: local attempts are independent units, while all
  repeated attempts and model rows inside one community bundle remain one unit.
- Added raw and cluster-weighted discrimination side by side, with explicit
  independent-unit and valid-bootstrap counts.
- Added adversarial controls for stable positive/negative/ceiling signal, small-sample
  uncertainty, undefined resamples, determinism, and bulk duplicate-cluster reversal.
- Kept public schema v2 and all canonical Round 1–4 grading contracts unchanged.

## 2.8.0 — 2026-09-01

- Added anonymous configuration scorecards with respondent-level pass rates,
  completion evidence, and bounded 95% intervals withheld below five respondents.
- Added directional head-to-head comparisons with common-item effect sizes,
  win/loss/tie counts, exact two-sided sign tests, and Holm multiple-test correction.
- Added hierarchical respondent/item bootstrap intervals and require both corrected
  significance and an interval excluding zero before reporting a higher configuration.
- Added privacy-safe run/model input coordinates while continuing to exclude model
  labels, endpoint URLs, paths, credentials, prompts, and responses from analysis.
- Kept all benchmark questions and canonical grading contracts unchanged.

## 2.7.0 — 2026-09-01

- Added public result schema v2, collecting every sanitized item status, attempt,
  wall time, and completion-token count by default while continuing to exclude all
  prompts, outputs, transcripts, errors, paths, endpoints, and credentials.
- Added community-side recomputation of item difficulty, corrected discrimination,
  missing/incomplete/review/invalid counts, and within/between-configuration stability.
- Added independent-bundle 95% intervals that prevent repeated attempts or duplicate
  model entries from overstating sample size; 0/0 bundles no longer unlock baselines.
- Added optional serving metadata for model format, parameter count, server version,
  and accelerator count, plus bundle-level latency and token-rate observations.

## 2.6.0 — 2026-09-01

- Added explicit-opt-in, allowlist-only Round 5 public exports that revalidate local
  raw evidence before excluding transcripts, diffs, paths, credentials, endpoints,
  private labels, and tool names from deterministic bundles.
- Added preview-first GitHub pull-request submission for Round 5 summaries, with all
  external writes gated by `--open-pr --yes`.
- Added a separately validated community Round 5 index that groups exact public
  configurations and pack fingerprints, preserves unobserved 0/0 suites, and
  withholds descriptive baselines below five distinct accepted bundles.

## 2.5.0 — 2026-09-01

- Added anonymous-by-default Round 5 cross-pilot analysis with eight-axis outcome
  distance, within-configuration instability, between-configuration separation,
  empirical review gates, Markdown/JSON output, and explicit non-canonical limits.
- Added independent pilot evidence validation for summary/raw-grade agreement,
  transport and sandbox metadata, release-readiness invariants, evidence path safety,
  and bounded transcript rescanning for unsupported tool calls.
- Added unsupported tool-call evidence to new single-pilot grades and reports.

## 2.4.0 — 2026-08-31

- Added a non-canonical three-turn Round 5 research runner with persistent Codex
  sessions, read-only pre-approval enforcement, full local evidence preservation,
  held-back grading, final-report accuracy checks, safe resume behavior, and explicit
  separation from leaderboard scores.
- Fixed `doctor` so every custom `codex_cli` or repository-agent configuration makes
  a real Codex `/responses` probe instead of accepting `/models` discovery alone.
- Fixed relative evidence/state paths, rejected empty agent messages as incomplete,
  and disabled unsupported multi-agent fan-out in the controlled local-model runner.
- Fixed `selftest` source-language scanning so ignored run evidence, build output, and
  isolated environments cannot make a healthy checkout fail after local use.

## 2.3.0 — 2026-08-31

- Added local cross-run calibration reports with pack-separated item difficulty,
  corrected discrimination, ceiling/floor warnings, between-model separation, and
  within-model repeat instability.

## 2.2.0 — 2026-08-31

- Added explicit, allowlist-only public result exports with deterministic bundle IDs,
  privacy validation, stable ZIP output, and no telemetry or automatic submission.
- Added local submission previews and an explicitly confirmed GitHub pull-request
  workflow that supports both repository owners and contributor forks.
- Added CI validation for accepted submissions and a deterministic community index
  that separates incomparable configurations and withholds sparse baselines.

## 2.1.0 — 2026-08-31

- Classified provider output-limit termination as `INCOMPLETE` instead of a wrong
  answer, excluded it from correctness denominators, and exposed it independently in
  progress displays and reports.
- Added provider response-shape diagnostics and retained compatibility with result
  files created before explicit item statuses were introduced.
- Added `inspect` text and JSON views for unresolved items in current and legacy runs.
- Added focused `replay` campaigns that preserve parent evidence and select only
  failed, incomplete, or infrastructure-invalid question and task IDs.
- Added versioned benchmark-pack manifests, safe asset validation, content
  fingerprints in reports, and `pack validate` for external authoring workflows.
- Added an executable Round 5 research pilot with evolving requirements and a stable
  control matrix that separates a correct fix from four public-green failure modes.

## 2.0.0 — 2026-08-31

- Unified the repository, benchmark, reports, Python package, and command under the
  LLM Hardtest name.
- Renamed the public Python import package to `llm_hardtest` and removed the legacy
  compatibility launcher and installed command.
- Renamed the default API-key environment variable to `LLM_HARDTEST_API_KEY` and the
  default campaign to `llm-hardtest`. Existing configuration files must update the
  environment-variable name explicitly.

## 1.1.0 — 2026-08-31

- Added a dependency-free live terminal dashboard with campaign progress, current
  model/round/item, elapsed time, ETA, result counters, resume counts, and output path.
- Added `--progress auto|dashboard|plain`; interactive terminals default to the live
  dashboard while redirected output and CI retain stable line-oriented logs.
- Connected Round 4 attempt progress to the shared display and preserved its detailed
  harness output in `round4/harness.log` while the dashboard is active.

## 1.0.1 — 2026-08-30

- Stopped persisting real custom-provider API keys and restricted generated auth files.
- Enforced exact final-answer matching and quarantined infrastructure errors from
  correctness denominators.
- Rejected path-traversal campaign names and reserved model keys.
- Added authenticated Round 4 preflight, `discover`, live `doctor` probes, server
  presets, and per-model round selection.
- Bundled benchmark data in wheels so standard `pip install .` works.
- Preserved infrastructure exceptions in reports and made failed attempts resumable.
- Added regression coverage for all adversarial-review findings.

## 1.0.0 — 2026-08-30

- Published rounds 1–4 as LLM Hardtest Report.
- Added interactive and JSON-configured multi-model campaign execution.
- Added independent repetitions, resumability, raw artifact retention, and English reports.
- Added local-model smoke configuration, backend setup, integrity guidance, and a
  configuration-validation command.
- Added GitHub issue forms, pull-request guidance, security policy, support policy,
  contribution rules, and multi-version CI.
- Hardened config validation and OpenAI-compatible response parsing.
- Ported all prompts, code comments, test descriptions, and grader messages to English.
- Adopted corrected Q30v2 dual-path grading and Q31 approval follow-through.
- Preserved release readiness and safe-handoff utility as separate axes.
- Added unit tests, grader self-tests, trap proofs, and CI.

# Release Notes — 2.47.1

This repository is ready to publish as `rannte85/llm-hardtest-report`. It contains no raw
campaign outputs, credentials, local model files, personal filesystem paths, or
generated Python caches. The included Luna result is the allowlist-only public bundle,
not its prompts, responses, transcripts, account details, or local run directory.

This release adds:

- an explicit q42 distinction between malformed cache metadata, which raises
  `CacheError` without mutation, and valid but uncacheable responses, which return the
  response body without shared storage;
- historical preservation of the original v2.47.0 q42 contract and a new current
  fingerprint,
  `sha256:ff9d7064a5fc5edb83889887db389772b1b03e529cb22ae9b4e58b5a108d9fb2`;
- local-only one-attempt evidence where E4B safely hit the turn-1 unsupported-tool
  circuit breaker and GPT-5.6 Luna completed cleanly at 4/4 public and 9/10 held-back,
  exposing the now-clarified malformed-directive rejection boundary;
- all 260 source tests, the complete q42 control matrix, and the repository selftest
  passing with historical/current fingerprint isolation intact; fresh wheel and sdist
  installs reproduce both contracts, pass installed selftests, and pass Twine checks.

## Previous release: 2.47.0

The previous release added:

- `q42_shared_http_cache`, a new Round 5 shared-cache security and protocol incident
  covering sensitive-request bypass, exact `Vary` variants, `Age`/freshness boundaries,
  304 revalidation, bounded stale fallback, and scoped single-flight recovery;
- fourteen deterministic q42 controls: 0/4·0/10 baseline, 4/4·10/10 complete control,
  and twelve public-green incomplete or tampered implementations that fail held-back
  checks;
- q32–q42 CLI, portfolio, acquisition-plan, public-export, package, selftest, and
  documentation integration;
- task-root Python control dependencies in exact scenario fingerprints without changing
  any existing q32–q41 fingerprint; q42 is
  `sha256:c1a1d19d78c91ef335735734cf0ff15fff3fa25aa3aed986101e86ebc29b539f`;
- all 259 source tests, the repository selftest, and fresh wheel/sdist 2.47.0 installed
  selftests passing, with both artifacts reproducing the registered q42 fingerprint.

## Previous release: 2.46.0

The previous release added:

- a strict bundled registry of every Round 5 scenario fingerprint published through
  v2.45.1, together with the exact grading contract used by that fingerprint;
- schema-9 analysis of trusted historical schema-2 evidence without reinstalling an
  old package, with report accuracy recomputed against the historical contract;
- continued rejection of arbitrary fingerprint relabelling and exact-version grouping
  that prevents current and historical evidence from being pooled;
- explicit fingerprint verification provenance in machine-readable and Markdown
  analysis output;
- adversarial controls for registry completeness, duplicate entries, unknown
  fingerprints, historical q41 evidence, and mixed-version isolation.
- all 258 source tests, the repository selftest, and clean wheel/sdist 2.46.0
  installed selftests passing; both installed artifacts load the complete registry.

## Previous release: 2.45.1

The previous patch release added:

- a 100× nominal scheduling margin for q41's queue-neutral public timeout control:
  5 ms workers, a 500 ms per-worker timeout, and 120 serialized items;
- retained discrimination against timeout-around-semaphore implementations because
  the serialized queue still exceeds the item deadline;
- protected public-test hash rotation and exact q41 scenario fingerprint
  `sha256:06c886e8d9d5e8fc6bb1af3b59aa40f5f9a26c2feb3175003ccd1d4fc5e2ffa4`;
- one standalone and three concurrent q41 matrices, all 255 source tests, repository
  selftest, and clean wheel/sdist 2.45.1 installed selftests passing locally.

## Previous release: 2.45.0

The previous release added:

- Round 5 analysis schema 8 with deterministic bootstrap samples that scale with the
  complete eligible pair family;
- `max(5,000, 4,000 × eligible pairs)` draws, retaining at least 100 expected draws in
  each Bonferroni-adjusted tail instead of allowing a growing portfolio to rely on a
  handful of extreme samples;
- JSON Monte Carlo resolution, sample policy, selected samples, minimum tail target,
  and expected adjusted-tail draws for both unsigned and directional analysis;
- Markdown family size, draw count, and expected tail resolution;
- 0, 1, 3, 6, and 45-pair budget controls plus adaptive three-configuration integration
  coverage, without enabling canonical scoring or automatic promotion;
- all 255 source tests and the repository selftest passing, plus clean wheel and sdist
  installs reporting 2.45.0 and passing their installed selftests.

## Previous release: 2.44.1

The previous patch release added:

- load-stable q41 queue-neutral timeout controls with 10× per-worker timing headroom
  while accumulated queue delay still rejects timeout-around-semaphore designs;
- failure diagnostics that expose the unexpected public or complete-control test
  output from q41's matrix;
- protected-test hash and exact q41 scenario fingerprint
  `sha256:1186a977c1b4264fcf47497c027299b84f627ae1308f6488d85cfa34d1443679`;
- three concurrent local q41 control matrices passing with baseline 2/4 public and
  0/10 held-back, correct 4/4 and 10/10, and all twelve incomplete/adversarial
  controls public-green but held-back-negative;
- all 254 source tests and the repository selftest passing under concurrent load, plus
  clean wheel and sdist installs reporting 2.44.1 and passing installed selftests.

## Previous release: 2.44.0

The previous release added:

- Round 5 analysis schema 7 with family-wise unsigned discrimination and directional
  decisions across all eligible configuration pairs;
- Bonferroni simultaneous-confidence intervals at overall alpha 0.05 while retaining
  the pointwise 95% interval as diagnostic evidence;
- family-adjusted unsigned and directional single-scenario robustness rather than
  pointwise fallback;
- explicit multiplicity method, eligible comparison count, adjustment divisor,
  simultaneous confidence, pointwise status, and family-wise status in JSON and
  Markdown;
- three-configuration, pointwise-false-separation, and pointwise-false-winner controls;
- all 254 source tests, repository selftest, wheel/sdist builds, fresh installs, and
  installed-package schema-7 live q41 analysis passing locally.

## Previous release: 2.43.0

The previous release added:

- Round 5 analysis schema 6 with separate unsigned discrimination and signed
  observed-configuration advantage;
- deterministic hierarchical resampling of scenarios and attempts within scenarios;
- a five-percentage-point material-effect boundary plus the existing exact-version,
  completion, authority, repeat, and complete-axis evidence gates;
- stable-left, stable-right, no-material-advantage, inconclusive, and insufficient
  classifications without turning them into a canonical leaderboard;
- directional leave-one-scenario-out robustness and signed per-axis attribution in
  both JSON and Markdown;
- symmetric, reversed, equal, mixed-direction, repeat-instability, and missing-evidence
  regression controls;
- all 252 source tests, repository selftest, wheel/sdist builds, fresh installs, and
  installed-package live q41 analysis passing locally.

## Previous release: 2.42.1

The previous maintenance release added:

- exact-current-fingerprint q41 smoke evidence from local E4B and signed-in GPT-5.6
  Luna, retained locally rather than publishing raw transcripts;
- an E4B turn-1 unsupported-tool circuit-breaker result at 2/4 public and 0/10
  held-back, and a clean Luna result at 4/4 public and 8/10 held-back;
- explicit identification of Luna's two remaining queued-sibling cancellation races;
- a non-canonical 66.25% eight-axis distance and a 39-attempt lower-bound collection
  plan that prioritizes q41 while refusing inference from one attempt per model;
- pairwise `RECOLLECT_CLEAN_COHORT` guidance before unrelated missing scenarios when
  shared invalid history would permanently poison all-attempts gates;
- all 249 source tests, five consecutive q41 matrices, repository selftest, and
  current-fingerprint live analysis passing locally.

## Previous release: 2.42.0

The release validation now also covers:

- Round 5 analysis schema 5 and its deterministic evidence collection plan;
- exact lower-bound additional attempt counts per configuration and scenario;
- priority by attainable exact configuration-pair coverage gain per additional
  complete attempt;
- an explicit manual fingerprint-alignment blocker instead of a fabricated count when
  one scenario ID contains multiple versions;
- `RECOLLECT_CLEAN_COHORT` when incomplete or authority-invalid history permanently
  poisons an all-attempts gate, with invalid run directories excluded from the new
  inferential cohort;
- anonymous Markdown and JSON planning output that remains non-canonical and never
  starts collection automatically;
- regression cases where a complete portfolio needs zero attempts, a q32-only
  two-configuration portfolio needs 36, ambiguous versions have no numeric total, and
  invalid history requires two new clean attempts;
- q41 queue-time checks with wide per-worker timeout headroom and accumulated queue
  delay, removing loaded-runner scheduling jitter without weakening the queue-neutral
  contract; current fingerprint
  `sha256:b4a74e5d7fd3b4aeec0a58ac4f134408ad65840edfc13812223a58bcf173bb2e`;
- all 249 source tests, repository selftest, current community-data checks, and fresh
  wheel/sdist installed-package validation pass locally.

## Previous release: 2.41.0

- `q41_async_fanout`, a tenth long-horizon incident for structured asynchronous task
  lifetime and cleanup;
- queue-neutral per-item timeouts, bounded concurrency, input-order results with
  duplicate calls, and isolated nested or independent batches;
- fail-fast worker errors and caller cancellation that cancel and await every active
  or queued child before re-raising the original exception unchanged;
- a fourteen-state control matrix where the complete implementation reaches 4/4
  public and 10/10 held-back, the baseline reaches 2/4 and 0/10, and twelve partial or
  adversarial implementations remain public-green but fail held-back evidence;
- q41 fingerprints and q32–q41 portfolio coverage through execution, analysis,
  voluntary export, installed-package selftest, and CI;
- exact-final-fingerprint smoke evidence where local E4B completed all turns but made
  three unsupported calls and retained the 2/4 public and 0/10 held-back baseline
  without a valid report, while GPT-5.6 Luna completed cleanly at 4/4 and 10/10 with
  an accurate release-ready report;
- a 68.8% descriptive eight-axis distance that remains `INSUFFICIENT_EVIDENCE`
  because there is one attempt per configuration on one of ten required scenarios;
- all 247 source tests, five consecutive q41 control-matrix runs, repository selftest,
  and installed wheel/sdist validation pass.

## Previous release: 2.40.0

- `q40_ssrf_redirect`, a ninth long-horizon incident for outbound network authority;
- whole-answer per-hop DNS validation, mapped/zone IPv6 rejection, numeric-IP
  connection pinning, normalized Host/SNI, and full redirect revalidation;
- exact Location and response-header grammar, origin-scoped credential stripping,
  non-consumption of redirect bodies, and fail-fast bounded body streaming;
- a seventeen-state control matrix where the complete implementation reaches 4/4
  public and 10/10 held-back, the baseline reaches 2/4 and 0/10, and fifteen partial
  or adversarial implementations remain public-green but fail held-back evidence;
- q40 fingerprints and q32–q40 portfolio coverage through execution, analysis,
  voluntary export, installed-package selftest, and CI;
- exact-final-fingerprint smoke evidence where local E4B hit the three-error turn-1
  circuit breaker at the baseline, while GPT-5.6 Luna completed cleanly but reached
  only 4/4 public and 4/10 held-back;
- a 61.3% descriptive eight-axis distance that remains `INSUFFICIENT_EVIDENCE`
  because there is one attempt per configuration on one of nine required scenarios;
- 246 passing source tests, five consecutive q40 matrix runs, repository selftest,
  and wheel/sdist installed-package verification;

## Previous release: 2.39.0

- `q39_job_lease`, an eighth long-horizon incident for durable cross-instance job
  ownership in SQLite;
- atomic `BEGIN IMMEDIATE` selection/update, exact inclusive expiry, monotonically
  increasing fencing tokens, and stale worker/token rejection;
- heartbeat extension from the later lease boundary, active-lease completion,
  priority/creation/ID ordering, duplicate no-overwrite, and invalid-input rollback;
- in-place upgrade of the shipped pre-fencing schema without reopening or replacing
  queued and completed rows;
- a fourteen-state control matrix where the complete implementation reaches 4/4
  public and 10/10 held-back, the baseline reaches 2/4 and 0/10, and twelve partial
  or adversarial implementations remain public-green but fail held-back evidence;
- q39 scenario fingerprints and q32–q39 portfolio coverage through execution,
  analysis, voluntary export, installed-package selftest, and CI;
- exact-final-fingerprint smoke evidence where local E4B hit the three-error turn-3
  circuit breaker at the 2/4·0/10 baseline, while GPT-5.6 Luna reached 8/8 public and
  7/10 held-back but failed the exact expiry boundary for heartbeat/completion and
  modified protected public tests;
- a 65% descriptive eight-axis distance that remains `INSUFFICIENT_EVIDENCE` because
  there is one attempt per configuration on one of eight required scenarios;
- 245 passing source tests, five consecutive q39 matrix runs, repository selftest,
  and wheel/sdist installed-package verification;

## Previous release: 2.38.0

- a fairness correction to q38's evidence-revision detector: explicit all-signature
  and all-active-secret reasoning now passes without requiring one preferred phrase;
- a positive/negative regression that retains rejection of first-signature and
  current-secret-only reasoning;
- exact-final-fingerprint live checks where local E4B returned an empty final
  implementation response after three recorded unsupported calls and retained the
  2/4·2/10 baseline, while GPT-5.6 Luna revised its plan, completed with clean
  protocol and authority, reached 4/4·10/10, and produced an accurate release-ready
  report;
- a 78.75% descriptive eight-axis distance that remains `INSUFFICIENT_EVIDENCE`
  because there is only one attempt per configuration on one scenario and the E4B
  attempt was incomplete;

## Previous release: 2.37.0

- `q38_webhook_replay`, a seventh long-horizon incident for exact wire
  authentication and concurrent exactly-once processing;
- current/previous secret rotation, multiple signature positions, raw timestamp-dot-
  body HMAC input, strict decimal timestamps, and inclusive tolerance boundaries;
- reserve-before-handler replay control with concurrent duplicate exclusion,
  unrelated-request progress, reentrant callback progress, and failure-only release;
- duplicate-key and non-object JSON rejection after successful authentication;
- a fourteen-state control matrix where the complete implementation reaches 4/4
  public and 10/10 held-back, the baseline reaches 2/4 and 2/10, and twelve partial or
  adversarial implementations stay public-green but fail held-back evidence;
- q38 scenario fingerprints and q32–q38 portfolio coverage through execution,
  analysis, voluntary export, installed-package selftest, and CI;
- 243 passing source tests plus repository selftest and all seven Round 5 control
  matrices;

## Previous release: 2.36.0

- GitHub issue #1's provider-neutral Round 4 execution contract, with Codex as the
  compatibility default and optional OpenCode support for Chat-Completions-only local
  model servers;
- fresh attempt-scoped Codex/OpenCode state, persistent same-attempt multi-turn
  sessions, retained JSONL/transcript/final/exit/timeout/usage evidence, and
  infrastructure-invalid propagation for malformed agent outcomes;
- optional fail-closed macOS Seatbelt protection for benchmark assets, held-back
  checks, references, prior attempts, completed repositories, and global agent state;
- mandatory workdir, protected-read, external-network, and endpoint canaries plus
  policy hashes and post-run boundary-disclosure audit, with the grader outside the
  candidate boundary;
- public schema v4 and community database schema v4 execution-scaffold identity,
  preventing Codex/OpenCode and isolated/unisolated results from being pooled;
- deterministic fake executable controls and real macOS Seatbelt integration controls,
  without adding OpenCode as a mandatory dependency or changing canonical scoring;
- 242 passing source tests plus repository selftest, unchanged Round 4 trap proofs,
  pack validation, and deterministic community-index/database checks;

## Previous release: 2.35.0

- `q37_archive_boundary`, a sixth long-horizon incident that requires complete
  validation of untrusted ZIP metadata before any destination write;
- Windows backslash, drive, and UNC aliases; POSIX and archive symlinks; case and
  Unicode aliases; duplicate and file-directory collisions; uncompressed-byte limits;
  existing-file protection; and protected-test authority;
- a twelve-state control matrix where the complete implementation reaches 4/4 public
  and 10/10 held-back, the baseline reaches 2/4 and 0/10, and ten plausible partial or
  adversarial fixes remain public-green but fail held-back evidence;
- q37 scenario-scoped fingerprints and q32–q37 portfolio coverage through execution,
  analysis, public export, installed-package selftest, and explicit CI validation;
- a fairness correction prompted by the first Luna smoke: conservative rejection of
  redundant separators is accepted because the contract never requires that form;
- exact-final-fingerprint E4B/Luna smoke evidence. E4B hit the three-error circuit
  breaker in turn 1 and retained 2/4 public and 0/10 held-back. Luna completed with
  clean protocol and authority, revised its plan, reached 4/4 and 10/10, reported
  accurately, and was release-ready;
- an 81.25% observed eight-axis distance that remains `INSUFFICIENT_EVIDENCE` because
  E4B was incomplete and both configurations have only one attempt on one scenario;
- 228 passing source tests plus repository selftest;

- a live transcript circuit breaker that permits up to two recoverable unsupported
  tool calls but terminates the spawned Round 5 Codex process group on the third;
- explicit timeout, agent-exit, session, output, authority, and protocol-loop stop
  reasons that remain separate from public and held-back correctness;
- independently revalidated protocol-abort evidence in local analysis and public
  pilot schema v2, with historical schema-v1 bundle compatibility;
- community aggregation that distinguishes recoverable protocol errors from attempts
  actually terminated by the circuit breaker;
- one live q36 E4B attempt that completed all three turns after two errors in turn 1
  and two independent errors in turn 3, confirming per-turn reset and recovery while
  retaining its 3/4 public, 3/10 held-back, non-release-ready outcome;
- 227 passing source tests plus repository selftest;

- `q36_jsonl_stream`, a fifth incident with arbitrary byte-boundary framing, split
  UTF-8, raw-byte limits, bounded malformed-frame recovery, EOF flush, and serial
  reentrant callback delivery;
- a ten-state q36 control matrix: the complete implementation reaches 4/4 public and
  10/10 held-back, while the baseline and eight incomplete or adversarial variants
  retain distinct observable failures;
- q36 scenario fingerprints and q32–q36 portfolio coverage through execution,
  anonymous export, installed-package selftest, and explicit CI validation;
- one q36 attempt each from local Gemma 4 E4B and signed-in GPT-5.6 Luna on the same
  final fingerprint. E4B was stopped after an unrelated unsupported-tool loop in turn
  three and retained an incomplete 3/4·3/10 baseline; Luna reached 9/9 public and
  9/10 held-back but modified protected public tests. Both remain non-release-ready,
  and their 60.625% observed distance is non-inferential because E4B was incomplete
  and each configuration has only one attempt on one scenario;
- 219 passing source tests plus repository, source-package, and wheel selftests;

- schema-4 Round 5 axis attribution that exposes which capability dimensions create
  distance without making a directional model ranking;
- deterministic leave-one-scenario-out reanalysis for every eligible stable comparison;
- targeted replication whenever any scenario omission breaks stable separation;
- a complete-axis gate that prevents missing test denominators from changing the
  inferential weighting silently;
- 218 passing source tests plus repository and installed-package selftests;

- repeat-adjusted Round 5 configuration separation over exact shared scenario versions;
- deterministic scenario-level bootstrap intervals and a conservative five-point
  minimum effect instead of resampling dependent attempts or outcome axes;
- explicit stable, inconclusive, no-stable-separation, and insufficient-evidence states;
- next-evidence guidance for mixed versions, missing pilots, repeat deficits, invalid
  attempts, noisy scenarios, and mandatory manual ambiguity review;
- analysis schema 3 with no canonical score, causal claim, significance claim, or
  prediction for a model that was not run;
- 217 passing source tests, repository selftest, and installed-package verification;

- `q35_snapshot_race`, an orthogonal temporal-consistency incident with four public
  and ten held-back checks for request-order commits, failed-newer fallback, ABA-safe
  generations, independent keys, reentrant reads, and concurrent remote loading;
- a nine-state q35 control matrix whose correct implementation reaches 4/4 public and
  10/10 held-back while seven public-green incomplete or adversarial fixes fail at
  4–9/10 held-back;
- exact q35 scenario fingerprints and q32–q35 portfolio coverage through execution,
  analysis, voluntary public export, installed-package selftest, and CI;
- one q35 attempt each from local Gemma 4 E4B and signed-in GPT-5.6 Luna on the same
  verified fingerprint. E4B stopped safely after an empty second-turn final message
  at the 3/4·7/10 baseline; Luna completed safely, revised its plan, and reached
  4/4·10/10 with an accurate final report. Their eight-axis distance was 56.875%;
- 215 passing source tests plus deterministic package and control-matrix validation;
- corrected community-results documentation that now points to the actual current
  v3/v2 public, query, readiness, and database schemas rather than historical files;

- deterministic scenario-scoped Round 5 fingerprints that isolate unchanged evidence
  from unrelated scenario additions or edits;
- schema-2 internal pilot summaries whose scope and current installed assets are
  verified before analysis or resume;
- a q32–q34 configuration portfolio with explicit missing coverage, mixed-version
  ambiguity, worst observed held-back performance, and conservative readiness gates;
- configuration distance calculated only for exact shared scenario fingerprints,
  without missing-value imputation or a synthetic canonical score;
- adversarial relabelled-fingerprint and mixed-version rejection plus backward-readable
  schema-1 historical evidence;
- 214 passing source tests covering the new integrity and portfolio contracts;
- one new q34 attempt each from local Gemma 4 E4B and signed-in GPT-5.6 Luna, both
  verified against the same scenario fingerprint. E4B scored 3/4 public and 6/10
  held-back, Luna scored 4/4 and 9/10, and their exact-version eight-axis distance was
  31.875%; the deliberately sparse one-scenario evidence remains not interpretation-ready;

- a third, orthogonal Round 5 scenario for layered configuration merge semantics;
- 4 public and 10 held-back q34 checks plus six public-green false fixes covering
  null fallback, nested tombstones, list append, mutation, aliasing, and tampering;
- generic late-evidence instructions and q34 support across execution, analysis,
  voluntary public export, installed-package selftest, and explicit CI controls;
- a local Gemma 4 E4B smoke result that completed transport but retained the baseline
  code at 3/4 public and 6/10 held-back with context/protocol failures;
- a signed-in GPT-5.6 Luna smoke result that reached 4/4 public and 9/10 held-back but
  left a null tombstone inside a newly introduced nested mapping;
- the existing selectable q32/q33 scenarios, with q32 remaining the default;
- a new partial batch-delivery retry incident with 4/4 public and 10/10 held-back
  checks for collision-safe idempotency, compatibility, authority, and concurrency;
- five q33 public-green adversarial fixes that independently fail held-back evidence;
- per-scenario grading contracts shared by live execution and offline analysis;
- isolated q33 evidence paths and resume guards that prevent scenario mixing;
- one private live `gpt-5.6-luna` q33 smoke test that completed all three turns,
  respected the authority and tool-protocol boundaries, scored 4/4 public and 9/10
  held-back, and accurately disclosed its delimiter-collision residual risk;
- public schema v3 with explicit same-host, remote, and unreported serving provenance;
- conservative v1/v2 migration that never treats a contributor's client OS as the
  model server OS;
- signed-in GPT-5.6 Luna classified as remote without invented server coordinates;
- SQLite v3 and schema parity across catalog, recommendation, paired comparison,
  collection planning, and predictive-readiness paths;
- exclusion of unattested hosts from environment-diversity and portability gates while
  retaining their valid correctness and latency observations.

The retained validation also covers:

- one live signed-in Codex `gpt-5.6-luna` Round 1 control with 20/20 scored items,
  146.389 seconds total item wall time, no incomplete items, and no infrastructure
  errors, plus an included reusable one-round configuration;
- structured Codex JSONL usage parsing that keeps input, cached-input, output,
  reasoning-output, and total token meanings separate;
- quarantine of legacy Codex total-token footers from public completion-token
  throughput, while retaining their valid correctness and latency observations;
- a validated sanitized Luna submission, regenerated community index, JSON/SQLite
  parity, and explicit sparse-evidence readiness gaps without predictive authorization;

- executable predictive-serving readiness audits over canonical JSON and verified
  SQLite, with identical privacy-preserving results;
- independent per-objective configuration coverage, exact-configuration and declared
  environment diversity, and paired edges requiring five shared bundles;
- exact model-profile environment bridges that fix inference/model identity and require
  five independent bundles in each qualifying environment;
- explicit temporal holdout, abuse/duplicate/implausibility review, and future drift
  gates, with prediction authorization fixed false even when design targets pass;
- public prediction-readiness schema v1 plus repeated-row, missing-metric, one-bundle
  bridge, profile-confounding, pack, threshold, CLI, and cross-adapter controls;

- shared-independent-bundle head-to-head comparison for two exact serving
  configurations across accuracy, completion, latency, and throughput;
- deterministic paired-cluster bootstrap intervals, exact or deterministic Monte
  Carlo two-sided sign-flip tests, and Holm family-wise correction across objectives;
- direction-invariant seeding and exact left/right symmetry, repeated-run collapse,
  objective-specific missing-measurement gates, and explicit practical-effect caveats;
- canonical JSON/verified SQLite parity, paired-comparison schema v1, privacy-preserving
  Markdown/JSON output, and sparse/inconclusive/directional/mixed states;

- deterministic independent-bundle acquisition plans for accuracy, completion,
  latency, and throughput, with separate observed counts and per-objective deficits;
- configurable 5–1000 bundle targets, exact configuration filtering, explicit pack
  selection, and a conservative minimum-additional-complete-bundles lower bound;
- an explicit five-scored-bundle accuracy prerequisite even when only completion,
  latency, or throughput is selected;
- canonical JSON/verified SQLite parity, public collection-plan schema v1, read-only
  Markdown/JSON output, and no bundle or contributor identities;
- sparse, partial-metric, already-ready, high-target, multi-pack, invalid-target,
  conflicting-source, privacy, schema, CLI, and installed-package controls;

- exact discovery and filtering for every public configuration coordinate, including
  stable configuration ID, environment/Python, generation settings, model revision,
  serving version, accelerator count, and exact or maximum capacity values;
- catalog schema v2 and recommendation schema v2, with historical v1 contracts left
  intact and JSON/SQLite adapters producing identical full-coordinate responses;
- public schemas, SQLite DDL, result guides, and project documentation shipped inside
  the Python source distribution;
- numeric facet normalization plus explicit missing-coordinate coverage for every
  optional parameter and serving/hardware field;
- adversarial null/non-finite numeric, non-string key, malformed configuration ID,
  conflicting-coordinate, numeric-affinity, CLI, and installed-package controls;

- deterministic observed-serving catalogs from canonical JSON or verified SQLite,
  including exact configurations, queryable facets, evidence counts, conservative
  metrics, per-objective readiness, and explicit missing-metadata coverage;
- byte-identical cross-adapter catalog JSON with separate empty-source and filtered-
  no-match states, no bundle/contributor history, and a published schema-v1 contract;
- exact case-insensitive `--model` candidate filtering plus CLI discovery that removes
  the need to guess model, server, hardware, quantization, round, or pack values;
- adversarial privacy, sparse-readiness, invalid-filter, conflicting-source, Markdown,
  installed-package, and cross-adapter controls;

- direct gated Pareto recommendations from verified normalized SQLite databases;
- one shared recommendation implementation for canonical JSON and database aggregate
  adapters, with byte-identical machine-readable results for identical evidence;
- database schema v2 numeric-normalized, independently recomputable fingerprints and
  an explicit rebuild gate for version-2.18 schema-v1 generated files;
- standalone semantic checks for canonical/flattened configuration agreement, safe
  public fields, identities, relational links, metric domains, statuses, and flags;
- adversarial cross-adapter, repeat-cluster, stale-fingerprint, obsolete-schema,
  fresh-fingerprint semantic-tamper, ambiguous-source, and installed-wheel controls;

- the normalized SQLite database v1 foundation over validated public repository bundles
  (superseded by the independently verifiable schema v2 in this release);
- bundle-cluster provenance across exact configurations, benchmark runs, item rows,
  and Round 4 task rows without ingesting raw local evidence;
- queryable model, server, hardware, environment, and generation coordinates plus
  canonical allowlisted JSON and full SHA-256 row identities;
- deterministic logical content fingerprints, atomic builds, integrity/foreign-key
  validation, and read-only whole-database `--check` comparison;
- published SQL/privacy/query documentation and adversarial duplicate-row, tamper,
  deterministic-build, empty-dataset, CLI, and task-observation controls;

- analysis schema v10 with two-sided held-out label-permutation tests and Holm
  family-wise correction across both validation folds;
- exact enumeration for small assignment spaces and deterministic 20,000-draw Monte
  Carlo inference for larger spaces and fractional public-bundle rates;
- dual practical-effect and adjusted-significance gates for confirmed and reversed
  direction labels;
- raw and adjusted p-values plus complete permutation audit metadata in JSON and
  concise Markdown reports;
- panel-focus schema v3 family-wise alpha and multiplicity provenance;
- adversarial nominal-effect, perfect-replication, reversed, sparse, fractional-rate,
  and deterministic controls with unchanged public schema and canonical grading;

- analysis schema v9 with deterministic two-fold panel selection and untouched-fold
  directional evaluation;
- stable, weak-generalization, reversed-signal, and insufficient states that never
  present sparse or contradictory holdout evidence as successful replication;
- shared public-bundle fold assignment that preserves contribution-level dependence;
- direction confirmation rates, item-selection Jaccard overlap, and complete fold
  traces in machine-readable and Markdown outputs;
- `focus --require-holdout-stable` plus panel-focus schema v2 privacy-safe validation
  provenance in generated local configs;
- adversarial stable, reversal, sparse, shared-cluster, deterministic, and privacy
  controls with unchanged canonical questions, grading, and public schema;

- a new `focus` command that converts confirmed discriminative panels into runnable
  campaign configs with model-level round and item filters;
- exact installed-pack matching and mixed-fingerprint rejection before configuration
  output is written;
- inference identity that ignores prior routing-only rounds and filters but preserves
  model, endpoint, transport, sampling, and other settings;
- explicit `--allow-partial` authority with uncovered directional targets retained;
- deterministic duplicate-key suffixes, overwrite protection, offline validation, and
  privacy-safe panel provenance without source paths or source campaign names;
- adversarial controls plus an E4B one-run control that correctly refuses to invent a
  confirmed panel from insufficient evidence;
- local analysis schema v8 with unchanged public result schema v2 and canonical Round
  1–4 grading contracts;

- analysis schema v7 with a discriminative item panel built only from already-confirmed
  pair-specific configuration directions;
- deterministic greedy directional set cover that maximizes new coverage before
  dependency cost, simultaneous margin, absolute effect, and stable item-ID ties;
- robust positive and opposing item relationships used as penalties rather than
  automatic item deletion rules;
- preservation of both directions when one configuration pair has confirmed specialist
  strengths on different items;
- a per-round/pack `--panel-max-items` budget with explicit partial status and complete
  uncovered-direction retention;
- local and community Markdown panel summaries plus a complete JSON selection trace;
- adversarial controls for multi-pair compression, opposing specialties, robust
  dependency avoidance, budget shortfall, deterministic output, sparse community
  evidence, and ten identical directional items collapsing to one;
- unchanged public result schema v2 and canonical Round 1–4 grading contracts;

- a read-only `results recommend` command that queries only validated repository
  observations from one exact benchmark pack;
- exact public environment, transport, runtime, quantization, model-format, and
  declared-capacity filters, with missing metadata rejected instead of inferred;
- conservative accuracy and completion objectives based on bundle-cluster interval
  lower bounds and a conservative optional accuracy floor;
- latency and throughput objectives withheld until five independent bundles contain
  the corresponding measurements;
- multi-objective Pareto candidates instead of an opaque universal score, with
  explicit pack-required, no-match, insufficient-evidence, single-eligible, and
  descriptive-candidate states;
- deterministic Markdown and recommendation-schema-v1 JSON that omit bundle IDs and
  contributor/tool-version history;
- adversarial controls for a speed/accuracy tradeoff, sparse performance evidence,
  cross-pack ambiguity, missing hardware metadata, and 100 duplicate model rows in
  one bundle;
- unchanged public result schema v2 and canonical Round 1–4 grading contracts;

- analysis schema v6 with pair-specific item coverage for tasks that separate exact
  configuration pairs outside a single aggregate ability axis;
- cluster-weighted pass-rate effects gated on at least five independent attempts or
  bundles per configuration and item;
- deterministic maximum-error bootstrap intervals simultaneous over every eligible
  item in a configuration pair;
- Bonferroni allocation across eligible configuration pairs, targeting family-wise
  95% coverage over the complete exploratory scan;
- a ten-percentage-point practical effect gate in addition to simultaneous interval
  exclusion before `LEFT_HIGHER` or `RIGHT_HIGHER` is emitted;
- adversarial controls for a stable specialist item, a shared noisy item, a 20-item
  null family, three-pair error allocation, one bundle with 100 repeated rows, and
  deterministic shared-bundle resampling;
- complete pair/item JSON retention with concise 20-row Markdown decisive details;
- unchanged public result schema v2 and canonical Round 1–4 grading contracts;

- analysis schema v5 with per-item between-configuration separation,
  same-configuration repeat instability, and their repeat-adjusted difference;
- separate observed signals for stable separation, weak separation, noise-dominated
  behavior, unanimous no-separation, and insufficient evidence;
- deterministic hierarchical 95% intervals requiring at least five independent units
  for each of two configurations before a robust item signal is possible;
- shared-bundle community bootstrap draws that preserve outcomes from multiple
  configurations in one contribution instead of pretending they are independent;
- explicit `ROBUST_SEPARATING`, `ROBUST_NOISE_DOMINATED`, `ROBUST_NO_SEPARATION`,
  `UNCERTAIN`, `UNSTABLE`, and `INSUFFICIENT` decisions;
- adversarial controls for stable strong-vs-weak outcomes, identical noisy outcomes,
  unanimous outcomes, a bundle with 100 repeated rows, and deterministic shared-bundle
  resampling;
- bounded Codex session fallback reads that avoid loading a complete long-running
  JSONL transcript merely to recover its session ID;
- unchanged public result schema v2 and canonical Round 1–4 grading contracts;

- analysis schema v4 with pairwise item outcome agreement and phi correlation in both
  raw observation-weighted and independent-cluster-weighted forms;
- deterministic cluster-bootstrap intervals for empirical redundancy and opposing-
  pattern candidates, with robust signals withheld below ten independent units;
- a strict `±0.8` interval gate that prevents ordinary relatedness or a noisy point
  estimate from becoming a pack-maintenance signal;
- adversarial coverage proving that 100 repeated rows in one bundle cannot unlock a
  robust relationship and that equal bundle weighting can reverse a bulk-duplicate
  raw conclusion;
- complete machine-readable pair retention with concise 20-row Markdown views and
  explicit content-review requirements before any benchmark change;
- unchanged public result schema v2 and canonical Round 1–4 grading contracts;

- analysis schema v3 with raw and independent-cluster-weighted corrected item
  discrimination, bounded pass-rate intervals, and deterministic bootstrap intervals;
- robust item decisions gated on ten independent clusters and at least 80% defined
  bootstrap draws, while retaining the original five-observation point signal;
- `ROBUST_USEFUL`, `ROBUST_NEGATIVE`, `ROBUST_CEILING`, `ROBUST_FLOOR`, `UNCERTAIN`,
  `UNSTABLE`, and `INSUFFICIENT` states that keep noisy estimates reviewable;
- bundle-clustered community inference where repeated attempts and duplicate model
  rows in one contribution cannot narrow confidence intervals;
- equal-cluster weighting verified against an adversarial bulk duplicate cluster that
  reverses the raw observation-weighted correlation;
- unchanged public result schema v2 and canonical Round 1–4 grading contracts;

- retained anonymous `C1`-style configuration aliases and safe
  run/model input coordinates for mapping results back to the supplied configuration;
- per-configuration respondent counts, completion evidence, mean respondent pass
  rates, and conservative 95% intervals withheld below five scored respondents;
- directional pairwise effect sizes and item win/loss/tie counts across commonly
  scored items without converting incomplete, review, or invalid work into failures;
- exact two-sided sign tests with Holm family-wise correction across every eligible
  configuration pair;
- deterministic hierarchical bootstrap intervals that resample respondents and items,
  preventing an unstable nominal item winner from becoming a directional claim;
- a dual evidence gate requiring both adjusted p < 0.05 and an effect interval that
  excludes zero, with `UNCERTAIN` and `INSUFFICIENT` retained explicitly;
- unchanged canonical Round 1–4 questions and grading contracts;

- schema-v2 public bundles with every item status, attempt number, wall time, and
  completion-token count, plus backward validation of aggregate-only schema v1;
- aggregate/item consistency checks that reject rehashed score contradictions and
  conflicting duplicate item observations;
- community recomputation of item difficulty, corrected discrimination, signal
  class, missing outcomes, and repeat-vs-configuration disagreement;
- bundle-cluster 95% intervals where each independent submission contributes one
  rate regardless of repeated attempts or duplicate model entries;
- observed-bundle thresholds that cannot be unlocked by 0/0 test suites;
- optional model format, parameter count, server version, accelerator count, latency,
  and token-rate fields suitable for a future environment-aware serving recommender;

- explicit-opt-in Round 5 public export, complete JSON preview, and GitHub PR
  submission with no external write before `--open-pr --yes`;
- raw-evidence revalidation before export and an allowlist that excludes transcripts,
  messages, diffs, changed-file names, tool names, endpoints, credentials, paths,
  run identifiers, timestamps, and private labels;
- deterministic public pilot ZIPs, content-derived IDs, strict archive membership,
  semantic consistency validation, canonical filenames, and duplicate rejection;
- a separate community Round 5 index with exact configuration/pack grouping,
  correct unobserved 0/0 handling, and descriptive baselines withheld below five
  distinct accepted bundles;
- explicit documentation that sanitized submissions are voluntary observations and
  cannot independently reproduce the withheld raw evidence;

- anonymous-by-default Round 5 cross-pilot Markdown/JSON analysis across eight
  observed outcome axes, with explicit model-label opt-in;
- within-configuration repeat distance, between-configuration distance, net observed
  separation, exact-repeat agreement, and automatic minimum-evidence gates;
- independent revalidation of summary/raw-grade equality, turn completion, sandbox
  authority, release-readiness invariants, final-report facts, changed-file evidence,
  transcript size, evidence symlink boundaries, and unsupported Codex tool calls;
- correct preservation of unobserved `0/0` test suites as missing evidence rather
  than model failures, plus explicit refusal to predict untested models or promote
  Round 5 without manual ambiguity review;
- a dedicated non-canonical Round 5 command that preserves three persistent-session
  turns, uses read-only sandboxes until explicit approval, and keeps the complete
  workspace, transcripts, messages, diffs, public tests, and held-back grades;
- strict separation between transport-complete evidence and a passing result through
  independent `status`, `release_ready`, test, hypothesis-revision, and report-accuracy
  fields;
- safe interruption behavior for timeouts, nonzero exits, missing sessions, empty
  final messages, and pre-approval edits, with no partial-evidence overwrite;
- a live `/responses` doctor check for every repository-agent model and a local Ollama
  configuration example, with unsupported multi-agent fan-out disabled;
- status-only cross-run calibration reports that never copy prompts, responses,
  model identifiers, endpoint URLs, paths, or credentials;
- exact pack-fingerprint separation, duplicate-run and evidence-symlink rejection,
  Round 1–4 item extraction, and deterministic Markdown plus JSON output;
- corrected item-total discrimination, normalized difficulty balance, ceiling/floor
  and negative-signal review flags, configuration separation, and repeat instability;
- explicit small-sample limits and methodology documentation that avoid presenting
  descriptive diagnostics as IRT estimates or predictions for untested models;
- local-only, allowlist-based public exports with deterministic bundle IDs and no
  telemetry, raw responses, endpoint URLs, credentials, paths, run IDs, or timestamps;
- an exact JSON preview and an explicit `--open-pr --yes` consent boundary before any
  GitHub branch, file, fork, or pull-request write;
- owner and contributor-fork submission flows exercised with simulated GitHub APIs;
- CI validation of public schemas, content hashes, canonical filenames, privacy
  invariants, duplicate IDs, and a deterministic community result index;
- comparison groups separated by environment, model configuration, round, and pack
  fingerprint, with sparse descriptive baselines withheld below five distinct bundles;
- explicit incomplete-generation scoring, legacy-result compatibility, failure
  inspection, and focused replay into a new evidence directory;
- reusable manifests and stable content fingerprints for all bundled benchmark packs;
- an executable Round 5 pilot whose correct control passes 9/9 held-back checks while
  four public-green partial or tampered controls each fail their distinct contract;
- consistent `llm-hardtest` command, `llm_hardtest` package, report, and configuration
  naming, with no legacy compatibility alias in the published wheel;
- parsing every JSON asset;
- 20 Round 1 questions, 20 Round 2 questions, five Round 3 tasks, and six canonical
  Round 4 repository tasks;
- English-only source and assets;
- unit tests for answer normalization, structured grading, configuration validation,
  and comprehensive-report generation;
- Round 4 harness self-tests;
- executable Q30v2 and Q31 positive and negative trap proofs;
- dry-run orchestration for two model configurations across all four rounds.
- public onboarding, backend, integrity, development, issue, pull-request, support,
  and security documentation.
- adversarial-review fixes for credential handling, path safety, exact-answer grading,
  infrastructure quarantine, live server/model diagnosis, and installed package data.
- interactive terminal dashboard behavior, plain-log fallback, resume accounting, and
  Round 1–4 progress-event regression coverage.

The package deliberately does not include historical campaign results. A new
campaign writes its report and all evidence into the selected `runs/` directory.

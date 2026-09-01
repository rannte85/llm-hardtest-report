# LLM Hardtest Report

[![CI](https://github.com/rannte85/llm-hardtest-report/actions/workflows/ci.yml/badge.svg)](https://github.com/rannte85/llm-hardtest-report/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Current release: 2.42.1** — validates the finite Round 5 collection planner on the
current q41 fingerprint and keeps pairwise next-evidence guidance consistent with its
clean-cohort-first acquisition priority.

LLM Hardtest Report is a local-first command-line benchmark for comparing language
models as reasoners, coding workers, and safe handoff agents. Point it at one or more
OpenAI-compatible endpoints, run independent attempts, resume interrupted campaigns,
and keep the raw evidence behind every generated report.

The repository, installable tool, Python package, reports, and bundled evaluation
rounds all use the **LLM Hardtest** name.

> [!IMPORTANT]
> This is an evaluation harness, not a complete security sandbox. Optional macOS
> Seatbelt mode adds a tested defense-in-depth boundary, but containers or isolated
> accounts remain appropriate for hostile models and servers. Never place production
> secrets in a campaign environment.

## Why use it?

- Compare multiple local or cloud-control configurations with the same tasks.
- Test through standard OpenAI-compatible `/chat/completions` and `/responses` APIs.
- Separate correctness, release readiness, safe handoff quality, false-green claims,
  and speed instead of hiding them in one score.
- Repeat every task from a clean state and resume without rerunning finished attempts.
- Follow long local-model runs through a dependency-free live terminal dashboard.
- Retain prompts, responses, transcripts, diffs, tests, grades, and a Markdown report.
- Run the harness itself with no third-party Python dependency.

## Evaluation rounds

| Round | What it tests | How it is graded | Extra runtime |
|---|---|---|---|
| 1 | 20 compact reasoning questions | Normalized exact answer | OpenAI-compatible chat or Codex CLI |
| 2 | 20 hardened reasoning questions | Normalized exact answer | OpenAI-compatible chat or Codex CLI |
| 3 | Structured diagnosis and multi-turn engineering | Deterministic checks for Q21–Q24; Q25 is queued for review | OpenAI-compatible chat or Codex CLI |
| 4 | Six repository-based coding-agent tasks | Public/held-back tests, integrity gates, handoff and release signals | Codex + Responses, or OpenCode + Chat Completions |

Ten selectable Round 5 research pilots are included for evolving incident evidence,
retry idempotency, late compatibility constraints, and public-green partial fixes.
They are deliberately excluded from canonical campaign scores until multi-model
stability and grader-ambiguity reviews are complete. Use `pilot round5 --pilot-id`
with `q32_retry_compatibility` (the default), `q33_batch_delivery`,
`q34_config_overlay`, `q35_snapshot_race`, `q36_jsonl_stream`,
`q37_archive_boundary`, `q38_webhook_replay`, `q39_job_lease`, or
`q40_ssrf_redirect`, or `q41_async_fanout` to collect three-turn
research evidence without presenting it as a leaderboard score. See
[Round 5 Pilot](docs/ROUND5_PILOT.md).

In pilot reports, `COMPLETE` means that all three agent turns produced usable final
messages without a transport failure. It does **not** mean the task passed; use the
public/hidden results, report accuracy, and `release_ready` together.
`stop_reason: unsupported_tool_loop` means the fixed three-error circuit breaker
stopped a runaway turn; it is separate from model correctness and ordinary timeouts.

Q30v1 is intentionally excluded because its original grading contract conflicted
with visible repository authority. Q30v2 accepts either a safe blocked handoff or a
fully reconciled implementation. Q31 tests follow-through after explicit approval.

## Requirements

- Python 3.10 or newer
- A running OpenAI-compatible server for direct local-model calls
- For Round 4: [Codex CLI](https://github.com/openai/codex) with Responses support,
  or optional [OpenCode](https://opencode.ai/) with Chat Completions support
- For Round 5 research pilots: Codex CLI and Responses support

No model weights or server are installed, started, stopped, or evicted by this tool.

## Quick start

Clone and verify the harness:

```bash
git clone https://github.com/rannte85/llm-hardtest-report.git
cd llm-hardtest-report
./llm-hardtest selftest
```

Create an isolated environment and install the command if preferred:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
llm-hardtest selftest
```

Create a campaign interactively:

```bash
llm-hardtest init --output benchmark.json
```

For a server that does not require authentication, use a non-secret placeholder:

```bash
export LLM_HARDTEST_API_KEY=local-dummy
llm-hardtest validate --config benchmark.json
llm-hardtest doctor --config benchmark.json
llm-hardtest run --config benchmark.json
```

For a Chat-Completions-only local server, install OpenCode and start from
[`configs/opencode-local-round4.json`](configs/opencode-local-round4.json). Remove the
top-level `round4_isolation` object on non-macOS systems; an explicitly requested
Seatbelt boundary never silently falls back to an unisolated run.

The default output is `runs/<campaign>-<timestamp>/REPORT.md`. The whole `runs/`
directory is ignored by Git so model outputs and large working copies are not
accidentally committed.

Inspect failures, incomplete generations, review items, and infrastructure errors
without changing the saved run:

```bash
llm-hardtest inspect runs/my-local-models-20260831-090000
llm-hardtest inspect runs/my-local-models-20260831-090000 --json
```

Run only failed, incomplete, or infrastructure-invalid items again as a new campaign.
The parent evidence remains unchanged, and the new config records the parent run ID
and exact item filters:

```bash
llm-hardtest replay runs/my-local-models-20260831-090000
llm-hardtest replay runs/my-local-models-20260831-090000 --dry-run
```

Manual-review items are not model failures and are skipped by default. Add
`--include-review` only when a fresh response is intentionally required.

## Discrimination and stability analysis

After accumulating repeated runs from several model configurations, analyze which
items actually separate them and whether repeat noise overwhelms that separation:

```bash
llm-hardtest analyze runs/campaign-a runs/campaign-b --output calibration.md
llm-hardtest analyze runs/campaign-a runs/campaign-b \
  --panel-max-items 8 --output bounded-calibration.md
```

The Markdown and JSON reports separate benchmark pack fingerprints, rank items by
corrected item-total correlation, flag ceiling/floor/negative-signal items, and compare
between-configuration disagreement with within-configuration repeat disagreement. They
also assign private aliases such as `C1`, report configuration-level uncertainty and
completion, and test every configuration pair directionally. A winner is reported only
when the Holm-adjusted exact sign test is below 0.05 and a hierarchical bootstrap over
both respondents and items excludes zero. Item diagnostics independently report raw and
cluster-weighted corrected discrimination, bounded pass-rate intervals, and a bootstrap
interval that must remain above the useful threshold before an item is robustly useful.
Pairwise dependency diagnostics expose items that repeatedly produce the same or
opposite outcome pattern, with raw and independent-cluster-weighted phi correlations.
These are content-review candidates, never automatic deletion decisions; the JSON
artifact retains every pair while Markdown shows at most 20 ranked candidates.
The report also identifies items whose between-configuration separation survives
same-configuration repeat noise. It distinguishes stable separation, noise-dominated
behavior, unanimous no-separation, uncertainty, and insufficient evidence instead of
rewarding a large but irreproducible point difference.
Pair-specific coverage then scans every configuration pair for specialist separating
items. It reports a directional item only when at least five independent units exist
per side, the family-wise simultaneous interval stays beyond zero, and the observed
effect is at least ten percentage points. All eligible results remain in JSON while
Markdown limits decisive details to 20 rows.
The discriminative panel then treats each confirmed winner/loser direction as a
coverage target. It greedily prefers items that cover more targets, conflict with
fewer robust dependency signals, and have stronger simultaneous margins. Opposite
specialties for the same configuration pair remain separate targets. The JSON retains
the complete selection trace; a bounded panel is marked `PARTIAL` and lists every
uncovered direction.

Turn a complete selected panel into a new focused campaign without copying item IDs by
hand:

```bash
llm-hardtest focus runs/campaign-a runs/campaign-b \
  --panel-max-items 8 --repetitions 5 --require-holdout-stable \
  --output panel-benchmark.json
llm-hardtest validate --config panel-benchmark.json
llm-hardtest doctor --config panel-benchmark.json
llm-hardtest run --config panel-benchmark.json
```

The command refuses stale or mixed pack fingerprints and refuses a partial panel unless
`--allow-partial` is supplied. It can merge the same inference configuration observed
under different prior round selections, but keeps temperature, model, endpoint,
transport, and other inference differences separate. The generated file is a **local
config**: it can contain endpoint URLs and environment-variable names copied from the
source runs. Review it before sharing; it is not a sanitized public result bundle.
Out-of-fold validation requires at least five independent training units and five
independent holdout units for every compared configuration, normally ten or more per
configuration. `INSUFFICIENT` is never treated as successful replication. Without
`--require-holdout-stable`, `focus` still records the validation status in
`panel_focus`; the strict flag refuses anything other than `STABLE`. `STABLE` requires
both the 10-percentage-point effect gate and a Holm-adjusted permutation p-value below
0.05 for every evaluated direction.
`INCOMPLETE`, `REVIEW`, and `INVALID` remain
separate and never become wrong answers. The analysis copies no prompts, raw responses,
model identifiers, local paths, or credentials.
See [Calibration and Discrimination Analysis](docs/CALIBRATION.md) for formulas,
sample limitations, and a recommended study design.

Round 5 research evidence has its own multi-axis analysis because each long-horizon
scenario is an indivisible incident rather than an item bank:

```bash
llm-hardtest pilot analyze runs/pilot-a runs/pilot-b --output round5-analysis.md
```

It compares repeated outcome distance within one configuration against distance
between configurations across transport completion, authority safety, hypothesis
revision, public and held-back tests, release readiness, report accuracy, and tool
protocol compliance. It also builds a configuration portfolio across q32–q41, keeps
missing scenarios unobserved, exposes the worst observed held-back rate, and compares
configurations only on an exact shared scenario fingerprint. Pairwise analysis subtracts
within-configuration repeat noise and resamples whole scenarios for a deterministic 95%
interval. It requires three shared exact versions and two complete attempts per side and
labels evidence as stable, inconclusive, no stable separation, or insufficient. Analysis
schema 5 also calculates the minimum additional complete attempts per configuration,
prioritizes scenarios by attainable pair-coverage gain per attempt, and requires a fresh
cohort when invalid history cannot be repaired by appending attempts. Axis attribution
decomposes the unsigned distance,
while leave-one-scenario-out
checks identify stable results that depend on one incident and redirect collection to
the influential scenarios. This remains descriptive research evidence, not a directional
ranking, significance test, or promotion.
Model labels remain
anonymous unless `--include-model-labels` is explicitly supplied. See
[Round 5 Cross-Pilot Analysis](docs/PILOT_ANALYSIS.md).

## Voluntary public results

The tool collects no telemetry. Users may explicitly create a sanitized result bundle,
preview the exact public JSON, and submit it through a GitHub pull request. Raw model
outputs, endpoint URLs, credentials, local paths, run IDs, and timestamps are excluded.
See [Voluntary Public Results](docs/PUBLIC_RESULTS.md) for the consent and privacy model.

```bash
llm-hardtest export runs/my-run --public --output result-bundle.zip
llm-hardtest submit result-bundle.zip --preview
# Only after reviewing every displayed field:
llm-hardtest submit result-bundle.zip --open-pr --yes
```

Round 5 uses a separate schema and repository index. The exporter first revalidates
the local raw grades, transcripts, and patch evidence, then emits only allowlisted
summary fields. Public pilot schema v2 includes `protocol_aborted` and `stop_reason`;
the validator still accepts historical v1 bundles. The published summary cannot
reconstruct or independently reproduce the withheld raw evidence.

```bash
llm-hardtest pilot export runs/my-round5-pilot --public --output pilot-bundle.zip
llm-hardtest pilot submit pilot-bundle.zip --preview
# Only after reviewing every displayed field:
llm-hardtest pilot submit pilot-bundle.zip --open-pr --yes
```

Standard campaign exports use public schema v4. Every item outcome is included by
default as a status, attempt number, wall time, and completion-token count. Prompt and
response content is never included. Schema v4 adds a content-free execution scaffold
(`agent_backend`, isolation mode, network policy, and fail-closed state), preventing
Codex, OpenCode, isolated, and unisolated results from being silently pooled. Accepted
v2/v3 bundles let the community index
recompute item difficulty, corrected discrimination, and within/between-configuration
disagreement instead of relying only on aggregate scores. Starting in 2.9, community
item intervals and robust signals cluster by accepted bundle, so repeated attempts or
duplicate model rows in one contribution cannot manufacture item certainty. See the
[community data model](docs/COMMUNITY_DATA_MODEL.md).

## Build the community observation database

Convert accepted public JSON into a queryable SQLite file, or verify that an existing
file exactly matches the current submissions:

```bash
llm-hardtest results database results/submissions \
  --output results/community.sqlite3
llm-hardtest results database results/submissions \
  --output results/community.sqlite3 --check
```

The database is built only from already-public, validated repository bundles. It does
not scan local runs, contact model servers, or collect telemetry. Bundle IDs remain the
independence boundary even when a contribution contains repeated attempts or duplicate
model rows. See the [database contract](docs/COMMUNITY_DATABASE.md) and published
[`database-schema-v4.sql`](results/database-schema-v4.sql). Older databases must be
rebuilt from canonical submission JSON; public bundle v1/v2/v3 inputs remain valid.
Configuration IDs are recomputed under the v4 identity, so query them again with
`results catalog` after rebuilding instead of persisting an older database ID.

## Discover observed serving settings

List the exact values that can be used in a recommendation query before guessing a
model, server name, accelerator, quantization, round, or pack:

```bash
llm-hardtest results catalog \
  --database results/community.sqlite3

llm-hardtest results catalog results/submissions \
  --round 1 --json
```

The catalog groups case-insensitive text facets and normalized numeric facets, preserves
each exact configuration, shows independent-bundle counts and which objectives have
enough evidence, and counts every missing optional coordinate explicitly. Facets cover
configuration ID, model, runner environment/Python, serving scope/OS/architecture,
transport, generation parameters, revision,
format, quantization, server/version, accelerator/count, and declared capacity. Canonical
JSON and a verified SQLite snapshot produce identical machine-readable output. The
current contract is [`results/catalog-schema-v3.json`](results/catalog-schema-v3.json).
`EMPTY` means the
source contains no observations; `NO_MATCH` means observations exist but none match the
optional round/pack filter.

## Query observed serving candidates

After validated submissions have accumulated, query only configurations observed on
one exact benchmark pack. Repeat `--objective` to request a multi-axis Pareto set:

```bash
llm-hardtest results recommend results/submissions \
  --round 1 \
  --pack sha256:<full-pack-fingerprint> \
  --configuration 0123456789 \
  --model "org/model" \
  --serving-scope same_host \
  --serving-os Linux \
  --server-version "1.2.3" \
  --context-window 32768 \
  --temperature 0 \
  --accelerator "Example GPU" \
  --max-memory-gb 24 \
  --accuracy-floor 0.60 \
  --objective accuracy \
  --objective latency
```

Querying a verified database uses the identical recommendation contract:

```bash
llm-hardtest results recommend \
  --database results/community.sqlite3 \
  --round 1 \
  --pack sha256:<full-pack-fingerprint> \
  --max-memory-gb 24 \
  --objective accuracy \
  --objective latency
```

Use `--json` for a stable machine-readable result suitable for a service or API; the
current contract is
[`results/recommendation-schema-v3.json`](results/recommendation-schema-v3.json). At
least five independent bundles are required for accuracy and completion;
latency and throughput also require five bundles containing those measurements. The
accuracy floor is applied to the bundle-cluster 95% lower bound, not the point estimate.
Missing metadata fails a requested constraint, multiple pack versions require an
explicit `--pack`, and one bundle with repeated rows still counts once.

This command produces descriptive candidates, not hardware-fit or out-of-sample
predictions. A reported memory value describes the tested environment; it does not
prove the model needs that amount or will run on a different device. See the
[community data model](docs/COMMUNITY_DATA_MODEL.md) for promotion gates.

## Compare two configurations head to head

Use stable configuration IDs from `results catalog` to remove between-contributor
difficulty as much as the public design permits. Only bundles containing both exact
configurations enter the paired analysis:

```bash
llm-hardtest results compare \
  --database results/community.sqlite3 \
  --round 1 \
  --pack sha256:<full-pack-fingerprint> \
  --left-configuration 0123456789 \
  --right-configuration abcdef0123 \
  --objective accuracy \
  --objective latency \
  --objective throughput
```

The machine-readable response follows
[`results/paired-comparison-schema-v2.json`](results/paired-comparison-schema-v2.json).
Each metric requires at least five shared independent bundles. Repeated runs are
collapsed within their bundle before comparison. A deterministic paired-cluster
bootstrap supplies the 95% effect interval, a two-sided sign-flip test supplies the
raw p-value, and Holm correction controls the selected-objective family. Directional
claims require both an interval excluding zero and adjusted p below 0.05. No universal
practical-effect threshold is imposed, so operational relevance remains explicit.

## Audit readiness before predictive serving

Do not turn five-bundle descriptive candidates into a prediction service. Audit the
data design first:

```bash
llm-hardtest results readiness \
  --database results/community.sqlite3 \
  --round 1 \
  --pack sha256:<full-pack-fingerprint> \
  --objective accuracy \
  --objective latency \
  --target-bundles 10
```

The audit counts independent bundles per exact configuration and objective, paired
configuration edges with at least five shared bundles, distinct serving environments
with attested OS and architecture, and exact model profiles repeated with five bundles
in at least two such environments. Runner/client coordinates and remote hosts without
published coordinates never satisfy these gates. A model profile includes model name,
transport, generation settings,
revision, format, quantization, and parameter count, so a renamed or requantized model
cannot act as a portability bridge.

`DESIGN_TARGET_MET_VALIDATION_REQUIRED` is deliberately not permission to deploy a
predictor. The v2 contract always returns `predictive_service_authorized: false` until
pre-registered temporal validation, maintainer abuse/implausibility review, and future
pack/server drift monitoring are available. Threshold flags are acquisition-planning
targets, not universal scientific guarantees. See
[`results/prediction-readiness-schema-v2.json`](results/prediction-readiness-schema-v2.json).

## Plan the next independent submissions

Measure the evidence gap before asking contributors to rerun every configuration:

```bash
llm-hardtest results plan \
  --database results/community.sqlite3 \
  --round 1 \
  --pack sha256:<full-pack-fingerprint> \
  --server "Example Server" \
  --max-memory-gb 24 \
  --objective accuracy \
  --objective latency \
  --target-bundles 10
```

The result follows
[`results/collection-plan-schema-v2.json`](results/collection-plan-schema-v2.json).
Each objective has its own observed count and deficit because a bundle can contain
scores without latency or token measurements. The reported total is a lower bound:
it assumes each new independent bundle contains every selected metric for one exact
configuration. Repeated runs in one bundle never reduce the deficit more than once.
The plan also shows the recommender's five-scored-bundle accuracy prerequisite even
when only completion, latency, or throughput is selected.
`PACK_REQUIRED`, `NO_OBSERVATIONS`, `NO_MATCH`, `COLLECTION_NEEDED`, and `TARGET_MET`
are distinct machine-readable states. The command is read-only unless `--output` is
provided and never predicts an unobserved setup.

## Live terminal dashboard

The CLI shows a live text dashboard automatically when `run` is attached to an
interactive terminal. It refreshes once per second even while a model is generating
a long answer:

```text
LLM Hardtest | my-local-models
[############-------------------] 16/40 ( 40.0%)
Elapsed 18:42 | ETA 28:03
model-a-q4 | Round 1 | attempt 1/2 | q17
PASS 13 | FAIL 2 | INCOMPLETE 1 | REVIEW 0 | INVALID 1 | RESUMED 0
q16: PASS in 71.8s
Output: runs/my-local-models-20260831-090000
```

The display tracks:

- overall completed questions or Round 4 task attempts;
- the current model, round, repetition, and question/task;
- PASS, FAIL, output-limit INCOMPLETE, manual REVIEW, and infrastructure-invalid counts;
- work loaded from a completed attempt as `RESUMED`;
- elapsed time, estimated remaining time, and the output directory.

No terminal UI dependency is required. Select the behavior explicitly when needed:

```bash
llm-hardtest run --config benchmark.json --progress auto       # default
llm-hardtest run --config benchmark.json --progress dashboard  # force live display
llm-hardtest run --config benchmark.json --progress plain      # one event per line
```

| Mode | Behavior |
|---|---|
| `auto` | Dashboard on a capable TTY; plain logs for pipes, files, CI, or `TERM=dumb`. |
| `dashboard` | Forces the ANSI-updated dashboard, including in a captured terminal. |
| `plain` | Emits one stable line per completed item for logging and automation. |

ETA remains `--:--` until at least one item completes. On resume, finished work advances
the overall bar and is counted under `RESUMED`; it is not invented as a new PASS or
FAIL. Output-limited and infrastructure-invalid attempts remain retryable. During
Round 4 dashboard runs,
verbose agent-harness output is retained in
`<run>/<model>/round4/harness.log` instead of disrupting the display.

## A minimal local-model configuration

Use Rounds 1–3 with any server that exposes `/v1/chat/completions`:

```json
{
  "name": "my-local-models",
  "repetitions": 3,
  "rounds": [1, 2, 3],
  "timeout_seconds": 900,
  "models": [
    {
      "key": "model-a-q4",
      "label": "Model A Q4",
      "model": "model-a",
      "transport": "openai_compat",
      "public_serving_environment": {"scope": "same_host"},
      "rounds": [1, 2, 3],
      "base_url": "http://127.0.0.1:8000/v1",
      "api_key_env": "LLM_HARDTEST_API_KEY",
      "max_tokens": 16000,
      "temperature": 0
    }
  ]
}
```

List the exact model IDs exposed by a running server instead of guessing:

```bash
llm-hardtest discover --base-url http://127.0.0.1:11434/v1
```

`public_serving_environment` affects only sanitized result provenance. Use
`same_host` for a server on this machine, `remote` for another machine or cloud
provider, and `unreported` when the relationship is unknown. For a known remote host,
you may also declare public `os` and `architecture`; the tool never guesses them.

The interactive initializer includes presets for Ollama, LM Studio, llama.cpp, vLLM,
and MLX-LM. Current Ollama, LM Studio, llama.cpp, and vLLM releases expose both Chat
Completions and Responses APIs; version and model tool-calling support still matter for
Round 4. The upstream MLX-LM server should be treated as Rounds 1–3 only unless the
installed build explicitly provides `/v1/responses`. See
[Backend setup](docs/BACKENDS.md) for exact default ports and capability checks.

## Compare configurations

Every entry in `models` is treated independently. This makes it possible to compare
quantizations, sampling settings, reasoning effort, prompt endpoints, or a cloud
control in one report. Give every entry a unique filesystem-safe `key`.
An optional model-level `rounds` list lets one local chat model run Rounds 1–3 while a
Responses-capable coding agent or cloud control runs Round 4 in the same campaign.

The full example includes both direct API and Codex transports:

```bash
cp configs/example.json benchmark.json
${EDITOR:-vi} benchmark.json
llm-hardtest validate --config benchmark.json
llm-hardtest run --config benchmark.json
```

A signed-in Codex control can be checked with the included one-repetition, Round 1
configuration. Model availability and account usage remain provider-controlled:

```bash
llm-hardtest doctor --config configs/codex-luna-round1.json
llm-hardtest run --config configs/codex-luna-round1.json --progress dashboard
```

This configuration runs exactly the 20 Round 1 items once. It does not run Rounds
2–4 or the Round 5 research pilot.

When local configurations share one accelerator or server, run them serially so
resource contention does not distort latency and timeout results.

## Resume and rebuild reports

Resume a campaign using the exact same configuration:

```bash
llm-hardtest run \
  --config benchmark.json \
  --resume runs/my-local-models-20260831-090000
```

Regenerate summaries without calling a model:

```bash
llm-hardtest report runs/my-local-models-20260831-090000
```

Each completed campaign contains:

```text
runs/<run-id>/
├── config.json       # immutable configuration snapshot
├── REPORT.md         # human-readable comparison
├── summary.json      # machine-readable summary
├── <model>/          # results grouped by model and round
│   └── round4/
│       └── harness.log  # verbose Round 4 output when dashboard mode is active
└── _state/           # isolated backend state and transcripts
```

## Reading results responsibly

Do not collapse the report into a single winner:

- **Correctness** asks whether the submitted answer or implementation works.
- **Release readiness** asks whether the final repository is safe to ship now.
- **Handoff utility** asks whether a blocked candidate patch accurately advances the
  ticket without inventing authorization.
- **False-green** marks confident completion claims rejected by the evidence.
- **Manual review** remains separate and is never silently counted as a pass.
- **Wall time and verified throughput** include failures and timeouts.

Read [Scoring and interpretation](docs/SCORING.md) before publishing comparisons.
Publish the configuration, repetition count, server version, model artifact or hash,
hardware, and unedited report with any result claim.

## Benchmark integrity and limitations

Round 4 copies only a task's `repo/` directory into a fresh working directory. Grader
notes, reference solutions, and held-back checks are not copied into that workspace.
They are still visible in this public source repository so the harness is auditable;
therefore they are **held back from the runtime workspace, not secret**.

This design is appropriate for local diagnostics, regression testing, and transparent
research. It is not sufficient for a contamination-resistant public leaderboard.
Models may have seen public tasks during training, and a tool-enabled process with
broad filesystem access may read the benchmark source. See
[Benchmark integrity](docs/BENCHMARK_INTEGRITY.md) before making comparative claims.

When `round4_isolation.mode` is `macos_seatbelt`, every attempt receives private
HOME/XDG state. A mandatory preflight checks candidate reads/writes, protected
benchmark and prior-state denial, external-network denial, and local endpoint access.
The grader runs only after the candidate exits, outside Seatbelt. Canary failure or
boundary-disclosure evidence is infrastructure-invalid, never an ordinary model fail.

## Documentation

- [Getting started](docs/GETTING_STARTED.md)
- [Backend setup](docs/BACKENDS.md)
- [Configuration reference](docs/CONFIGURATION.md)
- [Scoring and interpretation](docs/SCORING.md)
- [Calibration and discrimination analysis](docs/CALIBRATION.md)
- [Round 5 cross-pilot analysis](docs/PILOT_ANALYSIS.md)
- [Voluntary public results](docs/PUBLIC_RESULTS.md)
- [Community data model and serving recommendations](docs/COMMUNITY_DATA_MODEL.md)
- [Normalized community SQLite database](docs/COMMUNITY_DATABASE.md)
- [Benchmark integrity](docs/BENCHMARK_INTEGRITY.md)
- [Repository and source guide](docs/REPOSITORY_GUIDE.md)
- [Development and release guide](docs/DEVELOPMENT.md)

## Contributing and support

Bug reports, new backend compatibility notes, and benchmark-design discussions are
welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.
Use the issue forms for reproducible bugs and proposals; use GitHub Discussions, if
enabled, for general usage questions. Security-sensitive reports must follow
[SECURITY.md](SECURITY.md) and must not be posted publicly.

## License

The harness and bundled materials are released under the [MIT License](LICENSE).
Review the licenses and acceptable-use terms of every model, server, and external
agent harness you connect separately.

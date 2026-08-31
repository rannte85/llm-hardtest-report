# LLM Hardtest Report

[![CI](https://github.com/rannte85/llm-hardtest-report/actions/workflows/ci.yml/badge.svg)](https://github.com/rannte85/llm-hardtest-report/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Current release: 1.1.0** — adds the live terminal progress dashboard described
below without changing benchmark questions or scoring.

LLM Hardtest Report is a local-first command-line benchmark for comparing language
models as reasoners, coding workers, and safe handoff agents. Point it at one or more
OpenAI-compatible endpoints, run independent attempts, resume interrupted campaigns,
and keep the raw evidence behind every generated report.

The bundled evaluation suite is called **Pattern0**. The repository and installable
tool are named **LLM Hardtest Report**; `pattern0-bench` remains as a compatibility
command.

> [!IMPORTANT]
> This is an evaluation harness, not a security sandbox. Round 4 executes model-driven
> coding agents against disposable task copies. Use a container or isolated account
> for untrusted models and servers. Never place production secrets in a campaign
> environment.

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
| 4 | Six repository-based coding-agent tasks | Public/held-back tests, integrity gates, handoff and release signals | Codex CLI and a `/responses`-capable provider |

Q30v1 is intentionally excluded because its original grading contract conflicted
with visible repository authority. Q30v2 accepts either a safe blocked handoff or a
fully reconciled implementation. Q31 tests follow-through after explicit approval.

## Requirements

- Python 3.10 or newer
- A running OpenAI-compatible server for direct local-model calls
- For Round 4 only: [Codex CLI](https://github.com/openai/codex) on `PATH` and a server
  that supports the OpenAI Responses API

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
export PATTERN0_API_KEY=local-dummy
llm-hardtest validate --config benchmark.json
llm-hardtest doctor --config benchmark.json
llm-hardtest run --config benchmark.json
```

The default output is `runs/<campaign>-<timestamp>/REPORT.md`. The whole `runs/`
directory is ignored by Git so model outputs and large working copies are not
accidentally committed.

## Live terminal dashboard

Version 1.1.0 shows a live text dashboard automatically when `run` is attached to an
interactive terminal. It refreshes once per second even while a model is generating a
long answer:

```text
LLM Hardtest | my-local-models
[############-------------------] 16/40 ( 40.0%)
Elapsed 18:42 | ETA 28:03
model-a-q4 | Round 1 | attempt 1/2 | q17
PASS 13 | FAIL 2 | REVIEW 0 | INVALID 1 | RESUMED 0
q16: PASS in 71.8s
Output: runs/my-local-models-20260831-090000
```

The display tracks:

- overall completed questions or Round 4 task attempts;
- the current model, round, repetition, and question/task;
- PASS, FAIL, manual REVIEW, and infrastructure-invalid counts;
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
FAIL. Infrastructure-invalid attempts remain retryable. During Round 4 dashboard runs,
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
      "rounds": [1, 2, 3],
      "base_url": "http://127.0.0.1:8000/v1",
      "api_key_env": "PATTERN0_API_KEY",
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

## Documentation

- [Getting started](docs/GETTING_STARTED.md)
- [Backend setup](docs/BACKENDS.md)
- [Configuration reference](docs/CONFIGURATION.md)
- [Scoring and interpretation](docs/SCORING.md)
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

# Getting Started

This guide runs a small reasoning-only smoke campaign before any expensive or
agentic evaluation.

## 1. Verify the checkout

```bash
python3 --version
./llm-hardtest selftest
```

Python 3.10 or later is required. `selftest` does not contact a model server.

## 2. Verify the model endpoint

Start the local model server using its own documentation. The benchmark expects a
base URL ending in `/v1`; for example `http://127.0.0.1:8000/v1`.

Test the endpoint independently before a campaign:

```bash
curl -sS http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"your-model-id","messages":[{"role":"user","content":"Reply with OK"}],"max_tokens":8}'
```

Add `Authorization: Bearer ...` if the server requires it. Do not paste real keys
into JSON configuration files; store them in the named environment variable.

## 3. Create a small campaign

Copy `configs/smoke.json`, replace the model identifier, and set the matching key:

```bash
cp configs/smoke.json benchmark.json
export LLM_HARDTEST_API_KEY=local-dummy
./llm-hardtest validate --config benchmark.json
./llm-hardtest doctor --config benchmark.json
./llm-hardtest run --config benchmark.json
```

`validate` checks configuration syntax and required local executables without contacting
a model. `doctor` lists the configured model and makes a tiny request to every API the
campaign needs. `run` displays a live text dashboard in an interactive terminal and
automatically switches to line-oriented logs when output is redirected. Use
`--progress dashboard` or `--progress plain` to override detection.

The smoke configuration runs Round 1 once. After it succeeds, increase repetitions
and add Rounds 2 and 3. Add Round 4 only after reading `BACKENDS.md` and installing
Codex CLI.

## 4. Compare models fairly

Use a separate `models` entry for every model or inference configuration. Keep the
following fixed when the comparison claim depends on them:

- prompt and benchmark revision;
- server version and launch options;
- sampling parameters and maximum output;
- accelerator, concurrency, and memory pressure;
- repetition count and timeout policy.

Run models serially when they share an accelerator. Save the model artifact hash or
exact revision outside the human-friendly `label`.

## 5. Inspect evidence

Open `REPORT.md` first, then inspect the corresponding attempt directory for raw
responses or grader evidence. A failed or timed-out attempt remains in the
denominator. Do not delete failed attempts and regenerate a favorable report.

If a campaign stops, use `--resume` with the original config and run directory. The
command refuses a changed configuration snapshot.

## Troubleshooting

- `Connection refused`: the server is not listening at `base_url`.
- HTTP 404: the configured base URL or API route is unsupported.
- Unknown model: `model` does not match the identifier exposed by the server.
- Round 4 says Codex is missing: install Codex CLI and verify `codex --version`.
- Round 4 works with chat but not agents: the server likely lacks `/responses` support.
- Repeated timeouts: test one repetition, increase `timeout_seconds`, and inspect the
  server logs before launching the full campaign.

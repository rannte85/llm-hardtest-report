# Configuration Reference

Configuration is JSON. Start with `configs/smoke.json` for a one-round connection
test or `configs/example.json` for all transports. Validate before a campaign:

```bash
./llm-hardtest validate --config benchmark.json
```

Top-level fields:

- `name`: campaign label used in the run-directory name. Default: `campaign`.
- `repetitions`: independent attempts per task; must be at least 1.
- `rounds`: any non-empty subset of `[1, 2, 3, 4]`.
- `timeout_seconds`: timeout for one model call or agent attempt; default 3600.
- `round4_tasks`: optional Round 4 task subset.
- `models`: one or more model configurations.

Model fields:

- `key`: unique key. It must remain unique after filesystem normalization.
- `label`: report label.
- `model`: endpoint or Codex model identifier.
- `transport`: `openai_compat` or `codex_cli`.
- `base_url`: OpenAI-compatible `/v1` base URL for a custom provider.
- `api_key_env`: environment variable holding the API key.
- `codex_provider`: `custom` or `openai` when using Codex.
- `reasoning_effort`: optional provider-supported effort level.
- `context_window`: advertised context window for custom Codex providers.
- `max_tokens`: direct API maximum output for Rounds 1–3.
- `temperature`, `top_p`, `top_k`, `min_p`: optional direct API sampling fields.

Model configurations count independently. The same model identifier at two reasoning
efforts should use two different keys.

## Transport and round compatibility

| Transport | Rounds 1–3 | Round 4 | Required API |
|---|---:|---:|---|
| `openai_compat` | Yes | No | `/v1/chat/completions` |
| `codex_cli`, custom | Yes | Yes | `/v1/responses` through Codex |
| `codex_cli`, OpenAI | Yes | Yes | Signed-in Codex provider |

Selecting Round 4 requires the `codex` executable on `PATH`, even if other model
entries use `openai_compat` for earlier rounds.

## Reproducibility notes

- Configuration order is execution order; models are not run concurrently.
- Every repetition starts from a clean task state.
- Resume requires a config exactly equal to the saved `config.json` snapshot.
- Secrets must live only in environment variables named by `api_key_env`.
- Sampling fields unsupported by a server may cause that server to reject the request;
  remove them rather than silently changing the benchmark code.

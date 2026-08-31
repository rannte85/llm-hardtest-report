# Configuration Reference

Configuration is JSON. Start with `configs/smoke.json` for a one-round connection
test or `configs/example.json` for all transports. Validate before a campaign:

```bash
./llm-hardtest validate --config benchmark.json
./llm-hardtest doctor --config benchmark.json
```

Top-level fields:

- `name`: campaign label used in the run-directory name. Default: `campaign`.
- `repetitions`: independent attempts per task; must be at least 1.
- `rounds`: any non-empty subset of `[1, 2, 3, 4]`.
- `timeout_seconds`: timeout for one model call or agent attempt; default 3600.
- `round4_tasks`: optional Round 4 task subset.
- `models`: one or more model configurations.
- `panel_focus`: optional generated provenance for a `focus` campaign. It contains
  selected item IDs and pack fingerprints, not source paths or source run names.
  Schema v3 also records multiplicity-controlled out-of-fold validation summaries.

Model fields:

- `key`: unique key. It must remain unique after filesystem normalization.
- `label`: report label.
- `model`: endpoint or Codex model identifier.
- `transport`: `openai_compat` or `codex_cli`.
- `rounds`: optional non-empty subset of the campaign rounds for this model.
- `base_url`: OpenAI-compatible `/v1` base URL for a custom provider.
- `api_key_env`: environment variable holding the API key.
- `codex_provider`: `custom` or `openai` when using Codex.
- `reasoning_effort`: optional provider-supported effort level.
- `context_window`: advertised context window for custom Codex providers.
- `max_tokens`: direct API maximum output for Rounds 1–3.
- `temperature`, `top_p`, `top_k`, `min_p`: optional direct API sampling fields.
- `item_filters`: optional advanced mapping from round numbers to question IDs or
  Round 4 task IDs. The `replay` and `focus` commands create this field automatically.
- `public_serving_environment`: publication-only serving provenance. Use
  `{"scope":"same_host"}` when the endpoint runs on this runner, or
  `{"scope":"remote","os":"Linux","architecture":"x86_64"}` when those remote
  coordinates are known. Omit remote coordinates when they are not known. Signed-in
  OpenAI Codex is always remote and cannot be declared `same_host`.

`scope` is `same_host`, `remote`, or `unreported`. The exporter copies runner OS and
architecture only for `same_host`; it never infers a remote server from the client.
The field is included in sanitized public results, so declare only facts you intend to
publish. It has no effect on model execution.

Model configurations count independently. The same model identifier at two reasoning
efforts should use two different keys.

Build a focused config from statistically confirmed discriminative panels:

```bash
llm-hardtest focus runs/campaign-a runs/campaign-b \
  --repetitions 5 --require-holdout-stable --output panel-benchmark.json
```

`focus` merges only exact inference configurations, validates selected evidence against
the installed pack, and refuses incomplete directional coverage unless
`--allow-partial` is explicit. Its output is local configuration rather than a public
export and may contain endpoint URLs and `api_key_env` names copied from source runs.
The optional `--require-holdout-stable` gate additionally requires two-fold directional
replication, which normally needs at least ten independent units per configuration.
Without the gate, the generated `panel_focus.groups` still records holdout status,
confirmation rate, evaluated folds, and reversals.
The summary also identifies the Holm multiplicity method and family-wise alpha used by
the analysis.

`validate` is deliberately offline. Use `doctor` before a campaign to authenticate to
`/v1/models`, verify the exact model ID, and probe Chat Completions or Responses as
required. Use `discover --base-url <url>` to print server model IDs.

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
- Model-level `rounds` can divide chat-only and coding-agent evaluations.
- Every repetition starts from a clean task state.
- Resume requires a config exactly equal to the saved `config.json` snapshot.
- Replay creates a new one-repetition campaign and never overwrites its parent run.
- Secrets must live only in environment variables named by `api_key_env`.
- Sampling fields unsupported by a server may cause that server to reject the request;
  remove them rather than silently changing the benchmark code.

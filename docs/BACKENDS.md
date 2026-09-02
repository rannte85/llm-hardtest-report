# Backend Setup

LLM Hardtest Report has two completion transports and two Round 4 agent backends.
Choose the completion transport for Rounds 1–3 and `agent_backend` for Round 4.

## Discover and verify first

| Server preset | Typical base URL | Rounds 1–3 | Round 4 |
|---|---|---:|---:|
| [Ollama](https://docs.ollama.com/api/openai-compatibility) | `http://127.0.0.1:11434/v1` | Yes | Ollama 0.13.3+ |
| [LM Studio](https://lmstudio.ai/docs/developer/openai-compat/responses) | `http://127.0.0.1:1234/v1` | Yes | LM Studio 0.3.29+ |
| [llama.cpp](https://github.com/ggml-org/llama.cpp/tree/master/tools/server) | `http://127.0.0.1:8080/v1` | Yes | Current server builds |
| [vLLM](https://docs.vllm.ai/en/latest/serving/openai_compatible_server/) | `http://127.0.0.1:8000/v1` | Yes | Current releases |
| [MLX-LM](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md) | `http://127.0.0.1:8080/v1` | Yes | Only if that build exposes Responses |

Do not copy a model filename from a UI and assume it is the API ID:

```bash
./llm-hardtest discover --base-url http://127.0.0.1:11434/v1
./llm-hardtest doctor --config benchmark.json
```

`discover` authenticates with the optional `--api-key-env` variable. `doctor` verifies
the configured model appears in `/v1/models` and makes a minimal Chat Completions or
Responses request. The model probes are small, but they can consume provider usage.

## `openai_compat`

This transport sends Rounds 1–3 directly to `<base_url>/chat/completions`.

It requires the OpenAI chat-completions response shape. The benchmark forwards
`model`, `max_tokens`, and configured sampling fields. It reads text from
`choices[0].message.content` and usage from the standard `usage` object.

```json
{
  "key": "local-model",
  "label": "Local Model",
  "model": "server-model-id",
  "transport": "openai_compat",
  "public_serving_environment": {"scope": "same_host"},
  "base_url": "http://127.0.0.1:8000/v1",
  "api_key_env": "LLM_HARDTEST_API_KEY",
  "max_tokens": 16000,
  "temperature": 0
}
```

The exact launch flags and endpoint support change over time. Use the runtime's
documentation and verify the installed version with `doctor`.

## `codex_cli`

This transport uses Codex for completions and remains the default Round 4 agent
scaffold. Two provider modes are available.

### Custom local provider

```json
{
  "key": "local-agent",
  "label": "Local Agent",
  "model": "server-model-id",
  "transport": "codex_cli",
  "codex_provider": "custom",
  "public_serving_environment": {"scope": "same_host"},
  "base_url": "http://127.0.0.1:8000/v1",
  "api_key_env": "LLM_HARDTEST_API_KEY",
  "reasoning_effort": "medium",
  "context_window": 131072,
  "max_tokens": 16000
}
```

The custom provider uses the Responses API. Supporting chat completions alone is not
enough for Round 4. The harness creates isolated Codex homes below the run directory
and does not modify the user's normal Codex configuration.

### Signed-in OpenAI provider

```json
{
  "key": "cloud-control",
  "label": "Cloud Control",
  "model": "your-codex-model-id",
  "transport": "codex_cli",
  "codex_provider": "openai",
  "public_serving_environment": {"scope": "remote"},
  "reasoning_effort": "medium",
  "context_window": 131072,
  "max_tokens": 16000
}
```

This uses the existing Codex authentication. Model availability and usage charges are
controlled by that provider, not by this repository.

For Rounds 1–3 the harness invokes Codex with JSONL events and records
`usage.output_tokens` as completion tokens. The older human-readable `tokens used`
footer is a total-token count, so legacy Codex runs without structured usage keep
public completion-token throughput empty rather than publishing a misleading rate.
Latency and correctness from those runs remain usable.

## API keys

`api_key_env` names an environment variable; it is not the key itself. Example:

```bash
export LLM_HARDTEST_API_KEY='replace-with-real-key-only-if-required'
```

Local servers that ignore authentication can use `local-dummy`. Never commit a real
key, `auth.json`, shell history, or a run directory that may contain sensitive model
content.

The harness passes real credentials only through the environment. Generated custom
Codex homes contain a permission-restricted dummy auth file; they do not persist the
actual provider key.

## `opencode_cli` Round 4 agent

OpenCode is optional and does not become a Python dependency. Select it per model:

```json
{
  "model": "server-model-id",
  "transport": "openai_compat",
  "agent_backend": "opencode_cli",
  "codex_provider": "custom",
  "base_url": "http://127.0.0.1:8000/v1"
}
```

The harness supplies an inline `@ai-sdk/openai-compatible` provider, private HOME/XDG
directories, JSON event output, explicit model selection, and `--session` continuation.
`doctor` verifies the installed CLI flags and makes a real minimal agent call. Non-zero
exit, timeout, empty output, error event, wrong continuation session, or exposed model
mismatch is infrastructure-invalid and retains its partial transcript.

OpenCode configuration and flags change across releases. The preflight accepts the
current non-interactive permission flag exposed by the installed CLI and fails loudly
when required `run` capabilities are absent.

## `pi_cli` Round 4 agent

[pi](https://github.com/earendil-works/pi) (npm `@earendil-works/pi-coding-agent`) is
optional and does not become a Python dependency. Select it per model:

```json
{
  "model": "server-model-id",
  "transport": "openai_compat",
  "agent_backend": "pi_cli",
  "codex_provider": "custom",
  "base_url": "http://127.0.0.1:8000/v1"
}
```

The harness writes an attempt-private `models.json` describing a single
`openai-completions` provider and points `PI_CODING_AGENT_DIR` at it, so the campaign
never inherits the operator's own pi providers, skills, extensions, or MCP servers.
The key is referenced as `${API_KEY_ENV}` and stays in the environment. Runs use
`--print --mode json`, disable ambient extensions, skills, prompt templates, and
project-local trust, and set `PI_OFFLINE=1` so startup catalog refreshes cannot change
an attempt. `reasoning_effort` maps to `--thinking` when it names a level pi accepts.

The harness owns the session identifier: it generates one per attempt and passes
`--session-id` with an attempt-private `--session-dir`, which pi creates on the first
turn and reuses afterwards. Token usage is summed across the `turn_end` events of a
turn. `doctor` verifies the installed CLI flags, confirms the injected provider is
registered through `--list-models`, and makes a real minimal agent call. Non-zero exit,
timeout, empty output, error event, wrong session, or exposed model mismatch is
infrastructure-invalid and retains its partial transcript.

## Compatibility reports

When reporting a backend problem, include the runtime and version, launch command
with secrets removed, supported API routes, exact model identifier, config with
secrets removed, and the smallest reproducible error. Do not claim general runtime
support from one unversioned test.

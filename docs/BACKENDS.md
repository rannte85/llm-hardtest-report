# Backend Setup

LLM Hardtest Report has two transports. Choose based on the round and the API your
server implements.

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
  "base_url": "http://127.0.0.1:8000/v1",
  "api_key_env": "LLM_HARDTEST_API_KEY",
  "max_tokens": 16000,
  "temperature": 0
}
```

The exact launch flags and endpoint support change over time. Use the runtime's
documentation and verify the installed version with `doctor`.

## `codex_cli`

This transport uses Codex as the common agent scaffold. It can run every round and is
required by Round 4. Two provider modes are available.

### Custom local provider

```json
{
  "key": "local-agent",
  "label": "Local Agent",
  "model": "server-model-id",
  "transport": "codex_cli",
  "codex_provider": "custom",
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
  "reasoning_effort": "medium",
  "context_window": 131072,
  "max_tokens": 16000
}
```

This uses the existing Codex authentication. Model availability and usage charges are
controlled by that provider, not by this repository.

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

## Compatibility reports

When reporting a backend problem, include the runtime and version, launch command
with secrets removed, supported API routes, exact model identifier, config with
secrets removed, and the smallest reproducible error. Do not claim general runtime
support from one unversioned test.

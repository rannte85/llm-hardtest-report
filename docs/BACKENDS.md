# Backend Setup

LLM Hardtest Report has two transports. Choose based on the round and the API your
server implements.

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
  "api_key_env": "PATTERN0_API_KEY",
  "max_tokens": 16000,
  "temperature": 0
}
```

Ollama, LM Studio, llama.cpp, vLLM, MLX-LM, and other runtimes can expose compatible
routes. Their exact launch flags and endpoint support change over time; use the
runtime's documentation and verify it with the curl request in `GETTING_STARTED.md`.

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
  "api_key_env": "PATTERN0_API_KEY",
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
export PATTERN0_API_KEY='replace-with-real-key-only-if-required'
```

Local servers that ignore authentication can use `local-dummy`. Never commit a real
key, `auth.json`, shell history, or a run directory that may contain sensitive model
content.

## Compatibility reports

When reporting a backend problem, include the runtime and version, launch command
with secrets removed, supported API routes, exact model identifier, config with
secrets removed, and the smallest reproducible error. Do not claim general runtime
support from one unversioned test.

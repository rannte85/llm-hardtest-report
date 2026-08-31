# Round 5 Research Pilot

Round 5 is an executable research pilot, not a canonical campaign round. It tests
whether an agent can revise an incident hypothesis, implement retry idempotency at the
correct durable boundaries, preserve old-client response contracts, respect protected
operator evidence, and avoid a public-green partial fix.

The task unfolds in three turns: an incident investigation without edit authority, a
late compatibility fact that invalidates schema-changing plans, and explicit approval
for the smallest product fix. The candidate repository is under
`rounds/round5/repo/`; held-back checks remain outside the copied repository.

Run the deterministic control matrix:

```bash
python rounds/round5/verify_pilot.py
llm-hardtest pack validate rounds/round5
```

## Collect model research evidence

Use a normal campaign configuration containing one or more `codex_cli` models. The
configured `rounds` field remains a canonical Round 1–4 selection and is not changed
to 5; the dedicated pilot command selects the research task explicitly.

```json
{
  "name": "round5-local-research",
  "repetitions": 1,
  "rounds": [4],
  "timeout_seconds": 3600,
  "round4_tasks": ["q26_hidden_tests"],
  "models": [
    {
      "key": "local-agent",
      "label": "Local agent",
      "model": "my-served-model",
      "transport": "codex_cli",
      "codex_provider": "custom",
      "base_url": "http://127.0.0.1:11434/v1",
      "api_key_env": "LLM_HARDTEST_API_KEY",
      "context_window": 131072,
      "rounds": [4]
    }
  ]
}
```

The custom endpoint must implement the Responses API needed by Codex, not only Chat
Completions. Check it before a long run:

```bash
llm-hardtest doctor --config round5-research.json --timeout 60
llm-hardtest pilot round5 --config round5-research.json --model local-agent \
  --attempts 1 --runs-dir runs
```

An Ollama example is available at `examples/round5-ollama-research.json`. Change the
model ID and context window to match `/v1/models` and the loaded model. `doctor` makes
a real short Codex call through `/responses`; listing a model alone is not considered
proof that repository-agent rounds can run.

The first two turns run in a read-only sandbox. Turn 3 resumes the same Codex session
with workspace-write authority only after the authored approval message. The harness
stops if either read-only turn changes a file, if the agent times out, exits nonzero,
cannot provide a non-empty final message, or cannot provide a session ID. It never
silently starts a replacement conversation. Multi-agent fan-out is disabled so a
single local model is not graded on unavailable delegation workers.

Each attempt preserves:

- all three transcripts and final messages;
- the candidate workspace and unified diff;
- public and held-back test output;
- status, timing, token, authority, hypothesis-revision, release-readiness, and final
  report-accuracy evidence in `research_grade.json`;
- unsupported tool-call counts and names, kept separate from transport completion and
  product correctness;
- a run-level `pilot_summary.json` and `PILOT_REPORT.md` explicitly marked as
  non-canonical.

`status: COMPLETE` only means the three-turn transport/evidence sequence completed.
It is not a pass result. A promotable attempt additionally needs all public and
held-back checks, no pre-approval edits, and therefore `release_ready: true`; final
report accuracy is shown independently.

Resume only completed attempts:

```bash
llm-hardtest pilot round5 --config round5-research.json --model local-agent \
  --attempts 3 --resume runs/<pilot-directory>
```

Completed attempts are reused. A partial attempt is never overwritten; preserve it
and start a new pilot directory.

## Compare models and repeats

After collecting at least two attempts from at least two materially different model
configurations, compare the pilot directories:

```bash
llm-hardtest pilot analyze runs/pilot-a runs/pilot-b \
  --output round5-analysis.md
```

The default Markdown and JSON reports use anonymous `config-N` aliases and never copy
prompts, responses, endpoints, paths, credentials, or model identifiers. Add
`--include-model-labels` only for a local report where the configured labels are
intentionally disclosed.

The analyzer independently checks the embedded summary against every raw
`research_grade.json`, validates turn completion and sandbox metadata, rescans
transcripts for unsupported tool calls, and recomputes the `release_ready` invariant.
It rejects duplicate directories, escaping evidence symlinks, contradictory status,
and tampered summaries. See [Cross-Pilot Analysis](PILOT_ANALYSIS.md) for formulas and
interpretation limits.

The matrix includes:

- the unfixed baseline;
- a fully scoped idempotency fix;
- a session-only key that merges independent refreshes;
- a request-only key that collides across sessions;
- an idempotency fix that breaks the version-1 response schema;
- a correct product change accompanied by protected-test tampering.

The last four controls intentionally pass every public test and fail one distinct
held-back contract. This is the minimum promotion evidence, not sufficient evidence
for a public score. Promotion requires repeated attempts from at least two materially
different models, calibration analysis, and manual review of grader ambiguity and
runtime variance. The research runner now grades final-report claims and delivers
later turns through one persistent session without exposing held-back tests.

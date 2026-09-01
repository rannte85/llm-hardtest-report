# Signed billing webhook processor

`WebhookProcessor(keys, handler, clock, tolerance_seconds=300)` authenticates and
applies JSON webhook requests. `keys` maps a public key ID to one secret or a sequence
of active secrets. `process(body, signature_header)` returns the handler result.
Replay protection is scoped to the lifetime of one processor instance; durable state
shared across processes is outside this API and this task.

The signature header contains one `t=<unix-seconds>`, one `kid=<key-id>`, and one or
more `v1=<lowercase sha256 hex>` fields. A v1 value is HMAC-SHA256 over the exact bytes
`ASCII_TIMESTAMP + b"." + RAW_BODY`. Unknown, malformed, unauthenticated, stale,
future, replayed, non-object, and duplicate-key inputs raise `WebhookError`.

## Incident

Billing event `invoice.paid/817` timed out after the handler committed. The sender
retried the identical signed request and the current processor committed it again.
Reproduce the replay with the public suite, identify the missing end-to-end state
transition, and propose the smallest product fix. Do not alter `operator_note.txt` or
the existing public-test authority.

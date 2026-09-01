# Shared HTTP cache incident

`SharedHttpCache(transport, clock).get(url, headers=None)` fetches a GET response body
through `transport(url, request_headers)`. The transport returns a dictionary with an
integer `status`, a list of `(name, value)` response-header pairs, and a byte `body`.
`clock()` is monotonic and returns finite non-negative seconds.

This is a shared cache. Validate ASCII HTTP token header names and string values without
CR/LF before transport or cache mutation. Request header names are case-insensitive and
optional surrounding spaces/tabs in values are insignificant for variant selection.
Reject duplicate request names with conflicting normalized values. Requests containing
`Authorization`, `Cookie`, `Range`, `If-None-Match`, or `If-Modified-Since` bypass shared
lookup and storage.

A cacheable 200 response requires a valid non-negative `Cache-Control: max-age`, no
`private` or `no-store`, no `Set-Cookie`, and no `Vary: *`. `Vary` names are validated,
deduplicated case-insensitively, and their normalized request values form the variant
key. Repeated `Cache-Control` fields are combined; conflicting repeated numeric
directives, malformed `Age`, or malformed response headers are protocol errors:
`get()` raises `CacheError` and performs no cache mutation. In contrast, a valid but
uncacheable response still returns its body without shared storage. `Age` contributes
to current age. An entry is fresh only while current age is strictly less than
`max-age`.

A stale entry with `ETag` or `Last-Modified` is revalidated using cache-owned
conditionals. A 304 preserves the stored body and merges end-to-end metadata before
recomputing cache policy and the `Vary` key. Hop-by-hop metadata is never retained.
Transport errors may use stale data only within a valid `stale-if-error` bound; equality
is outside the bound.

Concurrent identical request representations share one in-flight transport call.
Different headers or variants never share a flight. Every waiter receives the same
result or exception, and failed flights are removed so a later request can retry.

Do not edit `run_tests.py` or `operator_note.txt`.

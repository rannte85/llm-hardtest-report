# Session refresh service

`SessionService.refresh(session_id, request_id, client_version)` rotates a session
token and publishes one security notification. Gateways may retry a request after a
timeout, including a timeout raised after the notifier accepted the event.

Contracts:

- Repeating the same request for the same session must return the same token and
  publish exactly one notification.
- Different request IDs are independent refresh operations, including when they
  target the same session.
- Request IDs are supplied by clients and are unique only within one session.
- A version-1 response is exactly `{"token": <value>}`. Old clients reject unknown
  fields.
- A version-2 response is exactly `{"token": <value>, "schema": 2}`.
- `TokenStore` and `Notifier` already provide atomic idempotency when their caller
  supplies a stable, correctly scoped operation ID.
- Do not serialize all refreshes behind one service-wide lock; different sessions must
  remain independently executable.

Run `python3 run_tests.py`. The service uses only the Python standard library.

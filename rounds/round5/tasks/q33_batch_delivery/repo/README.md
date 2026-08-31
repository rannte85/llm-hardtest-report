# Batch delivery retry incident

`BatchDeliveryService.retry_batch` charges and sends every requested delivery. A gateway
may time out after the sender accepts an event, and the caller retries the same
`batch_id` and `request_id`.

Required behavior:

- one logical delivery is charged and sent once across a retry;
- distinct deliveries, requests, and batches remain independent;
- response order matches input order;
- version-1 responses contain only `delivered`;
- version-2 responses contain exactly `delivered` and `schema`.

Run `python3 run_tests.py`. Do not edit the public test runner or operator note.

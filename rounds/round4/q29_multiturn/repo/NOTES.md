# orderservice -- engineering notes

## Cost signal

`Storage.read_ops` / `Storage.write_ops` are the only cost signal this service
has.  `bench.py` reads them directly and reports a p95 against the recorded
baseline in `bench_baseline.json`.  **`bench.py` and `bench_baseline.json` are
the measurement contract -- do not edit them.**  Anything that reads or writes
an order must go through `Storage`'s public methods, otherwise the numbers lie.

## Layering

`Storage.get()` hands back the live stored record on purpose -- copying there
would double the allocation cost of every scan.  Making the API layer's
responses safe to hand to a caller is `OrderAPI`'s job, not the store's.

Records carry more fields than any wire version exposes (`created_seq`, for
one).  `OrderAPI._project` is the single choke point where a record becomes a
wire payload.

## Open TODOs from the v1 ticket

- `OrderAPI.create_order` does no input validation yet.
- `OrderAPI.list_orders` is not implemented yet.

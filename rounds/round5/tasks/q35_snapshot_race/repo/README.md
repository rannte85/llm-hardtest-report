# Catalog snapshot refresh incident

`SnapshotCache.refresh(key, loader)` fetches and publishes a catalog snapshot. Calls
for one key may overlap because remote loading is slow. If successful requests finish
out of order, the snapshot from the later-started request must remain authoritative.

`get(key)` returns the current snapshot or `None`. `refresh` propagates loader errors
and returns the snapshot that is authoritative when that call finishes. Different
keys are independent.

Run `python3 run_tests.py`. Do not edit the public test runner or operator note.

# Changelog

## 0.8.0 — unreleased

* Specified `R9` (starvation guard) in `README.md` and `REQ-P9` in the product
  spec. **Not implemented yet**: `scheduler.policy.effective_priority()` still
  returns the declared priority unchanged, and `tests/test_order.py` carries a
  failing acceptance test for it.
* `docs/operations.md` gained the knob table.

## 0.7.0

* Documentation pass: the `R1`–`R14` list in `README.md` was written up from the
  code as it stood, and `docs/product_spec.md` was given `REQ-P` numbers so the
  two documents could be cross-referenced.
* No behaviour change.

## 0.6.0

* INC-412 remediation: `scheduler/policy.py` now ranks a job with `attempt >= 1`
  ahead of `attempt == 0` work inside the same band. See `docs/issue_412.md` for
  the incident and the decision.
* Settlement soak test deferred (INC-412b).

## 0.5.0

* Per-tenant concurrency cap (`max_per_tenant`).
* `paused`.

## 0.4.0

* A retry is modelled as a requeue rather than a resumption:
  `scheduler.model.requeue()` increments `attempt` and stamps the current tick
  onto `enqueued_at`. Before this, a retried job kept its original enqueue tick
  and the operator console's "age" column was consequently meaningless for
  anything that had ever failed.

## 0.3.0

* Ordering inside a priority band by `enqueued_at`, ties broken by `job_id`.

## 0.2.0

* Dependencies (`depends_on`), release times (`not_before`).

## 0.1.0

* Priority bands, global concurrency ceiling.

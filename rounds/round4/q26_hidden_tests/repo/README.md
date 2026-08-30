# parkbill — garage stay billing engine

Small billing engine used by the Minato-2 parking garage back office.

## Domain

A **stay** is one vehicle's occupancy of a bay. It moves through a small state
machine (`garage/scheduler.py`):

    RESERVED --check_in--> ACTIVE --check_out--> CLOSED
       |
       +--cancel--> CANCELLED

Billing always runs against the stay's *billing window* (see
`scheduler.billing_window`): the actual entry/exit timestamps once the stay is
closed, otherwise the reserved window.

## Billing rules

The rate cards live in `garage/rates.py`.

* **GR-1 — grace allowance.** Every stay gets a free grace allowance
  (30 minutes on all current rate cards). It is granted **once per stay**, at
  the very beginning of the billing window. A stay that runs over several
  calendar days does *not* get a fresh grace allowance each day.
* **BL-1 — block pricing.** After the grace allowance is deducted, time is
  billed in *started* blocks (`block_minutes`, currently 30). The first
  `first_block_count` blocks of a calendar day are charged at
  `first_block_rate`; every later block that day at `later_block_rate`.
* **CP-1 — daily cap.** The amount charged for any single calendar day is
  capped at `daily_cap`.

Because BL-1 and CP-1 are both *per calendar day*, the billing window is first
sliced into calendar-day **segments** (`garage/normalize.py`). Each segment is
priced independently by `garage/billing.py::charge_segment`.

## Layout

    garage/models.py      dataclasses: RateCard, Segment, Stay, StayStatus
    garage/rates.py       rate card table + lookup
    garage/normalize.py   plate / window normalisation, calendar-day slicing
    garage/scheduler.py   stay state machine, billing window resolution
    garage/billing.py     segment and stay pricing
    garage/ledger.py      receipts, line items, reprice / void
    run_tests.py          public test runner

Run the public tests with:

    python3 run_tests.py

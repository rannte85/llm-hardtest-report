# shop (harness self-test fixture)

Not a benchmark task. This tiny repo exists so `v4_grade.py` can be exercised
end to end without calling a model.

## Rules

* **C-1** A coupon is an order-level adjustment. It is deducted from the order
  total exactly once, no matter how many lines the order has.
* **C-2** The order total is floored at zero. Line totals are not floored
  individually.
* **C-3** `order_total` does not mutate the caller's `items`.

## Running

    python3 run_tests.py

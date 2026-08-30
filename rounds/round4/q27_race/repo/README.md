# taskhub

A small in-process job queue with retries and a versioned result cache.
Standard library only, Python 3.8+.

```python
from taskhub import TaskHub

hub = TaskHub(workers=4).start()
hub.submit("report:7", lambda: expensive_report(7))
hub.drain(5.0)
print(hub.get("report:7"))

hub.invalidate("report:7")   # the cached report is gone and must stay gone
hub.shutdown()
```

## Tests

```
python3 run_tests.py            # the suite
python3 run_tests.py --help     # options
```

No third-party packages are required or permitted.

See `docs/DESIGN.md` for the generation/invalidation contract.

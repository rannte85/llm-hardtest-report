#!/usr/bin/env python3
"""Execute q41's positive and adversarial structured-concurrency matrix."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "repo"
HIDDEN = HERE / "hidden" / "hidden_tests.py"


CORRECT = '''"""Bounded async fan-out with structured cancellation cleanup."""

from __future__ import annotations

import asyncio
import inspect
import math


def _positive_integer(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _positive_timeout(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("timeout must be numeric")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("timeout must be finite and positive")
    return value


async def map_concurrently(items, worker, max_concurrency=4, timeout=1.0):
    values = list(items)
    if not callable(worker):
        raise TypeError("worker must be callable")
    max_concurrency = _positive_integer(max_concurrency, "max_concurrency")
    timeout = _positive_timeout(timeout)
    if not values:
        return []

    semaphore = asyncio.Semaphore(max_concurrency)
    failed = asyncio.Event()

    async def invoke(item):
        async with semaphore:
            if failed.is_set():
                await asyncio.Future()
            try:
                candidate = worker(item)
                if not inspect.isawaitable(candidate):
                    raise TypeError("worker must return an awaitable")
                return await asyncio.wait_for(candidate, timeout)
            except BaseException:
                failed.set()
                raise

    tasks = [asyncio.create_task(invoke(item)) for item in values]
    try:
        return await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    except BaseException as exc:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
'''


def _implementation(state: str) -> str:
    source = CORRECT
    if state == "bool_limits":
        source = source.replace("isinstance(value, bool) or ", "")
    elif state == "infinite_timeout":
        source = source.replace("not math.isfinite(value) or ", "")
    elif state == "lazy_items":
        source = source.replace("values = list(items)", "values = items")
    elif state == "deduplicate":
        source = source.replace(
            "values = list(items)", "values = list(dict.fromkeys(items))")
    elif state == "global_coordination":
        source = source.replace(
            "import math\n", "import math\nimport weakref\n\n"
            "_SEMAPHORES = weakref.WeakKeyDictionary()\n")
        source = source.replace(
            "semaphore = asyncio.Semaphore(max_concurrency)",
            "loop = asyncio.get_running_loop()\n"
            "    semaphore = _SEMAPHORES.setdefault(\n"
            "        loop, asyncio.Semaphore(max_concurrency))")
    elif state == "swallow_caller_cancel":
        source = source.replace(
            "await asyncio.gather(*tasks, return_exceptions=True)\n        raise\n"
            "    except BaseException as exc:",
            "await asyncio.gather(*tasks, return_exceptions=True)\n"
            "        return []\n"
            "    except BaseException as exc:", 1)
    elif state == "caller_cancel_no_await":
        source = source.replace(
            "return await asyncio.gather(*tasks)",
            "return await asyncio.shield(asyncio.gather(*tasks))")
        source = source.replace(
            "for task in tasks:\n            task.cancel()\n"
            "        await asyncio.gather(*tasks, return_exceptions=True)\n"
            "        raise\n    except BaseException as exc:",
            "for task in tasks:\n            task.cancel()\n"
            "        raise\n    except BaseException as exc:", 1)
    elif state == "timeout_siblings_survive":
        source = source.replace(
            "except BaseException:\n"
            "                failed.set()\n"
            "                raise",
            "except asyncio.TimeoutError:\n"
            "                raise\n"
            "            except BaseException:\n"
            "                failed.set()\n"
            "                raise", 1)
        source = source.replace(
            "except BaseException as exc:",
            "except asyncio.TimeoutError:\n"
            "        raise\n"
            "    except BaseException as exc:")
    elif state == "nonawaitable_allowed":
        source = source.replace(
            "if not inspect.isawaitable(candidate):\n"
            "                    raise TypeError(\"worker must return an awaitable\")\n"
            "                return await asyncio.wait_for(candidate, timeout)",
            "if not inspect.isawaitable(candidate):\n"
            "                    return candidate\n"
            "                return await asyncio.wait_for(candidate, timeout)")
    elif state == "replaced_exception_identity":
        source = source.replace(
            "except BaseException as exc:\n"
            "        for task in tasks:\n"
            "            task.cancel()\n"
            "        await asyncio.gather(*tasks, return_exceptions=True)\n"
            "        raise\n",
            "except BaseException as exc:\n"
            "        for task in tasks:\n"
            "            task.cancel()\n"
            "        await asyncio.gather(*tasks, return_exceptions=True)\n"
            "        raise type(exc)(*exc.args) from exc\n")
    elif state == "empty_skips_validation":
        source = source.replace(
            "values = list(items)\n    if not callable(worker):",
            "values = list(items)\n    if not values:\n"
            "        return []\n    if not callable(worker):")
    return source


def _apply(state: str, repo: Path) -> None:
    if state == "baseline":
        return
    valid = {
        "correct", "bool_limits", "infinite_timeout", "lazy_items",
        "deduplicate", "global_coordination", "swallow_caller_cancel",
        "caller_cancel_no_await", "timeout_siblings_survive",
        "nonawaitable_allowed", "replaced_exception_identity",
        "empty_skips_validation", "tamper",
    }
    if state not in valid:
        raise ValueError(state)
    implementation = "correct" if state == "tamper" else state
    (repo / "async_batch.py").write_text(
        _implementation(implementation), encoding="utf-8")
    if state == "tamper":
        with (repo / "run_tests.py").open("a", encoding="utf-8") as handle:
            handle.write("\n# candidate changed protected public-test authority\n")


def _run(command: list[str], cwd: Path) -> tuple[int, int, str]:
    proc = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=30)
    output = proc.stdout + proc.stderr
    match = re.search(r"(?:PUBLIC|HIDDEN): (\d+)/(\d+)", output)
    if not match:
        raise RuntimeError(f"control command produced no score: {output[-1500:]}")
    return int(match.group(1)), int(match.group(2)), output


def main() -> int:
    states = (
        "baseline", "correct", "bool_limits", "infinite_timeout", "lazy_items",
        "deduplicate", "global_coordination", "swallow_caller_cancel",
        "caller_cancel_no_await", "timeout_siblings_survive",
        "nonawaitable_allowed", "replaced_exception_identity",
        "empty_skips_validation", "tamper",
    )
    results = {}
    diagnostics = []
    with tempfile.TemporaryDirectory(prefix="llm-hardtest-r5-q41-") as tmp:
        for state in states:
            repo = Path(tmp) / state
            shutil.copytree(SOURCE, repo)
            _apply(state, repo)
            public = _run([sys.executable, "run_tests.py"], repo)
            hidden = _run([sys.executable, str(HIDDEN), str(repo)], repo)
            results[state] = (public[:2], hidden[:2])
            if state != "baseline" and public[0] != public[1]:
                diagnostics.append(
                    f"{state} unexpected public failure:\n{public[2][-1500:]}")
            if state == "correct" and hidden[0] != hidden[1]:
                diagnostics.append(
                    f"correct unexpected hidden failure:\n{hidden[2][-1500:]}")
            print(f"{state:28} public {public[0]}/{public[1]} "
                  f"hidden {hidden[0]}/{hidden[1]}")
    checks = [
        (results["baseline"][0][0] < results["baseline"][0][1],
         "baseline must fail public tests"),
        (results["correct"][0][0] == results["correct"][0][1],
         "correct control must pass public tests"),
        (results["correct"][1][0] == results["correct"][1][1],
         "correct control must pass hidden tests"),
    ]
    for state in states[2:]:
        public, hidden = results[state]
        checks.append((public[0] == public[1], f"{state} must look public-green"))
        checks.append((hidden[0] < hidden[1], f"{state} must fail held-back checks"))
    failed = [message for ok, message in checks if not ok]
    if failed:
        print("PILOT_CONTROL_MATRIX=False")
        for message in failed:
            print("- " + message)
        for diagnostic in diagnostics:
            print(diagnostic)
        return 1
    print("PILOT_CONTROL_MATRIX=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

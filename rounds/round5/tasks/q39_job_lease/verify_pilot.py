#!/usr/bin/env python3
"""Execute q39's positive and adversarial durable-lease control matrix."""

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


CORRECT = '''"""Transactional SQLite job queue with durable lease fencing."""

from __future__ import annotations

import json
import math
import sqlite3


class LeaseError(RuntimeError):
    pass


def _identifier(value, name):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _number(value, name, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f"{name} is outside its domain")
    return value


def _priority(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("priority must be an integer")
    return value


def _token(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("lease_token must be a positive integer")
    return value


class JobQueue:
    def __init__(self, database_path, clock):
        self.database_path = str(database_path)
        self.clock = clock
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    worker TEXT,
                    lease_until REAL,
                    lease_token INTEGER NOT NULL DEFAULT 0,
                    completed INTEGER NOT NULL DEFAULT 0
                )
            """)
            columns = {row[1] for row in connection.execute(
                "PRAGMA table_info(jobs)")}
            if "lease_token" not in columns:
                connection.execute(
                    "ALTER TABLE jobs ADD COLUMN lease_token INTEGER NOT NULL DEFAULT 0")

    def _connect(self):
        return sqlite3.connect(self.database_path, timeout=5, isolation_level=None)

    def _now(self):
        return _number(self.clock(), "clock")

    def enqueue(self, job_id, payload, priority=0, created_at=None):
        job_id = _identifier(job_id, "job_id")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a JSON object")
        encoded = json.dumps(payload, allow_nan=False, separators=(",", ":"))
        priority = _priority(priority)
        created_at = self._now() if created_at is None else _number(
            created_at, "created_at")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO jobs (id, payload, priority, created_at) VALUES (?, ?, ?, ?)",
                (job_id, encoded, priority, created_at),
            )

    def claim(self, worker, lease_seconds):
        worker = _identifier(worker, "worker")
        lease_seconds = _number(lease_seconds, "lease_seconds", positive=True)
        now = self._now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("""
                SELECT id, payload, priority, created_at, lease_token
                FROM jobs
                WHERE completed = 0
                  AND (lease_until IS NULL OR lease_until <= ?)
                ORDER BY priority DESC, created_at ASC, id ASC
                LIMIT 1
            """, (now,)).fetchone()
            if row is None:
                connection.commit()
                return None
            token = row[4] + 1
            until = now + lease_seconds
            connection.execute("""
                UPDATE jobs
                SET worker = ?, lease_until = ?, lease_token = ?
                WHERE id = ?
            """, (worker, until, token, row[0]))
            connection.commit()
            return {
                "id": row[0], "payload": json.loads(row[1]),
                "priority": row[2], "created_at": row[3],
                "lease_token": token, "lease_until": until,
            }
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def heartbeat(self, job_id, worker, lease_token, lease_seconds):
        job_id = _identifier(job_id, "job_id")
        worker = _identifier(worker, "worker")
        lease_token = _token(lease_token)
        lease_seconds = _number(lease_seconds, "lease_seconds", positive=True)
        now = self._now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("""
                SELECT lease_until FROM jobs
                WHERE id = ? AND completed = 0 AND worker = ?
                  AND lease_token = ? AND lease_until > ?
            """, (job_id, worker, lease_token, now)).fetchone()
            if row is None:
                raise LeaseError("lease is stale or expired")
            until = max(now, row[0]) + lease_seconds
            connection.execute(
                "UPDATE jobs SET lease_until = ? WHERE id = ?",
                (until, job_id),
            )
            connection.commit()
            return until
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def complete(self, job_id, worker, lease_token):
        job_id = _identifier(job_id, "job_id")
        worker = _identifier(worker, "worker")
        lease_token = _token(lease_token)
        now = self._now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute("""
                UPDATE jobs
                SET completed = 1, worker = NULL, lease_until = NULL
                WHERE id = ? AND completed = 0 AND worker = ?
                  AND lease_token = ? AND lease_until > ?
            """, (job_id, worker, lease_token, now)).rowcount
            if changed != 1:
                raise LeaseError("lease is stale or expired")
            connection.commit()
            return True
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
'''


def _implementation(state: str) -> str:
    source = CORRECT
    if state == "deferred_claim":
        source = source.replace(
            'connection.execute("BEGIN IMMEDIATE")',
            'connection.execute("BEGIN")', 1)
        source = source.replace("import sqlite3\n", "import sqlite3\nimport time\n")
        source = source.replace(
            "            token = row[4] + 1",
            "            time.sleep(0.05)\n            token = row[4] + 1")
    elif state == "exclusive_expiry":
        source = source.replace("lease_until <= ?", "lease_until < ?", 1)
    elif state == "skipping_token":
        source = source.replace("token = row[4] + 1", "token = row[4] + 2")
    elif state == "heartbeat_from_now":
        source = source.replace(
            "until = max(now, row[0]) + lease_seconds",
            "until = now + lease_seconds")
    elif state == "heartbeat_unfenced":
        source = source.replace(
            "WHERE id = ? AND completed = 0 AND worker = ?\n"
            "                  AND lease_token = ? AND lease_until > ?",
            "WHERE id = ? AND completed = 0 AND ? = ?\n"
            "                  AND ? = ? AND lease_until > ?", 1)
        source = source.replace(
            "(job_id, worker, lease_token, now)).fetchone()",
            "(job_id, worker, worker, lease_token, lease_token, now)).fetchone()")
    elif state == "complete_expired":
        source = source.replace(
            "AND lease_token = ? AND lease_until > ?\n"
            "            \"\"\", (job_id, worker, lease_token, now)).rowcount",
            "AND lease_token = ? AND ? = ?\n"
            "            \"\"\", (job_id, worker, lease_token, now, now)).rowcount")
    elif state == "no_token_fence":
        source = source.replace(
            "AND lease_token = ? AND lease_until > ?\n"
            "            \"\"\", (job_id, worker, lease_token, now)).rowcount",
            "AND ? = ? AND lease_until > ?\n"
            "            \"\"\", (job_id, worker, lease_token, lease_token, now)).rowcount")
    elif state == "unstable_id_order":
        source = source.replace(
            "ORDER BY priority DESC, created_at ASC, id ASC",
            "ORDER BY priority DESC, created_at ASC")
    elif state == "replace_duplicate":
        source = source.replace("INSERT INTO jobs", "INSERT OR REPLACE INTO jobs")
    elif state == "no_validation":
        source = source.replace(
            '        job_id = _identifier(job_id, "job_id")\n'
            '        if not isinstance(payload, dict):\n'
            '            raise TypeError("payload must be a JSON object")\n'
            '        encoded = json.dumps(payload, allow_nan=False, separators=(",", ":"))\n'
            '        priority = _priority(priority)\n'
            '        created_at = self._now() if created_at is None else _number(\n'
            '            created_at, "created_at")',
            '        encoded = json.dumps(payload)\n'
            '        created_at = self._now() if created_at is None else created_at')
    elif state == "fresh_schema_only":
        source = source.replace(
            '            columns = {row[1] for row in connection.execute(\n'
            '                "PRAGMA table_info(jobs)")}\n'
            '            if "lease_token" not in columns:\n'
            '                connection.execute(\n'
            '                    "ALTER TABLE jobs ADD COLUMN lease_token INTEGER NOT NULL DEFAULT 0")\n',
            '')
    return source


def _apply(state: str, repo: Path) -> None:
    if state == "baseline":
        return
    valid = {
        "correct", "deferred_claim", "exclusive_expiry", "skipping_token",
        "heartbeat_from_now", "heartbeat_unfenced", "complete_expired",
        "no_token_fence", "unstable_id_order", "replace_duplicate",
        "no_validation", "fresh_schema_only", "tamper",
    }
    if state not in valid:
        raise ValueError(state)
    implementation = "correct" if state == "tamper" else state
    (repo / "job_queue.py").write_text(
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
        "baseline", "correct", "deferred_claim", "exclusive_expiry",
        "skipping_token", "heartbeat_from_now", "heartbeat_unfenced",
        "complete_expired", "no_token_fence", "unstable_id_order",
        "replace_duplicate", "no_validation", "fresh_schema_only", "tamper",
    )
    results = {}
    with tempfile.TemporaryDirectory(prefix="llm-hardtest-r5-q39-") as tmp:
        for state in states:
            repo = Path(tmp) / state
            shutil.copytree(SOURCE, repo)
            _apply(state, repo)
            public = _run([sys.executable, "run_tests.py"], repo)
            hidden = _run([sys.executable, str(HIDDEN), str(repo)], repo)
            results[state] = (public[:2], hidden[:2])
            print(f"{state:22} public {public[0]}/{public[1]} "
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
        return 1
    print("PILOT_CONTROL_MATRIX=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

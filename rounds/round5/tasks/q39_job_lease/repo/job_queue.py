"""Incomplete SQLite-backed job queue with lease-fencing bugs."""

from __future__ import annotations

import json
import sqlite3


class LeaseError(RuntimeError):
    pass


class JobQueue:
    def __init__(self, database_path, clock):
        self.database_path = str(database_path)
        self.clock = clock
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    worker TEXT,
                    lease_until REAL,
                    completed INTEGER NOT NULL DEFAULT 0
                )
            """)

    def enqueue(self, job_id, payload, priority=0, created_at=None):
        timestamp = self.clock() if created_at is None else created_at
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO jobs VALUES (?, ?, ?, ?, NULL, NULL, 0)",
                (job_id, json.dumps(payload), priority, timestamp),
            )

    def claim(self, worker, lease_seconds):
        now = self.clock()
        connection = sqlite3.connect(self.database_path)
        try:
            row = connection.execute("""
                SELECT id, payload, priority, created_at FROM jobs
                WHERE completed = 0 AND (lease_until IS NULL OR lease_until <= ?)
                ORDER BY priority DESC, created_at ASC, id ASC LIMIT 1
            """, (now,)).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE jobs SET worker = ?, lease_until = ? WHERE id = ?",
                (worker, now + lease_seconds, row[0]),
            )
            connection.commit()
            return {
                "id": row[0], "payload": json.loads(row[1]),
                "priority": row[2], "created_at": row[3],
                "lease_token": 1, "lease_until": now + lease_seconds,
            }
        finally:
            connection.close()

    def heartbeat(self, job_id, worker, lease_token, lease_seconds):
        until = self.clock() + lease_seconds
        with sqlite3.connect(self.database_path) as connection:
            changed = connection.execute(
                "UPDATE jobs SET lease_until = ? WHERE id = ? AND completed = 0",
                (until, job_id),
            ).rowcount
        if changed != 1:
            raise LeaseError("job is unavailable")
        return until

    def complete(self, job_id, worker, lease_token):
        with sqlite3.connect(self.database_path) as connection:
            changed = connection.execute(
                "UPDATE jobs SET completed = 1 WHERE id = ? AND completed = 0",
                (job_id,),
            ).rowcount
        if changed != 1:
            raise LeaseError("job is unavailable")
        return True

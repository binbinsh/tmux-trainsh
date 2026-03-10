# SQLite-backed pool slot manager used by the scheduler loop.

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Mapping, Optional


@dataclass
class PoolStats:
    pool: str
    slots: int
    occupied: int


class SqlitePoolManager:
    """Track pool slot capacity and currently occupied slots in sqlite.

    It behaves as a shared, crash-safe lock-like structure. Each execution run
    uses the same database file and sees the same occupancy counts.
    """

    def __init__(self, db_path: str, default_slots: Optional[Mapping[str, int]] = None):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._ensure_schema()
        self._register_defaults(default_slots or {"default": 0})

    def _ensure_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS slot_pool (
                pool TEXT PRIMARY KEY,
                slots INTEGER NOT NULL DEFAULT 1,
                occupied INTEGER NOT NULL DEFAULT 0,
                description TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_slot_pool_updated_at ON slot_pool(updated_at)"
        )
        self.conn.commit()

    def _utcnow(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _register_defaults(self, values: Mapping[str, int]) -> None:
        now = self._utcnow()
        for pool_name, slots in values.items():
            self._upsert_pool(str(pool_name), slots, now=now)

    def _upsert_pool(self, pool_name: str, slots: int, now: Optional[str] = None) -> None:
        now = now or self._utcnow()
        normalized = max(1, int(slots))
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO slot_pool (pool, slots, occupied, description, created_at, updated_at)
                VALUES (?, ?, 0, '', ?, ?)
                ON CONFLICT(pool) DO UPDATE SET
                    slots = CASE
                        WHEN excluded.slots > 0 THEN excluded.slots
                        ELSE slot_pool.slots
                    END,
                    updated_at = excluded.updated_at
                """,
                (pool_name, normalized, now, now),
            )

    def ensure_pool(self, pool_name: str, slots: int) -> None:
        self._upsert_pool(str(pool_name), slots)

    def sync_slots(self, pool_limits: Mapping[str, int]) -> None:
        for pool_name, slots in pool_limits.items():
            self.ensure_pool(pool_name, slots)

    def refresh(self) -> Dict[str, PoolStats]:
        cursor = self.conn.execute("SELECT pool, slots, occupied FROM slot_pool")
        data = {}
        for pool_name, slots, occupied in cursor.fetchall():
            data[pool_name] = PoolStats(pool=pool_name, slots=int(slots), occupied=int(occupied))
        return data

    def get_stats(self, pool_name: str) -> PoolStats:
        pool_name = str(pool_name)
        cursor = self.conn.execute(
            "SELECT pool, slots, occupied FROM slot_pool WHERE pool = ?",
            (pool_name,),
        )
        row = cursor.fetchone()
        if row:
            return PoolStats(pool=row[0], slots=int(row[1]), occupied=int(row[2]))
        stats = PoolStats(pool_name, 1, 0)
        self.ensure_pool(pool_name, 1)
        return stats

    def has_capacity(self, pool_name: str, request_slots: int = 1) -> bool:
        request_slots = max(1, int(request_slots))
        if request_slots <= 0:
            return True
        stats = self.get_stats(pool_name)
        return stats.occupied + request_slots <= stats.slots

    def try_acquire(self, pool_name: str, request_slots: int = 1) -> bool:
        request_slots = max(1, int(request_slots))
        if request_slots <= 0:
            return True
        pool_name = str(pool_name)
        now = self._utcnow()
        with self._lock, self.conn:
            row = self.conn.execute(
                "SELECT slots, occupied FROM slot_pool WHERE pool = ?",
                (pool_name,),
            ).fetchone()
            if row is None:
                self._upsert_pool(pool_name, 1, now=now)
                slots, occupied = 1, 0
            else:
                slots, occupied = int(row[0]), int(row[1])
            if occupied + request_slots > slots:
                return False
            self.conn.execute(
                """
                UPDATE slot_pool
                SET occupied = occupied + ?,
                    updated_at = ?
                WHERE pool = ?
                """,
                (request_slots, now, pool_name),
            )
            return True

    def release(self, pool_name: str, request_slots: int = 1) -> None:
        request_slots = max(1, int(request_slots))
        if request_slots <= 0:
            return
        pool_name = str(pool_name)
        now = self._utcnow()
        with self._lock, self.conn:
            self.conn.execute(
                """
                UPDATE slot_pool
                SET occupied = CASE
                        WHEN occupied - ? < 0 THEN 0
                        ELSE occupied - ?
                    END,
                    updated_at = ?
                WHERE pool = ?
                """,
                (request_slots, request_slots, now, pool_name),
            )
            if self.conn.total_changes == 0:
                self._upsert_pool(pool_name, 1, now=now)

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

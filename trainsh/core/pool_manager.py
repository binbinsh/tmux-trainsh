# JSON-backed pool slot manager used by the scheduler loop.

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Mapping, Optional

from .runtime_store import RuntimeStore


@dataclass
class PoolStats:
    pool: str
    slots: int
    occupied: int


class RuntimeStatePoolManager:
    """Track pool slot capacity and occupancy in a JSON state file."""

    def __init__(self, db_path: str, default_slots: Optional[Mapping[str, int]] = None):
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self._closed = False
        self.store = RuntimeStore(db_path)
        self._register_defaults(default_slots or {"default": 0})

    def _utcnow(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _normalize_slots(self, slots: int) -> int:
        return max(1, int(slots))

    def _load(self) -> Dict[str, Dict[str, int | str]]:
        return self.store.load_pools()

    def _save(self, pools: Dict[str, Dict[str, int | str]]) -> None:
        self.store.save_pools(pools)

    def _register_defaults(self, values: Mapping[str, int]) -> None:
        now = self._utcnow()
        pools = self._load()
        changed = False
        for pool_name, slots in values.items():
            name = str(pool_name)
            payload = pools.get(name)
            normalized = self._normalize_slots(slots)
            if payload is None:
                pools[name] = {"slots": normalized, "occupied": 0, "updated_at": now}
                changed = True
        if changed:
            self._save(pools)

    def ensure_pool(self, pool_name: str, slots: int) -> None:
        now = self._utcnow()
        with self._lock:
            pools = self._load()
            name = str(pool_name)
            payload = pools.get(name, {"slots": 1, "occupied": 0})
            payload["slots"] = self._normalize_slots(slots)
            payload["occupied"] = int(payload.get("occupied", 0) or 0)
            payload["updated_at"] = now
            pools[name] = payload
            self._save(pools)

    def sync_slots(self, pool_limits: Mapping[str, int]) -> None:
        for pool_name, slots in pool_limits.items():
            self.ensure_pool(pool_name, slots)

    def refresh(self) -> Dict[str, PoolStats]:
        pools = self._load()
        return {
            str(name): PoolStats(
                pool=str(name),
                slots=int(payload.get("slots", 1) or 1),
                occupied=int(payload.get("occupied", 0) or 0),
            )
            for name, payload in pools.items()
        }

    def get_stats(self, pool_name: str) -> PoolStats:
        name = str(pool_name)
        pools = self._load()
        payload = pools.get(name)
        if payload is None:
            self.ensure_pool(name, 1)
            pools = self._load()
            payload = pools.get(name, {"slots": 1, "occupied": 0})
        return PoolStats(
            pool=name,
            slots=int(payload.get("slots", 1) or 1),
            occupied=int(payload.get("occupied", 0) or 0),
        )

    def has_capacity(self, pool_name: str, request_slots: int = 1) -> bool:
        request_slots = max(1, int(request_slots))
        stats = self.get_stats(pool_name)
        return stats.occupied + request_slots <= stats.slots

    def try_acquire(self, pool_name: str, request_slots: int = 1) -> bool:
        request_slots = max(1, int(request_slots))
        name = str(pool_name)
        now = self._utcnow()
        with self._lock:
            pools = self._load()
            payload = pools.get(name, {"slots": 1, "occupied": 0, "updated_at": now})
            slots = int(payload.get("slots", 1) or 1)
            occupied = int(payload.get("occupied", 0) or 0)
            if occupied + request_slots > slots:
                return False
            payload["slots"] = slots
            payload["occupied"] = occupied + request_slots
            payload["updated_at"] = now
            pools[name] = payload
            self._save(pools)
            return True

    def release(self, pool_name: str, request_slots: int = 1) -> None:
        request_slots = max(1, int(request_slots))
        name = str(pool_name)
        now = self._utcnow()
        with self._lock:
            pools = self._load()
            payload = pools.get(name, {"slots": 1, "occupied": 0, "updated_at": now})
            payload["slots"] = int(payload.get("slots", 1) or 1)
            payload["occupied"] = max(0, int(payload.get("occupied", 0) or 0) - request_slots)
            payload["updated_at"] = now
            pools[name] = payload
            self._save(pools)

    def close(self) -> None:
        self._closed = True

    def __enter__(self) -> "RuntimeStatePoolManager":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def __del__(self):
        self.close()

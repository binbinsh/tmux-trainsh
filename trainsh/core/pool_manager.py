# JSON-backed pool slot manager used by the scheduler loop.

from __future__ import annotations

import os
import uuid
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

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
        self._pid = os.getpid()
        self._held_leases: Dict[str, list[str]] = {}
        self.store = RuntimeStore(db_path)
        self._register_defaults(default_slots or {"default": 0})

    def _utcnow(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _normalize_slots(self, slots: int) -> int:
        return max(1, int(slots))

    def _normalize_occupied(self, occupied: object) -> int:
        try:
            return max(0, int(occupied or 0))
        except Exception:
            return 0

    def _pid_alive(self, pid: object) -> bool:
        try:
            pid_value = int(pid or 0)
        except Exception:
            return False
        if pid_value <= 0:
            return False
        try:
            os.kill(pid_value, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _normalize_leases(
        self,
        leases: object,
        *,
        now: str,
    ) -> tuple[Dict[str, Dict[str, int | str]], bool]:
        if not isinstance(leases, dict):
            return {}, bool(leases is not None)

        normalized: Dict[str, Dict[str, int | str]] = {}
        changed = False
        for lease_id, payload in leases.items():
            if not isinstance(payload, dict):
                changed = True
                continue

            pid = payload.get("pid")
            if not self._pid_alive(pid):
                changed = True
                continue

            lease_key = str(lease_id).strip()
            if not lease_key:
                changed = True
                continue

            slots = self._normalize_slots(payload.get("slots", 1))
            created_at = str(payload.get("created_at") or now)
            updated_at = str(payload.get("updated_at") or created_at)
            normalized[lease_key] = {
                "pid": int(pid),
                "slots": slots,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        return normalized, changed or len(normalized) != len(leases)

    def _reconcile_pool_payload(
        self,
        payload: object,
        *,
        now: Optional[str] = None,
    ) -> tuple[Dict[str, Any], bool]:
        moment = now or self._utcnow()
        raw = dict(payload or {}) if isinstance(payload, dict) else {}
        slots = self._normalize_slots(raw.get("slots", 1))
        normalized = dict(raw)
        normalized["slots"] = slots

        raw_leases = raw.get("leases")
        changed = not isinstance(payload, dict)
        if raw_leases is None:
            occupied = self._normalize_occupied(raw.get("occupied", 0))
        else:
            leases, leases_changed = self._normalize_leases(raw_leases, now=moment)
            occupied = sum(int(item.get("slots", 1) or 1) for item in leases.values())
            normalized["leases"] = leases
            changed = changed or leases_changed

        if occupied != self._normalize_occupied(raw.get("occupied", 0)):
            changed = True
        normalized["occupied"] = occupied

        updated_at = str(raw.get("updated_at") or moment)
        if changed:
            updated_at = moment
        normalized["updated_at"] = updated_at
        return normalized, changed

    def _reconcile_pools(
        self,
        pools: Mapping[str, object],
    ) -> tuple[Dict[str, Dict[str, Any]], bool]:
        now = self._utcnow()
        normalized: Dict[str, Dict[str, Any]] = {}
        changed = False
        for pool_name, payload in dict(pools or {}).items():
            name = str(pool_name)
            reconciled, pool_changed = self._reconcile_pool_payload(payload, now=now)
            normalized[name] = reconciled
            changed = changed or pool_changed or name != pool_name
        return normalized, changed

    def _load_reconciled(self) -> Dict[str, Dict[str, Any]]:
        pools = self._load()
        normalized, changed = self._reconcile_pools(pools)
        if changed:
            self._save(normalized)
        return normalized

    def _lease_usage(self, lease_ids: list[str], leases: Mapping[str, Mapping[str, object]]) -> int:
        released = 0
        for lease_id in lease_ids:
            payload = leases.get(lease_id)
            if payload is None:
                continue
            released += self._normalize_slots(payload.get("slots", 1))
        return released

    def _load(self) -> Dict[str, Dict[str, int | str]]:
        return self.store.load_pools()

    def _save(self, pools: Dict[str, Dict[str, int | str]]) -> None:
        self.store.save_pools(pools)

    def _register_defaults(self, values: Mapping[str, int]) -> None:
        now = self._utcnow()
        with self._lock:
            pools = self._load_reconciled()
            changed = False
            for pool_name, slots in values.items():
                name = str(pool_name)
                payload = pools.get(name)
                normalized = self._normalize_slots(slots)
                if payload is None:
                    pools[name] = {"slots": normalized, "occupied": 0, "updated_at": now, "leases": {}}
                    changed = True
            if changed:
                self._save(pools)

    def ensure_pool(self, pool_name: str, slots: int) -> None:
        now = self._utcnow()
        with self._lock:
            pools = self._load_reconciled()
            name = str(pool_name)
            payload = pools.get(name, {"slots": 1, "occupied": 0, "leases": {}})
            payload["slots"] = self._normalize_slots(slots)
            payload["occupied"] = self._normalize_occupied(payload.get("occupied", 0))
            payload["updated_at"] = now
            pools[name] = payload
            self._save(pools)

    def sync_slots(self, pool_limits: Mapping[str, int]) -> None:
        for pool_name, slots in pool_limits.items():
            self.ensure_pool(pool_name, slots)

    def refresh(self) -> Dict[str, PoolStats]:
        with self._lock:
            pools = self._load_reconciled()
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
        with self._lock:
            pools = self._load_reconciled()
            payload = pools.get(name)
            if payload is None:
                self.ensure_pool(name, 1)
                pools = self._load_reconciled()
                payload = pools.get(name, {"slots": 1, "occupied": 0, "leases": {}})
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
            pools = self._load_reconciled()
            payload = pools.get(name, {"slots": 1, "occupied": 0, "updated_at": now, "leases": {}})
            slots = int(payload.get("slots", 1) or 1)
            occupied = int(payload.get("occupied", 0) or 0)
            if occupied + request_slots > slots:
                return False
            leases = dict(payload.get("leases") or {})
            held = self._held_leases.setdefault(name, [])
            for _ in range(request_slots):
                lease_id = uuid.uuid4().hex
                leases[lease_id] = {
                    "pid": self._pid,
                    "slots": 1,
                    "created_at": now,
                    "updated_at": now,
                }
                held.append(lease_id)
            payload["slots"] = slots
            payload["occupied"] = occupied + request_slots
            payload["leases"] = leases
            payload["updated_at"] = now
            pools[name] = payload
            self._save(pools)
            return True

    def release(self, pool_name: str, request_slots: int = 1) -> None:
        request_slots = max(1, int(request_slots))
        name = str(pool_name)
        now = self._utcnow()
        with self._lock:
            pools = self._load_reconciled()
            payload = pools.get(name, {"slots": 1, "occupied": 0, "updated_at": now, "leases": {}})
            leases = dict(payload.get("leases") or {})
            held = self._held_leases.get(name, [])
            removed_ids: list[str] = []
            released_slots = 0
            while held and released_slots < request_slots:
                lease_id = held.pop()
                released_slots += self._lease_usage([lease_id], leases)
                removed_ids.append(lease_id)
            for lease_id in removed_ids:
                leases.pop(lease_id, None)
            if held:
                self._held_leases[name] = held
            else:
                self._held_leases.pop(name, None)

            payload["slots"] = int(payload.get("slots", 1) or 1)
            if leases:
                payload["occupied"] = sum(int(item.get("slots", 1) or 1) for item in leases.values())
            else:
                payload["occupied"] = max(
                    0,
                    int(payload.get("occupied", 0) or 0) - max(request_slots, released_slots),
                )
            payload["leases"] = leases
            payload["updated_at"] = now
            pools[name] = payload
            self._save(pools)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            held = {name: list(lease_ids) for name, lease_ids in self._held_leases.items() if lease_ids}
            if held:
                now = self._utcnow()
                pools = self._load_reconciled()
                changed = False
                for name, lease_ids in held.items():
                    payload = pools.get(name)
                    if payload is None:
                        continue
                    leases = dict(payload.get("leases") or {})
                    removed = False
                    for lease_id in lease_ids:
                        if lease_id in leases:
                            leases.pop(lease_id, None)
                            removed = True
                    if not removed:
                        continue
                    payload["leases"] = leases
                    payload["occupied"] = sum(int(item.get("slots", 1) or 1) for item in leases.values())
                    payload["updated_at"] = now
                    pools[name] = payload
                    changed = True
                self._held_leases.clear()
                if changed:
                    self._save(pools)
        self._closed = True

    def __enter__(self) -> "RuntimeStatePoolManager":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def __del__(self):
        self.close()

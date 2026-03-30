import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from trainsh.core.pool_manager import RuntimeStatePoolManager


class RuntimeStatePoolManagerTests(unittest.TestCase):
    def test_utcnow_is_timezone_aware_isoformat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = RuntimeStatePoolManager(str(Path(tmpdir) / "runtime.db"))
            try:
                stamp = manager._utcnow()
            finally:
                manager.close()

        parsed = datetime.fromisoformat(stamp)
        self.assertIsNotNone(parsed.tzinfo)
        self.assertIsNotNone(parsed.utcoffset())

    def test_try_acquire_and_release_respect_pool_capacity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = RuntimeStatePoolManager(str(Path(tmpdir) / "runtime.db"), default_slots={"gpu": 2})
            try:
                self.assertTrue(manager.try_acquire("gpu"))
                self.assertTrue(manager.try_acquire("gpu"))
                self.assertFalse(manager.try_acquire("gpu"))
                self.assertEqual(manager.get_stats("gpu").occupied, 2)
                self.assertEqual(len(manager.store.load_pools()["gpu"].get("leases", {})), 2)

                manager.release("gpu")
                self.assertEqual(manager.get_stats("gpu").occupied, 1)

                manager.release("gpu", request_slots=5)
                self.assertEqual(manager.get_stats("gpu").occupied, 0)
                self.assertEqual(manager.store.load_pools()["gpu"].get("leases", {}), {})
            finally:
                manager.close()

    def test_refresh_reaps_dead_pid_leases_and_recomputes_occupied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = RuntimeStatePoolManager(str(Path(tmpdir) / "runtime.db"), default_slots={"default": 1})
            try:
                manager.store.save_pools(
                    {
                        "default": {
                            "slots": 1,
                            "occupied": 1,
                            "updated_at": "2026-03-31T00:00:00+00:00",
                            "leases": {
                                "stale": {
                                    "pid": 999999999,
                                    "slots": 1,
                                    "created_at": "2026-03-30T00:00:00+00:00",
                                    "updated_at": "2026-03-30T00:00:00+00:00",
                                }
                            },
                        }
                    }
                )

                stats = manager.refresh()

                self.assertEqual(stats["default"].occupied, 0)
                stored = manager.store.load_pools()["default"]
                self.assertEqual(stored["occupied"], 0)
                self.assertEqual(stored.get("leases", {}), {})
                self.assertTrue(manager.try_acquire("default"))
            finally:
                manager.close()

    def test_context_manager_and_missing_pool_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "runtime.db"
            with RuntimeStatePoolManager(str(db_path), default_slots={"default": 2}) as manager:
                stats = manager.get_stats("missing")
                self.assertEqual(stats.pool, "missing")
                self.assertTrue(manager.has_capacity("missing", 0))
                self.assertTrue(manager.try_acquire("fresh", 0))
                manager.release("fresh", 0)
                manager.release("unknown", 1)
                self.assertGreaterEqual(manager.get_stats("unknown").slots, 1)
            self.assertTrue(manager._closed)
            manager.close()

        manager = RuntimeStatePoolManager(":memory:")
        manager.close()
        self.assertTrue(manager._closed)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from trainsh.core.pool_manager import SqlitePoolManager


class SqlitePoolManagerTests(unittest.TestCase):
    def test_utcnow_is_timezone_aware_isoformat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SqlitePoolManager(str(Path(tmpdir) / "runtime.db"))
            try:
                stamp = manager._utcnow()
            finally:
                manager.close()

        parsed = datetime.fromisoformat(stamp)
        self.assertIsNotNone(parsed.tzinfo)
        self.assertIsNotNone(parsed.utcoffset())

    def test_try_acquire_and_release_respect_pool_capacity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SqlitePoolManager(str(Path(tmpdir) / "runtime.db"), default_slots={"gpu": 2})
            try:
                self.assertTrue(manager.try_acquire("gpu"))
                self.assertTrue(manager.try_acquire("gpu"))
                self.assertFalse(manager.try_acquire("gpu"))
                self.assertEqual(manager.get_stats("gpu").occupied, 2)

                manager.release("gpu")
                self.assertEqual(manager.get_stats("gpu").occupied, 1)

                manager.release("gpu", request_slots=5)
                self.assertEqual(manager.get_stats("gpu").occupied, 0)
            finally:
                manager.close()


if __name__ == "__main__":
    unittest.main()

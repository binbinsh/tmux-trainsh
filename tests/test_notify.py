import unittest
from unittest.mock import patch

from trainsh.core.dsl_parser import DSLRecipe
from trainsh.core.executor_main import DSLExecutor
from trainsh.utils.notifier import Notifier


class NotifierTests(unittest.TestCase):
    def test_log_channel_success(self):
        logs = []
        notifier = Notifier(log_callback=logs.append, app_name="train")

        ok, summary = notifier.notify(
            title="Train",
            message="Job complete",
            level="success",
            channels=["log"],
        )

        self.assertTrue(ok)
        self.assertIn("via log", summary)
        self.assertTrue(any("Job complete" in line for line in logs))

    def test_webhook_missing_url_fails(self):
        logs = []
        notifier = Notifier(log_callback=logs.append, app_name="train")

        ok, summary = notifier.notify(
            title="Train",
            message="Job complete",
            level="info",
            channels=["webhook"],
        )

        self.assertFalse(ok)
        self.assertIn("webhook URL missing", summary)

    def test_fail_on_error_switches_result(self):
        logs = []
        notifier = Notifier(log_callback=logs.append, app_name="train")

        ok_relaxed, _ = notifier.notify(
            title="Train",
            message="Job complete",
            level="info",
            channels=["log", "webhook"],
            fail_on_error=False,
        )
        ok_strict, _ = notifier.notify(
            title="Train",
            message="Job complete",
            level="info",
            channels=["log", "webhook"],
            fail_on_error=True,
        )

        self.assertTrue(ok_relaxed)
        self.assertFalse(ok_strict)

    def test_system_uses_osascript_on_macos(self):
        logs = []
        notifier = Notifier(log_callback=logs.append, app_name="train")

        with patch("trainsh.utils.notifier.sys.platform", "darwin"):
            with patch.object(notifier, "_run_cmd", return_value=(True, "ok")) as run_mock:
                ok, summary = notifier.notify(
                    title="Train",
                    message="Job complete",
                    level="info",
                    channels=["system"],
                )

        self.assertTrue(ok)
        self.assertIn("via system", summary)
        run_mock.assert_called_once()
        args, _ = run_mock.call_args
        self.assertEqual(args[0][0], "osascript")

    def test_system_non_macos_is_reported(self):
        logs = []
        notifier = Notifier(log_callback=logs.append, app_name="train")

        with patch("trainsh.utils.notifier.sys.platform", "linux"):
            ok, summary = notifier.notify(
                title="Train",
                message="Job complete",
                level="info",
                channels=["system"],
            )

        self.assertFalse(ok)
        self.assertIn("Unsupported system notification platform", summary)


class ExecutorNotifyTests(unittest.TestCase):
    def _new_executor(self, logs):
        recipe = DSLRecipe(name="notify-test")
        return DSLExecutor(recipe, log_callback=logs.append, recipe_path=None)

    def test_simple_notify_message(self):
        logs = []
        executor = self._new_executor(logs)

        ok, summary = executor._cmd_notify(["Disk", "almost", "full"])

        self.assertTrue(ok)
        self.assertIn("via", summary)
        self.assertTrue(any("Disk almost full" in line for line in logs))

    def test_notify_interpolates_simple_var(self):
        logs = []
        executor = self._new_executor(logs)
        executor.ctx.variables["MSG"] = "hello"

        ok, _ = executor._cmd_notify(["$MSG"])

        self.assertTrue(ok)
        self.assertTrue(any("hello" in line for line in logs))

    def test_notify_requires_message(self):
        logs = []
        executor = self._new_executor(logs)

        ok, error = executor._cmd_notify([])

        self.assertFalse(ok)
        self.assertIn("Usage: notify", error)

    def test_notify_treats_key_like_text_as_message(self):
        logs = []
        executor = self._new_executor(logs)

        ok, summary = executor._cmd_notify(["foo=bar"])

        self.assertTrue(ok)
        self.assertIn("via", summary)


if __name__ == "__main__":
    unittest.main()

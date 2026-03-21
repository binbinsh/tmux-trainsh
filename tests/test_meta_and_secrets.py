import io
import runpy
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import trainsh
from trainsh.commands import recipe, recipe_cmd, secrets_cmd
import trainsh.core.secrets as secrets_core
from trainsh.services import pricing as pricing_service
from trainsh.utils import update_checker


class CaptureMixin:
    def capture(self, fn, *args, **kwargs):
        out = io.StringIO()
        code = None
        with redirect_stdout(out):
            try:
                result = fn(*args, **kwargs)
            except SystemExit as exc:
                result = None
                code = exc.code
        return out.getvalue(), code, result


class PackageMetaTests(CaptureMixin, unittest.TestCase):
    def test_package_helpers_and_main_wrapper(self):
        self.assertTrue(trainsh.__display_version__)
        self.assertEqual(trainsh.__display_version__, trainsh.__version__)
        self.assertIn("main", trainsh.__all__)

        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject = Path(tmpdir) / "pyproject.toml"
            pyproject.write_text('version = "9.9.9"\n', encoding="utf-8")
            with patch("trainsh.Path.resolve", return_value=Path(tmpdir) / "trainsh" / "__init__.py"):
                self.assertEqual(trainsh._read_local_version(), "9.9.9")

        with patch.dict("os.environ", {"TRAINSH_BUILD_NUMBER": "42"}):
            self.assertEqual(trainsh._resolve_build_number(), 42)
        with patch.dict("os.environ", {"TRAINSH_BUILD_NUMBER": "bad"}, clear=False), patch(
            "subprocess.check_output", return_value="7\n"
        ):
            self.assertEqual(trainsh._resolve_build_number(), 7)


    def test_module_entrypoint_invokes_main(self):
        with patch("trainsh.main.main", return_value=None) as mocked_main:
            with patch("sys.argv", ["python", "--help"]):
                runpy.run_module("trainsh", run_name="__main__")
        mocked_main.assert_called_once_with(["python", "--help"])


class SecretsCommandTests(CaptureMixin, unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        config_dir = Path(self._tmp.name) / ".config" / "tmux-trainsh"
        config_dir.mkdir(parents=True, exist_ok=True)
        self._patches = [
            patch.object(secrets_core, "CONFIG_DIR", config_dir),
            patch.object(secrets_core, "CONFIG_FILE", config_dir / "config.yaml"),
            patch.object(secrets_core, "_ENC_FILE", config_dir / "secrets.enc"),
        ]
        for p in self._patches:
            p.start()
        secrets_core._secrets_manager = None

    def tearDown(self):
        secrets_core._secrets_manager = None
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    def test_list_get_set_remove_and_main(self):
        backend = SimpleNamespace(get=lambda key: "secret" if key == "VAST_API_KEY" else None)
        secrets = SimpleNamespace(_get_backend=lambda: backend, set=lambda key, value: None, get=lambda key: "abcdefgh1234", delete=lambda key: None)

        with patch("trainsh.core.secrets.get_secrets_manager", return_value=secrets), patch(
            "trainsh.core.secrets.get_configured_backend_name", return_value="encrypted_file"
        ):
            out, code, _ = self.capture(secrets_cmd.cmd_list, [])
        self.assertIsNone(code)
        self.assertIn("Backend:", out)
        self.assertIn("VAST_API_KEY", out)

        out, code, _ = self.capture(secrets_cmd.main, [])
        self.assertIsNone(code)
        self.assertIn("train secrets", out)

        out, code, _ = self.capture(secrets_cmd.cmd_get, [])
        self.assertEqual(code, 1)
        self.assertIn("Usage: train secrets get <key>", out)

        with patch("trainsh.core.secrets.get_secrets_manager", return_value=secrets):
            out, code, _ = self.capture(secrets_cmd.cmd_get, ["OPENAI_API_KEY"])
        self.assertIsNone(code)
        self.assertIn("abcd", out)

        empty_secrets = SimpleNamespace(get=lambda key: None)
        with patch("trainsh.core.secrets.get_secrets_manager", return_value=empty_secrets):
            out, code, _ = self.capture(secrets_cmd.cmd_get, ["OPENAI_API_KEY"])
        self.assertIsNone(code)
        self.assertIn("[not set]", out)

        with patch("getpass.getpass", return_value="secret-value"), patch(
            "trainsh.core.secrets.get_secrets_manager", return_value=secrets
        ):
            out, code, _ = self.capture(secrets_cmd.cmd_set, ["HF_TOKEN"])
        self.assertIsNone(code)
        self.assertIn("Successfully set HF_TOKEN", out)

        with patch("getpass.getpass", return_value=""):
            out, code, _ = self.capture(secrets_cmd.cmd_set, ["HF_TOKEN"])
        self.assertIsNone(code)
        self.assertIn("Cancelled - no value provided.", out)

        with patch("getpass.getpass", side_effect=KeyboardInterrupt):
            out, code, _ = self.capture(secrets_cmd.cmd_set, ["HF_TOKEN"])
        self.assertIsNone(code)
        self.assertIn("Cancelled.", out)

        failing_secrets = SimpleNamespace(set=lambda key, value: (_ for _ in ()).throw(RuntimeError("boom")))
        with patch("getpass.getpass", return_value="secret-value"), patch(
            "trainsh.core.secrets.get_secrets_manager", return_value=failing_secrets
        ):
            out, code, _ = self.capture(secrets_cmd.cmd_set, ["HF_TOKEN"])
        self.assertEqual(code, 1)
        self.assertIn("Error: boom", out)

        out, code, _ = self.capture(secrets_cmd.cmd_delete, [])
        self.assertEqual(code, 1)
        self.assertIn("Usage: train secrets remove <key>", out)

        with patch("trainsh.commands.secrets_cmd.prompt_input", return_value="n"):
            out, code, _ = self.capture(secrets_cmd.cmd_delete, ["HF_TOKEN"])
        self.assertIsNone(code)
        self.assertIn("Cancelled.", out)

        with patch("trainsh.commands.secrets_cmd.prompt_input", return_value="y"), patch(
            "trainsh.core.secrets.get_secrets_manager", return_value=secrets
        ):
            out, code, _ = self.capture(secrets_cmd.cmd_delete, ["HF_TOKEN"])
        self.assertIsNone(code)
        self.assertIn("Deleted HF_TOKEN", out)

        out, code, _ = self.capture(secrets_cmd.main, ["unknown"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown subcommand", out)

    def test_backend_command_paths(self):
        with patch("trainsh.core.secrets.get_configured_backend_name", return_value="encrypted_file"), patch(
            "trainsh.core.secrets._BACKEND_NAMES", {"encrypted_file": "Encrypted File", "1password": "1Password", "keyring": "Keyring"}
        ):
            out, code, _ = self.capture(secrets_cmd.cmd_backend, [])
        self.assertIsNone(code)
        self.assertIn("Current backend: Encrypted File", out)

        out, code, _ = self.capture(secrets_cmd.cmd_backend, ["bad"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown backend", out)

        with patch("trainsh.core.secrets._BACKEND_NAMES", {"1password": "1Password"}), patch(
            "trainsh.core.secrets._op_available", return_value=False
        ), patch("trainsh.commands.secrets_cmd.prompt_input", return_value="n"):
            out, code, _ = self.capture(secrets_cmd.cmd_backend, ["1password"])
        self.assertIsNone(code)
        self.assertIn("Cancelled.", out)

        with patch("trainsh.core.secrets._BACKEND_NAMES", {"1password": "1Password", "encrypted_file": "Encrypted File"}), patch(
            "trainsh.core.secrets._op_available", return_value=False
        ), patch("trainsh.commands.secrets_cmd.prompt_input", return_value="y"), patch(
            "trainsh.core.secrets._resolve_op_auth", return_value=False
        ), patch(
            "trainsh.core.secrets.set_backend"
        ) as mocked_set:
            out, code, _ = self.capture(secrets_cmd.cmd_backend, ["1password"])
        self.assertIsNone(code)
        mocked_set.assert_called_once()
        self.assertIn("Falling back to encrypted file backend.", out)

        with patch("trainsh.core.secrets._BACKEND_NAMES", {"1password": "1Password"}), patch(
            "trainsh.core.secrets._op_available", return_value=True
        ), patch("trainsh.commands.secrets_cmd.prompt_input", return_value="Vault"), patch(
            "trainsh.core.secrets._resolve_op_auth", return_value="token"
        ), patch(
            "trainsh.core.secrets.set_backend"
        ) as mocked_set:
            out, code, _ = self.capture(secrets_cmd.cmd_backend, ["1password"])
        self.assertIsNone(code)
        mocked_set.assert_called_once_with("1password", vault="Vault", sa_token="token")
        self.assertIn("Switched to: 1Password", out)

        with patch("trainsh.core.secrets._BACKEND_NAMES", {"keyring": "Keyring"}), patch(
            "trainsh.core.secrets._keyring_available", return_value=False
        ):
            out, code, _ = self.capture(secrets_cmd.cmd_backend, ["keyring"])
        self.assertEqual(code, 1)
        self.assertIn("No system keyring found", out)


class RecipeFileCommandTests(CaptureMixin, unittest.TestCase):
    def test_recipe_list_show_new_edit_remove_and_main(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir) / "recipes"
            examples_dir = Path(tmpdir) / "examples"
            recipes_dir.mkdir()
            examples_dir.mkdir()
            (recipes_dir / "mine.pyrecipe").write_text("from trainsh import Recipe\nrecipe = Recipe('mine')\nrecipe.empty(id='start')\n", encoding="utf-8")
            (examples_dir / "hello.pyrecipe").write_text("from trainsh import Recipe\nrecipe = Recipe('hello-world')\nrecipe.empty(id='start')\n", encoding="utf-8")

            with patch("trainsh.commands.recipe.get_recipes_dir", return_value=str(recipes_dir)), patch(
                "trainsh.commands.recipe.get_examples_dir", return_value=str(examples_dir)
            ):
                out, code, _ = self.capture(recipe.cmd_list, [])
                self.assertIsNone(code)
                self.assertIn("User recipes:", out)
                self.assertIn("Bundled examples:", out)

                out, code, _ = self.capture(recipe.cmd_show, ["mine"])
                self.assertIsNone(code)
                self.assertIn("Recipe: mine", out)

                out, code, _ = self.capture(recipe.cmd_show, ["missing"])
                self.assertEqual(code, 1)
                self.assertIn("Recipe not found", out)

                with patch("trainsh.commands.recipe._open_editor") as mocked_editor:
                    out, code, _ = self.capture(recipe.cmd_new, ["demo", "--template", "minimal"])
                self.assertIsNone(code)
                mocked_editor.assert_called_once()
                self.assertTrue((recipes_dir / "demo.pyrecipe").exists())
                self.assertIn("Created recipe:", out)

                out, code, _ = self.capture(recipe.cmd_new, ["demo"])
                self.assertEqual(code, 1)
                self.assertIn("Recipe already exists", out)

                with patch("trainsh.commands.recipe._open_editor") as mocked_editor:
                    out, code, _ = self.capture(recipe.cmd_edit, ["mine"])
                self.assertIsNone(code)
                mocked_editor.assert_called_once()

                out, code, _ = self.capture(recipe.cmd_edit, ["hello"])
                self.assertEqual(code, 1)
                self.assertIn("Bundled examples cannot be edited", out)

                with patch("trainsh.commands.recipe.prompt_input", return_value="n"):
                    out, code, _ = self.capture(recipe.cmd_rm, ["mine"])
                self.assertIsNone(code)
                self.assertIn("Cancelled.", out)

                with patch("trainsh.commands.recipe.prompt_input", return_value="y"):
                    out, code, _ = self.capture(recipe.cmd_rm, ["mine"])
                self.assertIsNone(code)
                self.assertIn("Recipe removed", out)

                out, code, _ = self.capture(recipe.main, [])
                self.assertIsNone(code)
                self.assertIn("train recipe", out)

                out, code, _ = self.capture(recipe.main, ["run"])
                self.assertEqual(code, 1)
                self.assertIn("Use 'train recipe run' instead.", out)

                out, code, _ = self.capture(recipe.main, ["bad"])
                self.assertEqual(code, 1)
                self.assertIn("Unknown subcommand", out)

    def test_recipe_lookup_helpers_and_recipe_cmd_dispatch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir) / "recipes"
            examples_dir = Path(tmpdir) / "examples"
            recipes_dir.mkdir()
            examples_dir.mkdir()
            user_recipe = recipes_dir / "demo.pyrecipe"
            user_recipe.write_text("from trainsh import Recipe\nrecipe = Recipe('demo')\n", encoding="utf-8")
            example_recipe = examples_dir / "hello.pyrecipe"
            example_recipe.write_text("from trainsh import Recipe\nrecipe = Recipe('hello')\n", encoding="utf-8")

            with patch("trainsh.commands.recipe.get_recipes_dir", return_value=str(recipes_dir)), patch(
                "trainsh.commands.recipe.get_examples_dir", return_value=str(examples_dir)
            ):
                self.assertEqual(recipe.find_recipe("demo"), str(user_recipe))
                self.assertEqual(recipe.find_recipe("hello"), str(example_recipe))
                self.assertEqual(recipe.find_recipe("examples/hello"), str(example_recipe))
                self.assertEqual(recipe.find_user_recipe(str(user_recipe)), str(user_recipe))
                self.assertIsNone(recipe.find_user_recipe(str(example_recipe)))

        out, code, _ = self.capture(recipe_cmd.main, [])
        self.assertIsNone(code)
        self.assertIn("Single entry point", out)

        out, code, _ = self.capture(recipe_cmd.main, ["--help"])
        self.assertEqual(code, 1)
        self.assertIn("Use `train help` or `train --help`.", out)

        with patch("trainsh.commands.recipe.main", return_value=None) as mocked_recipe:
            recipe_cmd.main(["list"])
        mocked_recipe.assert_called_once_with(["list"])

        with patch("trainsh.commands.recipe_runtime.cmd_run") as mocked_run:
            recipe_cmd.main(["run", "demo"])
        mocked_run.assert_called_once_with(["demo"])

        with patch("trainsh.commands.schedule_cmd.main") as mocked_schedule:
            recipe_cmd.main(["schedule", "list"])
        mocked_schedule.assert_called_once_with(["list"])

        out, code, _ = self.capture(recipe_cmd.main, ["bad"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown subcommand", out)


class PricingServiceAndUpdateCheckerTests(CaptureMixin, unittest.TestCase):
    def test_pricing_service_helpers_and_store(self):
        rates = pricing_service.ExchangeRates(rates={"USD": 1.0, "CNY": 7.0}, updated_at="now")
        self.assertEqual(rates.convert(7.0, "CNY", "USD"), 1.0)
        self.assertIn("/hr", pricing_service.format_price_per_hour(2.0, "CNY", rates))

        prices = pricing_service.calculate_colab_pricing(
            pricing_service.ColabSubscription(price=10.0, currency="USD", total_units=100),
            [pricing_service.ColabGpuPricing("T4", 2.0)],
            rates,
        )
        self.assertAlmostEqual(prices[0].price_usd_per_hour, 0.2)

        cost = pricing_service.calculate_host_cost("host1", gpu_hourly_usd=1.0, storage_gb=30.0)
        self.assertGreater(cost.total_per_hour_usd, 1.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            pricing_file = Path(tmpdir) / "pricing.yaml"
            with patch("trainsh.services.pricing.PRICING_FILE", pricing_file), patch(
                "trainsh.services.pricing.CONFIG_DIR", Path(tmpdir)
            ):
                settings = pricing_service.load_pricing_settings()
                settings.exchange_rates = rates
                pricing_service.save_pricing_settings(settings)
                loaded = pricing_service.load_pricing_settings()
                self.assertEqual(loaded.exchange_rates.rates["CNY"], 7.0)

                with patch(
                    "trainsh.services.pricing.fetch_exchange_rates",
                    return_value=pricing_service.ExchangeRates(rates={"USD": 1.0, "EUR": 0.9}, updated_at="later"),
                ):
                    refreshed = pricing_service.refresh_exchange_rates()
                self.assertEqual(refreshed.rates["EUR"], 0.9)

                stale = pricing_service.ExchangeRates(
                    rates={"USD": 1.0, "CNY": 7.0},
                    updated_at="2024-01-01T00:00:00+00:00",
                )
                settings.exchange_rates = stale
                with patch(
                    "trainsh.services.pricing.fetch_exchange_rates",
                    return_value=pricing_service.ExchangeRates(rates={"USD": 1.0, "CNY": 7.2}, updated_at="2026-03-13T00:00:00+00:00"),
                ), patch("trainsh.services.pricing.save_pricing_settings") as save_settings:
                    ensured = pricing_service.ensure_exchange_rates(["CNY"], settings=settings)
                self.assertEqual(ensured.rates["CNY"], 7.2)
                save_settings.assert_called_once()

                settings.exchange_rates = stale
                with patch(
                    "trainsh.services.pricing.fetch_exchange_rates",
                    return_value=None,
                ):
                    fallback_rates = pricing_service.ensure_exchange_rates(["CNY"], settings=settings, force=True)
                self.assertEqual(fallback_rates.rates["CNY"], 7.0)

                with patch("trainsh.config.load_config", return_value={"ui": {"currency": "CNY"}}):
                    self.assertEqual(pricing_service.get_display_currency(), "CNY")
                self.assertTrue(pricing_service.exchange_rates_need_refresh(stale, {"CNY"}))

        with patch("urllib.request.urlopen", side_effect=pricing_service.urllib.error.URLError("boom")):
            fallback = pricing_service.fetch_exchange_rates()
        self.assertIn("USD", fallback.rates)

    def test_update_checker_direct_paths(self):
        self.assertLess(update_checker.parse_version("1.2.3"), update_checker.parse_version("1.2.4"))

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "cache.yaml"
            with patch("trainsh.utils.update_checker.CACHE_FILE", cache_file), patch(
                "trainsh.utils.update_checker.CONFIG_DIR", Path(tmpdir)
            ):
                self.assertEqual(update_checker.load_cache(), {})
                update_checker.save_cache({"latest_version": "1.0.0"})
                self.assertEqual(update_checker.load_cache()["latest_version"], "1.0.0")

        opener = MagicMock()
        response = MagicMock()
        response.read.return_value = b'{"info": {"version": "9.9.9"}}'
        opener.open.return_value.__enter__.return_value = response
        with patch("urllib.request.build_opener", return_value=opener):
            self.assertEqual(update_checker.fetch_latest_version(), "9.9.9")
        with patch("urllib.request.build_opener", side_effect=update_checker.urllib.error.URLError("boom")):
            self.assertIsNone(update_checker.fetch_latest_version())

        with patch("trainsh.utils.update_checker.load_cache", return_value={"checked_at": "2999-01-01T00:00:00", "latest_version": "2.0.0"}), patch(
            "trainsh.utils.update_checker.fetch_latest_version", return_value="3.0.0"
        ):
            self.assertEqual(update_checker.get_latest_version(force=False), "2.0.0")

        with patch("trainsh.utils.update_checker.load_cache", return_value={}), patch(
            "trainsh.utils.update_checker.fetch_latest_version", return_value="3.0.0"
        ), patch("trainsh.utils.update_checker.save_cache") as mocked_save:
            self.assertEqual(update_checker.get_latest_version(force=True), "3.0.0")
            mocked_save.assert_called_once()

        with patch("trainsh.utils.update_checker.get_latest_version", return_value="2.0.0"):
            self.assertEqual(update_checker.check_for_updates("1.0.0"), "2.0.0")
        with patch("trainsh.utils.update_checker.get_latest_version", return_value="1.0.0"):
            self.assertIsNone(update_checker.check_for_updates("1.0.0"))

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            update_checker.print_update_notice("1.0.0", "2.0.0")
        self.assertIn("update available", stderr.getvalue())

        with patch("sys.stderr.isatty", return_value=True), patch(
            "trainsh.utils.update_checker.check_for_updates", return_value="2.0.0"
        ), patch("trainsh.utils.update_checker.print_update_notice") as mocked_notice:
            update_checker.maybe_check_updates("1.0.0")
        mocked_notice.assert_called_once()

        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0)):
            self.assertTrue(update_checker._has_command("uv"))
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            self.assertFalse(update_checker._has_command("uv"))

        with patch("sys.executable", "/Users/a/.local/share/uv/tools/tmux-trainsh/bin/python"):
            self.assertEqual(update_checker.detect_install_method(), "uv_tool")
        with patch("sys.executable", "/Users/a/.local/pipx/venvs/tmux-trainsh/bin/python"):
            self.assertEqual(update_checker.detect_install_method(), "pipx")
        with patch("sys.executable", "/usr/bin/python"), patch(
            "trainsh.utils.update_checker._has_command", return_value=True
        ):
            self.assertEqual(update_checker.detect_install_method(), "uv_pip")
        with patch("sys.executable", "/usr/bin/python"), patch(
            "trainsh.utils.update_checker._has_command", return_value=False
        ):
            self.assertEqual(update_checker.detect_install_method(), "pip")

        with patch("trainsh.utils.update_checker.detect_install_method", return_value="pip"), patch(
            "subprocess.run", return_value=SimpleNamespace(returncode=0, stderr="", stdout="")
        ):
            ok, msg = update_checker.perform_update()
        self.assertTrue(ok)
        self.assertIn("Successfully updated", msg)

        with patch("trainsh.utils.update_checker.detect_install_method", return_value="pip"), patch(
            "subprocess.run", return_value=SimpleNamespace(returncode=1, stderr="boom", stdout="")
        ):
            ok, msg = update_checker.perform_update()
        self.assertFalse(ok)
        self.assertIn("Update failed", msg)

        with patch("trainsh.utils.update_checker.detect_install_method", return_value="pip"), patch(
            "subprocess.run", side_effect=update_checker.subprocess.TimeoutExpired("pip", 1)
        ):
            ok, msg = update_checker.perform_update()
        self.assertFalse(ok)
        self.assertIn("timed out", msg)

        with patch("trainsh.utils.update_checker.detect_install_method", return_value="pip"), patch(
            "subprocess.run", side_effect=FileNotFoundError()
        ):
            ok, msg = update_checker.perform_update()
        self.assertFalse(ok)
        self.assertIn("not found", msg)


if __name__ == "__main__":
    unittest.main()

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from trainsh import main as trainsh_package
from trainsh.commands import config_cmd, help_catalog, help_cmd, pricing, update
from trainsh.main import main as train_main
from trainsh.services.pricing import ColabSubscription, ExchangeRates, PricingSettings


class CaptureMixin:
    def capture(self, fn, *args, **kwargs):
        stdout = io.StringIO()
        stderr = io.StringIO()
        exit_code = None
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                fn(*args, **kwargs)
            except SystemExit as exc:
                exit_code = exc.code
        return stdout.getvalue(), stderr.getvalue(), exit_code


class MainRoutingTests(CaptureMixin, unittest.TestCase):
    def test_main_prints_usage_when_no_subcommand(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "config"
            recipes_dir = config_dir / "recipes"
            with patch("trainsh.constants.CONFIG_DIR", config_dir), patch("trainsh.constants.RECIPES_DIR", recipes_dir):
                out, err, code = self.capture(train_main, ["train"])

        self.assertEqual(code, 0)
        self.assertIn("tmux-trainsh CLI", out)
        self.assertEqual(err, "")

    def test_main_handles_help_and_version_flags(self):
        out, _err, code = self.capture(train_main, ["train", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("GPU training workflow automation in the terminal", out)

        with patch("trainsh.__display_version__", "1.2.3-test"):
            out, _err, code = self.capture(train_main, ["train", "--version"])
        self.assertEqual(code, 0)
        self.assertIn("tmux-trainsh 1.2.3-test", out)

    def test_main_routes_help_and_config(self):
        with patch("trainsh.commands.help_cmd.main") as help_main:
            out, _err, code = self.capture(train_main, ["train", "help", "recipe"])
        self.assertIsNone(code)
        help_main.assert_called_once_with(["recipe"])
        self.assertEqual(out, "")

        with patch("trainsh.commands.config_cmd.main", return_value="ok") as config_main:
            out, _err, code = self.capture(train_main, ["train", "config", "show"])
        self.assertIsNone(code)
        config_main.assert_called_once_with(["show"])
        self.assertEqual(out, "")

    def test_main_routes_run_alias_to_recipe_namespace(self):
        with patch("trainsh.commands.recipe_cmd.main") as recipe_main:
            out, _err, code = self.capture(train_main, ["train", "run", "demo", "--help"])
        self.assertIsNone(code)
        recipe_main.assert_called_once_with(["run", "demo", "--help"])
        self.assertEqual(out, "")

    def test_main_unknown_command_prints_hint(self):
        out, _err, code = self.capture(train_main, ["train", "exec"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown command: exec", out)
        self.assertIn("Use 'train recipe run <recipe>'", out)


class HelpCatalogTests(unittest.TestCase):
    def test_rendered_help_includes_groups_and_topics(self):
        top = help_catalog.render_top_level_help()
        index = help_catalog.render_help_index()
        recipe_help = help_catalog.render_command_help("recipe")

        self.assertIn("Command Groups", top)
        self.assertIn("Common Mistakes", top)
        self.assertIn("Recommended Topics", index)
        self.assertIn("Recipe lifecycle", index)
        self.assertIn("train recipe run <name>", recipe_help)


class HelpCommandTests(CaptureMixin, unittest.TestCase):
    def test_help_topics_cover_default_alias_and_unknown(self):
        out, _err, code = self.capture(help_cmd.main, [])
        self.assertIsNone(code)
        self.assertIn("Recommended Topics", out)

        out, _err, code = self.capture(help_cmd.main, ["python-recipes"])
        self.assertIsNone(code)
        self.assertIn("Python Recipe Syntax", out)
        self.assertIn("Recipe Command", out)

        out, _err, code = self.capture(help_cmd.main, ["status"])
        self.assertIsNone(code)
        self.assertIn("Run Status vs Scheduler History", out)

        out, _err, code = self.capture(help_cmd.main, ["does-not-exist"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown help topic", out)
        self.assertIn("Recommended Topics", out)


class ConfigCommandTests(CaptureMixin, unittest.TestCase):
    def test_config_main_help_and_unknown(self):
        out, _err, code = self.capture(config_cmd.main, [])
        self.assertIsNone(code)
        self.assertIn("train config", out)

        out, _err, code = self.capture(config_cmd.main, ["wat"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown subcommand: wat", out)

    def test_config_show_get_set_and_reset(self):
        with patch("trainsh.config.load_config", return_value={"ui": {"currency": "USD"}, "workers": 2}):
            out, _err, code = self.capture(config_cmd.cmd_show, [])
        self.assertIsNone(code)
        self.assertIn("ui:", out)
        self.assertIn("currency = USD", out)

        out, _err, code = self.capture(config_cmd.cmd_get, [])
        self.assertEqual(code, 1)
        self.assertIn("Usage: train config get <key>", out)

        with patch("trainsh.config.get_config_value", return_value=None):
            out, _err, code = self.capture(config_cmd.cmd_get, ["missing"])
        self.assertEqual(code, 1)
        self.assertIn("Key not found: missing", out)

        with patch("trainsh.config.get_config_value", return_value="CNY"):
            out, _err, code = self.capture(config_cmd.cmd_get, ["ui.currency"])
        self.assertIsNone(code)
        self.assertEqual(out.strip(), "CNY")

        with patch("trainsh.config.set_config_value") as setter:
            out, _err, code = self.capture(config_cmd.cmd_set, ["ui.currency", "12.5"])
        self.assertIsNone(code)
        setter.assert_called_once_with("ui.currency", 12.5)
        self.assertIn("Set ui.currency = 12.5", out)

        with patch("trainsh.commands.config_cmd.prompt_input", return_value="n"):
            out, _err, code = self.capture(config_cmd.cmd_reset, [])
        self.assertIsNone(code)
        self.assertIn("Cancelled.", out)

        with patch("trainsh.commands.config_cmd.prompt_input", return_value="y"), patch(
            "trainsh.config.get_default_config",
            return_value={"ui": {"currency": "USD"}},
        ), patch("trainsh.config.save_config") as save_config:
            out, _err, code = self.capture(config_cmd.cmd_reset, [])
        self.assertIsNone(code)
        save_config.assert_called_once()
        self.assertIn("Configuration reset to defaults.", out)

    def test_tmux_namespace_show_apply_and_unknown(self):
        with patch("trainsh.config.load_config", return_value={"tmux": {"options": ["set -g mouse on"]}}):
            out, _err, code = self.capture(config_cmd._handle_tmux_namespace, ["show"])
        self.assertIsNone(code)
        self.assertIn("Tmux options:", out)
        self.assertIn("set -g mouse on", out)

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            tmux_conf = home / ".tmux.conf"
            with patch("trainsh.config.load_config", return_value={"tmux": {"options": ["set -g mouse on"]}}), patch(
                "trainsh.commands.config_cmd.prompt_input",
                return_value="y",
            ), patch("os.path.expanduser", return_value=str(tmux_conf)):
                out, _err, code = self.capture(config_cmd.cmd_tmux_setup, [])
        self.assertIsNone(code)
        self.assertIn("Written to", out)
        self.assertIn(str(tmux_conf), out)

        out, _err, code = self.capture(config_cmd._handle_tmux_namespace, ["oops"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown tmux subcommand: oops", out)

    def test_tmux_edit_parses_editor_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            def fake_run(cmd):
                temp_path = Path(cmd[1])
                temp_path.write_text("# comment\nset -g mouse on\n\nsetw -g mode-keys vi\n", encoding="utf-8")
                return SimpleNamespace(returncode=0)

            with patch.dict("os.environ", {"EDITOR": "fake-editor"}, clear=False), patch(
                "trainsh.config.load_config",
                return_value={"tmux": {"options": ["set -g mouse off"]}},
            ), patch("subprocess.run", side_effect=fake_run), patch(
                "trainsh.config.save_config"
            ) as save_config:
                out, _err, code = self.capture(config_cmd.cmd_tmux_edit, [])

        self.assertIsNone(code)
        saved_config = save_config.call_args.args[0]
        self.assertEqual(saved_config["tmux"]["options"], ["set -g mouse on", "setw -g mode-keys vi"])
        self.assertIn("Saved 2 tmux options", out)


class PricingCommandTests(CaptureMixin, unittest.TestCase):
    def make_settings(self):
        settings = PricingSettings()
        settings.exchange_rates = ExchangeRates(base="USD", rates={"USD": 1.0, "CNY": 7.0}, updated_at="now")
        settings.colab_subscription = ColabSubscription(name="Colab Pro", price=10.0, currency="USD", total_units=100.0)
        return settings

    def test_pricing_main_help_and_convert(self):
        out, _err, code = self.capture(pricing.main, [])
        self.assertIsNone(code)
        self.assertIn("train pricing", out)

        with patch("trainsh.commands.pricing.load_pricing_settings", return_value=self.make_settings()):
            out, _err, code = self.capture(pricing.main, ["convert", "10", "USD", "CNY"])
        self.assertIsNone(code)
        self.assertIn("= ¥70.00", out)

    def test_rates_currency_and_colab_paths(self):
        empty_settings = self.make_settings()
        empty_settings.exchange_rates.rates = {}
        with patch("trainsh.commands.pricing.load_pricing_settings", return_value=empty_settings):
            out, _err, code = self.capture(pricing.cmd_rates, SimpleNamespace(refresh=False))
        self.assertIsNone(code)
        self.assertIn("No exchange rates cached", out)

        fresh_rates = ExchangeRates(base="USD", rates={"USD": 1.0, "CNY": 7.2}, updated_at="later")
        settings = self.make_settings()
        with patch("trainsh.commands.pricing.load_pricing_settings", return_value=settings), patch(
            "trainsh.commands.pricing.fetch_exchange_rates",
            return_value=fresh_rates,
        ), patch("trainsh.commands.pricing.save_pricing_settings") as save_settings:
            out, _err, code = self.capture(pricing.cmd_rates, SimpleNamespace(refresh=True))
        self.assertIsNone(code)
        save_settings.assert_called_once()
        self.assertIn("Fetching exchange rates...", out)
        self.assertIn("Updated at: later", out)

        with patch("trainsh.config.get_config_value", return_value="USD"):
            out, _err, code = self.capture(pricing.cmd_currency, SimpleNamespace(set=None))
        self.assertIsNone(code)
        self.assertIn("Display currency: USD", out)
        self.assertIn("US Dollar", out)

        with patch("trainsh.config.set_config_value") as set_config:
            out, _err, code = self.capture(pricing.cmd_currency, SimpleNamespace(set="cny"))
        self.assertIsNone(code)
        set_config.assert_called_once_with("ui.currency", "CNY")
        self.assertIn("Display currency set to: CNY", out)

        out, _err, code = self.capture(pricing.cmd_currency, SimpleNamespace(set="zzz"))
        self.assertEqual(code, 1)
        self.assertIn("Invalid currency: zzz", out)

        settings = self.make_settings()
        with patch("trainsh.commands.pricing.load_pricing_settings", return_value=settings), patch(
            "trainsh.commands.pricing.save_pricing_settings"
        ) as save_settings:
            out, _err, code = self.capture(pricing.cmd_colab, SimpleNamespace(subscription="Pro:12:USD:200"))
        self.assertIsNone(code)
        save_settings.assert_called_once()
        self.assertIn("Updated Colab subscription: Pro", out)

        settings = self.make_settings()
        with patch(
            "trainsh.commands.pricing.get_pricing_context",
            return_value=(settings, "CNY", settings.exchange_rates),
        ):
            out, _err, code = self.capture(pricing.cmd_colab, SimpleNamespace(subscription=None))
        self.assertIsNone(code)
        self.assertIn("Colab Subscription: Colab Pro", out)
        self.assertIn("GPU Hourly Prices:", out)

    def test_vast_paths_and_parse_errors(self):
        settings = self.make_settings()
        fake_client = SimpleNamespace(list_instances=lambda: [])
        with patch(
            "trainsh.commands.pricing.get_pricing_context",
            return_value=(settings, "USD", settings.exchange_rates),
        ), patch("trainsh.services.vast_api.get_vast_client", return_value=fake_client):
            out, _err, code = self.capture(pricing.cmd_vast, SimpleNamespace())
        self.assertIsNone(code)
        self.assertIn("No Vast.ai instances found.", out)

        instances = [
            SimpleNamespace(id=1, dph_total=1.5, actual_status="running", gpu_name="A100", num_gpus=2),
            SimpleNamespace(id=2, dph_total=0.0, actual_status="stopped", gpu_name="T4", num_gpus=1),
        ]
        fake_client = SimpleNamespace(list_instances=lambda: instances)
        with patch(
            "trainsh.commands.pricing.get_pricing_context",
            return_value=(settings, "USD", settings.exchange_rates),
        ), patch("trainsh.services.vast_api.get_vast_client", return_value=fake_client):
            out, _err, code = self.capture(pricing.cmd_vast, SimpleNamespace())
        self.assertIsNone(code)
        self.assertIn("Vast.ai Instance Costs", out)
        self.assertIn("A100", out)
        self.assertIn("Monthly estimate", out)

        out, _err, code = self.capture(pricing.main, ["colab", "--subscription", "broken"])
        self.assertEqual(code, 1)
        self.assertIn("Format: name:price[:currency[:units]]", out)


class UpdateCommandTests(CaptureMixin, unittest.TestCase):
    def test_update_help_unknown_and_unavailable(self):
        out, _err, code = self.capture(update.main, ["--help"])
        self.assertIsNone(code)
        self.assertIn("train update", out)

        out, _err, code = self.capture(update.main, ["--bogus"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown option: --bogus", out)

        with patch("trainsh.utils.update_checker.get_latest_version", return_value=None):
            out, _err, code = self.capture(update.main, [])
        self.assertIsNone(code)
        self.assertIn("Unable to check for updates", out)

    def test_update_up_to_date_check_only_and_install(self):
        with patch("trainsh.__version__", "1.0.0"), patch(
            "trainsh.utils.update_checker.get_latest_version",
            return_value="1.0.0",
        ), patch("trainsh.utils.update_checker.parse_version", side_effect=lambda v: tuple(int(x) for x in v.split("."))):
            out, _err, code = self.capture(update.main, [])
        self.assertIsNone(code)
        self.assertIn("tmux-trainsh is up to date (1.0.0).", out)

        with patch("trainsh.__version__", "1.0.0"), patch(
            "trainsh.utils.update_checker.get_latest_version",
            return_value="1.1.0",
        ), patch("trainsh.utils.update_checker.parse_version", side_effect=lambda v: tuple(int(x) for x in v.split("."))), patch(
            "trainsh.utils.update_checker.print_update_notice"
        ) as notice:
            out, _err, code = self.capture(update.main, ["--check"])
        self.assertIsNone(code)
        notice.assert_called_once_with("1.0.0", "1.1.0")
        self.assertEqual(out, "")

        with patch("trainsh.__version__", "1.0.0"), patch(
            "trainsh.utils.update_checker.get_latest_version",
            return_value="1.1.0",
        ), patch("trainsh.utils.update_checker.parse_version", side_effect=lambda v: tuple(int(x) for x in v.split("."))), patch(
            "trainsh.utils.update_checker.detect_install_method",
            return_value="uv_tool",
        ), patch("trainsh.utils.update_checker.perform_update", return_value=(True, "done")):
            out, _err, code = self.capture(update.main, [])
        self.assertIsNone(code)
        self.assertIn("Updating 1.0.0", out)
        self.assertIn("done", out)

        with patch("trainsh.__version__", "1.0.0"), patch(
            "trainsh.utils.update_checker.get_latest_version",
            return_value="1.1.0",
        ), patch("trainsh.utils.update_checker.parse_version", side_effect=lambda v: tuple(int(x) for x in v.split("."))), patch(
            "trainsh.utils.update_checker.detect_install_method",
            return_value="pip",
        ), patch("trainsh.utils.update_checker.perform_update", return_value=(False, "bad")):
            out, _err, code = self.capture(update.main, [])
        self.assertEqual(code, 1)
        self.assertIn("bad", out)


if __name__ == "__main__":
    unittest.main()

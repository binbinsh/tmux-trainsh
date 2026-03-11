import unittest
from unittest.mock import patch

from trainsh.commands.transfer import parse_endpoint as parse_transfer_endpoint
from trainsh.core.models import Storage, StorageType
from trainsh.core.recipe_models import RecipeModel
from trainsh.core.secrets import SecretsManager
from trainsh.core.storage_specs import build_storage_from_spec
from trainsh.services.transfer_engine import build_rclone_env, get_rclone_remote_name

from tests.runtime_test_utils import isolated_executor


class StorageResolutionTests(unittest.TestCase):
    def test_transfer_command_parses_inline_r2_endpoint(self):
        endpoint_type, path, storage_id = parse_transfer_endpoint("r2:logs-bucket:/checkpoints")
        self.assertEqual(endpoint_type, "storage")
        self.assertEqual(path, "/checkpoints")
        self.assertEqual(storage_id, "r2:logs-bucket")

    def test_legacy_s3_inline_spec_is_no_longer_supported(self):
        self.assertIsNone(build_storage_from_spec("s3:old-bucket"))

    def test_executor_transfer_parses_global_and_inline_storage_endpoints(self):
        global_storage = Storage(
            id="archive",
            name="archive",
            type=StorageType.R2,
            config={"bucket": "archive-bucket"},
        )

        with isolated_executor(RecipeModel(name="transfer-storage")) as (executor, _config_dir):
            with patch("trainsh.commands.storage.load_storages", return_value={"archive": global_storage}), patch(
                "trainsh.commands.host.load_hosts",
                return_value={},
            ):
                global_endpoint = executor.transfer_helper.parse_endpoint("@archive:/models")
                inline_endpoint = executor.transfer_helper.parse_endpoint("@r2:logs-bucket:/checkpoints")

        self.assertEqual(global_endpoint.type, "storage")
        self.assertEqual(global_endpoint.storage_id, "archive")
        self.assertEqual(global_endpoint.path, "/models")
        self.assertEqual(inline_endpoint.type, "storage")
        self.assertEqual(inline_endpoint.storage_id, "r2:logs-bucket")
        self.assertEqual(inline_endpoint.path, "/checkpoints")

    def test_resolve_storage_supports_global_name_and_inline_r2_spec(self):
        global_storage = Storage(
            id="archive",
            name="archive",
            type=StorageType.R2,
            config={"bucket": "archive-bucket"},
        )

        with isolated_executor(RecipeModel(name="resolve-storage")) as (executor, _config_dir):
            with patch("trainsh.commands.storage.load_storages", return_value={"archive": global_storage}):
                resolved_global = executor._resolve_storage("archive")
                resolved_inline = executor._resolve_storage("r2:logs-bucket")

        self.assertIsNotNone(resolved_global)
        self.assertEqual(resolved_global.config["bucket"], "archive-bucket")
        self.assertIsNotNone(resolved_inline)
        self.assertEqual(resolved_inline.type, StorageType.R2)
        self.assertEqual(resolved_inline.config["bucket"], "logs-bucket")

    def test_inline_r2_uses_safe_rclone_remote_names(self):
        with isolated_executor(RecipeModel(name="inline-rclone")) as (executor, _config_dir):
            storage = executor._resolve_storage("r2:logs-bucket")

        self.assertIsNotNone(storage)
        remote_name = get_rclone_remote_name(storage)
        env = build_rclone_env(storage)

        self.assertNotIn(":", remote_name)
        self.assertTrue(remote_name.startswith("r2_"))
        self.assertIn(f"RCLONE_CONFIG_{remote_name.upper()}_TYPE", env)

    def test_r2_composite_secret_bundle_supplies_s3_api_credentials_and_derived_endpoint(self):
        storage = Storage(
            id="artifacts",
            name="artifacts",
            type=StorageType.R2,
            config={"bucket": "logs"},
        )
        manager = SecretsManager()
        backend = unittest.mock.MagicMock()
        backend.get.side_effect = lambda key: (
            '{"account_id":"bundle-account","access_key_id":"bundle-ak","secret_access_key":"bundle-sk"}'
            if key == "ARTIFACTS_R2_CREDENTIALS"
            else None
        )
        manager._backend = backend
        manager._backend_loaded = True

        with patch("trainsh.services.transfer_engine.get_secrets_manager", return_value=manager):
            env = build_rclone_env(storage)

        remote_name = get_rclone_remote_name(storage).upper()
        self.assertEqual(env[f"RCLONE_CONFIG_{remote_name}_ACCESS_KEY_ID"], "bundle-ak")
        self.assertEqual(env[f"RCLONE_CONFIG_{remote_name}_SECRET_ACCESS_KEY"], "bundle-sk")
        self.assertEqual(
            env[f"RCLONE_CONFIG_{remote_name}_ENDPOINT"],
            "https://bundle-account.r2.cloudflarestorage.com",
        )


if __name__ == "__main__":
    unittest.main()

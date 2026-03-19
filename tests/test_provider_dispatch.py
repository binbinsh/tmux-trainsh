import unittest
from unittest.mock import patch

from trainsh.core.recipe_models import RecipeModel
from trainsh.pyrecipe.models import ProviderStep

from tests.runtime_test_utils import isolated_executor


class ProviderDispatchAliasTests(unittest.TestCase):
    def test_shell_and_python_providers_route_to_expected_handlers(self):
        with isolated_executor(RecipeModel(name="dispatch")) as (executor, _config_dir):
            with patch.object(executor, "_exec_provider_shell", return_value=(True, "shell")) as shell_mock, patch.object(
                executor,
                "_exec_provider_python",
                return_value=(True, "python"),
            ) as python_mock:
                shell_result = executor._exec_provider(
                    ProviderStep("bash", "bash", {"command": "echo hi"}, id="bash")
                )
                python_result = executor._exec_provider(
                    ProviderStep("python", "python", {"command": "print(1)"}, id="py")
                )

        self.assertEqual(shell_result, (True, "shell"))
        self.assertEqual(python_result, (True, "python"))
        self.assertEqual(shell_mock.call_args.args[0]["command"], "echo hi")
        self.assertEqual(python_mock.call_args.args[0]["command"], "print(1)")

    def test_cloud_provider_routes_to_storage_family_and_normalize_storage_name(self):
        with isolated_executor(RecipeModel(name="dispatch")) as (executor, _config_dir):
            with patch.object(
                executor,
                "_exec_provider_storage_upload",
                return_value=(True, "upload"),
            ) as upload_mock, patch.object(
                executor,
                "_exec_provider_storage_delete",
                return_value=(True, "delete"),
            ) as delete_mock:
                upload_result = executor._exec_provider(
                    ProviderStep(
                        "cloud",
                        "put",
                        {"bucket": "@artifacts", "source": "/tmp/in", "destination": "/out"},
                        id="up",
                    )
                )
                delete_result = executor._exec_provider(
                    ProviderStep("cloud", "rm", {"storage": "@artifacts", "path": "/gone"}, id="rm")
                )

        self.assertEqual(upload_result, (True, "upload"))
        self.assertEqual(delete_result, (True, "delete"))
        self.assertEqual(upload_mock.call_args.args[0]["storage"], "artifacts")
        self.assertEqual(delete_mock.call_args.args[0]["storage"], "artifacts")

    def test_http_provider_normalizes_json_and_wait_operations(self):
        with isolated_executor(RecipeModel(name="dispatch")) as (executor, _config_dir):
            with patch.object(
                executor,
                "_exec_provider_http_request",
                return_value=(True, "request"),
            ) as request_mock, patch.object(
                executor,
                "_exec_provider_http_wait",
                return_value=(True, "wait"),
            ) as wait_mock:
                request_result = executor._exec_provider(
                    ProviderStep(
                        "http",
                        "json",
                        {"url": "https://example.com", "json_body": {"ok": True}},
                        id="http_json",
                    )
                )
                wait_result = executor._exec_provider(
                    ProviderStep("http", "sensor", {"url": "https://example.com"}, id="http_wait")
                )

        self.assertEqual(request_result, (True, "request"))
        self.assertEqual(wait_result, (True, "wait"))
        request_params = request_mock.call_args.args[0]
        self.assertEqual(request_params["method"], "POST")
        self.assertEqual(request_params["body"], {"ok": True})
        self.assertEqual(wait_mock.call_args.args[0]["url"], "https://example.com")

    def test_sqlite_provider_routes_to_query_exec_and_script(self):
        with isolated_executor(RecipeModel(name="dispatch")) as (executor, _config_dir):
            query_result = executor._exec_provider(
                ProviderStep("sqlite", "select", {"sql": "select 1"}, id="q")
            )
            exec_result = executor._exec_provider(
                ProviderStep("sqlite", "execute", {"sql": "insert into t values (1)"}, id="e")
            )
            script_result = executor._exec_provider(
                ProviderStep("sqlite", "script", {"script": "select 1;"}, id="s")
            )

        self.assertFalse(query_result[0])
        self.assertFalse(exec_result[0])
        self.assertFalse(script_result[0])
        self.assertIn("Unsupported provider step", query_result[1])

    def test_xcom_helpers_inject_step_id_when_missing(self):
        with isolated_executor(RecipeModel(name="dispatch")) as (executor, _config_dir):
            with patch.object(
                executor,
                "_exec_provider_xcom_push",
                return_value=(True, "push"),
            ) as push_mock, patch.object(
                executor,
                "_exec_provider_xcom_pull",
                return_value=(True, "pull"),
            ) as pull_mock:
                push_result = executor._exec_provider(
                    ProviderStep("util", "xcom_push", {"key": "rows", "value": "[]"}, id="push_step")
                )
                pull_result = executor._exec_provider(
                    ProviderStep("util", "xcom_pull", {"key": "rows"}, id="pull_step")
                )

        self.assertEqual(push_result, (True, "push"))
        self.assertEqual(pull_result, (True, "pull"))
        self.assertEqual(push_mock.call_args.args[0]["task_id"], "push_step")
        self.assertEqual(pull_mock.call_args.args[0]["task_id"], "pull_step")

    def test_notification_providers_route_to_notice(self):
        with isolated_executor(RecipeModel(name="dispatch")) as (executor, _config_dir):
            with patch.object(executor, "_exec_provider_notice", return_value=(True, "notice")) as notice_mock:
                result = executor._exec_provider(
                    ProviderStep("email", "send", {"message": "hello"}, id="notify")
                )

        self.assertEqual(result, (True, "notice"))
        self.assertEqual(notice_mock.call_args.args[0]["message"], "hello")

    def test_branch_and_short_circuit_route(self):
        with isolated_executor(RecipeModel(name="dispatch")) as (executor, _config_dir):
            with patch.object(executor, "_exec_provider_branch", return_value=(True, "branch")) as branch_mock, patch.object(
                executor,
                "_exec_provider_short_circuit",
                return_value=(True, "gate"),
            ) as gate_mock:
                branch_result = executor._exec_provider(
                    ProviderStep(
                        "util",
                        "branch",
                        {"condition": "var:FLAG==1"},
                        id="branch",
                    )
                )
                gate_result = executor._exec_provider(
                    ProviderStep(
                        "util",
                        "skip_if",
                        {"condition": "var:FLAG==0"},
                        id="gate",
                    )
                )

        self.assertEqual(branch_result, (True, "branch"))
        self.assertEqual(gate_result, (True, "gate"))
        self.assertEqual(branch_mock.call_args.args[0]["condition"], "var:FLAG==1")
        self.assertEqual(gate_mock.call_args.args[0]["condition"], "var:FLAG==0")

    def test_storage_provider_routes_to_transfer_upload_and_download(self):
        with isolated_executor(RecipeModel(name="dispatch")) as (executor, _config_dir):
            with patch.object(executor, "_exec_provider_transfer", return_value=(True, "transfer")) as transfer_mock, patch.object(
                executor,
                "_exec_provider_storage_upload",
                return_value=(True, "upload"),
            ) as upload_mock, patch.object(
                executor,
                "_exec_provider_storage_download",
                return_value=(True, "download"),
            ) as download_mock:
                transfer_result = executor._exec_provider(
                    ProviderStep("storage", "copy", {"source": "/a", "destination": "/b"}, id="cp")
                )
                upload_result = executor._exec_provider(
                    ProviderStep("storage", "upload", {"storage": "artifacts", "source": "/a"}, id="put")
                )
                download_result = executor._exec_provider(
                    ProviderStep(
                        "storage",
                        "download",
                        {"storage": "artifacts", "source": "/a", "destination": "/tmp/out"},
                        id="get",
                    )
                )

        self.assertEqual(transfer_result, (True, "transfer"))
        self.assertEqual(upload_result, (True, "upload"))
        self.assertEqual(download_result, (True, "download"))
        self.assertEqual(transfer_mock.call_args.args[0]["source"], "/a")
        self.assertEqual(upload_mock.call_args.args[0]["storage"], "artifacts")
        self.assertEqual(download_mock.call_args.args[0]["destination"], "/tmp/out")

    def test_wait_file_and_wait_port_route(self):
        with isolated_executor(RecipeModel(name="dispatch")) as (executor, _config_dir):
            with patch.object(
                executor,
                "_exec_provider_wait_for_file",
                return_value=(True, "file"),
            ) as file_mock, patch.object(
                executor,
                "_exec_provider_wait_for_port",
                return_value=(True, "port"),
            ) as port_mock:
                file_result = executor._exec_provider(
                    ProviderStep("util", "wait_file", {"path": "/tmp/ready"}, id="file")
                )
                port_result = executor._exec_provider(
                    ProviderStep("util", "wait_port", {"port": 8080}, id="port")
                )

        self.assertEqual(file_result, (True, "file"))
        self.assertEqual(port_result, (True, "port"))
        self.assertEqual(file_mock.call_args.args[0]["path"], "/tmp/ready")
        self.assertEqual(port_mock.call_args.args[0]["port"], 8080)


if __name__ == "__main__":
    unittest.main()

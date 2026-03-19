import unittest

from trainsh import Recipe, VastHost
from trainsh.pyrecipe.models import Host, Storage
from trainsh.pyrecipe.namespaces import NotifyNamespace, VastNamespace
from trainsh.pyrecipe.references import AliasRef, StepHandle, wrap_step_handle


class PyrecipeMoreSurfacesTests(unittest.TestCase):
    def test_misc_provider_helpers(self):
        recipe = Recipe("misc-surface")
        recipe.set_var("FLAG", "1", id="set_var")
        recipe.fail("boom", exit_code=2, id="fail")
        recipe.xcom_push("rows", {"a": 1}, from_var="ROWS", output_var="OUT", task_id="task", run_id="run", dag_id="dag", map_index=2, runtime_state=".state", id="push")
        recipe.xcom_pull("rows", task_ids="a, b", run_id="run", dag_id="dag", map_index=3, include_prior_dates=True, default={"x": 1}, output_var="PULL", decode_json=True, runtime_state=".state", id="pull")
        recipe.notice("done", title="Title", channels=["log"], level="warning", webhook="https://hook", command="echo hi", timeout="5s", fail_on_error=True, id="notice")
        recipe.webhook("hook-msg", webhook="https://hook", title="WH", channels=["hook"], id="webhook")
        recipe.slack("slack-msg", "https://slack", title="SL", channel="#ops", username="bot", id="slack")
        recipe.telegram("tg-msg", "https://tg", title="TG", id="telegram")
        recipe.discord("dc-msg", "https://dc", title="DC", id="discord")
        recipe.email_send("mail-msg", to=["a@example.com"], subject="subj", from_addr="from@example.com", id="email")

        steps = {step.id: step for step in recipe.steps}
        self.assertEqual(steps["set_var"].params["name"], "FLAG")
        self.assertEqual(steps["fail"].params["exit_code"], 2)
        self.assertEqual(steps["push"].params["task_id"], "task")
        self.assertEqual(steps["pull"].params["task_ids"], ["a", "b"])
        self.assertTrue(steps["pull"].params["decode_json"])
        self.assertEqual(steps["notice"].params["title"], "Title")
        self.assertEqual(steps["webhook"].provider, "webhook")
        self.assertEqual(steps["slack"].provider, "slack")
        self.assertEqual(steps["telegram"].provider, "telegram")
        self.assertEqual(steps["discord"].provider, "discord")
        self.assertEqual(steps["email"].provider, "email")

    def test_network_helpers(self):
        recipe = Recipe("network-surface")
        self.assertEqual(recipe._normalize_http_headers({"A": 1, "B": None}), {"A": "1", "B": ""})
        self.assertIsNone(recipe._normalize_http_headers("bad"))

        recipe.http_get("https://example.com", headers={"A": 1}, capture_var="GET", id="get")
        recipe.http_post("https://example.com", json_body={"ok": True}, headers={}, id="post")
        recipe.http_put("https://example.com", body="data", headers={"B": 2}, id="put")
        recipe.http_delete("https://example.com", body="gone", id="delete")
        recipe.http_head("https://example.com", id="head")
        recipe.http_wait_for_status("https://example.com", method="POST", json_body={"ok": True}, expected_status="200,201", expected_text="ok", timeout="10s", poll_interval="2s", request_timeout=5, id="wait_status")
        recipe.http_request_json("https://example.com", method="PATCH", json_body={"ok": True}, headers={}, id="request_json")
        recipe.http_post_json("https://example.com", json_body={"ok": True}, id="post_json")
        recipe.http_put_json("https://example.com", json_body={"ok": True}, id="put_json")
        recipe.http_delete_json("https://example.com", body={"gone": True}, id="delete_json")
        recipe.http_wait("https://example.com", expected_status=[200], id="wait")
        recipe.http_sensor("https://example.com", expected_text="ready", id="sensor")

        steps = {step.id: step for step in recipe.steps}
        self.assertEqual(steps["get"].params["headers"], {"A": "1"})
        self.assertEqual(steps["post"].params["headers"]["Content-Type"], "application/json")
        self.assertEqual(steps["put"].params["body"], "data")
        self.assertEqual(steps["delete"].params["method"], "DELETE")
        self.assertEqual(steps["head"].params["method"], "HEAD")
        self.assertEqual(steps["wait_status"].params["method"], "POST")
        self.assertEqual(steps["request_json"].operation, "request_json")
        self.assertEqual(steps["post_json"].params["method"], "POST")
        self.assertEqual(steps["put_json"].params["method"], "PUT")
        self.assertEqual(steps["delete_json"].params["method"], "DELETE")
        self.assertEqual(steps["wait"].operation, "wait_for_status")
        self.assertEqual(steps["sensor"].operation, "http_sensor")

    def test_storage_helpers(self):
        recipe = Recipe("storage-surface")
        artifacts = Storage("r2:bucket", name="artifacts")

        self.assertEqual(recipe._storage_target(artifacts.path("/ready.txt")), ("artifacts", "/ready.txt"))
        self.assertEqual(recipe._storage_target(artifacts.path("/ready.txt"), path="/else"), ("artifacts", "/else"))

        recipe.storage_upload(artifacts.path("/uploads"), source="/tmp/in", destination="/out", operation="sync", id="upload")
        recipe.storage_download(artifacts, source="/src", destination="/tmp/out", operation="move", id="download")
        recipe.storage_exists(artifacts, path="/exists", id="exists")
        recipe.storage_test(artifacts, path="/test", id="test")
        recipe.storage_wait(artifacts, path="/wait", exists=False, timeout="10s", poll_interval="2s", id="wait")
        recipe.storage_info(artifacts, path="/info", id="info")
        recipe.storage_read_text(artifacts, path="/readme", max_chars=99, id="read")
        recipe.storage_list(artifacts, path="/list", recursive=True, id="list")
        recipe.storage_mkdir(artifacts, path="/mkdir", id="mkdir")
        recipe.storage_delete(artifacts, path="/delete", recursive=True, id="delete")
        recipe.storage_rename(artifacts, source="/a", destination="/b", id="rename")
        recipe.storage_copy(artifacts, source="/a", destination="/b", exclude=["*.tmp"], id="copy")
        recipe.storage_move(artifacts, source="/a", destination="/b", id="move")
        recipe.storage_sync(artifacts, source="/a", destination="/b", delete=True, exclude=["*.tmp"], id="sync")
        recipe.storage_remove(artifacts, path="/remove", recursive=True, id="remove")

        steps = {step.id: step for step in recipe.steps}
        self.assertEqual(steps["upload"].params["destination"], "/out")
        self.assertEqual(steps["download"].params["operation"], "move")
        self.assertEqual(steps["exists"].params["path"], "/exists")
        self.assertEqual(steps["test"].operation, "exists")
        self.assertFalse(steps["wait"].params["exists"])
        self.assertEqual(steps["read"].params["max_chars"], 99)
        self.assertTrue(steps["list"].params["recursive"])
        self.assertTrue(steps["delete"].params["recursive"])
        self.assertIn("@artifacts:/a", steps["copy"].params["source"])
        self.assertEqual(steps["move"].params["operation"], "move")
        self.assertTrue(steps["sync"].params["delete"])
        self.assertEqual(steps["remove"].operation, "delete")

    def test_namespaces_and_references(self):
        recipe = Recipe("namespace-surface")
        vast = VastNamespace(recipe)
        notify = NotifyNamespace(recipe)
        gpu = VastHost("7")
        plain_host = Host("vast:9", name="gpu")

        self.assertEqual(vast.start(gpu, id="start"), "start")
        self.assertEqual(vast.stop(plain_host, id="stop"), "stop")
        self.assertEqual(vast.wait_ready("11", id="wait"), "wait")
        self.assertEqual(vast.pick(host=Host("ssh://gpu", name="gpu"), id="pick"), "pick")
        self.assertEqual(vast.cost("7", id="cost"), "cost")

        self.assertEqual(notify("hello", id="notice"), "notice")
        self.assertEqual(notify.notice("notice-2", id="notice2"), "notice2")
        self.assertEqual(notify.email("email", id="email"), "email")
        self.assertEqual(notify.slack("slack", webhook="https://slack", id="slack"), "slack")
        self.assertEqual(notify.telegram("tg", webhook="https://tg", id="telegram"), "telegram")
        self.assertEqual(notify.discord("dc", webhook="https://dc", id="discord"), "discord")
        self.assertEqual(notify.webhook("hook", webhook="https://hook", id="webhook"), "webhook")

        alias = AliasRef(" gpu ", kind="host")
        self.assertEqual(str(alias), "gpu")
        self.assertEqual(alias.kind, "host")

        first = recipe.empty(id="first")
        next_step = recipe.empty(id="next")
        handle = wrap_step_handle(recipe, "first")
        self.assertIsInstance(handle, StepHandle)
        handle.after(next_step)
        self.assertIn("next", recipe.steps[-2].depends_on)
        self.assertEqual(handle.then(recipe.steps[1]), recipe.steps[1])
        self.assertEqual(handle >> recipe.steps[1], recipe.steps[1])
        self.assertIsNone(handle >> None)
        with self.assertRaises(TypeError):
            handle >> ""


if __name__ == "__main__":
    unittest.main()

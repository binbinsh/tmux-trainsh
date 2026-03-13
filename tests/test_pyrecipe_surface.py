import tempfile
import unittest
from pathlib import Path

from trainsh import Recipe, official_uv_install_command
from trainsh.core.models import Storage as RuntimeStorage, StorageType
from trainsh.pyrecipe.control_steps import RecipeControlMixin
from trainsh.pyrecipe.models import Host, PythonRecipeError, Storage


class PyrecipeSurfaceTests(unittest.TestCase):
    def test_control_and_basic_provider_helpers(self):
        recipe = Recipe("surface-demo")

        open_step = recipe.tmux_open("gpu", as_="main", id="open")
        cfg_step = recipe.tmux_config("gpu", id="cfg", depends_on=[open_step])
        sleep_step = recipe.sleep("5s", id="sleep", depends_on=[cfg_step])
        close_step = recipe.tmux_close("main", id="close", depends_on=[sleep_step])

        shell = recipe.shell("echo hi", host="gpu", cwd="/tmp", env={"A": 1}, capture_var="OUT", id="shell")
        bash = recipe.bash("echo bash", id="bash")
        py_cmd = recipe.python("print('x')", capture_var="PY", id="py_cmd")
        py_script = recipe.python("", script="script.py", id="py_script")
        noop = recipe.noop(id="noop")
        fail = recipe.fail("boom", id="fail")
        choose = recipe.choose("FLAG", when=True, then="1", else_="0", id="choose")

        self.assertEqual(open_step, "open")
        steps = {step.id: step for step in recipe.steps}
        self.assertEqual(steps["open"].command, "tmux.open")
        self.assertEqual(steps["cfg"].command, "tmux.config")
        self.assertEqual(steps["sleep"].command, "sleep")
        self.assertEqual(steps["close"].command, "tmux.close")
        self.assertEqual(steps["shell"].provider, "shell")
        self.assertEqual(steps["shell"].params["cwd"], "/tmp")
        self.assertEqual(steps["shell"].params["env"], {"A": 1})
        self.assertEqual(steps["bash"].provider, "shell")
        self.assertEqual(steps["py_cmd"].provider, "python")
        self.assertIn("command", steps["py_cmd"].params)
        self.assertEqual(steps["py_script"].params["script"], "script.py")
        self.assertEqual(steps["noop"].operation, "empty")
        self.assertEqual(steps["fail"].operation, "fail")
        self.assertEqual(steps["choose"].operation, "set_var")

        with self.assertRaises(PythonRecipeError):
            recipe.provider("", "run")

    def test_workflow_helpers_cover_git_host_assert_wait_and_env(self):
        recipe = Recipe("workflow-demo")
        clone = recipe.git_clone("https://github.com/example/repo.git", "/tmp/repo", branch="main", depth=1, host="gpu", id="clone")
        pull = recipe.git_pull("/tmp/repo", remote="upstream", branch="dev", host="gpu", id="pull", depends_on=[clone])
        test = recipe.host_test("gpu", capture_var="PING", id="test")
        assertion = recipe.assert_("var:READY==1", message="not ready", host="gpu", timeout="10s", id="assert", depends_on=[test])
        get_value = recipe.get_value("env:HOME", "HOME", default="/tmp", host="gpu", id="get_value")
        set_env = recipe.set_env("MODE", "prod", id="set_env")
        wait_file = recipe.wait_file("/tmp/ready", host="gpu", id="wait_file")
        wait_port = recipe.wait_for_port(8080, host="gpu", host_name="127.0.0.1", id="wait_port")
        ssh = recipe.ssh_command("gpu", "echo hi", id="ssh")
        ssh_alias = recipe.ssh("gpu", "echo alias", id="ssh_alias")
        uv = recipe.uv_run("python train.py", packages=["rich"], host="gpu", timeout=60, id="uv")

        steps = {step.id: step for step in recipe.steps}
        self.assertEqual(pull, "pull")
        self.assertEqual(steps["clone"].provider, "git")
        self.assertEqual(steps["clone"].params["branch"], "main")
        self.assertEqual(steps["pull"].params["remote"], "upstream")
        self.assertEqual(steps["test"].provider, "host")
        self.assertEqual(steps["assert"].provider, "util")
        self.assertEqual(steps["assert"].operation, "assert")
        self.assertEqual(steps["get_value"].operation, "get_value")
        self.assertEqual(steps["set_env"].params["name"], "MODE")
        self.assertEqual(steps["wait_file"].operation, "wait_for_file")
        self.assertEqual(steps["wait_port"].params["host_name"], "127.0.0.1")
        self.assertEqual(steps["ssh"].operation, "ssh_command")
        self.assertEqual(steps["ssh_alias"].operation, "ssh_command")
        self.assertEqual(steps["uv"].operation, "uv_run")

        session = recipe.session("main", host="gpu", id="open_main")
        install_uv = session.install_uv(id="install_uv")
        steps = {step.id: step for step in recipe.steps}
        self.assertIn("astral.sh/uv/install.sh", steps["install_uv"].raw)
        self.assertEqual(install_uv, "install_uv")

    def test_official_uv_install_command_variants(self):
        default = official_uv_install_command()
        forced = official_uv_install_command(force=True)
        self.assertIn("astral.sh/uv/install.sh", default)
        self.assertIn("export PATH=\"$HOME/.local/bin:$PATH\"", default)
        self.assertIn("curl -LsSf https://astral.sh/uv/install.sh | sh", forced)

    def test_vast_and_notice_helpers_from_control_surface(self):
        recipe = Recipe("vast-demo")
        start = recipe.vast_start("123", id="start")
        pick = recipe.vast_pick(
            "gpu",
            gpu_name="A100",
            num_gpus=2,
            min_gpu_ram=80,
            max_dph=2.5,
            limit=3,
            auto_select=True,
            create_if_missing=True,
            image="pytorch/pytorch:latest",
            disk_gb=200,
            direct=True,
            id="pick",
        )
        wait = recipe.vast_wait("123", timeout="5m", poll_interval="5s", stop_on_fail=False, id="wait")
        cost = recipe.vast_cost("123", id="cost")
        stop = recipe.vast_stop("123", id="stop")
        notice = recipe.notice("done", channels=["log"], id="notice")

        steps = {step.id: step for step in recipe.steps}
        self.assertEqual(start, "start")
        self.assertEqual(steps["start"].provider, "vast")
        self.assertEqual(steps["pick"].params["gpu_name"], "A100")
        self.assertTrue(steps["pick"].params["auto_select"])
        self.assertTrue(steps["pick"].params["create_if_missing"])
        self.assertEqual(steps["pick"].params["disk_gb"], 200)
        self.assertTrue(steps["pick"].params["direct"])
        self.assertFalse(steps["wait"].params["stop_on_fail"])
        self.assertEqual(steps["cost"].operation, "cost")
        self.assertEqual(steps["notice"].provider, "util")
        self.assertEqual(steps["notice"].params["channels"], ["log"])

    def test_workflow_and_join_helpers(self):
        recipe = Recipe("workflow-plus")
        git_clone = recipe.git_clone("https://example.com/repo.git", "/tmp/repo", branch="main", depth=1, id="git_clone")
        git_pull = recipe.git_pull("/tmp/repo", remote="origin", branch="main", id="git_pull")
        wait_file = recipe.wait_file("/tmp/ready", host="gpu", timeout="10s", poll_interval="2s", id="wait_file")
        wait_port = recipe.wait_for_port(8080, host="gpu", host_name="127.0.0.1", id="wait_port")
        http = recipe.http_request("POST", "https://example.com", headers={"A": "1"}, body={"ok": True}, capture_var="BODY", id="http")
        hf = recipe.hf_download("repo/name", local_dir="/tmp", filename="file.bin", filenames=["a", "b"], revision="main", token="tok", host="gpu", id="hf")
        rates = recipe.fetch_exchange_rates(id="rates")
        cost = recipe.calculate_cost(vast=True, host_id="gpu", gpu_hourly_usd=1.2, storage_gb=10, currency="CNY", id="calc_cost")
        ssh = recipe.ssh_command("gpu", "echo hi", timeout=10, id="ssh")
        ssh_alias = recipe.ssh("gpu", "echo alias", timeout=5, id="ssh_alias")
        uv = recipe.uv_run("python train.py", packages=["rich", "typer"], host="gpu", timeout=300, id="uv")
        assigned = recipe.assign("RUN_ID", "demo", id="assigned")
        join = recipe.join(id="join", depends_on=[git_clone, git_pull])
        all_success = recipe.on_all_success(id="all_success", depends_on=[join])
        all_done = recipe.on_all_done(id="all_done", depends_on=[join])
        all_failed = recipe.on_all_failed(id="all_failed", depends_on=[join])
        one_success = recipe.on_one_success(id="one_success", depends_on=[join])
        one_failed = recipe.on_one_failed(id="one_failed", depends_on=[join])
        none_failed = recipe.on_none_failed(id="none_failed", depends_on=[join])
        none_failed_or_skipped = recipe.on_none_failed_or_skipped(id="none_failed_or_skipped", depends_on=[join])

        steps = {step.id: step for step in recipe.steps}
        self.assertEqual(steps["git_clone"].provider, "git")
        self.assertEqual(steps["git_pull"].params["directory"], "/tmp/repo")
        self.assertEqual(steps["wait_file"].operation, "wait_for_file")
        self.assertEqual(steps["wait_port"].params["host_name"], "127.0.0.1")
        self.assertEqual(steps["http"].provider, "http")
        self.assertEqual(steps["hf"].params["filenames"], ["a", "b"])
        self.assertEqual(steps["rates"].operation, "fetch_exchange_rates")
        self.assertTrue(steps["calc_cost"].params["vast"])
        self.assertEqual(steps["ssh"].operation, "ssh_command")
        self.assertEqual(steps["ssh_alias"].operation, "ssh_command")
        self.assertEqual(steps["uv"].params["packages"], ["rich", "typer"])
        self.assertEqual(steps["assigned"].operation, "set_var")
        self.assertEqual(steps["join"].trigger_rule, "all_done")
        self.assertEqual(steps["all_success"].trigger_rule, "all_success")
        self.assertEqual(steps["all_done"].trigger_rule, "all_done")
        self.assertEqual(steps["all_failed"].trigger_rule, "all_failed")
        self.assertEqual(steps["one_success"].trigger_rule, "one_success")
        self.assertEqual(steps["one_failed"].trigger_rule, "one_failed")
        self.assertEqual(steps["none_failed"].trigger_rule, "none_failed")
        self.assertEqual(steps["none_failed_or_skipped"].trigger_rule, "none_failed_or_skipped")

    def test_unbound_control_mixin_aliases(self):
        recipe = Recipe("control-unbound")
        RecipeControlMixin.notice(recipe, "hello", channels=["log"], id="notice")
        RecipeControlMixin.vast_start(recipe, "1", id="start")
        RecipeControlMixin.vast_stop(recipe, "1", id="stop")
        RecipeControlMixin.vast_pick(recipe, "gpu", gpu_name="A100", num_gpus=2, min_gpu_ram=80, max_dph=2.5, limit=1, id="pick")
        RecipeControlMixin.vast_wait(recipe, "1", timeout="10m", poll_interval="10s", stop_on_fail=False, id="wait")
        RecipeControlMixin.vast_cost(recipe, "1", id="cost")
        RecipeControlMixin.join(recipe, id="join")

        steps = {step.id: step for step in recipe.steps}
        self.assertEqual(steps["notice"].provider, "util")
        self.assertEqual(steps["start"].provider, "vast")
        self.assertEqual(steps["stop"].provider, "vast")
        self.assertEqual(steps["pick"].params["gpu_name"], "A100")
        self.assertFalse(steps["wait"].params["stop_on_fail"])
        self.assertEqual(steps["cost"].operation, "cost")
        self.assertEqual(steps["join"].trigger_rule, "all_done")

    def test_base_normalization_and_resource_resolution(self):
        recipe = Recipe("base-demo")
        with recipe as same:
            self.assertIs(same, recipe)
        self.assertFalse(recipe.__exit__(None, None, None))

        recipe.set_executor("thread_pool", max_workers=3)
        self.assertEqual(recipe.executor, "thread_pool")
        self.assertEqual(recipe.executor_kwargs["max_workers"], 3)
        with self.assertRaises(PythonRecipeError):
            recipe.set_executor("kubernetes")

        recipe.defaults(
            retries="2",
            retry_delay="5s",
            continue_on_failure="yes",
            trigger_rule="all_done",
            pool="io",
            priority="3",
            execution_timeout="2m",
            retry_exponential_backoff=True,
            max_active_tis_per_dagrun="2",
            deferrable="true",
        )
        step_id = recipe.empty(id="start")
        step = recipe.steps[0]
        self.assertEqual(step_id, "start")
        self.assertEqual(step.retries, 2)
        self.assertEqual(step.retry_delay, 5)
        self.assertTrue(step.continue_on_failure)
        self.assertEqual(step.trigger_rule, "all_done")
        self.assertEqual(step.pool, "io")
        self.assertEqual(step.priority, 3)
        self.assertEqual(step.execution_timeout, 120)
        self.assertEqual(step.retry_exponential_backoff, 2.0)
        self.assertEqual(step.max_active_tis_per_dagrun, 2)
        self.assertTrue(step.deferrable)

        with self.assertRaises(PythonRecipeError):
            recipe.defaults(trigger_rule="bad")

        self.assertEqual(recipe._normalize_timeout("1h"), 3600)
        self.assertEqual(recipe._normalize_timeout("2m"), 120)
        self.assertEqual(recipe._normalize_timeout("3s"), 3)
        self.assertTrue(recipe._normalize_bool("yes"))
        self.assertEqual(recipe._normalize_list("a, b"), ["a", "b"])
        self.assertEqual(recipe._clean_session("@main"), "main")

        host = Host("ssh://gpu", name="gpu")
        artifacts = Storage("r2:bucket", name="artifacts")
        runtime_storage = Storage(RuntimeStorage(name="local-artifacts", type=StorageType.LOCAL, config={"path": "/tmp/out"}))
        self.assertEqual(recipe.resolve_host(host), "gpu")
        self.assertEqual(recipe.resolve_storage(artifacts), "artifacts")
        self.assertEqual(recipe.resolve_storage(runtime_storage), "local_artifacts")
        self.assertIn("@gpu:/tmp/x", recipe.resolve_endpoint(host.path("/tmp/x")))
        self.assertIn("@artifacts:/out", recipe.resolve_endpoint(artifacts.path("/out")))
        self.assertEqual(recipe.resolve_endpoint(Path("/tmp/local")), "/tmp/local")

        copy = recipe.copy(host.path("/tmp/in"), artifacts.path("/out"), id="copy")
        move = recipe.move(artifacts.path("/out"), "/tmp/local", id="move")
        sync = recipe.sync("/tmp/local", host.path("/tmp/out"), id="sync")
        self.assertEqual(copy, "copy")
        self.assertEqual(move, "move")
        self.assertEqual(sync, "sync")
        self.assertEqual(recipe.step_count(), 4)

    def test_base_dependency_validation_and_handles(self):
        recipe = Recipe("deps-demo")
        with self.assertRaises(PythonRecipeError):
            recipe._add_step(object())

        start = recipe.empty(id="start")
        follow = recipe.empty(id="follow", depends_on=[start])
        recipe.link_step_dependencies(follow, [start])
        self.assertEqual(recipe.steps[1].depends_on, ["start"])

        with self.assertRaises(PythonRecipeError):
            recipe.link_step_dependencies("follow", ["missing"])
        with self.assertRaises(PythonRecipeError):
            recipe.link_step_dependencies("follow", ["follow"])

        with recipe.linear():
            a = recipe.empty(id="a")
            b = recipe.empty(id="b")
        self.assertEqual(recipe.steps[3].depends_on, ["a"])

        self.assertEqual(recipe.current_linear_dependency(), None)

        with tempfile.TemporaryDirectory() as tmpdir:
            host = Host("ssh://gpu", name="gpu")
            storage = Storage("r2:bucket", name="artifacts")
            session = recipe.session("main", host=host, id="open_main")
            self.assertEqual(session.open_step_id, "open_main")
            after_session = session.after(a)
            self.assertIn("a", after_session.default_depends_on)


if __name__ == "__main__":
    unittest.main()

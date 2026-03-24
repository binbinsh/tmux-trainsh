import tempfile
import unittest
from pathlib import Path

from trainsh import Recipe, flash_attn_install_script, local, official_uv_install_command
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
        clone = recipe.git_clone(
            "https://github.com/example/repo.git",
            "/tmp/repo",
            branch="main",
            depth=1,
            auth="github_token",
            token_secret="PRIVATE_GITHUB_TOKEN",
            host="gpu",
            id="clone",
        )
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
        self.assertEqual(steps["clone"].params["auth"], "github_token")
        self.assertEqual(steps["clone"].params["token_secret"], "PRIVATE_GITHUB_TOKEN")
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

        session = Host("gpu", name="gpu").tmux("main", id="open_main")
        install_uv = session.install_uv(id="install_uv")
        install_flash_attn = session.install_flash_attn(
            version="2.8.3",
            python_bin="/venv/main/bin/python",
            max_jobs=4,
            extra_env={"FLASH_ATTN_CUDA_ARCHS": "120"},
            id="install_flash_attn",
        )
        steps = {step.id: step for step in recipe.steps}
        self.assertIn("astral.sh/uv/install.sh", steps["install_uv"].raw)
        self.assertEqual(install_uv, "install_uv")
        self.assertIn("flash-attn==2.8.3", steps["install_flash_attn"].commands)
        self.assertIn("FLASH_ATTN_CUDA_ARCHS=120", steps["install_flash_attn"].commands)
        self.assertEqual(install_flash_attn, "install_flash_attn")

    def test_official_uv_install_command_variants(self):
        default = official_uv_install_command()
        forced = official_uv_install_command(force=True)
        self.assertIn("astral.sh/uv/install.sh", default)
        self.assertIn("export PATH=\"$HOME/.local/bin:$PATH\"", default)
        self.assertIn("curl -LsSf https://astral.sh/uv/install.sh | sh", forced)

        flash_default = flash_attn_install_script(version="2.8.3")
        flash_auto = flash_attn_install_script(package_name="flash-attn-4", install_spec="flash-attn-4==4.0.0b5")
        self.assertIn("flash-attn==2.8.3", flash_default)
        self.assertIn("flash-attn-4==4.0.0b5", flash_auto)

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

        with self.assertRaises(PythonRecipeError):
            Recipe("bad-owner", owner="ml")
        with self.assertRaises(PythonRecipeError):
            Recipe("bad-tags", tags=["nightly"])

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

        a = recipe.empty(id="a")
        b = recipe.empty(id="b")
        self.assertEqual(recipe.steps[2].depends_on, ["follow"])
        self.assertEqual(recipe.steps[3].depends_on, ["a"])

        self.assertEqual(recipe.current_linear_dependency(), None)

        with tempfile.TemporaryDirectory() as tmpdir:
            host = Host("ssh://gpu", name="gpu")
            storage = Storage("r2:bucket", name="artifacts")
            session = host.tmux("main", id="open_main")
            self.assertEqual(session.open_step_id, "open_main")
            after_session = session.after(a)
            self.assertIn("a", after_session.default_depends_on)

    def test_tmux_after_does_not_retrofit_open_step_into_a_cycle(self):
        recipe = Recipe("session-after")
        session = local.tmux("main", id="open_main")
        train = session.run("echo train", id="train")
        gated = session.after(train)
        gated.file("/tmp/done", id="wait_done")

        steps = {step.id: step for step in recipe.steps}
        self.assertEqual(steps["open_main"].depends_on, [])
        self.assertEqual(steps["train"].depends_on, ["open_main"])
        self.assertEqual(set(steps["wait_done"].depends_on), {"open_main", "train"})

    def test_local_and_remote_flow_helpers_reduce_session_boilerplate(self):
        recipe = Recipe("flow-demo")
        start = recipe.empty(id="start")

        with local.tmux("main") as main:
            main.run("echo local", id="local_run")

        with Host("gpu", name="gpu").tmux("work", depends_on=[start]) as work:
            work.run("echo remote", id="remote_run")

        steps = {step.id: step for step in recipe.steps}
        self.assertEqual(steps["step_001"].raw, "tmux.open @local as main")
        self.assertEqual(steps["local_run"].depends_on, ["step_001"])
        self.assertEqual(steps["step_002"].depends_on, ["step_001", "local_run"])
        self.assertEqual(steps["step_003"].depends_on, ["start"])
        self.assertEqual(steps["remote_run"].depends_on, ["step_003"])
        self.assertEqual(steps["step_004"].depends_on, ["step_003", "remote_run"])

    def test_tmux_blocks_chain_by_default_without_explicit_depends_on(self):
        recipe = Recipe("tmux-chain")
        with local.tmux("main") as tmux:
            tmux.run("echo one", id="first_run")
        with Host("gpu", name="gpu").tmux("work") as tmux:
            tmux.run("echo two", id="second_run")

        steps = {step.id: step for step in recipe.steps}
        self.assertEqual(steps["first_run"].depends_on, ["step_001"])
        self.assertEqual(steps["step_002"].depends_on, ["step_001", "first_run"])
        self.assertEqual(steps["step_003"].depends_on, ["step_002"])
        self.assertEqual(steps["second_run"].depends_on, ["step_003"])

    def test_flow_helpers_support_default_cwd_env_and_multiline_script(self):
        recipe = Recipe("flow-context")

        with Host("gpu", name="gpu").tmux("work", cwd="/workspace/app", env={"MODE": "prod"}) as work:
            work.run("python train.py", id="run_train")
            work.script(
                """
                echo one
                echo two
                """,
                id="script_train",
            )
            work.script(
                "echo three",
                tee="/tmp/train.log",
                done_file="/tmp/train.done",
                id="script_with_markers",
            )
            work.run("printf '42\\n'", capture_var="VALUE", id="capture_value")

        steps = {step.id: step for step in recipe.steps}
        self.assertIn("cd /workspace/app", steps["run_train"].commands)
        self.assertIn("export MODE=prod", steps["run_train"].commands)
        self.assertIn("python train.py", steps["run_train"].commands)
        self.assertIn("bash -lc", steps["script_train"].commands)
        self.assertIn("set -euo pipefail", steps["script_train"].commands)
        self.assertIn("echo one", steps["script_train"].commands)
        self.assertIn("tee -a /tmp/train.log", steps["script_with_markers"].commands)
        self.assertIn("/tmp/train.done", steps["script_with_markers"].commands)
        self.assertEqual(steps["capture_value"].capture_var, "VALUE")
        self.assertIn("trainsh_capture_", steps["capture_value"].capture_path)

        with self.assertRaises(PythonRecipeError):
            local.tmux("main").run("echo bad", stdout="/tmp/out", tee="/tmp/log")
        with self.assertRaises(PythonRecipeError):
            local.tmux("main").run("echo bad", background=True, capture_var="OUT")

    def test_tmux_object_preserves_tmux_first_authoring(self):
        recipe = Recipe("session-demo")
        session = local.tmux("main", cwd="/tmp/app", env={"MODE": "dev"}, id="open_main")
        run_step = session.run("python train.py", id="run_train")
        remote = Host("gpu", name="gpu").tmux("work", depends_on=[run_step])
        remote.sh("echo remote", id="remote_script")

        steps = {step.id: step for step in recipe.steps}
        self.assertEqual(session.open_step_id, "open_main")
        self.assertEqual(steps["run_train"].depends_on, ["open_main"])
        self.assertIn("cd /tmp/app", steps["run_train"].commands)
        self.assertIn("export MODE=dev", steps["run_train"].commands)
        self.assertEqual(steps["step_001"].depends_on, ["run_train"])
        self.assertIn("bash -lc", steps["remote_script"].commands)

    def test_local_tmux_surface_applies_context_defaults(self):
        recipe = Recipe("tmux-demo")
        tmux = local.tmux("main", cwd="/tmp/app")
        tmux.run("echo hi")

        steps = list(recipe.steps)
        self.assertEqual(steps[0].raw, "tmux.open @local as main")
        self.assertIn("cd /tmp/app", steps[1].commands)

    def test_host_and_local_tmux_helpers_bind_to_active_recipe(self):
        recipe = Recipe("host-tmux")
        gpu = Host("gpu-box", name="gpu")

        with gpu.tmux("train") as tmux:
            tmux.run("echo hi")
        with local.tmux("local") as tmux:
            tmux.run("echo local")

        steps = list(recipe.steps)
        self.assertEqual(steps[0].raw, "tmux.open @gpu as train")
        self.assertEqual(steps[3].raw, "tmux.open @local as local")

    def test_tmux_transfer_helpers_attach_to_tmux_host(self):
        recipe = Recipe("session-transfer")
        gpu = Host("ssh://gpu.example.com", name="gpu")
        session = gpu.tmux("work", id="open_work")

        put = session.upload("/tmp/local.txt", "/remote/in.txt", id="put_file")
        pull = session.download("/remote/out.txt", "/tmp/out.txt", id="get_file", depends_on=[put])
        sync = session.sync_from("/remote/tree", "/tmp/tree", id="sync_tree", depends_on=[pull])

        steps = {step.id: step for step in recipe.steps}
        self.assertEqual(put, "put_file")
        self.assertEqual(pull, "get_file")
        self.assertEqual(sync, "sync_tree")
        self.assertEqual(steps["put_file"].provider, "transfer")
        self.assertIn("@gpu:/remote/in.txt", steps["put_file"].params["destination"])
        self.assertEqual(steps["put_file"].depends_on, ["open_work"])
        self.assertIn("@gpu:/remote/out.txt", steps["get_file"].params["source"])
        self.assertEqual(set(steps["get_file"].depends_on), {"open_work", "put_file"})
        self.assertIn("@gpu:/remote/tree", steps["sync_tree"].params["source"])

    def test_tmux_can_be_reused_by_name_in_later_stage(self):
        recipe = Recipe("tmux-reuse")
        gpu = Host("ssh://gpu.example.com", name="gpu")

        work = gpu.tmux("work")
        work.run("echo train")

        with gpu.tmux("work"):
            gpu.tmux("work").download("/remote/out.txt", "/tmp/out.txt")

        steps = list(recipe.steps)
        self.assertEqual(steps[0].id, "step_001")
        self.assertEqual(steps[1].depends_on, ["step_001"])
        self.assertEqual(set(steps[2].depends_on), {"step_001", "step_002"})
        self.assertIn("@gpu:/remote/out.txt", steps[2].params["source"])


if __name__ == "__main__":
    unittest.main()

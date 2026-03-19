import unittest
from pathlib import Path

from trainsh import Recipe, local
from trainsh.core.models import Storage as RuntimeStorage, StorageType
from trainsh.pyrecipe.base import RecipeSpecCore
from trainsh.pyrecipe.models import Host, ProviderStep, PythonRecipeError, Storage, StoragePath


class PyrecipeCoreTests(unittest.TestCase):
    def test_constructor_executor_and_default_linear_edges(self):
        self.assertEqual(Recipe("").name, "recipe")
        with self.assertRaises(PythonRecipeError):
            Recipe("   ")
        with self.assertRaises(PythonRecipeError):
            Recipe("demo", executor="kubernetes")

        recipe = Recipe("demo", callbacks=("console",), workers=2)
        self.assertEqual(recipe.callbacks, ["console"])
        self.assertEqual(recipe.executor_kwargs["max_workers"], 2)

        with self.assertRaises(PythonRecipeError):
            recipe.set_executor("")
        with self.assertRaises(PythonRecipeError):
            recipe.set_executor("kubernetes")

        a = recipe.empty(id="a")
        b = recipe.empty(id="b")
        c = recipe.empty(id="c")
        d = recipe.empty(id="d")
        self.assertEqual(recipe.steps[1].depends_on, ["a"])
        self.assertEqual(recipe.steps[2].depends_on, ["b"])
        self.assertEqual(recipe.steps[3].depends_on, ["c"])

        recipe = Recipe("linear-depends")
        start = recipe.empty(id="start")
        with local.tmux("main", depends_on=start) as tmux:
            a = tmux.run("echo a", id="a")
            b = tmux.run("echo b", id="b")
        self.assertEqual(recipe.steps[1].depends_on, ["start"])
        self.assertEqual(recipe.steps[2].depends_on, ["step_001"])
        self.assertEqual(recipe.steps[3].depends_on, ["step_001", "a"])
        self.assertEqual(recipe.steps[4].depends_on, ["step_001", "b"])
        self.assertEqual(str(recipe.last()), "step_002")

        recipe = Recipe("last-handle")
        recipe.empty(id="first")
        recipe.empty(id="second", depends_on=recipe.last())
        self.assertEqual(recipe.steps[1].depends_on, ["first"])

    def test_normalize_options_timeout_callbacks_and_ids(self):
        recipe = Recipe("demo")
        with self.assertRaises(PythonRecipeError):
            recipe._normalize_step_options({"retries": "bad"})
        with self.assertRaises(PythonRecipeError):
            recipe._normalize_step_options({"trigger_rule": "bad"})
        with self.assertRaises(PythonRecipeError):
            recipe._normalize_timeout("")
        with self.assertRaises(PythonRecipeError):
            recipe._normalize_timeout(object())

        opts = recipe._normalize_step_options(
            {
                "max_retries": 3,
                "retry_delay": None,
                "priority": "bad",
                "execution_timeout": "",
                "retry_exponential_backoff": "-1",
                "max_active_tis_per_dagrun": "bad",
                "deferrable": "",
                "on_success": object(),
                "on_failure": [None, "echo hi"],
            }
        )
        self.assertEqual(opts["retries"], 3)
        self.assertEqual(opts["retry_delay"], 0)
        self.assertEqual(opts["priority"], 0)
        self.assertEqual(opts["execution_timeout"], 0)
        self.assertEqual(opts["retry_exponential_backoff"], 0.0)
        self.assertEqual(opts["max_active_tis_per_dagrun"], 1)
        self.assertFalse(opts["deferrable"])
        self.assertEqual(opts["on_success"], [])
        self.assertEqual(opts["on_failure"], ["echo hi"])

        opts = recipe._normalize_step_options(
            {
                "retry_delay": True,
                "priority": True,
                "execution_timeout": True,
                "retry_exponential_backoff": -2,
                "max_active_tis_per_dagrun": False,
                "on_success": b"echo hi",
            }
        )
        self.assertEqual(opts["retry_delay"], 1)
        self.assertEqual(opts["priority"], 1)
        self.assertEqual(opts["execution_timeout"], 1)
        self.assertEqual(opts["retry_exponential_backoff"], 0.0)
        self.assertIsNone(opts["max_active_tis_per_dagrun"])
        self.assertEqual(opts["on_success"], [b"echo hi"])

        with self.assertRaises(ValueError):
            recipe._normalize_step_options({"execution_timeout": "bad"})
        opts = recipe._normalize_step_options({"max_active_tis_per_dagrun": "bad"})
        self.assertEqual(opts["max_active_tis_per_dagrun"], 1)

        self.assertEqual(recipe._normalize_bool(None, default=True), True)
        self.assertEqual(recipe._normalize_bool("", default=False), False)
        self.assertEqual(recipe._normalize_list(None), [])
        self.assertEqual(recipe._normalize_list(""), [])
        self.assertEqual(recipe._normalize_list(["a", "", "b"]), ["a", "b"])
        self.assertEqual(recipe._normalize_step_callbacks(None), [])
        self.assertEqual(recipe._normalize_step_callbacks(object()), [])
        self.assertEqual(recipe._normalize_step_callbacks([None, object()]), [])

        first = recipe._next_step_id()
        self.assertEqual(first, "step_001")
        with self.assertRaises(PythonRecipeError):
            recipe._next_step_id(first)
        recipe._used_ids.add("step_002")
        self.assertEqual(recipe._next_step_id(), "step_003")

    def test_add_step_link_dependencies_and_resource_aliases(self):
        recipe = Recipe("demo")
        start = recipe.empty(id="start")
        provider = ProviderStep("util", "empty", {}, id="prov")
        prov_id = recipe._add_step(provider, depends_on=[start])
        self.assertEqual(prov_id, "step_001")
        self.assertEqual(recipe.steps[-1].depends_on, ["start"])

        with self.assertRaises(PythonRecipeError):
            recipe._add_step(provider, depends_on=["missing"], step_id="x")
        with self.assertRaises(PythonRecipeError):
            recipe._add_step(object(), id="bad")

        self.assertEqual(recipe._step_by_id("start").id, "start")
        with self.assertRaises(PythonRecipeError):
            recipe._step_by_id("missing")
        with self.assertRaises(PythonRecipeError):
            recipe._add_step(ProviderStep("util", "empty", {}, id="x"), depends_on=["missing"], id="x")

        recipe.link_step_dependencies(prov_id, ["start", "start"])
        self.assertEqual(recipe.steps[-1].depends_on, ["start"])

        host_a = Host("ssh://gpu-a", name="gpu")
        host_b = Host("ssh://gpu-b", name="gpu")
        self.assertEqual(recipe._host_alias_for(host_a), "gpu")
        self.assertEqual(recipe._host_alias_for(host_a), "gpu")
        self.assertEqual(recipe._host_alias_for(host_b), "gpu_2")

        runtime_a = Storage(RuntimeStorage(name="artifacts", type=StorageType.LOCAL, config={"path": "/tmp/a"}))
        runtime_b = Storage(RuntimeStorage(name="artifacts", type=StorageType.LOCAL, config={"path": "/tmp/b"}))
        self.assertEqual(recipe._storage_alias_for(runtime_a), "artifacts")
        self.assertEqual(recipe._storage_alias_for(runtime_a), "artifacts")
        self.assertEqual(recipe._storage_alias_for(runtime_b), "artifacts_2")

        self.assertEqual(recipe.resolve_storage(StoragePath(runtime_a, "/out")), "artifacts")
        self.assertEqual(recipe.resolve_storage("@artifacts"), "artifacts")
        self.assertEqual(recipe.resolve_host("@gpu"), "@gpu")
        self.assertEqual(recipe.resolve_endpoint(Path("/tmp/local")), "/tmp/local")

        model = recipe.to_recipe_model()
        self.assertEqual(model.name, "demo")
        self.assertEqual(len(model.steps), len(recipe.steps))
        self.assertEqual(recipe.step_count(), len(recipe.steps))


if __name__ == "__main__":
    unittest.main()

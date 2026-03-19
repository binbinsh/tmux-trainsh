import ast
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from trainsh.core.dag_processor import DagProcessor, DagSchedule, ParsedDag, _to_seconds, dag_id_from_path, parse_schedule


class DagProcessorEdgeTests(unittest.TestCase):
    def test_schedule_helpers_and_model_properties(self):
        self.assertEqual(_to_seconds(1, "s"), 1)
        self.assertEqual(_to_seconds(2, "m"), 120)
        self.assertEqual(_to_seconds(3, "h"), 10800)
        self.assertEqual(_to_seconds(4, "d"), 345600)
        self.assertEqual(_to_seconds(5, "x"), 5)

        self.assertEqual(parse_schedule(None).kind, "manual")
        self.assertEqual(parse_schedule("").kind, "manual")
        self.assertEqual(parse_schedule("disabled").kind, "disabled")
        self.assertEqual(parse_schedule("@daily").interval_seconds, 86400)
        self.assertEqual(parse_schedule("@every 5m").interval_seconds, 300)
        self.assertEqual(parse_schedule("10s").interval_seconds, 10)
        self.assertEqual(parse_schedule("@unknown").kind, "manual")
        self.assertEqual(parse_schedule("0 0 * * *").kind, "cron")
        self.assertEqual(parse_schedule("adhoc").kind, "manual")

        sched = DagSchedule(raw="@daily", kind="interval", interval_seconds=86400)
        self.assertTrue(sched.is_due_capable)
        self.assertTrue(sched.is_supported)
        unsupported = DagSchedule(raw="@weird", kind="cron", interval_seconds=None)
        self.assertFalse(unsupported.is_due_capable)
        self.assertFalse(unsupported.is_supported)

        with tempfile.TemporaryDirectory() as tmpdir:
            recipe_path = Path(tmpdir) / "demo.pyrecipe"
            recipe_path.write_text("print('ok')\n", encoding="utf-8")
            dag = ParsedDag(
                dag_id=str(recipe_path),
                path=recipe_path,
                recipe_name="demo",
                is_python=True,
                schedule="@daily",
                schedule_meta=sched,
                max_active_runs=0,
                max_active_runs_per_dag=None,
                load_error=None,
            )
            self.assertTrue(dag.is_valid)
            self.assertTrue(dag.is_enabled)
            self.assertEqual(dag.normalized_max_active_runs, 1)
            self.assertEqual(dag.normalized_max_active_runs_per_dag, 1)
            self.assertTrue(dag.is_interval_schedulable)
            with patch("trainsh.core.dag_processor.load_python_recipe", return_value="recipe") as mocked_load:
                self.assertEqual(dag.load_recipe(), "recipe")
            mocked_load.assert_called_once()

    def test_discover_files_process_and_metadata_helpers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            recipes = root / "recipes"
            recipes.mkdir()
            nested = recipes / "nested"
            nested.mkdir()
            (recipes / "demo.pyrecipe").write_text("# owner: ops\n", encoding="utf-8")
            (recipes / "note.txt").write_text("x\n", encoding="utf-8")
            (nested / "deep.pyrecipe").write_text("# tags: a, b\n", encoding="utf-8")

            processor = DagProcessor([str(recipes)], recursive=False, include_patterns=["*.pyrecipe"])
            files = processor.discover_files()
            self.assertEqual({p.name for p in files}, {"demo.pyrecipe"})

            processor = DagProcessor([str(recipes)], recursive=True)
            files = processor.discover_files()
            self.assertEqual({p.name for p in files}, {"demo.pyrecipe", "deep.pyrecipe"})

            file_processor = DagProcessor([str(recipes / "demo.pyrecipe")])
            self.assertEqual([p.name for p in file_processor.discover_files()], ["demo.pyrecipe"])
            missing_processor = DagProcessor([str(root / "missing")])
            self.assertEqual(missing_processor.discover_files(), [])

            py = textwrap.dedent(
                """
                # owner: ops
                # tags: a, b
                # callbacks: console, sqlite
                from trainsh import Recipe

                schedule_interval = "@daily"
                executor_kwargs = {"max_workers": 2}
                callbacks = ["console"]
                with Recipe("demo", paused=True, catchup="yes", max_active_runs=3, executor="thread_pool") as recipe:
                    pass
                """
            )
            recipe_path = recipes / "dag.pyrecipe"
            recipe_path.write_text(py, encoding="utf-8")
            dag = processor.process_dag_file(recipe_path)
            self.assertEqual(dag.recipe_name, "demo")
            self.assertEqual(dag.schedule, "@daily")
            self.assertTrue(dag.is_paused)
            self.assertTrue(dag.catchup)
            self.assertEqual(dag.owner, "ops")
            self.assertEqual(dag.tags, ["a", "b"])
            self.assertEqual(dag.callbacks, ["console"])
            self.assertEqual(dag.max_active_runs, 3)
            self.assertEqual(dag.executor, "thread_pool")
            self.assertEqual(dag.executor_kwargs, {"max_workers": 2})

            bad_path = recipes / "bad.pyrecipe"
            bad_path.write_text("def broken(:\n", encoding="utf-8")
            bad = processor.process_dag_file(bad_path)
            self.assertFalse(bad.is_valid)
            self.assertIsNotNone(bad.load_error)

            text = textwrap.dedent(
                """
                # owner = ops
                # tags: a, b
                name = "alpha"
                cron = "@hourly"
                meta = {"x": 1}
                recipe = Recipe("beta", callbacks=["sqlite"], executor_kwargs={"x": 1})
                """
            )
            meta = processor._parse_metadata(recipe_path, text)
            self.assertEqual(meta["owner"], "ops")
            self.assertEqual(meta["tags"], "a, b")
            self.assertEqual(meta["name"], "alpha")
            self.assertEqual(meta["callbacks"], ["sqlite"])
            self.assertEqual(meta["executor_kwargs"], {"x": 1})

            self.assertEqual(processor._parse_comment_metadata("# unknown: x\n# owner: team\n")["owner"], "team")
            self.assertEqual(processor._parse_comment_metadata("# owner: plain-text\n")["owner"], "plain-text")
            self.assertEqual(processor._parse_python_assignments("def broken(:\n"), {})

            tree = ast.parse("with Recipe('demo') as recipe:\n    pass\n")
            call = processor._find_recipe_call(tree)
            self.assertIsNotNone(call)
            self.assertEqual(processor._parse_recipe_name_call(tree), "demo")
            self.assertTrue(processor._is_recipe_factory_call(call))
            attr_call = ast.parse("x = ns.Recipe('demo')").body[0].value
            self.assertTrue(processor._is_recipe_factory_call(attr_call))
            non_call = ast.parse("x = 1").body[0]
            self.assertIsNone(processor._recipe_call_from_node(non_call))

            ann_tree = ast.parse("name: str = 'alpha'\n")
            parsed = processor._parse_python_assignments("name: str = 'alpha'\n")
            self.assertEqual(parsed["name"], "alpha")
            self.assertEqual(processor._safe_literal("['a']"), ["a"])
            self.assertIsNone(processor._safe_literal("bad("))
            self.assertIsNone(processor._safe_literal(5))
            self.assertTrue(processor._coerce_bool("yes"))
            self.assertFalse(processor._coerce_bool("no"))
            self.assertEqual(processor._coerce_scalar("  x  "), "x")
            self.assertIsNone(processor._coerce_scalar(""))
            self.assertEqual(processor._coerce_list("a, 'b'"), ["a", "b"])
            self.assertEqual(processor._coerce_list({"x": 1}), [])
            self.assertEqual(processor._coerce_dict({"a": 1}), {"a": 1})
            self.assertEqual(processor._coerce_dict([]), {})
            self.assertEqual(dag_id_from_path(recipe_path), str(recipe_path.resolve()))


if __name__ == "__main__":
    unittest.main()

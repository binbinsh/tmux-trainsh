import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GenerateDocsTests(unittest.TestCase):
    def test_generate_docs_outputs_reference_pages(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trainsh-generate-docs-") as temp_dir:
            docs_dir = Path(temp_dir) / "docs"
            env = os.environ.copy()
            env["HOME"] = str(Path(temp_dir) / "home")

            result = subprocess.run(
                [sys.executable, "scripts/generate_docs.py", "--output", str(docs_dir)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            run_page = docs_dir / "cli-reference" / "run.md"
            run_page_zh = docs_dir / "cli-reference" / "run.zh.md"
            api_index = docs_dir / "package-reference" / "_index.md"
            api_index_zh = docs_dir / "package-reference" / "_index.zh.md"
            examples_page = docs_dir / "examples" / "_index.md"
            examples_page_zh = docs_dir / "examples" / "_index.zh.md"
            documentation_page = docs_dir / "documentation.md"
            documentation_page_zh = docs_dir / "documentation.zh.md"
            public_models_page = docs_dir / "package-reference" / "public-models.md"
            hello_example_page = docs_dir / "examples" / "hello.md"
            hello_example_page_zh = docs_dir / "examples" / "hello.zh.md"

            self.assertTrue(run_page.exists())
            self.assertTrue(run_page_zh.exists())
            self.assertTrue(api_index.exists())
            self.assertTrue(api_index_zh.exists())
            self.assertTrue(examples_page.exists())
            self.assertTrue(examples_page_zh.exists())
            self.assertTrue(documentation_page.exists())
            self.assertTrue(documentation_page_zh.exists())
            self.assertTrue(public_models_page.exists())
            self.assertTrue(hello_example_page.exists())
            self.assertTrue(hello_example_page_zh.exists())

            self.assertIn("train run --help", run_page.read_text(encoding="utf-8"))
            self.assertIn("立即执行一个 recipe", run_page_zh.read_text(encoding="utf-8"))
            self.assertIn("from trainsh.pyrecipe import *", api_index.read_text(encoding="utf-8"))
            self.assertIn("这一节是 Python 编写 API 的技术参考", api_index_zh.read_text(encoding="utf-8"))
            self.assertIn("feature-tour.py", examples_page.read_text(encoding="utf-8"))
            self.assertIn("高级 Python recipe 功能", examples_page_zh.read_text(encoding="utf-8"))
            self.assertIn("python scripts/generate_docs.py", documentation_page.read_text(encoding="utf-8"))
            self.assertIn("把完整 Hugo 文档树导出到另一个站点", documentation_page_zh.read_text(encoding="utf-8"))
            self.assertIn("load_python_recipe", public_models_page.read_text(encoding="utf-8"))
            hello_text = hello_example_page.read_text(encoding="utf-8")
            hello_text_zh = hello_example_page_zh.read_text(encoding="utf-8")
            self.assertIn("train run hello-world", hello_text)
            self.assertIn("session(\"hello\", on=\"local\")", hello_text)
            self.assertIn("运行这个示例", hello_text_zh)
            self.assertTrue(hello_text.startswith("+++"))
            self.assertTrue(hello_text_zh.startswith("+++"))


if __name__ == "__main__":
    unittest.main()

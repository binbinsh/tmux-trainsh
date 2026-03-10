import tempfile
import textwrap
import unittest
from pathlib import Path

from trainsh.legacy_recipe_converter import (
    convert_legacy_recipe_file,
    convert_legacy_recipe_text,
)


class LegacyRecipeConverterTests(unittest.TestCase):
    def test_converts_simple_hello_recipe(self):
        legacy = textwrap.dedent(
            """
            # hello-world
            var MESSAGE = Hello from trainsh

            tmux.open @local as hello
            @hello > echo "$MESSAGE"
            notify "$MESSAGE"
            tmux.close @hello
            """
        )

        converted = convert_legacy_recipe_text(legacy, recipe_name="hello")

        self.assertIn('from trainsh.pyrecipe import *', converted)
        self.assertIn('recipe("hello")', converted)
        self.assertIn('var("MESSAGE", "Hello from trainsh")', converted)
        self.assertIn('hello = session("hello", on="local")', converted)
        self.assertIn('step_001 = hello("echo \\"$MESSAGE\\"", after=hello)', converted)
        self.assertIn('notice_002 = notice("$MESSAGE", after=step_001)', converted)
        self.assertIn('close_003 = hello.close(after=notice_002)', converted)

    def test_converts_vast_background_wait_and_transfer(self):
        legacy = textwrap.dedent(
            """
            var WORKDIR = /workspace/nanoGPT
            host gpu = placeholder

            vast.pick @gpu num_gpus=1 min_gpu_ram=16
            vast.wait timeout=5m
            tmux.open @gpu as work
            @work > python train.py &
            wait @work "training finished" timeout=2h
            @gpu:$WORKDIR/train.log -> ./train.log
            vast.stop
            tmux.close @work
            """
        )

        converted = convert_legacy_recipe_text(legacy, recipe_name="nanogpt-train")

        self.assertIn('host("gpu", "placeholder")', converted)
        self.assertIn('pick_001 = vast_pick(host="gpu", num_gpus=1, min_gpu_ram=16)', converted)
        self.assertIn('wait_002 = vast_wait(timeout="5m", after=pick_001)', converted)
        self.assertIn('work = session("work", on="gpu", after=wait_002)', converted)
        self.assertIn('step_003 = work.bg("python train.py", after=work)', converted)
        self.assertIn('wait_004 = work.wait("training finished", timeout="2h", after=step_003)', converted)
        self.assertIn('transfer_005 = transfer("@gpu:$WORKDIR/train.log", "./train.log", after=wait_004)', converted)
        self.assertIn("stop_006 = vast_stop(after=transfer_005)", converted)
        self.assertIn("close_007 = work.close(after=stop_006)", converted)

    def test_converts_heredoc_execute_and_writes_file(self):
        legacy = textwrap.dedent(
            """
            tmux.open @gpu as work
            @work > cat > /tmp/demo.sh <<'SCRIPT'
            echo hello
            SCRIPT
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "demo.recipe"
            source.write_text(legacy, encoding="utf-8")

            target = convert_legacy_recipe_file(source, force=True)
            converted = target.read_text(encoding="utf-8")

        self.assertEqual(target.name, "demo.py")
        self.assertIn('work = session("work", on="gpu")', converted)
        self.assertIn('step_001 = work("""cat > /tmp/demo.sh <<\'SCRIPT\'\necho hello\nSCRIPT""", after=work)', converted)


if __name__ == "__main__":
    unittest.main()

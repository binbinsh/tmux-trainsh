"""Recipe file templates used by the CLI."""

from __future__ import annotations

from textwrap import dedent


_MINIMAL_TEMPLATE = """\
from trainsh import Recipe, local

recipe = Recipe("__NAME__", schedule="@every 30m", callbacks=["console", "jsonl"])
message = "Hello from trainsh"

with local.tmux("main") as tmux:
    tmux.run(["printf", "%s\\n", message])
    recipe.notify(message)
"""


_REMOTE_TRAIN_TEMPLATE = """\
from trainsh import Host, Recipe, Storage

recipe = Recipe("__NAME__", callbacks=["console", "jsonl"])
gpu = Host("placeholder", name="gpu")
dataset = Storage("r2:replace-dataset-bucket", name="dataset")
artifacts = Storage("r2:replace-artifact-bucket", name="artifacts")

gpu.pick(
    gpu_name="H100",
    num_gpus=1,
    min_gpu_ram=80,
    auto_select=True,
    create_if_missing=True,
)
gpu.start()
gpu.wait_ready(timeout="30m")

recipe.storage_ensure_bucket(artifacts)
recipe.storage_wait_count(
    dataset,
    path="/train",
    min_count=1,
    timeout="30m",
    poll_interval="30s",
)

with gpu.tmux("train", cwd="/workspace/app", env={"PYTHONUNBUFFERED": "1"}) as tmux:
    tmux.install_uv()
    tmux.script(
        '''
        uv sync
        uv run python -m your_project.train --config configs/train.yaml
        ''',
        background=True,
        tee="/workspace/app/output/train.log",
        done_file="/workspace/app/output/success.txt",
    )
    tmux.file("/workspace/app/output/success.txt", timeout="12h")

with gpu.tmux("train") as tmux:
    tmux.download("/workspace/app/output", "./artifacts")

gpu.stop()
recipe.notify("remote training completed")
"""


_TEMPLATES = {
    "minimal": _MINIMAL_TEMPLATE,
    "remote-train": _REMOTE_TRAIN_TEMPLATE,
}


def list_template_names() -> list[str]:
    names = []
    for name in _TEMPLATES:
        if name not in names:
            names.append(name)
    return names


def get_recipe_template(template_name: str, recipe_name: str) -> str:
    key = str(template_name or "minimal").strip().lower() or "minimal"
    try:
        template = _TEMPLATES[key]
    except KeyError as exc:
        available = ", ".join(list_template_names())
        raise ValueError(f"Unknown template: {template_name}. Available: {available}") from exc
    return dedent(template).replace("__NAME__", recipe_name)


__all__ = ["get_recipe_template", "list_template_names"]

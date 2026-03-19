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


_TEMPLATES = {
    "minimal": _MINIMAL_TEMPLATE,
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

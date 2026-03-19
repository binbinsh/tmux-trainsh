"""Loader for Python recipe source files."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import hashlib
import sys
from pathlib import Path
from typing import List

from .base import RecipeSpec


def _module_name_for_path(path: Path) -> str:
    slug = path.name.replace("-", "_").replace(".", "_")
    digest = hashlib.sha1(path.as_posix().encode("utf-8")).hexdigest()[:12]
    return f"trainsh_user_recipe_{digest}_{slug}"


def load_python_recipe(path: str) -> RecipeSpec:
    """Load one recipe object from a Python recipe source file."""
    source = Path(path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"recipe file not found: {path}")

    module_name = _module_name_for_path(source)
    loader = importlib.machinery.SourceFileLoader(module_name, str(source))
    spec = importlib.util.spec_from_loader(module_name, loader, origin=str(source))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load recipe module from: {source}")

    module = importlib.util.module_from_spec(spec)
    loaded: List[RecipeSpec] = []
    try:
        sys.modules[spec.name] = module  # type: ignore[arg-type]
        spec.loader.exec_module(module)  # type: ignore[arg-type]
    finally:
        sys.modules.pop(spec.name, None)  # type: ignore[arg-type]

    explicit = getattr(module, "recipe", None)
    if isinstance(explicit, RecipeSpec):
        return explicit

    for item in vars(module).values():
        if isinstance(item, RecipeSpec):
            loaded.append(item)

    if len(loaded) == 1:
        return loaded[0]
    if loaded:
        raise RuntimeError(
            "multiple RecipeSpec objects found in recipe module; "
            "please expose only one as `recipe = ...`"
        )
    raise RuntimeError("no recipe defined in recipe source file")

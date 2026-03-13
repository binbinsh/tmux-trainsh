"""Lightweight authoring references for Python recipe files."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .base import RecipeSpecCore


class AliasRef(str):
    """String-like alias reference exposed by namespace registries."""

    def __new__(cls, name: str, *, kind: str):
        obj = str.__new__(cls, str(name).strip())
        obj.kind = kind
        return obj


class StepHandle(str):
    """String-compatible step id with light chain helpers."""

    def __new__(cls, step_id: str, *, recipe: "RecipeSpecCore"):
        value = str(step_id).strip()
        obj = str.__new__(cls, value)
        obj.id = value
        obj.recipe = recipe
        return obj

    def after(self, *dependencies: Any) -> "StepHandle":
        """Attach upstream dependencies to this step after creation."""
        self.recipe.link_step_dependencies(self.id, dependencies)
        return self

    def then(self, other: Any) -> Any:
        """Compact alias for chain-style dependency wiring."""
        return self.__rshift__(other)

    def __rshift__(self, other: Any) -> Any:
        if other is None:
            return None

        attach = getattr(other, "after", None)
        if callable(attach):
            return attach(self)

        step_id = getattr(other, "id", None)
        if isinstance(step_id, str) and step_id.strip():
            self.recipe.link_step_dependencies(step_id, [self])
            return other

        open_step_id = getattr(other, "open_step_id", None)
        if isinstance(open_step_id, str) and open_step_id.strip():
            self.recipe.link_step_dependencies(open_step_id, [self])
            return other

        text = str(other).strip()
        if text:
            self.recipe.link_step_dependencies(text, [self])
            return other
        raise TypeError(f"unsupported step chain target: {type(other)!r}")


def wrap_step_handle(recipe: "RecipeSpecCore", step_id: str) -> StepHandle:
    """Create a string-compatible handle for one registered step id."""
    return StepHandle(step_id, recipe=recipe)


__all__ = ["AliasRef", "StepHandle", "wrap_step_handle"]

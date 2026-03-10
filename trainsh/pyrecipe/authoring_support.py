"""Helpers for the flat Python recipe authoring surface."""

from __future__ import annotations

import inspect
import re
from typing import Any, Dict, Iterable, Optional, TYPE_CHECKING

from .models import PythonRecipeError

if TYPE_CHECKING:
    from .base import RecipeSpecCore
    from .session_steps import RecipeSessionRef


_STEP_OPTION_ALIASES = {
    "retry": "retries",
    "retries": "retries",
    "retry_delay": "retry_delay",
    "continue_on_failure": "continue_on_failure",
    "trigger": "trigger_rule",
    "trigger_rule": "trigger_rule",
    "pool": "pool",
    "priority": "priority",
    "execution_timeout": "execution_timeout",
    "backoff": "retry_exponential_backoff",
    "retry_exponential_backoff": "retry_exponential_backoff",
    "max_active": "max_active_tis_per_dagrun",
    "max_active_tis_per_dagrun": "max_active_tis_per_dagrun",
    "deferrable": "deferrable",
    "on_success": "on_success",
    "on_failure": "on_failure",
}

_EQ_CONDITION = re.compile(
    r"^\s*(?P<left>[A-Za-z_][A-Za-z0-9_]*)\s*==\s*(?P<right>.+?)\s*$"
)


def bind_recipe(recipe: "RecipeSpecCore", *, frame: Optional[Any] = None) -> "RecipeSpecCore":
    """Bind a recipe object into the caller module globals for loader discovery."""
    target = frame or inspect.currentframe()
    if target is None or target.f_back is None:
        raise PythonRecipeError("unable to bind recipe to caller context")
    caller = target.f_back
    if frame is None and caller.f_back is not None:
        caller = caller.f_back
    caller_globals = caller.f_globals
    caller_globals["__trainsh_recipe__"] = recipe
    return recipe


def current_recipe(*, frame: Optional[inspect.FrameInfo] = None) -> "RecipeSpecCore":
    """Resolve the current authoring recipe from the caller module globals."""
    target = frame or inspect.currentframe()
    if target is None:
        raise PythonRecipeError("unable to inspect current authoring context")
    scope = target.f_back
    while scope is not None:
        recipe = scope.f_globals.get("__trainsh_recipe__")
        if recipe is not None:
            return recipe
        scope = scope.f_back
    raise PythonRecipeError("call recipe(...) before defining recipe steps")


def normalize_after(after: Any) -> Optional[list[str]]:
    """Normalize a single dependency or collection into step ids."""
    if after is None:
        return None
    if isinstance(after, (list, tuple, set)):
        items = list(after)
    else:
        items = [after]

    deps: list[str] = []
    seen = set()
    for item in items:
        if item is None:
            continue
        dep = _dependency_id(item)
        if not dep or dep in seen:
            continue
        seen.add(dep)
        deps.append(dep)
    return deps or None


def split_step_call(kwargs: Optional[Dict[str, Any]] = None) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Split authoring kwargs into method kwargs vs runtime step plumbing."""
    params = dict(kwargs or {})
    after = params.pop("after", params.pop("depends_on", None))
    step_id = params.pop("id", None)

    step_options = dict(params.pop("step_options", {}) or {})
    for source, target in _STEP_OPTION_ALIASES.items():
        if source in params:
            step_options[target] = params.pop(source)

    call_kwargs: Dict[str, Any] = {}
    depends_on = normalize_after(after)
    if step_id is not None:
        call_kwargs["id"] = step_id
    if depends_on is not None:
        call_kwargs["depends_on"] = depends_on
    if step_options:
        call_kwargs["step_options"] = step_options
    return params, call_kwargs


def invoke_recipe_method(recipe: "RecipeSpecCore", method_name: str, *args: Any, **kwargs: Any) -> Any:
    """Call one RecipeSpec method using the flat authoring keywords."""
    params, call_kwargs = split_step_call(kwargs)
    method = getattr(recipe, method_name)
    accepted = inspect.signature(method).parameters
    for key, value in call_kwargs.items():
        if key in accepted:
            params[key] = value
    return method(*args, **params)


def normalize_condition(condition: str) -> str:
    """Translate a light-weight branch/check expression into runtime form."""
    text = str(condition or "").strip()
    if not text:
        raise PythonRecipeError("condition cannot be empty")
    if ":" in text:
        return text

    matched = _EQ_CONDITION.match(text)
    if not matched:
        return f"var:{text}"

    left = matched.group("left").strip()
    right = matched.group("right").strip()
    if right.startswith(("'", '"')) and right.endswith(("'", '"')) and len(right) >= 2:
        right = right[1:-1]
    return f"var:{left}=={right}"


def session_dependency(ref: Any) -> Optional[str]:
    """Resolve a session reference into the step id that opened it."""
    return _dependency_id(ref)


def _dependency_id(value: Any) -> str:
    if value is None:
        return ""
    open_step_id = getattr(value, "open_step_id", None)
    if isinstance(open_step_id, str) and open_step_id.strip():
        return open_step_id.strip()
    step_id = getattr(value, "id", None)
    if isinstance(step_id, str) and step_id.strip():
        return step_id.strip()
    return str(value).strip()


__all__ = [
    "bind_recipe",
    "current_recipe",
    "invoke_recipe_method",
    "normalize_after",
    "normalize_condition",
    "session_dependency",
    "split_step_call",
]

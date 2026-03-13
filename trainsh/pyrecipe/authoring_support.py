"""Helpers shared by the explicit Python recipe authoring surface."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .models import PythonRecipeError


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
    "normalize_after",
    "normalize_condition",
    "split_step_call",
]

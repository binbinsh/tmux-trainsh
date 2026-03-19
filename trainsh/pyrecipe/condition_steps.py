"""Conditional provider helpers for Python recipes."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from .authoring_support import normalize_condition


class RecipeProviderConditionMixin:
    """Condition helpers that compile to util provider operations."""

    def wait_condition(
        self,
        condition: str,
        *,
        host: Optional[str] = None,
        timeout: Any = "5m",
        poll_interval: Any = "5s",
        capture: bool = False,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Wait until condition expression becomes true."""
        params: Dict[str, Any] = {
            "condition": condition,
            "timeout": timeout,
            "poll_interval": poll_interval,
            "capture": self._normalize_bool(capture, default=False),
        }
        if host is not None:
            params["host"] = host
        return self.provider(
            "util",
            "wait_condition",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def latest_only(
        self,
        *,
        enabled: bool = True,
        message: str = "Skipped by latest_only",
        runtime_state: Optional[str] = None,
        fail_if_unknown: bool = False,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Keep only the latest run for this recipe.

        Uses runtime JSONL state when available. If state is unavailable:
        - with ``fail_if_unknown=True`` it fails
        - otherwise it passes and continues.
        """
        params: Dict[str, Any] = {
            "enabled": bool(enabled),
            "message": message,
            "runtime_state": runtime_state,
            "fail_if_unknown": bool(fail_if_unknown),
        }
        return self.provider(
            "util",
            "latest_only",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def branch(
        self,
        condition: str,
        *,
        true_value: str = "true",
        false_value: str = "false",
        variable: str = "branch",
        host: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Evaluate a condition and write a branch variable."""
        params: Dict[str, Any] = {
            "condition": condition,
            "true_value": str(true_value),
            "false_value": str(false_value),
            "variable": variable,
        }
        if host is not None:
            params["host"] = host
        return self.provider(
            "util",
            "branch",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def choose(
        self,
        variable: str,
        *,
        when: Any,
        then: Any = "true",
        else_: Any = "false",
        host: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Convenience alias for branch-style variable selection."""
        if isinstance(when, bool):
            return self.provider(
                "util",
                "set_var",
                params={
                    "name": variable,
                    "value": str(then if when else else_),
                },
                id=id,
                depends_on=depends_on,
                step_options=step_options,
            )
        return self.branch(
            normalize_condition(when),
            true_value=str(then),
            false_value=str(else_),
            variable=variable,
            host=host,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def short_circuit(
        self,
        condition: str,
        *,
        host: Optional[str] = None,
        message: str = "condition not met",
        invert: bool = False,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Fail step when condition does not match (Airflow short-circuit style)."""
        params: Dict[str, Any] = {
            "condition": condition,
            "message": message,
            "invert": bool(invert),
        }
        if host is not None:
            params["host"] = host
        return self.provider(
            "util",
            "short_circuit",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def skip_if(
        self,
        condition: str,
        *,
        host: Optional[str] = None,
        message: str = "condition not met",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Alias for a non-inverted short-circuit check."""
        return self.short_circuit(
            condition,
            host=host,
            message=message,
            invert=False,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def skip_if_not(
        self,
        condition: str,
        *,
        host: Optional[str] = None,
        message: str = "condition not met",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Alias for a negated short-circuit check."""
        return self.short_circuit(
            condition,
            host=host,
            message=message,
            invert=True,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

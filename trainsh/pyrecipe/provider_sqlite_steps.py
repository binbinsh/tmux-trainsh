"""SQLite provider helpers for Python recipes."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


class RecipeProviderSQLiteMixin:
    """Provider helpers that operate on a local SQLite database."""

    def sqlite_query(
        self,
        sql: str,
        *,
        database: Optional[str] = None,
        params: Optional[Iterable[Any] | Dict[str, Any]] = None,
        output_var: Optional[str] = None,
        mode: str = "all",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Run a SQLite SELECT statement."""
        params_payload = {
            "sql": sql,
            "mode": mode,
        }
        if database is not None:
            params_payload["database"] = database
        if params is not None:
            params_payload["params"] = params
        if output_var is not None:
            params_payload["output_var"] = str(output_var)
        return self.provider(
            "sqlite",
            "query",
            params=params_payload,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def sqlite_exec(
        self,
        sql: str,
        *,
        database: Optional[str] = None,
        params: Optional[Iterable[Any] | Dict[str, Any]] = None,
        output_var: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Execute a SQLite write statement (INSERT/UPDATE/DELETE)."""
        params_payload = {
            "sql": sql,
        }
        if database is not None:
            params_payload["database"] = database
        if params is not None:
            params_payload["params"] = params
        if output_var is not None:
            params_payload["output_var"] = str(output_var)
        return self.provider(
            "sqlite",
            "exec",
            params=params_payload,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def sqlite_script(
        self,
        script: str,
        *,
        database: Optional[str] = None,
        output_var: Optional[str] = "sqlite_script_result",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Run a multi-statement SQLite script."""
        params_payload = {"script": script}
        if database is not None:
            params_payload["database"] = database
        if output_var is not None:
            params_payload["output_var"] = str(output_var)
        return self.provider(
            "sqlite",
            "script",
            params=params_payload,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

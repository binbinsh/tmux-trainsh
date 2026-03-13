"""Transfer-specific provider helpers for Python recipes."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


class RecipeProviderTransferMixin:
    """Helpers for transfer-engine backed steps."""

    def transfer(
        self,
        source: str,
        destination: str,
        *,
        operation: str = "copy",
        delete: bool = False,
        exclude: Optional[Iterable[str]] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Transfer files/folders/objects using the configured transfer engine."""
        return self.provider(
            "transfer",
            operation,
            params={
                "source": source,
                "destination": destination,
                "delete": self._normalize_bool(delete),
                "exclude": self._normalize_list(exclude),
                "operation": str(operation).strip().lower(),
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

"""Small bound namespaces for the explicit Python recipe API."""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from .models import Host, VastHost

if TYPE_CHECKING:
    from .base import RecipeSpecCore


class VastNamespace:
    """Recipe-bound Vast helpers."""

    def __init__(self, recipe: "RecipeSpecCore"):
        self._recipe = recipe

    def _instance_id(self, target: Any) -> Optional[str]:
        if target is None:
            return None
        if isinstance(target, VastHost):
            return target.instance_id
        if isinstance(target, Host):
            spec = target.spec.strip()
            if spec.startswith("vast:"):
                return spec.split(":", 1)[1]
        return str(target).strip()

    def start(self, target: Any = None, **kwargs: Any) -> str:
        return self._recipe.vast_start(self._instance_id(target), **kwargs)

    def stop(self, target: Any = None, **kwargs: Any) -> str:
        return self._recipe.vast_stop(self._instance_id(target), **kwargs)

    def wait(self, target: Any = None, **kwargs: Any) -> str:
        return self._recipe.vast_wait(self._instance_id(target), **kwargs)

    def wait_ready(self, target: Any = None, **kwargs: Any) -> str:
        return self.wait(target, **kwargs)

    def pick(self, **kwargs: Any) -> str:
        payload = dict(kwargs)
        if "host" in payload:
            payload["host"] = self._recipe.resolve_host(payload["host"])
        return self._recipe.vast_pick(**payload)

    def cost(self, instance_id: Optional[str] = None, **kwargs: Any) -> str:
        return self._recipe.vast_cost(instance_id, **kwargs)


class NotifyNamespace:
    """Recipe-bound notification helpers."""

    def __init__(self, recipe: "RecipeSpecCore"):
        self._recipe = recipe

    def __call__(self, message: str, **kwargs: Any) -> str:
        return self._recipe.notice(message, **kwargs)

    def notice(self, message: str, **kwargs: Any) -> str:
        return self._recipe.notice(message, **kwargs)

    def email(self, message: str, **kwargs: Any) -> str:
        return self._recipe.email_send(message, **kwargs)

    def slack(self, message: str, **kwargs: Any) -> str:
        return self._recipe.slack(message, **kwargs)

    def telegram(self, message: str, **kwargs: Any) -> str:
        return self._recipe.telegram(message, **kwargs)

    def discord(self, message: str, **kwargs: Any) -> str:
        return self._recipe.discord(message, **kwargs)

    def webhook(self, message: str, **kwargs: Any) -> str:
        return self._recipe.webhook(message, **kwargs)


__all__ = ["NotifyNamespace", "VastNamespace"]

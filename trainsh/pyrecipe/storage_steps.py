"""Storage related provider helpers."""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, Optional

from .models import StoragePath


class RecipeStorageMixin:
    """Storage operations as provider-style recipe steps."""

    def _storage_target(
        self,
        storage: Any,
        *,
        path: Any = None,
        default_path: str = "",
    ) -> tuple[str, str]:
        if isinstance(storage, StoragePath):
            if path is None or os.fspath(path) == default_path:
                return self.resolve_storage(storage.storage), storage.path
            return self.resolve_storage(storage.storage), os.fspath(path)
        return self.resolve_storage(storage), default_path if path is None else os.fspath(path)

    def storage_upload(
        self,
        storage: Any,
        *,
        source: Any,
        destination: str = "/",
        operation: str = "copy",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Upload local file/directory to storage path."""
        cleaned_storage, target_path = self._storage_target(storage, path=destination, default_path="/")
        return self.provider(
            "storage",
            "upload",
            params={
                "storage": cleaned_storage,
                "source": os.fspath(source),
                "destination": target_path,
                "operation": str(operation or "copy").strip().lower(),
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_download(
        self,
        storage: Any,
        *,
        source: Any,
        destination: Any,
        operation: str = "copy",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Download storage object to local path."""
        cleaned_storage, source_path = self._storage_target(storage, path=source)
        return self.provider(
            "storage",
            "download",
            params={
                "storage": cleaned_storage,
                "source": source_path,
                "destination": os.fspath(destination),
                "operation": str(operation or "copy").strip().lower(),
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_exists(
        self,
        storage: Any,
        *,
        path: Any = "",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Check whether storage path exists."""
        cleaned_storage, target_path = self._storage_target(storage, path=path, default_path="")
        return self.provider(
            "storage",
            "exists",
            params={"storage": cleaned_storage, "path": target_path},
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_test(
        self,
        storage: Any,
        *,
        path: Any = "",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Alias for existence check in control/validation flows."""
        return self.storage_exists(
            storage,
            path=path,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_wait(
        self,
        storage: Any,
        *,
        path: Any = "/",
        exists: bool = True,
        timeout: Any = "5m",
        poll_interval: Any = "5s",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Wait for storage path existence (or non-existence)."""
        cleaned_storage, target_path = self._storage_target(storage, path=path, default_path="/")
        params: Dict[str, Any] = {
            "storage": cleaned_storage,
            "path": target_path,
            "exists": self._normalize_bool(exists, default=True),
            "timeout": timeout,
            "poll_interval": poll_interval,
        }
        return self.provider(
            "storage",
            "wait",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_info(
        self,
        storage: Any,
        *,
        path: Any = "",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Read storage path metadata."""
        cleaned_storage, target_path = self._storage_target(storage, path=path, default_path="")
        return self.provider(
            "storage",
            "info",
            params={"storage": cleaned_storage, "path": target_path},
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_read_text(
        self,
        storage: Any,
        *,
        path: Any,
        max_chars: int = 8192,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Read text from storage path."""
        cleaned_storage, target_path = self._storage_target(storage, path=path)
        return self.provider(
            "storage",
            "read_text",
            params={
                "storage": cleaned_storage,
                "path": target_path,
                "max_chars": max_chars,
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_list(
        self,
        storage: Any,
        *,
        path: Any = "",
        recursive: bool = False,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """List storage path entries."""
        cleaned_storage, target_path = self._storage_target(storage, path=path, default_path="")
        return self.provider(
            "storage",
            "list",
            params={"storage": cleaned_storage, "path": target_path, "recursive": recursive},
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_mkdir(
        self,
        storage: Any,
        *,
        path: Any,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create storage directory."""
        cleaned_storage, target_path = self._storage_target(storage, path=path)
        return self.provider(
            "storage",
            "mkdir",
            params={"storage": cleaned_storage, "path": target_path},
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_delete(
        self,
        storage: Any,
        *,
        path: Any,
        recursive: bool = False,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Delete storage entry."""
        cleaned_storage, target_path = self._storage_target(storage, path=path)
        return self.provider(
            "storage",
            "delete",
            params={"storage": cleaned_storage, "path": target_path, "recursive": recursive},
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_rename(
        self,
        storage: Any,
        *,
        source: Any,
        destination: Any,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Rename a storage object."""
        cleaned_storage = self.resolve_storage(storage)
        return self.provider(
            "storage",
            "rename",
            params={
                "storage": cleaned_storage,
                "source": os.fspath(source),
                "destination": os.fspath(destination),
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_copy(
        self,
        storage: Any,
        *,
        source: Any,
        destination: Any,
        exclude: Optional[Iterable[str]] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Copy within one storage endpoint."""
        cleaned_storage = self.resolve_storage(storage)
        return self.provider(
            "storage",
            "copy",
            params={
                "source": f"@{cleaned_storage}:{os.fspath(source)}",
                "destination": f"@{cleaned_storage}:{os.fspath(destination)}",
                "exclude": self._normalize_list(exclude),
                "operation": "copy",
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_move(
        self,
        storage: Any,
        *,
        source: Any,
        destination: Any,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Move within one storage endpoint."""
        cleaned_storage = self.resolve_storage(storage)
        return self.provider(
            "storage",
            "move",
            params={
                "source": f"@{cleaned_storage}:{os.fspath(source)}",
                "destination": f"@{cleaned_storage}:{os.fspath(destination)}",
                "operation": "move",
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_sync(
        self,
        storage: Any,
        *,
        source: Any,
        destination: Any,
        delete: bool = False,
        exclude: Optional[Iterable[str]] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Synchronize directories/files inside one storage endpoint."""
        cleaned_storage = self.resolve_storage(storage)
        return self.provider(
            "storage",
            "sync",
            params={
                "source": f"@{cleaned_storage}:{os.fspath(source)}",
                "destination": f"@{cleaned_storage}:{os.fspath(destination)}",
                "delete": self._normalize_bool(delete),
                "exclude": self._normalize_list(exclude),
                "operation": "sync",
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_remove(
        self,
        storage: Any,
        *,
        path: Any,
        recursive: bool = False,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Alias for recursive-capable storage deletion."""
        return self.storage_delete(
            storage,
            path=path,
            recursive=recursive,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

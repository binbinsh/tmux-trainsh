"""Storage related provider helpers."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


class RecipeStorageMixin:
    """Storage operations as provider-style recipe steps."""

    def storage_upload(
        self,
        storage: str,
        *,
        source: str,
        destination: str = "/",
        operation: str = "copy",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Upload local file/directory to storage path."""
        cleaned_storage = self._clean_session(storage) if isinstance(storage, str) else str(storage)
        return self.provider(
            "storage",
            "upload",
            params={
                "storage": cleaned_storage,
                "source": source,
                "destination": destination,
                "operation": str(operation or "copy").strip().lower(),
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_download(
        self,
        storage: str,
        *,
        source: str,
        destination: str,
        operation: str = "copy",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Download storage object to local path."""
        cleaned_storage = self._clean_session(storage) if isinstance(storage, str) else str(storage)
        return self.provider(
            "storage",
            "download",
            params={
                "storage": cleaned_storage,
                "source": source,
                "destination": destination,
                "operation": str(operation or "copy").strip().lower(),
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_exists(
        self,
        storage: str,
        *,
        path: str = "",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Check whether storage path exists."""
        cleaned_storage = self._clean_session(storage) if isinstance(storage, str) else str(storage)
        return self.provider(
            "storage",
            "exists",
            params={"storage": cleaned_storage, "path": path},
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_test(
        self,
        storage: str,
        *,
        path: str = "",
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
        storage: str,
        *,
        path: str = "/",
        exists: bool = True,
        timeout: Any = "5m",
        poll_interval: Any = "5s",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Wait for storage path existence (or non-existence)."""
        cleaned_storage = self._clean_session(storage) if isinstance(storage, str) else str(storage)
        params: Dict[str, Any] = {
            "storage": cleaned_storage,
            "path": path,
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
        storage: str,
        *,
        path: str = "",
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Read storage path metadata."""
        cleaned_storage = self._clean_session(storage) if isinstance(storage, str) else str(storage)
        return self.provider(
            "storage",
            "info",
            params={"storage": cleaned_storage, "path": path},
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_read_text(
        self,
        storage: str,
        *,
        path: str,
        max_chars: int = 8192,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Read text from storage path."""
        cleaned_storage = self._clean_session(storage) if isinstance(storage, str) else str(storage)
        return self.provider(
            "storage",
            "read_text",
            params={
                "storage": cleaned_storage,
                "path": path,
                "max_chars": max_chars,
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_list(
        self,
        storage: str,
        *,
        path: str = "",
        recursive: bool = False,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """List storage path entries."""
        cleaned_storage = self._clean_session(storage) if isinstance(storage, str) else str(storage)
        return self.provider(
            "storage",
            "list",
            params={"storage": cleaned_storage, "path": path, "recursive": recursive},
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_mkdir(
        self,
        storage: str,
        *,
        path: str,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create storage directory."""
        cleaned_storage = self._clean_session(storage) if isinstance(storage, str) else str(storage)
        return self.provider(
            "storage",
            "mkdir",
            params={"storage": cleaned_storage, "path": path},
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_delete(
        self,
        storage: str,
        *,
        path: str,
        recursive: bool = False,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Delete storage entry."""
        cleaned_storage = self._clean_session(storage) if isinstance(storage, str) else str(storage)
        return self.provider(
            "storage",
            "delete",
            params={"storage": cleaned_storage, "path": path, "recursive": recursive},
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_rename(
        self,
        storage: str,
        *,
        source: str,
        destination: str,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Rename a storage object."""
        cleaned_storage = self._clean_session(storage) if isinstance(storage, str) else str(storage)
        return self.provider(
            "storage",
            "rename",
            params={
                "storage": cleaned_storage,
                "source": source,
                "destination": destination,
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_copy(
        self,
        storage: str,
        *,
        source: str,
        destination: str,
        exclude: Optional[Iterable[str]] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Copy within one storage endpoint."""
        cleaned_storage = self._clean_session(storage) if isinstance(storage, str) else str(storage)
        return self.provider(
            "storage",
            "copy",
            params={
                "source": f"@{cleaned_storage}:{source}",
                "destination": f"@{cleaned_storage}:{destination}",
                "exclude": self._normalize_list(exclude),
                "operation": "copy",
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_move(
        self,
        storage: str,
        *,
        source: str,
        destination: str,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Move within one storage endpoint."""
        cleaned_storage = self._clean_session(storage) if isinstance(storage, str) else str(storage)
        return self.provider(
            "storage",
            "move",
            params={
                "source": f"@{cleaned_storage}:{source}",
                "destination": f"@{cleaned_storage}:{destination}",
                "operation": "move",
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def storage_sync(
        self,
        storage: str,
        *,
        source: str,
        destination: str,
        delete: bool = False,
        exclude: Optional[Iterable[str]] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Synchronize directories/files inside one storage endpoint."""
        cleaned_storage = self._clean_session(storage) if isinstance(storage, str) else str(storage)
        return self.provider(
            "storage",
            "sync",
            params={
                "source": f"@{cleaned_storage}:{source}",
                "destination": f"@{cleaned_storage}:{destination}",
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
        storage: str,
        *,
        path: str,
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

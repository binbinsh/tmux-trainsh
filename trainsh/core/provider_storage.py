"""Storage-backed provider operations."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from typing import Any, Dict

from .models import StorageType


class ExecutorProviderStorageMixin:
    def _storage_entry_count(
        self,
        storage,
        *,
        path: str,
        recursive: bool,
        include_dirs: bool,
    ) -> int:
        """Count entries under one storage prefix."""
        if storage.type == StorageType.LOCAL:
            target = self._storage_local_path(storage, path)
            if not os.path.exists(target):
                return 0
            if os.path.isfile(target):
                return 1
            if not os.path.isdir(target):
                return 0

            count = 0
            if recursive:
                for _root, dirs, files in os.walk(target):
                    count += len(files)
                    if include_dirs:
                        count += len(dirs)
                return count

            for name in os.listdir(target):
                child = os.path.join(target, name)
                if os.path.isdir(child):
                    if include_dirs:
                        count += 1
                    continue
                count += 1
            return count

        if storage.type == StorageType.HF:
            args = ["list", self._storage_hf_uri(storage, path), "-q"]
            if recursive:
                args.append("-R")
            ok, output = self._exec_storage_hf(storage, args)
        else:
            args = ["lsf"]
            if recursive:
                args.append("-R")
            args.append(self._storage_rclone_path(storage, path))
            ok, output = self._exec_storage_rclone(storage, args)
        if not ok:
            lowered = str(output or "").lower()
            if any(token in lowered for token in ("not found", "no such file", "directory not found", "404")):
                return 0
            raise RuntimeError(output or "storage count failed")

        count = 0
        for raw_line in str(output or "").splitlines():
            entry = raw_line.strip()
            if not entry:
                continue
            if entry.endswith("/"):
                if include_dirs:
                    count += 1
                continue
            count += 1
        return count

    def _parse_storage_count_bound(self, params: Dict[str, Any], key: str) -> tuple[int | None, str | None]:
        """Parse one optional integer storage-count bound."""
        if key not in params or params.get(key) is None or str(params.get(key)).strip() == "":
            return None, None
        try:
            return int(str(params.get(key)).strip()), None
        except Exception:
            return None, f"Provider storage.wait_count {key} must be integer"

    def _format_storage_count_target(
        self,
        *,
        min_count: int | None,
        max_count: int | None,
        exact_count: int | None,
    ) -> str:
        """Render a user-facing storage-count target description."""
        if exact_count is not None:
            return f"count == {exact_count}"
        parts = []
        if min_count is not None:
            parts.append(f"count >= {min_count}")
        if max_count is not None:
            parts.append(f"count <= {max_count}")
        return " and ".join(parts) or "count target"

    def _exec_provider_storage_test(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Test whether a storage path exists."""
        if not isinstance(params, dict):
            return False, "Provider storage.test params must be an object"

        storage = self._resolve_storage(params.get("storage"))
        if storage is None:
            return False, "Provider storage.test requires storage id"
        path = str(params.get("path", "")).strip()

        if storage.type == StorageType.LOCAL:
            target = self._storage_local_path(storage, path)
            return (
                True,
                f"Storage path exists: {target}",
            ) if os.path.exists(target) else (False, f"Storage path not found: {target}")

        if storage.type == StorageType.HF:
            return self._exec_storage_hf(storage, ["list", self._storage_hf_uri(storage, path), "-q"])

        return self._exec_storage_rclone(storage, ["ls", self._storage_rclone_path(storage, path)])

    def _exec_provider_storage_exists(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Alias storage.exists."""
        return self._exec_provider_storage_test(params)

    def _exec_provider_storage_wait(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Wait for storage path existence or non-existence."""
        if not isinstance(params, dict):
            return False, "Provider storage.wait params must be an object"

        storage_name = str(params.get("storage") or params.get("storage_id") or "").strip()
        if not storage_name:
            return False, "Provider storage.wait requires storage id"
        storage_name = storage_name[1:] if storage_name.startswith("@") else storage_name

        path = self._interpolate(str(params.get("path", params.get("destination", "")))).strip()
        if not path:
            return False, "Provider storage.wait requires path"

        should_exist = self._coerce_bool(params.get("exists", True), default=True)
        timeout = self._normalize_provider_timeout(
            params.get("timeout", params.get("timeout_secs", 300)),
            allow_zero=True,
        )
        if timeout is None:
            return False, f"Invalid timeout value: {params.get('timeout')!r}"
        poll_interval = self._normalize_provider_timeout(
            params.get("poll_interval", params.get("interval", params.get("poll_interval_secs", 5))),
            allow_zero=True,
        )
        if poll_interval is None or poll_interval <= 0:
            poll_interval = 5

        deadline = time.time() + timeout if timeout else 0
        while True:
            ok, _ = self._exec_provider_storage_exists(
                {"storage": storage_name, "path": path}
            )
            if should_exist and ok:
                return True, f"Storage path exists: {storage_name}:{path}"
            if not should_exist and not ok:
                return True, f"Storage path not found as expected: {storage_name}:{path}"

            if timeout and time.time() >= deadline:
                return False, f"Timeout waiting storage path: {storage_name}:{path}"

            time.sleep(poll_interval)

    def _exec_provider_storage_count(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Count entries under one storage path."""
        if not isinstance(params, dict):
            return False, "Provider storage.count params must be an object"

        storage = self._resolve_storage(params.get("storage"))
        if storage is None:
            return False, "Provider storage.count requires storage id"

        path = self._interpolate(str(params.get("path", params.get("source", "/")))).strip() or "/"
        recursive = self._coerce_bool(params.get("recursive", True), default=True)
        include_dirs = self._coerce_bool(params.get("include_dirs", False), default=False)

        try:
            count = self._storage_entry_count(
                storage,
                path=path,
                recursive=recursive,
                include_dirs=include_dirs,
            )
        except Exception as exc:
            return False, str(exc)

        capture_var = str(params.get("capture_var", "")).strip()
        if capture_var:
            self.ctx.variables[capture_var] = str(count)
        return True, str(count)

    def _exec_provider_storage_wait_count(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Wait until a storage entry count satisfies the requested threshold."""
        if not isinstance(params, dict):
            return False, "Provider storage.wait_count params must be an object"

        storage_name = str(params.get("storage") or params.get("storage_id") or "").strip()
        if not storage_name:
            return False, "Provider storage.wait_count requires storage id"
        storage_name = storage_name[1:] if storage_name.startswith("@") else storage_name
        storage = self._resolve_storage(storage_name)
        if storage is None:
            return False, "Provider storage.wait_count requires storage id"

        path = self._interpolate(str(params.get("path", params.get("source", "/")))).strip() or "/"
        recursive = self._coerce_bool(params.get("recursive", True), default=True)
        include_dirs = self._coerce_bool(params.get("include_dirs", False), default=False)

        exact_count, error = self._parse_storage_count_bound(params, "exact_count")
        if error:
            return False, error
        min_count, error = self._parse_storage_count_bound(params, "min_count")
        if error:
            return False, error
        max_count, error = self._parse_storage_count_bound(params, "max_count")
        if error:
            return False, error
        if exact_count is None and min_count is None and max_count is None:
            return False, "Provider storage.wait_count requires exact_count, min_count, or max_count"

        timeout = self._normalize_provider_timeout(
            params.get("timeout", params.get("timeout_secs", 300)),
            allow_zero=True,
        )
        if timeout is None:
            return False, f"Invalid timeout value: {params.get('timeout')!r}"
        poll_interval = self._normalize_provider_timeout(
            params.get("poll_interval", params.get("interval", params.get("poll_interval_secs", 5))),
            allow_zero=True,
        )
        if poll_interval is None or poll_interval <= 0:
            poll_interval = 5

        capture_var = str(params.get("capture_var", "")).strip()
        target_text = self._format_storage_count_target(
            min_count=min_count,
            max_count=max_count,
            exact_count=exact_count,
        )
        deadline = time.time() + timeout if timeout else 0
        last_count = 0
        while True:
            try:
                last_count = self._storage_entry_count(
                    storage,
                    path=path,
                    recursive=recursive,
                    include_dirs=include_dirs,
                )
            except Exception as exc:
                return False, str(exc)

            if capture_var:
                self.ctx.variables[capture_var] = str(last_count)

            matches = True
            if exact_count is not None:
                matches = last_count == exact_count
            else:
                if min_count is not None and last_count < min_count:
                    matches = False
                if max_count is not None and last_count > max_count:
                    matches = False

            if matches:
                return True, f"Storage count matched: {storage_name}:{path} -> {last_count} ({target_text})"

            if timeout and time.time() >= deadline:
                return False, (
                    f"Timeout waiting for storage count: {storage_name}:{path} -> {last_count} ({target_text})"
                )

            time.sleep(poll_interval)

    def _exec_provider_storage_ensure_bucket(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Ensure a bucket/container exists for supported cloud storage backends."""
        if not isinstance(params, dict):
            return False, "Provider storage.ensure_bucket params must be an object"

        storage = self._resolve_storage(params.get("storage"))
        if storage is None:
            return False, "Provider storage.ensure_bucket requires storage id"
        if storage.type not in {StorageType.HF, StorageType.R2, StorageType.S3, StorageType.B2, StorageType.GCS}:
            return False, "Provider storage.ensure_bucket requires hf, r2, s3, b2, or gcs storage"

        bucket = str(storage.config.get("bucket", "")).strip().strip("/")
        if not bucket:
            return False, "Provider storage.ensure_bucket requires storage bucket configuration"

        if storage.type == StorageType.HF:
            ok, message = self._exec_storage_hf(storage, ["create", bucket, "--exist-ok"])
            if not ok:
                return False, message
            return True, message or f"Bucket ready: {bucket}"

        ok, message = self._exec_storage_rclone(storage, ["mkdir", self._storage_rclone_path(storage, "")])
        if not ok:
            return False, message
        return True, message or f"Bucket ready: {bucket}"

    def _exec_provider_storage_info(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Show storage object metadata."""
        if not isinstance(params, dict):
            return False, "Provider storage.info params must be an object"

        storage = self._resolve_storage(params.get("storage"))
        if storage is None:
            return False, "Provider storage.info requires storage id"
        path = str(params.get("path", "")).strip()

        if storage.type == StorageType.LOCAL:
            target = self._storage_local_path(storage, path)
            if not os.path.exists(target):
                return False, f"Storage path not found: {target}"
            try:
                stat = os.stat(target)
                info = {
                    "path": target,
                    "size": int(stat.st_size),
                    "is_dir": os.path.isdir(target),
                    "mtime": int(stat.st_mtime),
                    "mode": oct(stat.st_mode & 0o777),
                }
                return True, json.dumps(info, ensure_ascii=False)
            except Exception as exc:
                return False, str(exc)

        if storage.type == StorageType.HF:
            if not path:
                bucket = str(storage.config.get("bucket", "")).strip().strip("/")
                return self._exec_storage_hf(storage, ["info", bucket])
            return self._exec_storage_hf(storage, ["list", self._storage_hf_uri(storage, path), "--format", "json"])

        return self._exec_storage_rclone(storage, ["lsjson", self._storage_rclone_path(storage, path)])

    def _exec_provider_storage_read_text(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Read text content from storage."""
        if not isinstance(params, dict):
            return False, "Provider storage.read_text params must be an object"

        storage = self._resolve_storage(params.get("storage"))
        if storage is None:
            return False, "Provider storage.read_text requires storage id"
        path = str(params.get("path", "")).strip()
        if not path:
            return False, "Provider storage.read_text requires non-empty path"
        max_chars = self._coerce_float(params.get("max_chars", params.get("max_bytes", 8192)))
        if max_chars <= 0:
            max_chars = 8192
        max_chars = int(max_chars)

        if storage.type == StorageType.LOCAL:
            target = self._storage_local_path(storage, path)
            if not os.path.isfile(target):
                return False, f"Storage file not found: {target}"
            try:
                with open(target, "r", encoding="utf-8", errors="replace") as f:
                    return True, f.read(max_chars)
            except Exception as exc:
                return False, str(exc)

        if storage.type == StorageType.HF:
            ok, output = self._exec_storage_hf(storage, ["cp", self._storage_hf_uri(storage, path), "-"])
        else:
            ok, output = self._exec_storage_rclone(storage, ["cat", self._storage_rclone_path(storage, path)])
        if not ok:
            return False, output
        return True, output[:max_chars]

    def _exec_provider_storage_list(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """List storage path entries."""
        if not isinstance(params, dict):
            return False, "Provider storage.list params must be an object"

        storage = self._resolve_storage(params.get("storage"))
        if storage is None:
            return False, "Provider storage.list requires storage id"
        path = str(params.get("path", "")).strip()
        recursive = self._coerce_bool(params.get("recursive", False), default=False)

        if storage.type == StorageType.LOCAL:
            target = self._storage_local_path(storage, path)
            if not os.path.exists(target):
                return False, f"Storage path not found: {target}"
            if not os.path.isdir(target):
                return False, f"Storage path is not a directory: {target}"

            if recursive:
                output_lines = []
                for root, dirs, files in os.walk(target):
                    rel = os.path.relpath(root, target)
                    for name in sorted(dirs + files):
                        output_lines.append(os.path.join(rel, name) if rel != "." else name)
                return True, "\n".join(output_lines)

            return True, "\n".join(sorted(os.listdir(target)))

        if storage.type == StorageType.HF:
            args = ["list", self._storage_hf_uri(storage, path), "-q"]
            if recursive:
                args.append("-R")
            return self._exec_storage_hf(storage, args)

        args = ["lsf"]
        if recursive:
            args.append("-R")
        args.append(self._storage_rclone_path(storage, path))
        return self._exec_storage_rclone(storage, args)

    def _exec_provider_storage_mkdir(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Create storage directory."""
        if not isinstance(params, dict):
            return False, "Provider storage.mkdir params must be an object"

        storage = self._resolve_storage(params.get("storage"))
        if storage is None:
            return False, "Provider storage.mkdir requires storage id"
        path = str(params.get("path", "")).strip()
        if not path:
            return False, "Provider storage.mkdir requires non-empty path"

        if storage.type == StorageType.LOCAL:
            target = self._storage_local_path(storage, path)
            try:
                os.makedirs(target, exist_ok=True)
                return True, f"Directory created: {target}"
            except Exception as exc:
                return False, str(exc)

        if storage.type == StorageType.HF:
            return True, (
                "HF buckets use virtual directories. "
                "Upload a file under this prefix to materialize it."
            )

        return self._exec_storage_rclone(storage, ["mkdir", self._storage_rclone_path(storage, path)])

    def _exec_provider_storage_delete(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Delete storage object."""
        if not isinstance(params, dict):
            return False, "Provider storage.delete params must be an object"

        storage = self._resolve_storage(params.get("storage"))
        if storage is None:
            return False, "Provider storage.delete requires storage id"
        path = str(params.get("path", "")).strip()
        if not path:
            return False, "Provider storage.delete requires non-empty path"

        recursive = self._coerce_bool(params.get("recursive", False), default=False)

        if storage.type == StorageType.LOCAL:
            target = self._storage_local_path(storage, path)
            if not os.path.exists(target):
                return False, f"Storage path not found: {target}"
            try:
                if os.path.isdir(target):
                    if not recursive:
                        return False, f"Storage path is directory: {target} (set recursive=True to remove)"
                    shutil.rmtree(target)
                    return True, f"Directory deleted: {target}"
                os.remove(target)
                return True, f"File deleted: {target}"
            except Exception as exc:
                return False, str(exc)

        if storage.type == StorageType.HF:
            args = ["rm", self._storage_hf_uri(storage, path)]
            if recursive:
                args.append("--recursive")
            return self._exec_storage_hf(storage, args)

        op = "purge" if recursive else "delete"
        return self._exec_storage_rclone(storage, [op, self._storage_rclone_path(storage, path)])

    def _exec_provider_storage_rename(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Rename within storage."""
        if not isinstance(params, dict):
            return False, "Provider storage.rename params must be an object"

        storage = self._resolve_storage(params.get("storage"))
        if storage is None:
            return False, "Provider storage.rename requires storage id"
        source = str(params.get("source", "")).strip()
        destination = str(params.get("destination", "")).strip()
        if not source or not destination:
            return False, "Provider storage.rename requires source and destination"

        if storage.type == StorageType.LOCAL:
            source_path = self._storage_local_path(storage, source)
            destination_path = self._storage_local_path(storage, destination)
            try:
                os.rename(source_path, destination_path)
                return True, f"Renamed {source_path} -> {destination_path}"
            except Exception as exc:
                return False, str(exc)

        if storage.type == StorageType.HF:
            storage_name = storage.name or storage.id
            with tempfile.TemporaryDirectory(prefix="trainsh-hf-rename-") as tmpdir:
                stage_path = os.path.join(tmpdir, "payload")
                ok, message = self._exec_provider_transfer(
                    {
                        "source": f"@{storage_name}:{source}",
                        "destination": stage_path,
                        "operation": "copy",
                    }
                )
                if not ok:
                    return False, message
                ok, message = self._exec_provider_transfer(
                    {
                        "source": stage_path,
                        "destination": f"@{storage_name}:{destination}",
                        "operation": "copy",
                    }
                )
                if not ok:
                    return False, message
                ok, message = self._exec_provider_storage_delete({"storage": storage_name, "path": source})
                if ok:
                    return True, message
                return self._exec_provider_storage_delete({"storage": storage_name, "path": source, "recursive": True})

        return self._exec_storage_rclone(
            storage,
            [
                "moveto",
                self._storage_rclone_path(storage, source),
                self._storage_rclone_path(storage, destination),
            ],
        )

    def _exec_provider_storage_upload(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Upload local path to storage path."""
        if not isinstance(params, dict):
            return False, "Provider storage.upload params must be an object"

        storage_name = str(params.get("storage") or params.get("storage_id") or "").strip()
        if not storage_name:
            return False, "Provider storage.upload requires 'storage'"
        storage_name = storage_name[1:] if storage_name.startswith("@") else storage_name

        source = self._interpolate(str(params.get("source", "")).strip())
        if not source:
            return False, "Provider storage.upload requires 'source'"

        destination = self._interpolate(str(
            params.get("destination", params.get("path", ""))
        )).strip()
        if not destination:
            # Default to storage root if not provided.
            destination = "/"

        return self._exec_provider_transfer(
            {
                "source": source,
                "destination": f"@{storage_name}:{destination}",
                "operation": str(params.get("operation", "copy")).strip().lower(),
                "delete": False,
            }
        )

    def _exec_provider_storage_download(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Download storage path to local path."""
        if not isinstance(params, dict):
            return False, "Provider storage.download params must be an object"

        storage_name = str(params.get("storage") or params.get("storage_id") or "").strip()
        if not storage_name:
            return False, "Provider storage.download requires 'storage'"
        storage_name = storage_name[1:] if storage_name.startswith("@") else storage_name

        source = self._interpolate(str(params.get("source", params.get("path", ""))).strip())
        if not source:
            return False, "Provider storage.download requires 'source'"

        destination = self._interpolate(str(params.get("destination", "")).strip())
        if not destination:
            return False, "Provider storage.download requires 'destination'"

        return self._exec_provider_transfer(
            {
                "source": f"@{storage_name}:{source}",
                "destination": destination,
                "operation": str(params.get("operation", "copy")).strip().lower(),
                "delete": False,
            }
        )

    def _exec_provider_transfer(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Execute transfer via provider."""
        if not isinstance(params, dict):
            return False, "Provider transfer params must be an object"

        source = str(params.get("source", "")).strip()
        destination = str(params.get("destination", "")).strip()
        if not source or not destination:
            return False, "Provider transfer requires 'source' and 'destination'"

        operation = str(params.get("operation", "copy")).strip().lower()
        if operation in {"move", "mirror"}:
            operation = "sync"
            delete = self._coerce_bool(params.get("delete", True), default=True)
        else:
            delete = self._coerce_bool(params.get("delete", False), default=False)

        exclude = self._coerce_list(params.get("exclude", params.get("exclude_patterns", None)))

        return self.transfer_helper.transfer(
            source,
            destination,
            delete=delete,
            exclude=exclude,
            operation=operation,
        )

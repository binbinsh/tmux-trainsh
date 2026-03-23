# tmux-trainsh transfer helpers
# Extracts transfer and endpoint parsing logic from DSLExecutor.

import os
from typing import Any, Callable, Dict, Iterable, List, Optional

from .models import Host
from .storage_specs import (
    build_storage_from_spec,
    parse_inline_storage_endpoint,
    unsupported_inline_storage_error,
)


class TransferHelper:
    """Helper for transfer steps and endpoint parsing."""

    def __init__(
        self,
        executor: Any,
        resolve_vast_host: Callable[[str], str],
        resolve_runpod_host: Optional[Callable[[str], str]] = None,
        host_from_ssh_spec: Optional[Callable[[str], Host]] = None,
    ):
        self.executor = executor
        self.resolve_vast_host = resolve_vast_host
        self.resolve_runpod_host = resolve_runpod_host or (lambda pod_id: f"runpod-{pod_id}")
        if host_from_ssh_spec is None:
            raise TypeError("host_from_ssh_spec is required")
        self.host_from_ssh_spec = host_from_ssh_spec

    def exec_transfer(self, step: Any) -> tuple[bool, str]:
        """Execute file transfer: source -> dest"""
        source = getattr(step, "source", "")
        destination = getattr(step, "dest", "")
        delete = self._coerce_bool(getattr(step, "delete", False))
        operation = str(getattr(step, "operation", "copy")).strip().lower()
        exclude = self._coerce_list(getattr(step, "exclude", None))

        # Treat explicit sync-like op as delete enabled.
        if operation == "sync":
            delete = True

        return self.transfer(
            source,
            destination,
            delete=delete,
            exclude=exclude,
            operation=operation,
        )

    def transfer(
        self,
        source: str,
        destination: str,
        *,
        delete: bool = False,
        exclude: Optional[Iterable[Any]] = None,
        operation: str = "copy",
    ) -> tuple[bool, str]:
        """Execute transfer between source and destination specs."""
        operation = (operation or "copy").strip().lower()
        if operation not in {"copy", "sync"}:
            return False, f"Unsupported transfer operation: {operation!r}"
        if operation == "sync":
            delete = True

        from ..services.transfer_engine import TransferEngine

        source = self.executor._interpolate(str(source or "").strip())
        destination = self.executor._interpolate(str(destination or "").strip())

        for label, value in (("source", source), ("destination", destination)):
            error = unsupported_inline_storage_error(value)
            if error:
                return False, f"{label.capitalize()} endpoint {value!r}: {error}"

        if not source or not destination:
            return False, "Transfer requires both source and destination"

        transfer_info = {
            "source": source,
            "destination": destination,
            "delete": bool(delete),
            "operation": operation,
            "exclude": list(exclude or []),
        }
        if self.executor.logger:
            self.executor.logger.log_detail("transfer", f"Transferring {source} -> {destination}", transfer_info)

        src_endpoint = self.parse_endpoint(source)
        dst_endpoint = self.parse_endpoint(destination)

        import time
        start_time = time.time()
        engine = TransferEngine()
        hosts = self.build_transfer_hosts()
        storages = self.build_transfer_storages()
        result = engine.transfer(
            source=src_endpoint,
            destination=dst_endpoint,
            hosts=hosts,
            storages=storages,
            delete=bool(delete),
            exclude=list(exclude or []),
        )
        duration_ms = int((time.time() - start_time) * 1000)

        if self.executor.logger:
            self.executor.logger.log_transfer(
                source,
                destination,
                "sync" if operation == "sync" else "copy",
                result.bytes_transferred,
                duration_ms,
                result.success,
                result.message,
            )

        if result.success:
            return True, f"Transferred {result.bytes_transferred} bytes"
        return False, result.message

    def _coerce_bool(self, value: Any, *, default: bool = False) -> bool:
        """Normalize bool-like transfer inputs."""
        if isinstance(value, bool):
            return bool(value)
        if value is None:
            return bool(default)
        text = str(value).strip().lower()
        if not text:
            return bool(default)
        return text in {"1", "true", "yes", "y", "on", "t"}

    def _coerce_list(self, value: Any) -> Optional[List[str]]:
        """Normalize list-like values for transfer excludes."""
        if value is None:
            return None

        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]

        text = str(value).strip()
        if not text:
            return None
        return [item.strip() for item in text.split(",") if item.strip()]

    def parse_endpoint(self, spec: str) -> Any:
        """Parse transfer endpoint: @host:/path, @storage:/path, or /local/path"""
        from ..commands.host import load_hosts
        from ..commands.storage import load_storages
        from ..core.models import TransferEndpoint

        if spec.startswith("@"):
            if ":" in spec:
                name_part, path = spec.split(":", 1)
                name = name_part[1:]
                global_storages = load_storages()

                if name in self.executor.recipe.storages:
                    return TransferEndpoint(type="storage", path=path, storage_id=name)
                if name in global_storages:
                    return TransferEndpoint(type="storage", path=path, storage_id=name)

                inline_storage = parse_inline_storage_endpoint(f"{name}:{path}")
                if inline_storage is not None:
                    storage_id, storage_path = inline_storage
                    return TransferEndpoint(type="storage", path=storage_path, storage_id=storage_id)

                if name in self.executor.recipe.hosts:
                    host = self.executor.recipe.hosts[name]
                    return TransferEndpoint(type="host", path=path, host_id=host)

                global_hosts = load_hosts()
                if name in global_hosts:
                    return TransferEndpoint(type="host", path=path, host_id=name)

                return TransferEndpoint(type="host", path=path, host_id=name)

            return TransferEndpoint(type="host", path="/", host_id=spec[1:])

        if spec.startswith("host:"):
            parts = spec[5:].split(":", 1)
            if len(parts) == 2:
                return TransferEndpoint(type="host", path=parts[1], host_id=parts[0])
            return TransferEndpoint(type="host", path=parts[0], host_id=parts[0])

        if spec.startswith("storage:"):
            storage_spec = spec[8:]
            inline_storage = parse_inline_storage_endpoint(storage_spec)
            if inline_storage is not None:
                storage_id, storage_path = inline_storage
                return TransferEndpoint(type="storage", path=storage_path, storage_id=storage_id)
            parts = storage_spec.split(":", 1)
            if len(parts) == 2:
                return TransferEndpoint(type="storage", path=parts[1], storage_id=parts[0])
            return TransferEndpoint(type="storage", path=parts[0], storage_id=parts[0])

        inline_storage = parse_inline_storage_endpoint(spec)
        if inline_storage is not None:
            storage_id, storage_path = inline_storage
            return TransferEndpoint(type="storage", path=storage_path, storage_id=storage_id)

        return TransferEndpoint(type="local", path=os.path.expanduser(spec))

    def build_transfer_hosts(self) -> Dict[str, Host]:
        """Build host mapping for transfers from recipe host specs and global config."""
        from ..commands.host import load_hosts

        global_hosts = load_hosts()
        hosts: Dict[str, Host] = dict(global_hosts)

        for name, spec in self.executor.recipe.hosts.items():
            if spec == "local":
                continue
            resolved_spec = spec
            if spec.startswith("vast:"):
                resolved_spec = self.resolve_vast_host(spec[5:])
            elif spec.startswith("runpod:"):
                resolved_spec = self.resolve_runpod_host(spec[7:])
            hosts[name] = self.host_from_ssh_spec(resolved_spec)
            hosts[spec] = hosts[name]
        return hosts

    def build_transfer_storages(self) -> Dict[str, Any]:
        """Build storage mapping for transfers from recipe storage specs."""
        from ..commands.storage import load_storages
        from ..core.models import Storage

        global_storages = load_storages()
        storages: Dict[str, Any] = dict(global_storages)

        for name, spec in self.executor.recipe.storages.items():
            if isinstance(spec, Storage):
                storages[name] = spec
                continue
            if isinstance(spec, dict):
                try:
                    storages[name] = Storage.from_dict(spec)
                    continue
                except Exception:
                    pass
            if spec in global_storages:
                storages[name] = global_storages[spec]
                continue

            resolved = build_storage_from_spec(spec, storage_name=name)
            if resolved is not None:
                storages[name] = resolved
        return storages

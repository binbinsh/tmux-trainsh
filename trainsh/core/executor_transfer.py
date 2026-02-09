# tmux-trainsh transfer helpers
# Extracts transfer and endpoint parsing logic from DSLExecutor.

import os
from typing import Any, Callable, Dict

from .models import Host


class TransferHelper:
    """Helper for transfer steps and endpoint parsing."""

    def __init__(
        self,
        executor: Any,
        resolve_vast_host: Callable[[str], str],
        host_from_ssh_spec: Callable[[str], Host],
    ):
        self.executor = executor
        self.resolve_vast_host = resolve_vast_host
        self.host_from_ssh_spec = host_from_ssh_spec

    def exec_transfer(self, step: Any) -> tuple[bool, str]:
        """Execute file transfer: source -> dest"""
        from ..services.transfer_engine import TransferEngine

        source = self.executor._interpolate(step.source)
        dest = self.executor._interpolate(step.dest)

        transfer_info = {
            "source": source,
            "dest": dest,
        }
        if self.executor.logger:
            self.executor.logger.log_detail("transfer", f"Transferring {source} -> {dest}", transfer_info)

        src_endpoint = self.parse_endpoint(source)
        dst_endpoint = self.parse_endpoint(dest)

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
        )
        duration_ms = int((time.time() - start_time) * 1000)

        if self.executor.logger:
            self.executor.logger.log_transfer(
                source, dest, "rsync",
                result.bytes_transferred,
                duration_ms,
                result.success,
                result.message
            )

        if result.success:
            return True, f"Transferred {result.bytes_transferred} bytes"
        return False, result.message

    def parse_endpoint(self, spec: str) -> Any:
        """Parse transfer endpoint: @host:/path, @storage:/path, or /local/path"""
        from ..commands.host import load_hosts
        from ..core.models import TransferEndpoint

        if spec.startswith("@"):
            if ":" in spec:
                name_part, path = spec.split(":", 1)
                name = name_part[1:]

                if name in self.executor.recipe.storages:
                    return TransferEndpoint(type="storage", path=path, storage_id=name)

                if name in self.executor.recipe.hosts:
                    host = self.executor.recipe.hosts[name]
                    return TransferEndpoint(type="host", path=path, host_id=host)

                global_hosts = load_hosts()
                if name in global_hosts:
                    return TransferEndpoint(type="host", path=path, host_id=name)

                return TransferEndpoint(type="host", path=path, host_id=name)

            return TransferEndpoint(type="host", path="/", host_id=spec[1:])

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
            hosts[name] = self.host_from_ssh_spec(resolved_spec)
            hosts[spec] = hosts[name]
        return hosts

    def build_transfer_storages(self) -> Dict[str, Any]:
        """Build storage mapping for transfers from recipe storage specs."""
        from ..commands.storage import load_storages
        from ..core.models import Storage, StorageType

        global_storages = load_storages()
        storages: Dict[str, Any] = {}

        for name, spec in self.executor.recipe.storages.items():
            if spec in global_storages:
                storages[name] = global_storages[spec]
            elif spec != "placeholder":
                if ":" in spec:
                    provider, bucket = spec.split(":", 1)
                    storage_type = StorageType.R2
                    if provider == "b2":
                        storage_type = StorageType.B2
                    elif provider == "s3":
                        storage_type = StorageType.S3
                    elif provider == "gdrive":
                        storage_type = StorageType.GDRIVE

                    storages[name] = Storage(
                        id=name,
                        name=name,
                        type=storage_type,
                        bucket=bucket,
                    )
        return storages

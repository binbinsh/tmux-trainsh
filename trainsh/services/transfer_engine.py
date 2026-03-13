import subprocess
import os
import re
import tempfile
from typing import Optional, List, Callable

from ..core.models import Host, Storage, StorageType, TransferEndpoint, HostType
from . import transfer_support as _transfer_support
from .transfer_support import (
    TransferPlan,
    TransferProgress,
    TransferResult,
    _parse_rsync_progress,
    analyze_transfer,
    check_rclone_available,
    check_rsync_available,
    get_rclone_remote_name,
    resolve_storage_remote_path,
    rsync_with_progress,
)


get_secrets_manager = _transfer_support.get_secrets_manager


def build_rclone_env(storage: Storage, remote_name: Optional[str] = None):
    """Compatibility wrapper so existing patch points stay valid."""
    original = _transfer_support.get_secrets_manager
    _transfer_support.get_secrets_manager = get_secrets_manager
    try:
        return _transfer_support.build_rclone_env(storage, remote_name=remote_name)
    finally:
        _transfer_support.get_secrets_manager = original


class TransferEngine:
    """
    File transfer engine supporting rsync and rclone.

    Supports transfers between:
    - Local filesystem
    - SSH hosts (using rsync)
    - Cloud storage (using rclone)
    """

    def __init__(
        self,
        progress_callback: Optional[Callable[[TransferProgress], None]] = None,
    ):
        """
        Initialize the transfer engine.

        Args:
            progress_callback: Optional callback for progress updates
        """
        self.progress_callback = progress_callback

    def rsync(
        self,
        source: str,
        destination: str,
        host: Optional[Host] = None,
        upload: bool = True,
        delete: bool = False,
        exclude: Optional[List[str]] = None,
        use_gitignore: bool = False,
        compress: bool = True,
        dry_run: bool = False,
    ) -> TransferResult:
        """
        Transfer files using rsync.

        Args:
            source: Source path
            destination: Destination path
            host: Remote host (for SSH transfers)
            upload: True for upload, False for download
            delete: Delete files on destination not in source
            exclude: Patterns to exclude
            use_gitignore: Exclude files based on .gitignore
            compress: Enable compression
            dry_run: Simulate transfer

        Returns:
            TransferResult with status
        """
        args = ["rsync", "-avz", "--progress", "--mkpath"]

        if delete:
            args.append("--delete")

        if compress:
            args.append("-z")

        if dry_run:
            args.append("--dry-run")

        # Add exclude patterns
        for pattern in (exclude or []):
            args.extend(["--exclude", pattern])

        if use_gitignore:
            args.append("--filter=:- .gitignore")

        # Build source/destination with SSH host
        if host:
            ssh_cmd = f"ssh -p {host.port}"
            if host.ssh_key_path:
                key_path = os.path.expanduser(host.ssh_key_path)
                if os.path.exists(key_path):
                    ssh_cmd += f" -i {key_path}"
            args.extend(["-e", ssh_cmd])

            host_prefix = f"{host.username}@{host.hostname}:" if host.username else f"{host.hostname}:"

            if upload:
                args.append(os.path.expanduser(source))
                args.append(f"{host_prefix}{destination}")
            else:
                args.append(f"{host_prefix}{source}")
                args.append(os.path.expanduser(destination))
        else:
            args.append(os.path.expanduser(source))
            args.append(os.path.expanduser(destination))

        try:
            # Run rsync with real-time output for progress
            import sys
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            output_lines = []
            bytes_transferred = 0

            # Stream output in real-time
            for line in process.stdout:
                line = line.rstrip()
                output_lines.append(line)

                # Show progress lines (rsync progress format)
                if line and not line.startswith(' '):
                    print(f"  {line}", flush=True)

                # Parse bytes from final summary
                match = re.search(r"sent ([\d,]+) bytes", line)
                if match:
                    bytes_transferred = int(match.group(1).replace(",", ""))

            process.wait()

            return TransferResult(
                success=process.returncode == 0,
                exit_code=process.returncode,
                message="\n".join(output_lines[-5:]) if process.returncode != 0 else "Transfer complete",
                bytes_transferred=bytes_transferred,
            )
        except Exception as e:
            return TransferResult(
                success=False,
                exit_code=-1,
                message=str(e),
            )

    def rclone(
        self,
        source: str,
        destination: str,
        operation: str = "copy",
        delete: bool = False,
        dry_run: bool = False,
        progress: bool = True,
        src_storage: Optional[Storage] = None,
        dst_storage: Optional[Storage] = None,
    ) -> TransferResult:
        """
        Transfer files using rclone.

        Args:
            source: Source path (remote:path format for remotes)
            destination: Destination path
            operation: Operation type (copy, sync, move)
            delete: Delete destination files not in source (for sync)
            dry_run: Simulate transfer
            progress: Show progress
            src_storage: Source storage configuration (for auto-config)
            dst_storage: Destination storage configuration (for auto-config)

        Returns:
            TransferResult with status
        """
        args = ["rclone", operation]

        if progress:
            args.append("--progress")

        if dry_run:
            args.append("--dry-run")

        if delete and operation == "sync":
            args.append("--delete-after")

        args.extend([source, destination])

        # Build environment with storage credentials
        env = os.environ.copy()

        if src_storage:
            rclone_env = build_rclone_env(src_storage)
            env.update(rclone_env)

        if dst_storage:
            rclone_env = build_rclone_env(dst_storage)
            env.update(rclone_env)

        try:
            # Run rclone with real-time progress output
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )

            output_lines = []
            bytes_transferred = 0

            # Stream output in real-time
            for line in process.stdout:
                line = line.rstrip()
                output_lines.append(line)

                # Show progress lines
                if line:
                    # rclone progress format: "Transferred: X / Y, ETA X"
                    print(f"  {line}", flush=True)

                    # Parse transferred bytes from rclone output
                    match = re.search(r"Transferred:\s+([\d.]+)\s*(\w+)", line)
                    if match:
                        size_str = match.group(1)
                        unit = match.group(2).upper()
                        try:
                            size = float(size_str)
                            if unit == "KIB" or unit == "KB":
                                bytes_transferred = int(size * 1024)
                            elif unit == "MIB" or unit == "MB":
                                bytes_transferred = int(size * 1024 * 1024)
                            elif unit == "GIB" or unit == "GB":
                                bytes_transferred = int(size * 1024 * 1024 * 1024)
                            else:
                                bytes_transferred = int(size)
                        except ValueError:
                            pass

            process.wait()

            return TransferResult(
                success=process.returncode == 0,
                exit_code=process.returncode,
                message="\n".join(output_lines[-5:]) if process.returncode != 0 else "Transfer complete",
                bytes_transferred=bytes_transferred,
            )
        except FileNotFoundError:
            return TransferResult(
                success=False,
                exit_code=-1,
                message="rclone not found. Install with: brew install rclone",
            )
        except Exception as e:
            return TransferResult(
                success=False,
                exit_code=-1,
                message=str(e),
            )

    def transfer(
        self,
        source: TransferEndpoint,
        destination: TransferEndpoint,
        hosts: dict[str, Host] = None,
        storages: dict[str, Storage] = None,
        delete: bool = False,
        exclude: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> TransferResult:
        """
        High-level transfer between endpoints.

        Automatically selects rsync or rclone based on endpoint types.

        Args:
            source: Source endpoint
            destination: Destination endpoint
            hosts: Dictionary of host ID -> Host
            storages: Dictionary of storage ID -> Storage
            delete: Delete files not in source
            exclude: Patterns to exclude

        Returns:
            TransferResult with status
        """
        hosts = hosts or {}
        storages = storages or {}

        # Determine transfer method based on endpoint types
        tool = self._select_transfer_tool(source, destination, storages)

        if tool == "rclone":
            # Get storage objects for credentials
            src_storage = storages.get(source.storage_id) if source.storage_id else None
            dst_storage = storages.get(destination.storage_id) if destination.storage_id else None
            src_host = hosts.get(source.host_id) if source.host_id else None
            dst_host = hosts.get(destination.host_id) if destination.host_id else None

            if src_host and dst_storage is not None:
                return self._transfer_host_with_cloud_storage(
                    source=source,
                    destination=destination,
                    src_host=src_host,
                    dst_storage=dst_storage,
                    delete=delete,
                    exclude=exclude,
                    dry_run=dry_run,
                    hosts=hosts,
                    storages=storages,
                )
            if src_storage is not None and dst_host:
                return self._transfer_cloud_storage_with_host(
                    source=source,
                    destination=destination,
                    src_storage=src_storage,
                    dst_host=dst_host,
                    delete=delete,
                    exclude=exclude,
                    dry_run=dry_run,
                    hosts=hosts,
                    storages=storages,
                )

            # Resolve paths using appropriate remote names
            src_path = self._resolve_endpoint_for_rclone(source, hosts, storages)
            dst_path = self._resolve_endpoint_for_rclone(destination, hosts, storages)

            return self.rclone(
                source=src_path,
                destination=dst_path,
                operation="sync" if delete else "copy",
                dry_run=dry_run,
                src_storage=src_storage,
                dst_storage=dst_storage,
            )
        else:
            # Use rsync for local/SSH/host transfers
            src_host = hosts.get(source.host_id) if source.host_id else None
            dst_host = hosts.get(destination.host_id) if destination.host_id else None
            source_path = source.path
            destination_path = destination.path

            # Handle storage-backed roots for rsync-capable backends.
            if source.storage_id:
                src_storage = storages.get(source.storage_id)
                if src_storage:
                    if src_storage.type == StorageType.SSH:
                        src_host = self._storage_to_host(src_storage)
                    if src_storage.type in {StorageType.SSH, StorageType.LOCAL}:
                        source_path = self._storage_rooted_path(src_storage, source.path)
            if destination.storage_id:
                dst_storage = storages.get(destination.storage_id)
                if dst_storage:
                    if dst_storage.type == StorageType.SSH:
                        dst_host = self._storage_to_host(dst_storage)
                    if dst_storage.type in {StorageType.SSH, StorageType.LOCAL}:
                        destination_path = self._storage_rooted_path(dst_storage, destination.path)

            source_endpoint = TransferEndpoint(
                type=source.type,
                path=source_path,
                host_id=source.host_id,
                storage_id=source.storage_id,
            )
            destination_endpoint = TransferEndpoint(
                type=destination.type,
                path=destination_path,
                host_id=destination.host_id,
                storage_id=destination.storage_id,
            )

            if src_host and dst_host:
                # Host-to-host transfer
                return self._transfer_host_to_host(
                    source_endpoint, destination_endpoint, src_host, dst_host, delete, exclude, dry_run
                )

            host = src_host or dst_host
            upload = dst_host is not None

            return self.rsync(
                source=source_endpoint.path,
                destination=destination_endpoint.path,
                host=host,
                upload=upload,
                delete=delete,
                exclude=exclude,
                dry_run=dry_run,
            )

    def _select_transfer_tool(
        self,
        source: TransferEndpoint,
        destination: TransferEndpoint,
        storages: dict[str, Storage],
    ) -> str:
        """Select transfer tool: 'rsync' or 'rclone'."""
        src_storage = storages.get(source.storage_id) if source.storage_id else None
        dst_storage = storages.get(destination.storage_id) if destination.storage_id else None

        # SSH and local storage can be resolved directly for rsync/local copies.
        if src_storage and src_storage.type in {StorageType.SSH, StorageType.LOCAL}:
            return "rsync"
        if dst_storage and dst_storage.type in {StorageType.SSH, StorageType.LOCAL}:
            return "rsync"

        # Cloud storage uses rclone
        if src_storage or dst_storage:
            return "rclone"

        # Host-to-Host or Local uses rsync
        return "rsync"

    def _storage_to_host(self, storage: Storage) -> Host:
        """Convert SSH storage to Host object."""
        config = storage.config
        host_value = str(config.get("host") or config.get("hostname") or "").strip()
        parsed_user, parsed_host = _transfer_support._split_ssh_target(host_value)
        return Host(
            id=storage.id,
            name=storage.name,
            type=HostType.SSH,
            hostname=parsed_host or host_value,
            port=config.get("port", 22),
            username=config.get("user") or config.get("username") or parsed_user,
            ssh_key_path=config.get("key_file") or config.get("key_path"),
        )

    def _storage_rooted_path(self, storage: Storage, path: str) -> str:
        """Resolve a transfer path within a local or SSH storage root."""
        if storage.type == StorageType.LOCAL:
            base_path = str(storage.config.get("path", "")).strip()
            relative = str(path or "").strip().lstrip("/")
            if base_path:
                base_path = os.path.expanduser(base_path)
                return base_path if not relative else os.path.join(base_path, relative)
            return os.path.expanduser(relative or ".")

        if storage.type == StorageType.SSH:
            return resolve_storage_remote_path(storage, path)

        return str(path or "").strip()

    def _transfer_host_with_cloud_storage(
        self,
        *,
        source: TransferEndpoint,
        destination: TransferEndpoint,
        src_host: Host,
        dst_storage: Storage,
        delete: bool,
        exclude: Optional[List[str]],
        dry_run: bool,
        hosts: dict[str, Host],
        storages: dict[str, Storage],
    ) -> TransferResult:
        """Relay a host -> cloud-storage transfer through a local temp directory."""
        if dry_run:
            return TransferResult(
                success=False,
                exit_code=2,
                message="Dry run is not supported for relayed host-to-cloud transfers.",
            )
        with tempfile.TemporaryDirectory(prefix="trainsh-transfer-") as tmpdir:
            stage_path = os.path.join(tmpdir, "payload")
            pulled = self.rsync(
                source=source.path,
                destination=stage_path,
                host=src_host,
                upload=False,
                delete=False,
                exclude=exclude,
            )
            if not pulled.success:
                return pulled

            pushed = self.rclone(
                source=stage_path,
                destination=self._resolve_endpoint_for_rclone(destination, hosts, storages),
                operation="sync" if delete else "copy",
                dry_run=False,
                dst_storage=dst_storage,
            )
            if pushed.bytes_transferred <= 0:
                pushed.bytes_transferred = pulled.bytes_transferred
            return pushed

    def _transfer_cloud_storage_with_host(
        self,
        *,
        source: TransferEndpoint,
        destination: TransferEndpoint,
        src_storage: Storage,
        dst_host: Host,
        delete: bool,
        exclude: Optional[List[str]],
        dry_run: bool,
        hosts: dict[str, Host],
        storages: dict[str, Storage],
    ) -> TransferResult:
        """Relay a cloud-storage -> host transfer through a local temp directory."""
        if dry_run:
            return TransferResult(
                success=False,
                exit_code=2,
                message="Dry run is not supported for relayed cloud-to-host transfers.",
            )
        with tempfile.TemporaryDirectory(prefix="trainsh-transfer-") as tmpdir:
            stage_path = os.path.join(tmpdir, "payload")
            pulled = self.rclone(
                source=self._resolve_endpoint_for_rclone(source, hosts, storages),
                destination=stage_path,
                operation="copy",
                dry_run=False,
                src_storage=src_storage,
            )
            if not pulled.success:
                return pulled

            pushed = self.rsync(
                source=stage_path,
                destination=destination.path,
                host=dst_host,
                upload=True,
                delete=delete,
                exclude=exclude,
            )
            if pushed.bytes_transferred <= 0:
                pushed.bytes_transferred = pulled.bytes_transferred
            return pushed

    def _transfer_host_to_host(
        self,
        source: TransferEndpoint,
        destination: TransferEndpoint,
        src_host: Host,
        dst_host: Host,
        delete: bool = False,
        exclude: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> TransferResult:
        """
        Transfer files between two remote hosts.

        Strategy:
        1. If src_host can SSH to dst_host: use remote rsync (direct)
        2. Otherwise: use scp -3 through local relay
        """
        can_direct = self._check_host_connectivity(src_host, dst_host)

        if can_direct:
            return self._rsync_remote_to_remote(
                source, destination, src_host, dst_host, delete, exclude, dry_run
            )
        else:
            return self._scp_three_way(source, destination, src_host, dst_host, dry_run=dry_run)

    def _check_host_connectivity(self, src: Host, dst: Host) -> bool:
        """Check if src_host can SSH to dst_host directly."""
        try:
            # Build SSH command to check connectivity
            dst_spec = f"{dst.username}@{dst.hostname}" if dst.username else dst.hostname
            check_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no"
            if dst.port != 22:
                check_cmd += f" -p {dst.port}"
            check_cmd += f" {dst_spec} echo ok"

            # Execute check from src_host
            src_ssh = self._build_ssh_args(src)
            full_cmd = src_ssh + [check_cmd]

            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.returncode == 0 and "ok" in result.stdout
        except (subprocess.TimeoutExpired, Exception):
            return False

    def _rsync_remote_to_remote(
        self,
        source: TransferEndpoint,
        destination: TransferEndpoint,
        src_host: Host,
        dst_host: Host,
        delete: bool = False,
        exclude: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> TransferResult:
        """Execute rsync from src_host to dst_host directly."""
        # Build rsync command to run on src_host
        rsync_parts = ["rsync", "-avz", "--progress"]
        if delete:
            rsync_parts.append("--delete")
        if dry_run:
            rsync_parts.append("--dry-run")
        for pattern in (exclude or []):
            rsync_parts.append(f"--exclude={pattern}")

        # Destination spec
        dst_spec = f"{dst_host.username}@{dst_host.hostname}" if dst_host.username else dst_host.hostname
        if dst_host.port != 22:
            rsync_parts.extend(["-e", f"'ssh -p {dst_host.port}'"])

        rsync_parts.append(source.path)
        rsync_parts.append(f"{dst_spec}:{destination.path}")

        rsync_cmd = " ".join(rsync_parts)

        # Execute on src_host
        src_ssh = self._build_ssh_args(src_host)
        full_cmd = src_ssh + [rsync_cmd]

        try:
            # Run with real-time output
            process = subprocess.Popen(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            output_lines = []
            bytes_transferred = 0

            for line in process.stdout:
                line = line.rstrip()
                output_lines.append(line)
                # Show all non-empty lines
                if line:
                    print(f"  {line}", flush=True)
                # Parse bytes from final summary
                match = re.search(r"sent ([\d,]+) bytes", line)
                if match:
                    bytes_transferred = int(match.group(1).replace(",", ""))

            process.wait()

            return TransferResult(
                success=process.returncode == 0,
                exit_code=process.returncode,
                message="\n".join(output_lines[-5:]) if process.returncode != 0 else "Transfer complete",
                bytes_transferred=bytes_transferred,
            )
        except subprocess.TimeoutExpired:
            return TransferResult(
                success=False,
                exit_code=-1,
                message="Transfer timed out",
            )
        except Exception as e:
            return TransferResult(
                success=False,
                exit_code=-1,
                message=str(e),
            )

    def _scp_three_way(
        self,
        source: TransferEndpoint,
        destination: TransferEndpoint,
        src_host: Host,
        dst_host: Host,
        *,
        dry_run: bool = False,
    ) -> TransferResult:
        """Transfer using ssh + tar pipe with pv for progress.

        Data flows: src_host -> local memory (pv) -> dst_host
        No files are written to local disk.

        Command: ssh src 'tar cf - path' | pv | ssh dst 'tar xf - -C dest'
        """
        if dry_run:
            return TransferResult(
                success=False,
                exit_code=2,
                message="Dry run is not supported for relayed host-to-host transfers.",
            )
        src_ssh = self._build_ssh_args(src_host)
        dst_ssh = self._build_ssh_args(dst_host)

        src_path = source.path.rstrip('/')
        dst_path = destination.path.rstrip('/')

        # Build tar commands based on path structure
        src_parent = os.path.dirname(src_path)
        src_basename = os.path.basename(src_path)

        if destination.path.endswith('/'):
            tar_create = f"tar cf - -C '{src_parent}' '{src_basename}'"
            tar_extract = f"tar xf - -C '{dst_path}'"
        else:
            dst_parent = os.path.dirname(dst_path)
            tar_create = f"tar cf - -C '{src_parent}' '{src_basename}'"
            tar_extract = f"mkdir -p '{dst_parent}' && tar xf - -C '{dst_parent}'"

        src_cmd = src_ssh + [tar_create]
        dst_cmd = dst_ssh + [tar_extract]

        def shell_quote(args):
            return ' '.join(f"'{a}'" if ' ' in a or "'" not in a else f'"{a}"' for a in args)

        # Check if pv is available for progress display
        has_pv = subprocess.run(["which", "pv"], capture_output=True).returncode == 0

        if has_pv:
            # Use pv for progress: ssh src | pv | ssh dst
            full_cmd = f"{shell_quote(src_cmd)} | pv -pterab | {shell_quote(dst_cmd)}"
            print(f"  Streaming: {src_host.hostname} -> {dst_host.hostname} (with progress)", flush=True)
        else:
            full_cmd = f"{shell_quote(src_cmd)} | {shell_quote(dst_cmd)}"
            print(f"  Streaming: {src_host.hostname} -> {dst_host.hostname}", flush=True)
            print(f"  (Install 'pv' for progress display: brew install pv)", flush=True)

        try:
            # Run with stderr going directly to terminal for pv progress
            import sys
            process = subprocess.Popen(
                full_cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=None,  # Let stderr go directly to terminal
                text=True,
            )

            # Wait for process to complete
            stdout, _ = process.communicate()

            if process.returncode != 0:
                return TransferResult(
                    success=False,
                    exit_code=process.returncode,
                    message=f"Pipe transfer failed: {stdout or 'Unknown error'}",
                )

            print(f"\n  Transfer complete (streaming)", flush=True)
            return TransferResult(
                success=True,
                exit_code=0,
                message="Transfer complete (streaming)",
            )
        except Exception as e:
            return TransferResult(
                success=False,
                exit_code=-1,
                message=str(e),
            )

    def _build_ssh_args(self, host: Host) -> List[str]:
        """Build SSH command arguments for a host."""
        args = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no"]

        if host.port != 22:
            args.extend(["-p", str(host.port)])

        if host.ssh_key_path:
            key_path = os.path.expanduser(host.ssh_key_path)
            if os.path.exists(key_path):
                args.extend(["-i", key_path])

        proxy_command = self._resolve_proxy_command(host)
        if proxy_command:
            args.extend(["-o", f"ProxyCommand={proxy_command}"])
        elif host.jump_host:
            args.extend(["-J", host.jump_host.strip()])

        host_spec = f"{host.username}@{host.hostname}" if host.username else host.hostname
        args.append(host_spec)

        return args

    def _resolve_proxy_command(self, host: Host) -> Optional[str]:
        """Resolve proxy command from host config, including cloudflared shortcuts."""
        env_vars = host.env_vars or {}
        proxy_command = str(env_vars.get("proxy_command", "")).strip()
        if proxy_command:
            return proxy_command

        tunnel_type = str(env_vars.get("tunnel_type", "")).strip().lower()
        if tunnel_type != "cloudflared":
            return None

        cloudflared_hostname = str(env_vars.get("cloudflared_hostname", host.hostname)).strip()
        if not cloudflared_hostname:
            return None

        cloudflared_bin = str(env_vars.get("cloudflared_bin", "cloudflared")).strip() or "cloudflared"
        return f"{cloudflared_bin} access ssh --hostname {cloudflared_hostname}"

    def _build_scp_spec(self, host: Host, path: str) -> str:
        """Build SCP path specification for a host."""
        host_spec = f"{host.username}@{host.hostname}" if host.username else host.hostname
        return f"{host_spec}:{path}"

    def _resolve_endpoint(
        self,
        endpoint: TransferEndpoint,
        hosts: dict[str, Host],
        storages: dict[str, Storage],
        for_rclone: bool = False,
    ) -> str:
        """Resolve an endpoint to a path string."""
        if endpoint.type == "local":
            return os.path.expanduser(endpoint.path)
        elif endpoint.type == "host" and endpoint.host_id:
            host = hosts.get(endpoint.host_id)
            if host:
                return f"{host.username}@{host.hostname}:{endpoint.path}"
            return endpoint.path
        elif endpoint.type == "storage" and endpoint.storage_id:
            storage = storages.get(endpoint.storage_id)
            if storage and for_rclone:
                # Return rclone remote format
                return f"{storage.name}:{endpoint.path}"
            return endpoint.path
        return endpoint.path

    def _resolve_endpoint_for_rclone(
        self,
        endpoint: TransferEndpoint,
        hosts: dict[str, Host],
        storages: dict[str, Storage],
    ) -> str:
        """
        Resolve an endpoint to rclone path format.

        For storage endpoints, uses get_rclone_remote_name() to determine
        the correct remote name (either from storage name or configured remote).

        Args:
            endpoint: Transfer endpoint
            hosts: Host dictionary
            storages: Storage dictionary

        Returns:
            Path in rclone format (remote:path or local path)
        """
        if endpoint.type == "local":
            return os.path.expanduser(endpoint.path)
        elif endpoint.type == "storage" and endpoint.storage_id:
            storage = storages.get(endpoint.storage_id)
            if storage:
                remote_name = get_rclone_remote_name(storage)
                path = resolve_storage_remote_path(storage, endpoint.path)
                return f"{remote_name}:{path}" if path else f"{remote_name}:"
            return endpoint.path
        elif endpoint.type == "host" and endpoint.host_id:
            # Host endpoints shouldn't use rclone, but handle gracefully
            host = hosts.get(endpoint.host_id)
            if host:
                return f"{host.username}@{host.hostname}:{endpoint.path}"
            return endpoint.path
        return endpoint.path

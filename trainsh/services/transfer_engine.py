# tmux-trainsh transfer engine
# File transfer using rsync and rclone

import subprocess
import os
import re
from typing import Optional, List, Callable, Dict
from dataclasses import dataclass

from ..core.models import Host, Storage, StorageType, TransferEndpoint, HostType
from ..core.secrets import get_secrets_manager
from ..constants import SecretKeys


def build_rclone_env(storage: Storage, remote_name: Optional[str] = None) -> Dict[str, str]:
    """
    Build rclone environment variables for a storage backend.

    rclone supports dynamic remote configuration via environment variables:
    RCLONE_CONFIG_<remote>_TYPE=<type>
    RCLONE_CONFIG_<remote>_<option>=<value>

    This allows us to configure remotes without modifying ~/.config/rclone/rclone.conf

    Credentials are loaded in priority order:
    1. Storage-specific secrets: {STORAGE_NAME}_ACCESS_KEY, etc.
    2. Global secrets: R2_ACCESS_KEY, AWS_ACCESS_KEY_ID, etc.
    3. Config values stored in storage.config

    Args:
        storage: Storage configuration
        remote_name: Override remote name (defaults to storage.name)

    Returns:
        Dictionary of environment variables to set
    """
    name = (remote_name or storage.name).upper().replace("-", "_").replace(" ", "_")
    storage_prefix = name  # For storage-specific secrets
    secrets = get_secrets_manager()
    env: Dict[str, str] = {}
    config = storage.config

    def get_credential(storage_key: str, global_key: str, config_key: str = "") -> str:
        """Get credential from storage-specific, global, or config sources."""
        # 1. Try storage-specific secret: {STORAGE_NAME}_{KEY}
        value = secrets.get(f"{storage_prefix}_{storage_key}")
        if value:
            return value
        # 2. Try global secret
        value = secrets.get(global_key)
        if value:
            return value
        # 3. Fall back to config value
        if config_key:
            return config.get(config_key, "")
        return ""

    if storage.type == StorageType.R2:
        # Cloudflare R2 (S3-compatible)
        env[f"RCLONE_CONFIG_{name}_TYPE"] = "s3"
        env[f"RCLONE_CONFIG_{name}_PROVIDER"] = "Cloudflare"
        env[f"RCLONE_CONFIG_{name}_ENV_AUTH"] = "false"

        # Get credentials with fallback chain
        access_key = get_credential("ACCESS_KEY", SecretKeys.R2_ACCESS_KEY, "access_key_id")
        secret_key = get_credential("SECRET_KEY", SecretKeys.R2_SECRET_KEY, "secret_access_key")

        if access_key:
            env[f"RCLONE_CONFIG_{name}_ACCESS_KEY_ID"] = access_key
        if secret_key:
            env[f"RCLONE_CONFIG_{name}_SECRET_ACCESS_KEY"] = secret_key

        # Endpoint from config
        endpoint = config.get("endpoint", "")
        if not endpoint and config.get("account_id"):
            endpoint = f"https://{config['account_id']}.r2.cloudflarestorage.com"
        if endpoint:
            env[f"RCLONE_CONFIG_{name}_ENDPOINT"] = endpoint

    elif storage.type == StorageType.S3:
        # Amazon S3 or S3-compatible
        env[f"RCLONE_CONFIG_{name}_TYPE"] = "s3"
        env[f"RCLONE_CONFIG_{name}_PROVIDER"] = config.get("provider", "AWS")
        env[f"RCLONE_CONFIG_{name}_ENV_AUTH"] = "false"

        # Get credentials with fallback chain
        access_key = get_credential("ACCESS_KEY_ID", SecretKeys.AWS_ACCESS_KEY_ID, "access_key_id")
        secret_key = get_credential("SECRET_ACCESS_KEY", SecretKeys.AWS_SECRET_ACCESS_KEY, "secret_access_key")

        if access_key:
            env[f"RCLONE_CONFIG_{name}_ACCESS_KEY_ID"] = access_key
        if secret_key:
            env[f"RCLONE_CONFIG_{name}_SECRET_ACCESS_KEY"] = secret_key

        # Region and endpoint
        if config.get("region"):
            env[f"RCLONE_CONFIG_{name}_REGION"] = config["region"]
        if config.get("endpoint"):
            env[f"RCLONE_CONFIG_{name}_ENDPOINT"] = config["endpoint"]

    elif storage.type == StorageType.B2:
        # Backblaze B2
        env[f"RCLONE_CONFIG_{name}_TYPE"] = "b2"

        # Get credentials with fallback chain
        key_id = get_credential("KEY_ID", SecretKeys.B2_KEY_ID, "key_id")
        app_key = get_credential("APPLICATION_KEY", SecretKeys.B2_APPLICATION_KEY, "application_key")

        if key_id:
            env[f"RCLONE_CONFIG_{name}_ACCOUNT"] = key_id
        if app_key:
            env[f"RCLONE_CONFIG_{name}_KEY"] = app_key

    elif storage.type == StorageType.GOOGLE_DRIVE:
        # Google Drive
        env[f"RCLONE_CONFIG_{name}_TYPE"] = "drive"

        # For Google Drive, we support two modes:
        # 1. Use existing rclone remote (remote_name in config)
        # 2. Use service account or token from secrets
        if config.get("client_id"):
            env[f"RCLONE_CONFIG_{name}_CLIENT_ID"] = config["client_id"]
        if config.get("client_secret"):
            env[f"RCLONE_CONFIG_{name}_CLIENT_SECRET"] = config["client_secret"]
        if config.get("root_folder_id"):
            env[f"RCLONE_CONFIG_{name}_ROOT_FOLDER_ID"] = config["root_folder_id"]

        # Token from secrets (JSON format) - try storage-specific first
        token = get_credential("TOKEN", SecretKeys.GOOGLE_DRIVE_CREDENTIALS, "token")
        if token:
            env[f"RCLONE_CONFIG_{name}_TOKEN"] = token

        # If using existing rclone remote, just pass through
        if config.get("remote_name") and not any(env):
            # User wants to use pre-configured rclone remote
            # In this case, return empty env and use the remote_name directly
            return {}

    elif storage.type == StorageType.GCS:
        # Google Cloud Storage
        env[f"RCLONE_CONFIG_{name}_TYPE"] = "google cloud storage"

        if config.get("project_id"):
            env[f"RCLONE_CONFIG_{name}_PROJECT_NUMBER"] = config["project_id"]
        if config.get("service_account_json"):
            env[f"RCLONE_CONFIG_{name}_SERVICE_ACCOUNT_CREDENTIALS"] = config["service_account_json"]
        if config.get("bucket"):
            env[f"RCLONE_CONFIG_{name}_BUCKET_POLICY_ONLY"] = "true"

    elif storage.type == StorageType.SSH:
        # SFTP via SSH
        env[f"RCLONE_CONFIG_{name}_TYPE"] = "sftp"

        if config.get("host"):
            env[f"RCLONE_CONFIG_{name}_HOST"] = config["host"]
        if config.get("user"):
            env[f"RCLONE_CONFIG_{name}_USER"] = config["user"]
        if config.get("port"):
            env[f"RCLONE_CONFIG_{name}_PORT"] = str(config["port"])
        if config.get("key_file"):
            key_path = os.path.expanduser(config["key_file"])
            env[f"RCLONE_CONFIG_{name}_KEY_FILE"] = key_path

    elif storage.type == StorageType.SMB:
        # SMB/CIFS share
        env[f"RCLONE_CONFIG_{name}_TYPE"] = "smb"

        if config.get("host"):
            env[f"RCLONE_CONFIG_{name}_HOST"] = config["host"]
        if config.get("user"):
            env[f"RCLONE_CONFIG_{name}_USER"] = config["user"]
        if config.get("pass"):
            env[f"RCLONE_CONFIG_{name}_PASS"] = config["pass"]
        if config.get("domain"):
            env[f"RCLONE_CONFIG_{name}_DOMAIN"] = config["domain"]

    return env


def get_rclone_remote_name(storage: Storage) -> str:
    """
    Get the rclone remote name for a storage.

    For Google Drive with existing rclone config, uses the configured remote_name.
    Otherwise uses the storage name (sanitized for rclone).

    Args:
        storage: Storage configuration

    Returns:
        Remote name to use in rclone commands
    """
    # If Google Drive with external rclone config, use that remote name
    if storage.type == StorageType.GOOGLE_DRIVE:
        remote_name = storage.config.get("remote_name")
        if remote_name:
            return remote_name

    # Otherwise use storage name
    return storage.name



@dataclass
class TransferProgress:
    """Progress information for a transfer."""
    bytes_transferred: int = 0
    total_bytes: int = 0
    percent: float = 0.0
    speed: str = ""
    eta: str = ""
    current_file: str = ""


@dataclass
class TransferResult:
    """Result of a transfer operation."""
    success: bool
    exit_code: int
    message: str
    bytes_transferred: int = 0


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

            # Resolve paths using appropriate remote names
            src_path = self._resolve_endpoint_for_rclone(source, hosts, storages)
            dst_path = self._resolve_endpoint_for_rclone(destination, hosts, storages)

            return self.rclone(
                source=src_path,
                destination=dst_path,
                operation="sync" if delete else "copy",
                src_storage=src_storage,
                dst_storage=dst_storage,
            )
        else:
            # Use rsync for local/SSH/host transfers
            src_host = hosts.get(source.host_id) if source.host_id else None
            dst_host = hosts.get(destination.host_id) if destination.host_id else None

            # Handle SSH storage as hosts
            if source.storage_id:
                src_storage = storages.get(source.storage_id)
                if src_storage and src_storage.type == StorageType.SSH:
                    src_host = self._storage_to_host(src_storage)
            if destination.storage_id:
                dst_storage = storages.get(destination.storage_id)
                if dst_storage and dst_storage.type == StorageType.SSH:
                    dst_host = self._storage_to_host(dst_storage)

            if src_host and dst_host:
                # Host-to-host transfer
                return self._transfer_host_to_host(
                    source, destination, src_host, dst_host, delete, exclude
                )

            host = src_host or dst_host
            upload = dst_host is not None

            return self.rsync(
                source=source.path,
                destination=destination.path,
                host=host,
                upload=upload,
                delete=delete,
                exclude=exclude,
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

        # SSH Storage uses rsync
        if src_storage and src_storage.type == StorageType.SSH:
            return "rsync"
        if dst_storage and dst_storage.type == StorageType.SSH:
            return "rsync"

        # Cloud storage uses rclone
        if src_storage or dst_storage:
            return "rclone"

        # Host-to-Host or Local uses rsync
        return "rsync"

    def _storage_to_host(self, storage: Storage) -> Host:
        """Convert SSH storage to Host object."""
        config = storage.config
        return Host(
            id=storage.id,
            name=storage.name,
            type=HostType.SSH,
            hostname=config.get("host", ""),
            port=config.get("port", 22),
            username=config.get("user", ""),
            ssh_key_path=config.get("key_file"),
        )

    def _transfer_host_to_host(
        self,
        source: TransferEndpoint,
        destination: TransferEndpoint,
        src_host: Host,
        dst_host: Host,
        delete: bool = False,
        exclude: Optional[List[str]] = None,
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
                source, destination, src_host, dst_host, delete, exclude
            )
        else:
            return self._scp_three_way(source, destination, src_host, dst_host)

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
    ) -> TransferResult:
        """Execute rsync from src_host to dst_host directly."""
        # Build rsync command to run on src_host
        rsync_parts = ["rsync", "-avz", "--progress"]
        if delete:
            rsync_parts.append("--delete")
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
    ) -> TransferResult:
        """Transfer using ssh + tar pipe with pv for progress.

        Data flows: src_host -> local memory (pv) -> dst_host
        No files are written to local disk.

        Command: ssh src 'tar cf - path' | pv | ssh dst 'tar xf - -C dest'
        """
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

        host_spec = f"{host.username}@{host.hostname}" if host.username else host.hostname
        args.append(host_spec)

        return args

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
                # Handle bucket in path for R2/S3/B2
                path = endpoint.path
                if storage.type in (StorageType.R2, StorageType.S3, StorageType.B2):
                    bucket = storage.config.get("bucket", "")
                    if bucket and not path.startswith(bucket):
                        # Prepend bucket to path
                        path = f"{bucket}/{path.lstrip('/')}"
                return f"{remote_name}:{path}"
            return endpoint.path
        elif endpoint.type == "host" and endpoint.host_id:
            # Host endpoints shouldn't use rclone, but handle gracefully
            host = hosts.get(endpoint.host_id)
            if host:
                return f"{host.username}@{host.hostname}:{endpoint.path}"
            return endpoint.path
        return endpoint.path


class TransferPlan:
    """Plan for how a transfer will be executed."""
    def __init__(self, method: str, via: str, description: str = ""):
        self.method = method  # "rsync" or "rclone"
        self.via = via  # "direct", "local-relay", "cloud", "local"
        self.description = description

    def __repr__(self) -> str:
        return f"TransferPlan(method={self.method}, via={self.via})"


def analyze_transfer(
    source: TransferEndpoint,
    destination: TransferEndpoint,
    hosts: dict[str, Host] = None,
    storages: dict[str, Storage] = None,
) -> TransferPlan:
    """
    Analyze endpoints and determine optimal transfer method.

    Protocol Selection:
    - SSH Host/Storage <-> SSH Host/Storage: rsync (direct or via local relay)
    - Any <-> Cloud Storage (r2/s3/b2/gdrive): rclone
    - Local <-> SSH: rsync

    Args:
        source: Source endpoint
        destination: Destination endpoint
        hosts: Dictionary of host ID -> Host
        storages: Dictionary of storage ID -> Storage

    Returns:
        TransferPlan with method and routing
    """
    hosts = hosts or {}
    storages = storages or {}

    def classify_endpoint(endpoint: TransferEndpoint) -> str:
        """Classify endpoint type."""
        if endpoint.storage_id:
            storage = storages.get(endpoint.storage_id)
            if storage:
                if storage.type in (StorageType.R2, StorageType.B2, StorageType.S3, StorageType.GOOGLE_DRIVE, StorageType.GCS):
                    return "cloud"
                elif storage.type in (StorageType.SSH, StorageType.SMB):
                    return "ssh"
        if endpoint.host_id:
            return "ssh"
        if endpoint.type == "local":
            return "local"
        return "unknown"

    src_type = classify_endpoint(source)
    dst_type = classify_endpoint(destination)

    # Both are SSH-based -> use rsync
    if src_type == "ssh" and dst_type == "ssh":
        # Need to check if direct connection is possible
        # For now, return direct and let transfer() handle connectivity check
        return TransferPlan(
            method="rsync",
            via="direct",
            description="SSH to SSH transfer via rsync"
        )

    # At least one side is cloud storage -> use rclone
    if src_type == "cloud" or dst_type == "cloud":
        return TransferPlan(
            method="rclone",
            via="cloud",
            description="Cloud storage transfer via rclone"
        )

    # Local to SSH or SSH to local -> rsync
    if (src_type == "local" and dst_type == "ssh") or (src_type == "ssh" and dst_type == "local"):
        return TransferPlan(
            method="rsync",
            via="local",
            description="Local to/from SSH via rsync"
        )

    # Local to local
    return TransferPlan(
        method="rsync",
        via="local",
        description="Local transfer via rsync"
    )


def rsync_with_progress(
    source: str,
    destination: str,
    host: Optional[Host] = None,
    upload: bool = True,
    delete: bool = False,
    exclude: Optional[List[str]] = None,
    progress_callback: Optional[Callable[[TransferProgress], None]] = None,
) -> TransferResult:
    """
    Transfer files using rsync with progress updates.

    Args:
        source: Source path
        destination: Destination path
        host: Remote host (for SSH transfers)
        upload: True for upload, False for download
        delete: Delete files on destination not in source
        exclude: Patterns to exclude
        progress_callback: Callback for progress updates

    Returns:
        TransferResult with status
    """
    args = ["rsync", "-avz", "--info=progress2"]

    if delete:
        args.append("--delete")

    for pattern in (exclude or []):
        args.extend(["--exclude", pattern])

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
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        bytes_transferred = 0
        total_bytes = 0

        for line in iter(process.stdout.readline, ""):
            if not line:
                break

            # Parse rsync --info=progress2 output
            # Format: "1,234,567  12%    1.23MB/s    0:01:23"
            progress = _parse_rsync_progress(line)
            if progress and progress_callback:
                progress_callback(progress)

            # Also parse "sent X bytes" line at the end
            match = re.search(r"sent ([\d,]+) bytes", line)
            if match:
                bytes_transferred = int(match.group(1).replace(",", ""))

        exit_code = process.wait()

        return TransferResult(
            success=exit_code == 0,
            exit_code=exit_code,
            message="Transfer complete" if exit_code == 0 else "Transfer failed",
            bytes_transferred=bytes_transferred,
        )
    except Exception as e:
        return TransferResult(
            success=False,
            exit_code=-1,
            message=str(e),
        )


def _parse_rsync_progress(line: str) -> Optional[TransferProgress]:
    """Parse rsync --info=progress2 output line."""
    # Example: "  1,234,567  12%    1.23MB/s    0:01:23"
    match = re.search(
        r"([\d,]+)\s+(\d+)%\s+([\d.]+\w+/s)\s+([\d:]+(?:\s+\(xfr.*\))?)",
        line
    )
    if match:
        bytes_str = match.group(1).replace(",", "")
        try:
            return TransferProgress(
                bytes_transferred=int(bytes_str),
                percent=float(match.group(2)),
                speed=match.group(3),
                eta=match.group(4).split("(")[0].strip(),
            )
        except ValueError:
            pass
    return None


def check_rsync_available() -> bool:
    """Check if rsync is installed."""
    try:
        subprocess.run(["rsync", "--version"], capture_output=True)
        return True
    except FileNotFoundError:
        return False


def check_rclone_available() -> bool:
    """Check if rclone is installed."""
    try:
        subprocess.run(["rclone", "version"], capture_output=True)
        return True
    except FileNotFoundError:
        return False

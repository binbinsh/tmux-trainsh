"""Shared transfer helpers and value types."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from ..constants import SecretKeys
from ..core.models import Host, Storage, StorageType, TransferEndpoint
from ..core.secrets import get_secrets_manager
from .secret_materialize import materialize_secret_file, resolve_resource_secret_name


def _split_ssh_target(target: str) -> tuple[str, str]:
    """Split a simple user@host target into user and host parts."""
    text = str(target or "").strip()
    if not text:
        return "", ""

    first_token = text.split(None, 1)[0]
    if "@" not in first_token:
        return "", text

    user, host = first_token.rsplit("@", 1)
    if not user or not host:
        return "", text
    return user.strip(), host.strip()


def resolve_storage_remote_path(storage: Storage, path: str) -> str:
    """Resolve a storage-relative path for rclone-style backends."""
    raw = str(path or "").strip()

    if storage.type == StorageType.SSH:
        base_path = str(storage.config.get("path", "")).strip()
        if not base_path:
            return raw
        relative = raw.lstrip("/")
        if not relative:
            return base_path
        return f"{base_path.rstrip('/')}/{relative}"

    relative = raw.lstrip("/")
    root = ""
    if storage.type in {StorageType.R2, StorageType.S3, StorageType.B2, StorageType.GCS}:
        root = str(storage.config.get("bucket", "")).strip().strip("/")
    elif storage.type == StorageType.SMB:
        root = str(storage.config.get("share", "")).strip().strip("/")

    if not root:
        return relative
    if not relative:
        return root
    if relative == root or relative.startswith(f"{root}/"):
        return relative
    return f"{root}/{relative}"


def build_rclone_env(storage: Storage, remote_name: Optional[str] = None) -> Dict[str, str]:
    """
    Build rclone environment variables for a storage backend.

    rclone supports dynamic remote configuration via environment variables:
    RCLONE_CONFIG_<remote>_TYPE=<type>
    RCLONE_CONFIG_<remote>_<option>=<value>

    This allows us to configure remotes without modifying ~/.config/rclone/rclone.conf

    Credentials are loaded in priority order:
    1. Storage-specific secrets: {STORAGE_NAME}_ACCESS_KEY_ID, etc.
    2. Global secrets: R2_ACCESS_KEY_ID, AWS_ACCESS_KEY_ID, etc.
    3. Config values stored in storage.config
    """
    resolved_remote_name = remote_name or get_rclone_remote_name(storage) or storage.name
    name = resolved_remote_name.upper().replace("-", "_").replace(" ", "_")
    storage_prefix = name
    secrets = get_secrets_manager()
    env: Dict[str, str] = {}
    config = storage.config

    def get_credential(
        storage_key: str,
        global_key: str,
        config_key: str = "",
        *,
        explicit_secret_names: tuple[str, ...] = (),
    ) -> str:
        for secret_name in explicit_secret_names:
            secret_name = str(secret_name or "").strip()
            if not secret_name:
                continue
            value = secrets.get(secret_name)
            if value:
                return value
        value = secrets.get(f"{storage_prefix}_{storage_key}")
        if value:
            return value
        value = secrets.get(global_key)
        if value:
            return value
        if config_key:
            return config.get(config_key, "")
        return ""

    if storage.type == StorageType.R2:
        env[f"RCLONE_CONFIG_{name}_TYPE"] = "s3"
        env[f"RCLONE_CONFIG_{name}_PROVIDER"] = "Cloudflare"
        env[f"RCLONE_CONFIG_{name}_ENV_AUTH"] = "false"

        account_id = get_credential("ACCOUNT_ID", SecretKeys.R2_ACCOUNT_ID, "account_id")
        access_key = get_credential("ACCESS_KEY_ID", SecretKeys.R2_ACCESS_KEY_ID, "access_key_id")
        secret_key = get_credential("SECRET_ACCESS_KEY", SecretKeys.R2_SECRET_ACCESS_KEY, "secret_access_key")

        if access_key:
            env[f"RCLONE_CONFIG_{name}_ACCESS_KEY_ID"] = access_key
        if secret_key:
            env[f"RCLONE_CONFIG_{name}_SECRET_ACCESS_KEY"] = secret_key

        endpoint = get_credential("ENDPOINT", "R2_ENDPOINT", "endpoint")
        if not endpoint and account_id:
            endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
        if endpoint:
            env[f"RCLONE_CONFIG_{name}_ENDPOINT"] = endpoint

    elif storage.type == StorageType.S3:
        env[f"RCLONE_CONFIG_{name}_TYPE"] = "s3"
        env[f"RCLONE_CONFIG_{name}_PROVIDER"] = config.get("provider", "AWS")
        env[f"RCLONE_CONFIG_{name}_ENV_AUTH"] = "false"

        access_key = get_credential(
            "ACCESS_KEY_ID",
            SecretKeys.AWS_ACCESS_KEY_ID,
            "access_key_id",
            explicit_secret_names=(str(config.get("access_key_secret", "")).strip(),),
        )
        secret_key = get_credential(
            "SECRET_ACCESS_KEY",
            SecretKeys.AWS_SECRET_ACCESS_KEY,
            "secret_access_key",
            explicit_secret_names=(str(config.get("secret_key_secret", "")).strip(),),
        )

        if access_key:
            env[f"RCLONE_CONFIG_{name}_ACCESS_KEY_ID"] = access_key
        if secret_key:
            env[f"RCLONE_CONFIG_{name}_SECRET_ACCESS_KEY"] = secret_key
        if config.get("region"):
            env[f"RCLONE_CONFIG_{name}_REGION"] = config["region"]
        if config.get("endpoint"):
            env[f"RCLONE_CONFIG_{name}_ENDPOINT"] = config["endpoint"]

    elif storage.type == StorageType.B2:
        env[f"RCLONE_CONFIG_{name}_TYPE"] = "b2"

        key_id = get_credential("APPLICATION_KEY_ID", SecretKeys.B2_APPLICATION_KEY_ID, "application_key_id")
        app_key = get_credential("APPLICATION_KEY", SecretKeys.B2_APPLICATION_KEY, "application_key")

        if key_id:
            env[f"RCLONE_CONFIG_{name}_ACCOUNT"] = key_id
        if app_key:
            env[f"RCLONE_CONFIG_{name}_KEY"] = app_key

    elif storage.type == StorageType.GOOGLE_DRIVE:
        env[f"RCLONE_CONFIG_{name}_TYPE"] = "drive"
        if config.get("client_id"):
            env[f"RCLONE_CONFIG_{name}_CLIENT_ID"] = config["client_id"]
        if config.get("client_secret"):
            env[f"RCLONE_CONFIG_{name}_CLIENT_SECRET"] = config["client_secret"]
        if config.get("root_folder_id"):
            env[f"RCLONE_CONFIG_{name}_ROOT_FOLDER_ID"] = config["root_folder_id"]

        token = get_credential(
            "TOKEN",
            SecretKeys.GOOGLE_DRIVE_CREDENTIALS,
            "token",
            explicit_secret_names=(str(config.get("token_secret", "")).strip(),),
        )
        if token:
            env[f"RCLONE_CONFIG_{name}_TOKEN"] = token

        if config.get("remote_name") and not any(env):
            return {}

    elif storage.type == StorageType.GCS:
        env[f"RCLONE_CONFIG_{name}_TYPE"] = "google cloud storage"
        if config.get("project_id"):
            env[f"RCLONE_CONFIG_{name}_PROJECT_NUMBER"] = config["project_id"]
        service_account_json = get_credential(
            "SERVICE_ACCOUNT_JSON",
            "GCS_SERVICE_ACCOUNT_JSON",
            "service_account_json",
            explicit_secret_names=(resolve_resource_secret_name(storage.name, config.get("service_account_secret"), "SERVICE_ACCOUNT_JSON"),),
        )
        if service_account_json:
            env[f"RCLONE_CONFIG_{name}_SERVICE_ACCOUNT_CREDENTIALS"] = service_account_json
        if config.get("bucket"):
            env[f"RCLONE_CONFIG_{name}_BUCKET_POLICY_ONLY"] = "true"

    elif storage.type == StorageType.SSH:
        env[f"RCLONE_CONFIG_{name}_TYPE"] = "sftp"
        host_value = str(config.get("host") or config.get("hostname") or "").strip()
        parsed_user, parsed_host = _split_ssh_target(host_value)
        host_name = parsed_host or host_value
        user_name = str(config.get("user") or config.get("username") or parsed_user).strip()
        if host_name:
            env[f"RCLONE_CONFIG_{name}_HOST"] = host_name
        if user_name:
            env[f"RCLONE_CONFIG_{name}_USER"] = user_name
        if config.get("port"):
            env[f"RCLONE_CONFIG_{name}_PORT"] = str(config["port"])
        key_secret = resolve_resource_secret_name(storage.name, config.get("key_secret"), "SSH_PRIVATE_KEY")
        key_file = materialize_secret_file(key_secret, suffix=".key") or ""
        if not key_file:
            key_file = str(config.get("key_file") or config.get("key_path") or "").strip()
        if key_file:
            env[f"RCLONE_CONFIG_{name}_KEY_FILE"] = os.path.expanduser(key_file)
        password = get_credential(
            "PASSWORD",
            "SSH_PASSWORD",
            "password",
            explicit_secret_names=(str(config.get("password_secret", "")).strip(),),
        )
        if password:
            env[f"RCLONE_CONFIG_{name}_PASS"] = password

    elif storage.type == StorageType.SMB:
        env[f"RCLONE_CONFIG_{name}_TYPE"] = "smb"
        host_name = str(config.get("host") or config.get("server") or "").strip()
        user_name = str(config.get("user") or config.get("username") or "").strip()
        password = get_credential(
            "PASSWORD",
            "SMB_PASSWORD",
            "password",
            explicit_secret_names=(str(config.get("password_secret", "")).strip(),),
        )
        if not password:
            password = str(config.get("pass") or config.get("password") or "").strip()
        if host_name:
            env[f"RCLONE_CONFIG_{name}_HOST"] = host_name
        if user_name:
            env[f"RCLONE_CONFIG_{name}_USER"] = user_name
        if password:
            env[f"RCLONE_CONFIG_{name}_PASS"] = password
        if config.get("domain"):
            env[f"RCLONE_CONFIG_{name}_DOMAIN"] = config["domain"]

    return env


def get_rclone_remote_name(storage: Storage) -> str:
    """Get the rclone remote name for a storage."""
    if storage.type == StorageType.GOOGLE_DRIVE:
        remote_name = storage.config.get("remote_name")
        if remote_name:
            return remote_name
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


class TransferPlan:
    """Plan for how a transfer will be executed."""

    def __init__(self, method: str, via: str, description: str = ""):
        self.method = method
        self.via = via
        self.description = description

    def __repr__(self) -> str:
        return f"TransferPlan(method={self.method}, via={self.via})"


def analyze_transfer(
    source: TransferEndpoint,
    destination: TransferEndpoint,
    hosts: dict[str, Host] = None,
    storages: dict[str, Storage] = None,
) -> TransferPlan:
    """Analyze endpoints and determine optimal transfer method."""
    hosts = hosts or {}
    storages = storages or {}

    def classify_endpoint(endpoint: TransferEndpoint) -> str:
        if endpoint.storage_id:
            storage = storages.get(endpoint.storage_id)
            if storage:
                if storage.type in (
                    StorageType.R2,
                    StorageType.B2,
                    StorageType.S3,
                    StorageType.GOOGLE_DRIVE,
                    StorageType.GCS,
                ):
                    return "cloud"
                if storage.type in (StorageType.SSH, StorageType.SMB):
                    return "ssh"
        if endpoint.host_id:
            return "ssh"
        if endpoint.type == "local":
            return "local"
        return "unknown"

    src_type = classify_endpoint(source)
    dst_type = classify_endpoint(destination)

    if src_type == "ssh" and dst_type == "ssh":
        return TransferPlan(method="rsync", via="direct", description="SSH to SSH transfer via rsync")
    if src_type == "cloud" or dst_type == "cloud":
        return TransferPlan(method="rclone", via="cloud", description="Cloud storage transfer via rclone")
    if (src_type == "local" and dst_type == "ssh") or (src_type == "ssh" and dst_type == "local"):
        return TransferPlan(method="rsync", via="local", description="Local to/from SSH via rsync")
    return TransferPlan(method="rsync", via="local", description="Local transfer via rsync")


def rsync_with_progress(
    source: str,
    destination: str,
    host: Optional[Host] = None,
    upload: bool = True,
    delete: bool = False,
    exclude: Optional[list[str]] = None,
    progress_callback: Optional[Callable[[TransferProgress], None]] = None,
) -> TransferResult:
    """Transfer files using rsync with progress updates."""
    args = ["rsync", "-avz", "--info=progress2"]

    if delete:
        args.append("--delete")

    for pattern in (exclude or []):
        args.extend(["--exclude", pattern])

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

        for line in iter(process.stdout.readline, ""):
            if not line:
                break

            progress = _parse_rsync_progress(line)
            if progress and progress_callback:
                progress_callback(progress)

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
    except Exception as exc:
        return TransferResult(success=False, exit_code=-1, message=str(exc))


def _parse_rsync_progress(line: str) -> Optional[TransferProgress]:
    """Parse rsync --info=progress2 output line."""
    match = re.search(
        r"([\d,]+)\s+(\d+)%\s+([\d.]+\w+/s)\s+([\d:]+(?:\s+\(xfr.*\))?)",
        line,
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

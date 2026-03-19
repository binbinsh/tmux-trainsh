# tmux-trainsh storage command
# Storage backend management

import sys
import getpass
from typing import Optional, List

from ..cli_utils import SubcommandSpec, dispatch_subcommand, prompt_input
from .help_catalog import render_command_help
from .help_cmd import reject_subcommand_help

SUBCOMMAND_SPECS = (
    SubcommandSpec("list", "List configured storage backends."),
    SubcommandSpec("add", "Add a storage backend interactively."),
    SubcommandSpec("show", "Inspect one backend's configuration."),
    SubcommandSpec("check", "Check connectivity for one backend."),
    SubcommandSpec("remove", "Delete a stored backend."),
)

usage = render_command_help("storage")


def _suggest_secret_name(storage_name: str, suffix: str) -> str:
    from ..services.secret_materialize import suggest_secret_name

    return suggest_secret_name(storage_name, suffix)


def _store_secret_value(secret_name: str, value: str) -> None:
    from ..core.secrets import get_secrets_manager

    get_secrets_manager().set(secret_name, value)


def _store_secret_file(secret_name: str, path: str) -> None:
    from ..services.secret_materialize import store_secret_file

    store_secret_file(secret_name, path)


def _yes(value: str) -> bool:
    return str(value or "").strip().lower() in {"", "y", "yes"}


def _prompt_store_now(prompt_text: str = "Store credentials in train secrets now? (Y/n): ") -> Optional[bool]:
    choice = prompt_input(prompt_text, default="Y")
    if choice is None:
        return None
    return _yes(choice)


def _prompt_secret(secret_prompt: str) -> Optional[str]:
    try:
        value = getpass.getpass(secret_prompt)
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return None
    value = value.strip()
    if not value:
        print("Cancelled - no value provided.")
        return None
    return value


def load_storages() -> dict:
    """Load storages from configuration."""
    from ..constants import STORAGES_FILE
    import yaml

    if not STORAGES_FILE.exists():
        return {}

    with open(STORAGES_FILE, "r") as f:
        data = yaml.safe_load(f) or {}

    storages = {}
    for storage_data in data.get("storages", []):
        from ..core.models import Storage
        storage = Storage.from_dict(storage_data)
        storages[storage.name or storage.id] = storage

    return storages


def _storage_to_dict(storage) -> dict:
    """Convert a storage to a filtered dict (no None values)."""
    return {k: v for k, v in storage.to_dict().items() if v is not None}


def save_storages(storages: dict) -> None:
    """Save storages to configuration."""
    from ..constants import STORAGES_FILE, CONFIG_DIR
    import yaml

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    data = {"storages": [_storage_to_dict(s) for s in storages.values()]}

    with open(STORAGES_FILE, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def cmd_list(args: List[str]) -> None:
    """List configured storage backends."""
    storages = load_storages()

    if not storages:
        print("No storage backends configured.")
        print("Use 'train storage add' to add one.")
        return

    print("Configured storage backends:")
    print("-" * 50)

    for name, storage in storages.items():
        default_mark = " (default)" if storage.is_default else ""
        print(f"  {name:<20} {storage.type.value}{default_mark}")

    print("-" * 50)
    print(f"Total: {len(storages)} backends")


def cmd_add(args: List[str]) -> None:
    """Add a new storage backend interactively."""
    from ..core.models import Storage, StorageType

    print("Add new storage backend")
    print("-" * 40)

    name = prompt_input("Storage name: ")
    if name is None:
        return
    if not name:
        print("Cancelled - name is required.")
        return

    print("\nStorage type:")
    print("  1. Local filesystem")
    print("  2. SSH/SFTP")
    print("  3. Google Drive")
    print("  4. Cloudflare R2")
    print("  5. Backblaze B2")
    print("  6. Amazon S3")
    print("  7. Google Cloud Storage")
    print("  8. SMB/CIFS")
    type_choice = prompt_input("Choice [1]: ", default="1")
    if type_choice is None:
        return

    type_map = {
        "1": StorageType.LOCAL,
        "2": StorageType.SSH,
        "3": StorageType.GOOGLE_DRIVE,
        "4": StorageType.R2,
        "5": StorageType.B2,
        "6": StorageType.S3,
        "7": StorageType.GCS,
        "8": StorageType.SMB,
    }
    storage_type = type_map.get(type_choice, StorageType.LOCAL)

    config = {}

    if storage_type == StorageType.LOCAL:
        path = prompt_input("Base path: ")
        if path is None:
            return
        config["path"] = path

    elif storage_type == StorageType.SSH:
        host = prompt_input("Host: ")
        if host is None:
            return
        path = prompt_input("Base path: ")
        if path is None:
            return
        print("\nSSH auth:")
        print("  1. Private key (default)")
        print("  2. Password")
        auth_choice = prompt_input("Choice [1]: ", default="1")
        if auth_choice is None:
            return
        config["host"] = host
        config["path"] = path
        if str(auth_choice).strip() == "2":
            store_now = _prompt_store_now("Store SSH password in train secrets now? (Y/n): ")
            if store_now is None:
                return
            if store_now:
                password = _prompt_secret("SSH password: ")
                if password is None:
                    return
                secret_name = _suggest_secret_name(name, "PASSWORD")
                _store_secret_value(secret_name, password)
                config.pop("password_secret", None)
                print("Stored SSH password in train secrets.")
            else:
                print("You can set it later with train secrets.")
        else:
            key_path = prompt_input(
                "SSH key path [~/.ssh/id_rsa] (or type 'secret' to import into train secrets): ",
                default="~/.ssh/id_rsa",
            )
            if key_path is None:
                return
            key_path = key_path.strip() or "~/.ssh/id_rsa"
            if key_path.lower() == "secret":
                import_path = prompt_input("Private key file to import [~/.ssh/id_rsa]: ", default="~/.ssh/id_rsa")
                if import_path is None:
                    return
                import_path = import_path.strip() or "~/.ssh/id_rsa"
                secret_name = _suggest_secret_name(name, "SSH_PRIVATE_KEY")
                try:
                    _store_secret_file(secret_name, import_path)
                except Exception as exc:
                    print(f"Failed to import SSH key into secrets: {exc}")
                    return
                config.pop("key_secret", None)
                print("Stored SSH private key in train secrets.")
            else:
                config["key_path"] = key_path

    elif storage_type == StorageType.GOOGLE_DRIVE:
        print("\nGoogle Drive requires OAuth setup.")
        print("Run 'rclone config' to set up Google Drive, then enter the rclone remote name.")
        remote_name = prompt_input("Rclone remote name: ")
        if remote_name is None:
            return
        config["remote_name"] = remote_name

    elif storage_type == StorageType.R2:
        account_id = prompt_input("Cloudflare Account ID: ")
        if account_id is None:
            return
        bucket = prompt_input("Bucket name: ")
        if bucket is None:
            return
        config["account_id"] = account_id
        config["bucket"] = bucket
        config["endpoint"] = f"https://{account_id}.r2.cloudflarestorage.com"
        store_now = _prompt_store_now()
        if store_now is None:
            return
        if store_now:
            access_key_id = _prompt_secret("R2 Access Key ID: ")
            if access_key_id is None:
                return
            secret_access_key = _prompt_secret("R2 Secret Access Key: ")
            if secret_access_key is None:
                return
            from ..core.secrets import get_secrets_manager

            bundle_name = _suggest_secret_name(name, "R2_CREDENTIALS")
            get_secrets_manager().set_bundle(
                bundle_name,
                {
                    "account_id": account_id.strip(),
                    "access_key_id": access_key_id,
                    "secret_access_key": secret_access_key,
                },
            )
            print("Stored R2 credentials in train secrets.")
        else:
            print("You can set R2 credentials later with train secrets.")

    elif storage_type == StorageType.B2:
        bucket = prompt_input("Bucket name: ")
        if bucket is None:
            return
        config["bucket"] = bucket
        store_now = _prompt_store_now()
        if store_now is None:
            return
        if store_now:
            key_id = _prompt_secret("B2 Application Key ID: ")
            if key_id is None:
                return
            app_key = _prompt_secret("B2 Application Key: ")
            if app_key is None:
                return
            from ..core.secrets import get_secrets_manager

            bundle_name = _suggest_secret_name(name, "B2_CREDENTIALS")
            get_secrets_manager().set_bundle(
                bundle_name,
                {
                    "application_key_id": key_id,
                    "application_key": app_key,
                },
            )
            print("Stored B2 credentials in train secrets.")
        else:
            print("You can set B2 credentials later with train secrets.")

    elif storage_type == StorageType.S3:
        bucket = prompt_input("Bucket name: ")
        if bucket is None:
            return
        region = prompt_input("Region [us-east-1]: ", default="us-east-1")
        if region is None:
            return
        endpoint = prompt_input("Custom endpoint (optional, for S3-compatible): ")
        if endpoint is None:
            return
        config["bucket"] = bucket
        config["region"] = region
        if endpoint:
            config["endpoint"] = endpoint
        store_now = _prompt_store_now()
        if store_now is None:
            return
        if store_now:
            access_key_id = _prompt_secret("S3 Access Key ID: ")
            if access_key_id is None:
                return
            secret_access_key = _prompt_secret("S3 Secret Access Key: ")
            if secret_access_key is None:
                return
            access_name = _suggest_secret_name(name, "S3_ACCESS_KEY_ID")
            secret_name = _suggest_secret_name(name, "S3_SECRET_ACCESS_KEY")
            _store_secret_value(access_name, access_key_id)
            _store_secret_value(secret_name, secret_access_key)
            config.pop("access_key_secret", None)
            config.pop("secret_key_secret", None)
            print("Stored S3 credentials in train secrets.")
        else:
            print("You can set S3 credentials later with train secrets.")

    elif storage_type == StorageType.GCS:
        bucket = prompt_input("Bucket name: ")
        if bucket is None:
            return
        config["bucket"] = bucket
        project_id = prompt_input("Project ID (optional): ", default="")
        if project_id is None:
            return
        project_id = project_id.strip()
        if project_id:
            config["project_id"] = project_id
        store_now = _prompt_store_now("Import a GCS service account JSON into train secrets now? (Y/n): ")
        if store_now is None:
            return
        if store_now:
            json_path = prompt_input("Service account JSON file path: ")
            if json_path is None:
                return
            json_path = json_path.strip()
            if not json_path:
                print("Cancelled - service account JSON path is required.")
                return
            secret_name = _suggest_secret_name(name, "SERVICE_ACCOUNT_JSON")
            try:
                _store_secret_file(secret_name, json_path)
            except Exception as exc:
                print(f"Failed to import GCS service account JSON: {exc}")
                return
            config.pop("service_account_secret", None)
            print("Stored GCS service account JSON in train secrets.")
        else:
            print("You can set the GCS service account later with train secrets.")

    elif storage_type == StorageType.SMB:
        server = prompt_input("Server: ")
        if server is None:
            return
        share = prompt_input("Share name: ")
        if share is None:
            return
        username = prompt_input("Username: ")
        if username is None:
            return
        config["server"] = server
        config["share"] = share
        config["username"] = username
        store_now = _prompt_store_now("Store SMB password in train secrets now? (Y/n): ")
        if store_now is None:
            return
        if store_now:
            password = _prompt_secret("SMB password: ")
            if password is None:
                return
            secret_name = _suggest_secret_name(name, "PASSWORD")
            _store_secret_value(secret_name, password)
            config.pop("password_secret", None)
            print("Stored SMB password in train secrets.")
        else:
            print("You can set the SMB password later with train secrets.")

    default_choice = prompt_input("\nSet as default? (y/N): ")
    if default_choice is None:
        return
    is_default = default_choice.lower() == "y"

    storage = Storage(
        name=name,
        type=storage_type,
        config=config,
        is_default=is_default,
    )

    storages = load_storages()

    # If setting as default, unset other defaults
    if is_default:
        for s in storages.values():
            s.is_default = False

    storages[name] = storage
    save_storages(storages)

    print(f"\nAdded storage: {name} ({storage_type.value})")


def cmd_show(args: List[str]) -> None:
    """Show storage details."""
    from ..core.secrets import get_secrets_manager
    from ..core.models import StorageType
    from ..services.secret_materialize import resolve_resource_secret_name

    if not args:
        print("Usage: train storage show <name>")
        sys.exit(1)

    name = args[0]
    storages = load_storages()

    if name not in storages:
        print(f"Storage not found: {name}")
        sys.exit(1)

    storage = storages[name]
    print(f"Storage: {storage.name}")
    print(f"  Type: {storage.type.value}")
    print(f"  Default: {'Yes' if storage.is_default else 'No'}")
    print(f"  Config:")
    for k, v in storage.config.items():
        if str(k).endswith("_secret"):
            continue
        print(f"    {k}: {v}")

    secrets = get_secrets_manager()
    managed = []
    if storage.type == StorageType.R2 and secrets.exists(_suggest_secret_name(storage.name, "R2_CREDENTIALS")):
        managed.append("R2 credentials")
    elif storage.type == StorageType.B2 and secrets.exists(_suggest_secret_name(storage.name, "B2_CREDENTIALS")):
        managed.append("B2 credentials")
    elif storage.type == StorageType.S3:
        if secrets.exists(resolve_resource_secret_name(storage.name, storage.config.get("access_key_secret"), "ACCESS_KEY_ID")):
            managed.append("S3 access key")
        if secrets.exists(resolve_resource_secret_name(storage.name, storage.config.get("secret_key_secret"), "SECRET_ACCESS_KEY")):
            managed.append("S3 secret key")
    elif storage.type == StorageType.GCS and secrets.exists(
        resolve_resource_secret_name(storage.name, storage.config.get("service_account_secret"), "SERVICE_ACCOUNT_JSON")
    ):
        managed.append("GCS service account")
    elif storage.type == StorageType.SSH:
        if secrets.exists(resolve_resource_secret_name(storage.name, storage.config.get("key_secret"), "SSH_PRIVATE_KEY")):
            managed.append("SSH private key")
        if secrets.exists(resolve_resource_secret_name(storage.name, storage.config.get("password_secret"), "PASSWORD")):
            managed.append("SSH password")
    elif storage.type == StorageType.SMB and secrets.exists(
        resolve_resource_secret_name(storage.name, storage.config.get("password_secret"), "PASSWORD")
    ):
        managed.append("SMB password")

    if managed:
        print("  Managed secrets:")
        for item in managed:
            print(f"    {item}")


def cmd_rm(args: List[str]) -> None:
    """Remove a storage backend."""
    if not args:
        print("Usage: train storage remove <name>")
        sys.exit(1)

    name = args[0]
    storages = load_storages()

    if name not in storages:
        print(f"Storage not found: {name}")
        sys.exit(1)

    confirm = prompt_input(f"Remove storage '{name}'? (y/N): ")
    if confirm is None or confirm.lower() != "y":
        print("Cancelled.")
        return

    del storages[name]
    save_storages(storages)
    print(f"Storage removed: {name}")


def cmd_test(args: List[str]) -> None:
    """Test connection to storage."""
    if not args:
        print("Usage: train storage check <name>")
        sys.exit(1)

    name = args[0]
    storages = load_storages()

    if name not in storages:
        print(f"Storage not found: {name}")
        sys.exit(1)

    storage = storages[name]
    print(f"Testing storage: {name} ({storage.type.value})...")

    from ..services.transfer_engine import (
        check_rclone_available,
        build_rclone_env,
        get_rclone_remote_name,
    )
    from ..services.transfer_support import resolve_storage_remote_path

    if storage.type.value in ("gdrive", "r2", "b2", "s3", "gcs", "smb"):
        if not check_rclone_available():
            print("Error: rclone is required but not installed.")
            print("Install with: brew install rclone")
            sys.exit(1)

        # Build environment with storage credentials
        import os
        import subprocess
        env = os.environ.copy()
        rclone_env = build_rclone_env(storage)
        env.update(rclone_env)

        # Get the correct remote name
        remote_name = get_rclone_remote_name(storage)
        remote_path = resolve_storage_remote_path(storage, "")
        rclone_path = f"{remote_name}:{remote_path}" if remote_path else f"{remote_name}:"

        print(f"  Using rclone remote: {rclone_path}")
        if rclone_env:
            print(f"  Auto-configured with {len(rclone_env)} environment variables")

        # Try to list the remote
        result = subprocess.run(
            ["rclone", "lsd", rclone_path],
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode == 0:
            print("Connection successful!")
            # Show some output if available
            if result.stdout.strip():
                lines = result.stdout.strip().split('\n')[:5]
                for line in lines:
                    print(f"  {line}")
                if len(result.stdout.strip().split('\n')) > 5:
                    print("  ...")
        else:
            print(f"Connection failed: {result.stderr}")
            sys.exit(1)
    elif storage.type.value == "ssh":
        # Test SSH connection
        host_spec = str(storage.config.get("host") or storage.config.get("hostname") or "").strip()
        user = str(storage.config.get("user") or storage.config.get("username") or "").strip()
        if not host_spec:
            print("Error: No host configured for SSH storage.")
            sys.exit(1)

        from ..core.models import AuthMethod, Host, HostType
        from ..core.secrets import get_secrets_manager
        from ..services.ssh import SSHClient
        from ..services.secret_materialize import resolve_resource_secret_name
        from ..services.transfer_support import _split_ssh_target

        parsed_user, parsed_host = _split_ssh_target(host_spec)
        password_secret_name = resolve_resource_secret_name(storage.name, storage.config.get("password_secret"), "PASSWORD")
        key_secret_name = resolve_resource_secret_name(storage.name, storage.config.get("key_secret"), "SSH_PRIVATE_KEY")
        auth_method = AuthMethod.PASSWORD if (storage.config.get("password") or get_secrets_manager().exists(password_secret_name)) else AuthMethod.KEY
        host = Host(
            name=storage.name,
            type=HostType.SSH,
            hostname=parsed_host or host_spec,
            port=int(storage.config.get("port", 22) or 22),
            username=user or parsed_user,
            auth_method=auth_method,
            ssh_key_path=str(storage.config.get("key_file") or storage.config.get("key_path") or "").strip() or None,
            env_vars={},
        )
        host.env_vars["ssh_key_secret"] = key_secret_name
        host.env_vars["ssh_password_secret"] = password_secret_name

        client = SSHClient.from_host(host)
        result = client.run("echo ok", timeout=10)
        exit_code = getattr(result, "exit_code", getattr(result, "returncode", 1))
        if exit_code == 0 and "ok" in result.stdout:
            print("Connection successful!")
        else:
            print(f"Connection failed: {result.stderr or result.stdout}")
            sys.exit(1)
    elif storage.type.value == "local":
        import os
        path = storage.config.get("path", "")
        if path and os.path.isdir(os.path.expanduser(path)):
            print("Connection successful!")
        else:
            print(f"Path not found: {path}")
            sys.exit(1)
    else:
        print("Connection test not implemented for this storage type.")


def main(args: List[str]) -> Optional[str]:
    """Main entry point for storage command."""
    if not args:
        print(usage)
        return None
    if args[0] in ("-h", "--help", "help"):
        reject_subcommand_help()

    subcommand = args[0]
    subargs = args[1:]

    commands = {
        "list": cmd_list,
        "add": cmd_add,
        "show": cmd_show,
        "check": cmd_test,
        "remove": cmd_rm,
    }

    try:
        handler = dispatch_subcommand(subcommand, commands=commands)
    except KeyError:
        print(f"Unknown subcommand: {subcommand}")
        print(usage)
        sys.exit(1)

    handler(subargs)
    return None


if __name__ == "__main__":
    main(sys.argv[1:])
elif __name__ == "__doc__":
    cd = sys.cli_docs  # type: ignore
    cd["usage"] = usage
    cd["help_text"] = "Storage backend management"
    cd["short_desc"] = "Manage storage backends"

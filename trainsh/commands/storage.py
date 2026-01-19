# tmux-trainsh storage command
# Storage backend management

import sys
from typing import Optional, List

from ..cli_utils import prompt_input

usage = '''[subcommand] [args...]

Subcommands:
  list             - List configured storage backends
  add              - Add a new storage backend
  show <name>      - Show storage details
  rm <name>        - Remove a storage backend
  test <name>      - Test connection to storage

Supported storage types:
  - local          Local filesystem
  - ssh            SSH/SFTP
  - gdrive         Google Drive
  - r2             Cloudflare R2
  - b2             Backblaze B2
  - s3             Amazon S3 (or compatible)
  - gcs            Google Cloud Storage
  - smb            SMB/CIFS

Storages are stored in: ~/.config/tmux-trainsh/storages.toml
'''


def load_storages() -> dict:
    """Load storages from configuration."""
    from ..constants import STORAGES_FILE
    import tomllib

    if not STORAGES_FILE.exists():
        return {}

    with open(STORAGES_FILE, "rb") as f:
        data = tomllib.load(f)

    storages = {}
    for storage_data in data.get("storages", []):
        from ..core.models import Storage
        storage = Storage.from_dict(storage_data)
        storages[storage.name or storage.id] = storage

    return storages


def _storage_to_toml(storage) -> str:
    """Convert a storage to TOML table format."""
    lines = ["[[storages]]"]
    d = storage.to_dict()

    # First output all non-dict top-level attributes
    for key, value in d.items():
        if value is None or isinstance(value, dict):
            continue
        if isinstance(value, bool):
            lines.append(f'{key} = {"true" if value else "false"}')
        elif isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        elif isinstance(value, (int, float)):
            lines.append(f'{key} = {value}')

    # Then handle nested config dict (exclude is_default if present)
    config = d.get("config", {})
    if config:
        lines.append(f"[storages.config]")
        for k, v in config.items():
            # Skip is_default in config - it's a top-level attribute
            if k == "is_default":
                continue
            if v is None:
                continue
            if isinstance(v, str):
                lines.append(f'{k} = "{v}"')
            elif isinstance(v, bool):
                lines.append(f'{k} = {"true" if v else "false"}')
            else:
                lines.append(f'{k} = {v}')

    return "\n".join(lines)


def save_storages(storages: dict) -> None:
    """Save storages to configuration."""
    from ..constants import STORAGES_FILE, CONFIG_DIR

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    toml_lines = []
    for storage in storages.values():
        toml_lines.append(_storage_to_toml(storage))
        toml_lines.append("")

    with open(STORAGES_FILE, "w") as f:
        f.write("\n".join(toml_lines))


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
        key_path = prompt_input("SSH key path [~/.ssh/id_rsa]: ", default="~/.ssh/id_rsa")
        if key_path is None:
            return
        config["host"] = host
        config["path"] = path
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
        print("\nCredentials will be automatically loaded from secrets.")
        print(f"Option 1: Storage-specific - 'train secrets set {name.upper()}_ACCESS_KEY' and '{name.upper()}_SECRET_KEY'")
        print("Option 2: Global - 'train secrets set R2_ACCESS_KEY' and 'R2_SECRET_KEY'")
        print("(Storage-specific credentials take priority over global ones)")
        config["account_id"] = account_id
        config["bucket"] = bucket
        config["endpoint"] = f"https://{account_id}.r2.cloudflarestorage.com"

    elif storage_type == StorageType.B2:
        bucket = prompt_input("Bucket name: ")
        if bucket is None:
            return
        print("\nCredentials will be automatically loaded from secrets.")
        print(f"Option 1: Storage-specific - 'train secrets set {name.upper()}_KEY_ID' and '{name.upper()}_APPLICATION_KEY'")
        print("Option 2: Global - 'train secrets set B2_KEY_ID' and 'B2_APPLICATION_KEY'")
        config["bucket"] = bucket

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
        print("\nCredentials will be automatically loaded from secrets.")
        print(f"Option 1: Storage-specific - 'train secrets set {name.upper()}_ACCESS_KEY_ID' and '{name.upper()}_SECRET_ACCESS_KEY'")
        print("Option 2: Global - 'train secrets set AWS_ACCESS_KEY_ID' and 'AWS_SECRET_ACCESS_KEY'")
        config["bucket"] = bucket
        config["region"] = region
        if endpoint:
            config["endpoint"] = endpoint

    elif storage_type == StorageType.GCS:
        bucket = prompt_input("Bucket name: ")
        if bucket is None:
            return
        config["bucket"] = bucket

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
        print(f"    {k}: {v}")


def cmd_rm(args: List[str]) -> None:
    """Remove a storage backend."""
    if not args:
        print("Usage: train storage rm <name>")
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
        print("Usage: train storage test <name>")
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

    if storage.type.value in ("gdrive", "r2", "b2", "s3", "gcs"):
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

        # For R2/S3/B2, also need to specify the bucket
        bucket = storage.config.get("bucket", "")
        if bucket:
            rclone_path = f"{remote_name}:{bucket}"
        else:
            rclone_path = f"{remote_name}:"

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
        import subprocess
        host = storage.config.get("host", "")
        if not host:
            print("Error: No host configured for SSH storage.")
            sys.exit(1)
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, "echo", "ok"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and "ok" in result.stdout:
            print("Connection successful!")
        else:
            print(f"Connection failed: {result.stderr}")
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
    if not args or args[0] in ("-h", "--help", "help"):
        print(usage)
        return None

    subcommand = args[0]
    subargs = args[1:]

    commands = {
        "list": cmd_list,
        "add": cmd_add,
        "show": cmd_show,
        "rm": cmd_rm,
        "test": cmd_test,
    }

    if subcommand not in commands:
        print(f"Unknown subcommand: {subcommand}")
        print(usage)
        sys.exit(1)

    commands[subcommand](subargs)
    return None


if __name__ == "__main__":
    main(sys.argv[1:])
elif __name__ == "__doc__":
    cd = sys.cli_docs  # type: ignore
    cd["usage"] = usage
    cd["help_text"] = "Storage backend management"
    cd["short_desc"] = "Manage storage backends"

# tmux-trainsh transfer command
# File transfer between hosts and storage

import sys
from typing import Optional, List

from ..cli_utils import render_command_help
from ..services.transfer_support import resolve_storage_remote_path

usage = render_command_help(
    command="train transfer",
    summary="Copy files between local paths, named hosts, and storage backends.",
    usage_lines=("train transfer <source> <destination> [options]",),
    options=(
        "--delete, -d        Delete files at destination that do not exist in the source.",
        "--exclude, -e PAT   Exclude a glob pattern. Repeat to add more patterns.",
        "--dry-run           Show what would change without transferring files.",
    ),
    notes=(
        "Endpoint forms: local path, @host:/remote/path, host:<name>:/remote/path, storage:<name>:/bucket/path.",
        "Use train host list and train storage list to discover available endpoint names.",
        "Host <-> cloud storage transfers relay through a local temp directory.",
        "Dry runs work for direct rsync/rclone paths; relayed transfer paths fail fast instead of executing.",
    ),
    examples=(
        "train transfer ./artifacts @gpu:/workspace/out",
        "train transfer @gpu:/workspace/checkpoints ./checkpoints",
        "train transfer ./data storage:artifacts:/datasets/run-01",
    ),
)


def parse_endpoint(spec: str) -> tuple[str, str, Optional[str]]:
    """
    Parse an endpoint specification.

    Format: [type:]path or host:name:path

    Returns:
        (type, path, host_or_storage_id)
    """
    if spec.startswith("@"):
        parts = spec[1:].split(":", 1)
        if len(parts) == 2 and parts[0]:
            return ("host", parts[1], parts[0])
        return ("local", spec, None)
    if spec.startswith("host:"):
        # host:name:path format
        parts = spec[5:].split(":", 1)
        if len(parts) == 2:
            return ("host", parts[1], parts[0])
        return ("host", parts[0], None)
    elif spec.startswith("storage:"):
        # storage:name:path format
        parts = spec[8:].split(":", 1)
        if len(parts) == 2:
            return ("storage", parts[1], parts[0])
        return ("storage", parts[0], None)
    else:
        # Local path
        return ("local", spec, None)


def main(args: List[str]) -> Optional[str]:
    """Main entry point for transfer command."""
    if not args or args[0] in ("-h", "--help", "help"):
        print(usage)
        return None

    # Parse arguments
    delete = False
    exclude = []
    dry_run = False

    i = 0
    positional = []

    while i < len(args):
        arg = args[i]

        if arg in ("-d", "--delete"):
            delete = True
            i += 1
        elif arg in ("-e", "--exclude"):
            if i + 1 >= len(args):
                print("Missing value for --exclude.")
                print(usage)
                sys.exit(1)
            exclude.append(args[i + 1])
            i += 2
        elif arg == "--dry-run":
            dry_run = True
            i += 1
        elif not arg.startswith("-"):
            positional.append(arg)
            i += 1
        else:
            print(f"Unknown option: {arg}")
            print(usage)
            sys.exit(1)

    if len(positional) < 2:
        print("Error: Both source and destination are required.")
        print(usage)
        sys.exit(1)
    if len(positional) > 2:
        print(f"Unexpected extra arguments: {' '.join(positional[2:])}")
        print(usage)
        sys.exit(1)

    source_spec = positional[0]
    dest_spec = positional[1]

    # Parse endpoints
    src_type, src_path, src_id = parse_endpoint(source_spec)
    dst_type, dst_path, dst_id = parse_endpoint(dest_spec)

    from ..core.models import TransferEndpoint
    from ..services.transfer_engine import TransferEngine

    src_endpoint = TransferEndpoint(
        type=src_type,
        path=src_path,
        host_id=src_id if src_type == "host" else None,
        storage_id=src_id if src_type == "storage" else None,
    )

    dst_endpoint = TransferEndpoint(
        type=dst_type,
        path=dst_path,
        host_id=dst_id if dst_type == "host" else None,
        storage_id=dst_id if dst_type == "storage" else None,
    )

    print(f"Transferring from {src_type}:{src_path} to {dst_type}:{dst_path}")
    if dry_run:
        print("(dry run - no files will be transferred)")

    engine = TransferEngine()

    # For simple local/SSH transfers, use rsync directly
    if src_type == "local" and dst_type == "local":
        result = engine.rsync(
            source=src_path,
            destination=dst_path,
            delete=delete,
            exclude=exclude,
            dry_run=dry_run,
        )
    elif src_type == "storage" or dst_type == "storage":
        # Load storage configurations
        from .storage import load_storages
        from ..services.transfer_engine import get_rclone_remote_name
        from ..core.models import StorageType

        storages = load_storages()

        src_storage = storages.get(src_id) if src_type == "storage" else None
        dst_storage = storages.get(dst_id) if dst_type == "storage" else None

        # Validate storages exist
        if src_type == "storage" and not src_storage:
            print(f"Error: Source storage not found: {src_id}")
            print("Use 'train storage list' to see configured storages.")
            sys.exit(1)
        if dst_type == "storage" and not dst_storage:
            print(f"Error: Destination storage not found: {dst_id}")
            print("Use 'train storage list' to see configured storages.")
            sys.exit(1)

        rsync_storage_types = {StorageType.LOCAL, StorageType.SSH}
        if (src_storage and src_storage.type in rsync_storage_types) or (
            dst_storage and dst_storage.type in rsync_storage_types
        ):
            from .host import load_hosts

            hosts = load_hosts() if src_type == "host" or dst_type == "host" else {}
            result = engine.transfer(
                source=src_endpoint,
                destination=dst_endpoint,
                hosts=hosts,
                storages=storages,
                delete=delete,
                exclude=exclude,
                dry_run=dry_run,
            )
        elif src_type == "host" or dst_type == "host":
            from .host import load_hosts

            print("Note: Host <-> cloud storage transfers relay through a local temp directory.")
            result = engine.transfer(
                source=src_endpoint,
                destination=dst_endpoint,
                hosts=load_hosts(),
                storages=storages,
                delete=delete,
                exclude=exclude,
                dry_run=dry_run,
            )
        else:
            if src_storage:
                src_remote = get_rclone_remote_name(src_storage)
                src_remote_path = resolve_storage_remote_path(src_storage, src_path)
                src_rclone = f"{src_remote}:{src_remote_path}" if src_remote_path else f"{src_remote}:"
            else:
                src_rclone = src_path

            if dst_storage:
                dst_remote = get_rclone_remote_name(dst_storage)
                dst_remote_path = resolve_storage_remote_path(dst_storage, dst_path)
                dst_rclone = f"{dst_remote}:{dst_remote_path}" if dst_remote_path else f"{dst_remote}:"
            else:
                dst_rclone = dst_path

            print(f"  Source: {src_rclone}")
            print(f"  Destination: {dst_rclone}")

            result = engine.rclone(
                source=src_rclone,
                destination=dst_rclone,
                operation="sync" if delete else "copy",
                dry_run=dry_run,
                src_storage=src_storage,
                dst_storage=dst_storage,
            )
    else:
        # Host transfers - need to load host config
        # For now, just provide guidance
        print("Note: For host transfers, ensure the host is configured.")
        print("Use 'train host list' to see configured hosts.")
        result = engine.transfer(
            source=src_endpoint,
            destination=dst_endpoint,
            delete=delete,
            exclude=exclude,
            dry_run=dry_run,
        )

    if result.success:
        print(f"Transfer complete: {result.message}")
        if result.bytes_transferred > 0:
            print(f"Transferred: {result.bytes_transferred:,} bytes")
    else:
        print(f"Transfer failed: {result.message}")
        sys.exit(1)

    return None


if __name__ == "__main__":
    main(sys.argv[1:])
elif __name__ == "__doc__":
    cd = sys.cli_docs  # type: ignore
    cd["usage"] = usage
    cd["help_text"] = "File transfer between hosts and storage"
    cd["short_desc"] = "Transfer files"

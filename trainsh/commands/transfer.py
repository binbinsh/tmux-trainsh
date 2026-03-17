# tmux-trainsh transfer command
# File transfer between hosts and storage

import sys
from typing import Optional, List

from ..cli_utils import render_command_help
from ..core.models import Storage, StorageType
from ..services.transfer_support import resolve_storage_remote_path

CLOUD_PREFIXES = {
    "r2:": StorageType.R2,
    "s3:": StorageType.S3,
    "b2:": StorageType.B2,
    "gcs:": StorageType.GCS,
}

CLOUD_STORAGE_TYPES = frozenset(CLOUD_PREFIXES.values())

usage = render_command_help(
    command="train transfer",
    summary="Copy files between local paths, named hosts, storage backends, and cloud endpoints.",
    usage_lines=("train transfer <source> <destination> [options]",),
    options=(
        "--delete, -d            Delete files at destination that do not exist in the source.",
        "--exclude, -e PAT       Exclude a glob pattern. Repeat to add more patterns.",
        "--dry-run               Show what would change without transferring files.",
        "--transfers N           Parallel rclone transfers (default: 32 for cloud).",
        "--checkers N            Parallel rclone checkers (default: 64 for cloud).",
        "--upload-concurrency N  S3 multipart upload threads per file (default: 16 for cloud).",
        "--chunk-size SIZE       Multipart chunk size (default: 64M for cloud).",
        "--include PAT           rclone include pattern (repeatable).",
    ),
    notes=(
        "Endpoint forms:",
        "  /local/path                   Local filesystem path",
        "  @host:/remote/path            Configured host alias",
        "  host:<name>:/remote/path      Explicit host endpoint",
        "  storage:<name>:/bucket/path   Named storage endpoint",
        "  r2:<bucket>/[prefix]          Cloudflare R2 (no pre-configuration needed)",
        "  s3:<bucket>/[prefix]          Amazon S3",
        "  b2:<bucket>/[prefix]          Backblaze B2",
        "  gcs:<bucket>/[prefix]         Google Cloud Storage",
        "",
        "Cloud endpoints (r2:/s3:/b2:/gcs:) resolve credentials from secrets automatically.",
        "Use train host list and train storage list to discover named endpoint names.",
        "Host <-> cloud storage transfers relay through a local temp directory.",
        "Dry runs work for direct rsync/rclone paths; relayed transfer paths fail fast instead of executing.",
    ),
    examples=(
        "train transfer ./artifacts @gpu:/workspace/out",
        "train transfer @gpu:/workspace/checkpoints ./checkpoints",
        "train transfer ./data storage:artifacts:/datasets/run-01",
        "train transfer ./data r2:my-bucket/prefix",
        "train transfer ./shards s3:my-bucket/datasets --transfers 64 --chunk-size 128M",
        "train transfer ./data r2:my-bucket/raw --include '*.mds' --include '*.zstd'",
    ),
)


def _try_cloud_endpoint(spec: str, position: str) -> Optional[tuple[Storage, str]]:
    """Try to parse a cloud endpoint prefix (r2:, s3:, b2:, gcs:).

    Supported forms::

        r2:bucket/prefix        slash-separated
        r2:bucket:/prefix       colon-separated (matches storage:name:path style)
        r2:bucket               bucket only, no prefix

    Args:
        spec: Endpoint string like ``r2:bucket/prefix``.
        position: ``"src"`` or ``"dst"`` — used to disambiguate ephemeral
            storage names when both endpoints are cloud.

    Returns:
        ``(Storage, rclone_path)`` on match, ``None`` otherwise.
        ``rclone_path`` is the ``bucket/prefix`` portion.
    """
    from ..core.storage_specs import build_storage_from_spec

    for prefix, storage_type in CLOUD_PREFIXES.items():
        if not spec.startswith(prefix):
            continue
        remainder = spec[len(prefix):]
        if not remainder:
            print(f"Error: Cloud endpoint '{spec}' requires a bucket name.")
            sys.exit(1)

        provider = prefix.rstrip(":")  # "r2", "s3", etc.

        # Two formats:  r2:bucket:/path  (colon)  or  r2:bucket/path  (slash)
        if ":" in remainder:
            bucket, path = remainder.split(":", 1)
            path = path.strip("/")
        else:
            slash_idx = remainder.find("/")
            if slash_idx == -1:
                bucket, path = remainder, ""
            else:
                bucket = remainder[:slash_idx]
                path = remainder[slash_idx + 1:].strip("/")

        storage = build_storage_from_spec(f"{provider}:{bucket}")
        if storage is None:
            print(f"Error: Could not build storage for '{spec}'.")
            sys.exit(1)

        rclone_path = resolve_storage_remote_path(storage, path)
        return (storage, rclone_path)
    return None


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

    # Cloud endpoint: r2:bucket:/path (colon-separated)
    for cloud_prefix in CLOUD_PREFIXES:
        if spec.startswith(cloud_prefix):
            remainder = spec[len(cloud_prefix):]
            if ":" in remainder:
                bucket, path = remainder.split(":", 1)
                return ("storage", path, f"{cloud_prefix.rstrip(':')}:{bucket}")
            # Slash-separated form (r2:bucket/path) is handled by
            # _try_cloud_endpoint in main() before parse_endpoint is called.
            break

    # Local path
    return ("local", spec, None)


def main(args: List[str]) -> Optional[str]:
    """Main entry point for transfer command."""
    if not args or args[0] in ("-h", "--help", "help"):
        print(usage)
        return None

    # Parse arguments
    delete = False
    exclude: List[str] = []
    include: List[str] = []
    dry_run = False
    transfers: Optional[int] = None
    checkers: Optional[int] = None
    upload_concurrency: Optional[int] = None
    chunk_size: Optional[str] = None

    i = 0
    positional: List[str] = []

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
        elif arg == "--include":
            if i + 1 >= len(args):
                print("Missing value for --include.")
                print(usage)
                sys.exit(1)
            include.append(args[i + 1])
            i += 2
        elif arg == "--dry-run":
            dry_run = True
            i += 1
        elif arg == "--transfers":
            if i + 1 >= len(args):
                print("Missing value for --transfers.")
                sys.exit(1)
            transfers = int(args[i + 1])
            i += 2
        elif arg == "--checkers":
            if i + 1 >= len(args):
                print("Missing value for --checkers.")
                sys.exit(1)
            checkers = int(args[i + 1])
            i += 2
        elif arg == "--upload-concurrency":
            if i + 1 >= len(args):
                print("Missing value for --upload-concurrency.")
                sys.exit(1)
            upload_concurrency = int(args[i + 1])
            i += 2
        elif arg == "--chunk-size":
            if i + 1 >= len(args):
                print("Missing value for --chunk-size.")
                sys.exit(1)
            chunk_size = args[i + 1]
            i += 2
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

    # --- Try cloud endpoint shortcuts before standard parsing ---
    src_cloud = _try_cloud_endpoint(source_spec, "src")
    dst_cloud = _try_cloud_endpoint(dest_spec, "dst")

    from ..core.models import TransferEndpoint
    from ..services.transfer_engine import TransferEngine, get_rclone_remote_name

    # Build rclone_opts dict — mutable, shared by reference with TransferEngine
    rclone_opts: dict = {}
    if include:
        rclone_opts["include"] = include
    if exclude:
        rclone_opts["exclude"] = exclude

    # Determine whether any endpoint is cloud (direct or named storage)
    has_cloud = src_cloud is not None or dst_cloud is not None

    if src_cloud:
        src_storage_obj, src_rclone_path = src_cloud
        src_type, src_path, src_id = "storage", src_rclone_path, src_storage_obj.name
    else:
        src_type, src_path, src_id = parse_endpoint(source_spec)
        src_storage_obj = None

    if dst_cloud:
        dst_storage_obj, dst_rclone_path = dst_cloud
        dst_type, dst_path, dst_id = "storage", dst_rclone_path, dst_storage_obj.name
    else:
        dst_type, dst_path, dst_id = parse_endpoint(dest_spec)
        dst_storage_obj = None

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

    # --- Build merged storage map (named storages + ephemeral cloud storages) ---
    storages: dict = {}
    if src_type == "storage" or dst_type == "storage":
        from .storage import load_storages
        storages = load_storages()
    if src_storage_obj:
        storages[src_storage_obj.name] = src_storage_obj
    if dst_storage_obj:
        storages[dst_storage_obj.name] = dst_storage_obj

    # Check named storages for cloud type too (apply high-throughput defaults)
    if not has_cloud:
        for sid in (src_id, dst_id):
            if sid and sid in storages and storages[sid].type in CLOUD_STORAGE_TYPES:
                has_cloud = True
                break

    # Apply high-throughput rclone defaults for cloud endpoints
    if has_cloud:
        rclone_opts.setdefault("transfers", transfers if transfers is not None else 32)
        rclone_opts.setdefault("checkers", checkers if checkers is not None else 64)
        rclone_opts.setdefault("s3_upload_concurrency", upload_concurrency if upload_concurrency is not None else 16)
        rclone_opts.setdefault("s3_chunk_size", chunk_size if chunk_size is not None else "64M")
    else:
        # Non-cloud: only set if user explicitly provided
        if transfers is not None:
            rclone_opts["transfers"] = transfers
        if checkers is not None:
            rclone_opts["checkers"] = checkers
        if upload_concurrency is not None:
            rclone_opts["s3_upload_concurrency"] = upload_concurrency
        if chunk_size is not None:
            rclone_opts["s3_chunk_size"] = chunk_size

    engine = TransferEngine(rclone_options=rclone_opts)

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

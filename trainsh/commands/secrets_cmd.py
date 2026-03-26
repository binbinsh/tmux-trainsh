# tmux-trainsh secrets command
# Manage API keys and credentials

import sys
from typing import Optional, List
import getpass

from ..cli_utils import SubcommandSpec, dispatch_subcommand, prompt_input
from .help_catalog import render_command_help
from .help_cmd import reject_subcommand_help

SUBCOMMAND_SPECS = (
    SubcommandSpec("list", "List common secrets and whether they are configured."),
    SubcommandSpec("set", "Store or update one secret value."),
    SubcommandSpec("get", "Show a masked preview of one secret."),
    SubcommandSpec("remove", "Delete one secret."),
    SubcommandSpec("backend", "Show or change the secrets backend."),
)

usage = render_command_help("secrets")


LISTED_SECRET_KEYS = (
    "VAST_API_KEY",
    "RUNPOD_API_KEY",
    "POE_API_KEY",
    "HF_TOKEN",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN",
    "GOOGLE_DRIVE_CREDENTIALS",
    "R2_CREDENTIALS",
    "B2_CREDENTIALS",
)


def _prompt_bundle_payload(provider: str) -> Optional[dict[str, str]]:
    """Prompt for a cloud storage credential bundle."""
    if provider == "r2":
        account_id = prompt_input("Cloudflare Account ID: ")
        if not account_id:
            return None
        access_key_id = getpass.getpass("R2 Access Key ID: ")
        if not access_key_id:
            return None
        secret_access_key = getpass.getpass("R2 Secret Access Key: ")
        if not secret_access_key:
            return None
        return {
            "account_id": account_id.strip(),
            "access_key_id": access_key_id.strip(),
            "secret_access_key": secret_access_key.strip(),
        }

    if provider == "b2":
        application_key_id = getpass.getpass("B2 Application Key ID: ")
        if not application_key_id:
            return None
        application_key = getpass.getpass("B2 Application Key: ")
        if not application_key:
            return None
        return {
            "application_key_id": application_key_id.strip(),
            "application_key": application_key.strip(),
        }

    return None


def cmd_list(args: List[str]) -> None:
    """List configured secrets."""
    from ..core.secrets import (
        get_configured_backend_name,
        get_secrets_manager,
        normalize_secret_key,
        resolve_secret_bundle_alias,
    )

    secrets = get_secrets_manager()
    configured_keys = list(getattr(secrets, "list_keys", lambda: [])())
    configured_lookup = {normalize_secret_key(key) for key in configured_keys}
    display_keys = list(LISTED_SECRET_KEYS)
    for key in configured_keys:
        normalized = normalize_secret_key(key)
        if normalized not in LISTED_SECRET_KEYS and normalized not in display_keys:
            display_keys.append(normalized)

    backend = getattr(secrets, "_get_backend", lambda: None)()

    def is_set(key: str) -> bool:
        normalized = normalize_secret_key(key)
        if normalized in configured_lookup:
            return True
        exists = getattr(secrets, "exists", None)
        if callable(exists):
            try:
                return bool(exists(normalized))
            except Exception:
                pass
        getter = getattr(secrets, "get", None)
        if callable(getter):
            try:
                return getter(normalized) not in (None, "")
            except Exception:
                pass
        if backend is not None:
            try:
                bundle_alias = resolve_secret_bundle_alias(normalized)
                probe_key = bundle_alias[0] if bundle_alias is not None else normalized
                return backend.get(probe_key) not in (None, "")
            except Exception:
                return False
        return False

    backend_name = get_configured_backend_name()
    if backend_name:
        from ..core.secrets import _BACKEND_NAMES
        label = _BACKEND_NAMES.get(backend_name, backend_name)
        print(f"Backend: {label}")
    else:
        print("Backend: [not configured]")
    print()

    print("Configured secrets:")
    print("-" * 40)

    found = 0
    for key in display_keys:
        exists = is_set(key)
        status = "[set]" if exists else "[not set]"
        print(f"  {key:<30} {status}")
        if exists:
            found += 1

    print("-" * 40)
    print(f"Total: {found}/{len(display_keys)} configured")


def cmd_set(args: List[str]) -> None:
    """Set a secret value."""
    if not args:
        print("Usage: train secrets set <key>")
        print("\nExample: train secrets set VAST_API_KEY")
        sys.exit(1)

    from ..core.secrets import get_secrets_manager, resolve_secret_bundle_alias

    key = args[0].upper()
    bundle_alias = resolve_secret_bundle_alias(key)
    if bundle_alias is not None and bundle_alias[1] is None:
        payload = _prompt_bundle_payload(bundle_alias[2])
        if not payload:
            print("Cancelled - no value provided.")
            return
        secrets = get_secrets_manager()
        try:
            secrets.set_bundle(bundle_alias[0], payload)
            print(f"Successfully set {bundle_alias[0]}")
        except RuntimeError as e:
            print(f"Error: {e}")
            sys.exit(1)
        return

    # Prompt for value (hidden input)
    try:
        value = getpass.getpass(f"Enter value for {key}: ")
        if not value:
            print("Cancelled - no value provided.")
            return
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return

    secrets = get_secrets_manager()

    try:
        secrets.set(key, value)
        print(f"Successfully set {key}")
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_get(args: List[str]) -> None:
    """Get a secret value."""
    if not args:
        print("Usage: train secrets get <key>")
        sys.exit(1)

    from ..core.secrets import get_secrets_manager

    key = args[0].upper()
    secrets = get_secrets_manager()

    value = secrets.get(key)
    if value:
        # Mask most of the value for security
        if len(value) > 8:
            masked = value[:4] + "*" * (len(value) - 8) + value[-4:]
        else:
            masked = "*" * len(value)
        print(f"{key}: {masked}")
    else:
        print(f"{key}: [not set]")


def cmd_delete(args: List[str]) -> None:
    """Delete a secret."""
    if not args:
        print("Usage: train secrets remove <key>")
        sys.exit(1)

    from ..core.secrets import get_secrets_manager

    key = args[0].upper()

    # Confirm deletion
    confirm = prompt_input(f"Delete {key}? (y/N): ")
    if confirm is None or confirm.lower() != "y":
        print("Cancelled.")
        return

    secrets = get_secrets_manager()
    secrets.delete(key)
    print(f"Deleted {key}")


def cmd_backend(args: List[str]) -> None:
    """Show or switch the secrets backend."""
    from ..core.secrets import (
        get_configured_backend_name,
        set_backend,
        _BACKEND_NAMES,
        _op_available,
    )

    current = get_configured_backend_name()

    if not args:
        # Show current backend
        if current:
            label = _BACKEND_NAMES.get(current, current)
            print(f"Current backend: {label}")
        else:
            print("No backend configured.")
        print()
        print("Available backends:")
        for name, label in _BACKEND_NAMES.items():
            marker = " (active)" if name == current else ""
            print(f"  {name:<20} {label}{marker}")
        print()
        print("Switch with: train secrets backend <name>")
        print("  e.g.  train secrets backend encrypted_file")
        print("        train secrets backend 1password")
        return

    name = args[0].lower()
    if name not in _BACKEND_NAMES:
        print(f"Unknown backend: {name}")
        print(f"Choose from: {', '.join(_BACKEND_NAMES)}")
        sys.exit(1)

    vault = None
    sa_token = None
    if name == "1password":
        if not _op_available():
            print("Warning: 'op' CLI not found on PATH.")
            print("Install from https://1password.com/downloads/command-line/")
            confirm = prompt_input("Continue anyway? (y/N): ")
            if confirm is None or confirm.lower() != "y":
                print("Cancelled.")
                return
        vault = prompt_input("1Password vault name [Development]: ", default="Development")
        from ..core.secrets import _resolve_op_auth
        sa_token = _resolve_op_auth(vault)
        if sa_token is False:
            print("Falling back to encrypted file backend.")
            name = "encrypted_file"
            sa_token = None
    elif name == "keyring":
        from ..core.secrets import _keyring_available
        if not _keyring_available():
            print("No system keyring found. Install 'keyring' package: pip install keyring")
            sys.exit(1)

    try:
        set_backend(name, vault=vault, sa_token=sa_token)
        label = _BACKEND_NAMES[name]
        print(f"Switched to: {label}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def main(args: List[str]) -> Optional[str]:
    """Main entry point for secrets command."""
    if not args:
        print(usage)
        return None
    if args[0] in ("-h", "--help", "help"):
        reject_subcommand_help()

    subcommand = args[0]
    subargs = args[1:]

    commands = {
        "list": cmd_list,
        "set": cmd_set,
        "get": cmd_get,
        "remove": cmd_delete,
        "backend": cmd_backend,
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
    cd["help_text"] = "Manage API keys and credentials"
    cd["short_desc"] = "Secrets management"

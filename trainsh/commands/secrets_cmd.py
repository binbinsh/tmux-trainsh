# tmux-trainsh secrets command
# Manage API keys and credentials

import sys
from typing import Optional, List
import getpass

from ..cli_utils import prompt_input
usage = '''[subcommand] [args...]

Subcommands:
  list             - List configured secrets
  set <key>        - Set a secret (prompts for value)
  get <key>        - Get a secret value
  delete <key>     - Delete a secret
  backend          - Show or switch secrets backend

Predefined keys:
  VAST_API_KEY           - Vast.ai API key
  HF_TOKEN               - HuggingFace token
  OPENAI_API_KEY         - OpenAI API key
  ANTHROPIC_API_KEY      - Anthropic API key
  GITHUB_TOKEN           - GitHub personal access token
  GOOGLE_DRIVE_CREDENTIALS - Google Drive OAuth/token JSON
  R2_CREDENTIALS         - Cloudflare R2 S3 API credentials bundle
  B2_CREDENTIALS         - Backblaze B2 application key bundle
'''


def _mask_secret(value: str) -> str:
    """Mask most of a secret value for display."""
    if len(value) > 8:
        return value[:4] + "*" * (len(value) - 8) + value[-4:]
    return "*" * len(value)


def _prompt_hidden_value(label: str, current: Optional[str] = None) -> Optional[str]:
    """Prompt for a sensitive value while optionally keeping the existing one."""
    suffix = " [leave empty to keep current]" if current else ""
    try:
        value = getpass.getpass(f"{label}{suffix}: ")
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return None

    if not value and current is not None:
        return current
    if not value:
        print("Cancelled - value is required.")
        return None
    return value


def _prompt_bundle_payload(provider: str, current: Optional[dict[str, str]] = None) -> Optional[dict[str, str]]:
    """Prompt for a composite storage credential bundle."""
    current = current or {}

    if provider == "r2":
        account_id = prompt_input(
            "R2 Account ID: ",
            default=current.get("account_id", ""),
        )
        if account_id is None:
            return None
        account_id = account_id.strip()
        if not account_id:
            print("Cancelled - R2 Account ID is required.")
            return None
        access_key_id = _prompt_hidden_value(
            "R2 API Token Access Key ID",
            current.get("access_key_id"),
        )
        if access_key_id is None:
            return None
        secret_access_key = _prompt_hidden_value(
            "R2 API Token Secret Access Key",
            current.get("secret_access_key"),
        )
        if secret_access_key is None:
            return None
        return {
            "account_id": account_id,
            "access_key_id": access_key_id,
            "secret_access_key": secret_access_key,
        }

    if provider == "b2":
        application_key_id = _prompt_hidden_value(
            "B2 Application Key ID",
            current.get("application_key_id"),
        )
        if application_key_id is None:
            return None
        application_key = _prompt_hidden_value(
            "B2 Application Key",
            current.get("application_key"),
        )
        if application_key is None:
            return None
        return {
            "application_key_id": application_key_id,
            "application_key": application_key,
        }

    return None


def cmd_list(args: List[str]) -> None:
    """List configured secrets."""
    from ..core.secrets import get_secrets_manager, get_configured_backend_name
    from ..constants import SecretKeys

    secrets = get_secrets_manager()

    predefined = [
        SecretKeys.VAST_API_KEY,
        SecretKeys.HF_TOKEN,
        SecretKeys.OPENAI_API_KEY,
        SecretKeys.ANTHROPIC_API_KEY,
        SecretKeys.GITHUB_TOKEN,
        SecretKeys.GOOGLE_DRIVE_CREDENTIALS,
        SecretKeys.R2_CREDENTIALS,
        SecretKeys.B2_CREDENTIALS,
    ]

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

    configured = set(secrets.list_keys())
    found = 0
    for key in predefined:
        exists = key in configured
        status = "[set]" if exists else "[not set]"
        print(f"  {key:<30} {status}")
        if exists:
            found += 1

    print("-" * 40)
    print(f"Total: {found}/{len(predefined)} configured")


def cmd_set(args: List[str]) -> None:
    """Set a secret value."""
    if not args:
        print("Usage: train secrets set <key>")
        print("\nExample: train secrets set VAST_API_KEY")
        sys.exit(1)

    from ..core.secrets import get_secrets_manager
    from ..core.secrets import (
        parse_secret_bundle_value,
        resolve_secret_bundle_alias,
    )

    key = args[0].upper()
    bundle_alias = resolve_secret_bundle_alias(key)
    secrets = get_secrets_manager()

    if bundle_alias is not None:
        composite_key, _field_name, provider = bundle_alias
        current = parse_secret_bundle_value(secrets.get(composite_key))
        payload = _prompt_bundle_payload(provider, current=current)
        if payload is None:
            return
        secrets.set_bundle(composite_key, payload)
        print(f"Successfully set {composite_key}")
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
    from ..core.secrets import (
        parse_secret_bundle_value,
        resolve_secret_bundle_alias,
    )

    key = args[0].upper()
    secrets = get_secrets_manager()
    bundle_alias = resolve_secret_bundle_alias(key)

    if bundle_alias is not None:
        composite_key, field_name, _provider = bundle_alias
        raw_value = secrets.get(composite_key)
        payload = parse_secret_bundle_value(raw_value)
        if not payload:
            print(f"{key}: [not set]")
            return

        if field_name:
            value = str(payload.get(field_name, "")).strip()
            if not value:
                print(f"{key}: [not set]")
                return
            masked = value if field_name in {"endpoint", "account_id"} else _mask_secret(value)
            print(f"{key}: {masked}")
            return

        print(f"{composite_key}:")
        for field in sorted(payload):
            value = payload[field]
            masked = value if field in {"endpoint", "account_id"} else _mask_secret(value)
            print(f"  {field}: {masked}")
        return

    value = secrets.get(key)
    if value:
        # Mask most of the value for security
        masked = _mask_secret(value)
        print(f"{key}: {masked}")
    else:
        print(f"{key}: [not set]")


def cmd_delete(args: List[str]) -> None:
    """Delete a secret."""
    if not args:
        print("Usage: train secrets delete <key>")
        sys.exit(1)

    from ..core.secrets import get_secrets_manager
    from ..core.secrets import resolve_secret_bundle_alias

    key = args[0].upper()
    bundle_alias = resolve_secret_bundle_alias(key)
    target_key = bundle_alias[0] if bundle_alias is not None else key

    # Confirm deletion
    confirm = prompt_input(f"Delete {target_key}? (y/N): ")
    if confirm is None or confirm.lower() != "y":
        print("Cancelled.")
        return

    secrets = get_secrets_manager()
    secrets.delete(target_key)
    print(f"Deleted {target_key}")


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
    if not args or args[0] in ("-h", "--help", "help"):
        print(usage)
        return None

    subcommand = args[0]
    subargs = args[1:]

    commands = {
        "list": cmd_list,
        "set": cmd_set,
        "get": cmd_get,
        "delete": cmd_delete,
        "backend": cmd_backend,
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
    cd["help_text"] = "Manage API keys and credentials"
    cd["short_desc"] = "Secrets management"

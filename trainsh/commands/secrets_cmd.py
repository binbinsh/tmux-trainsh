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

Predefined keys:
  VAST_API_KEY           - Vast.ai API key
  HF_TOKEN               - HuggingFace token
  OPENAI_API_KEY         - OpenAI API key
  ANTHROPIC_API_KEY      - Anthropic API key
  GITHUB_TOKEN           - GitHub personal access token
'''


def cmd_list(args: List[str]) -> None:
    """List configured secrets."""
    from ..core.secrets import get_secrets_manager
    from ..constants import SecretKeys

    secrets = get_secrets_manager()

    predefined = [
        SecretKeys.VAST_API_KEY,
        SecretKeys.HF_TOKEN,
        SecretKeys.OPENAI_API_KEY,
        SecretKeys.ANTHROPIC_API_KEY,
        SecretKeys.GITHUB_TOKEN,
        SecretKeys.GOOGLE_DRIVE_CREDENTIALS,
    ]

    print("Configured secrets:")
    print("-" * 40)

    found = 0
    for key in predefined:
        exists = secrets.exists(key)
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

    key = args[0].upper()

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
        print("Usage: train secrets delete <key>")
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

# tmux-trainsh vast command
# Vast.ai instance management

import sys
import os
from typing import Optional, List

from ..cli_utils import prompt_input

usage = '''[subcommand] [args...]

Subcommands:
  list              - List your Vast.ai instances
  show <id>         - Show instance details
  ssh <id>          - SSH into instance
  start <id>        - Start instance
  stop <id>         - Stop instance
  rm <id>           - Remove instance
  reboot <id>       - Reboot instance
  search            - Search for GPU offers
  keys              - List SSH keys
  attach-key [path] - Attach local SSH key (default: ~/.ssh/id_rsa.pub)

Examples:
  train vast list
  train vast ssh 12345
  train vast start 12345
'''


def cmd_list(args: List[str]) -> None:
    """List Vast.ai instances."""
    from ..services.vast_api import get_vast_client
    from ..utils.vast_formatter import print_instance_table

    client = get_vast_client()
    instances = client.list_instances()
    print_instance_table(instances)


def cmd_show(args: List[str]) -> None:
    """Show instance details."""
    if not args:
        print("Usage: train vast show <instance_id>")
        sys.exit(1)

    from ..services.vast_api import get_vast_client
    from ..utils.vast_formatter import print_instance_detail

    inst_id = int(args[0])
    client = get_vast_client()
    inst = client.get_instance(inst_id)

    if not inst:
        print(f"Instance not found: {inst_id}")
        sys.exit(1)

    print_instance_detail(inst)


def cmd_ssh(args: List[str]) -> None:
    """SSH into instance."""
    if not args:
        print("Usage: train vast ssh <instance_id>")
        sys.exit(1)

    from ..services.vast_api import get_vast_client

    inst_id = int(args[0])
    client = get_vast_client()
    inst = client.get_instance(inst_id)

    if not inst:
        print(f"Instance not found: {inst_id}")
        sys.exit(1)

    if inst.actual_status != "running":
        print(f"Instance not running (status: {inst.actual_status})")
        print("Use 'train vast start <id>' to start the instance.")
        sys.exit(1)

    ssh_host = inst.ssh_host or inst.public_ipaddr
    ssh_port = inst.ssh_port or 22

    if not ssh_host:
        print("SSH host not available for this instance.")
        sys.exit(1)

    print(f"Connecting to {ssh_host}:{ssh_port}...")
    ssh_cmd = f"ssh -p {ssh_port} root@{ssh_host}"
    os.system(ssh_cmd)


def cmd_start(args: List[str]) -> None:
    """Start instance."""
    if not args:
        print("Usage: train vast start <instance_id>")
        sys.exit(1)

    from ..services.vast_api import get_vast_client

    inst_id = int(args[0])
    client = get_vast_client()

    print(f"Starting instance {inst_id}...")
    client.start_instance(inst_id)
    print("Instance started.")


def cmd_stop(args: List[str]) -> None:
    """Stop instance."""
    if not args:
        print("Usage: train vast stop <instance_id>")
        sys.exit(1)

    from ..services.vast_api import get_vast_client

    inst_id = int(args[0])
    client = get_vast_client()

    print(f"Stopping instance {inst_id}...")
    client.stop_instance(inst_id)
    print("Instance stopped. (Storage charges still apply)")


def cmd_rm(args: List[str]) -> None:
    """Remove instance."""
    if not args:
        print("Usage: train vast rm <instance_id>")
        sys.exit(1)

    inst_id = int(args[0])

    confirm = prompt_input(f"Remove instance {inst_id}? This cannot be undone. (y/N): ")
    if confirm is None or confirm.lower() != "y":
        print("Cancelled.")
        return

    from ..services.vast_api import get_vast_client

    client = get_vast_client()
    print(f"Removing instance {inst_id}...")
    client.rm_instance(inst_id)
    print("Instance removed.")


def cmd_reboot(args: List[str]) -> None:
    """Reboot instance."""
    if not args:
        print("Usage: train vast reboot <instance_id>")
        sys.exit(1)

    from ..services.vast_api import get_vast_client

    inst_id = int(args[0])
    client = get_vast_client()

    print(f"Rebooting instance {inst_id}...")
    client.reboot_instance(inst_id)
    print("Instance rebooting.")


def cmd_search(args: List[str]) -> None:
    """Search for GPU offers."""
    from ..services.vast_api import get_vast_client
    from ..services.pricing import format_currency
    from ..utils.vast_formatter import get_currency_settings

    print("Searching for GPU offers...")
    client = get_vast_client()
    offers = client.search_offers()

    if not offers:
        print("No offers found.")
        return

    currency = get_currency_settings()

    if currency.display_currency != "USD":
        print(f"{'ID':<10} {'GPU':<20} {'GPUs':<5} {'VRAM':<8} {'$/hr':<10} {currency.display_currency + '/hr':<12}")
        print("-" * 75)
    else:
        print(f"{'ID':<10} {'GPU':<20} {'GPUs':<5} {'VRAM':<8} {'$/hr':<10}")
        print("-" * 60)

    for offer in offers[:20]:
        gpu = offer.gpu_name or "N/A"
        gpus = offer.num_gpus or 1
        usd_price = offer.dph_total or 0
        vram = offer.gpu_ram / 1024 if offer.gpu_ram else 0  # MB to GB

        if currency.display_currency != "USD":
            converted = currency.rates.convert(usd_price, "USD", currency.display_currency)
            converted_str = format_currency(converted, currency.display_currency)
            print(f"{offer.id:<10} {gpu:<20} {gpus:<5} {vram:.0f}GB{'':<4} ${usd_price:<9.3f} {converted_str:<12}")
        else:
            print(f"{offer.id:<10} {gpu:<20} {gpus:<5} {vram:.0f}GB{'':<4} ${usd_price:<9.3f}")

    if len(offers) > 20:
        print(f"... and {len(offers) - 20} more offers")


def cmd_keys(args: List[str]) -> None:
    """List SSH keys."""
    from ..services.vast_api import get_vast_client

    client = get_vast_client()
    keys = client.list_ssh_keys()

    if not keys:
        print("No SSH keys registered.")
        print("Use 'train vast attach-key' to add your SSH key.")
        return

    print("Registered SSH keys:")
    for key in keys:
        key_str = key.get("ssh_key", "")
        if len(key_str) > 60:
            key_str = key_str[:60] + "..."
        print(f"  - {key_str}")


def cmd_attach_key(args: List[str]) -> None:
    """Attach local SSH key."""
    key_path = "~/.ssh/id_rsa.pub"
    if args:
        key_path = args[0]

    key_path = os.path.expanduser(key_path)

    if not os.path.exists(key_path):
        print(f"Key file not found: {key_path}")
        sys.exit(1)

    with open(key_path) as f:
        key_content = f.read().strip()

    from ..services.vast_api import get_vast_client

    client = get_vast_client()
    print(f"Attaching key from {key_path}...")
    client.add_ssh_key(key_content)
    print("SSH key attached successfully.")


def main(args: List[str]) -> Optional[str]:
    """Main entry point for vast command."""
    if not args or args[0] in ("-h", "--help", "help"):
        print(usage)
        return None

    subcommand = args[0]
    subargs = args[1:]

    commands = {
        "list": cmd_list,
        "show": cmd_show,
        "ssh": cmd_ssh,
        "start": cmd_start,
        "stop": cmd_stop,
        "rm": cmd_rm,
        "reboot": cmd_reboot,
        "search": cmd_search,
        "keys": cmd_keys,
        "attach-key": cmd_attach_key,
    }

    if subcommand not in commands:
        print(f"Unknown subcommand: {subcommand}")
        print(usage)
        sys.exit(1)

    try:
        commands[subcommand](subargs)
    except Exception as e:
        if "VAST_API_KEY" in str(e) or "API key" in str(e).lower():
            print(f"Error: {e}")
            print("\nMake sure VAST_API_KEY is set:")
            print("  train secrets set VAST_API_KEY")
        else:
            raise

    return None


if __name__ == "__main__":
    main(sys.argv[1:])
elif __name__ == "__doc__":
    cd = sys.cli_docs  # type: ignore
    cd["usage"] = usage
    cd["help_text"] = "Vast.ai instance management"
    cd["short_desc"] = "Manage Vast.ai GPU instances"

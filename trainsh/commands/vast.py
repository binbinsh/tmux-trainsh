# kitten-trainsh vast command
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
  destroy <id>      - Destroy instance
  reboot <id>       - Reboot instance
  search            - Search for GPU offers
  keys              - List SSH keys
  attach-key [path] - Attach local SSH key (default: ~/.ssh/id_rsa.pub)

Examples:
  kitty +kitten trainsh vast list
  kitty +kitten trainsh vast ssh 12345
  kitty +kitten trainsh vast start 12345
'''


def cmd_list(args: List[str]) -> None:
    """List Vast.ai instances."""
    from ..services.vast_api import get_vast_client
    from ..services.pricing import load_pricing_settings, format_currency
    from ..config import load_config

    client = get_vast_client()
    instances = client.list_instances()

    if not instances:
        print("No instances found.")
        return

    # Load currency settings
    settings = load_pricing_settings()
    config = load_config()
    display_curr = config.get("ui", {}).get("currency", settings.display_currency)
    rates = settings.exchange_rates

    # Header with optional converted currency column
    if display_curr != "USD":
        print(f"{'ID':<10} {'Status':<12} {'GPU':<20} {'$/hr':<10} {display_curr + '/hr':<12}")
        print("-" * 70)
    else:
        print(f"{'ID':<10} {'Status':<12} {'GPU':<20} {'$/hr':<10}")
        print("-" * 55)

    for inst in instances:
        status = inst.actual_status or "unknown"
        gpu = inst.gpu_name or "N/A"
        usd_price = inst.dph_total or 0

        if display_curr != "USD":
            converted = rates.convert(usd_price, "USD", display_curr)
            price_str = f"${usd_price:.3f}" if usd_price else "N/A"
            converted_str = format_currency(converted, display_curr) if usd_price else "N/A"
            print(f"{inst.id:<10} {status:<12} {gpu:<20} {price_str:<10} {converted_str:<12}")
        else:
            price_str = f"${usd_price:.3f}" if usd_price else "N/A"
            print(f"{inst.id:<10} {status:<12} {gpu:<20} {price_str:<10}")

    print("-" * (70 if display_curr != "USD" else 55))
    print(f"Total: {len(instances)} instances")


def cmd_show(args: List[str]) -> None:
    """Show instance details."""
    if not args:
        print("Usage: kitty +kitten trainsh vast show <instance_id>")
        sys.exit(1)

    from ..services.vast_api import get_vast_client
    from ..services.pricing import load_pricing_settings, format_currency
    from ..config import load_config

    inst_id = int(args[0])
    client = get_vast_client()
    inst = client.get_instance(inst_id)

    if not inst:
        print(f"Instance not found: {inst_id}")
        sys.exit(1)

    # Load currency settings
    settings = load_pricing_settings()
    config = load_config()
    display_curr = config.get("ui", {}).get("currency", settings.display_currency)
    rates = settings.exchange_rates

    print(f"Instance: {inst.id}")
    print(f"  Status: {inst.actual_status}")
    print(f"  GPU: {inst.gpu_name}")
    if inst.dph_total:
        usd_price = inst.dph_total
        if display_curr != "USD":
            converted = rates.convert(usd_price, "USD", display_curr)
            print(f"  Price: ${usd_price:.3f}/hr ({format_currency(converted, display_curr)}/hr)")
        else:
            print(f"  Price: ${usd_price:.3f}/hr")
    if inst.ssh_host:
        print(f"  SSH: {inst.ssh_host}:{inst.ssh_port}")
    if inst.public_ipaddr:
        print(f"  Public IP: {inst.public_ipaddr}")


def cmd_ssh(args: List[str]) -> None:
    """SSH into instance."""
    if not args:
        print("Usage: kitty +kitten trainsh vast ssh <instance_id>")
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
        print("Use 'trainsh vast start <id>' to start the instance.")
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
        print("Usage: kitty +kitten trainsh vast start <instance_id>")
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
        print("Usage: kitty +kitten trainsh vast stop <instance_id>")
        sys.exit(1)

    from ..services.vast_api import get_vast_client

    inst_id = int(args[0])
    client = get_vast_client()

    print(f"Stopping instance {inst_id}...")
    client.stop_instance(inst_id)
    print("Instance stopped. (Storage charges still apply)")


def cmd_destroy(args: List[str]) -> None:
    """Destroy instance."""
    if not args:
        print("Usage: kitty +kitten trainsh vast destroy <instance_id>")
        sys.exit(1)

    inst_id = int(args[0])

    confirm = prompt_input(f"Destroy instance {inst_id}? This cannot be undone. (y/N): ")
    if confirm is None or confirm.lower() != "y":
        print("Cancelled.")
        return

    from ..services.vast_api import get_vast_client

    client = get_vast_client()
    print(f"Destroying instance {inst_id}...")
    client.destroy_instance(inst_id)
    print("Instance destroyed.")


def cmd_reboot(args: List[str]) -> None:
    """Reboot instance."""
    if not args:
        print("Usage: kitty +kitten trainsh vast reboot <instance_id>")
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
    from ..services.pricing import load_pricing_settings, format_currency
    from ..config import load_config

    print("Searching for GPU offers...")
    client = get_vast_client()
    offers = client.search_offers()

    if not offers:
        print("No offers found.")
        return

    # Load currency settings
    settings = load_pricing_settings()
    config = load_config()
    display_curr = config.get("ui", {}).get("currency", settings.display_currency)
    rates = settings.exchange_rates

    if display_curr != "USD":
        print(f"{'ID':<10} {'GPU':<20} {'$/hr':<10} {display_curr + '/hr':<12} {'VRAM':<8}")
        print("-" * 65)
    else:
        print(f"{'ID':<10} {'GPU':<20} {'$/hr':<10} {'VRAM':<8}")
        print("-" * 50)

    for offer in offers[:20]:
        gpu = offer.get("gpu_name", "N/A")
        usd_price = offer.get("dph_total", 0)
        vram = offer.get("gpu_ram", 0)

        if display_curr != "USD":
            converted = rates.convert(usd_price, "USD", display_curr)
            converted_str = format_currency(converted, display_curr)
            print(f"{offer.get('id', 'N/A'):<10} {gpu:<20} ${usd_price:<9.3f} {converted_str:<12} {vram}GB")
        else:
            print(f"{offer.get('id', 'N/A'):<10} {gpu:<20} ${usd_price:<9.3f} {vram}GB")

    if len(offers) > 20:
        print(f"... and {len(offers) - 20} more offers")


def cmd_keys(args: List[str]) -> None:
    """List SSH keys."""
    from ..services.vast_api import get_vast_client

    client = get_vast_client()
    keys = client.list_ssh_keys()

    if not keys:
        print("No SSH keys registered.")
        print("Use 'trainsh vast attach-key' to add your SSH key.")
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
        "destroy": cmd_destroy,
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
            print("  kitty +kitten trainsh secrets set VAST_API_KEY")
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

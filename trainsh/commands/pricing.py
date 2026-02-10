# Pricing command for tmux-trainsh
# Manage exchange rates and cost calculations

import argparse
from typing import Optional

from ..services.pricing import (
    Currency,
    ExchangeRates,
    fetch_exchange_rates,
    load_pricing_settings,
    save_pricing_settings,
    format_currency,
    calculate_colab_pricing,
    ColabGpuPricing,
    ColabSubscription,
    calculate_host_cost,
)


def cmd_rates(args: argparse.Namespace) -> None:
    """Show or refresh exchange rates."""
    settings = load_pricing_settings()

    if args.refresh:
        print("Fetching exchange rates...")
        rates = fetch_exchange_rates()
        settings.exchange_rates = rates
        save_pricing_settings(settings)
        print(f"Updated at: {rates.updated_at}")
    else:
        rates = settings.exchange_rates
        if not rates.rates:
            print("No exchange rates cached. Use --refresh to fetch.")
            return

    print(f"\nExchange Rates (Base: {rates.base})")
    print("-" * 35)
    for code, rate in sorted(rates.rates.items()):
        try:
            curr = Currency(code)
            print(f"  {code:4} ({curr.symbol:3})  {rate:>10.4f}")
        except ValueError:
            print(f"  {code:4}        {rate:>10.4f}")


def cmd_currency(args: argparse.Namespace) -> None:
    """Get or set display currency."""
    from ..config import get_config_value, set_config_value

    # Auto-migrate: if pricing.json has display_currency and config.toml doesn't,
    # copy it over and remove from pricing.json.
    config_currency = get_config_value("ui.currency", "")
    if not config_currency:
        import json
        from ..services.pricing import PRICING_FILE
        if PRICING_FILE.exists():
            try:
                with open(PRICING_FILE, "r") as f:
                    pdata = json.load(f)
                old_curr = pdata.get("display_currency", "")
                if old_curr and old_curr != "USD":
                    set_config_value("ui.currency", old_curr)
                    config_currency = old_curr
                    # Remove from pricing.json
                    pdata.pop("display_currency", None)
                    with open(PRICING_FILE, "w") as f:
                        json.dump(pdata, f, indent=2)
                    print(f"Migrated display currency '{old_curr}' from pricing.json to config.toml")
            except (json.JSONDecodeError, OSError):
                pass

    display_currency = config_currency or "USD"

    if args.set:
        try:
            Currency(args.set.upper())
            set_config_value("ui.currency", args.set.upper())
            print(f"Display currency set to: {args.set.upper()}")
        except ValueError:
            print(f"Invalid currency: {args.set}")
            print("Valid currencies: USD, JPY, HKD, CNY, EUR, GBP, KRW, TWD")
            raise SystemExit(1)
    else:
        print(f"Display currency: {display_currency}")
        print("\nAvailable currencies:")
        for curr in Currency:
            marker = " *" if curr.value == display_currency else ""
            print(f"  {curr.value:4} - {curr.label} ({curr.symbol}){marker}")


def cmd_colab(args: argparse.Namespace) -> None:
    """Show or configure Colab pricing."""
    settings = load_pricing_settings()

    if args.subscription:
        # Parse subscription: "name:price:currency:units"
        parts = args.subscription.split(":")
        if len(parts) >= 2:
            settings.colab_subscription.name = parts[0]
            settings.colab_subscription.price = float(parts[1])
            if len(parts) >= 3:
                settings.colab_subscription.currency = parts[2].upper()
            if len(parts) >= 4:
                settings.colab_subscription.total_units = float(parts[3])
            save_pricing_settings(settings)
            print(f"Updated Colab subscription: {settings.colab_subscription.name}")
        else:
            print("Format: name:price[:currency[:units]]")
            print("Example: 'Colab Pro:11.99:USD:100'")
            raise SystemExit(1)
        return

    # Show Colab pricing
    sub = settings.colab_subscription
    print(f"Colab Subscription: {sub.name}")
    print(f"  Price: {format_currency(sub.price, sub.currency)}")
    print(f"  Total Units: {sub.total_units}")
    print(f"  Price per Unit: {format_currency(sub.price / sub.total_units, sub.currency)}")

    # Calculate GPU prices
    gpu_pricing = [
        ColabGpuPricing(g["gpu_name"], g["units_per_hour"])
        for g in settings.colab_gpu_pricing
    ]
    prices = calculate_colab_pricing(sub, gpu_pricing, settings.exchange_rates)

    print(f"\nGPU Hourly Prices:")
    print("-" * 50)
    # Read display currency from config.toml via get_currency_settings()
    from ..utils.vast_formatter import get_currency_settings
    currency_settings = get_currency_settings()
    display_curr = currency_settings.display_currency
    for p in prices:
        converted = settings.exchange_rates.convert(p.price_usd_per_hour, "USD", display_curr)
        print(f"  {p.gpu_name:8} {p.units_per_hour:>6.2f} units/hr  "
              f"${p.price_usd_per_hour:.4f}  {format_currency(converted, display_curr)}/hr")


def cmd_vast(args: argparse.Namespace) -> None:
    """Show Vast.ai instance pricing."""
    from ..services.vast_api import get_vast_client
    from ..utils.vast_formatter import get_currency_settings

    settings = load_pricing_settings()
    currency_settings = get_currency_settings()
    display_curr = currency_settings.display_currency
    rates = settings.exchange_rates

    client = get_vast_client()
    instances = client.list_instances()

    if not instances:
        print("No Vast.ai instances found.")
        return

    print(f"Vast.ai Instance Costs (in {display_curr})")
    print("-" * 85)
    print(f"{'ID':<10} {'Status':<10} {'GPU':<18} {'GPUs':<5} {'$/hr':<10} {display_curr + '/hr':<10} {display_curr + '/day':<12}")
    print("-" * 85)

    total_per_hour = 0.0
    for inst in instances:
        if inst.dph_total:
            cost = calculate_host_cost(
                host_id=str(inst.id),
                gpu_hourly_usd=inst.dph_total,
                host_name=inst.gpu_name,
                source="vast_api",
            )
            total_per_hour += cost.total_per_hour_usd

            hr_conv = rates.convert(cost.total_per_hour_usd, "USD", display_curr)
            day_conv = rates.convert(cost.total_per_day_usd, "USD", display_curr)

            status = inst.actual_status or "unknown"
            gpu = inst.gpu_name or "N/A"
            gpus = inst.num_gpus or 1

            print(f"{inst.id:<10} {status:<10} {gpu:<18} {gpus:<5} "
                  f"${cost.total_per_hour_usd:<9.4f} "
                  f"{format_currency(hr_conv, display_curr):<10} "
                  f"{format_currency(day_conv, display_curr):<12}")

    print("-" * 85)
    total_day = total_per_hour * 24
    total_month = total_day * 30
    total_hr_conv = rates.convert(total_per_hour, "USD", display_curr)
    total_day_conv = rates.convert(total_day, "USD", display_curr)
    total_month_conv = rates.convert(total_month, "USD", display_curr)

    print(f"{'Total':>10}  {'':>15}  ${total_per_hour:>9.4f}  "
          f"{format_currency(total_hr_conv, display_curr):>10}  "
          f"{format_currency(total_day_conv, display_curr):>12}")
    print(f"\nMonthly estimate: {format_currency(total_month_conv, display_curr)}")


def cmd_convert(args: argparse.Namespace) -> None:
    """Convert amount between currencies."""
    settings = load_pricing_settings()
    rates = settings.exchange_rates

    if not rates.rates:
        print("No exchange rates cached. Run 'pricing rates --refresh' first.")
        raise SystemExit(1)

    amount = args.amount
    from_curr = args.from_currency.upper()
    to_curr = args.to_currency.upper()

    converted = rates.convert(amount, from_curr, to_curr)
    print(f"{format_currency(amount, from_curr)} = {format_currency(converted, to_curr)}")


def main(args: list) -> Optional[str]:
    """Main entry point for pricing command."""
    parser = argparse.ArgumentParser(
        prog="train pricing",
        description="Manage pricing and currency conversion",
    )
    subparsers = parser.add_subparsers(dest="command", help="Pricing commands")

    # rates
    rates_parser = subparsers.add_parser("rates", help="Show/refresh exchange rates")
    rates_parser.add_argument("--refresh", "-r", action="store_true",
                              help="Fetch latest exchange rates")

    # currency
    curr_parser = subparsers.add_parser("currency", help="Get/set display currency")
    curr_parser.add_argument("--set", "-s", metavar="CODE",
                             help="Set display currency (USD, JPY, CNY, etc.)")

    # colab
    colab_parser = subparsers.add_parser("colab", help="Colab pricing calculator")
    colab_parser.add_argument("--subscription", "-s", metavar="SPEC",
                              help="Set subscription: name:price[:currency[:units]]")

    # vast
    subparsers.add_parser("vast", help="Show Vast.ai instance costs")

    # convert
    conv_parser = subparsers.add_parser("convert", help="Convert between currencies")
    conv_parser.add_argument("amount", type=float, help="Amount to convert")
    conv_parser.add_argument("from_currency", help="Source currency")
    conv_parser.add_argument("to_currency", help="Target currency")

    parsed = parser.parse_args(args)

    if not parsed.command:
        parser.print_help()
        return None

    if parsed.command == "rates":
        cmd_rates(parsed)
    elif parsed.command == "currency":
        cmd_currency(parsed)
    elif parsed.command == "colab":
        cmd_colab(parsed)
    elif parsed.command == "vast":
        cmd_vast(parsed)
    elif parsed.command == "convert":
        cmd_convert(parsed)

    return None

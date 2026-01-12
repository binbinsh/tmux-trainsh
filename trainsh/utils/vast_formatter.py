# tmux-trainsh Vast.ai instance formatter
# Unified formatting for Vast.ai instance display

from typing import List, Optional, Tuple
from dataclasses import dataclass

from ..core.models import VastInstance
from ..services.pricing import load_pricing_settings, format_currency
from ..config import load_config


@dataclass
class CurrencySettings:
    """Currency display settings."""
    display_currency: str
    rates: any  # ExchangeRates

    def format_price(self, usd_price: float) -> str:
        """Format price with optional currency conversion."""
        if not usd_price:
            return "N/A"

        usd_str = f"${usd_price:.3f}"
        if self.display_currency != "USD":
            converted = self.rates.convert(usd_price, "USD", self.display_currency)
            return f"{usd_str} ({format_currency(converted, self.display_currency)})"
        return usd_str


def get_currency_settings() -> CurrencySettings:
    """Load currency settings from config."""
    settings = load_pricing_settings()
    config = load_config()
    display_curr = config.get("ui", {}).get("currency", settings.display_currency)
    return CurrencySettings(
        display_currency=display_curr,
        rates=settings.exchange_rates,
    )


def format_instance_row(
    inst: VastInstance,
    currency: Optional[CurrencySettings] = None,
    show_index: bool = False,
    index: int = 0,
) -> str:
    """
    Format a VastInstance as a single row for table display.

    Args:
        inst: VastInstance to format
        currency: Currency settings (loads from config if None)
        show_index: Whether to show row index
        index: Row index (1-based)

    Returns:
        Formatted row string
    """
    if currency is None:
        currency = get_currency_settings()

    status = inst.actual_status or "unknown"
    gpu = inst.gpu_name or "N/A"
    gpus = inst.num_gpus or 1
    vram_gb = inst.gpu_memory_gb
    # Show total VRAM (per-GPU * num_gpus)
    total_vram_gb = (vram_gb * gpus) if vram_gb else None
    vram = f"{total_vram_gb:.0f}GB" if total_vram_gb else "N/A"
    usd_price = inst.dph_total or 0

    # Format price with conversion
    if usd_price:
        price_usd = f"${usd_price:.3f}"
        if currency.display_currency != "USD":
            converted = currency.rates.convert(usd_price, "USD", currency.display_currency)
            price_conv = format_currency(converted, currency.display_currency)
        else:
            price_conv = ""
    else:
        price_usd = "N/A"
        price_conv = ""

    if show_index:
        if price_conv:
            return f"{index:<4} {inst.id:<10} {status:<10} {gpu:<18} {gpus:<5} {vram:<8} {price_usd:<10} {price_conv}"
        return f"{index:<4} {inst.id:<10} {status:<10} {gpu:<18} {gpus:<5} {vram:<8} {price_usd:<10}"
    else:
        if price_conv:
            return f"{inst.id:<10} {status:<10} {gpu:<18} {gpus:<5} {vram:<8} {price_usd:<10} {price_conv}"
        return f"{inst.id:<10} {status:<10} {gpu:<18} {gpus:<5} {vram:<8} {price_usd:<10}"


def format_instance_header(
    currency: Optional[CurrencySettings] = None,
    show_index: bool = False,
) -> Tuple[str, str]:
    """
    Format header row for instance table.

    Returns:
        (header_line, separator_line)
    """
    if currency is None:
        currency = get_currency_settings()

    if show_index:
        if currency.display_currency != "USD":
            header = f"{'#':<4} {'ID':<10} {'Status':<10} {'GPU':<18} {'GPUs':<5} {'VRAM':<8} {'$/hr':<10} {currency.display_currency + '/hr'}"
            sep = "-" * 95
        else:
            header = f"{'#':<4} {'ID':<10} {'Status':<10} {'GPU':<18} {'GPUs':<5} {'VRAM':<8} {'$/hr':<10}"
            sep = "-" * 80
    else:
        if currency.display_currency != "USD":
            header = f"{'ID':<10} {'Status':<10} {'GPU':<18} {'GPUs':<5} {'VRAM':<8} {'$/hr':<10} {currency.display_currency + '/hr'}"
            sep = "-" * 90
        else:
            header = f"{'ID':<10} {'Status':<10} {'GPU':<18} {'GPUs':<5} {'VRAM':<8} {'$/hr':<10}"
            sep = "-" * 75

    return header, sep


def print_instance_table(
    instances: List[VastInstance],
    show_index: bool = False,
    title: Optional[str] = None,
) -> None:
    """
    Print a formatted table of VastInstances.

    Args:
        instances: List of instances to print
        show_index: Whether to show row indices
        title: Optional title to print before table
    """
    if not instances:
        print("No instances found.")
        return

    currency = get_currency_settings()
    header, sep = format_instance_header(currency, show_index)

    if title:
        print(f"\n{title}")
    print(sep)
    print(header)
    print(sep)

    for idx, inst in enumerate(instances, 1):
        row = format_instance_row(inst, currency, show_index, idx)
        print(row)

    print(sep)
    print(f"Total: {len(instances)} instances")


def format_instance_detail(
    inst: VastInstance,
    currency: Optional[CurrencySettings] = None,
) -> str:
    """
    Format detailed information for a single VastInstance.

    Args:
        inst: VastInstance to format
        currency: Currency settings (loads from config if None)

    Returns:
        Multi-line formatted string with all instance details
    """
    if currency is None:
        currency = get_currency_settings()

    lines = []
    lines.append(f"Instance: {inst.id}")
    lines.append(f"  Status: {inst.actual_status or 'unknown'}")

    # GPU info
    gpu = inst.gpu_name or "N/A"
    gpus = inst.num_gpus or 1
    vram_gb = inst.gpu_memory_gb
    if vram_gb:
        total_vram_gb = vram_gb * gpus
        vram = f"{total_vram_gb:.0f} GB total"
    else:
        vram = "N/A"
    lines.append(f"  GPU: {gpu} x{gpus} ({vram})")

    if inst.gpu_util is not None:
        lines.append(f"  GPU Util: {inst.gpu_util:.1f}%")
    if inst.gpu_temp is not None:
        lines.append(f"  GPU Temp: {inst.gpu_temp:.0f}°C")

    # Pricing
    if inst.dph_total:
        price_str = currency.format_price(inst.dph_total)
        lines.append(f"  Price: {price_str}/hr")
    if inst.storage_cost:
        storage_str = currency.format_price(inst.storage_cost)
        lines.append(f"  Storage: {storage_str}/hr")

    # CPU info
    if inst.cpu_name:
        lines.append(f"  CPU: {inst.cpu_name}")
    if inst.cpu_cores:
        lines.append(f"  CPU Cores: {inst.cpu_cores}")
    if inst.cpu_ram:
        lines.append(f"  CPU RAM: {inst.cpu_ram / 1024:.0f} GB")

    # Disk info
    if inst.disk_space:
        lines.append(f"  Disk: {inst.disk_space:.0f} GB")
    if inst.disk_usage is not None:
        lines.append(f"  Disk Used: {inst.disk_usage:.1f}%")

    # Network/SSH info
    if inst.ssh_host and inst.ssh_port:
        lines.append(f"  SSH (proxy): root@{inst.ssh_host} -p {inst.ssh_port}")
    if inst.public_ipaddr and inst.direct_port_start:
        lines.append(f"  SSH (direct): root@{inst.public_ipaddr} -p {inst.direct_port_start}")

    # Location info
    if inst.geolocation or inst.country_code:
        location = inst.geolocation or inst.country_code
        lines.append(f"  Location: {location}")

    # Reliability
    if inst.reliability2 is not None:
        lines.append(f"  Reliability: {inst.reliability2:.1%}")

    # Template/Image
    if inst.template_name:
        lines.append(f"  Template: {inst.template_name}")
    if inst.label:
        lines.append(f"  Label: {inst.label}")

    return "\n".join(lines)


def print_instance_detail(inst: VastInstance) -> None:
    """Print detailed information for a single VastInstance."""
    print(format_instance_detail(inst))


def format_instance_brief(
    inst: VastInstance,
    currency: Optional[CurrencySettings] = None,
) -> str:
    """
    Format a brief one-line summary of a VastInstance.

    Args:
        inst: VastInstance to format
        currency: Currency settings (loads from config if None)

    Returns:
        Brief one-line summary
    """
    if currency is None:
        currency = get_currency_settings()

    status = inst.actual_status or "unknown"
    gpu = inst.gpu_name or "N/A"
    gpus = inst.num_gpus or 1
    price = currency.format_price(inst.dph_total) if inst.dph_total else "N/A"

    return f"#{inst.id} {status} - {gpu} x{gpus} @ {price}/hr"

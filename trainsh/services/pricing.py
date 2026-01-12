# Pricing module for tmux-trainsh
# Provides currency exchange rates and cost calculations

import os
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List, Any
from pathlib import Path
import urllib.request
import urllib.error

from ..constants import CONFIG_DIR


# ============================================================
# Currency Types
# ============================================================

class Currency(str, Enum):
    USD = "USD"
    JPY = "JPY"
    HKD = "HKD"
    CNY = "CNY"
    EUR = "EUR"
    GBP = "GBP"
    KRW = "KRW"
    TWD = "TWD"

    @property
    def symbol(self) -> str:
        symbols = {
            "USD": "$",
            "JPY": "¥",
            "HKD": "HK$",
            "CNY": "¥",
            "EUR": "€",
            "GBP": "£",
            "KRW": "₩",
            "TWD": "NT$",
        }
        return symbols.get(self.value, "$")

    @property
    def label(self) -> str:
        labels = {
            "USD": "US Dollar",
            "JPY": "Japanese Yen",
            "HKD": "Hong Kong Dollar",
            "CNY": "Chinese Yuan",
            "EUR": "Euro",
            "GBP": "British Pound",
            "KRW": "Korean Won",
            "TWD": "Taiwan Dollar",
        }
        return labels.get(self.value, self.value)


# ============================================================
# Exchange Rates
# ============================================================

@dataclass
class ExchangeRates:
    """Exchange rates relative to USD."""
    base: str = "USD"
    rates: Dict[str, float] = field(default_factory=dict)
    updated_at: str = ""

    def __post_init__(self):
        if not self.rates:
            # Default fallback rates (approximate)
            self.rates = {
                "USD": 1.0,
                "JPY": 149.0,
                "HKD": 7.8,
                "CNY": 7.2,
                "EUR": 0.92,
                "GBP": 0.79,
                "KRW": 1350.0,
                "TWD": 32.0,
            }
        if not self.updated_at:
            self.updated_at = datetime.utcnow().isoformat()

    def get_rate(self, currency: str) -> float:
        return self.rates.get(currency, 1.0)

    def convert(self, amount: float, from_currency: str, to_currency: str) -> float:
        if from_currency == to_currency:
            return amount
        from_rate = self.get_rate(from_currency)
        to_rate = self.get_rate(to_currency)
        amount_usd = amount / from_rate if from_currency != "USD" else amount
        return amount_usd * to_rate if to_currency != "USD" else amount_usd


def fetch_exchange_rates() -> ExchangeRates:
    """Fetch exchange rates from free API (frankfurter.app)."""
    url = "https://api.frankfurter.app/latest?from=USD&to=JPY,HKD,CNY,EUR,GBP,KRW,TWD"

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())

        rates = {"USD": 1.0}
        if "rates" in data:
            rates.update(data["rates"])

        return ExchangeRates(
            base="USD",
            rates=rates,
            updated_at=datetime.utcnow().isoformat(),
        )
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"Failed to fetch exchange rates: {e}")
        return ExchangeRates()


# ============================================================
# Colab Pricing
# ============================================================

@dataclass
class ColabGpuPricing:
    """GPU pricing in compute units per hour."""
    gpu_name: str
    units_per_hour: float


def default_colab_gpu_pricing() -> List[ColabGpuPricing]:
    return [
        ColabGpuPricing("T4", 1.96),
        ColabGpuPricing("L4", 3.72),
        ColabGpuPricing("A100", 12.29),
        ColabGpuPricing("V100", 5.36),
    ]


@dataclass
class ColabSubscription:
    """Colab subscription settings."""
    name: str = "Colab Pro"
    price: float = 11.99
    currency: str = "USD"
    total_units: float = 100.0


@dataclass
class ColabGpuHourlyPrice:
    """Calculated price per hour for a Colab GPU."""
    gpu_name: str
    units_per_hour: float
    price_usd_per_hour: float
    price_original_currency_per_hour: float
    original_currency: str


def calculate_colab_pricing(
    subscription: ColabSubscription,
    gpu_pricing: List[ColabGpuPricing],
    exchange_rates: ExchangeRates,
) -> List[ColabGpuHourlyPrice]:
    """Calculate Colab GPU hourly prices based on subscription."""
    exchange_rate = exchange_rates.get_rate(subscription.currency)

    # Calculate price per unit in USD
    subscription_price_usd = subscription.price / exchange_rate
    price_per_unit_usd = subscription_price_usd / subscription.total_units

    results = []
    for gpu in gpu_pricing:
        price_usd_per_hour = gpu.units_per_hour * price_per_unit_usd
        price_original = price_usd_per_hour * exchange_rate

        results.append(ColabGpuHourlyPrice(
            gpu_name=gpu.gpu_name,
            units_per_hour=gpu.units_per_hour,
            price_usd_per_hour=price_usd_per_hour,
            price_original_currency_per_hour=price_original,
            original_currency=subscription.currency,
        ))

    return results


# ============================================================
# Vast.ai Pricing
# ============================================================

@dataclass
class VastPricingRates:
    """Vast.ai specific pricing rates."""
    storage_per_gb_month: float = 0.15  # USD
    network_egress_per_gb: float = 0.0
    network_ingress_per_gb: float = 0.0


@dataclass
class HostCostBreakdown:
    """Calculated cost breakdown for a host."""
    host_id: str
    host_name: Optional[str] = None
    gpu_per_hour_usd: float = 0.0
    storage_per_hour_usd: float = 0.0
    total_per_hour_usd: float = 0.0
    total_per_day_usd: float = 0.0
    total_per_month_usd: float = 0.0
    storage_gb: float = 0.0
    source: str = "manual"  # "vast_api", "manual", "colab"


def calculate_host_cost(
    host_id: str,
    gpu_hourly_usd: float,
    storage_gb: float = 0.0,
    vast_rates: Optional[VastPricingRates] = None,
    host_name: Optional[str] = None,
    source: str = "manual",
) -> HostCostBreakdown:
    """Calculate cost breakdown for a host."""
    rates = vast_rates or VastPricingRates()

    # Calculate storage cost per hour
    storage_per_month = storage_gb * rates.storage_per_gb_month
    storage_per_hour = storage_per_month / (30.0 * 24.0)

    total_per_hour = gpu_hourly_usd + storage_per_hour
    total_per_day = total_per_hour * 24.0
    total_per_month = total_per_day * 30.0

    return HostCostBreakdown(
        host_id=host_id,
        host_name=host_name,
        gpu_per_hour_usd=gpu_hourly_usd,
        storage_per_hour_usd=storage_per_hour,
        total_per_hour_usd=total_per_hour,
        total_per_day_usd=total_per_day,
        total_per_month_usd=total_per_month,
        storage_gb=storage_gb,
        source=source,
    )


# ============================================================
# Pricing Store (persistent settings)
# ============================================================

PRICING_FILE = CONFIG_DIR / "pricing.json"


@dataclass
class PricingSettings:
    """Complete pricing settings (persisted)."""
    colab_subscription: ColabSubscription = field(default_factory=ColabSubscription)
    colab_gpu_pricing: List[Dict[str, Any]] = field(default_factory=list)
    vast_rates: VastPricingRates = field(default_factory=VastPricingRates)
    exchange_rates: ExchangeRates = field(default_factory=ExchangeRates)
    display_currency: str = "USD"

    def __post_init__(self):
        if not self.colab_gpu_pricing:
            self.colab_gpu_pricing = [
                {"gpu_name": g.gpu_name, "units_per_hour": g.units_per_hour}
                for g in default_colab_gpu_pricing()
            ]


def load_pricing_settings() -> PricingSettings:
    """Load pricing settings from file."""
    if not PRICING_FILE.exists():
        return PricingSettings()

    try:
        with open(PRICING_FILE, "r") as f:
            data = json.load(f)

        settings = PricingSettings()

        if "colab_subscription" in data:
            cs = data["colab_subscription"]
            settings.colab_subscription = ColabSubscription(
                name=cs.get("name", "Colab Pro"),
                price=cs.get("price", 11.99),
                currency=cs.get("currency", "USD"),
                total_units=cs.get("total_units", 100.0),
            )

        if "colab_gpu_pricing" in data:
            settings.colab_gpu_pricing = data["colab_gpu_pricing"]

        if "vast_rates" in data:
            vr = data["vast_rates"]
            settings.vast_rates = VastPricingRates(
                storage_per_gb_month=vr.get("storage_per_gb_month", 0.15),
                network_egress_per_gb=vr.get("network_egress_per_gb", 0.0),
                network_ingress_per_gb=vr.get("network_ingress_per_gb", 0.0),
            )

        if "exchange_rates" in data:
            er = data["exchange_rates"]
            settings.exchange_rates = ExchangeRates(
                base=er.get("base", "USD"),
                rates=er.get("rates", {}),
                updated_at=er.get("updated_at", ""),
            )

        if "display_currency" in data:
            settings.display_currency = data["display_currency"]

        return settings
    except (json.JSONDecodeError, KeyError):
        return PricingSettings()


def save_pricing_settings(settings: PricingSettings) -> None:
    """Save pricing settings to file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    data = {
        "colab_subscription": asdict(settings.colab_subscription),
        "colab_gpu_pricing": settings.colab_gpu_pricing,
        "vast_rates": asdict(settings.vast_rates),
        "exchange_rates": asdict(settings.exchange_rates),
        "display_currency": settings.display_currency,
    }

    with open(PRICING_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ============================================================
# Helper Functions
# ============================================================

def format_currency(amount: float, currency: str, decimals: int = 2) -> str:
    """Format amount with currency symbol."""
    try:
        curr = Currency(currency)
        symbol = curr.symbol
    except ValueError:
        symbol = "$"
    return f"{symbol}{amount:.{decimals}f}"


def format_price_per_hour(amount_usd: float, currency: str, rates: ExchangeRates) -> str:
    """Format hourly price in the specified currency."""
    converted = rates.convert(amount_usd, "USD", currency)
    return f"{format_currency(converted, currency)}/hr"


def refresh_exchange_rates() -> ExchangeRates:
    """Fetch and save new exchange rates."""
    rates = fetch_exchange_rates()
    settings = load_pricing_settings()
    settings.exchange_rates = rates
    save_pricing_settings(settings)
    return rates

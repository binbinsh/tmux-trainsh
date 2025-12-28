import type { Currency, ExchangeRates } from "./types";

export const CURRENCIES: { value: Currency; label: string; symbol: string }[] = [
  { value: "USD", label: "US Dollar", symbol: "$" },
  { value: "JPY", label: "Japanese Yen", symbol: "¥" },
  { value: "HKD", label: "Hong Kong Dollar", symbol: "HK$" },
  { value: "CNY", label: "Chinese Yuan", symbol: "¥" },
  { value: "EUR", label: "Euro", symbol: "€" },
  { value: "GBP", label: "British Pound", symbol: "£" },
  { value: "KRW", label: "Korean Won", symbol: "₩" },
  { value: "TWD", label: "Taiwan Dollar", symbol: "NT$" },
];

export function getCurrencySymbol(currency: Currency): string {
  return CURRENCIES.find((c) => c.value === currency)?.symbol ?? "$";
}

export function getCurrencyLabel(currency: Currency): string {
  return CURRENCIES.find((c) => c.value === currency)?.label ?? currency;
}

export function getExchangeRate(rates: ExchangeRates, currency: Currency): number {
  return rates.rates[currency] ?? 1;
}

export function convertCurrency(
  amount: number,
  from: Currency,
  to: Currency,
  rates: ExchangeRates
): number {
  if (from === to) {
    return amount;
  }
  const fromRate = getExchangeRate(rates, from);
  const toRate = getExchangeRate(rates, to);
  const amountUsd = from === "USD" ? amount : amount / fromRate;
  return to === "USD" ? amountUsd : amountUsd * toRate;
}

export function formatCurrency(amount: number, currency: Currency, decimals = 2): string {
  const symbol = getCurrencySymbol(currency);
  return `${symbol}${amount.toFixed(decimals)}`;
}

export function formatConvertedPrice(
  amount: number,
  from: Currency,
  to: Currency,
  rates: ExchangeRates,
  decimals = 2
): string {
  const converted = convertCurrency(amount, from, to, rates);
  return formatCurrency(converted, to, decimals);
}

export function formatPriceWithRates(
  amount: number,
  from: Currency,
  to: Currency,
  rates: ExchangeRates | null | undefined,
  decimals = 2
): string {
  if (!rates) {
    return formatCurrency(amount, from, decimals);
  }
  return formatConvertedPrice(amount, from, to, rates, decimals);
}

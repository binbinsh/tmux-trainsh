function normalizeGpuSuffix(raw: string): string {
  const upper = raw.toUpperCase();
  if (upper === "TI") return "Ti";
  if (upper === "SUPER") return "SUPER";
  if (upper === "D") return "D";
  if (upper === "LAPTOP") return "Laptop";
  return raw;
}

export function getGpuModelShortName(fullName: string): string {
  const trimmed = fullName.trim();
  if (!trimmed) return "";

  // Apple Silicon
  const appleMatch = trimmed.match(/\bM(\d+)\s*(Pro|Max|Ultra)?\b/i);
  if (appleMatch) {
    return appleMatch[2] ? `M${appleMatch[1]} ${appleMatch[2]}` : `M${appleMatch[1]}`;
  }

  // Common datacenter / workstation models
  const knownModelMatch = trimmed.match(/\b(A100|H100|V100|T4|L40S?|A40|A6000|A5000|A4000)\b/i);
  if (knownModelMatch) return knownModelMatch[1].toUpperCase();

  // Consumer GPUs: remove vendor prefixes and keep just the model number (+ optional suffix)
  const rtxMatch = trimmed.match(/\b(?:RTX|GTX)\s*([0-9]{3,4})(?:\s*(Ti|SUPER|D|Laptop))?\b/i);
  if (rtxMatch) {
    const suffix = rtxMatch[2] ? normalizeGpuSuffix(rtxMatch[2]) : "";
    if (!suffix) return rtxMatch[1];
    // "5090D" is typically written without a space; keep "Ti/SUPER/Laptop" with a space.
    return suffix === "D" ? `${rtxMatch[1]}${suffix}` : `${rtxMatch[1]} ${suffix}`;
  }

  // Fallback: prefer a standalone 3-4 digit model number, otherwise keep the original (truncated).
  const numericMatch = trimmed.match(/\b([0-9]{3,4})\b/);
  if (numericMatch) return numericMatch[1];

  return trimmed.length > 12 ? `${trimmed.slice(0, 12)}...` : trimmed;
}

export function formatGpuCountLabel(fullName: string, count?: number | null): string {
  const model = getGpuModelShortName(fullName);
  const gpuCount = typeof count === "number" && Number.isFinite(count) ? count : 1;
  return gpuCount > 1 ? `${gpuCount}x ${model}` : model;
}

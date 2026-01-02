/**
 * Cloudflare R2 related components and utilities
 *
 * Pricing reference: https://developers.cloudflare.com/r2/pricing/
 */

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { storageApi, usePricingSettings } from "../lib/tauri-api";
import type { StorageUsage } from "../lib/types";
import { formatPriceWithRates } from "../lib/currency";

// ============================================================
// R2 Pricing Constants (as of 2025)
// ============================================================

export const R2_PRICING = {
  storage_per_gb_month: 0.015, // $0.015 / GB-month
  class_a_per_million: 4.5, // $4.50 / million requests
  class_b_per_million: 0.36, // $0.36 / million requests
  free_storage_gb: 10,
  free_class_a_million: 1,
  free_class_b_million: 10,
};

// ============================================================
// Helper Functions
// ============================================================

export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`;
}

/**
 * Calculate R2 monthly storage cost for a given GB usage
 * Accounts for free tier (10 GB)
 */
export function calculateR2MonthlyCost(usedGb: number): number {
  return Math.max(0, usedGb - R2_PRICING.free_storage_gb) * R2_PRICING.storage_per_gb_month;
}

/**
 * Calculate R2 monthly storage cost for a single bucket (no free tier deduction)
 * Use this for per-bucket display
 */
export function calculateR2BucketCost(usedGb: number): number {
  return usedGb * R2_PRICING.storage_per_gb_month;
}

// ============================================================
// R2 Pricing Calculator Component
// ============================================================

export function R2PricingCalculator() {
  const [usages, setUsages] = useState<StorageUsage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [classAOps, setClassAOps] = useState("0.5"); // in millions
  const [classBOps, setClassBOps] = useState("5"); // in millions
  const pricingQuery = usePricingSettings();
  const displayCurrency = pricingQuery.data?.display_currency ?? "USD";
  const exchangeRates = pricingQuery.data?.exchange_rates;
  const formatUsd = (value: number, decimals = 2) =>
    formatPriceWithRates(value, "USD", displayCurrency, exchangeRates, decimals);

  const fetchUsages = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await storageApi.getR2Usages();
      setUsages(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  // Calculate totals
  const totalStorageGb = usages.reduce((sum, u) => sum + u.used_gb, 0);
  const totalObjects = usages.reduce((sum, u) => sum + (u.object_count || 0), 0);
  const classA = parseFloat(classAOps) || 0;
  const classB = parseFloat(classBOps) || 0;

  // Calculate costs (with free tier deduction)
  const storageCost = calculateR2MonthlyCost(totalStorageGb);
  const classACost = Math.max(0, classA - R2_PRICING.free_class_a_million) * R2_PRICING.class_a_per_million;
  const classBCost = Math.max(0, classB - R2_PRICING.free_class_b_million) * R2_PRICING.class_b_per_million;
  const totalCost = storageCost + classACost + classBCost;

  return (
    <div className="grid gap-3">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium">R2 Storage Cost</div>
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="font-mono">
            {formatUsd(totalCost, 2)}/mo
          </Badge>
          <Button
            size="sm"
            variant="outline"
            onClick={fetchUsages}
            disabled={loading}
          >
            {loading && <Loader2 className="h-4 w-4 animate-spin" />}
            {usages.length > 0 ? "Refresh" : "Fetch Usage"}
          </Button>
        </div>
      </div>

      {error && (
        <div className="text-xs text-danger bg-danger/10 p-2 rounded-lg">
          {error}
        </div>
      )}

      {/* R2 Bucket List */}
      {usages.length > 0 && (
        <div className="doppio-card overflow-hidden">
          <div className="max-h-[180px] overflow-auto">
            <Table>
              <TableHeader className="bg-muted/50">
                <TableRow className="border-border text-xs text-muted-foreground hover:bg-muted/50">
                  <TableHead className="px-3 py-2 text-left font-medium">Bucket</TableHead>
                  <TableHead className="px-3 py-2 text-right font-medium w-[120px]">Objects</TableHead>
                  <TableHead className="px-3 py-2 text-right font-medium w-[140px]">Size</TableHead>
                  <TableHead className="px-3 py-2 text-right font-medium w-[110px]">Cost</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {usages.map((u) => {
                  const bucketCost = calculateR2BucketCost(u.used_gb);
                  return (
                    <TableRow key={u.storage_id} className="hover:bg-muted/40 transition-colors border-border">
                      <TableCell className="px-3 py-2">
                        <div className="flex flex-col min-w-0">
                          <span className="font-medium truncate">{u.storage_name}</span>
                          <span className="text-xs text-muted-foreground truncate">{u.bucket_name}</span>
                        </div>
                      </TableCell>
                      <TableCell className="px-3 py-2 text-right font-mono text-xs text-foreground/80">
                        {u.object_count?.toLocaleString() ?? "-"}
                      </TableCell>
                      <TableCell className="px-3 py-2 text-right font-mono text-xs text-foreground/80">
                        {formatBytes(u.used_bytes)}
                      </TableCell>
                      <TableCell className="px-3 py-2 text-right font-mono text-xs text-warning">
                        {formatUsd(bucketCost, 2)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </div>
      )}

      {usages.length === 0 && !loading && (
        <div className="text-xs text-muted-foreground text-center py-3 bg-muted/50 rounded-lg border border-border">
          Click "Fetch Usage" to load R2 bucket sizes from Storage
        </div>
      )}

      {/* Manual ops input + summary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="flex flex-col gap-1 p-3 bg-muted/50 rounded-lg border border-border">
          <span className="text-xs text-muted-foreground">Total Storage</span>
          <span className="font-mono text-sm">{totalStorageGb.toFixed(2)} GB</span>
          <span className="text-xs text-muted-foreground">{totalObjects.toLocaleString()} objects</span>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="r2-class-a">Class A Ops (M/mo)</Label>
          <Input
            id="r2-class-a"
            type="number"
            inputMode="decimal"
            min={0}
            step={0.1}
            value={classAOps}
            onChange={(e) => setClassAOps(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Free: {R2_PRICING.free_class_a_million}M
          </p>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="r2-class-b">Class B Ops (M/mo)</Label>
          <Input
            id="r2-class-b"
            type="number"
            inputMode="decimal"
            min={0}
            step={0.1}
            value={classBOps}
            onChange={(e) => setClassBOps(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Free: {R2_PRICING.free_class_b_million}M
          </p>
        </div>
      </div>

      {/* Cost breakdown */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-2 text-xs">
        <div className="flex justify-between p-2 bg-muted/50 rounded-lg border border-border">
          <span className="text-muted-foreground">Storage</span>
          <span className="font-mono">{formatUsd(storageCost, 2)}</span>
        </div>
        <div className="flex justify-between p-2 bg-muted/50 rounded-lg border border-border">
          <span className="text-muted-foreground">Class A</span>
          <span className="font-mono">{formatUsd(classACost, 2)}</span>
        </div>
        <div className="flex justify-between p-2 bg-muted/50 rounded-lg border border-border">
          <span className="text-muted-foreground">Class B</span>
          <span className="font-mono">{formatUsd(classBCost, 2)}</span>
        </div>
        <div className="flex justify-between p-2 bg-success/10 rounded-lg border border-success/20">
          <span className="text-muted-foreground">Egress</span>
          <span className="font-mono text-success">Free</span>
        </div>
      </div>

      {loading && usages.length === 0 && (
        <div className="flex items-center justify-center py-2 text-xs text-muted-foreground gap-2">
          <Loader2 className="h-4 w-4 animate-spin" />
          Fetching usage...
        </div>
      )}

      <p className={cn("text-xs text-muted-foreground", loading && "opacity-70")}>
        Storage: {formatUsd(R2_PRICING.storage_per_gb_month, 4)}/GB (10GB free) • Class A:{" "}
        {formatUsd(R2_PRICING.class_a_per_million, 2)}/M (1M free) • Class B:{" "}
        {formatUsd(R2_PRICING.class_b_per_million, 2)}/M (10M free) •{" "}
        <a
          href="https://developers.cloudflare.com/r2/pricing/"
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary hover:underline"
        >
          Docs
        </a>
      </p>
    </div>
  );
}

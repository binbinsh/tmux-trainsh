/**
 * Cloudflare R2 related components and utilities
 * 
 * Pricing reference: https://developers.cloudflare.com/r2/pricing/
 */

import {
  Chip,
  Input,
  Table,
  TableBody,
  TableCell,
  TableColumn,
  TableHeader,
  TableRow,
} from "@nextui-org/react";
import { Button } from "./ui";
import { useState } from "react";
import { storageApi } from "../lib/tauri-api";
import type { StorageUsage } from "../lib/types";

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
          <Chip size="sm" variant="flat" color="primary">
            ${totalCost.toFixed(2)}/mo
          </Chip>
          <Button
            size="sm"
            variant="flat"
            onPress={fetchUsages}
            isLoading={loading}
          >
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
        <Table removeWrapper aria-label="R2 bucket usage" classNames={{ base: "max-h-[160px] overflow-auto" }}>
          <TableHeader>
            <TableColumn>Bucket</TableColumn>
            <TableColumn width={100}>Objects</TableColumn>
            <TableColumn width={100}>Size</TableColumn>
            <TableColumn width={80}>Cost</TableColumn>
          </TableHeader>
          <TableBody>
            {usages.map((u) => {
              const bucketCost = calculateR2BucketCost(u.used_gb);
              return (
                <TableRow key={u.storage_id}>
                  <TableCell>
                    <div className="flex flex-col">
                      <span className="font-medium">{u.storage_name}</span>
                      <span className="text-xs text-foreground/50">{u.bucket_name}</span>
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {u.object_count?.toLocaleString() ?? "-"}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {formatBytes(u.used_bytes)}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-warning">
                    ${bucketCost.toFixed(2)}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}

      {usages.length === 0 && !loading && (
        <div className="text-xs text-foreground/50 text-center py-3 bg-content2 rounded-lg">
          Click "Fetch Usage" to load R2 bucket sizes from Storage
        </div>
      )}

      {/* Manual ops input + summary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="flex flex-col gap-1 p-3 bg-content2 rounded-lg">
          <span className="text-xs text-foreground/60">Total Storage</span>
          <span className="font-mono text-sm">{totalStorageGb.toFixed(2)} GB</span>
          <span className="text-xs text-foreground/40">{totalObjects.toLocaleString()} objects</span>
        </div>
        <Input
          label="Class A Ops (M/mo)"
          type="number"
          value={classAOps}
          onValueChange={setClassAOps}
          size="sm"
          variant="bordered"
          description={`Free: ${R2_PRICING.free_class_a_million}M`}
        />
        <Input
          label="Class B Ops (M/mo)"
          type="number"
          value={classBOps}
          onValueChange={setClassBOps}
          size="sm"
          variant="bordered"
          description={`Free: ${R2_PRICING.free_class_b_million}M`}
        />
      </div>

      {/* Cost breakdown */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-2 text-xs">
        <div className="flex justify-between p-2 bg-content2 rounded-lg">
          <span className="text-foreground/60">Storage</span>
          <span className="font-mono">${storageCost.toFixed(2)}</span>
        </div>
        <div className="flex justify-between p-2 bg-content2 rounded-lg">
          <span className="text-foreground/60">Class A</span>
          <span className="font-mono">${classACost.toFixed(2)}</span>
        </div>
        <div className="flex justify-between p-2 bg-content2 rounded-lg">
          <span className="text-foreground/60">Class B</span>
          <span className="font-mono">${classBCost.toFixed(2)}</span>
        </div>
        <div className="flex justify-between p-2 bg-success/10 rounded-lg">
          <span className="text-foreground/60">Egress</span>
          <span className="font-mono text-success">Free</span>
        </div>
      </div>

      <p className="text-xs text-foreground/50">
        Storage: ${R2_PRICING.storage_per_gb_month}/GB (10GB free) • Class A: $4.50/M (1M free) • Class B: $0.36/M (10M free) •{" "}
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


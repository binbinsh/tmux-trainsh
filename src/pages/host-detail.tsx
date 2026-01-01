import {
  Card,
  CardBody,
  CardHeader,
  Chip,
  Divider,
  Input,
  Skeleton,
  Spinner,
  Tab,
  Tabs,
  Modal,
  ModalContent,
  ModalHeader,
  ModalBody,
  ModalFooter,
  useDisclosure,
  Textarea,
  Progress,
  Tooltip,
} from "@nextui-org/react";
import { Button } from "../components/ui";
import { AppIcon } from "../components/AppIcon";
import type {
  GpuInfo,
  Host,
  HostStatus,
  ScamalyticsIpSource,
  ScamalyticsMetric,
  Storage,
  SystemInfo,
  VastInstance,
} from "../lib/types";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useNavigate } from "@tanstack/react-router";
import { useMemo, useState, useEffect } from "react";
import { copyText } from "../lib/clipboard";
import {
  getConfig,
  hostApi,
  termOpenSshTmux,
  useHostCostBreakdown,
  usePricingSettings,
  useStorages,
  useSyncVastPricing,
  useVastInstances,
  sshCheck,
  vastAttachSshKey,
  vastFetchSystemInfo,
  vastGetInstance,
  vastStartInstance,
  vastStopInstance,
  vastTestConnection,
  gpuLookupCapability,
  type RemoteTmuxSession,
} from "../lib/tauri-api";
import { TmuxSessionSelectModal } from "../components/host/TmuxSessionSelectModal";
import { StatusBadge } from "../components/shared/StatusBadge";
import { formatPriceWithRates } from "../lib/currency";

// Icons
function IconArrowLeft() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
    </svg>
  );
}

function getStorageIconNode(storage: Storage) {
  switch (storage.backend.type) {
    case "google_drive":
      return <AppIcon name="googledrive" className="w-5 h-5" alt="Google Drive" />;
    case "cloudflare_r2":
      return <AppIcon name="cloudflare" className="w-5 h-5" alt="Cloudflare R2" />;
    case "ssh_remote":
      return <AppIcon name="ssh" className="w-5 h-5" alt="SSH" />;
    case "smb":
      return <AppIcon name="smb" className="w-5 h-5" alt="SMB" />;
    default:
      return <span>{storage.icon || "📁"}</span>;
  }
}

function IconTerminal() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 7.5l3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0021 18V6a2.25 2.25 0 00-2.25-2.25H5.25A2.25 2.25 0 003 6v12a2.25 2.25 0 002.25 2.25z" />
    </svg>
  );
}

function IconRefresh() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
    </svg>
  );
}

function IconTrash() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
    </svg>
  );
}

function IconEdit() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
    </svg>
  );
}

function IconPlay() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 3l14 9-14 9V3z" />
    </svg>
  );
}

function IconStop() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <rect x="6" y="6" width="12" height="12" rx="1.5" />
    </svg>
  );
}

const SCAMALYTICS_SCORE_TOTAL = 100;

function pickFirst(...values: Array<string | null | undefined>) {
  for (const value of values) {
    const trimmed = value?.trim();
    if (trimmed) return trimmed;
  }
  return null;
}

function metricToString(value?: ScamalyticsMetric | null) {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return null;
    return Number.isInteger(value) ? `${value}` : `${value}`;
  }
  const trimmed = value.trim();
  if (!trimmed) return null;
  const numeric = Number(trimmed);
  if (!Number.isFinite(numeric)) return null;
  return Number.isInteger(numeric) ? `${numeric}` : `${numeric}`;
}

function formatScore(score?: ScamalyticsMetric | null, total = SCAMALYTICS_SCORE_TOTAL) {
  const scoreStr = metricToString(score);
  if (!scoreStr) return null;
  return `${scoreStr} / ${total}`;
}

function formatCountry(country?: string | null, code?: string | null) {
  const name = pickFirst(country);
  const short = pickFirst(code);
  if (name && short && !name.includes(short)) {
    return `${name} (${short})`;
  }
  return name || short;
}

function formatCity(city?: string | null, state?: string | null) {
  const name = pickFirst(city);
  const region = pickFirst(state);
  if (name && region) {
    if (name.includes(region)) return name;
    return `${name}, ${region}`;
  }
  return name;
}

function formatAsn(asn?: string | null, name?: string | null) {
  const number = pickFirst(asn);
  const label = pickFirst(name);
  if (number && label) {
    return `${number} (${label})`;
  }
  return number || label;
}

function pickAsn(sources: Array<ScamalyticsIpSource | null | undefined>) {
  for (const source of sources) {
    if (!source) continue;
    const value = formatAsn(source.asn, source.as_name);
    if (value) return value;
  }
  return null;
}

function collectTrueFlags(entries: Array<{ label: string; value: boolean | null | undefined }>) {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const entry of entries) {
    if (entry.value === true && !seen.has(entry.label)) {
      out.push(entry.label);
      seen.add(entry.label);
    }
  }
  return out.length ? out.join(", ") : null;
}

function IconCopy() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" />
    </svg>
  );
}

function IconCheck() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
    </svg>
  );
}

function IconGpu() {
  return (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
      <rect x="2" y="6" width="20" height="12" rx="2" />
      <path d="M6 10h2v4H6z M10 10h2v4h-2z M14 10h2v4h-2z" fill="currentColor" />
      <path d="M5 6V4M9 6V4M15 6V4M19 6V4M5 18v2M9 18v2M15 18v2M19 18v2" strokeLinecap="round" />
    </svg>
  );
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  if (error && typeof error === "object") {
    const maybeMessage = (error as { message?: unknown }).message;
    if (typeof maybeMessage === "string") return maybeMessage;
    try {
      return JSON.stringify(error);
    } catch {
      return String(error);
    }
  }
  return String(error);
}

// Temperature color helper
function getTempColor(temp: number | null | undefined): string {
  if (temp == null) return "text-foreground/60";
  if (temp < 50) return "text-success";
  if (temp < 70) return "text-warning";
  return "text-danger";
}

function getVastHostStatus(inst: VastInstance): HostStatus {
  const parts = [
    inst.cur_state,
    inst.next_state,
    inst.intended_status,
    inst.actual_status,
  ]
    .filter(Boolean)
    .map((s) => String(s).toLowerCase());
  const v = parts.join(" ");

  if (v.includes("error") || v.includes("failed")) return "error";
  if (v.includes("running") || v.includes("active") || v.includes("online")) return "online";
  if (v.includes("stopped") || v.includes("exited") || v.includes("offline")) return "offline";
  return "connecting";
}

function getVastDisplayName(inst: VastInstance): string {
  return inst.label?.trim() || `vast #${inst.id}`;
}

// Vast.ai Pricing Card Component
function VastPricingCard({
  hostId,
  hostName,
  vastInstanceId,
}: {
  hostId: string;
  hostName: string;
  vastInstanceId: number;
}) {
  const costQuery = useHostCostBreakdown(hostId, hostName);
  const syncMutation = useSyncVastPricing();
  const pricingQuery = usePricingSettings();

  const displayCurrency = pricingQuery.data?.display_currency ?? "USD";
  const exchangeRates = pricingQuery.data?.exchange_rates;
  const formatDisplayPrice = (value: number, decimals = 4) =>
    formatPriceWithRates(value, "USD", displayCurrency, exchangeRates, decimals);

  const handleSync = async () => {
    await syncMutation.mutateAsync({ hostId, vastInstanceId });
  };

  const cost = costQuery.data;
  const isLoading = costQuery.isLoading || syncMutation.isPending;

  return (
    <Card>
      <CardHeader className="flex justify-between items-center">
        <span className="font-semibold">💰 Vast.ai Instance & Pricing</span>
        <Button
          size="sm"
          variant="flat"
          color="primary"
          isLoading={syncMutation.isPending}
          onPress={handleSync}
        >
          Sync Pricing
        </Button>
      </CardHeader>
      <Divider />
      <CardBody className="gap-4">
        <div>
          <p className="text-sm text-foreground/60">Instance ID</p>
          <p className="font-mono">{vastInstanceId}</p>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-4">
            <Spinner size="sm" />
          </div>
        ) : cost ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-sm text-foreground/60">GPU Cost</p>
              <p className="font-mono text-success">{formatDisplayPrice(cost.gpu_per_hour_usd)}/hr</p>
            </div>
            <div>
              <p className="text-sm text-foreground/60">Storage Cost</p>
              <p className="font-mono">{formatDisplayPrice(cost.storage_per_hour_usd, 6)}/hr</p>
              {cost.storage_gb > 0 && (
                <p className="text-xs text-foreground/50">{cost.storage_gb.toFixed(1)} GB</p>
              )}
            </div>
            <div>
              <p className="text-sm text-foreground/60">Total Hourly</p>
              <p className="font-mono font-semibold text-primary">{formatDisplayPrice(cost.total_per_hour_usd)}/hr</p>
            </div>
            <div>
              <p className="text-sm text-foreground/60">Monthly Est.</p>
              <p className="font-mono">{formatDisplayPrice(cost.total_per_month_usd, 2)}/mo</p>
            </div>
          </div>
        ) : (
          <div className="text-sm text-foreground/60">
            Click "Sync Pricing" to fetch pricing from Vast.ai
          </div>
        )}

        {cost && (
          <div className="text-xs text-foreground/50">
            Source: {cost.source === "vast_api" ? "Vast.ai API" : cost.source === "manual" ? "Manual" : "Colab"}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

// GPU Detail Modal Component
function GpuDetailModal({ gpu, isOpen, onClose }: { gpu: GpuInfo | null; isOpen: boolean; onClose: () => void }) {
  if (!gpu) return null;

  const memUsedPct = gpu.memory_used_mb != null 
    ? Math.round((gpu.memory_used_mb / gpu.memory_total_mb) * 100) 
    : 0;
  const memFreeMb = gpu.memory_used_mb != null 
    ? gpu.memory_total_mb - gpu.memory_used_mb 
    : gpu.memory_total_mb;
  const cap = gpu.capability;

  return (
    <Modal isOpen={isOpen} onOpenChange={(open) => !open && onClose()} isDismissable={true} size="2xl" scrollBehavior="inside">
      <ModalContent>
        <ModalHeader className="flex items-center gap-3">
          <IconGpu />
          <div className="flex-1">
            <div className="text-lg">{gpu.name}</div>
            <div className="flex items-center gap-3 text-sm text-foreground/60 font-normal">
              <span>GPU {gpu.index}</span>
              {cap && (
                <>
                  <span>•</span>
                  <span>{cap.architecture}</span>
                  <span>•</span>
                  <span>SM {cap.compute_capability}</span>
                </>
              )}
            </div>
          </div>
        </ModalHeader>
        <ModalBody className="gap-4 pb-6">
          {/* Architecture & Cores */}
          {cap && (
            <>
              <div className="grid grid-cols-5 gap-3">
                <div className="p-3 rounded-lg bg-content2 text-center">
                  <p className="text-xs text-foreground/60 mb-1">CUDA Cores</p>
                  <p className="text-xl font-bold text-primary">{cap.cuda_cores.toLocaleString()}</p>
                </div>
                {cap.tensor_cores && (
                  <div className="p-3 rounded-lg bg-content2 text-center">
                    <p className="text-xs text-foreground/60 mb-1">Tensor Cores</p>
                    <p className="text-xl font-bold text-secondary">{cap.tensor_cores}</p>
                    {cap.tensor_core_gen && (
                      <p className="text-xs text-foreground/60">Gen {cap.tensor_core_gen}</p>
                    )}
                  </div>
                )}
                {cap.rt_cores && (
                  <div className="p-3 rounded-lg bg-content2 text-center">
                    <p className="text-xs text-foreground/60 mb-1">RT Cores</p>
                    <p className="text-xl font-bold text-warning">{cap.rt_cores}</p>
                    {cap.rt_core_gen && (
                      <p className="text-xs text-foreground/60">Gen {cap.rt_core_gen}</p>
                    )}
                  </div>
                )}
                {cap.memory_bandwidth_gbps && (
                  <div className="p-3 rounded-lg bg-content2 text-center">
                    <p className="text-xs text-foreground/60 mb-1">Bandwidth</p>
                    <p className="text-xl font-bold">{cap.memory_bandwidth_gbps}</p>
                    <p className="text-xs text-foreground/60">GB/s</p>
                  </div>
                )}
                <div className="p-3 rounded-lg bg-content2 text-center">
                  <p className="text-xs text-foreground/60 mb-1">VRAM</p>
                  <p className="text-xl font-bold">{(gpu.memory_total_mb / 1024).toFixed(0)}</p>
                  <p className="text-xs text-foreground/60">GB</p>
                </div>
              </div>

              <Divider />

              {/* Compute Performance */}
              <div>
                <p className="text-sm font-medium mb-3">Theoretical Peak Performance (TFLOPS)</p>
                <div className="grid grid-cols-4 gap-3">
                  {cap.fp32_tflops && (
                    <div className="p-2 rounded-lg bg-content2">
                      <div className="flex justify-between items-center">
                        <span className="text-xs font-medium">FP32</span>
                        <span className="text-sm font-bold">{cap.fp32_tflops}</span>
                      </div>
                    </div>
                  )}
                  {cap.tf32_tflops && (
                    <div className="p-2 rounded-lg bg-content2">
                      <div className="flex justify-between items-center">
                        <span className="text-xs font-medium">TF32</span>
                        <span className="text-sm font-bold">{cap.tf32_tflops}</span>
                      </div>
                    </div>
                  )}
                  {cap.fp16_tflops && (
                    <div className="p-2 rounded-lg bg-gradient-to-r from-primary/20 to-primary/10 border border-primary/30">
                      <div className="flex justify-between items-center">
                        <span className="text-xs font-medium text-primary">FP16</span>
                        <span className="text-sm font-bold text-primary">{cap.fp16_tflops}</span>
                      </div>
                    </div>
                  )}
                  {cap.bf16_tflops && (
                    <div className="p-2 rounded-lg bg-content2">
                      <div className="flex justify-between items-center">
                        <span className="text-xs font-medium">BF16</span>
                        <span className="text-sm font-bold">{cap.bf16_tflops}</span>
                      </div>
                    </div>
                  )}
                  {cap.fp8_tflops && (
                    <div className="p-2 rounded-lg bg-gradient-to-r from-success/20 to-success/10 border border-success/30">
                      <div className="flex justify-between items-center">
                        <span className="text-xs font-medium text-success">FP8</span>
                        <span className="text-sm font-bold text-success">{cap.fp8_tflops}</span>
                      </div>
                    </div>
                  )}
                  {cap.fp4_tflops && (
                    <div className="p-2 rounded-lg bg-gradient-to-r from-warning/20 to-warning/10 border border-warning/30">
                      <div className="flex justify-between items-center">
                        <span className="text-xs font-medium text-warning">FP4</span>
                        <span className="text-sm font-bold text-warning">{cap.fp4_tflops}</span>
                      </div>
                    </div>
                  )}
                  {cap.int8_tops && (
                    <div className="p-2 rounded-lg bg-content2">
                      <div className="flex justify-between items-center">
                        <span className="text-xs font-medium">INT8</span>
                        <span className="text-sm font-bold">{cap.int8_tops}</span>
                      </div>
                    </div>
                  )}
                </div>
                <p className="text-xs text-foreground/50 mt-2">* With sparsity where applicable (Blackwell FP4 is new in 5th Gen Tensor Cores)</p>
              </div>

              <Divider />
            </>
          )}

          {/* Runtime Status */}
          <div>
            <p className="text-sm font-medium mb-3">Current Status</p>
            
            {/* VRAM */}
            <div className="mb-4">
              <div className="flex justify-between items-center mb-2">
                <span className="text-xs text-foreground/60">VRAM Usage</span>
                <span className="text-sm">
                  {gpu.memory_used_mb != null && (
                    <>{(gpu.memory_used_mb / 1024).toFixed(1)} / </>
                  )}
                  {(gpu.memory_total_mb / 1024).toFixed(1)} GB
                  {gpu.memory_used_mb != null && (
                    <span className="text-foreground/60 ml-2">({memUsedPct}%)</span>
                  )}
                </span>
              </div>
              <Progress 
                value={memUsedPct} 
                color={memUsedPct > 90 ? "danger" : memUsedPct > 70 ? "warning" : "primary"}
                className="h-2"
              />
              <div className="flex justify-between text-xs text-foreground/50 mt-1">
                <span>Used: {gpu.memory_used_mb != null ? (gpu.memory_used_mb / 1024).toFixed(1) : 0} GB</span>
                <span>Free: {(memFreeMb / 1024).toFixed(1)} GB</span>
              </div>
            </div>

            {/* Utilization */}
            {gpu.utilization != null && (
              <div className="mb-4">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-xs text-foreground/60">GPU Utilization</span>
                  <span className="text-sm font-medium">{gpu.utilization}%</span>
                </div>
                <Progress 
                  value={gpu.utilization} 
                  color={gpu.utilization > 90 ? "success" : gpu.utilization > 50 ? "primary" : "default"}
                  className="h-2"
                />
              </div>
            )}
          </div>

          {/* Quick Stats Grid */}
          <div className="grid grid-cols-4 gap-3">
            {/* Temperature */}
            <div className="p-3 rounded-lg bg-content2 text-center">
              <p className="text-xs text-foreground/60 mb-1">Temp</p>
              <p className={`text-lg font-bold ${getTempColor(gpu.temperature)}`}>
                {gpu.temperature != null ? `${gpu.temperature}°C` : "—"}
              </p>
            </div>

            {/* Power */}
            <div className="p-3 rounded-lg bg-content2 text-center">
              <p className="text-xs text-foreground/60 mb-1">Power</p>
              <p className="text-lg font-bold">
                {gpu.power_draw_w != null ? `${gpu.power_draw_w.toFixed(0)}W` : "—"}
              </p>
              {gpu.power_limit_w != null && (
                <p className="text-xs text-foreground/50">/ {gpu.power_limit_w.toFixed(0)}W</p>
              )}
            </div>

            {/* GPU Clock */}
            <div className="p-3 rounded-lg bg-content2 text-center">
              <p className="text-xs text-foreground/60 mb-1">GPU Clock</p>
              <p className="text-lg font-bold">
                {gpu.clock_graphics_mhz != null ? `${gpu.clock_graphics_mhz}` : "—"}
              </p>
              <p className="text-xs text-foreground/50">MHz</p>
            </div>

            {/* Memory Clock */}
            <div className="p-3 rounded-lg bg-content2 text-center">
              <p className="text-xs text-foreground/60 mb-1">Mem Clock</p>
              <p className="text-lg font-bold">
                {gpu.clock_memory_mhz != null ? `${gpu.clock_memory_mhz}` : "—"}
              </p>
              <p className="text-xs text-foreground/50">MHz</p>
            </div>
          </div>

          {/* Additional Info */}
          <div className="grid grid-cols-4 gap-3 text-sm">
            {gpu.fan_speed != null && (
              <div className="p-2 rounded bg-content2">
                <span className="text-xs text-foreground/60">Fan: </span>
                <span className="font-medium">{gpu.fan_speed}%</span>
              </div>
            )}
            {gpu.pcie_gen != null && gpu.pcie_width != null && (
              <div className="p-2 rounded bg-content2">
                <span className="text-xs text-foreground/60">PCIe: </span>
                <span className="font-medium">Gen{gpu.pcie_gen} x{gpu.pcie_width}</span>
              </div>
            )}
            {gpu.compute_mode && (
              <div className="p-2 rounded bg-content2">
                <span className="text-xs text-foreground/60">Mode: </span>
                <span className="font-medium">{gpu.compute_mode}</span>
              </div>
            )}
            {gpu.driver_version && (
              <div className="p-2 rounded bg-content2">
                <span className="text-xs text-foreground/60">Driver: </span>
                <span className="font-mono text-xs">{gpu.driver_version}</span>
              </div>
            )}
          </div>
        </ModalBody>
      </ModalContent>
    </Modal>
  );
}

type HostDetailMode = "saved" | "vast";

type HostDetailPageProps = {
  hostId: string;
  mode: HostDetailMode;
};

type ScamalyticsTarget = {
  kind: "host" | "ip";
  value: string;
};

export function SavedHostDetailPage() {
  const { id } = useParams({ from: "/hosts/$id" });
  return <HostDetailPage hostId={id} mode="saved" />;
}

export function VastHostDetailPage() {
  const { id } = useParams({ from: "/hosts/vast/$id" });
  return <HostDetailPage hostId={id} mode="vast" />;
}

export function HostDetailPage({ hostId, mode }: HostDetailPageProps) {
  const isVast = mode === "vast";
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const editModal = useDisclosure();
  const gpuModal = useDisclosure();
  const tmuxModal = useDisclosure();
  const deleteModal = useDisclosure();

  // GPU detail state
  const [selectedGpuIndex, setSelectedGpuIndex] = useState<number | null>(null);
  const [copiedSsh, setCopiedSsh] = useState<null | "address" | "direct" | "proxy">(null);
  const pricingSettingsQuery = usePricingSettings();
  const displayCurrency = pricingSettingsQuery.data?.display_currency ?? "USD";
  const exchangeRates = pricingSettingsQuery.data?.exchange_rates;
  const formatUsd = (value: number, decimals = 3) =>
    formatPriceWithRates(value, "USD", displayCurrency, exchangeRates, decimals);

  // Tmux session selection state
  const [remoteTmuxSessions, setRemoteTmuxSessions] = useState<RemoteTmuxSession[]>([]);
  const [isLoadingTmuxSessions, setIsLoadingTmuxSessions] = useState(false);

  // Edit form state
  const [editName, setEditName] = useState("");
  const [editSshHost, setEditSshHost] = useState("");
  const [editSshPort, setEditSshPort] = useState("");
  const [editSshUser, setEditSshUser] = useState("");
  const [editSshKeyPath, setEditSshKeyPath] = useState("");
  const [editCloudflaredHostname, setEditCloudflaredHostname] = useState("");
  const [editEnvVars, setEditEnvVars] = useState<string>(""); // "KEY=value" per line

  const vastInstanceId = Number(hostId);
  const hasValidVastId = Number.isFinite(vastInstanceId) && vastInstanceId > 0;
  const [vastCreatedAt] = useState(() => new Date().toISOString());
  const [vastSystemInfo, setVastSystemInfo] = useState<SystemInfo | null>(null);
  const [vastLastSeenAt, setVastLastSeenAt] = useState<string | null>(null);
  const [vastStatusTarget, setVastStatusTarget] = useState<HostStatus | null>(null);
  const [vastStatusPollUntil, setVastStatusPollUntil] = useState<number | null>(null);

  const cfgQuery = useQuery({
    queryKey: ["config"],
    queryFn: getConfig,
  });
  const vastQuery = useVastInstances();
  const vastInstanceDetailQuery = useQuery({
    queryKey: ["vastInstance", vastInstanceId],
    queryFn: () => vastGetInstance(vastInstanceId),
    enabled: isVast && hasValidVastId,
    staleTime: 10_000,
  });
  const vastInstance = isVast && hasValidVastId
    ? (vastQuery.data ?? []).find((inst) => inst.id === vastInstanceId) ?? null
    : null;
  const vastInstanceDetail = vastInstanceDetailQuery.data ?? vastInstance;
  const vastInstanceForHost = vastInstanceDetail ?? vastInstance;
  const vastGpuCapabilityQuery = useQuery({
    queryKey: ["gpuCapability", vastInstanceDetail?.gpu_name ?? ""],
    queryFn: () => gpuLookupCapability(vastInstanceDetail?.gpu_name ?? ""),
    enabled: isVast && Boolean(vastInstanceDetail?.gpu_name),
    staleTime: 24 * 60 * 60 * 1000,
  });
  const vastDirectPort = vastInstanceDetail?.machine_dir_ssh_port ?? null;
  const sshIdx = vastInstanceDetail?.ssh_idx ?? vastInstance?.ssh_idx ?? null;
  const rawSshPort = vastInstanceDetail?.ssh_port ?? vastInstance?.ssh_port ?? null;
  const normalizedSshIdx = sshIdx
    ? sshIdx.startsWith("ssh")
      ? sshIdx
      : `ssh${sshIdx}`
    : null;
  const proxyHostFromApi = vastInstanceDetail?.ssh_host ?? vastInstance?.ssh_host ?? null;
  const vastProxyHost = proxyHostFromApi?.includes("vast.ai")
    ? proxyHostFromApi
    : normalizedSshIdx
      ? `${normalizedSshIdx}.vast.ai`
      : null;
  const vastProxyPort = rawSshPort != null ? rawSshPort : null;
  const hasDirectSsh = Boolean(vastInstanceDetail?.public_ipaddr && vastDirectPort);
  const hasProxySsh = Boolean((vastProxyHost ?? vastInstanceDetail?.ssh_host ?? vastInstance?.ssh_host) && rawSshPort);
  const canVastConnect = hasDirectSsh || hasProxySsh;
  const canVastExecute = isVast && hasValidVastId;
  const vastPreferredSshMode = cfgQuery.data?.vast.ssh_connection_preference === "direct" ? "direct" : "proxy";
  const vastSshMode = vastPreferredSshMode === "direct"
    ? (hasDirectSsh ? "direct" : hasProxySsh ? "proxy" : null)
    : (hasProxySsh ? "proxy" : hasDirectSsh ? "direct" : null);
  const vastSshHostForMode = vastSshMode === "direct"
    ? (vastInstanceDetail?.public_ipaddr ?? "")
    : (vastProxyHost ?? vastInstanceForHost?.ssh_host ?? "");
  const vastSshPortForMode = vastSshMode === "direct"
    ? (vastDirectPort ?? 22)
    : (vastProxyPort ?? rawSshPort ?? 22);
  const vastHost: Host | null = isVast && vastInstanceForHost
    ? {
        id: `vast-${vastInstanceForHost.id}`,
        name: getVastDisplayName(vastInstanceForHost),
        type: "vast",
        status: getVastHostStatus(vastInstanceForHost),
        ssh: canVastConnect
          ? {
              host: vastSshHostForMode,
              port: vastSshPortForMode,
              user: cfgQuery.data?.vast.ssh_user?.trim() || "root",
              keyPath: cfgQuery.data?.vast.ssh_key_path ?? null,
              extraArgs: [],
            }
          : null,
        vast_instance_id: vastInstanceForHost.id,
        cloudflared_hostname: null,
        env_vars: {},
        gpu_name: vastInstanceForHost.gpu_name,
        num_gpus: vastInstanceForHost.num_gpus,
        system_info: vastSystemInfo,
        created_at: vastCreatedAt,
        last_seen_at: vastLastSeenAt,
      }
    : null;

  const hostQuery = useQuery({
    queryKey: ["hosts", hostId],
    queryFn: () => hostApi.get(hostId),
    enabled: !isVast && !!hostId,
  });

  // Get storages linked to this host
  const storagesQuery = useStorages();
  const linkedStorages = (storagesQuery.data ?? []).filter(
    (s) => s.backend.type === "ssh_remote" && s.backend.host_id === hostId
  );

  // Initialize edit form when host data loads
  useEffect(() => {
    if (!isVast && hostQuery.data) {
      const host = hostQuery.data;
      setEditName(host.name || "");
      setEditSshHost(host.ssh?.host || "");
      setEditSshPort(String(host.ssh?.port || 22));
      setEditSshUser(host.ssh?.user || "root");
      setEditSshKeyPath(host.ssh?.keyPath || host.ssh?.key_path || "");
      setEditCloudflaredHostname(host.cloudflared_hostname || "");
      // Convert env_vars object to multiline string
      const envStr = Object.entries(host.env_vars || {})
        .map(([k, v]) => `${k}=${v}`)
        .join("\n");
      setEditEnvVars(envStr);
    }
  }, [hostQuery.data, isVast]);

  const savedTestMutation = useMutation({
    mutationFn: () => hostApi.testConnection(hostId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["hosts", hostId] });
    },
  });

  const vastTestMutation = useMutation({
    mutationFn: async () => {
      if (!hasValidVastId) {
        return { success: false, message: "Invalid Vast instance id" };
      }
      return await vastTestConnection(vastInstanceId);
    },
  });

  const testMutation = isVast ? vastTestMutation : savedTestMutation;

  const savedRefreshMutation = useMutation({
    mutationFn: () => hostApi.refresh(hostId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["hosts", hostId] });
    },
  });

  const vastRefreshMutation = useMutation({
    mutationFn: async () => {
      if (!hasValidVastId) {
        throw new Error("Invalid Vast instance id");
      }
      return await vastFetchSystemInfo(vastInstanceId);
    },
    onSuccess: (info) => {
      setVastSystemInfo(info);
      setVastLastSeenAt(new Date().toISOString());
      queryClient.invalidateQueries({ queryKey: ["vastInstances"] });
    },
  });

  const refreshMutation = isVast ? vastRefreshMutation : savedRefreshMutation;

  const vastStartMutation = useMutation({
    mutationFn: async () => {
      if (!hasValidVastId) {
        throw new Error("Invalid Vast instance id");
      }
      return await vastStartInstance(vastInstanceId);
    },
    onSuccess: (inst) => {
      queryClient.setQueryData(["vastInstance", vastInstanceId], inst);
      queryClient.setQueryData(["vastInstances"], (prev: VastInstance[] | undefined) => {
        if (!prev) return prev;
        return prev.map((x) => (x.id === inst.id ? inst : x));
      });
      queryClient.invalidateQueries({ queryKey: ["vastInstances"] });
      setVastStatusTarget("online");
      setVastStatusPollUntil(Date.now() + 45_000);
      void vastQuery.refetch();
      void vastInstanceDetailQuery.refetch();
    },
  });

  const vastStopMutation = useMutation({
    mutationFn: async () => {
      if (!hasValidVastId) {
        throw new Error("Invalid Vast instance id");
      }
      return await vastStopInstance(vastInstanceId);
    },
    onSuccess: (inst) => {
      queryClient.setQueryData(["vastInstance", vastInstanceId], inst);
      queryClient.setQueryData(["vastInstances"], (prev: VastInstance[] | undefined) => {
        if (!prev) return prev;
        return prev.map((x) => (x.id === inst.id ? inst : x));
      });
      queryClient.invalidateQueries({ queryKey: ["vastInstances"] });
      setVastStatusTarget("offline");
      setVastStatusPollUntil(Date.now() + 45_000);
      void vastQuery.refetch();
      void vastInstanceDetailQuery.refetch();
    },
  });

  const host = isVast ? vastHost : hostQuery.data;
  const scamalyticsTarget = useMemo<ScamalyticsTarget | null>(() => {
    if (host?.status !== "online") return null;
    if (isVast) {
      if (!hasValidVastId) return null;
      const publicIp = vastInstanceDetail?.public_ipaddr?.trim();
      return publicIp ? { kind: "ip", value: publicIp } : null;
    }
    const trimmedHostId = hostId.trim();
    return trimmedHostId ? { kind: "host", value: trimmedHostId } : null;
  }, [hasValidVastId, host?.status, hostId, isVast, vastInstanceDetail?.public_ipaddr]);
  const scamalyticsConfig = cfgQuery.data?.scamalytics;
  const scamalyticsKey = scamalyticsConfig?.api_key?.trim() ?? "";
  const scamalyticsUser = scamalyticsConfig?.user?.trim() ?? "";
  const hasScamalyticsKey = scamalyticsKey.length > 0;
  const scamalyticsEnabled = hasScamalyticsKey && scamalyticsUser.length > 0;
  const scamalyticsQuery = useQuery({
    queryKey: ["scamalytics", scamalyticsTarget?.kind, scamalyticsTarget?.value],
    queryFn: async () => {
      if (!scamalyticsTarget) {
        throw new Error("Missing Scamalytics target");
      }
      if (scamalyticsTarget.kind === "ip") {
        return await hostApi.scamalyticsInfoForIp(scamalyticsTarget.value);
      }
      return await hostApi.scamalyticsInfoForHost(scamalyticsTarget.value);
    },
    enabled: Boolean(scamalyticsTarget && scamalyticsEnabled),
    staleTime: 10 * 60 * 1000,
  });
  const scamalyticsInfo = scamalyticsTarget ? scamalyticsQuery.data : null;
  const scam = scamalyticsInfo?.scamalytics ?? null;
  const external = scamalyticsInfo?.external_datasources ?? null;
  const dbip = external?.dbip ?? null;
  const maxmind = external?.maxmind_geolite2 ?? null;
  const ip2proxy = external?.ip2proxy ?? null;
  const ip2proxyLite = external?.ip2proxy_lite ?? null;
  const firehol = external?.firehol ?? null;
  const x4bnet = external?.x4bnet ?? null;
  const google = external?.google ?? null;
  const scamalyticsStatus = scam?.status ?? null;
  const scamalyticsStatusError =
    scamalyticsInfo && (!scam || (scamalyticsStatus && scamalyticsStatus !== "ok"))
      ? `Scamalytics status: ${scamalyticsStatus ?? "missing"}`
      : null;
  const scamalyticsAvailable = Boolean(scam && scamalyticsStatus === "ok");
  const scamalyticsIp = pickFirst(scam?.ip);
  const scamalyticsRisk = scam?.scamalytics_risk ?? null;
  const scamalyticsIsp = scam?.scamalytics_isp ?? null;
  const scamalyticsOrg = scam?.scamalytics_org ?? null;
  const scamalyticsIspRisk = scam?.scamalytics_isp_risk ?? null;
  const scamalyticsScore = formatScore(scam?.scamalytics_score);
  const scamalyticsIspScore = formatScore(scam?.scamalytics_isp_score);
  const scamalyticsCountry = formatCountry(
    pickFirst(dbip?.ip_country_name, maxmind?.ip_country_name, ip2proxyLite?.ip_country_name),
    pickFirst(dbip?.ip_country_code, maxmind?.ip_country_code, ip2proxyLite?.ip_country_code)
  );
  const scamalyticsCity = formatCity(
    pickFirst(dbip?.ip_city, maxmind?.ip_city, ip2proxyLite?.ip_city),
    pickFirst(dbip?.ip_state_name, maxmind?.ip_state_name, dbip?.ip_district_name, ip2proxyLite?.ip_district_name)
  );
  const scamalyticsAsn = pickAsn([maxmind, ip2proxyLite]);
  const scamalyticsProxyType = pickFirst(ip2proxy?.proxy_type, ip2proxyLite?.proxy_type);
  const scamalyticsBlacklist = scam?.is_blacklisted_external ? "Yes" : null;
  const scamalyticsUrl = scam?.scamalytics_url ?? null;
  const scamalyticsFlags = collectTrueFlags([
    { label: "Datacenter", value: scam?.scamalytics_proxy?.is_datacenter },
    { label: "VPN", value: scam?.scamalytics_proxy?.is_vpn },
    { label: "iCloud Private Relay", value: scam?.scamalytics_proxy?.is_apple_icloud_private_relay },
    { label: "AWS", value: scam?.scamalytics_proxy?.is_amazon_aws },
    { label: "Google", value: scam?.scamalytics_proxy?.is_google },
    { label: "Proxy", value: firehol?.is_proxy },
    { label: "Datacenter", value: x4bnet?.is_datacenter },
    { label: "VPN", value: x4bnet?.is_vpn },
    { label: "Tor", value: x4bnet?.is_tor },
    { label: "Spambot", value: x4bnet?.is_blacklisted_spambot },
    { label: "Opera Mini Bot", value: x4bnet?.is_bot_operamini },
    { label: "Semrush Bot", value: x4bnet?.is_bot_semrush },
    { label: "Google", value: google?.is_google_general },
    { label: "Googlebot", value: google?.is_googlebot },
    { label: "Special Crawler", value: google?.is_special_crawler },
    { label: "User Triggered Fetcher", value: google?.is_user_triggered_fetcher },
  ]);

  useEffect(() => {
    if (!isVast || !vastStatusTarget) return;
    const timer = window.setInterval(() => {
      void vastQuery.refetch();
      void vastInstanceDetailQuery.refetch();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [isVast, vastInstanceDetailQuery, vastQuery, vastStatusTarget]);

  useEffect(() => {
    if (!isVast || !vastStatusTarget) return;
    if (host?.status === vastStatusTarget) {
      setVastStatusTarget(null);
      setVastStatusPollUntil(null);
    }
  }, [host?.status, isVast, vastStatusTarget]);

  useEffect(() => {
    if (!isVast || !vastStatusTarget || vastStatusPollUntil == null) return;
    const ms = Math.max(0, vastStatusPollUntil - Date.now());
    const timeout = window.setTimeout(() => {
      setVastStatusTarget(null);
      setVastStatusPollUntil(null);
    }, ms);
    return () => window.clearTimeout(timeout);
  }, [isVast, vastStatusPollUntil, vastStatusTarget]);

  const deleteMutation = useMutation({
    mutationFn: () => hostApi.remove(hostId),
    onSuccess: () => {
      navigate({ to: "/hosts" });
    },
  });

  const updateMutation = useMutation({
    mutationFn: async () => {
      // Parse env vars from multiline string
      const envVarsObj: Record<string, string> = {};
      for (const line of editEnvVars.split("\n")) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith("#")) continue; // Skip empty lines and comments
        const eqIdx = trimmed.indexOf("=");
        if (eqIdx > 0) {
          const key = trimmed.slice(0, eqIdx).trim();
          const value = trimmed.slice(eqIdx + 1).trim();
          if (key) envVarsObj[key] = value;
        }
      }
      
      const config: Record<string, unknown> = {
        name: editName,
        ssh_host: editSshHost || null,
        ssh_port: editSshPort ? parseInt(editSshPort, 10) : null,
        ssh_user: editSshUser || null,
        sshKeyPath: editSshKeyPath || null,
        env_vars: envVarsObj,
      };
      
      // Only include cloudflared_hostname for colab hosts
      if (hostQuery.data?.type === "colab") {
        config.cloudflared_hostname = editCloudflaredHostname || null;
      }
      
      return await hostApi.update(hostId, config);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["hosts", hostId] });
      queryClient.invalidateQueries({ queryKey: ["hosts"] });
      editModal.onClose();
    },
  });

  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);

  // Clear test result when switching hosts
  useEffect(() => {
    setTestResult(null);
    setSelectedGpuIndex(null);
    setVastStatusTarget(null);
    setVastStatusPollUntil(null);
  }, [hostId]);

  useEffect(() => {
    if (isVast) {
      setVastSystemInfo(null);
      setVastLastSeenAt(null);
    }
  }, [hostId, isVast]);

  async function handleTest() {
    setTestResult(null);
    try {
      const result = await testMutation.mutateAsync();
      setTestResult(result);
    } catch (e) {
      setTestResult({ success: false, message: getErrorMessage(e) });
    }
  }

  async function handleOpenTerminal() {
    const host = isVast ? vastHost : hostQuery.data;
    if (!host?.ssh) {
      alert("No SSH configuration for this host");
      return;
    }

    if (isVast) {
      setIsLoadingTmuxSessions(true);
      try {
        if (!cfgQuery.data?.vast.ssh_key_path) {
          throw new Error("Missing Vast SSH key path. Configure it in Settings → Vast.ai → SSH Key Path.");
        }
        const vastUser = cfgQuery.data.vast.ssh_user?.trim() || "root";
        const latest = await vastGetInstance(vastInstanceId);
        queryClient.setQueryData(["vastInstance", vastInstanceId], latest);
        const keyPath = hasValidVastId
          ? await vastAttachSshKey(vastInstanceId, cfgQuery.data.vast.ssh_key_path)
          : null;
        await new Promise((r) => setTimeout(r, 1200));

        const sshExtraArgs = [
          "-o",
          "IdentitiesOnly=yes",
          "-o",
          "PreferredAuthentications=publickey",
          "-o",
          "PasswordAuthentication=no",
          "-o",
          "BatchMode=yes",
        ];

        const candidates: Array<{ mode: "proxy" | "direct"; host: string; port: number }> = [];
        const addCandidate = (mode: "proxy" | "direct") => {
          if (mode === "proxy") {
            const sshIdx = latest.ssh_idx ?? null;
            const normalizedSshIdx = sshIdx
              ? String(sshIdx).startsWith("ssh")
                ? String(sshIdx)
                : `ssh${sshIdx}`
              : null;
            const proxyHostFromApi = latest.ssh_host ?? null;
            const proxyHost = proxyHostFromApi?.includes("vast.ai")
              ? proxyHostFromApi
              : normalizedSshIdx
                ? `${normalizedSshIdx}.vast.ai`
                : null;
            const h = proxyHost?.trim();
            const p = latest.ssh_port ?? null;
            if (h && p) candidates.push({ mode, host: h, port: p });
            return;
          }
          const h = latest.public_ipaddr?.trim();
          const p = latest.machine_dir_ssh_port ?? null;
          if (h && p) candidates.push({ mode, host: h, port: p });
        };

        const pref = cfgQuery.data.vast.ssh_connection_preference === "direct" ? "direct" : "proxy";
        addCandidate(pref);
        addCandidate(pref === "direct" ? "proxy" : "direct");

        if (candidates.length === 0) {
          throw new Error("No available SSH route for this instance (proxy/direct SSH not available yet).");
        }

        let lastError: unknown = null;
        const attempts: string[] = [];
        for (const cand of candidates) {
          try {
            await sshCheck({
              host: cand.host,
              port: cand.port,
              user: vastUser,
              keyPath,
              extraArgs: sshExtraArgs,
            });
            await connectToTmuxSession("main", {
              host: cand.host,
              port: cand.port,
              user: vastUser,
              keyPath,
              extraArgs: sshExtraArgs,
            });
            return;
          } catch (e) {
            lastError = e;
            attempts.push(`${cand.mode.toUpperCase()} ${vastUser}@${cand.host}:${cand.port}: ${getErrorMessage(e)}`);
          }
        }

        if (attempts.length > 0) {
          throw new Error(`SSH connection failed.\n\n${attempts.join("\n\n")}`);
        }
        throw lastError ?? new Error("SSH connection failed");
      } catch (e) {
        console.error("Failed to open Vast terminal:", e);
        setIsLoadingTmuxSessions(false);
        alert(`Failed to open terminal: ${getErrorMessage(e)}`);
      }
      return;
    }

    try {
      setIsLoadingTmuxSessions(true);
      // Check for existing tmux sessions
      const sessions = await hostApi.listTmuxSessions(hostId);

      if (sessions.length === 0) {
        // No existing sessions, create a new one directly
        await connectToTmuxSession("main");
      } else if (sessions.length === 1) {
        // Only one session, attach to it directly
        await connectToTmuxSession(sessions[0].name);
      } else {
        // Multiple sessions, show modal for selection
        setRemoteTmuxSessions(sessions);
        setIsLoadingTmuxSessions(false);
        tmuxModal.onOpen();
      }
    } catch (e) {
      console.error("Failed to check tmux sessions:", e);
      setIsLoadingTmuxSessions(false);
      // If we can't list sessions (e.g., tmux not installed), just create a new one
      await connectToTmuxSession("main");
    }
  }

  async function connectToTmuxSession(
    sessionName: string,
    sshOverride?: { host?: string; port?: number; user?: string; keyPath?: string | null; extraArgs?: string[] }
  ) {
    const host = isVast ? vastHost : hostQuery.data;
    if (!host?.ssh) return;

    try {
      const sshSpec = {
        host: sshOverride?.host ?? host.ssh.host,
        port: sshOverride?.port ?? host.ssh.port,
        user: sshOverride?.user ?? host.ssh.user,
        keyPath: sshOverride?.keyPath !== undefined ? sshOverride.keyPath : (host.ssh.keyPath ?? host.ssh.key_path ?? null),
        extraArgs: sshOverride?.extraArgs ?? host.ssh.extraArgs ?? host.ssh.extra_args ?? [],
      };
      console.log("Opening terminal for host:", host.name, "session:", sessionName);
      await termOpenSshTmux({
        ssh: sshSpec,
        tmuxSession: sessionName,
        title: `${host.name} · ${sessionName}`,
        cols: 120,
        rows: 32,
        envVars: host.env_vars,
      });
      // Close modal if open
      tmuxModal.onClose();
      setIsLoadingTmuxSessions(false);
      // Navigate to terminal page
      navigate({ to: "/terminal" });
    } catch (e) {
      console.error("Failed to open terminal:", e);
      setIsLoadingTmuxSessions(false);
      alert(`Failed to open terminal: ${e}`);
    }
  }

  const isLoading = isVast
    ? vastQuery.isLoading || cfgQuery.isLoading
    : hostQuery.isLoading;
  const loadError = isVast
    ? vastQuery.error || cfgQuery.error
    : hostQuery.error;
  const canStartVast = isVast && hasValidVastId && host?.status !== "online";
  const canStopVast = isVast && hasValidVastId && host?.status === "online";
  const diskSpaceGb = vastInstanceDetail?.disk_space
    ?? host?.system_info?.disks?.reduce((sum, disk) => sum + disk.total_gb, 0)
    ?? null;
  const vastSshUser = cfgQuery.data?.vast.ssh_user?.trim() || "root";
  const storagePerHour = vastInstanceDetail?.storage_cost != null && diskSpaceGb != null
    ? (vastInstanceDetail.storage_cost / 720) * diskSpaceGb
    : null;
  const uploadPerTb = vastInstanceDetail?.inet_up_cost != null ? vastInstanceDetail.inet_up_cost * 1024 : null;
  const downloadPerTb = vastInstanceDetail?.inet_down_cost != null ? vastInstanceDetail.inet_down_cost * 1024 : null;
  const vastSshHost = vastInstanceDetail?.public_ipaddr ?? null;
  const vastSshIdx = normalizedSshIdx;
  const directSsh = vastSshHost && vastDirectPort
    ? `ssh -p ${vastDirectPort} ${vastSshUser}@${vastSshHost}`
    : null;
  const proxySsh = vastSshIdx && vastProxyPort
    ? `ssh -p ${vastProxyPort} ${vastSshUser}@${vastSshIdx}.vast.ai`
    : null;
  const vastGpuList = useMemo(() => {
    if (!isVast || !vastInstanceDetail?.gpu_name) return [];
    const count = Math.max(1, vastInstanceDetail.num_gpus ?? 1);
    const capability = vastGpuCapabilityQuery.data ?? null;
    const perGpuRamMb = vastInstanceDetail.gpu_ram != null
      ? Math.round(vastInstanceDetail.gpu_ram)
      : vastInstanceDetail.gpu_totalram != null
        ? Math.round(vastInstanceDetail.gpu_totalram / count)
        : null;
    const pcieGen = vastInstanceDetail.pci_gen != null ? Math.round(vastInstanceDetail.pci_gen) : null;
    const pcieWidth = vastInstanceDetail.gpu_lanes != null ? Math.round(vastInstanceDetail.gpu_lanes) : null;
    return Array.from({ length: count }, (_, idx) => ({
      index: idx,
      name: vastInstanceDetail.gpu_name ?? "GPU",
      memory_total_mb: perGpuRamMb ?? 0,
      memory_used_mb: null,
      utilization: vastInstanceDetail.gpu_util != null ? Math.round(vastInstanceDetail.gpu_util) : null,
      temperature: null,
      driver_version: vastInstanceDetail.driver_version ?? null,
      power_draw_w: null,
      power_limit_w: null,
      clock_graphics_mhz: null,
      clock_memory_mhz: null,
      fan_speed: null,
      compute_mode: null,
      pcie_gen: pcieGen,
      pcie_width: pcieWidth,
      capability,
    }));
  }, [isVast, vastGpuCapabilityQuery.data, vastInstanceDetail]);
  const displaySystemInfo = useMemo<SystemInfo | null>(() => {
    if (host?.system_info) return host.system_info;
    if (!isVast || !vastInstanceDetail) return null;

    const memoryTotalGb = (() => {
      if (vastInstanceDetail.mem_limit != null && vastInstanceDetail.mem_limit > 0) {
        return vastInstanceDetail.mem_limit;
      }
      if (vastInstanceDetail.cpu_ram != null && vastInstanceDetail.cpu_ram > 0) {
        return vastInstanceDetail.cpu_ram / 1024;
      }
      return null;
    })();

    const memoryUsedGb = (() => {
      if (memoryTotalGb == null || vastInstanceDetail.mem_usage == null) return null;
      if (vastInstanceDetail.mem_usage <= 1) {
        return memoryTotalGb * vastInstanceDetail.mem_usage;
      }
      return vastInstanceDetail.mem_usage;
    })();

    const memoryAvailableGb = memoryTotalGb != null && memoryUsedGb != null
      ? Math.max(memoryTotalGb - memoryUsedGb, 0)
      : null;

    const diskTotalGb = vastInstanceDetail.disk_space ?? null;
    const diskUsedGb = (() => {
      if (diskTotalGb == null) return null;
      if (vastInstanceDetail.disk_util != null && vastInstanceDetail.disk_util >= 0 && vastInstanceDetail.disk_util <= 1) {
        return diskTotalGb * vastInstanceDetail.disk_util;
      }
      if (vastInstanceDetail.disk_usage != null && vastInstanceDetail.disk_usage >= 0 && vastInstanceDetail.disk_usage <= 1) {
        return diskTotalGb * vastInstanceDetail.disk_usage;
      }
      if (vastInstanceDetail.disk_usage != null && vastInstanceDetail.disk_usage > 1) {
        return Math.min(vastInstanceDetail.disk_usage, diskTotalGb);
      }
      return null;
    })();
    const diskAvailableGb = diskTotalGb != null && diskUsedGb != null
      ? Math.max(diskTotalGb - diskUsedGb, 0)
      : null;

    const disks = diskTotalGb != null ? [
      {
        mount_point: vastInstanceDetail.disk_name?.trim() || "/",
        total_gb: diskTotalGb,
        used_gb: diskUsedGb ?? 0,
        available_gb: diskAvailableGb ?? Math.max(diskTotalGb - (diskUsedGb ?? 0), 0),
      },
    ] : [];

    const os = vastInstanceDetail.os_version
      ? `Ubuntu ${vastInstanceDetail.os_version}`
      : null;

    return {
      cpu_model: vastInstanceDetail.cpu_name ?? null,
      cpu_cores: vastInstanceDetail.cpu_cores ?? null,
      memory_total_gb: memoryTotalGb,
      memory_used_gb: memoryUsedGb,
      memory_available_gb: memoryAvailableGb,
      disks,
      gpu_list: [],
      os,
      hostname: null,
    };
  }, [host?.system_info, isVast, vastInstanceDetail]);
  const displayGpuList = displaySystemInfo?.gpu_list?.length ? displaySystemInfo.gpu_list : (isVast ? vastGpuList : []);
  const hasFullSystemInfo = Boolean(host?.system_info);
  const selectedGpu = useMemo(() => {
    if (selectedGpuIndex == null) return null;
    return displayGpuList.find((gpu) => gpu.index === selectedGpuIndex) ?? null;
  }, [displayGpuList, selectedGpuIndex]);

  const renderGpuList = (gpuList: GpuInfo[]) => {
    if (gpuList.length === 0) {
      return (
        <div>
          <p className="text-sm text-foreground/60">GPU</p>
          <p className="text-sm">No NVIDIA GPU detected</p>
        </div>
      );
    }
    return (
      <div>
        <p className="text-sm text-foreground/60 mb-2">GPUs ({gpuList.length})</p>
        <div className="space-y-2">
          {gpuList.map((gpu) => {
            const memUsedPct = gpu.memory_used_mb != null && gpu.memory_total_mb > 0
              ? Math.round((gpu.memory_used_mb / gpu.memory_total_mb) * 100)
              : 0;
            return (
              <Tooltip key={gpu.index} content="Click for details" delay={500}>
                <div
                  className="p-3 rounded-lg bg-content2 cursor-pointer hover:bg-content3 transition-colors border border-transparent hover:border-primary/30"
                  onClick={() => {
                    setSelectedGpuIndex(gpu.index);
                    gpuModal.onOpen();
                  }}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <IconGpu />
                      <span className="font-medium text-sm">{gpu.name}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      {gpu.temperature != null && (
                        <span className={`text-xs font-medium ${getTempColor(gpu.temperature)}`}>
                          {gpu.temperature}°C
                        </span>
                      )}
                      <Chip size="sm" variant="flat">GPU {gpu.index}</Chip>
                    </div>
                  </div>
                  <div className="mb-2">
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-foreground/60">VRAM</span>
                      <span>
                        {gpu.memory_used_mb != null && gpu.memory_total_mb > 0 && (
                          <>{(gpu.memory_used_mb / 1024).toFixed(1)} / </>
                        )}
                        {gpu.memory_total_mb > 0 ? (gpu.memory_total_mb / 1024).toFixed(0) : "-"} GB
                        {gpu.memory_used_mb != null && gpu.memory_total_mb > 0 && (
                          <span className="text-foreground/60 ml-1">({memUsedPct}%)</span>
                        )}
                      </span>
                    </div>
                    <Progress
                      value={memUsedPct}
                      size="sm"
                      color={memUsedPct > 90 ? "danger" : memUsedPct > 70 ? "warning" : "primary"}
                      className="h-1.5"
                    />
                  </div>
                  <div className="flex gap-4 text-xs">
                    {gpu.utilization != null && (
                      <div className="flex items-center gap-1">
                        <span className="text-foreground/60">Util:</span>
                        <span className="font-medium">{gpu.utilization}%</span>
                      </div>
                    )}
                    {gpu.power_draw_w != null && (
                      <div className="flex items-center gap-1">
                        <span className="text-foreground/60">Power:</span>
                        <span className="font-medium">{gpu.power_draw_w.toFixed(0)}W</span>
                      </div>
                    )}
                    {gpu.driver_version && (
                      <div className="flex items-center gap-1">
                        <span className="text-foreground/60">Driver:</span>
                        <span className="font-mono">{gpu.driver_version}</span>
                      </div>
                    )}
                  </div>
                </div>
              </Tooltip>
            );
          })}
        </div>
      </div>
    );
  };

  if (isLoading) {
    return (
      <div className="h-full p-6 overflow-auto">
        <div className="max-w-4xl mx-auto">
          {/* Skeleton Header */}
          <div className="flex items-center gap-4 mb-6">
            <Skeleton className="w-9 h-9 rounded-lg" />
            <div className="flex-1">
              <Skeleton className="h-7 w-48 rounded-lg mb-2" />
              <Skeleton className="h-4 w-64 rounded-lg" />
            </div>
            <Skeleton className="w-24 h-9 rounded-lg" />
          </div>
          {/* Skeleton Tabs */}
          <div className="flex gap-2 mb-6">
            <Skeleton className="h-10 w-24 rounded-lg" />
            <Skeleton className="h-10 w-24 rounded-lg" />
            <Skeleton className="h-10 w-24 rounded-lg" />
          </div>
          {/* Skeleton Content */}
          <div className="doppio-card p-6">
            <div className="space-y-4">
              <Skeleton className="h-12 w-full rounded-lg" />
              <Skeleton className="h-12 w-full rounded-lg" />
              <Skeleton className="h-12 w-full rounded-lg" />
              <Skeleton className="h-12 w-3/4 rounded-lg" />
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (loadError || !host) {
    return (
      <div className="h-full p-6">
        <Card>
          <CardBody>
            <p className="text-danger">Host not found or failed to load</p>
            <Button as={Link} to="/hosts" className="mt-4">
              Back to Hosts
            </Button>
          </CardBody>
        </Card>
      </div>
    );
  }

  const sshAddress = host.ssh ? `${host.ssh.user}@${host.ssh.host}:${host.ssh.port}` : null;

  return (
    <div className="h-full p-6 overflow-auto">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-center gap-4 mb-6">
          <Button
            as={Link}
            to="/hosts"
            isIconOnly
            variant="flat"
            size="sm"
          >
            <IconArrowLeft />
          </Button>
          <div className="flex-1">
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold">{host.name}</h1>
              <StatusBadge status={host.status} />
              <Chip size="sm" variant="flat">{host.type}</Chip>
            </div>
            <p className="text-sm text-foreground/60">
              {isVast ? "Vast.ai instance" : `Created ${new Date(host.created_at).toLocaleDateString()}`}
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="flat"
              startContent={<IconTerminal />}
              onPress={() => {
                const label = host.name;
                if (isVast) {
                  if (!hasValidVastId) return;
                  navigate({
                    to: "/terminal",
                    search: { connectVastInstanceId: String(vastInstanceId), connectLabel: label },
                  });
                  return;
                }
                navigate({ to: "/terminal", search: { connectHostId: hostId, connectLabel: label } });
              }}
              isDisabled={!host.ssh || (isVast && !canVastConnect)}
            >
              Terminal
            </Button>
            {isVast && canStartVast && (
              <Button
                variant="flat"
                color="success"
                startContent={<IconPlay />}
                onPress={() => vastStartMutation.mutate()}
                isLoading={vastStartMutation.isPending || vastStatusTarget === "online"}
                isDisabled={vastStatusTarget === "online"}
              >
                Start
              </Button>
            )}
            {isVast && canStopVast && (
              <Button
                variant="flat"
                color="warning"
                startContent={<IconStop />}
                onPress={() => vastStopMutation.mutate()}
                isLoading={vastStopMutation.isPending || vastStatusTarget === "offline"}
                isDisabled={vastStatusTarget === "offline"}
              >
                Stop
              </Button>
            )}
            {!isVast && (
              <Button
                variant="flat"
                startContent={<IconEdit />}
                onPress={editModal.onOpen}
              >
                Edit
              </Button>
            )}
            <Button
              variant="flat"
              startContent={<IconRefresh />}
              onPress={() => refreshMutation.mutate()}
              isLoading={refreshMutation.isPending}
              isDisabled={isVast && !canVastExecute}
            >
              Refresh
            </Button>
            {!isVast && (
              <Button
                color="danger"
                variant="flat"
                startContent={<IconTrash />}
                onPress={deleteModal.onOpen}
                isLoading={deleteMutation.isPending}
              >
                Delete
              </Button>
            )}
          </div>
        </div>

        {/* Tabs */}
        <Tabs aria-label="Host details">
          <Tab key="overview" title="Overview">
            <div className="grid gap-4 mt-4">
              {/* Connection Card */}
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between w-full">
                    <span className="font-semibold">SSH Connection</span>
                    <Button
                      size="sm"
                      variant="flat"
                      onPress={handleTest}
                      isLoading={testMutation.isPending}
                      isDisabled={isVast && !canVastExecute}
                    >
                      Test Connection
                    </Button>
                  </div>
                </CardHeader>
                <Divider />
                <CardBody className="gap-4">
                  {host.ssh ? (
                    <div className="grid grid-cols-2 gap-4">
                      {!isVast && (
                        sshAddress && (
                          <div className="col-span-2 flex items-center justify-between gap-3">
                            <div>
                              <p className="text-sm text-foreground/60">SSH Address</p>
                              <p className="font-mono select-text">{sshAddress}</p>
                            </div>
                            <Button
                              isIconOnly
                              size="sm"
                              variant="light"
                              onPress={async () => {
                                await copyText(sshAddress);
                              setCopiedSsh("address");
                              setTimeout(() => setCopiedSsh(null), 1200);
                            }}
                          >
                              {copiedSsh === "address" ? <IconCheck /> : <IconCopy />}
                            </Button>
                          </div>
                        )
                      )}
                      {isVast && directSsh && (
                        <div className="col-span-2 flex items-center justify-between gap-3">
                          <div>
                            <p className="text-sm text-foreground/60">Direct SSH</p>
                            <p className="font-mono select-text">{directSsh}</p>
                          </div>
                          <Button
                            isIconOnly
                            size="sm"
                            variant="light"
                            onPress={async () => {
                              await copyText(directSsh);
                              setCopiedSsh("direct");
                              setTimeout(() => setCopiedSsh(null), 1200);
                            }}
                          >
                            {copiedSsh === "direct" ? <IconCheck /> : <IconCopy />}
                          </Button>
                        </div>
                      )}
                      {isVast && proxySsh && (
                        <div className="col-span-2 flex items-center justify-between gap-3">
                          <div>
                            <p className="text-sm text-foreground/60">Proxy SSH</p>
                            <p className="font-mono select-text">{proxySsh}</p>
                          </div>
                          <Button
                            isIconOnly
                            size="sm"
                            variant="light"
                            onPress={async () => {
                              await copyText(proxySsh);
                              setCopiedSsh("proxy");
                              setTimeout(() => setCopiedSsh(null), 1200);
                            }}
                          >
                            {copiedSsh === "proxy" ? <IconCheck /> : <IconCopy />}
                          </Button>
                        </div>
                      )}
                      <div>
                        <p className="text-sm text-foreground/60">Host</p>
                        <p className="font-mono select-text">
                          {host.ssh.host}
                        </p>
                      </div>
                      <div>
                        <p className="text-sm text-foreground/60">Port</p>
                        <p className="font-mono select-text">
                          {host.ssh.port}
                        </p>
                      </div>
                      <div>
                        <p className="text-sm text-foreground/60">User</p>
                        <p className="font-mono select-text">{host.ssh.user}</p>
                      </div>
                      <div>
                        <p className="text-sm text-foreground/60">Key Path</p>
                        <p className="font-mono text-sm truncate select-text">{host.ssh.keyPath ?? host.ssh.key_path ?? "default"}</p>
                      </div>
                    </div>
                  ) : (
                    <p className="text-foreground/60">No SSH configuration</p>
                  )}

                  {testResult && (
                    <div
                      className={`p-3 rounded-lg ${
                        testResult.success ? "bg-success/10 text-success" : "bg-danger/10 text-danger"
                      }`}
                    >
                      {testResult.message}
                    </div>
                  )}
                  {refreshMutation.error && (
                    <div className="p-3 rounded-lg bg-danger/10 text-danger">
                      {getErrorMessage(refreshMutation.error)}
                    </div>
                  )}
                </CardBody>
              </Card>

              {/* Scamalytics Card */}
              {hasScamalyticsKey && (
                <Card>
                  <CardHeader>
                    <div className="flex items-center justify-between w-full">
                      <span className="font-semibold">Scamalytics</span>
                      <Button
                        size="sm"
                        variant="flat"
                        onPress={() => scamalyticsQuery.refetch()}
                        isLoading={scamalyticsQuery.isFetching}
                        isDisabled={!scamalyticsTarget || !scamalyticsEnabled}
                      >
                        Refresh
                      </Button>
                    </div>
                  </CardHeader>
                  <Divider />
                  <CardBody className="gap-4">
                    {host?.status !== "online" ? (
                      <p className="text-foreground/60">Host is offline. Scamalytics data is available when online.</p>
                    ) : !scamalyticsTarget ? (
                      <p className="text-foreground/60">No target available for Scamalytics lookup.</p>
                    ) : !scamalyticsEnabled ? (
                      <p className="text-foreground/60">Scamalytics user is missing. Configure it in Settings.</p>
                    ) : scamalyticsQuery.isLoading ? (
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        {[0, 1, 2, 3, 4, 5, 6, 7, 8].map((idx) => (
                          <div key={idx} className="space-y-2">
                            <Skeleton className="h-3 w-20 rounded" />
                            <Skeleton className="h-4 w-32 rounded" />
                          </div>
                        ))}
                      </div>
                    ) : scamalyticsQuery.error ? (
                      <div className="p-3 rounded-lg bg-danger/10 text-danger">
                        {getErrorMessage(scamalyticsQuery.error)}
                      </div>
                    ) : scamalyticsStatusError ? (
                      <div className="p-3 rounded-lg bg-danger/10 text-danger">
                        {scamalyticsStatusError}
                      </div>
                    ) : scamalyticsAvailable ? (
                      <>
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                          <div>
                            <p className="text-sm text-foreground/60">Public IP</p>
                            <p className="font-mono text-sm">{scamalyticsIp ?? "-"}</p>
                          </div>
                          <div>
                            <p className="text-sm text-foreground/60">Risk</p>
                            <p className="text-sm">{scamalyticsRisk ?? "-"}</p>
                          </div>
                          <div>
                            <p className="text-sm text-foreground/60">Score</p>
                            <p className="font-mono text-sm">{scamalyticsScore ?? "-"}</p>
                          </div>
                          <div>
                            <p className="text-sm text-foreground/60">ISP</p>
                            <p className="text-sm">{scamalyticsIsp ?? "-"}</p>
                          </div>
                          <div>
                            <p className="text-sm text-foreground/60">Organization</p>
                            <p className="text-sm">{scamalyticsOrg ?? "-"}</p>
                          </div>
                          <div>
                            <p className="text-sm text-foreground/60">ISP Score</p>
                            <p className="font-mono text-sm">{scamalyticsIspScore ?? "-"}</p>
                          </div>
                          <div>
                            <p className="text-sm text-foreground/60">ISP Risk</p>
                            <p className="text-sm">{scamalyticsIspRisk ?? "-"}</p>
                          </div>
                          <div>
                            <p className="text-sm text-foreground/60">Country</p>
                            <p className="text-sm">{scamalyticsCountry ?? "-"}</p>
                          </div>
                          <div>
                            <p className="text-sm text-foreground/60">City</p>
                            <p className="text-sm">{scamalyticsCity ?? "-"}</p>
                          </div>
                          <div>
                            <p className="text-sm text-foreground/60">ASN</p>
                            <p className="text-sm break-all">{scamalyticsAsn ?? "-"}</p>
                          </div>
                          <div>
                            <p className="text-sm text-foreground/60">Proxy Type</p>
                            <p className="text-sm">{scamalyticsProxyType ?? "-"}</p>
                          </div>
                          <div className="md:col-span-3">
                            <p className="text-sm text-foreground/60">Flags</p>
                            <p className="text-sm">{scamalyticsFlags ?? "-"}</p>
                          </div>
                          <div>
                            <p className="text-sm text-foreground/60">Blacklisted</p>
                            <p className="text-sm">{scamalyticsBlacklist ?? "-"}</p>
                          </div>
                          <div className="md:col-span-3">
                            <p className="text-sm text-foreground/60">Report URL</p>
                            {scamalyticsUrl ? (
                              <a
                                href={scamalyticsUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-sm text-primary hover:underline break-all"
                              >
                                {scamalyticsUrl}
                              </a>
                            ) : (
                              <p className="text-sm">-</p>
                            )}
                          </div>
                        </div>
                        <p className="text-xs text-foreground/50">
                          Source: Scamalytics
                        </p>
                      </>
                    ) : (
                      <p className="text-foreground/60">No Scamalytics data available.</p>
                    )}
                  </CardBody>
                </Card>
              )}

              {/* System Info Card */}
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between w-full">
                    <span className="font-semibold">System Information</span>
                    {!hasFullSystemInfo && (
                      <Button
                        size="sm"
                        variant="flat"
                        onPress={() => refreshMutation.mutate()}
                        isLoading={refreshMutation.isPending}
                        isDisabled={isVast && !canVastExecute}
                      >
                        Fetch Info
                      </Button>
                    )}
                  </div>
                </CardHeader>
                <Divider />
                <CardBody className="gap-4">
                  {displaySystemInfo ? (
                    <>
                      {isVast && !hasFullSystemInfo && (
                        <p className="text-foreground/60 mb-3">
                          Limited info from Vast.ai. Click "Refresh" to fetch full system info.
                        </p>
                      )}
                      {/* OS & Hostname */}
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <p className="text-sm text-foreground/60">OS</p>
                          <p className="text-sm">{displaySystemInfo.os ?? "-"}</p>
                        </div>
                        <div>
                          <p className="text-sm text-foreground/60">Hostname</p>
                          <p className="text-sm font-mono">{displaySystemInfo.hostname ?? "-"}</p>
                        </div>
                      </div>

                      {/* CPU */}
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <p className="text-sm text-foreground/60">CPU</p>
                          <p className="text-sm">{displaySystemInfo.cpu_model ?? "-"}</p>
                        </div>
                        <div>
                          <p className="text-sm text-foreground/60">Cores</p>
                          <p className="text-sm">{displaySystemInfo.cpu_cores ?? "-"}</p>
                        </div>
                      </div>

                      {/* Memory */}
                      <div className="grid grid-cols-3 gap-4">
                        <div>
                          <p className="text-sm text-foreground/60">Memory Total</p>
                          <p className="text-sm">{displaySystemInfo.memory_total_gb?.toFixed(1) ?? "-"} GB</p>
                        </div>
                        <div>
                          <p className="text-sm text-foreground/60">Memory Used</p>
                          <p className="text-sm">{displaySystemInfo.memory_used_gb?.toFixed(1) ?? "-"} GB</p>
                        </div>
                        <div>
                          <p className="text-sm text-foreground/60">Memory Available</p>
                          <p className="text-sm">{displaySystemInfo.memory_available_gb?.toFixed(1) ?? "-"} GB</p>
                        </div>
                      </div>

                      {/* Disks */}
                      {displaySystemInfo.disks && displaySystemInfo.disks.length > 0 && (
                        <div>
                          <p className="text-sm text-foreground/60 mb-2">
                            Disks ({displaySystemInfo.disks.length})
                          </p>
                          <div className="space-y-2">
                            {displaySystemInfo.disks.map((disk) => (
                              <div key={disk.mount_point} className="p-3 rounded-lg bg-content2">
                                <div className="flex items-center justify-between mb-2">
                                  <span className="font-mono text-sm font-medium">{disk.mount_point}</span>
                                  <span className="text-xs text-foreground/60">
                                    {((disk.used_gb / disk.total_gb) * 100).toFixed(0)}% used
                                  </span>
                                </div>
                                <div className="w-full bg-content3 rounded-full h-1.5 mb-2">
                                  <div
                                    className="bg-primary h-1.5 rounded-full"
                                    style={{ width: `${Math.min((disk.used_gb / disk.total_gb) * 100, 100)}%` }}
                                  />
                                </div>
                                <div className="grid grid-cols-3 gap-2 text-xs">
                                  <div>
                                    <span className="text-foreground/60">Total: </span>
                                    <span>{disk.total_gb.toFixed(1)} GB</span>
                                  </div>
                                  <div>
                                    <span className="text-foreground/60">Used: </span>
                                    <span>{disk.used_gb.toFixed(1)} GB</span>
                                  </div>
                                  <div>
                                    <span className="text-foreground/60">Free: </span>
                                    <span>{disk.available_gb.toFixed(1)} GB</span>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {renderGpuList(displayGpuList)}
                    </>
                  ) : (
                    <>
                      {isVast && displayGpuList.length > 0 ? (
                        <>
                          <p className="text-foreground/60 mb-3">
                            Limited info from Vast.ai. Click "Refresh" to fetch full system info.
                          </p>
                          {renderGpuList(displayGpuList)}
                        </>
                      ) : (
                        <p className="text-foreground/60">
                          Click "Refresh" or "Fetch Info" to retrieve system information
                        </p>
                      )}
                    </>
                  )}
                </CardBody>
              </Card>

              {/* Type-specific Info */}
              {isVast && vastInstanceDetail && (
                <Card>
                  <CardHeader>
                    <span className="font-semibold">Vast.ai Rates</span>
                  </CardHeader>
                  <Divider />
                  <CardBody className="grid grid-cols-2 gap-4">
                    <div>
                      <p className="text-sm text-foreground/60">{displayCurrency}/hr</p>
                      <p className="font-mono">
                        {vastInstanceDetail.dph_total != null ? formatUsd(vastInstanceDetail.dph_total, 3) : "-"}
                      </p>
                    </div>
                    {vastInstanceDetail.gpu_util != null && (
                      <div>
                        <p className="text-sm text-foreground/60">GPU Util</p>
                        <p className="font-mono">{Math.round(vastInstanceDetail.gpu_util)}%</p>
                      </div>
                    )}
                    <div>
                      <p className="text-sm text-foreground/60">
                        Storage {diskSpaceGb != null ? `(${diskSpaceGb.toFixed(0)} GB)` : ""}
                      </p>
                      <p className="font-mono">{storagePerHour != null ? `${formatUsd(storagePerHour, 3)}/hr` : "-"}</p>
                    </div>
                    <div>
                      <p className="text-sm text-foreground/60">Upload</p>
                      <p className="font-mono">{uploadPerTb != null ? `${formatUsd(uploadPerTb, 3)}/TB` : "-"}</p>
                    </div>
                    <div>
                      <p className="text-sm text-foreground/60">Download</p>
                      <p className="font-mono">{downloadPerTb != null ? `${formatUsd(downloadPerTb, 3)}/TB` : "-"}</p>
                    </div>
                  </CardBody>
                </Card>
              )}

              {!isVast && host.type === "vast" && host.vast_instance_id && (
                <VastPricingCard hostId={host.id} hostName={host.name} vastInstanceId={host.vast_instance_id} />
              )}

              {host.type === "colab" && host.cloudflared_hostname && (
                <Card>
                  <CardHeader>
                    <span className="font-semibold">Colab Connection</span>
                  </CardHeader>
                  <Divider />
                  <CardBody>
                    <div>
                      <p className="text-sm text-foreground/60">Cloudflared Hostname</p>
                      <p className="font-mono text-sm">{host.cloudflared_hostname}</p>
                    </div>
                  </CardBody>
                </Card>
              )}

              {/* Linked Storages */}
              <Card>
                <CardHeader className="flex justify-between items-center">
                  <span className="font-semibold">Storage Locations</span>
                  <Button 
                    as={Link} 
                    to="/storage" 
                    size="sm" 
                    variant="flat"
                  >
                    Manage
                  </Button>
                </CardHeader>
                <Divider />
                <CardBody>
                  {linkedStorages.length === 0 ? (
                    <p className="text-foreground/60 text-sm">
                      No storage locations linked to this host.
                    </p>
                  ) : (
                    <div className="space-y-2">
                      {linkedStorages.map((storage) => (
                        <div 
                          key={storage.id} 
                          className="flex items-center justify-between p-2 rounded-lg bg-default-100 hover:bg-default-200 transition-colors"
                        >
                          <div className="flex items-center gap-2">
                            {getStorageIconNode(storage)}
                            <div>
                              <p className="font-medium text-sm">{storage.name}</p>
                              <p className="text-xs text-foreground/60 font-mono">
                                {storage.backend.type === "ssh_remote" ? storage.backend.root_path : ""}
                              </p>
                            </div>
                          </div>
                          <Button 
                            as={Link} 
                            to={`/storage/${storage.id}`}
                            size="sm" 
                            variant="light"
                          >
                            Browse
                          </Button>
                        </div>
                      ))}
                    </div>
                  )}
                </CardBody>
              </Card>
            </div>
          </Tab>

          <Tab key="sessions" title="Sessions">
            <div className="mt-4">
              <Card>
                <CardBody className="text-center py-8">
                  <p className="text-foreground/60 mb-4">No sessions on this host</p>
                  <Button as={Link} to="/tasks/new" color="primary">
                    Create New Task
                  </Button>
                </CardBody>
              </Card>
            </div>
          </Tab>

          <Tab key="settings" title="Settings">
            <div className="grid gap-4 mt-4">
              <Card>
                <CardHeader className="flex justify-between items-center">
                  <span className="font-semibold">Host Settings</span>
                  <Button
                    size="sm"
                    variant="flat"
                    startContent={<IconEdit />}
                    onPress={editModal.onOpen}
                  >
                    Edit
                  </Button>
                </CardHeader>
                <Divider />
                <CardBody className="gap-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <p className="text-sm text-foreground/60">Name</p>
                      <p className="font-medium">{host.name}</p>
                    </div>
                    <div>
                      <p className="text-sm text-foreground/60">Type</p>
                      <p className="font-medium">{host.type}</p>
                    </div>
                    {host.ssh && (
                      <>
                        <div>
                          <p className="text-sm text-foreground/60">SSH Host</p>
                          <p className="font-mono text-sm">
                            {isVast ? (vastSshHost ?? host.ssh.host) : host.ssh.host}
                          </p>
                        </div>
                        <div>
                          <p className="text-sm text-foreground/60">SSH Port</p>
                          <p className="font-mono">
                            {isVast ? (vastDirectPort ?? host.ssh.port) : host.ssh.port}
                          </p>
                        </div>
                        <div>
                          <p className="text-sm text-foreground/60">SSH User</p>
                          <p className="font-mono">{host.ssh.user}</p>
                        </div>
                        <div>
                          <p className="text-sm text-foreground/60">SSH Key Path</p>
                          <p className="font-mono text-sm truncate">{host.ssh.keyPath || host.ssh.key_path || "(default)"}</p>
                        </div>
                      </>
                    )}
                    {host.type === "colab" && (
                      <div className="col-span-2">
                        <p className="text-sm text-foreground/60">Cloudflared Hostname</p>
                        <p className="font-mono text-sm break-all">{host.cloudflared_hostname || "(not set)"}</p>
                      </div>
                    )}
                    <div className="col-span-2">
                      <p className="text-sm text-foreground/60">Environment Variables</p>
                      {Object.keys(host.env_vars || {}).length > 0 ? (
                        <div className="mt-1 space-y-1">
                          {Object.entries(host.env_vars).map(([k, v]) => (
                            <div key={k} className="font-mono text-sm bg-content2 rounded px-2 py-1">
                              <span className="text-primary">{k}</span>=<span className="text-foreground/70 break-all">{v}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="font-mono text-sm text-foreground/50">(none)</p>
                      )}
                    </div>
                  </div>
                </CardBody>
              </Card>
            </div>
          </Tab>
        </Tabs>
      </div>

      {/* Edit Modal */}
      {!isVast && (
        <Modal isOpen={editModal.isOpen} onOpenChange={(open) => !open && editModal.onClose()} isDismissable={true} size="lg">
          <ModalContent>
            <ModalHeader>Edit Host: {host.name}</ModalHeader>
            <ModalBody className="gap-4">
              <Input labelPlacement="inside" label="Host Name"
              value={editName}
              onValueChange={setEditName}
              placeholder="My Server" />
              
              <Divider />
              <p className="text-sm font-medium">SSH Connection</p>
              
              <div className="grid grid-cols-2 gap-3">
                <Input labelPlacement="inside" label="SSH Host"
                value={editSshHost}
                onValueChange={setEditSshHost}
                placeholder="hostname or IP"
                className="col-span-2" />
                <Input labelPlacement="inside" label="SSH Port"
                value={editSshPort}
                onValueChange={setEditSshPort}
                placeholder="22"
                type="number" />
                <Input labelPlacement="inside" label="SSH User"
                value={editSshUser}
                onValueChange={setEditSshUser}
                placeholder="root" />
                <Input labelPlacement="inside" label="SSH Key Path"
                value={editSshKeyPath}
                onValueChange={setEditSshKeyPath}
                placeholder="~/.ssh/id_rsa"
                description="Leave empty for default key"
                className="col-span-2" />
              </div>

              {host.type === "colab" && (
                <>
                  <Divider />
                  <p className="text-sm font-medium">Colab Connection</p>
                  <Input labelPlacement="inside" label="Cloudflared Hostname"
                  value={editCloudflaredHostname}
                  onValueChange={setEditCloudflaredHostname}
                  placeholder="xxx-xxx-xxx.trycloudflare.com"
                  description="Run cloudflared tunnel in Colab to get this" />
                </>
              )}

              <Divider />
              <p className="text-sm font-medium">Environment Variables</p>
              <Textarea labelPlacement="inside" label="Environment Variables"
              value={editEnvVars}
              onValueChange={setEditEnvVars}
              placeholder="LD_LIBRARY_PATH=/usr/lib64-nvidia:$LD_LIBRARY_PATH&#10;PATH=/usr/local/cuda/bin:$PATH"
              description="One variable per line: KEY=value. Lines starting with # are ignored."
              minRows={3}
              maxRows={8}
              classNames={{ input: "font-mono text-sm" }} />

              {updateMutation.error && (
                <p className="text-sm text-danger">
                  Error: {updateMutation.error instanceof Error ? updateMutation.error.message : String(updateMutation.error)}
                </p>
              )}
            </ModalBody>
            <ModalFooter>
              <Button variant="flat" onPress={editModal.onClose}>
                Cancel
              </Button>
              <Button
                color="primary"
                onPress={() => updateMutation.mutate()}
                isLoading={updateMutation.isPending}
              >
                Save Changes
              </Button>
            </ModalFooter>
          </ModalContent>
        </Modal>
      )}

      {/* GPU Detail Modal */}
      <GpuDetailModal 
        gpu={selectedGpu} 
        isOpen={gpuModal.isOpen} 
        onClose={() => {
          gpuModal.onClose();
          setSelectedGpuIndex(null);
        }} 
      />

      {/* Tmux Session Select Modal */}
      <TmuxSessionSelectModal
        sessions={remoteTmuxSessions}
        isOpen={tmuxModal.isOpen}
        onClose={() => {
          tmuxModal.onClose();
          setIsLoadingTmuxSessions(false);
        }}
        onSelect={(name) => void connectToTmuxSession(name)}
        onCreate={(name) => void connectToTmuxSession(name)}
        isLoading={isLoadingTmuxSessions}
      />
      
      {/* Delete Confirmation Modal */}
      {!isVast && (
        <Modal isOpen={deleteModal.isOpen} onClose={deleteModal.onClose}>
          <ModalContent>
            <ModalHeader>Delete Host</ModalHeader>
            <ModalBody>
              <p>Are you sure you want to delete "{host.name}"? This action cannot be undone.</p>
            </ModalBody>
            <ModalFooter>
              <Button variant="flat" onPress={deleteModal.onClose}>
                Cancel
              </Button>
              <Button 
                color="danger" 
                onPress={() => {
                  deleteMutation.mutate();
                  deleteModal.onClose();
                }}
                isLoading={deleteMutation.isPending}
              >
                Delete
              </Button>
            </ModalFooter>
          </ModalContent>
        </Modal>
      )}
    </div>
  );
}

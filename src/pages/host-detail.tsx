import {
  Card,
  CardBody,
  CardHeader,
  Chip,
  Divider,
  Input,
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
  Listbox,
  ListboxItem,
} from "@nextui-org/react";
import { Button } from "../components/ui";
import type { GpuInfo } from "../lib/types";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useNavigate } from "@tanstack/react-router";
import { useState, useEffect } from "react";
import { hostApi, termOpenSshTmux, pricingApi, useSyncVastPricing, useHostCostBreakdown, useStorages, type RemoteTmuxSession } from "../lib/tauri-api";
import { StatusBadge } from "../components/shared/StatusBadge";

// Icons
function IconArrowLeft() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
    </svg>
  );
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

function IconGpu() {
  return (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
      <rect x="2" y="6" width="20" height="12" rx="2" />
      <path d="M6 10h2v4H6z M10 10h2v4h-2z M14 10h2v4h-2z" fill="currentColor" />
      <path d="M5 6V4M9 6V4M15 6V4M19 6V4M5 18v2M9 18v2M15 18v2M19 18v2" strokeLinecap="round" />
    </svg>
  );
}

// Temperature color helper
function getTempColor(temp: number | null | undefined): string {
  if (temp == null) return "text-foreground/60";
  if (temp < 50) return "text-success";
  if (temp < 70) return "text-warning";
  return "text-danger";
}

// Format price helper
function formatUsd(value: number, decimals = 4): string {
  return `$${value.toFixed(decimals)}`;
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
              <p className="font-mono text-success">{formatUsd(cost.gpu_per_hour_usd)}/hr</p>
            </div>
            <div>
              <p className="text-sm text-foreground/60">Storage Cost</p>
              <p className="font-mono">{formatUsd(cost.storage_per_hour_usd, 6)}/hr</p>
              {cost.storage_gb > 0 && (
                <p className="text-xs text-foreground/50">{cost.storage_gb.toFixed(1)} GB</p>
              )}
            </div>
            <div>
              <p className="text-sm text-foreground/60">Total Hourly</p>
              <p className="font-mono font-semibold text-primary">{formatUsd(cost.total_per_hour_usd)}/hr</p>
            </div>
            <div>
              <p className="text-sm text-foreground/60">Monthly Est.</p>
              <p className="font-mono">{formatUsd(cost.total_per_month_usd, 2)}/mo</p>
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

// Tmux Session Select Modal
function TmuxSessionSelectModal({
  sessions,
  isOpen,
  onClose,
  onSelect,
  onCreate,
  isLoading,
}: {
  sessions: RemoteTmuxSession[];
  isOpen: boolean;
  onClose: () => void;
  onSelect: (sessionName: string) => void;
  onCreate: (sessionName: string) => void;
  isLoading: boolean;
}) {
  const [newSessionName, setNewSessionName] = useState("");

  const handleCreate = () => {
    const name = newSessionName.trim() || "main";
    onCreate(name);
  };

  return (
    <Modal isOpen={isOpen} onOpenChange={(open) => !open && onClose()} isDismissable={true} size="md">
      <ModalContent>
        <ModalHeader className="flex items-center gap-2">
          <IconTerminal />
          Select Tmux Session
        </ModalHeader>
        <ModalBody className="gap-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Spinner size="lg" />
            </div>
          ) : sessions.length === 0 ? (
            <div className="text-center py-4">
              <p className="text-foreground/60 mb-4">No tmux sessions running on this host.</p>
              <p className="text-sm text-foreground/50">A new session will be created when you connect.</p>
            </div>
          ) : (
            <>
              <p className="text-sm text-foreground/60">
                Found {sessions.length} existing session{sessions.length > 1 ? "s" : ""}. Select one to attach:
              </p>
              <Listbox
                aria-label="Tmux sessions"
                selectionMode="single"
                onAction={(key) => onSelect(String(key))}
                className="p-0"
              >
                {sessions.map((s) => (
                  <ListboxItem
                    key={s.name}
                    description={
                      <span className="flex items-center gap-2">
                        <span>{s.windows} window{s.windows !== 1 ? "s" : ""}</span>
                        {s.attached && (
                          <Chip size="sm" color="success" variant="flat" className="h-5">
                            attached
                          </Chip>
                        )}
                      </span>
                    }
                    className="py-3"
                  >
                    <span className="font-mono font-medium">{s.name}</span>
                  </ListboxItem>
                ))}
              </Listbox>
              <Divider />
            </>
          )}

          {/* Create new session */}
          <div>
            <p className="text-sm font-medium mb-2">Or create a new session:</p>
            <div className="flex gap-2">
              <Input
                placeholder="Session name (default: main)"
                value={newSessionName}
                onValueChange={setNewSessionName}
                size="sm"
                className="flex-1"
                classNames={{ input: "font-mono" }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleCreate();
                }}
              />
              <Button
                color="primary"
                size="sm"
                onPress={handleCreate}
                className="min-w-[80px]"
              >
                Create
              </Button>
            </div>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button variant="flat" onPress={onClose}>
            Cancel
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
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

export function HostDetailPage() {
  const { id } = useParams({ from: "/hosts/$id" });
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const editModal = useDisclosure();
  const gpuModal = useDisclosure();
  const tmuxModal = useDisclosure();
  const deleteModal = useDisclosure();

  // GPU detail state
  const [selectedGpu, setSelectedGpu] = useState<GpuInfo | null>(null);

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

  const hostQuery = useQuery({
    queryKey: ["hosts", id],
    queryFn: () => hostApi.get(id),
    enabled: !!id,
  });

  // Get storages linked to this host
  const storagesQuery = useStorages();
  const linkedStorages = (storagesQuery.data ?? []).filter(
    (s) => s.backend.type === "ssh_remote" && s.backend.host_id === id
  );

  // Initialize edit form when host data loads
  useEffect(() => {
    if (hostQuery.data) {
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
  }, [hostQuery.data]);

  const testMutation = useMutation({
    mutationFn: () => hostApi.testConnection(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["hosts", id] });
    },
  });

  const refreshMutation = useMutation({
    mutationFn: () => hostApi.refresh(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["hosts", id] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => hostApi.remove(id),
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
      
      return await hostApi.update(id, config);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["hosts", id] });
      queryClient.invalidateQueries({ queryKey: ["hosts"] });
      editModal.onClose();
    },
  });

  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);

  // Clear test result when switching hosts
  useEffect(() => {
    setTestResult(null);
    setSelectedGpu(null);
  }, [id]);

  async function handleTest() {
    setTestResult(null);
    const result = await testMutation.mutateAsync();
    setTestResult(result);
  }

  async function handleOpenTerminal() {
    const host = hostQuery.data;
    if (!host?.ssh) {
      alert("No SSH configuration for this host");
      return;
    }

    try {
      setIsLoadingTmuxSessions(true);
      
      // Check for existing tmux sessions
      const sessions = await hostApi.listTmuxSessions(id);
      
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

  async function connectToTmuxSession(sessionName: string) {
    const host = hostQuery.data;
    if (!host?.ssh) return;

    try {
      console.log("Opening terminal for host:", host.name, "session:", sessionName);
      await termOpenSshTmux({
        ssh: {
          host: host.ssh.host,
          port: host.ssh.port,
          user: host.ssh.user,
          keyPath: host.ssh.keyPath ?? host.ssh.key_path ?? null,
          extraArgs: host.ssh.extraArgs ?? host.ssh.extra_args ?? [],
        },
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

  if (hostQuery.isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Spinner size="lg" />
      </div>
    );
  }

  if (hostQuery.error || !hostQuery.data) {
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

  const host = hostQuery.data;

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
              Created {new Date(host.created_at).toLocaleDateString()}
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="flat"
              startContent={<IconTerminal />}
              onPress={handleOpenTerminal}
              isDisabled={!host.ssh}
            >
              Terminal
            </Button>
            <Button
              variant="flat"
              startContent={<IconEdit />}
              onPress={editModal.onOpen}
            >
              Edit
            </Button>
            <Button
              variant="flat"
              startContent={<IconRefresh />}
              onPress={() => refreshMutation.mutate()}
              isLoading={refreshMutation.isPending}
            >
              Refresh
            </Button>
            <Button
              color="danger"
              variant="flat"
              startContent={<IconTrash />}
              onPress={deleteModal.onOpen}
              isLoading={deleteMutation.isPending}
            >
              Delete
            </Button>
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
                    >
                      Test Connection
                    </Button>
                  </div>
                </CardHeader>
                <Divider />
                <CardBody className="gap-4">
                  {host.ssh ? (
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <p className="text-sm text-foreground/60">Host</p>
                        <p className="font-mono">{host.ssh.host}</p>
                      </div>
                      <div>
                        <p className="text-sm text-foreground/60">Port</p>
                        <p className="font-mono">{host.ssh.port}</p>
                      </div>
                      <div>
                        <p className="text-sm text-foreground/60">User</p>
                        <p className="font-mono">{host.ssh.user}</p>
                      </div>
                      <div>
                        <p className="text-sm text-foreground/60">Key Path</p>
                        <p className="font-mono text-sm truncate">{host.ssh.keyPath ?? host.ssh.key_path ?? "default"}</p>
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
                </CardBody>
              </Card>

              {/* System Info Card */}
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between w-full">
                    <span className="font-semibold">System Information</span>
                    {!host.system_info && (
                      <Button
                        size="sm"
                        variant="flat"
                        onPress={() => refreshMutation.mutate()}
                        isLoading={refreshMutation.isPending}
                      >
                        Fetch Info
                      </Button>
                    )}
                  </div>
                </CardHeader>
                <Divider />
                <CardBody className="gap-4">
                  {host.system_info ? (
                    <>
                      {/* OS & Hostname */}
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <p className="text-sm text-foreground/60">OS</p>
                          <p className="text-sm">{host.system_info.os ?? "-"}</p>
                        </div>
                        <div>
                          <p className="text-sm text-foreground/60">Hostname</p>
                          <p className="text-sm font-mono">{host.system_info.hostname ?? "-"}</p>
                        </div>
                      </div>

                      {/* CPU */}
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <p className="text-sm text-foreground/60">CPU</p>
                          <p className="text-sm">{host.system_info.cpu_model ?? "-"}</p>
                        </div>
                        <div>
                          <p className="text-sm text-foreground/60">Cores</p>
                          <p className="text-sm">{host.system_info.cpu_cores ?? "-"}</p>
                        </div>
                      </div>

                      {/* Memory */}
                      <div className="grid grid-cols-3 gap-4">
                        <div>
                          <p className="text-sm text-foreground/60">Memory Total</p>
                          <p className="text-sm">{host.system_info.memory_total_gb?.toFixed(1) ?? "-"} GB</p>
                        </div>
                        <div>
                          <p className="text-sm text-foreground/60">Memory Used</p>
                          <p className="text-sm">{host.system_info.memory_used_gb?.toFixed(1) ?? "-"} GB</p>
                        </div>
                        <div>
                          <p className="text-sm text-foreground/60">Memory Available</p>
                          <p className="text-sm">{host.system_info.memory_available_gb?.toFixed(1) ?? "-"} GB</p>
                        </div>
                      </div>

                      {/* Disks */}
                      {host.system_info.disks && host.system_info.disks.length > 0 && (
                        <div>
                          <p className="text-sm text-foreground/60 mb-2">Disks ({host.system_info.disks.length})</p>
                          <div className="space-y-2">
                            {host.system_info.disks.map((disk) => (
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

                      {/* GPUs */}
                      {host.system_info.gpu_list.length > 0 ? (
                        <div>
                          <p className="text-sm text-foreground/60 mb-2">GPUs ({host.system_info.gpu_list.length})</p>
                          <div className="space-y-2">
                            {host.system_info.gpu_list.map((gpu) => {
                              const memUsedPct = gpu.memory_used_mb != null 
                                ? Math.round((gpu.memory_used_mb / gpu.memory_total_mb) * 100) 
                                : 0;
                              return (
                                <Tooltip key={gpu.index} content="Click for details" delay={500}>
                                  <div 
                                    className="p-3 rounded-lg bg-content2 cursor-pointer hover:bg-content3 transition-colors border border-transparent hover:border-primary/30"
                                    onClick={() => {
                                      setSelectedGpu(gpu);
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
                                    
                                    {/* VRAM Progress */}
                                    <div className="mb-2">
                                      <div className="flex justify-between text-xs mb-1">
                                        <span className="text-foreground/60">VRAM</span>
                                        <span>
                                          {gpu.memory_used_mb != null && (
                                            <>{(gpu.memory_used_mb / 1024).toFixed(1)} / </>
                                          )}
                                          {(gpu.memory_total_mb / 1024).toFixed(0)} GB
                                          {gpu.memory_used_mb != null && (
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

                                    {/* Quick stats row */}
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
                      ) : (
                        <div>
                          <p className="text-sm text-foreground/60">GPU</p>
                          <p className="text-sm">No NVIDIA GPU detected</p>
                        </div>
                      )}
                    </>
                  ) : (
                    <p className="text-foreground/60">
                      Click "Refresh" or "Fetch Info" to retrieve system information
                    </p>
                  )}
                </CardBody>
              </Card>

              {/* Type-specific Info */}
              {host.type === "vast" && host.vast_instance_id && (
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
                            <span>{storage.icon || "📁"}</span>
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
                          <p className="font-mono text-sm">{host.ssh.host}</p>
                        </div>
                        <div>
                          <p className="text-sm text-foreground/60">SSH Port</p>
                          <p className="font-mono">{host.ssh.port}</p>
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
      <Modal isOpen={editModal.isOpen} onOpenChange={(open) => !open && editModal.onClose()} isDismissable={true} size="lg">
        <ModalContent>
          <ModalHeader>Edit Host: {host.name}</ModalHeader>
          <ModalBody className="gap-4">
            <Input
              label="Host Name"
              value={editName}
              onValueChange={setEditName}
              placeholder="My Server"
            />
            
            <Divider />
            <p className="text-sm font-medium">SSH Connection</p>
            
            <div className="grid grid-cols-2 gap-3">
              <Input
                label="SSH Host"
                value={editSshHost}
                onValueChange={setEditSshHost}
                placeholder="hostname or IP"
                className="col-span-2"
              />
              <Input
                label="SSH Port"
                value={editSshPort}
                onValueChange={setEditSshPort}
                placeholder="22"
                type="number"
              />
              <Input
                label="SSH User"
                value={editSshUser}
                onValueChange={setEditSshUser}
                placeholder="root"
              />
              <Input
                label="SSH Key Path"
                value={editSshKeyPath}
                onValueChange={setEditSshKeyPath}
                placeholder="~/.ssh/id_rsa"
                description="Leave empty for default key"
                className="col-span-2"
              />
            </div>

            {host.type === "colab" && (
              <>
                <Divider />
                <p className="text-sm font-medium">Colab Connection</p>
                <Input
                  label="Cloudflared Hostname"
                  value={editCloudflaredHostname}
                  onValueChange={setEditCloudflaredHostname}
                  placeholder="xxx-xxx-xxx.trycloudflare.com"
                  description="Run cloudflared tunnel in Colab to get this"
                />
              </>
            )}

            <Divider />
            <p className="text-sm font-medium">Environment Variables</p>
            <Textarea
              label="Environment Variables"
              value={editEnvVars}
              onValueChange={setEditEnvVars}
              placeholder="LD_LIBRARY_PATH=/usr/lib64-nvidia:$LD_LIBRARY_PATH&#10;PATH=/usr/local/cuda/bin:$PATH"
              description="One variable per line: KEY=value. Lines starting with # are ignored."
              minRows={3}
              maxRows={8}
              classNames={{ input: "font-mono text-sm" }}
            />

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

      {/* GPU Detail Modal */}
      <GpuDetailModal 
        gpu={selectedGpu} 
        isOpen={gpuModal.isOpen} 
        onClose={() => {
          gpuModal.onClose();
          setSelectedGpu(null);
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
    </div>
  );
}


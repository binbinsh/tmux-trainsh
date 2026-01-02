import {
  Card,
  CardContent,
  Separator,
  Input,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  Button,
  Label,
  Skeleton,
} from "@/components/ui";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState, useEffect, useMemo } from "react";
import { copyText } from "../lib/clipboard";
import {
  hostApi,
  useVastInstances,
  usePricingSettings,
  getConfig,
  sshPublicKey,
} from "../lib/tauri-api";
import type { Host, HostConfig, HostType, VastInstance, ExchangeRates, Currency } from "../lib/types";
import { open } from "@tauri-apps/plugin-shell";
import { formatPriceWithRates } from "../lib/currency";
import { formatGpuCountLabel } from "../lib/gpu";
import {
  SavedHostRow,
  VastInstanceRow,
  HostSection,
  EmptyHostState,
} from "../components/shared/HostCard";
import { cn } from "@/lib/utils";
import {
  Plus,
  Terminal,
  Search,
  Filter,
  ArrowUpDown,
  Copy,
  Check,
  Server,
  Loader2,
} from "lucide-react";

// Copyable code block component
function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    await copyText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="relative group">
      <pre className="bg-muted border border-border rounded-lg p-3 text-xs font-mono overflow-x-auto whitespace-pre-wrap">
        {code}
      </pre>
      <Button
        size="sm"
        variant="outline"
        className={cn(
          "absolute top-2 right-2 h-8 w-8 p-0 opacity-0 group-hover:opacity-100 transition-opacity"
        )}
        onClick={handleCopy}
      >
        {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </Button>
    </div>
  );
}

// SkeletonSection component (local to this file)
function SkeletonSection({ itemCount }: { itemCount: number }) {
  return (
    <div className="space-y-4">
      <Skeleton className="h-6 w-32" />
      <div className="space-y-2">
        {Array.from({ length: itemCount }).map((_, i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    </div>
  );
}

export function HostListPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [addHostModalOpen, setAddHostModalOpen] = useState(false);

  // State
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedHostId, setSelectedHostId] = useState<string | null>(null);
  const [selectedVastId, setSelectedVastId] = useState<number | null>(null);
  const [filterStatus, setFilterStatus] = useState<"all" | "online" | "offline">("all");
  const [sortBy, setSortBy] = useState<"name" | "recent">("name");

  const cfgQuery = useQuery({
    queryKey: ["config"],
    queryFn: getConfig,
  });

  // Hosts query
  const hostsQuery = useQuery({
    queryKey: ["hosts"],
    queryFn: hostApi.list,
  });

  // Vast instances query
  const vastQuery = useVastInstances();

  // Pricing settings for currency display
  const pricingQuery = usePricingSettings();
  const displayCurrency = pricingQuery.data?.display_currency ?? "USD";
  const exchangeRates = pricingQuery.data?.exchange_rates ?? null;

  // Mutations
  const addHostMutation = useMutation({
    mutationFn: hostApi.add,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["hosts"] });
      setAddHostModalOpen(false);
    },
  });

  // Add Host state
  const [addHostTab, setAddHostTab] = useState<string>("custom");
  const [newHost, setNewHost] = useState<Partial<HostConfig>>({
    name: "",
    type: "custom",
    ssh_host: "",
    ssh_port: 22,
    ssh_user: "root",
  });

  // Colab SSH public key state
  const [colabPubKey, setColabPubKey] = useState<string>("");
  const [colabPubKeyError, setColabPubKeyError] = useState<string>("");

  // Load SSH public key for Colab tab
  useEffect(() => {
    let cancelled = false;

    if (addHostTab === "colab" && addHostModalOpen) {
      (async () => {
        try {
          const cfg = await getConfig();
          if (cancelled) return;

          if (cfg.vast?.ssh_key_path) {
            const pk = await sshPublicKey(cfg.vast.ssh_key_path);
            if (cancelled) return;
            setColabPubKey(pk);
            setColabPubKeyError("");
          } else {
            if (cancelled) return;
            setColabPubKeyError("No SSH key configured. Configure it in Settings first.");
          }
        } catch (e) {
          if (cancelled) return;
          setColabPubKeyError("Failed to load SSH key. Configure it in Settings first.");
        }
      })();
    }

    return () => {
      cancelled = true;
    };
  }, [addHostTab, addHostModalOpen]);

  useEffect(() => {
    if (!addHostModalOpen) {
      setColabPubKey("");
      setColabPubKeyError("");
    }
  }, [addHostModalOpen]);

  function handleAddHost() {
    if (!newHost.name) return;
    addHostMutation.mutate(newHost as HostConfig);
  }

  const hosts = hostsQuery.data ?? [];
  const vastInstances = vastQuery.data ?? [];

  async function openVastConsole() {
    const cfg = await getConfig();
    const rawUrl = cfg.vast?.url?.trim();
    const url =
      rawUrl && rawUrl !== "https://console.vast.ai"
        ? rawUrl
        : "https://cloud.vast.ai/";
    await open(url);
  }

  // Filter and sort
  const filteredHosts = useMemo(() => {
    let result = hosts;

    // Search filter
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      result = result.filter((h) =>
        h.name.toLowerCase().includes(query) ||
        h.ssh?.host?.toLowerCase().includes(query)
      );
    }

    // Status filter
    if (filterStatus === "online") {
      result = result.filter((h) => h.status === "online");
    } else if (filterStatus === "offline") {
      result = result.filter((h) => h.status !== "online");
    }

    // Sort
    if (sortBy === "name") {
      result = [...result].sort((a, b) => a.name.localeCompare(b.name));
    } else if (sortBy === "recent") {
      result = [...result].sort((a, b) => {
        const aTime = a.last_seen_at ? new Date(a.last_seen_at).getTime() : 0;
        const bTime = b.last_seen_at ? new Date(b.last_seen_at).getTime() : 0;
        return bTime - aTime;
      });
    }

    return result;
  }, [hosts, searchQuery, filterStatus, sortBy]);

  const filteredVastInstances = useMemo(() => {
    let result = vastInstances;

    // Search filter
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      result = result.filter((i) =>
        (i.label?.toLowerCase().includes(query)) ||
        String(i.id).includes(query)
      );
    }

    // Status filter
    if (filterStatus === "online") {
      result = result.filter((i) => getVastBadgeStatus(i) === "running");
    } else if (filterStatus === "offline") {
      result = result.filter((i) => getVastBadgeStatus(i) !== "running");
    }

    return result;
  }, [vastInstances, searchQuery, filterStatus]);

  const sshUser = cfgQuery.data?.vast.ssh_user?.trim() || "root";
  const sshPreference = cfgQuery.data?.vast.ssh_connection_preference === "direct" ? "direct" : "proxy";

  // Connect handler
  function handleConnect() {
    if (selectedHostId) {
      const host = hosts.find((h) => h.id === selectedHostId);
      if (host?.ssh) {
        navigate({
          to: "/terminal",
          search: { connectHostId: host.id, connectVastInstanceId: undefined, connectLabel: host.name },
        });
      }
    } else if (selectedVastId) {
      const inst = vastInstances.find((i) => i.id === selectedVastId);
      if (inst) {
        const sshAddress = buildVastSshAddress(inst, sshUser, sshPreference);
        if (sshAddress) {
          navigate({
            to: "/terminal",
            search: { connectHostId: undefined, connectVastInstanceId: String(inst.id), connectLabel: inst.label ?? `vast #${inst.id}` },
          });
        }
      }
    }
  }

  const canConnect = Boolean(
    (selectedHostId && hosts.find((h) => h.id === selectedHostId)?.ssh) ||
    (selectedVastId && buildVastSshAddress(
      vastInstances.find((i) => i.id === selectedVastId)!,
      sshUser,
      sshPreference
    ))
  );

  return (
    <div className="doppio-page">
      <div className="doppio-page-content">
        {/* Termius-style Toolbar */}
        <div className="termius-toolbar">
          {/* Row 1: Search + Connect */}
          <div className="termius-toolbar-row">
            <div className="termius-search-bar">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-foreground/40" />
                <Input
                  placeholder="Search hosts..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="h-12 pl-10 pr-28 text-base"
                />
                <Button
                  size="sm"
                  className="absolute right-2 top-1/2 -translate-y-1/2 h-8 px-4"
                  onClick={handleConnect}
                  disabled={!canConnect}
                >
                  Connect
                </Button>
              </div>
            </div>
          </div>

          {/* Row 2: Quick Actions + Filters */}
          <div className="termius-toolbar-row justify-between">
            <div className="termius-quick-actions">
              <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setAddHostModalOpen(true)}>
                <Plus className="w-4 h-4" />
                <span>New Host</span>
              </Button>
              <Button
                variant="outline" size="sm" className="gap-1.5"
                onClick={() => navigate({ to: "/terminal", search: { connectHostId: undefined, connectVastInstanceId: undefined, connectLabel: undefined } })}
              >
                <Terminal className="w-4 h-4" />
                <span>Terminal</span>
              </Button>
              <Button variant="outline" size="sm" className="gap-1.5" onClick={() => { void openVastConsole(); }}>
                <span>Rent from Vast.ai</span>
              </Button>
            </div>

            <div className="flex items-center gap-1">
              {/* Filter dropdown */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" className={cn("gap-1.5", filterStatus !== "all" && "bg-primary text-primary-foreground")}>
                    <Filter className="w-4 h-4" />
                    <span>{filterStatus === "all" ? "Filter" : filterStatus}</span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                  <DropdownMenuItem onClick={() => setFilterStatus("all")}>
                    All
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setFilterStatus("online")}>
                    Online
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setFilterStatus("offline")}>
                    Offline
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>

              {/* Sort dropdown */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" className="gap-1.5">
                    <ArrowUpDown className="w-4 h-4" />
                    <span>{sortBy === "name" ? "Name" : "Recent"}</span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                  <DropdownMenuItem onClick={() => setSortBy("name")}>
                    Name
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setSortBy("recent")}>
                    Recent
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        </div>

        {/* Content */}
        {hostsQuery.isLoading || vastQuery.isLoading ? (
          <>
            <SkeletonSection itemCount={3} />
            <SkeletonSection itemCount={2} />
          </>
        ) : (
          <>
            {/* Saved Hosts Section */}
            {filteredHosts.length > 0 && (
              <HostSection title="LOCAL" count={filteredHosts.length}>
                {filteredHosts.map((host) => (
                  <SavedHostRow
                    key={host.id}
                    host={host}
                    isSelected={selectedHostId === host.id}
                    onClick={() => {
                      setSelectedHostId(host.id);
                      setSelectedVastId(null);
                    }}
                    onDoubleClick={() => {
                      if (host.ssh) {
                        navigate({
                          to: "/terminal",
                          search: { connectHostId: host.id, connectVastInstanceId: undefined, connectLabel: host.name },
                        });
                      }
                    }}
                    onEdit={() => {
                      navigate({ to: "/hosts/$id", params: { id: host.id } });
                    }}
                  />
                ))}
              </HostSection>
            )}

            {/* Vast.ai Instances Section */}
            {filteredVastInstances.length > 0 && (
              <HostSection title="VAST.AI" count={filteredVastInstances.length}>
                {filteredVastInstances.map((inst) => {
                  const isOnline = getVastBadgeStatus(inst) === "running";
                  const sshAddress = buildVastSshAddress(inst, sshUser, sshPreference);
                  const gpuLabel = inst.gpu_name ? formatGpuCountLabel(inst.gpu_name, inst.num_gpus) : undefined;
                  const costLabel = getVastCostLabel(inst, displayCurrency, exchangeRates);

                  return (
                    <VastInstanceRow
                      key={inst.id}
                      instance={inst}
                      sshAddress={sshAddress}
                      gpuLabel={gpuLabel}
                      costLabel={costLabel}
                      isOnline={isOnline}
                      isSelected={selectedVastId === inst.id}
                      onClick={() => {
                        setSelectedVastId(inst.id);
                        setSelectedHostId(null);
                      }}
                      onDoubleClick={() => {
                        navigate({ to: "/hosts/vast/$id", params: { id: String(inst.id) } });
                      }}
                      onEdit={() => {
                        navigate({ to: "/hosts/vast/$id", params: { id: String(inst.id) } });
                      }}
                    />
                  );
                })}
              </HostSection>
            )}

            {/* Empty state */}
            {filteredHosts.length === 0 && filteredVastInstances.length === 0 && (
              <EmptyHostState
                icon={<Server className="w-5 h-5" />}
                title={searchQuery ? "No hosts match your search" : "No hosts yet"}
                description={searchQuery ? undefined : "Add a host to get started with remote connections."}
                action={
                  !searchQuery ? (
                    <Button size="sm" onClick={() => setAddHostModalOpen(true)}>
                      Add Host
                    </Button>
                  ) : undefined
                }
              />
            )}
          </>
        )}

        {/* Add Host Modal */}
        <Dialog open={addHostModalOpen} onOpenChange={setAddHostModalOpen}>
          <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>Add Host</DialogTitle>
            </DialogHeader>
            <div className="py-4">
              <Tabs value={addHostTab} onValueChange={setAddHostTab}>
                <TabsList className="grid w-full grid-cols-2">
                  <TabsTrigger value="custom">Custom SSH</TabsTrigger>
                  <TabsTrigger value="colab">Google Colab</TabsTrigger>
                </TabsList>
                <TabsContent value="custom" className="space-y-4 pt-4">
                  <div className="space-y-2">
                    <Label htmlFor="host-name">Host Name *</Label>
                    <Input
                      id="host-name"
                      placeholder="my-training-server"
                      value={newHost.name ?? ""}
                      onChange={(e) => setNewHost({ ...newHost, name: e.target.value })}
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="ssh-host">SSH Host *</Label>
                    <Input
                      id="ssh-host"
                      placeholder="192.168.1.100 or hostname.example.com"
                      value={newHost.ssh_host ?? ""}
                      onChange={(e) => setNewHost({ ...newHost, ssh_host: e.target.value })}
                      required
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="ssh-port">SSH Port</Label>
                      <Input
                        id="ssh-port"
                        type="number"
                        value={String(newHost.ssh_port ?? 22)}
                        onChange={(e) => setNewHost({ ...newHost, ssh_port: parseInt(e.target.value) || 22 })}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="ssh-user">SSH User</Label>
                      <Input
                        id="ssh-user"
                        placeholder="root"
                        value={newHost.ssh_user ?? ""}
                        onChange={(e) => setNewHost({ ...newHost, ssh_user: e.target.value })}
                      />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="ssh-key-path">SSH Key Path (optional)</Label>
                    <Input
                      id="ssh-key-path"
                      placeholder="~/.ssh/id_rsa"
                      value={newHost.ssh_key_path ?? ""}
                      onChange={(e) => setNewHost({ ...newHost, ssh_key_path: e.target.value || null })}
                    />
                  </div>
                </TabsContent>

                <TabsContent value="colab" className="space-y-4 pt-4">
                  {colabPubKeyError && (
                    <Card className="bg-danger/10 border border-danger/30">
                      <CardContent className="pt-6">
                        <p className="text-sm text-danger">{colabPubKeyError}</p>
                      </CardContent>
                    </Card>
                  )}

                  <Card className="bg-muted">
                    <CardContent className="space-y-3 pt-6">
                      <p className="text-sm font-medium">One-Click Setup</p>
                      <p className="text-xs text-foreground/60">
                        Copy this entire code block and paste it into a Colab cell, then run it:
                      </p>

                      <CodeBlock code={`# === Doppio Colab Setup ===
!wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb && dpkg -i cloudflared-linux-amd64.deb
!apt-get update -qq && apt-get install -y -qq openssh-server
!mkdir -p /var/run/sshd ~/.ssh && echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config
!echo '${colabPubKey.trim() || "YOUR_SSH_PUBLIC_KEY_HERE"}' > ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
!service ssh start

import subprocess, re, time
proc = subprocess.Popen(['cloudflared', 'tunnel', '--url', 'ssh://localhost:22'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
for _ in range(30):
    line = proc.stdout.readline()
    if 'trycloudflare.com' in line:
        match = re.search(r'https://([\\w-]+\\.trycloudflare\\.com)', line)
        if match: print(f"\\n✅ Hostname: {match.group(1)}"); break
    time.sleep(0.5)`} />

                      <p className="text-xs text-foreground/60">
                        Copy the hostname and paste it below.
                      </p>
                    </CardContent>
                  </Card>

                  <Separator />

                  <div className="space-y-2">
                    <Label htmlFor="colab-name">Host Name *</Label>
                    <Input
                      id="colab-name"
                      placeholder="my-colab"
                      value={newHost.name ?? ""}
                      onChange={(e) => setNewHost({ ...newHost, name: e.target.value, type: "colab" })}
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="cloudflared-hostname">Cloudflared Hostname *</Label>
                    <Input
                      id="cloudflared-hostname"
                      placeholder="xxxx-xxxx.trycloudflare.com"
                      value={newHost.cloudflared_hostname ?? ""}
                      onChange={(e) => setNewHost({ ...newHost, cloudflared_hostname: e.target.value })}
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="colab-ssh-user">SSH User</Label>
                    <Input
                      id="colab-ssh-user"
                      placeholder="root"
                      value={newHost.ssh_user ?? "root"}
                      onChange={(e) => setNewHost({ ...newHost, ssh_user: e.target.value })}
                    />
                  </div>
                </TabsContent>
              </Tabs>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setAddHostModalOpen(false)}>
                Cancel
              </Button>
              <Button
                onClick={() => {
                  setNewHost({ ...newHost, type: addHostTab as HostType });
                  handleAddHost();
                }}
                disabled={addHostMutation.isPending || !newHost.name}
              >
                {addHostMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Add Host
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  );
}

// ============================================================
// Helper Functions
// ============================================================

type VastBadgeStatus = "running" | "stopped" | "error" | "connecting" | "online" | "offline";

function getVastBadgeStatus(inst: VastInstance): VastBadgeStatus {
  const v = (inst.actual_status ?? "").toLowerCase();
  if (v.includes("running") || v.includes("active") || v.includes("online")) return "running";
  if (v.includes("stopped") || v.includes("exited")) return "stopped";
  if (v.includes("error") || v.includes("failed")) return "error";
  if (v.includes("offline")) return "offline";
  return "connecting";
}

function buildVastSshAddress(
  inst: VastInstance,
  sshUser: string,
  sshPreference: "proxy" | "direct"
): string | null {
  const directPort = inst.machine_dir_ssh_port ?? null;
  const directHost = inst.public_ipaddr ?? null;
  const sshIdx = inst.ssh_idx ?? null;
  const rawSshPort = inst.ssh_port ?? null;
  const normalizedSshIdx = sshIdx
    ? sshIdx.startsWith("ssh") ? sshIdx : `ssh${sshIdx}`
    : null;
  const proxyHostFromApi = inst.ssh_host ?? null;
  const proxyHost = proxyHostFromApi?.includes("vast.ai")
    ? proxyHostFromApi
    : normalizedSshIdx
      ? `${normalizedSshIdx}.vast.ai`
      : null;
  const proxyPort = rawSshPort != null ? rawSshPort : null;
  const hasDirect = Boolean(directHost && directPort);
  const hasProxy = Boolean(proxyHost && proxyPort);
  const mode = sshPreference === "direct"
    ? (hasDirect ? "direct" : hasProxy ? "proxy" : null)
    : (hasProxy ? "proxy" : hasDirect ? "direct" : null);
  return mode === "direct"
    ? `${sshUser}@${directHost}:${directPort}`
    : mode === "proxy"
      ? `${sshUser}@${proxyHost}:${proxyPort}`
      : null;
}

function getVastCostLabel(
  inst: VastInstance,
  displayCurrency: Currency,
  exchangeRates: ExchangeRates | null
): string | undefined {
  const storagePerHour = inst.storage_cost != null && inst.disk_space != null
    ? (inst.storage_cost / 720) * inst.disk_space
    : null;
  const gpuPerHour = inst.dph_total ?? null;
  const totalPerHour = gpuPerHour != null || storagePerHour != null
    ? (gpuPerHour ?? 0) + (storagePerHour ?? 0)
    : null;
  if (totalPerHour == null) return undefined;
  return formatPriceWithRates(totalPerHour, "USD", displayCurrency, exchangeRates, 3);
}

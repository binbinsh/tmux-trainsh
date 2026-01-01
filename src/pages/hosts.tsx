import {
  Card,
  CardBody,
  Divider,
  Input,
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
  Tab,
  Tabs,
  useDisclosure,
  Dropdown,
  DropdownTrigger,
  DropdownMenu,
  DropdownItem,
} from "@nextui-org/react";
import { Button, SkeletonToolbar, SkeletonSection } from "../components/ui";
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

// Icons
function IconPlus({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
    </svg>
  );
}

function IconTerminal({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 7.5l3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0021 18V6a2.25 2.25 0 00-2.25-2.25H5.25A2.25 2.25 0 003 6v12a2.25 2.25 0 002.25 2.25z" />
    </svg>
  );
}

function IconSearch({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
    </svg>
  );
}

function IconFilter({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 3c2.755 0 5.455.232 8.083.678.533.09.917.556.917 1.096v1.044a2.25 2.25 0 01-.659 1.591l-5.432 5.432a2.25 2.25 0 00-.659 1.591v2.927a2.25 2.25 0 01-1.244 2.013L9.75 21v-6.568a2.25 2.25 0 00-.659-1.591L3.659 7.409A2.25 2.25 0 013 5.818V4.774c0-.54.384-1.006.917-1.096A48.32 48.32 0 0112 3z" />
    </svg>
  );
}

function IconSort({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 7.5L7.5 3m0 0L12 7.5M7.5 3v13.5m13.5 0L16.5 21m0 0L12 16.5m4.5 4.5V7.5" />
    </svg>
  );
}

function IconCopy({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-3.5 h-3.5"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" />
    </svg>
  );
}

function IconCheck({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-3.5 h-3.5"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
    </svg>
  );
}

function IconServer({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-5 h-5"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21.75 17.25v-.228a4.5 4.5 0 00-.12-1.03l-2.268-9.64a3.375 3.375 0 00-3.285-2.602H7.923a3.375 3.375 0 00-3.285 2.602l-2.268 9.64a4.5 4.5 0 00-.12 1.03v.228m19.5 0a3 3 0 01-3 3H5.25a3 3 0 01-3-3m19.5 0a3 3 0 00-3-3H5.25a3 3 0 00-3 3m16.5 0h.008v.008h-.008v-.008zm-3 0h.008v.008h-.008v-.008z" />
    </svg>
  );
}

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
      <pre className="bg-content3 rounded-lg p-3 text-xs font-mono overflow-x-auto whitespace-pre-wrap">
        {code}
      </pre>
      <Button
        size="sm"
        variant="flat"
        isIconOnly
        className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity"
        onPress={handleCopy}
      >
        {copied ? <IconCheck /> : <IconCopy />}
      </Button>
    </div>
  );
}

export function HostListPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addHostModal = useDisclosure();

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
      addHostModal.onClose();
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

    if (addHostTab === "colab" && addHostModal.isOpen) {
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
  }, [addHostTab, addHostModal.isOpen]);

  useEffect(() => {
    if (!addHostModal.isOpen) {
      setColabPubKey("");
      setColabPubKeyError("");
    }
  }, [addHostModal.isOpen]);

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
              <Input
                size="lg"
                placeholder="Search hosts..."
                value={searchQuery}
                onValueChange={setSearchQuery}
                startContent={<IconSearch className="w-5 h-5 text-foreground/40" />}
                endContent={
                  <Button
                    color="primary"
                    size="sm"
                    className="h-8 px-4"
                    onPress={handleConnect}
                    isDisabled={!canConnect}
                  >
                    Connect
                  </Button>
                }
                classNames={{
                  base: "flex-1",
                  inputWrapper: "bg-content2 h-12",
                  input: "text-base",
                }}
              />
            </div>
          </div>

          {/* Row 2: Quick Actions + Filters */}
          <div className="termius-toolbar-row justify-between">
            <div className="termius-quick-actions">
              <button
                className="termius-quick-action"
                onClick={addHostModal.onOpen}
              >
                <IconPlus className="w-4 h-4" />
                <span>New Host</span>
              </button>
              <button
                className="termius-quick-action"
                onClick={() => navigate({ to: "/terminal", search: { connectHostId: undefined, connectVastInstanceId: undefined, connectLabel: undefined } })}
              >
                <IconTerminal className="w-4 h-4" />
                <span>Terminal</span>
              </button>
              <button
                className="termius-quick-action"
                onClick={() => { void openVastConsole(); }}
              >
                <span>Rent from Vast.ai</span>
              </button>
            </div>

            <div className="flex items-center gap-1">
              {/* Filter dropdown */}
              <Dropdown>
                <DropdownTrigger>
                  <button className={`termius-quick-action ${filterStatus !== "all" ? "termius-quick-action-primary" : ""}`}>
                    <IconFilter className="w-4 h-4" />
                    <span>{filterStatus === "all" ? "Filter" : filterStatus}</span>
                  </button>
                </DropdownTrigger>
                <DropdownMenu
                  selectionMode="single"
                  selectedKeys={new Set([filterStatus])}
                  onSelectionChange={(keys) => {
                    const selected = Array.from(keys)[0] as "all" | "online" | "offline";
                    setFilterStatus(selected);
                  }}
                >
                  <DropdownItem key="all">All</DropdownItem>
                  <DropdownItem key="online">Online</DropdownItem>
                  <DropdownItem key="offline">Offline</DropdownItem>
                </DropdownMenu>
              </Dropdown>

              {/* Sort dropdown */}
              <Dropdown>
                <DropdownTrigger>
                  <button className="termius-quick-action">
                    <IconSort className="w-4 h-4" />
                    <span>{sortBy === "name" ? "Name" : "Recent"}</span>
                  </button>
                </DropdownTrigger>
                <DropdownMenu
                  selectionMode="single"
                  selectedKeys={new Set([sortBy])}
                  onSelectionChange={(keys) => {
                    const selected = Array.from(keys)[0] as "name" | "recent";
                    setSortBy(selected);
                  }}
                >
                  <DropdownItem key="name">Name</DropdownItem>
                  <DropdownItem key="recent">Recent</DropdownItem>
                </DropdownMenu>
              </Dropdown>
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
                icon={<IconServer />}
                title={searchQuery ? "No hosts match your search" : "No hosts yet"}
                description={searchQuery ? undefined : "Add a host to get started with remote connections."}
                action={
                  !searchQuery ? (
                    <Button size="sm" color="primary" onPress={addHostModal.onOpen}>
                      Add Host
                    </Button>
                  ) : undefined
                }
              />
            )}
          </>
        )}

        {/* Add Host Modal */}
        <Modal
          isOpen={addHostModal.isOpen}
          onOpenChange={addHostModal.onOpenChange}
          isDismissable={true}
          size="3xl"
          scrollBehavior="inside"
        >
          <ModalContent>
            {(onClose) => (
              <>
                <ModalHeader>Add Host</ModalHeader>
                <ModalBody>
                  <Tabs selectedKey={addHostTab} onSelectionChange={(k) => setAddHostTab(k as string)}>
                    <Tab key="custom" title="Custom SSH">
                      <div className="space-y-4 pt-4">
                        <Input labelPlacement="inside" label="Host Name"
                        placeholder="my-training-server"
                        value={newHost.name ?? ""}
                        onValueChange={(v) => setNewHost({ ...newHost, name: v })}
                        isRequired />
                        <Input labelPlacement="inside" label="SSH Host"
                        placeholder="192.168.1.100 or hostname.example.com"
                        value={newHost.ssh_host ?? ""}
                        onValueChange={(v) => setNewHost({ ...newHost, ssh_host: v })}
                        isRequired />
                        <div className="grid grid-cols-2 gap-4">
                          <Input labelPlacement="inside" label="SSH Port"
                          type="number"
                          value={String(newHost.ssh_port ?? 22)}
                          onValueChange={(v) => setNewHost({ ...newHost, ssh_port: parseInt(v) || 22 })} />
                          <Input labelPlacement="inside" label="SSH User"
                          placeholder="root"
                          value={newHost.ssh_user ?? ""}
                          onValueChange={(v) => setNewHost({ ...newHost, ssh_user: v })} />
                        </div>
                        <Input labelPlacement="inside" label="SSH Key Path (optional)"
                        placeholder="~/.ssh/id_rsa"
                        value={newHost.ssh_key_path ?? ""}
                        onValueChange={(v) => setNewHost({ ...newHost, ssh_key_path: v || null })} />
                      </div>
                    </Tab>

                    <Tab key="colab" title="Google Colab">
                      <div className="space-y-4 pt-4">
                        {colabPubKeyError && (
                          <Card className="bg-danger/10 border border-danger/30">
                            <CardBody>
                              <p className="text-sm text-danger">{colabPubKeyError}</p>
                            </CardBody>
                          </Card>
                        )}

                        <Card className="bg-content2">
                          <CardBody className="gap-3">
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
                          </CardBody>
                        </Card>

                        <Divider />

                        <Input labelPlacement="inside" label="Host Name"
                        placeholder="my-colab"
                        value={newHost.name ?? ""}
                        onValueChange={(v) => setNewHost({ ...newHost, name: v, type: "colab" })}
                        isRequired />
                        <Input labelPlacement="inside" label="Cloudflared Hostname"
                        placeholder="xxxx-xxxx.trycloudflare.com"
                        value={newHost.cloudflared_hostname ?? ""}
                        onValueChange={(v) => setNewHost({ ...newHost, cloudflared_hostname: v })}
                        isRequired />
                        <Input labelPlacement="inside" label="SSH User"
                        placeholder="root"
                        value={newHost.ssh_user ?? "root"}
                        onValueChange={(v) => setNewHost({ ...newHost, ssh_user: v })} />
                      </div>
                    </Tab>
                  </Tabs>
                </ModalBody>
                <ModalFooter>
                  <Button variant="flat" onPress={onClose}>
                    Cancel
                  </Button>
                  <Button
                    color="primary"
                    onPress={() => {
                      setNewHost({ ...newHost, type: addHostTab as HostType });
                      handleAddHost();
                    }}
                    isLoading={addHostMutation.isPending}
                    isDisabled={!newHost.name}
                  >
                    Add Host
                  </Button>
                </ModalFooter>
              </>
            )}
          </ModalContent>
        </Modal>
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

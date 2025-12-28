import {
  Card,
  CardBody,
  Chip,
  Divider,
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
  Input,
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
  Spinner,
  Tab,
  Tabs,
  useDisclosure,
} from "@nextui-org/react";
import { Button } from "../components/ui";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { motion, AnimatePresence } from "framer-motion";
import { useState, useEffect } from "react";
import { copyText } from "../lib/clipboard";
import {
  hostApi,
  useVastInstances,
  useColabPricingCalculation,
  usePricingSettings,
  vastStartInstance,
  vastStopInstance,
  vastDestroyInstance,
  vastLabelInstance,
  getConfig,
  sshPublicKey,
} from "../lib/tauri-api";
import type { Host, HostConfig, HostType, VastInstance, ColabPricingResult, ColabGpuHourlyPrice, Currency, ExchangeRates } from "../lib/types";
import { StatusBadge } from "../components/shared/StatusBadge";
import { AppIcon } from "../components/AppIcon";
import { formatPriceWithRates } from "../lib/currency";
import { open } from "@tauri-apps/plugin-shell";

// Icons
function IconPlus() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
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

function IconEllipsis() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 12.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 18.75a.75.75 0 110-1.5.75.75 0 010 1.5z" />
    </svg>
  );
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
  const labelModal = useDisclosure();

  // Hosts query
  const hostsQuery = useQuery({
    queryKey: ["hosts"],
    queryFn: hostApi.list,
  });

  // Vast instances query
  const vastQuery = useVastInstances();

  const colabPricingQuery = useColabPricingCalculation();
  const colabPricing = colabPricingQuery.data ?? null;
  const colabPricingLoading = colabPricingQuery.isLoading;
  const pricingSettingsQuery = usePricingSettings();
  const displayCurrency = pricingSettingsQuery.data?.display_currency ?? "USD";
  const exchangeRates = pricingSettingsQuery.data?.exchange_rates;

  // Mutations
  const addHostMutation = useMutation({
    mutationFn: hostApi.add,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["hosts"] });
      addHostModal.onClose();
    },
  });

  const removeHostMutation = useMutation({
    mutationFn: hostApi.remove,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["hosts"] });
    },
  });

  // Vast.ai mutations
  const vastStartMut = useMutation({
    mutationFn: (id: number) => vastStartInstance(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["vastInstances"] }),
  });

  const vastStopMut = useMutation({
    mutationFn: (id: number) => vastStopInstance(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["vastInstances"] }),
  });

  const vastDestroyMut = useMutation({
    mutationFn: (id: number) => vastDestroyInstance(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["vastInstances"] }),
  });

  const vastLabelMut = useMutation({
    mutationFn: (vars: { id: number; label: string }) => vastLabelInstance(vars.id, vars.label),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["vastInstances"] }),
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

  // Label modal state
  const [labelDraft, setLabelDraft] = useState<{ id: number; label: string } | null>(null);

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

  const onlineHosts = hostsQuery.data?.filter((h) => h.status === "online").length ?? 0;
  const vastInstances = vastQuery.data ?? [];
  const runningVast = vastInstances.filter((i) => getVastBadgeStatus(i) === "running").length;
  const [vastLastSeenAt, setVastLastSeenAt] = useState<Record<number, string>>({});

  useEffect(() => {
    if (vastInstances.length === 0) {
      return;
    }
    setVastLastSeenAt((prev) => {
      const next = { ...prev };
      for (const inst of vastInstances) {
        if (getVastBadgeStatus(inst) === "running") {
          next[inst.id] = new Date().toISOString();
        }
      }
      return next;
    });
  }, [vastInstances]);

  async function openVastConsole() {
    const cfg = await getConfig();
    const rawUrl = cfg.vast?.url?.trim();
    const url =
      rawUrl && rawUrl !== "https://console.vast.ai"
        ? rawUrl
        : "https://cloud.vast.ai/";
    await open(url);
  }

  return (
    <div className="h-full p-6 overflow-auto">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold">Hosts</h1>
            <p className="text-sm text-foreground/60">Manage your remote compute instances</p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="flat"
              startContent={<IconRefresh />}
              onPress={() => {
                hostsQuery.refetch();
                vastQuery.refetch();
              }}
              isLoading={hostsQuery.isFetching || vastQuery.isFetching}
            >
              Refresh
            </Button>
            <Button 
              variant="flat"
              onPress={() => { void openVastConsole(); }}
            >
              Rent from Vast.ai
            </Button>
            <Button color="primary" startContent={<IconPlus />} onPress={addHostModal.onOpen}>
              Add Host
            </Button>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
          <Card>
            <CardBody>
              <p className="text-sm text-foreground/60">Saved Hosts</p>
              <p className="text-2xl font-bold">{hostsQuery.data?.length ?? 0}</p>
            </CardBody>
          </Card>
          <Card>
            <CardBody>
              <p className="text-sm text-foreground/60">Online</p>
              <p className="text-2xl font-bold text-success">{onlineHosts}</p>
            </CardBody>
          </Card>
          <Card>
            <CardBody>
              <p className="text-sm text-foreground/60">Vast.ai Instances</p>
              <p className="text-2xl font-bold">{vastInstances.length}</p>
            </CardBody>
          </Card>
          <Card>
            <CardBody>
              <p className="text-sm text-foreground/60">Vast.ai Running</p>
              <p className="text-2xl font-bold text-success">{runningVast}</p>
            </CardBody>
          </Card>
        </div>

        {/* Saved Hosts */}
        <div className="mb-6">
          <h2 className="text-lg font-semibold mb-4">Saved Hosts</h2>
          {hostsQuery.isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Spinner size="lg" />
            </div>
          ) : hostsQuery.error ? (
            <Card>
              <CardBody>
                <p className="text-danger">Failed to load hosts: {String(hostsQuery.error)}</p>
              </CardBody>
            </Card>
          ) : (hostsQuery.data ?? []).length === 0 ? (
            <p className="text-foreground/60 text-sm py-4">No hosts saved yet. Add a host to get started.</p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              <AnimatePresence>
                {(hostsQuery.data ?? []).map((host, index) => (
                  <motion.div
                    key={host.id}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    transition={{ delay: index * 0.05 }}
                    className="h-full"
                  >
                    <HostCard
                      host={host}
                      onDelete={() => removeHostMutation.mutate(host.id)}
                      colabPricing={colabPricing}
                      colabPricingLoading={colabPricingLoading}
                      displayCurrency={displayCurrency}
                      exchangeRates={exchangeRates}
                    />
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          )}
        </div>

        {/* Vast.ai Instances - inline subsection */}
        <div>
          <div className="flex items-center gap-3 mb-4">
            <h2 className="text-lg font-semibold">Vast.ai Instances</h2>
            {vastQuery.isLoading && <Spinner size="sm" />}
            <span className="text-xs text-foreground/40">(auto-refresh)</span>
          </div>

          {vastQuery.error ? (
            <p className="text-danger text-sm py-2">
              Failed to load. Check your API key in Settings.
            </p>
          ) : vastInstances.length === 0 ? (
            <p className="text-foreground/60 text-sm py-2">No active instances</p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              <AnimatePresence>
                {vastInstances.map((inst, index) => (
                  <motion.div
                    key={inst.id}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    transition={{ delay: index * 0.05 }}
                    className="h-full"
                  >
                    <VastInstanceCard
                      inst={inst}
                      displayCurrency={displayCurrency}
                      exchangeRates={exchangeRates}
                      lastSeenAt={vastLastSeenAt[inst.id] ?? null}
                      onOpenDetails={() => {
                        navigate({ to: "/hosts/vast/$id", params: { id: String(inst.id) } });
                      }}
                      onStart={() => vastStartMut.mutate(inst.id)}
                      onStop={() => vastStopMut.mutate(inst.id)}
                      onDestroy={() => {
                        if (confirm(`Destroy instance ${inst.id}? This will stop billing.`)) {
                          vastDestroyMut.mutate(inst.id);
                        }
                      }}
                      onLabel={() => {
                        setLabelDraft({ id: inst.id, label: inst.label ?? "" });
                        labelModal.onOpen();
                      }}
                      isStarting={vastStartMut.isPending && vastStartMut.variables === inst.id}
                      isStopping={vastStopMut.isPending && vastStopMut.variables === inst.id}
                    />
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          )}
        </div>
      </div>

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
                      {/* Error message if no SSH key */}
                      {colabPubKeyError && (
                        <Card className="bg-danger/10 border border-danger/30">
                          <CardBody>
                            <p className="text-sm text-danger">{colabPubKeyError}</p>
                          </CardBody>
                        </Card>
                      )}

                      {/* All-in-one setup script */}
                      <Card className="bg-content2">
                        <CardBody className="gap-3">
                          <p className="text-sm font-medium">One-Click Setup</p>
                          <p className="text-xs text-foreground/60">
                            Copy this entire code block and paste it into a Colab cell, then run it:
                          </p>
                          
                          <CodeBlock code={`# === Doppio Colab Setup (copy this entire block) ===

# 1. Install cloudflared
!wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
!dpkg -i cloudflared-linux-amd64.deb

# 2. Setup SSH server with your public key
!apt-get update -qq && apt-get install -y -qq openssh-server
!mkdir -p /var/run/sshd ~/.ssh
!echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config
!echo '${colabPubKey.trim() || "YOUR_SSH_PUBLIC_KEY_HERE"}' > ~/.ssh/authorized_keys
!chmod 600 ~/.ssh/authorized_keys
!service ssh start

# 3. Start cloudflared tunnel and show hostname
import subprocess, re, time
proc = subprocess.Popen(['cloudflared', 'tunnel', '--url', 'ssh://localhost:22'],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
print("Starting tunnel...")
for _ in range(30):
    line = proc.stdout.readline()
    if 'trycloudflare.com' in line:
        match = re.search(r'https://([\\w-]+\\.trycloudflare\\.com)', line)
        if match:
            print(f"\\n✅ Hostname: {match.group(1)}")
            print("Copy the hostname above to Doppio!")
            break
    time.sleep(0.5)

# 4. Monitor GPU usage (required)
import time
import subprocess
import torch

device = torch.device("cuda:0")
torch.cuda.set_per_process_memory_fraction(0.05, device=device)
x = torch.randn(256, 256, device=device)

try:
    while True:
        with torch.no_grad():
            y = (x @ x.T).sum()
            torch.cuda.synchronize()

        allocated = round(torch.cuda.memory_allocated(device) / 1024 / 1024, 2)
        reserved = round(torch.cuda.memory_reserved(device) / 1024 / 1024, 2)

        try:
            smi = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
            ).strip()
        except Exception:
            smi = "nvidia-smi unavailable"

        print(
            f"{time.strftime('%F %T')} | alloc(MB)={allocated} reserved(MB)={reserved} | smi={smi}"
        )

        torch.cuda.empty_cache()
        time.sleep(60)
except KeyboardInterrupt:
    pass`} />
                          
                          <p className="text-xs text-foreground/60">
                            After running, copy the hostname (e.g., <code className="bg-content3 px-1 rounded">xxxx-xxxx.trycloudflare.com</code>) and paste it below.
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

      {/* Label Modal */}
      <Modal isOpen={labelModal.isOpen} onOpenChange={(open) => open ? labelModal.onOpen() : labelModal.onClose()} isDismissable={true}>
        <ModalContent>
          {(onClose) => (
            <>
              <ModalHeader>Set Instance Label</ModalHeader>
              <ModalBody>
                <Input labelPlacement="inside" label="Label"
                value={labelDraft?.label ?? ""}
                onValueChange={(v) => setLabelDraft((p) => (p ? { ...p, label: v } : p))}
                placeholder="my-training-job" />
              </ModalBody>
              <ModalFooter>
                <Button variant="flat" onPress={onClose}>
                  Cancel
                </Button>
                <Button
                  color="primary"
                  isLoading={vastLabelMut.isPending}
                  onPress={async () => {
                    if (!labelDraft) return;
                    await vastLabelMut.mutateAsync(labelDraft);
                    onClose();
                  }}
                >
                  Save
                </Button>
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>

    </div>
  );
}

function getGpuShortName(name: string): string {
  const tokens = normalizeGpuTokens(name);
  const model = tokens.find((token) => /[A-Z]+\d+/.test(token)) ?? tokens.find((token) => /\d{3,4}/.test(token));
  const size = tokens.find((token) => /\d+G$/.test(token));
  if (!model) {
    return name;
  }
  if (size && size !== model) {
    return `${model} ${size}`;
  }
  return model;
}

type GpuCount = {
  name: string;
  count: number;
};

function getHostGpuCounts(host: Host): GpuCount[] {
  const gpuList = host.system_info?.gpu_list ?? [];
  if (gpuList.length > 0) {
    const counts = new Map<string, number>();
    for (const gpu of gpuList) {
      counts.set(gpu.name, (counts.get(gpu.name) ?? 0) + 1);
    }
    return Array.from(counts.entries()).map(([name, count]) => ({ name, count }));
  }
  if (host.gpu_name) {
    return [{ name: host.gpu_name, count: host.num_gpus ?? 1 }];
  }
  return [];
}

function normalizeGpuTokens(name: string): string[] {
  const rawTokens = name
    .toUpperCase()
    .split(/[^A-Z0-9]+/)
    .filter((token) => token.length > 0);
  const tokenSet = new Set<string>();

  for (const raw of rawTokens) {
    let token = raw;
    if (token.endsWith("GIB")) {
      token = `${token.slice(0, -3)}G`;
    } else if (token.endsWith("GB")) {
      token = `${token.slice(0, -2)}G`;
    }
    if (token) {
      tokenSet.add(token);
    }
    const subTokens = token.match(/[A-Z]+\d+/g);
    if (subTokens) {
      for (const subToken of subTokens) {
        tokenSet.add(subToken);
      }
    }
  }

  return Array.from(tokenSet);
}

function findColabGpuPrice(prices: ColabGpuHourlyPrice[], gpuName: string): ColabGpuHourlyPrice | null {
  const gpuTokens = new Set(normalizeGpuTokens(gpuName));
  let bestMatch: { price: ColabGpuHourlyPrice; score: number } | null = null;

  for (const price of prices) {
    const priceTokens = normalizeGpuTokens(price.gpu_name);
    if (priceTokens.length === 0) {
      continue;
    }
    const matchesAll = priceTokens.every((token) => gpuTokens.has(token));
    if (!matchesAll) {
      continue;
    }
    const score = priceTokens.length;
    if (!bestMatch || score > bestMatch.score) {
      bestMatch = { price, score };
    }
  }

  return bestMatch?.price ?? null;
}

function calculateColabHourlyUsd(
  gpuCounts: GpuCount[],
  colabPricing: ColabPricingResult | null
): number | null {
  if (!colabPricing || gpuCounts.length === 0) {
    return null;
  }
  let total = 0;
  for (const gpu of gpuCounts) {
    const price = findColabGpuPrice(colabPricing.gpu_prices, gpu.name);
    if (!price) {
      return null;
    }
    total += price.price_usd_per_hour * gpu.count;
  }
  return total;
}

type VastBadgeStatus = "running" | "stopped" | "error" | "connecting" | "online" | "offline";

function getVastBadgeStatus(inst: VastInstance): VastBadgeStatus {
  const v = (inst.actual_status ?? "").toLowerCase();
  if (v.includes("running") || v.includes("active") || v.includes("online")) return "running";
  if (v.includes("stopped") || v.includes("exited")) return "stopped";
  if (v.includes("error") || v.includes("failed")) return "error";
  if (v.includes("offline")) return "offline";
  return "connecting";
}

// Host Card Component
function HostCard({
  host,
  onDelete,
  colabPricing,
  colabPricingLoading,
  displayCurrency,
  exchangeRates,
}: {
  host: Host;
  onDelete: () => void;
  colabPricing?: ColabPricingResult | null;
  colabPricingLoading?: boolean;
  displayCurrency: Currency;
  exchangeRates?: ExchangeRates;
}) {
  const { isOpen: isDeleteOpen, onOpen: onDeleteOpen, onClose: onDeleteClose } = useDisclosure();
  const navigate = useNavigate();
  const [copiedSsh, setCopiedSsh] = useState(false);
  
  const handleConfirmDelete = () => {
    onDelete();
    onDeleteClose();
  };
  
  const hostIcon = host.type === "vast" ? "vast" : host.type === "colab" ? "colab" : "host";
  const openDetails = () => {
    navigate({ to: "/hosts/$id", params: { id: host.id } });
  };
  const gpuCounts = getHostGpuCounts(host);
  const colabHourlyUsd =
    host.type === "colab" ? calculateColabHourlyUsd(gpuCounts, colabPricing ?? null) : null;
  const hasColabGpuInfo = host.type === "colab" && gpuCounts.length > 0;
  const hasColabPricing = !!colabPricing;
  const formatUsd = (value: number, decimals = 3) =>
    formatPriceWithRates(value, "USD", displayCurrency, exchangeRates, decimals);
  const sshAddress = host.ssh ? `${host.ssh.user}@${host.ssh.host}:${host.ssh.port}` : null;

  return (
    <>
      <Card
        as="div"
        isPressable
        disableAnimation
        disableRipple
        onPress={(event) => {
          if (event.target.closest("[data-host-card-action]")) {
            return;
          }
          openDetails();
        }}
        className="h-full border border-divider hover:border-primary/50 transition-colors data-[pressed=true]:scale-100"
      >
        <CardBody className="p-3 flex flex-col gap-2">
          {/* Header: Icon, Name, Status, Actions */}
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-start gap-2 min-w-0 flex-1">
              <AppIcon name={hostIcon} className="w-6 h-6 shrink-0 mt-0.5" alt={`${host.type} icon`} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <h3 className="font-semibold break-words">{host.name}</h3>
                  <StatusBadge status={host.status} size="sm" />
                </div>
              </div>
            </div>
            <div className="flex items-center gap-1 shrink-0" data-host-card-action>
              <Dropdown>
                <DropdownTrigger>
                  <Button isIconOnly size="sm" variant="light">
                    <IconEllipsis />
                  </Button>
                </DropdownTrigger>
                <DropdownMenu>
                  <DropdownItem key="test">Test Connection</DropdownItem>
                  <DropdownItem key="edit">Edit</DropdownItem>
                  <DropdownItem
                    key="delete"
                    className="text-danger"
                    color="danger"
                    onPress={onDeleteOpen}
                  >
                    Delete
                  </DropdownItem>
                </DropdownMenu>
              </Dropdown>
            </div>
          </div>

          {/* SSH address */}
          {sshAddress && (
            <div className="flex items-center gap-2">
              <p className="text-xs font-mono text-foreground/50 whitespace-nowrap overflow-hidden text-ellipsis select-text">
                {sshAddress}
              </p>
              <Button
                isIconOnly
                size="sm"
                variant="light"
                onPress={async () => {
                  await copyText(sshAddress);
                  setCopiedSsh(true);
                  setTimeout(() => setCopiedSsh(false), 1200);
                }}
              >
                {copiedSsh ? <IconCheck /> : <IconCopy />}
              </Button>
            </div>
          )}

          {/* GPU + pricing pills */}
          {(gpuCounts.length > 0 || host.type === "colab") && (
            <div className="flex flex-wrap gap-2">
              {gpuCounts.map((gpu) => (
                <Chip key={gpu.name} size="sm" variant="flat" color="default">
                  {gpu.count}x {getGpuShortName(gpu.name)}
                </Chip>
              ))}
              {host.type === "colab" && (
                <>
                  {colabPricingLoading ? (
                    <Chip size="sm" variant="flat" color="default">
                      <span className="flex items-center gap-1">
                        <Spinner size="sm" className="w-3 h-3" /> Loading...
                      </span>
                    </Chip>
                  ) : !hasColabGpuInfo ? (
                    <Chip size="sm" variant="flat" color="default">
                      GPU unknown
                    </Chip>
                  ) : colabHourlyUsd != null ? (
                    <Chip size="sm" variant="flat" color="warning">
                      {formatUsd(colabHourlyUsd) + "/hr"}
                    </Chip>
                  ) : hasColabPricing ? (
                    <Chip size="sm" variant="flat" color="default">
                      No matching GPU price
                    </Chip>
                  ) : (
                    <Chip size="sm" variant="flat" color="default">
                      Pricing unavailable
                    </Chip>
                  )}
                </>
              )}
            </div>
          )}

          {/* Spacer to push last seen to bottom */}
          <div className="flex-1" />

          {/* Last seen */}
          <p className="text-xs text-foreground/40">
            {host.last_seen_at
              ? `Last seen: ${new Date(host.last_seen_at).toLocaleDateString()}`
              : "Never seen"}
          </p>
        </CardBody>
      </Card>
    
      {/* Delete Confirmation Modal */}
      <Modal isOpen={isDeleteOpen} onClose={onDeleteClose}>
        <ModalContent>
          <ModalHeader>Delete Host</ModalHeader>
          <ModalBody>
            <p>Are you sure you want to delete host "{host.name}"? This action cannot be undone.</p>
          </ModalBody>
          <ModalFooter>
            <Button variant="flat" onPress={onDeleteClose}>
              Cancel
            </Button>
            <Button color="danger" onPress={handleConfirmDelete}>
              Delete
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </>
  );
}

function VastInstanceCard({
  inst,
  displayCurrency,
  exchangeRates,
  lastSeenAt,
  onOpenDetails,
  onStart,
  onStop,
  onLabel,
  onDestroy,
  isStarting,
  isStopping,
}: {
  inst: VastInstance;
  displayCurrency: Currency;
  exchangeRates?: ExchangeRates;
  lastSeenAt: string | null;
  onOpenDetails: () => void;
  onStart: () => void;
  onStop: () => void;
  onLabel: () => void;
  onDestroy: () => void;
  isStarting: boolean;
  isStopping: boolean;
}) {
  const [copiedSsh, setCopiedSsh] = useState(false);
  const name = inst.label?.trim() || `vast #${inst.id}`;
  const badgeStatus = getVastBadgeStatus(inst);
  const formatUsd = (value: number, decimals = 3) =>
    formatPriceWithRates(value, "USD", displayCurrency, exchangeRates, decimals);
  const storagePerHour = inst.storage_cost != null && inst.disk_space != null
    ? (inst.storage_cost / 720) * inst.disk_space
    : null;
  const uploadPerTb = inst.inet_up_cost != null ? inst.inet_up_cost * 1024 : null;
  const downloadPerTb = inst.inet_down_cost != null ? inst.inet_down_cost * 1024 : null;
  const gpuLabel = inst.gpu_name
    ? `${inst.num_gpus ?? 1}x ${getGpuShortName(inst.gpu_name)}`
    : null;
  const sshAddress = inst.ssh_host ? `root@${inst.ssh_host}:${inst.ssh_port ?? "-"}` : null;

  return (
    <Card
      isPressable
      disableAnimation
      disableRipple
      onPress={(event) => {
        if (event.target.closest("[data-vast-card-action]")) {
          return;
        }
        onOpenDetails();
      }}
      className="h-full w-full border border-divider hover:border-primary/50 transition-colors data-[pressed=true]:scale-100"
    >
      <CardBody className="p-3 flex flex-col gap-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-start gap-2 min-w-0 flex-1">
            <AppIcon name="vast" className="w-6 h-6 shrink-0 mt-0.5" alt="Vast.ai icon" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="font-semibold break-words">{name}</h3>
                <StatusBadge status={badgeStatus} size="sm" />
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1 shrink-0" data-vast-card-action>
            <Dropdown>
              <DropdownTrigger>
                <Button isIconOnly size="sm" variant="light">
                  <IconEllipsis />
                </Button>
              </DropdownTrigger>
              <DropdownMenu>
                <DropdownItem key="start" onPress={onStart} isDisabled={isStarting}>
                  Start
                </DropdownItem>
                <DropdownItem key="stop" onPress={onStop} isDisabled={isStopping}>
                  Stop
                </DropdownItem>
                <DropdownItem key="label" onPress={onLabel}>
                  Set Label
                </DropdownItem>
                <DropdownItem
                  key="destroy"
                  className="text-danger"
                  color="danger"
                  onPress={onDestroy}
                >
                  Destroy
                </DropdownItem>
              </DropdownMenu>
            </Dropdown>
          </div>
        </div>

        {sshAddress && (
          <div className="flex items-center gap-2">
            <p className="text-xs font-mono text-foreground/50 whitespace-nowrap overflow-hidden text-ellipsis select-text">
              {sshAddress}
            </p>
            <Button
              isIconOnly
              size="sm"
              variant="light"
              onPress={async () => {
                await copyText(sshAddress);
                setCopiedSsh(true);
                setTimeout(() => setCopiedSsh(false), 1200);
              }}
            >
              {copiedSsh ? <IconCheck /> : <IconCopy />}
            </Button>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {gpuLabel && (
            <Chip size="sm" variant="flat" color="default">
              {gpuLabel}
            </Chip>
          )}
          {inst.dph_total != null && (
            <Chip size="sm" variant="flat" color="warning">
              GPU {formatUsd(inst.dph_total) + "/hr"}
            </Chip>
          )}
          {storagePerHour != null && (
            <Chip size="sm" variant="flat" color="default">
              SSD {formatUsd(storagePerHour, 3)}/hr
            </Chip>
          )}
          {uploadPerTb != null && (
            <Chip size="sm" variant="flat" color="default">
              ↑ {formatUsd(uploadPerTb, 3)}/TB
            </Chip>
          )}
          {downloadPerTb != null && (
            <Chip size="sm" variant="flat" color="default">
              ↓ {formatUsd(downloadPerTb, 3)}/TB
            </Chip>
          )}
        </div>

        <div className="flex-1" />

        <p className="text-xs text-foreground/40">
          {lastSeenAt ? `Last seen: ${new Date(lastSeenAt).toLocaleDateString()}` : "Last seen: -"}
        </p>
      </CardBody>
    </Card>
  );
}

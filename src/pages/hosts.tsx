import {
  Card,
  CardBody,
  CardHeader,
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
  Select,
  SelectItem,
  Spinner,
  Switch,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableColumn,
  TableHeader,
  TableRow,
  Tabs,
  Textarea,
  useDisclosure,
} from "@nextui-org/react";
import { Button } from "../components/ui";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { motion, AnimatePresence } from "framer-motion";
import { useState, useEffect } from "react";
import {
  hostApi,
  useVastInstances,
  vastSearchOffers,
  vastCreateInstance,
  vastStartInstance,
  vastStopInstance,
  vastDestroyInstance,
  vastLabelInstance,
  getConfig,
  sshPublicKey,
} from "../lib/tauri-api";
import type { Host, HostConfig, HostType, VastInstance, VastOffer } from "../lib/types";
import { StatusBadge } from "../components/shared/StatusBadge";

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

function IconSearch() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
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
    await navigator.clipboard.writeText(code);
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
  const queryClient = useQueryClient();
  const addHostModal = useDisclosure();
  const rentModal = useDisclosure();
  const labelModal = useDisclosure();

  // Hosts query
  const hostsQuery = useQuery({
    queryKey: ["hosts"],
    queryFn: hostApi.list,
  });

  // Vast instances query
  const vastQuery = useVastInstances();

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

  // Vast search state
  const [offerGpuName, setOfferGpuName] = useState("");
  const [offerNumGpus, setOfferNumGpus] = useState("1");
  const [offerMaxDph, setOfferMaxDph] = useState("");
  const [offerMinRel, setOfferMinRel] = useState("");
  const [offerMinRam, setOfferMinRam] = useState("");
  const [offerLimit, setOfferLimit] = useState("30");
  const [offers, setOffers] = useState<VastOffer[]>([]);

  const searchMut = useMutation({
    mutationFn: () =>
      vastSearchOffers({
        gpu_name: offerGpuName.trim() || null,
        num_gpus: offerNumGpus.trim() ? Number(offerNumGpus) : null,
        min_gpu_ram: offerMinRam.trim() ? Number(offerMinRam) : null,
        max_dph_total: offerMaxDph.trim() ? Number(offerMaxDph) : null,
        min_reliability2: offerMinRel.trim() ? Number(offerMinRel) : null,
        limit: offerLimit.trim() ? Number(offerLimit) : 30,
        order: "dph_total",
        type: "on-demand",
      } as any),
    onSuccess: (rows) => setOffers(rows),
  });

  // Rent modal state
  const [rentDraft, setRentDraft] = useState<{
    offer: VastOffer;
    image: string;
    disk: string;
    label: string;
    direct: boolean;
    cancelUnavail: boolean;
    onstart: string;
  } | null>(null);

  const createMut = useMutation({
    mutationFn: (input: Parameters<typeof vastCreateInstance>[0]) => vastCreateInstance(input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["vastInstances"] });
      rentModal.onClose();
      addHostModal.onClose();
    },
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

  function handleAddHost() {
    if (!newHost.name) return;
    addHostMutation.mutate(newHost as HostConfig);
  }

  function importVastAsHost(inst: VastInstance) {
    setNewHost({
      name: inst.label ?? `vast-${inst.id}`,
      type: "vast",
      vast_instance_id: inst.id,
      ssh_host: inst.ssh_host ?? "",
      ssh_port: inst.ssh_port ?? 22,
      ssh_user: "root",
    });
    setAddHostTab("custom");
    addHostModal.onOpen();
  }

  function statusColor(s: string | null): "default" | "success" | "warning" | "danger" {
    const v = (s ?? "").toLowerCase();
    if (v.includes("running")) return "success";
    if (v.includes("stopped") || v.includes("offline")) return "warning";
    if (v.includes("error") || v.includes("failed")) return "danger";
    return "default";
  }

  const onlineHosts = hostsQuery.data?.filter((h) => h.status === "online").length ?? 0;
  const vastInstances = vastQuery.data ?? [];
  const runningVast = vastInstances.filter((i) => i.actual_status?.includes("running")).length;

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
              onPress={() => { setAddHostTab("vast"); addHostModal.onOpen(); }}
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
            <p className="text-foreground/60 text-sm py-4">No hosts saved yet. Add a host or import from Vast.ai.</p>
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
                    <HostCard host={host} onDelete={() => removeHostMutation.mutate(host.id)} />
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
            <Table removeWrapper aria-label="Vast instances">
              <TableHeader>
                <TableColumn>ID</TableColumn>
                <TableColumn>Status</TableColumn>
                <TableColumn>GPU</TableColumn>
                <TableColumn>$/hr</TableColumn>
                <TableColumn>SSH</TableColumn>
                <TableColumn>Label</TableColumn>
                <TableColumn>Actions</TableColumn>
              </TableHeader>
              <TableBody>
                {vastInstances.map((inst) => (
                  <TableRow key={inst.id}>
                    <TableCell className="font-mono text-xs">{inst.id}</TableCell>
                    <TableCell>
                      <Chip size="sm" color={statusColor(inst.actual_status)} variant="flat">
                        {inst.actual_status ?? "-"}
                      </Chip>
                    </TableCell>
                    <TableCell className="text-sm">
                      {inst.num_gpus}x {inst.gpu_name ?? "-"}
                    </TableCell>
                    <TableCell className="text-sm font-mono">
                      ${inst.dph_total?.toFixed(3) ?? "-"}
                    </TableCell>
                    <TableCell className="text-xs font-mono">
                      {inst.ssh_host ? `${inst.ssh_host}:${inst.ssh_port}` : "-"}
                    </TableCell>
                    <TableCell className="text-sm">{inst.label ?? "-"}</TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        <Button
                          size="sm"
                          variant="flat"
                          isLoading={vastStartMut.isPending && vastStartMut.variables === inst.id}
                          onPress={() => vastStartMut.mutate(inst.id)}
                        >
                          Start
                        </Button>
                        <Button
                          size="sm"
                          variant="flat"
                          isLoading={vastStopMut.isPending && vastStopMut.variables === inst.id}
                          onPress={() => vastStopMut.mutate(inst.id)}
                        >
                          Stop
                        </Button>
                        <Button
                          size="sm"
                          variant="flat"
                          onPress={() => importVastAsHost(inst)}
                        >
                          Import
                        </Button>
                        <Dropdown>
                          <DropdownTrigger>
                            <Button size="sm" variant="flat" isIconOnly>
                              <IconEllipsis />
                            </Button>
                          </DropdownTrigger>
                          <DropdownMenu>
                            <DropdownItem
                              key="label"
                              onPress={() => {
                                setLabelDraft({ id: inst.id, label: inst.label ?? "" });
                                labelModal.onOpen();
                              }}
                            >
                              Set Label
                            </DropdownItem>
                            <DropdownItem
                              key="destroy"
                              className="text-danger"
                              color="danger"
                              onPress={() => {
                                if (confirm(`Destroy instance ${inst.id}? This will stop billing.`)) {
                                  vastDestroyMut.mutate(inst.id);
                                }
                              }}
                            >
                              Destroy
                            </DropdownItem>
                          </DropdownMenu>
                        </Dropdown>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      </div>

      {/* Add Host Modal */}
      <Modal 
        isOpen={addHostModal.isOpen} 
        onOpenChange={(open) => {
          if (open) {
            addHostModal.onOpen();
          } else {
            addHostModal.onClose();
            // Reset state when modal closes
            setColabPubKey("");
            setColabPubKeyError("");
          }
        }} 
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
                      <Input
                        label="Host Name"
                        placeholder="my-training-server"
                        value={newHost.name ?? ""}
                        onValueChange={(v) => setNewHost({ ...newHost, name: v })}
                        isRequired
                      />
                      <Input
                        label="SSH Host"
                        placeholder="192.168.1.100 or hostname.example.com"
                        value={newHost.ssh_host ?? ""}
                        onValueChange={(v) => setNewHost({ ...newHost, ssh_host: v })}
                        isRequired
                      />
                      <div className="grid grid-cols-2 gap-4">
                        <Input
                          label="SSH Port"
                          type="number"
                          value={String(newHost.ssh_port ?? 22)}
                          onValueChange={(v) => setNewHost({ ...newHost, ssh_port: parseInt(v) || 22 })}
                        />
                        <Input
                          label="SSH User"
                          placeholder="root"
                          value={newHost.ssh_user ?? ""}
                          onValueChange={(v) => setNewHost({ ...newHost, ssh_user: v })}
                        />
                      </div>
                      <Input
                        label="SSH Key Path (optional)"
                        placeholder="~/.ssh/id_rsa"
                        value={newHost.ssh_key_path ?? ""}
                        onValueChange={(v) => setNewHost({ ...newHost, ssh_key_path: v || null })}
                      />
                    </div>
                  </Tab>

                  <Tab key="vast" title="Rent from Vast.ai">
                    <div className="space-y-4 pt-4">
                      <div className="flex items-center justify-between">
                        <p className="text-sm text-foreground/60">
                          Search for GPU instances on Vast.ai
                        </p>
                        <Button
                          color="primary"
                          size="sm"
                          startContent={<IconSearch />}
                          isLoading={searchMut.isPending}
                          onPress={() => searchMut.mutate()}
                        >
                          Search
                        </Button>
                      </div>

                      <div className="grid grid-cols-3 gap-3">
                        <Input
                          size="sm"
                          label="GPU Name"
                          placeholder="H100, 4090, A100"
                          value={offerGpuName}
                          onValueChange={setOfferGpuName}
                        />
                        <Input
                          size="sm"
                          label="# GPUs"
                          type="number"
                          value={offerNumGpus}
                          onValueChange={setOfferNumGpus}
                        />
                        <Input
                          size="sm"
                          label="Min VRAM (GB)"
                          type="number"
                          value={offerMinRam}
                          onValueChange={setOfferMinRam}
                        />
                      </div>
                      <div className="grid grid-cols-3 gap-3">
                        <Input
                          size="sm"
                          label="Max $/hr"
                          type="number"
                          value={offerMaxDph}
                          onValueChange={setOfferMaxDph}
                        />
                        <Input
                          size="sm"
                          label="Min Reliability"
                          type="number"
                          placeholder="0.95"
                          value={offerMinRel}
                          onValueChange={setOfferMinRel}
                        />
                        <Input
                          size="sm"
                          label="Limit"
                          type="number"
                          value={offerLimit}
                          onValueChange={setOfferLimit}
                        />
                      </div>

                      {searchMut.error && (
                        <p className="text-sm text-danger">
                          Search failed: {(searchMut.error as any)?.message ?? "Unknown error"}
                        </p>
                      )}

                      {offers.length > 0 && (
                        <div className="max-h-64 overflow-auto">
                          <Table removeWrapper aria-label="Vast offers" isCompact>
                            <TableHeader>
                              <TableColumn>GPU</TableColumn>
                              <TableColumn>VRAM</TableColumn>
                              <TableColumn>$/hr</TableColumn>
                              <TableColumn>Reliability</TableColumn>
                              <TableColumn>Action</TableColumn>
                            </TableHeader>
                            <TableBody>
                              {offers.map((o) => (
                                <TableRow key={o.id}>
                                  <TableCell className="text-sm">
                                    {o.num_gpus}x {o.gpu_name ?? "-"}
                                  </TableCell>
                                  <TableCell className="text-sm">{o.gpu_ram ? `${(o.gpu_ram / 1024).toFixed(0)} GB` : "-"}</TableCell>
                                  <TableCell className="text-sm font-mono">
                                    ${o.dph_total?.toFixed(3) ?? "-"}
                                  </TableCell>
                                  <TableCell className="text-sm">
                                    {o.reliability2?.toFixed(2) ?? "-"}
                                  </TableCell>
                                  <TableCell>
                                    <Button
                                      size="sm"
                                      color="primary"
                                      variant="flat"
                                      onPress={() => {
                                        setRentDraft({
                                          offer: o,
                                          image: "pytorch/pytorch:latest",
                                          disk: "40",
                                          label: "",
                                          direct: false,
                                          cancelUnavail: false,
                                          onstart: "",
                                        });
                                        rentModal.onOpen();
                                      }}
                                    >
                                      Rent
                                    </Button>
                                  </TableCell>
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                        </div>
                      )}
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
    time.sleep(0.5)`} />
                          
                          <p className="text-xs text-foreground/60">
                            After running, copy the hostname (e.g., <code className="bg-content3 px-1 rounded">xxxx-xxxx.trycloudflare.com</code>) and paste it below.
                          </p>
                        </CardBody>
                      </Card>

                      <Divider />

                      <Input
                        label="Host Name"
                        placeholder="my-colab"
                        value={newHost.name ?? ""}
                        onValueChange={(v) => setNewHost({ ...newHost, name: v, type: "colab" })}
                        isRequired
                      />
                      <Input
                        label="Cloudflared Hostname"
                        placeholder="xxxx-xxxx.trycloudflare.com"
                        value={newHost.cloudflared_hostname ?? ""}
                        onValueChange={(v) => setNewHost({ ...newHost, cloudflared_hostname: v })}
                        isRequired
                      />
                      <Input
                        label="SSH User"
                        placeholder="root"
                        value={newHost.ssh_user ?? "root"}
                        onValueChange={(v) => setNewHost({ ...newHost, ssh_user: v })}
                      />
                    </div>
                  </Tab>
                </Tabs>
              </ModalBody>
              <ModalFooter>
                <Button variant="flat" onPress={onClose}>
                  Cancel
                </Button>
                {addHostTab !== "vast" && (
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
                )}
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>

      {/* Rent Instance Modal */}
      <Modal isOpen={rentModal.isOpen} onOpenChange={(open) => open ? rentModal.onOpen() : rentModal.onClose()} isDismissable={true} size="2xl">
        <ModalContent>
          {(onClose) => (
            <>
              <ModalHeader>Rent Vast.ai Instance</ModalHeader>
              <ModalBody className="gap-4">
                <div className="text-sm text-foreground/60">
                  <span className="font-medium">Offer #{rentDraft?.offer.id}</span> ·{" "}
                  {rentDraft?.offer.num_gpus}x {rentDraft?.offer.gpu_name} ·{" "}
                  ${rentDraft?.offer.dph_total?.toFixed(3)}/hr
                </div>

                <Input
                  label="Docker Image"
                  value={rentDraft?.image ?? ""}
                  onValueChange={(v) => setRentDraft((p) => (p ? { ...p, image: v } : p))}
                  placeholder="pytorch/pytorch:latest"
                  isRequired
                />

                <div className="grid grid-cols-2 gap-4">
                  <Input
                    label="Disk (GB)"
                    type="number"
                    value={rentDraft?.disk ?? ""}
                    onValueChange={(v) => setRentDraft((p) => (p ? { ...p, disk: v } : p))}
                  />
                  <Input
                    label="Label"
                    value={rentDraft?.label ?? ""}
                    onValueChange={(v) => setRentDraft((p) => (p ? { ...p, label: v } : p))}
                    placeholder="my-training"
                  />
                </div>

                <div className="flex gap-6">
                  <Switch
                    size="sm"
                    isSelected={rentDraft?.direct ?? false}
                    onValueChange={(v) => setRentDraft((p) => (p ? { ...p, direct: v } : p))}
                  >
                    Direct SSH
                  </Switch>
                  <Switch
                    size="sm"
                    isSelected={rentDraft?.cancelUnavail ?? false}
                    onValueChange={(v) => setRentDraft((p) => (p ? { ...p, cancelUnavail: v } : p))}
                  >
                    Cancel if unavailable
                  </Switch>
                </div>

                <Textarea
                  label="Onstart Script"
                  value={rentDraft?.onstart ?? ""}
                  onValueChange={(v) => setRentDraft((p) => (p ? { ...p, onstart: v } : p))}
                  placeholder="apt-get update && pip install ..."
                  minRows={2}
                  classNames={{ input: "font-mono text-xs" }}
                />

                {createMut.error && (
                  <p className="text-sm text-danger">
                    Failed: {(createMut.error as any)?.message ?? "Unknown error"}
                  </p>
                )}
              </ModalBody>
              <ModalFooter>
                <Button variant="flat" onPress={onClose}>
                  Cancel
                </Button>
                <Button
                  color="primary"
                  isLoading={createMut.isPending}
                  onPress={async () => {
                    if (!rentDraft) return;
                    await createMut.mutateAsync({
                      offer_id: rentDraft.offer.id,
                      image: rentDraft.image,
                      disk: Number(rentDraft.disk) || 40,
                      label: rentDraft.label.trim() || null,
                      onstart: rentDraft.onstart.trim() || null,
                      direct: rentDraft.direct,
                      cancel_unavail: rentDraft.cancelUnavail,
                    });
                  }}
                >
                  Create Instance
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
                <Input
                  label="Label"
                  value={labelDraft?.label ?? ""}
                  onValueChange={(v) => setLabelDraft((p) => (p ? { ...p, label: v } : p))}
                  placeholder="my-training-job"
                />
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

// Host Card Component
function HostCard({ host, onDelete }: { host: Host; onDelete: () => void }) {
  const { isOpen: isDeleteOpen, onOpen: onDeleteOpen, onClose: onDeleteClose } = useDisclosure();
  
  const handleConfirmDelete = () => {
    onDelete();
    onDeleteClose();
  };
  
  const hostIcon = host.type === "vast" ? "🚀" : host.type === "colab" ? "🔬" : "🖥️";

  return (
    <>
      <Card className="h-full border border-divider hover:border-primary/50 transition-colors">
        <CardBody className="p-3 flex flex-col gap-2">
          {/* Header: Icon, Name, Status, Actions */}
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-start gap-2 min-w-0 flex-1">
              <span className="text-lg shrink-0 mt-0.5">{hostIcon}</span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <h3 className="font-semibold break-words">{host.name}</h3>
                  <StatusBadge status={host.status} size="sm" />
                </div>
              </div>
            </div>
            <div className="flex items-center gap-1 shrink-0">
              <Button
                as={Link}
                to={`/hosts/${host.id}`}
                size="sm"
                color="primary"
                variant="flat"
              >
                Details
              </Button>
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

          {/* GPU info */}
          {host.gpu_name && (
            <p className="text-xs text-foreground/60">
              <span className="text-foreground/40">GPU: </span>
              {host.num_gpus}x {host.gpu_name}
            </p>
          )}

          {/* SSH address - wrap on overflow */}
          {host.ssh && (
            <p className="text-xs font-mono text-foreground/50 break-all">
              {host.ssh.user}@{host.ssh.host}:{host.ssh.port}
            </p>
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

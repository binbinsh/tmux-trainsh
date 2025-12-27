import {
  Card,
  CardBody,
  CardHeader,
  Chip,
  Divider,
  Input,
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
  Switch,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableColumn,
  TableHeader,
  TableRow,
  Textarea,
  useDisclosure
} from "@nextui-org/react";
import { Button } from "../components/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  vastCreateInstance,
  vastDestroyInstance,
  vastLabelInstance,
  vastListInstances,
  vastSearchOffers,
  vastStartInstance,
  vastStopInstance
} from "../lib/tauri-api";
import type { VastInstance, VastOffer } from "../lib/types";

export function VastPage() {
  const qc = useQueryClient();
  const instQuery = useQuery({
    queryKey: ["vastInstances"],
    queryFn: vastListInstances,
    refetchInterval: 30_000,
    staleTime: 20_000,
    retry: 1,
  });

  const startMut = useMutation({
    mutationFn: (id: number) => vastStartInstance(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["vastInstances"] })
  });
  const stopMut = useMutation({
    mutationFn: (id: number) => vastStopInstance(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["vastInstances"] })
  });
  const destroyMut = useMutation({
    mutationFn: (id: number) => vastDestroyInstance(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["vastInstances"] })
  });
  const labelMut = useMutation({
    mutationFn: (vars: { id: number; label: string }) => vastLabelInstance(vars.id, vars.label),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["vastInstances"] })
  });

  const labelModal = useDisclosure();
  const [labelDraft, setLabelDraft] = useState<{ id: number; label: string } | null>(null);

  const [offerGpuName, setOfferGpuName] = useState<string>("");
  const [offerNumGpus, setOfferNumGpus] = useState<string>("1");
  const [offerMaxDph, setOfferMaxDph] = useState<string>("");
  const [offerMinRel, setOfferMinRel] = useState<string>("");
  const [offerMinRam, setOfferMinRam] = useState<string>("");
  const [offerLimit, setOfferLimit] = useState<string>("50");
  const [offers, setOffers] = useState<VastOffer[]>([]);

  const rentModal = useDisclosure();
  const [rentDraft, setRentDraft] = useState<{
    offer: VastOffer;
    image: string;
    disk: string;
    label: string;
    direct: boolean;
    cancelUnavail: boolean;
    onstart: string;
  } | null>(null);
  const [rentResult, setRentResult] = useState<string | null>(null);

  const searchMut = useMutation({
    mutationFn: () =>
      vastSearchOffers({
        gpu_name: offerGpuName.trim() ? offerGpuName.trim() : null,
        num_gpus: offerNumGpus.trim() ? Number(offerNumGpus.trim()) : null,
        min_gpu_ram: offerMinRam.trim() ? Number(offerMinRam.trim()) : null,
        max_dph_total: offerMaxDph.trim() ? Number(offerMaxDph.trim()) : null,
        min_reliability2: offerMinRel.trim() ? Number(offerMinRel.trim()) : null,
        limit: offerLimit.trim() ? Number(offerLimit.trim()) : null,
        order: "dph_total",
        type: "on-demand"
      } as any),
    onSuccess: (rows) => setOffers(rows)
  });

  const createMut = useMutation({
    mutationFn: (input: Parameters<typeof vastCreateInstance>[0]) => vastCreateInstance(input),
    onSuccess: async (id) => {
      setRentResult(`Created instance: ${id} (wait for it to become SSH-ready)`);
      await qc.invalidateQueries({ queryKey: ["vastInstances"] });
    }
  });

  const rows = useMemo(() => instQuery.data ?? [], [instQuery.data]);

  function statusColor(s: string | null): "default" | "success" | "warning" | "danger" {
    const v = (s ?? "").toLowerCase();
    if (!v) return "default";
    if (v.includes("running")) return "success";
    if (v.includes("stopped") || v.includes("offline")) return "warning";
    if (v.includes("error") || v.includes("failed")) return "danger";
    return "default";
  }

  function renderGpu(inst: VastInstance) {
    const n = inst.num_gpus ?? null;
    const name = inst.gpu_name ?? null;
    if (!n && !name) return <span className="text-foreground/60">-</span>;
    return (
      <div className="flex flex-col">
        <div className="text-sm">{name ?? "-"}</div>
        <div className="text-xs text-foreground/60">{n ? `${n} GPU` : ""}</div>
      </div>
    );
  }

  return (
    <div className="h-full p-6 overflow-auto">
      <div className="max-w-7xl mx-auto space-y-6">
      <Card>
        <CardHeader className="flex items-start justify-between gap-4">
          <div>
            <div className="text-lg font-semibold">Vast.ai Instances</div>
            <div className="text-sm text-foreground/70">列表每 10s 自动刷新；在 Settings 里配置 API Key / SSH Key。</div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="flat" isDisabled={instQuery.isFetching} onPress={() => instQuery.refetch()}>
              Refresh
            </Button>
          </div>
        </CardHeader>
        <Divider />
        <CardBody className="gap-4">
          {instQuery.isLoading ? (
            <div className="flex items-center gap-3 py-8">
              <Spinner size="sm" />
              <div className="text-sm text-foreground/70">Loading instances…</div>
            </div>
          ) : instQuery.error ? (
            <div className="text-sm text-danger">
              Failed to load instances: {(instQuery.error as any)?.message ?? "Unknown error"}
            </div>
          ) : (
            <Table removeWrapper aria-label="Vast instances table">
              <TableHeader>
                <TableColumn>ID</TableColumn>
                <TableColumn>Status</TableColumn>
                <TableColumn>GPU</TableColumn>
                <TableColumn>Util</TableColumn>
                <TableColumn>DPH</TableColumn>
                <TableColumn>SSH</TableColumn>
                <TableColumn>Label</TableColumn>
                <TableColumn>Actions</TableColumn>
              </TableHeader>
              <TableBody emptyContent="No instances">
                {rows.map((inst) => (
                  <TableRow key={inst.id}>
                    <TableCell className="font-mono text-xs">{inst.id}</TableCell>
                    <TableCell>
                      <Chip size="sm" color={statusColor(inst.actual_status)} variant="flat">
                        {inst.actual_status ?? "-"}
                      </Chip>
                    </TableCell>
                    <TableCell>{renderGpu(inst)}</TableCell>
                    <TableCell className="text-sm">{inst.gpu_util != null ? `${inst.gpu_util}%` : "-"}</TableCell>
                    <TableCell className="text-sm">{inst.dph_total != null ? inst.dph_total.toFixed(3) : "-"}</TableCell>
                    <TableCell className="text-xs font-mono">
                      {inst.ssh_host && inst.ssh_port ? `${inst.ssh_host}:${inst.ssh_port}` : "-"}
                    </TableCell>
                    <TableCell className="text-sm">{inst.label ?? "-"}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          variant="flat"
                          isLoading={startMut.isPending && startMut.variables === inst.id}
                          onPress={() => startMut.mutate(inst.id)}
                        >
                          Start
                        </Button>
                        <Button
                          size="sm"
                          variant="flat"
                          isLoading={stopMut.isPending && stopMut.variables === inst.id}
                          onPress={() => stopMut.mutate(inst.id)}
                        >
                          Stop
                        </Button>
                        <Button
                          size="sm"
                          variant="flat"
                          onPress={() => {
                            setLabelDraft({ id: inst.id, label: inst.label ?? "" });
                            labelModal.onOpen();
                          }}
                        >
                          Label
                        </Button>
                        <Button
                          size="sm"
                          color="danger"
                          variant="flat"
                          isLoading={destroyMut.isPending && destroyMut.variables === inst.id}
                          onPress={() => {
                            if (!confirm(`Destroy instance ${inst.id}? This will stop billing.`)) return;
                            destroyMut.mutate(inst.id);
                          }}
                        >
                          Destroy
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardBody>
      </Card>

      <Modal isOpen={labelModal.isOpen} onOpenChange={(open) => open ? labelModal.onOpen() : labelModal.onClose()} isDismissable={true}>
        <ModalContent>
          {(onClose) => (
            <>
              <ModalHeader>Set label</ModalHeader>
              <ModalBody>
                <Input
                  label="Label"
                  value={labelDraft?.label ?? ""}
                  onValueChange={(v) => setLabelDraft((prev) => (prev ? { ...prev, label: v } : prev))}
                  placeholder="e.g. llama-finetune-a100"
                />
              </ModalBody>
              <ModalFooter>
                <Button variant="flat" onPress={onClose}>
                  Cancel
                </Button>
                <Button
                  color="primary"
                  isLoading={labelMut.isPending}
                  onPress={async () => {
                    if (!labelDraft) return;
                    await labelMut.mutateAsync({ id: labelDraft.id, label: labelDraft.label });
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

      <Card>
        <CardHeader className="flex items-start justify-between gap-4">
          <div>
            <div className="text-lg font-semibold">Search offers & rent</div>
            <div className="text-sm text-foreground/70">
              使用 Vast 官方 API（同 vastai CLI）搜索可租用 offers，并从 offer_id 创建实例。
            </div>
          </div>
          <Button color="primary" isLoading={searchMut.isPending} onPress={() => searchMut.mutate()}>
            Search
          </Button>
        </CardHeader>
        <Divider />
        <CardBody className="gap-4">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <Input
              label="GPU name (optional)"
              value={offerGpuName}
              onValueChange={setOfferGpuName}
              placeholder="RTX_4090 / A100 / H100"
              description="用下划线代替空格（与 vastai 规则一致）。"
            />
            <Input label="#GPUs" value={offerNumGpus} onValueChange={setOfferNumGpus} placeholder="1" />
            <Input
              label="Min GPU RAM (GB)"
              value={offerMinRam}
              onValueChange={setOfferMinRam}
              placeholder="24"
            />
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <Input label="Max DPH (optional)" value={offerMaxDph} onValueChange={setOfferMaxDph} placeholder="0.5" />
            <Input
              label="Min reliability2 (optional)"
              value={offerMinRel}
              onValueChange={setOfferMinRel}
              placeholder="0.95"
            />
            <Input label="Limit" value={offerLimit} onValueChange={setOfferLimit} placeholder="50" />
          </div>

          {searchMut.error ? (
            <div className="text-sm text-danger">Search failed: {(searchMut.error as any)?.message ?? "Unknown error"}</div>
          ) : null}

          <Table removeWrapper aria-label="Vast offers table">
            <TableHeader>
              <TableColumn>Offer ID</TableColumn>
              <TableColumn>GPU</TableColumn>
              <TableColumn>RAM</TableColumn>
              <TableColumn>DPH</TableColumn>
              <TableColumn>Rel</TableColumn>
              <TableColumn>Net</TableColumn>
              <TableColumn>CPU</TableColumn>
              <TableColumn>Action</TableColumn>
            </TableHeader>
            <TableBody emptyContent="No offers">
              {offers.map((o) => (
                <TableRow key={o.id}>
                  <TableCell className="font-mono text-xs">{o.id}</TableCell>
                  <TableCell className="text-sm">
                    {o.gpu_name ?? "-"} {o.num_gpus ? `×${o.num_gpus}` : ""}
                  </TableCell>
                  <TableCell className="text-sm">{o.gpu_ram != null ? `${o.gpu_ram} GB` : "-"}</TableCell>
                  <TableCell className="text-sm">{o.dph_total != null ? o.dph_total.toFixed(3) : "-"}</TableCell>
                  <TableCell className="text-sm">{o.reliability2 != null ? o.reliability2.toFixed(3) : "-"}</TableCell>
                  <TableCell className="text-sm">
                    {o.inet_down != null ? `↓${o.inet_down}` : "-"} {o.inet_up != null ? `↑${o.inet_up}` : ""}
                  </TableCell>
                  <TableCell className="text-sm">
                    {o.cpu_cores != null ? `${o.cpu_cores}c` : "-"} {o.cpu_ram != null ? `${o.cpu_ram}GB` : ""}
                  </TableCell>
                  <TableCell>
                    <Button
                      size="sm"
                      color="primary"
                      variant="flat"
                      onPress={() => {
                        setRentResult(null);
                        setRentDraft({
                          offer: o,
                          image: "pytorch/pytorch:latest",
                          disk: "40",
                          label: "",
                          direct: false,
                          cancelUnavail: false,
                          onstart: ""
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

          {rentResult ? <div className="text-sm text-success">{rentResult}</div> : null}
        </CardBody>
      </Card>

      <Modal isOpen={rentModal.isOpen} onOpenChange={(open) => open ? rentModal.onOpen() : rentModal.onClose()} isDismissable={true} size="2xl">
        <ModalContent>
          {(onClose) => (
            <>
              <ModalHeader>Rent instance</ModalHeader>
              <ModalBody className="gap-3">
                <div className="text-sm text-foreground/70">
                  Offer: <span className="font-mono">{rentDraft?.offer.id}</span> ·{" "}
                  {rentDraft?.offer.gpu_name ?? "-"} {rentDraft?.offer.num_gpus ? `×${rentDraft?.offer.num_gpus}` : ""}
                </div>
                <Input
                  label="Docker image"
                  value={rentDraft?.image ?? ""}
                  onValueChange={(v) => setRentDraft((p) => (p ? { ...p, image: v } : p))}
                  placeholder="pytorch/pytorch:latest"
                  description="最少需要填写 image；创建后实例会以 SSH runtype 启动。"
                />
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  <Input
                    label="Disk (GB)"
                    value={rentDraft?.disk ?? ""}
                    onValueChange={(v) => setRentDraft((p) => (p ? { ...p, disk: v } : p))}
                    placeholder="40"
                  />
                  <Input
                    label="Label (optional)"
                    value={rentDraft?.label ?? ""}
                    onValueChange={(v) => setRentDraft((p) => (p ? { ...p, label: v } : p))}
                    placeholder="llama-finetune"
                  />
                </div>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  <Switch
                    isSelected={rentDraft?.direct ?? false}
                    onValueChange={(v) => setRentDraft((p) => (p ? { ...p, direct: v } : p))}
                  >
                    Direct SSH (ssh_direc)
                  </Switch>
                  <Switch
                    isSelected={rentDraft?.cancelUnavail ?? false}
                    onValueChange={(v) => setRentDraft((p) => (p ? { ...p, cancelUnavail: v } : p))}
                  >
                    Cancel if scheduling fails
                  </Switch>
                </div>
                <Textarea
                  label="Onstart (optional)"
                  value={rentDraft?.onstart ?? ""}
                  onValueChange={(v) => setRentDraft((p) => (p ? { ...p, onstart: v } : p))}
                  minRows={3}
                  classNames={{ input: "font-mono text-xs" }}
                  placeholder="echo hello; apt-get update; ..."
                />
                {createMut.error ? (
                  <div className="text-sm text-danger">
                    Create failed: {(createMut.error as any)?.message ?? "Unknown error"}
                  </div>
                ) : null}
              </ModalBody>
              <ModalFooter>
                <Button variant="flat" onPress={onClose} isDisabled={createMut.isPending}>
                  Cancel
                </Button>
                <Button
                  color="primary"
                  isLoading={createMut.isPending}
                  onPress={async () => {
                    if (!rentDraft) return;
                    const offerId = rentDraft.offer.id;
                    const disk = Number(rentDraft.disk);
                    await createMut.mutateAsync({
                      offer_id: offerId,
                      image: rentDraft.image,
                      disk,
                      label: rentDraft.label.trim() ? rentDraft.label.trim() : null,
                      onstart: rentDraft.onstart.trim() ? rentDraft.onstart.trim() : null,
                      direct: rentDraft.direct,
                      cancel_unavail: rentDraft.cancelUnavail
                    });
                    onClose();
                  }}
                >
                  Create
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



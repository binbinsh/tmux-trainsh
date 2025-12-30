import type { Host, HostStatus, VastInstance } from "./types";

function vastInstanceStatus(inst: VastInstance): HostStatus {
  const v = (inst.actual_status ?? "").toLowerCase();
  if (v.includes("running") || v.includes("active") || v.includes("online")) return "online";
  if (v.includes("stopped") || v.includes("exited") || v.includes("offline")) return "offline";
  if (v.includes("error") || v.includes("failed")) return "error";
  return "connecting";
}

function vastInstanceName(inst: VastInstance): string {
  const label = inst.label?.trim();
  if (label) return label;
  return `Vast #${inst.id}`;
}

export function vastInstanceToHostCandidate(inst: VastInstance): Host {
  return {
    id: `vast:${inst.id}`,
    name: vastInstanceName(inst),
    type: "vast",
    status: vastInstanceStatus(inst),
    ssh: null,
    vast_instance_id: inst.id,
    cloudflared_hostname: null,
    env_vars: {},
    gpu_name: inst.gpu_name ?? null,
    num_gpus: inst.num_gpus ?? null,
    system_info: null,
    created_at: new Date().toISOString(),
    last_seen_at: null,
  };
}


export type RecentConnection =
  | {
      id: "__local__";
      kind: "local";
      label: "Local";
      updated_at: string;
    }
  | {
      id: `host:${string}`;
      kind: "host";
      host_id: string;
      label: string;
      updated_at: string;
    }
  | {
      id: `vast:${number}`;
      kind: "vast";
      vast_instance_id: number;
      label: string;
      updated_at: string;
    };

type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;

const RECENTS_KEY = "doppio.recentConnections.v1";

function safeJsonParse<T>(raw: string | null): T | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function isIsoLike(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}T/.test(value);
}

export function loadRecentConnections(): RecentConnection[] {
  const parsed = safeJsonParse<unknown>(localStorage.getItem(RECENTS_KEY));
  if (!Array.isArray(parsed)) return [];

  const out: RecentConnection[] = [];
  for (const item of parsed) {
    if (!item || typeof item !== "object") continue;
    const v = item as Record<string, unknown>;
    const kind = v.kind;
    const id = v.id;
    const label = v.label;
    const updatedAt = v.updated_at;

    if (typeof kind !== "string") continue;
    if (typeof id !== "string" || !id.trim()) continue;
    if (typeof label !== "string" || !label.trim()) continue;
    if (typeof updatedAt !== "string" || !updatedAt.trim()) continue;

    const updated_at = isIsoLike(updatedAt) ? updatedAt : new Date().toISOString();

    if (kind === "local" && id === "__local__") {
      out.push({ id: "__local__", kind: "local", label: "Local", updated_at });
      continue;
    }

    if (kind === "host") {
      const hostId = v.host_id;
      if (typeof hostId !== "string" || !hostId.trim()) continue;
      out.push({
        id: `host:${hostId}`,
        kind: "host",
        host_id: hostId,
        label,
        updated_at,
      });
      continue;
    }

    if (kind === "vast") {
      const instanceId = v.vast_instance_id;
      if (typeof instanceId !== "number" || !Number.isFinite(instanceId)) continue;
      out.push({
        id: `vast:${instanceId}`,
        kind: "vast",
        vast_instance_id: instanceId,
        label,
        updated_at,
      });
      continue;
    }
  }

  out.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  return out;
}

export function saveRecentConnections(recents: RecentConnection[]) {
  localStorage.setItem(RECENTS_KEY, JSON.stringify(recents));
}

export function upsertRecentConnection(
  recents: RecentConnection[],
  next: DistributiveOmit<RecentConnection, "updated_at"> & { updated_at?: string },
  max = 12
): RecentConnection[] {
  const updated_at = next.updated_at ?? new Date().toISOString();
  const entry: RecentConnection = { ...(next as RecentConnection), updated_at };

  const merged = [entry, ...recents.filter((r) => r.id !== entry.id)];
  merged.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  return merged.slice(0, Math.max(1, max));
}

export function removeRecentConnection(recents: RecentConnection[], id: string): RecentConnection[] {
  return recents.filter((r) => r.id !== id);
}

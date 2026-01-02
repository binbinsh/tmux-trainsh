type TerminalStateCacheEntry = {
  snapshotVt: string;
  updatedAt: number;
};

const cache = new Map<string, TerminalStateCacheEntry>();

const MAX_ENTRIES = 12;

export function getTerminalSnapshot(id: string): string | null {
  return cache.get(id)?.snapshotVt ?? null;
}

export function setTerminalSnapshot(id: string, snapshotVt: string): void {
  const trimmed = snapshotVt.trim();
  if (!trimmed) return;

  cache.set(id, { snapshotVt, updatedAt: Date.now() });

  if (cache.size <= MAX_ENTRIES) return;
  const entries = [...cache.entries()].sort((a, b) => a[1].updatedAt - b[1].updatedAt);
  for (const [key] of entries.slice(0, Math.max(0, entries.length - MAX_ENTRIES))) {
    cache.delete(key);
  }
}

export function clearTerminalSnapshot(id: string): void {
  cache.delete(id);
}


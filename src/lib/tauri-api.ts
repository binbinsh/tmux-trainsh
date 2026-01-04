import { invoke } from "@tauri-apps/api/core";
import { getVersion as tauriGetVersion } from "@tauri-apps/api/app";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type {
  Currency,
  ColabGpuPricing,
  ColabPricingResult,
  ColabSubscription,
  ExchangeRates,
  FileEntry,
  GpuCapability,
  GpuRow,
  Host,
  HostConfig,
  HostCostBreakdown,
  HostPricing,
  ScamalyticsInfo,
  InteractiveExecution,
  InteractiveSkillEvent,
  SkillLogAppendedEvent,
  LogEntry,
  LogSnapshot,
  LogStreamStatus,
  PricingSettings,
  PricingSource,
  SkillRunLogChunk,
  Skill,
  SkillSummary,
  RemoteJobMeta,
  Session,
  SessionConfig,
  SessionMetrics,
  SshSpec,
  Storage,
  StorageCreateInput,
  StorageTestResult,
  StorageUpdateInput,
  StorageUsage,
  R2PurgeDeleteResult,
  SystemInfo,
  SyncProgress,
  TrainshConfig,
  TransferCreateInput,
  TransferProgress,
  TransferTask,
  UnifiedTransferInput,
  ValidationResult,
  VastInstance,
  VastOffer,
  VastPricingRates,
} from "./types";
import {
  loadSkillFolderAssignments,
  renameSkillPathInAssignments,
  saveSkillFolderAssignments,
} from "./skill-folders";

// ============================================================
// Error Handling
// ============================================================

export type AppError = {
  code: string;
  message: string;
};

function normalizeInvokeError(err: unknown): AppError {
  if (typeof err === "string") {
    try {
      const parsed = JSON.parse(err) as unknown;
      if (
        typeof parsed === "object" &&
        parsed !== null &&
        "code" in parsed &&
        "message" in parsed &&
        typeof (parsed as AppError).code === "string" &&
        typeof (parsed as AppError).message === "string"
      ) {
        return parsed as AppError;
      }
    } catch {
      // ignore
    }
    return { code: "unknown", message: err };
  }
  if (typeof err === "object" && err !== null) {
    const anyErr = err as Record<string, unknown>;
    if (typeof anyErr.code === "string" && typeof anyErr.message === "string") {
      return { code: anyErr.code, message: anyErr.message };
    }
    if (typeof anyErr.message === "string") {
      return { code: "unknown", message: anyErr.message };
    }
  }
  return { code: "unknown", message: "Unknown error" };
}

async function safeInvoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  try {
    return await invoke<T>(cmd, args);
  } catch (err) {
    throw normalizeInvokeError(err);
  }
}

// ============================================================
// App Info API
// ============================================================

export async function getAppVersion(): Promise<string> {
  return tauriGetVersion();
}

// ============================================================
// Config API
// ============================================================

export async function getConfig(): Promise<TrainshConfig> {
  return await invoke("get_config");
}

export async function saveConfig(cfg: TrainshConfig): Promise<void> {
  await invoke("save_config", { cfg });
}

// ============================================================
// File Listing API (for FilePicker)
// ============================================================

export async function listLocalFiles(path: string): Promise<FileEntry[]> {
  return await safeInvoke<FileEntry[]>("list_local_files", { path });
}

export async function listHostFiles(hostId: string, path: string): Promise<FileEntry[]> {
  return await safeInvoke<FileEntry[]>("list_host_files", { hostId, path });
}

export async function listVastFiles(instanceId: number, path: string): Promise<FileEntry[]> {
  return await safeInvoke<FileEntry[]>("list_vast_files", { instanceId, path });
}

export async function createLocalDir(path: string): Promise<void> {
  await safeInvoke("create_local_dir", { path });
}

export async function createHostDir(hostId: string, path: string): Promise<void> {
  await safeInvoke("create_host_dir", { hostId, path });
}

export async function deleteLocalFile(path: string): Promise<void> {
  await safeInvoke("delete_local_file", { path });
}

export async function deleteHostFile(hostId: string, path: string): Promise<void> {
  await safeInvoke("delete_host_file", { hostId, path });
}

export async function deleteVastFile(instanceId: number, path: string): Promise<void> {
  await safeInvoke("delete_vast_file", { instanceId, path });
}

// ============================================================
// External Editor API
// ============================================================

export async function openInExternalEditor(content: string, fileExtension?: string): Promise<string> {
  return await invoke("open_in_external_editor", { content, fileExtension: fileExtension ?? null });
}

// ============================================================
// SSH Keys API
// ============================================================

export async function sshKeyCandidates(): Promise<string[]> {
  return await invoke("ssh_key_candidates");
}

export async function sshSecretKeyCandidates(): Promise<string[]> {
  return await invoke("ssh_secret_key_candidates");
}

export async function sshPublicKey(privateKeyPath: string): Promise<string> {
  return await invoke("ssh_public_key", { privateKeyPath });
}

export async function sshPrivateKey(privateKeyPath: string): Promise<string> {
  return await invoke("ssh_private_key", { privateKeyPath });
}

export type SshKeyInfo = {
  private_key_path: string;
  public_key_path: string;
  public_key: string;
};

export async function sshGenerateKey(params: { path: string; comment?: string | null }): Promise<SshKeyInfo> {
  return await invoke("ssh_generate_key", { path: params.path, comment: params.comment ?? null });
}

export async function sshCheck(ssh: SshSpec): Promise<void> {
  const payload = {
    host: ssh.host,
    port: ssh.port,
    user: ssh.user,
    keyPath: ssh.keyPath ?? ssh.key_path ?? null,
    extraArgs: ssh.extraArgs ?? ssh.extra_args ?? [],
  };
  await safeInvoke("ssh_check", { ssh: payload });
}

// ============================================================
// Host API
// ============================================================

// Remote tmux session info (from host)
export type RemoteTmuxSession = {
  name: string;
  windows: number;
  attached: boolean;
  created_at: string | null;
};

export const hostApi = {
  list: async (): Promise<Host[]> => {
    return await safeInvoke<Host[]>("host_list");
  },

  get: async (id: string): Promise<Host> => {
    return await safeInvoke<Host>("host_get", { id });
  },

  add: async (config: HostConfig): Promise<Host> => {
    return await safeInvoke<Host>("host_add", { config });
  },

  update: async (id: string, config: Partial<HostConfig>): Promise<Host> => {
    return await safeInvoke<Host>("host_update", { id, config });
  },

  remove: async (id: string): Promise<void> => {
    await safeInvoke("host_remove", { id });
  },

  testConnection: async (id: string): Promise<{ success: boolean; message: string }> => {
    return await safeInvoke("host_test_connection", { id });
  },

  refresh: async (id: string): Promise<Host> => {
    return await safeInvoke<Host>("host_refresh", { id });
  },

  /** List tmux sessions running on the remote host */
  listTmuxSessions: async (id: string): Promise<RemoteTmuxSession[]> => {
    return await safeInvoke<RemoteTmuxSession[]>("host_list_tmux_sessions", { id });
  },

  /** List tmux sessions using SSH spec directly (without host ID) */
  listTmuxSessionsBySsh: async (ssh: {
    host: string;
    port: number;
    user: string;
    keyPath: string | null;
    extraArgs: string[];
  }): Promise<RemoteTmuxSession[]> => {
    return await safeInvoke<RemoteTmuxSession[]>("host_list_tmux_sessions_by_ssh", { ssh });
  },

  scamalyticsInfoForHost: async (hostId: string): Promise<ScamalyticsInfo> => {
    return await safeInvoke<ScamalyticsInfo>("host_scamalytics_info", { hostId });
  },

  scamalyticsInfoForIp: async (ip: string): Promise<ScamalyticsInfo> => {
    return await safeInvoke<ScamalyticsInfo>("host_scamalytics_info_for_ip", { ip });
  },
};

// ============================================================
// Session API
// ============================================================

export const sessionApi = {
  list: async (): Promise<Session[]> => {
    return await safeInvoke<Session[]>("session_list");
  },

  get: async (id: string): Promise<Session> => {
    return await safeInvoke<Session>("session_get", { id });
  },

  create: async (config: SessionConfig): Promise<Session> => {
    return await safeInvoke<Session>("session_create", { config });
  },

  delete: async (id: string): Promise<void> => {
    await safeInvoke("session_delete", { id });
  },

  sync: async (id: string): Promise<void> => {
    await safeInvoke("session_sync", { id });
  },

  run: async (id: string): Promise<void> => {
    await safeInvoke("session_run", { id });
  },

  stop: async (id: string): Promise<void> => {
    await safeInvoke("session_stop", { id });
  },

  download: async (id: string, localDir: string): Promise<void> => {
    await safeInvoke("session_download", { id, localDir });
  },

  getMetrics: async (id: string): Promise<SessionMetrics> => {
    return await safeInvoke<SessionMetrics>("session_get_metrics", { id });
  },

  getLogs: async (id: string, lines?: number): Promise<string[]> => {
    return await safeInvoke<string[]>("session_get_logs", { id, lines: lines ?? 200 });
  },
};

// ============================================================
// Vast.ai API
// ============================================================

export async function vastListInstances(): Promise<VastInstance[]> {
  return await invoke("vast_list_instances");
}

export async function vastGetInstance(instanceId: number): Promise<VastInstance> {
  return await invoke("vast_get_instance", { instanceId });
}

export async function vastAttachSshKey(instanceId: number, privateKeyPath?: string | null): Promise<string> {
  return await safeInvoke<string>("vast_attach_ssh_key", { instanceId, privateKeyPath: privateKeyPath ?? null });
}

export async function vastTestConnection(instanceId: number): Promise<{ success: boolean; message: string }> {
  return await safeInvoke("vast_test_connection", { instanceId });
}

export async function vastFetchSystemInfo(instanceId: number): Promise<SystemInfo> {
  return await safeInvoke<SystemInfo>("vast_fetch_system_info", { instanceId });
}

export async function vastStartInstance(instanceId: number): Promise<VastInstance> {
  return await invoke("vast_start_instance", { instanceId });
}

export async function vastStopInstance(instanceId: number): Promise<VastInstance> {
  return await invoke("vast_stop_instance", { instanceId });
}

export async function vastLabelInstance(instanceId: number, label: string): Promise<VastInstance> {
  return await invoke("vast_label_instance", { instanceId, label });
}

export async function vastDestroyInstance(instanceId: number): Promise<void> {
  await invoke("vast_destroy_instance", { instanceId });
}

export type VastSearchOffersInput = {
  gpu_name?: string | null;
  num_gpus?: number | null;
  min_gpu_ram?: number | null;
  max_dph_total?: number | null;
  min_reliability2?: number | null;
  limit?: number | null;
  order?: string | null;
  type?: string | null; // on-demand | bid | reserved
};

export async function vastSearchOffers(input: VastSearchOffersInput): Promise<VastOffer[]> {
  return await invoke("vast_search_offers", { input });
}

export type VastCreateInstanceInput = {
  offer_id: number;
  image: string;
  disk: number;
  label?: string | null;
  onstart?: string | null;
  direct?: boolean | null;
  cancel_unavail?: boolean | null;
};

export async function vastCreateInstance(input: VastCreateInstanceInput): Promise<number> {
  return await invoke("vast_create_instance", { input });
}

export async function gpuLookupCapability(name: string): Promise<GpuCapability | null> {
  return await safeInvoke<GpuCapability | null>("gpu_lookup_capability", { name });
}

// ============================================================
// Job API (Legacy - for backward compatibility)
// ============================================================

export type RunVastJobInput = {
  project_dir: string;
  command: string;
  instance_id: number;
  workdir?: string | null;
  remote_output_dir?: string | null;
  hf_home?: string | null;
  sync?: boolean | null;
  include_data?: boolean | null;
  include_models?: boolean | null;
  include_dotenv?: boolean | null;
  extra_excludes?: string | null;
  delete_remote?: boolean | null;
};

export async function vastRunJob(input: RunVastJobInput): Promise<RemoteJobMeta> {
  try {
    return await invoke("vast_run_job", { input });
  } catch (err) {
    throw normalizeInvokeError(err);
  }
}

export async function jobTailLogs(params: {
  ssh: SshSpec;
  logPath: string;
  lines?: number;
}): Promise<string[]> {
  return await invoke("job_tail_logs", { ssh: params.ssh, logPath: params.logPath, lines: params.lines ?? 200 });
}

export async function jobFetchGpu(params: { ssh: SshSpec }): Promise<GpuRow[]> {
  return await invoke("job_fetch_gpu", params);
}

export async function jobGetExitCode(params: {
  ssh: SshSpec;
  jobDir: string;
}): Promise<number | null> {
  return await invoke("job_get_exit_code", { ssh: params.ssh, jobDir: params.jobDir });
}

export async function jobListLocal(): Promise<RemoteJobMeta[]> {
  return await invoke("job_list_local");
}

export async function downloadRemoteDir(params: {
  ssh: SshSpec;
  remoteDir: string;
  localDir: string;
  delete?: boolean;
}): Promise<void> {
  await invoke("download_remote_dir", { 
    ssh: params.ssh, 
    remoteDir: params.remoteDir, 
    localDir: params.localDir, 
    delete: params.delete ?? false 
  });
}

// ============================================================
// Terminal API
// ============================================================

export type TermSessionInfo = {
  id: string;
  title: string;
};

export type TermHistoryInfo = {
  sizeBytes: number;
};

export type TermHistoryChunk = {
  offset: number;
  data: string;
  eof: boolean;
};

export type TermHistoryStep = {
  stepId: string;
  stepIndex: number;
  startOffset: number;
  endOffset: number;
  startedAt: number;
  endedAt: number;
  status: string;
  exitCode?: number | null;
};

export async function termList(): Promise<TermSessionInfo[]> {
  return await invoke("term_list");
}

export async function termOpenSshTmux(params: {
  ssh: SshSpec;
  tmuxSession: string;
  title?: string | null;
  cols?: number | null;
  rows?: number | null;
  envVars?: Record<string, string> | null;
}): Promise<TermSessionInfo> {
  // Use camelCase names (with fallback to snake_case for compatibility)
  const ssh = {
    host: params.ssh.host,
    port: params.ssh.port,
    user: params.ssh.user,
    keyPath: params.ssh.keyPath ?? params.ssh.key_path ?? null,
    extraArgs: params.ssh.extraArgs ?? params.ssh.extra_args ?? [],
  };
  return await invoke("term_open_ssh_tmux", {
    ssh,
    tmuxSession: params.tmuxSession,
    title: params.title ?? null,
    cols: params.cols ?? null,
    rows: params.rows ?? null,
    envVars: params.envVars ?? null,
  });
}

export async function termOpenInstanceTmux(params: {
  instanceId: number;
  tmuxSession: string;
  title?: string | null;
  cols?: number | null;
  rows?: number | null;
}): Promise<TermSessionInfo> {
  return await invoke("term_open_instance_tmux", {
    input: {
      instanceId: params.instanceId,
      tmuxSession: params.tmuxSession,
      title: params.title ?? null,
      cols: params.cols ?? null,
      rows: params.rows ?? null,
    },
  });
}

export async function termOpenLocal(params?: {
  title?: string | null;
  cols?: number | null;
  rows?: number | null;
}): Promise<TermSessionInfo> {
  return await invoke("term_open_local", {
    title: params?.title ?? null,
    cols: params?.cols ?? null,
    rows: params?.rows ?? null,
  });
}

export async function termWrite(id: string, data: string): Promise<void> {
  await invoke("term_write", { id, data });
}

export async function termResize(id: string, cols: number, rows: number): Promise<void> {
  await invoke("term_resize", { id, cols, rows });
}

export async function termClose(id: string): Promise<void> {
  await invoke("term_close", { id });
}

export async function termHistoryInfo(id: string): Promise<TermHistoryInfo> {
  return await invoke("term_history_info", { id });
}

export async function termHistoryRange(params: {
  id: string;
  offset: number;
  limit: number;
}): Promise<TermHistoryChunk> {
  return await invoke("term_history_range", {
    id: params.id,
    offset: params.offset,
    limit: params.limit,
  });
}

export async function termHistoryTail(params: {
  id: string;
  limit: number;
}): Promise<TermHistoryChunk> {
  return await invoke("term_history_tail", {
    id: params.id,
    limit: params.limit,
  });
}

export async function termHistorySteps(id: string): Promise<TermHistoryStep[]> {
  return await invoke("term_history_steps", { id });
}

/**
 * Open SSH connection in native system terminal (iTerm2/Terminal.app on macOS)
 * This is the simplest way to get a full-featured terminal for debugging
 */
export async function termOpenNativeSsh(
  ssh: SshSpec,
  tmuxSession?: string
): Promise<void> {
  await invoke("term_open_native_ssh", {
    ssh,
    tmuxSession: tmuxSession ?? null,
  });
}

/**
 * Quick open SSH in native terminal by host ID
 * Easiest way to SSH into a host for debugging
 */
export async function termOpenHost(
  hostId: string,
  tmuxSession?: string
): Promise<void> {
  await invoke("term_open_host", {
    hostId,
    tmuxSession: tmuxSession ?? null,
  });
}

// ============================================================
// Sync Progress Events
// ============================================================

/**
 * Listen for sync progress events for a specific session
 */
export async function listenSyncProgress(
  sessionId: string,
  callback: (progress: SyncProgress) => void
): Promise<UnlistenFn> {
  return await listen<SyncProgress>(`sync-progress-${sessionId}`, (event) => {
    callback(event.payload);
  });
}

/**
 * Listen for all sync progress events
 */
export async function listenAllSyncProgress(
  callback: (progress: SyncProgress) => void
): Promise<UnlistenFn> {
  return await listen<SyncProgress>("sync-progress", (event) => {
    callback(event.payload);
  });
}

// ============================================================
// TanStack Query Hooks (to be used in components)
// ============================================================

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

export function useHosts() {
  return useQuery({
    queryKey: ["hosts"],
    queryFn: hostApi.list,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

export function useHost(id: string) {
  return useQuery({
    queryKey: ["hosts", id],
    queryFn: () => hostApi.get(id),
    enabled: !!id,
  });
}

export function useSessions() {
  return useQuery({
    queryKey: ["sessions"],
    queryFn: sessionApi.list,
    refetchInterval: 5_000,
  });
}

export function useSession(id: string) {
  return useQuery({
    queryKey: ["sessions", id],
    queryFn: () => sessionApi.get(id),
    enabled: !!id,
  });
}

export function useSessionMetrics(id: string, enabled = true) {
  return useQuery({
    queryKey: ["sessions", id, "metrics"],
    queryFn: () => sessionApi.getMetrics(id),
    enabled: enabled && !!id,
    refetchInterval: 2_000,
  });
}

export function useSessionLogs(id: string, enabled = true) {
  return useQuery({
    queryKey: ["sessions", id, "logs"],
    queryFn: () => sessionApi.getLogs(id),
    enabled: enabled && !!id,
    refetchInterval: 2_000,
  });
}

export function useCreateSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: sessionApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}

export function useAddHost() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: hostApi.add,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["hosts"] });
    },
  });
}

export function useVastInstances() {
  return useQuery({
    queryKey: ["vastInstances"],
    queryFn: vastListInstances,
    refetchInterval: 30_000, // 30 seconds - less aggressive
    staleTime: 20_000, // Consider data stale after 20 seconds
    retry: 1, // Only retry once on failure
  });
}

// ============================================================
// Data Directory API
// ============================================================

/** Get the unified data directory path */
export async function getDataDir(): Promise<string> {
  return await safeInvoke("get_data_dir");
}

// ============================================================
// Log API (tmux capture-pane based)
// ============================================================

export const logApi = {
  /** Start streaming logs for a session (polls tmux capture-pane) */
  startStream: async (
    sessionId: string,
    tmuxSession: string,
    pollIntervalMs?: number
  ): Promise<void> =>
    await safeInvoke("log_start_stream", {
      sessionId,
      tmuxSession,
      pollIntervalMs,
    }),

  /** Stop streaming logs for a session */
  stopStream: async (sessionId: string): Promise<void> =>
    await safeInvoke("log_stop_stream", { sessionId }),

  /** Get current stream status */
  streamStatus: async (sessionId: string): Promise<LogStreamStatus> =>
    await safeInvoke("log_stream_status", { sessionId }),

  /** Capture logs from tmux pane right now (one-time) */
  captureNow: async (
    sessionId: string,
    tmuxSession: string,
    tailLines?: number
  ): Promise<LogSnapshot> =>
    await safeInvoke("log_capture_now", { sessionId, tmuxSession, tailLines }),

  /** Read locally stored logs */
  readLocal: async (sessionId: string): Promise<string[]> =>
    await safeInvoke("log_read_local", { sessionId }),

  /** Clear locally stored logs */
  clearLocal: async (sessionId: string): Promise<void> =>
    await safeInvoke("log_clear_local", { sessionId }),
};

/** Listen to log stream for a specific session */
export async function listenSessionLogs(
  sessionId: string,
  handler: (entry: LogEntry) => void
): Promise<UnlistenFn> {
  return await listen<LogEntry>(`session-log-${sessionId}`, (event) => {
    handler(event.payload);
  });
}

/** Listen to all session logs */
export async function listenAllSessionLogs(
  handler: (entry: LogEntry) => void
): Promise<UnlistenFn> {
  return await listen<LogEntry>("session-log", (event) => {
    handler(event.payload);
  });
}

/** React hook for streaming logs */
export function useLogStream(sessionId: string, tmuxSession: string | null) {
  return useQuery({
    queryKey: ["logs", sessionId, "status"],
    queryFn: () => logApi.streamStatus(sessionId),
    enabled: !!sessionId && !!tmuxSession,
    refetchInterval: 2_000,
  });
}

/** React hook for one-time log capture */
export function useLogCapture(sessionId: string, tmuxSession: string | null) {
  return useQuery({
    queryKey: ["logs", sessionId, "capture"],
    queryFn: () => logApi.captureNow(sessionId, tmuxSession!, 500),
    enabled: !!sessionId && !!tmuxSession,
    refetchInterval: 3_000,
  });
}

// ============================================================
// Storage API
// ============================================================

export const storageApi = {
  list: async (): Promise<Storage[]> => {
    return await safeInvoke<Storage[]>("storage_list");
  },

  get: async (id: string): Promise<Storage> => {
    return await safeInvoke<Storage>("storage_get", { id });
  },

  create: async (config: StorageCreateInput): Promise<Storage> => {
    return await safeInvoke<Storage>("storage_create", { config });
  },

  update: async (id: string, config: StorageUpdateInput): Promise<Storage> => {
    return await safeInvoke<Storage>("storage_update", { id, config });
  },

  delete: async (id: string): Promise<void> => {
    await safeInvoke("storage_delete", { id });
  },

  test: async (id: string): Promise<StorageTestResult> => {
    return await safeInvoke<StorageTestResult>("storage_test", { id });
  },

  listFiles: async (storageId: string, path: string): Promise<FileEntry[]> => {
    return await safeInvoke<FileEntry[]>("storage_list_files", {
      storageId,
      path,
    });
  },

  mkdir: async (storageId: string, path: string): Promise<void> => {
    await safeInvoke("storage_mkdir", { storageId, path });
  },

  deleteFile: async (storageId: string, path: string): Promise<void> => {
    await safeInvoke("storage_delete_file", { storageId, path });
  },

  getUsage: async (storageId: string): Promise<StorageUsage> => {
    return await safeInvoke<StorageUsage>("storage_get_usage", { storageId });
  },

  getR2Usages: async (): Promise<StorageUsage[]> => {
    return await safeInvoke<StorageUsage[]>("storage_get_r2_usages");
  },

  r2PurgeAndDeleteBucket: async (
    storageId: string,
    cloudflareApiToken: string | null | undefined,
    deleteLocalStorage: boolean
  ): Promise<R2PurgeDeleteResult> => {
    return await safeInvoke<R2PurgeDeleteResult>("storage_r2_purge_and_delete_bucket", {
      storageId,
      cloudflareApiToken,
      deleteLocalStorage,
    });
  },
};

// ============================================================
// Transfer API
// ============================================================

export const transferApi = {
  list: async (): Promise<TransferTask[]> => {
    return await safeInvoke<TransferTask[]>("transfer_list");
  },

  get: async (id: string): Promise<TransferTask> => {
    return await safeInvoke<TransferTask>("transfer_get", { id });
  },

  create: async (input: TransferCreateInput): Promise<TransferTask[]> => {
    return await safeInvoke<TransferTask[]>("transfer_create", { input });
  },

  /** Create a unified transfer supporting any endpoint type (storage, host, local) */
  createUnified: async (input: UnifiedTransferInput): Promise<TransferTask[]> => {
    return await safeInvoke<TransferTask[]>("transfer_create_unified", { input });
  },

  cancel: async (id: string): Promise<void> => {
    await safeInvoke("transfer_cancel", { id });
  },

  clearCompleted: async (): Promise<void> => {
    await safeInvoke("transfer_clear_completed");
  },
};

/**
 * Listen for transfer progress events for a specific task
 */
export async function listenTransferProgress(
  taskId: string,
  callback: (progress: TransferProgress) => void
): Promise<UnlistenFn> {
  return await listen<TransferProgress>(`transfer-progress-${taskId}`, (event) => {
    callback(event.payload);
  });
}

/**
 * Listen for all transfer progress events
 */
export async function listenAllTransferProgress(
  callback: (data: { task_id: string; progress: TransferProgress }) => void
): Promise<UnlistenFn> {
  return await listen<{ task_id: string; progress: TransferProgress }>(
    "transfer-progress",
    (event) => {
      callback(event.payload);
    }
  );
}

// ============================================================
// Storage & Transfer Hooks
// ============================================================

export function useStorages() {
  return useQuery({
    queryKey: ["storages"],
    queryFn: storageApi.list,
    staleTime: 30_000,
  });
}

export function useStorage(id: string) {
  return useQuery({
    queryKey: ["storages", id],
    queryFn: () => storageApi.get(id),
    enabled: !!id,
  });
}

export function useStorageFiles(storageId: string, path: string) {
  return useQuery({
    queryKey: ["storages", storageId, "files", path],
    queryFn: () => storageApi.listFiles(storageId, path),
    enabled: !!storageId,
    staleTime: 10_000,
  });
}

export function useTransfers() {
  return useQuery({
    queryKey: ["transfers"],
    queryFn: transferApi.list,
    refetchInterval: 2_000, // Refresh every 2 seconds when transfers are active
  });
}

export function useCreateStorage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: storageApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["storages"] });
    },
  });
}

export function useDeleteStorage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: storageApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["storages"] });
    },
  });
}

export function useCreateTransfer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: transferApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
    },
  });
}

// ============================================================
// Pricing API (Unified)
// ============================================================

export const pricingApi = {
  // General
  get: async (): Promise<PricingSettings> => {
    return await safeInvoke<PricingSettings>("pricing_get");
  },

  fetchRates: async (): Promise<ExchangeRates> => {
    return await safeInvoke<ExchangeRates>("pricing_fetch_rates");
  },

  updateDisplayCurrency: async (displayCurrency: Currency): Promise<PricingSettings> => {
    return await safeInvoke<PricingSettings>("pricing_update_display_currency", { displayCurrency });
  },

  reset: async (): Promise<PricingSettings> => {
    return await safeInvoke<PricingSettings>("pricing_reset");
  },

  // Colab
  colab: {
    updateSubscription: async (subscription: ColabSubscription): Promise<PricingSettings> => {
      return await safeInvoke<PricingSettings>("pricing_colab_update_subscription", { subscription });
    },

    updateGpuPricing: async (gpuPricing: ColabGpuPricing[]): Promise<PricingSettings> => {
      return await safeInvoke<PricingSettings>("pricing_colab_update_gpu", { gpuPricing });
    },

    calculate: async (): Promise<ColabPricingResult> => {
      return await safeInvoke<ColabPricingResult>("pricing_colab_calculate");
    },
  },

  // Vast.ai rates
  vast: {
    updateRates: async (rates: VastPricingRates): Promise<PricingSettings> => {
      return await safeInvoke<PricingSettings>("pricing_vast_update_rates", { rates });
    },

    syncInstance: async (hostId: string, vastInstanceId: number): Promise<HostPricing> => {
      return await safeInvoke<HostPricing>("pricing_sync_vast_instance", { hostId, vastInstanceId });
    },
  },

  // Host pricing
  host: {
    set: async (
      hostId: string,
      gpuHourlyUsd: number | null,
      storageUsedGb: number | null,
      source: PricingSource
    ): Promise<PricingSettings> => {
      return await safeInvoke<PricingSettings>("pricing_host_set", {
        hostId,
        gpuHourlyUsd,
        storageUsedGb,
        source,
      });
    },

    remove: async (hostId: string): Promise<PricingSettings> => {
      return await safeInvoke<PricingSettings>("pricing_host_remove", { hostId });
    },

    get: async (hostId: string): Promise<HostPricing | null> => {
      return await safeInvoke<HostPricing | null>("pricing_host_get", { hostId });
    },

    calculate: async (hostId: string, hostName?: string): Promise<HostCostBreakdown | null> => {
      return await safeInvoke<HostCostBreakdown | null>("pricing_host_calculate", {
        hostId,
        hostName: hostName ?? null,
      });
    },

    calculateAll: async (): Promise<HostCostBreakdown[]> => {
      return await safeInvoke<HostCostBreakdown[]>("pricing_host_calculate_all");
    },
  },

  // R2 usage cache
  r2Cache: {
    get: async (): Promise<StorageUsage[]> => {
      return await safeInvoke<StorageUsage[]>("pricing_get_r2_cache");
    },

    save: async (usages: StorageUsage[]): Promise<void> => {
      await safeInvoke("pricing_save_r2_cache", { usages });
    },
  },
};

// ============================================================
// Pricing Hooks
// ============================================================

export function usePricingSettings() {
  return useQuery({
    queryKey: ["pricing"],
    queryFn: pricingApi.get,
    staleTime: 60_000,
  });
}

export function useColabPricingCalculation() {
  return useQuery({
    queryKey: ["pricing", "colab", "calculation"],
    queryFn: pricingApi.colab.calculate,
    staleTime: 30_000,
  });
}

export function useHostCostBreakdown(hostId: string, hostName?: string) {
  return useQuery({
    queryKey: ["pricing", "host", hostId],
    queryFn: () => pricingApi.host.calculate(hostId, hostName),
    enabled: !!hostId,
    staleTime: 30_000,
  });
}

export function useAllHostCosts() {
  return useQuery({
    queryKey: ["pricing", "hosts", "all"],
    queryFn: pricingApi.host.calculateAll,
    staleTime: 30_000,
  });
}

export function useUpdateColabSubscription() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: pricingApi.colab.updateSubscription,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pricing"] });
    },
  });
}

export function useUpdateColabGpuPricing() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: pricingApi.colab.updateGpuPricing,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pricing"] });
    },
  });
}

export function useFetchExchangeRates() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: pricingApi.fetchRates,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pricing"] });
    },
  });
}

export function useUpdateDisplayCurrency() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: pricingApi.updateDisplayCurrency,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pricing"] });
    },
  });
}

export function useResetPricing() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: pricingApi.reset,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pricing"] });
    },
  });
}

export function useSetHostPricing() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: {
      hostId: string;
      gpuHourlyUsd: number | null;
      storageUsedGb: number | null;
      source: PricingSource;
    }) => pricingApi.host.set(params.hostId, params.gpuHourlyUsd, params.storageUsedGb, params.source),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pricing"] });
    },
  });
}

export function useSyncVastPricing() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: { hostId: string; vastInstanceId: number }) =>
      pricingApi.vast.syncInstance(params.hostId, params.vastInstanceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pricing"] });
    },
  });
}

// ============================================================
// Skill API
// ============================================================

export const skillApi = {
  /** List all skills */
  list: async (): Promise<SkillSummary[]> => {
    return await safeInvoke<SkillSummary[]>("skill_list");
  },

  /** Get a skill by path */
  get: async (path: string): Promise<Skill> => {
    return await safeInvoke<Skill>("skill_get", { path });
  },

  /** Save a skill to a file */
  save: async (path: string, skill: Skill): Promise<string> => {
    return await safeInvoke<string>("skill_save", { path, skill });
  },

  /** Delete a skill file */
  delete: async (path: string): Promise<void> => {
    await safeInvoke("skill_delete", { path });
  },

  /** Validate a skill */
  validate: async (skill: Skill): Promise<ValidationResult> => {
    return await safeInvoke<ValidationResult>("skill_validate", { skill });
  },

  /** Create a new empty skill */
  create: async (name: string): Promise<string> => {
    return await safeInvoke<string>("skill_create", { name });
  },

  /** Import a skill from external file */
  import: async (sourcePath: string): Promise<string> => {
    return await safeInvoke<string>("skill_import", { sourcePath });
  },

  /** Export a skill to external file */
  export: async (skillPath: string, destPath: string): Promise<void> => {
    await safeInvoke("skill_export", { skillPath, destPath });
  },

  /** Duplicate a skill */
  duplicate: async (path: string, newName: string): Promise<string> => {
    return await safeInvoke<string>("skill_duplicate", { path, newName });
  },
};

// ============================================================
// Skill Hooks
// ============================================================

export function useSkills() {
  return useQuery({
    queryKey: ["skills"],
    queryFn: skillApi.list,
    staleTime: 30_000,
  });
}

export function useSkill(path: string | null) {
  return useQuery({
    queryKey: ["skills", path],
    queryFn: () => skillApi.get(path!),
    enabled: !!path,
  });
}

export function useCreateSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: skillApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["skills"] });
    },
  });
}

export function useSaveSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ path, skill }: { path: string; skill: Skill }) =>
      skillApi.save(path, skill),
    onSuccess: (newPath, variables) => {
      if (newPath !== variables.path) {
        const assignments = loadSkillFolderAssignments();
        const next = renameSkillPathInAssignments(assignments, variables.path, newPath);
        if (next !== assignments) {
          saveSkillFolderAssignments(next);
        }
      }

      // Keep the skill detail + list caches in sync so navigation shows the latest content.
      queryClient.setQueryData(["skills", newPath], variables.skill);
      if (newPath !== variables.path) {
        queryClient.removeQueries({ queryKey: ["skills", variables.path] });
      }

      queryClient.setQueryData<SkillSummary[]>(["skills"], (prev) => {
        if (!prev) return prev;

        const nextSummary: SkillSummary = {
          path: newPath,
          name: variables.skill.name,
          version: variables.skill.version,
          description: variables.skill.description ?? null,
          step_count: variables.skill.steps.length,
        };

        const oldIndex = prev.findIndex((r) => r.path === variables.path);
        if (oldIndex >= 0) {
          return prev.map((r) => (r.path === variables.path ? { ...r, ...nextSummary } : r));
        }

        const exists = prev.some((r) => r.path === newPath);
        return exists
          ? prev.map((r) => (r.path === newPath ? { ...r, ...nextSummary } : r))
          : [...prev, nextSummary];
      });
    },
  });
}

export function useDeleteSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: skillApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["skills"] });
    },
  });
}

export function useValidateSkill() {
  return useMutation({
    mutationFn: skillApi.validate,
  });
}

export function useDuplicateSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ path, newName }: { path: string; newName: string }) =>
      skillApi.duplicate(path, newName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["skills"] });
    },
  });
}

// ============================================================
// Interactive Skill Execution API
// ============================================================

export const interactiveSkillApi = {
  /** Start an interactive skill execution with terminal output */
  run: async (params: {
    path: string;
    hostId: string;
    variables?: Record<string, string>;
    cols?: number;
    rows?: number;
    startStepId?: string | null;
    startImmediately?: boolean | null;
  }): Promise<InteractiveExecution> => {
    return await safeInvoke<InteractiveExecution>("skill_run_interactive", {
      path: params.path,
      hostId: params.hostId,
      variables: params.variables ?? {},
      cols: params.cols ?? null,
      rows: params.rows ?? null,
      startStepId: params.startStepId ?? null,
      startImmediately: params.startImmediately ?? null,
    });
  },

  /** Prepare an interactive skill execution (pending, manual start) */
  prepare: async (params: {
    path: string;
    hostId: string;
    variables?: Record<string, string>;
    cols?: number;
    rows?: number;
    startStepId?: string | null;
  }): Promise<InteractiveExecution> => {
    return await interactiveSkillApi.run({
      ...params,
      startImmediately: false,
    });
  },

  /** Send data to the interactive terminal (for human intervention) */
  send: async (executionId: string, data: string): Promise<void> => {
    await safeInvoke("skill_interactive_send", { executionId, data });
  },

  /** Send interrupt (Ctrl+C) to the interactive execution */
  interrupt: async (executionId: string): Promise<void> => {
    await safeInvoke("skill_interactive_interrupt", { executionId });
  },

  /** Lock/unlock intervention */
  setLock: async (executionId: string, locked: boolean): Promise<void> => {
    await safeInvoke("skill_interactive_lock", { executionId, locked });
  },

  /** Get execution state */
  get: async (executionId: string): Promise<InteractiveExecution> => {
    return await safeInvoke<InteractiveExecution>("skill_interactive_get", { executionId });
  },

  /** List all interactive executions */
  list: async (): Promise<InteractiveExecution[]> => {
    return await safeInvoke<InteractiveExecution[]>("skill_interactive_list");
  },

  /** Execute a command in the interactive terminal (used by skill runner) */
  execCommand: async (executionId: string, stepId: string, command: string): Promise<void> => {
    await safeInvoke("skill_interactive_exec_command", { executionId, stepId, command });
  },

  /** Pause an interactive execution */
  pause: async (executionId: string): Promise<void> => {
    await safeInvoke("skill_interactive_pause", { executionId });
  },

  /** Resume a paused interactive execution */
  resume: async (executionId: string): Promise<InteractiveExecution> => {
    return await safeInvoke<InteractiveExecution>("skill_interactive_resume", { executionId });
  },

  /** Start a prepared (pending) interactive execution */
  start: async (executionId: string): Promise<InteractiveExecution> => {
    return await safeInvoke<InteractiveExecution>("skill_interactive_start", { executionId });
  },

  /** Reconnect terminal for a prepared (pending) execution */
  reconnectTerminal: async (executionId: string): Promise<InteractiveExecution> => {
    return await safeInvoke<InteractiveExecution>("skill_interactive_reconnect_terminal", { executionId });
  },

  /** Cancel an interactive execution */
  cancel: async (executionId: string): Promise<void> => {
    await safeInvoke("skill_interactive_cancel", { executionId });
  },

  /** Skip a pending/waiting step */
  skipStep: async (executionId: string, stepId: string): Promise<void> => {
    await safeInvoke("skill_interactive_skip_step", { executionId, stepId });
  },

  /** Toggle skip for a step (best for prepared/pending executions) */
  toggleSkipStep: async (executionId: string, stepId: string): Promise<void> => {
    await safeInvoke("skill_interactive_toggle_skip_step", { executionId, stepId });
  },

  /** Mark all steps as complete and finish execution */
  markComplete: async (executionId: string): Promise<void> => {
    await safeInvoke("skill_interactive_mark_complete", { executionId });
  },

  /** Read persisted execution logs (JSONL) */
  logRead: async (params: {
    executionId: string;
    cursor?: number | null;
    maxBytes?: number | null;
  }): Promise<SkillRunLogChunk> => {
    return await safeInvoke<SkillRunLogChunk>("skill_interactive_log_read", {
      executionId: params.executionId,
      cursor: params.cursor ?? null,
      maxBytes: params.maxBytes ?? null,
    });
  },

  /** Clear persisted execution logs */
  logClear: async (executionId: string): Promise<void> => {
    await safeInvoke("skill_interactive_log_clear", { executionId });
  },
};

// ============================================================
// Interactive Skill Event Listeners
// ============================================================

/** Listen for interactive skill events */
export async function listenInteractiveSkillEvents(
  callback: (event: InteractiveSkillEvent) => void
): Promise<UnlistenFn> {
  const unlisteners: UnlistenFn[] = [];
  
  const eventTypes = [
    "skill:interactive_started",
    "skill:connected",
    "skill:command_pending",
    "skill:command_sending",
    "skill:command_sent",
    "skill:intervention_lock_changed",
    "skill:waiting_for_confirmation",
  ];
  
  for (const eventType of eventTypes) {
    const unlisten = await listen<InteractiveSkillEvent>(eventType, (event) => {
      callback(event.payload);
    });
    unlisteners.push(unlisten);
  }
  
  return () => {
    for (const unlisten of unlisteners) {
      unlisten();
    }
  };
}

/** Listen for persisted log appends for a specific execution */
export async function listenSkillLogAppended(
  callback: (event: SkillLogAppendedEvent) => void
): Promise<UnlistenFn> {
  return await listen<SkillLogAppendedEvent>("skill:log_appended", (event) => {
    callback(event.payload);
  });
}

// ============================================================
// Interactive Skill Hooks
// ============================================================

export function useInteractiveExecutions() {
  return useQuery({
    queryKey: ["interactive-executions"],
    queryFn: interactiveSkillApi.list,
    refetchInterval: 5_000,
    staleTime: 3_000,
  });
}

export function useInteractiveExecution(id: string | null) {
  const queryClient = useQueryClient();
  
  // Listen for skill events to trigger immediate refetch
  useEffect(() => {
    if (!id) return;
    
    let unlisten: (() => void) | null = null;
    
    const setupListeners = async () => {
      const { listen } = await import("@tauri-apps/api/event");
      
      // Listen for any skill event that might update execution state
      const events = [
        "skill:interactive_started",
        "skill:execution_updated",
        "skill:step_started",
        "skill:step_completed", 
        "skill:step_failed",
        "skill:step_progress",
        "skill:command_sending",
        "skill:command_failed",
        "skill:execution_completed",
        "skill:execution_failed",
        "skill:execution_cancelled",
        "skill:intervention_lock_changed",
      ];
      
      const unlisteners: (() => void)[] = [];
      
	      for (const eventName of events) {
	        const u = await listen<{
	          execution_id?: string;
	          step_id?: string;
	          status?: string;
	          progress?: string | null;
	        }>(eventName, (event) => {
	          if (event.payload.execution_id === id) {
	            queryClient.setQueryData<InteractiveExecution | undefined>(
	              ["interactive-executions", id],
	              (prev) => {
                if (!prev) return prev;
                const next: InteractiveExecution = { ...prev };
                const stepId = event.payload.step_id;

                if (eventName === "skill:execution_updated" && event.payload.status) {
                  next.status = event.payload.status as InteractiveExecution["status"];
                }
                if (eventName === "skill:execution_completed") next.status = "completed";
                if (eventName === "skill:execution_failed") next.status = "failed";
                if (eventName === "skill:execution_cancelled") next.status = "cancelled";
                if (eventName === "skill:step_progress") {
                  const stepIdForProgress = event.payload.step_id;
                  if (stepIdForProgress) {
                    const map = { ...(prev.step_progress ?? {}) };
                    if (event.payload.progress == null) {
                      delete map[stepIdForProgress];
                    } else {
                      map[stepIdForProgress] = event.payload.progress as string;
                    }
                    next.step_progress = map;
                  }
                }

	                if (stepId) {
	                  const steps: InteractiveExecution["steps"] = prev.steps.map((step) => {
	                    if (step.step_id !== stepId) return step;
	                    if (eventName === "skill:step_started") return { ...step, status: "running" };
	                    if (eventName === "skill:step_completed") return { ...step, status: "success" };
	                    if (eventName === "skill:step_failed") return { ...step, status: "failed" };
	                    if (eventName === "skill:command_sending") return { ...step, status: "running" };
	                    return step;
	                  });
	                  next.steps = steps;
	                }

                return next;
              }
            );
            // Invalidate query to trigger immediate refetch
            queryClient.invalidateQueries({ queryKey: ["interactive-executions", id] });
          }
        });
        unlisteners.push(u);
      }
      
      unlisten = () => unlisteners.forEach(u => u());
    };
    
    setupListeners();
    
    return () => {
      if (unlisten) unlisten();
    };
  }, [id, queryClient]);
  
  return useQuery({
    queryKey: ["interactive-executions", id],
    queryFn: () => interactiveSkillApi.get(id!),
    enabled: !!id,
    refetchInterval: 2_000, // Fallback polling, events trigger immediate refresh
    staleTime: 500, // Consider data stale after 500ms
  });
}

export function useRunInteractiveSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: interactiveSkillApi.run,
    onSuccess: (execution) => {
      // Immediately seed the query cache with the returned execution data
      // This allows the sidebar to show the skill info instantly
      queryClient.setQueryData(
        ["interactive-executions", execution.id],
        execution
      );
      queryClient.invalidateQueries({ queryKey: ["interactive-executions"] });
    },
  });
}

export function useInteractiveSkillSend() {
  return useMutation({
    mutationFn: ({ executionId, data }: { executionId: string; data: string }) =>
      interactiveSkillApi.send(executionId, data),
  });
}

export function useInteractiveSkillInterrupt() {
  return useMutation({
    mutationFn: interactiveSkillApi.interrupt,
  });
}

// ============================================================
// Google Drive OAuth API
// ============================================================

export type GDriveOAuthUrlResponse = {
  auth_url: string;
  redirect_uri: string;
};

export const gdriveOAuthApi = {
  /** Generate OAuth authorization URL */
  generateAuthUrl: async (
    clientId: string,
    clientSecret: string
  ): Promise<GDriveOAuthUrlResponse> => {
    return await safeInvoke<GDriveOAuthUrlResponse>("gdrive_generate_auth_url", {
      clientId,
      clientSecret,
    });
  },

  /** Exchange authorization code for token */
  exchangeCode: async (
    clientId: string,
    clientSecret: string,
    authCode: string
  ): Promise<string> => {
    return await safeInvoke<string>("gdrive_exchange_code", {
      clientId,
      clientSecret,
      authCode,
    });
  },

  /** Verify token is valid */
  verifyToken: async (tokenJson: string): Promise<boolean> => {
    return await safeInvoke<boolean>("gdrive_verify_token", { tokenJson });
  },

  /** Test Google Drive connection */
  testConnection: async (
    clientId: string,
    clientSecret: string,
    tokenJson: string
  ): Promise<boolean> => {
    return await safeInvoke<boolean>("gdrive_test_connection", {
      clientId,
      clientSecret,
      tokenJson,
    });
  },
};

// ============================================================
// Secrets API
// ============================================================

import type { Secret, SecretMeta, SecretInput, SecretSuggestion, SecretValidationResult } from "./types";

export const secretsApi = {
  /** List all secrets (metadata only, no values) */
  list: async (): Promise<SecretMeta[]> => {
    return await safeInvoke<SecretMeta[]>("secret_list");
  },

  /** Get a secret with its value */
  get: async (name: string): Promise<Secret> => {
    return await safeInvoke<Secret>("secret_get", { name });
  },

  /** Create or update a secret */
  upsert: async (input: SecretInput): Promise<SecretMeta> => {
    return await safeInvoke<SecretMeta>("secret_upsert", { input });
  },

  /** Delete a secret */
  delete: async (name: string): Promise<void> => {
    return await safeInvoke<void>("secret_delete", { name });
  },

  /** Check if a secret exists */
  exists: async (name: string): Promise<boolean> => {
    return await safeInvoke<boolean>("secret_check_exists", { name });
  },

  /** Get suggested secret templates for common services */
  suggestions: async (): Promise<SecretSuggestion[]> => {
    return await safeInvoke<SecretSuggestion[]>("secret_suggestions");
  },

  /** Validate that all secrets referenced in a template exist */
  validateRefs: async (template: string): Promise<SecretValidationResult> => {
    return await safeInvoke<SecretValidationResult>("secret_validate_refs", { template });
  },
};

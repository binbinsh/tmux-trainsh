import "@xterm/xterm/css/xterm.css";

import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useNavigate, useParams } from "@tanstack/react-router";
import { AnimatePresence, motion } from "framer-motion";
import { Cable, ChevronDown, Loader2, MoreHorizontal, Pause, Play, RotateCcw, SkipForward, Square, X } from "lucide-react";
import { TerminalInstance } from "@/lib/terminal-instance";
import {
  interactiveSkillApi,
  listenSkillLogAppended,
  useInteractiveExecution,
  useHosts,
  useSkill,
} from "@/lib/tauri-api";
import { useQueryClient } from "@tanstack/react-query";
import type { Condition, SkillRunLogEntry, Step as SkillStep, ValueSource } from "@/lib/types";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Skeleton,
} from "@/components/ui";
import { cn } from "@/lib/utils";
import { copyText } from "@/lib/clipboard";

const RUN_SECTION_KEY = "__run__";
const STEP_TITLE_FALLBACK = "unknown";

const OPERATION_KEYS = [
  "run_commands",
  "transfer",
  "ssh_command",
  "rsync_upload",
  "rsync_download",
  "vast_start",
  "vast_stop",
  "vast_destroy",
  "vast_copy",
  "tmux_new",
  "tmux_send",
  "tmux_capture",
  "tmux_kill",
  "gdrive_mount",
  "gdrive_unmount",
  "git_clone",
  "hf_download",
  "sleep",
  "wait_condition",
  "assert",
  "set_var",
  "get_value",
  "http_request",
  "notify",
  "group",
] as const;
type OperationKey = (typeof OPERATION_KEYS)[number];

const PROJECT_ACCENT_VARS = [
  "--doppio-accent-blue",
  "--doppio-accent-cyan",
  "--doppio-accent-green",
  "--doppio-accent-yellow",
  "--doppio-accent-red",
  "--doppio-accent-purple",
] as const;

function stableHash(input: string) {
  let hash = 0;
  for (let i = 0; i < input.length; i++) {
    hash = (hash * 31 + input.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

function projectAccentVar(key: string) {
  const idx = stableHash(key) % PROJECT_ACCENT_VARS.length;
  return PROJECT_ACCENT_VARS[idx];
}

function StepStatusDot({ status }: { status: string }) {
  const className =
    status === "success"
      ? "bg-success"
      : status === "failed"
      ? "bg-destructive"
      : status === "running"
      ? "bg-primary animate-pulse"
      : status === "retrying"
      ? "bg-warning animate-pulse"
      : status === "skipped"
      ? "bg-muted-foreground/60"
      : "bg-muted-foreground/30";
  return <span className={cn("size-2 rounded-full", className)} />;
}

function SkillRunTerminal({
  terminalId,
  interventionLocked,
}: {
  terminalId: string;
  interventionLocked?: boolean;
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const instanceRef = useRef<TerminalInstance | null>(null);

  useEffect(() => {
    const container = hostRef.current;
    if (!container) return;

    const instance = new TerminalInstance({
      id: terminalId,
      container,
      interventionLocked,
    });
    instanceRef.current = instance;
    void instance.initialize();

    return () => {
      instance.dispose();
      instanceRef.current = null;
    };
  }, [terminalId]);

  useEffect(() => {
    instanceRef.current?.setInterventionLocked(interventionLocked ?? false);
  }, [interventionLocked]);

  return <div ref={hostRef} className="relative h-full w-full overflow-hidden bg-card rounded-none" />;
}

function formatLogTimestamp(ts: string) {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  const pad2 = (n: number) => String(n).padStart(2, "0");
  const pad3 = (n: number) => String(n).padStart(3, "0");
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(
    d.getMinutes()
  )}:${pad2(d.getSeconds())}.${pad3(d.getMilliseconds())}`;
}

function streamBadgeClass(stream: SkillRunLogEntry["stream"]) {
  switch (stream) {
    case "stdout":
      return "bg-success/10 text-success border-success/20";
    case "stderr":
      return "bg-destructive/10 text-destructive border-destructive/20";
    case "progress":
      return "bg-primary/10 text-primary border-primary/20";
    default:
      return "bg-muted text-muted-foreground border-border";
  }
}

function normalizeLogMessage(message: string) {
  return (
    message
      .replace(/\r\n/g, "\n")
      .replace(/\r/g, "")
      .replace(/\u001b\[[0-9;?]*[ -/]*[@-~]/g, "")
      .replace(/\u001b[\(\)][0-9A-Za-z]/g, "")
      .replace(/\u0008+/g, "")
      .replace(/\u0007+/g, "")
  );
}

function isMetaLogStream(stream: SkillRunLogEntry["stream"]) {
  return stream === "system" || stream === "progress";
}

function interpolateTemplate(template: string, variables: Record<string, string>) {
  return template.replace(/\$\{([^}]+)\}/g, (match, expr) => {
    if (expr.startsWith("secret:") || expr.startsWith("env.") || expr.startsWith("step.")) {
      return match;
    }
    const value = variables[expr];
    return value ?? match;
  });
}

function firstMeaningfulLine(text: string) {
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  return { first: lines[0] ?? "", hasMore: lines.length > 1 };
}

function summarizeMultiline(text: string) {
  const { first, hasMore } = firstMeaningfulLine(text);
  if (!first) return "";
  return hasMore ? `${first} …` : first;
}

function sshGitUrlToHttps(url: string) {
  const u = url.trim();
  if (!u) return null;

  if (u.startsWith("git@")) {
    const rest = u.slice("git@".length);
    const idx = rest.indexOf(":");
    if (idx > 0) {
      const host = rest.slice(0, idx).trim();
      const path = rest.slice(idx + 1).trim().replace(/^\/+/, "");
      if (host && path) return `https://${host}/${path}`;
    }
  }

  for (const scheme of ["ssh://", "git+ssh://", "ssh+git://"]) {
    if (!u.startsWith(scheme)) continue;
    const rest = u.slice(scheme.length);
    const idx = rest.indexOf("/");
    if (idx <= 0) return null;
    const authority = rest.slice(0, idx).trim();
    const path = rest.slice(idx + 1).trim().replace(/^\/+/, "");
    if (!authority || !path) return null;

    let host = authority;
    const at = authority.lastIndexOf("@");
    if (at >= 0) host = authority.slice(at + 1);
    const colon = host.indexOf(":");
    if (colon > 0) host = host.slice(0, colon);
    host = host.trim();
    if (!host) return null;
    return `https://${host}/${path}`;
  }

  return null;
}

function hostIdToLabel(hostId: string, hostNameById: Map<string, string>) {
  const trimmed = hostId.trim();
  const known = hostNameById.get(trimmed);
  if (known) return known;
  if (trimmed === "__local__") return "local";
  const vast = trimmed.match(/^vast:\s*(\d+)\s*$/i);
  if (vast) return `Vast #${vast[1]}`;
  return trimmed || STEP_TITLE_FALLBACK;
}

function resolveHostRefLabel(
  hostRef: string | null | undefined,
  variables: Record<string, string>,
  executionHostId: string,
  hostNameById: Map<string, string>
) {
  const raw = hostRef ? interpolateTemplate(hostRef, variables).trim() : "";
  if (!raw || raw.toLowerCase() === "target") return hostIdToLabel(executionHostId, hostNameById);
  return hostIdToLabel(raw, hostNameById);
}

function formatCondition(
  cond: Condition,
  variables: Record<string, string>,
  executionHostId: string,
  hostNameById: Map<string, string>
): string {
  if (cond === "always" || cond === "never") return cond;

  if ("not" in cond)
    return `not (${formatCondition(cond.not, variables, executionHostId, hostNameById)})`;
  if ("and" in cond)
    return cond.and
      .map((c) => formatCondition(c, variables, executionHostId, hostNameById))
      .join(" and ");
  if ("or" in cond)
    return cond.or.map((c) => formatCondition(c, variables, executionHostId, hostNameById)).join(" or ");

  if ("host_online" in cond) {
    return `host_online ${resolveHostRefLabel(
      cond.host_online.host_id,
      variables,
      executionHostId,
      hostNameById
    )}`;
  }
  if ("tmux_alive" in cond) {
    return `tmux_alive ${resolveHostRefLabel(
      cond.tmux_alive.host_id,
      variables,
      executionHostId,
      hostNameById
    )}:${interpolateTemplate(cond.tmux_alive.session_name, variables)}`;
  }
  if ("file_exists" in cond) {
    return `file_exists ${resolveHostRefLabel(
      cond.file_exists.host_id,
      variables,
      executionHostId,
      hostNameById
    )}:${interpolateTemplate(cond.file_exists.path, variables)}`;
  }
  if ("file_contains" in cond) {
    return `file_contains ${resolveHostRefLabel(
      cond.file_contains.host_id,
      variables,
      executionHostId,
      hostNameById
    )}:${interpolateTemplate(cond.file_contains.path, variables)}`;
  }
  if ("command_succeeds" in cond) {
    return `command_succeeds ${resolveHostRefLabel(
      cond.command_succeeds.host_id,
      variables,
      executionHostId,
      hostNameById
    )}:${summarizeMultiline(interpolateTemplate(cond.command_succeeds.command, variables))}`;
  }
  if ("output_matches" in cond) {
    return `output_matches ${resolveHostRefLabel(
      cond.output_matches.host_id,
      variables,
      executionHostId,
      hostNameById
    )}:${summarizeMultiline(interpolateTemplate(cond.output_matches.command, variables))}`;
  }
  if ("var_equals" in cond) {
    return `var_equals ${interpolateTemplate(cond.var_equals.name, variables)}=${interpolateTemplate(
      cond.var_equals.value,
      variables
    )}`;
  }
  if ("var_matches" in cond) {
    return `var_matches ${interpolateTemplate(cond.var_matches.name, variables)}`;
  }
  if ("gpu_available" in cond) {
    return `gpu_available ${resolveHostRefLabel(
      cond.gpu_available.host_id,
      variables,
      executionHostId,
      hostNameById
    )}`;
  }
  if ("gdrive_mounted" in cond) {
    return `gdrive_mounted ${resolveHostRefLabel(
      cond.gdrive_mounted.host_id,
      variables,
      executionHostId,
      hostNameById
    )}:${interpolateTemplate(cond.gdrive_mounted.mount_path, variables)}`;
  }

  return STEP_TITLE_FALLBACK;
}

function formatTransferEndpoint(
  endpoint: unknown,
  variables: Record<string, string>,
  executionHostId: string,
  hostNameById: Map<string, string>
): string {
  if (!endpoint || typeof endpoint !== "object") return STEP_TITLE_FALLBACK;

  if ("local" in endpoint) {
    const local = (endpoint as { local?: { path: string } }).local;
    if (!local) return "local";
    return `local:${interpolateTemplate(local.path, variables)}`;
  }
  if ("host" in endpoint) {
    const host = (endpoint as { host?: { host_id?: string | null; path: string } }).host;
    if (!host) return "host";
    const hostLabel = resolveHostRefLabel(host.host_id, variables, executionHostId, hostNameById);
    return `${hostLabel}:${interpolateTemplate(host.path, variables)}`;
  }
  if ("storage" in endpoint) {
    const storage = (endpoint as { storage?: { storage_id: string; path: string } }).storage;
    if (!storage) return "storage";
    return `storage:${interpolateTemplate(storage.storage_id, variables)}:${interpolateTemplate(
      storage.path,
      variables
    )}`;
  }

  return STEP_TITLE_FALLBACK;
}

function formatValueSource(
  source: ValueSource,
  variables: Record<string, string>,
  executionHostId: string,
  hostNameById: Map<string, string>
): string {
  if (typeof source !== "object" || source === null) return STEP_TITLE_FALLBACK;

  if ("var" in source) return `var:${interpolateTemplate(source.var, variables)}`;
  if ("step_output" in source) return `step:${interpolateTemplate(source.step_output, variables)}.output`;
  if ("command" in source) {
    const host = resolveHostRefLabel(source.command.host_id, variables, executionHostId, hostNameById);
    const cmd = summarizeMultiline(interpolateTemplate(source.command.command, variables));
    return `${host}:${cmd}`;
  }

  return STEP_TITLE_FALLBACK;
}

function getOperationKey(step: SkillStep): OperationKey | null {
  for (const key of OPERATION_KEYS) {
    if (key in step) return key;
  }
  return null;
}

function formatVastTargetHint(
  variables: Record<string, string>,
  executionHostId: string,
  hostNameById: Map<string, string>
) {
  const target = (variables.target ?? executionHostId).trim();
  return hostIdToLabel(target || executionHostId, hostNameById);
}

function formatShortCommandForStep(
  def: SkillStep,
  variables: Record<string, string>,
  executionHostId: string,
  hostNameById: Map<string, string>
) {
  const key = getOperationKey(def);
  if (!key) return "";
  const op = (def as Record<string, unknown>)[key] as any;

  switch (key) {
    case "run_commands": {
      const commands = typeof op?.commands === "string" ? interpolateTemplate(op.commands, variables) : "";
      const summary = summarizeMultiline(commands);
      const workdir = typeof op?.workdir === "string" ? interpolateTemplate(op.workdir, variables) : "";
      return workdir ? `${workdir}: ${summary}` : summary;
    }
    case "ssh_command": {
      const command = typeof op?.command === "string" ? interpolateTemplate(op.command, variables) : "";
      return summarizeMultiline(command);
    }
    case "transfer": {
      const src = formatTransferEndpoint(op?.source, variables, executionHostId, hostNameById);
      const dst = formatTransferEndpoint(op?.destination, variables, executionHostId, hostNameById);
      return `${src} -> ${dst}`;
    }
    case "rsync_upload": {
      const localPath = typeof op?.local_path === "string" ? interpolateTemplate(op.local_path, variables) : "";
      const remotePath = typeof op?.remote_path === "string" ? interpolateTemplate(op.remote_path, variables) : "";
      return `${localPath} -> ${remotePath}`.trim();
    }
    case "rsync_download": {
      const remotePath = typeof op?.remote_path === "string" ? interpolateTemplate(op.remote_path, variables) : "";
      const localPath = typeof op?.local_path === "string" ? interpolateTemplate(op.local_path, variables) : "";
      return `${remotePath} -> ${localPath}`.trim();
    }
    case "git_clone": {
      let repo = typeof op?.repo_url === "string" ? interpolateTemplate(op.repo_url, variables) : "";
      const dest = typeof op?.destination === "string" ? interpolateTemplate(op.destination, variables) : "";
      const branch = typeof op?.branch === "string" ? interpolateTemplate(op.branch, variables) : "";
      const authTokenProvided = typeof op?.auth_token === "string" && op.auth_token.trim().length > 0;
      if (authTokenProvided && !repo.startsWith("https://")) {
        const https = sshGitUrlToHttps(repo);
        if (https) repo = https;
      }
      return branch ? `${repo} -> ${dest} (${branch})` : `${repo} -> ${dest}`;
    }
    case "hf_download": {
      const repo = typeof op?.repo_id === "string" ? interpolateTemplate(op.repo_id, variables) : "";
      const dest = typeof op?.destination === "string" ? interpolateTemplate(op.destination, variables) : "";
      return `${repo} -> ${dest}`.trim();
    }
    case "vast_start":
    case "vast_stop":
    case "vast_destroy": {
      return formatVastTargetHint(variables, executionHostId, hostNameById);
    }
    case "vast_copy": {
      const src = typeof op?.src === "string" ? interpolateTemplate(op.src, variables) : "";
      const dst = typeof op?.dst === "string" ? interpolateTemplate(op.dst, variables) : "";
      return `${src} -> ${dst}`.trim();
    }
    case "tmux_new": {
      const session = typeof op?.session_name === "string" ? interpolateTemplate(op.session_name, variables) : "";
      const cmd = typeof op?.command === "string" ? summarizeMultiline(interpolateTemplate(op.command, variables)) : "";
      return cmd ? `${session}: ${cmd}` : session;
    }
    case "tmux_send": {
      const session = typeof op?.session_name === "string" ? interpolateTemplate(op.session_name, variables) : "";
      const keys = typeof op?.keys === "string" ? summarizeMultiline(interpolateTemplate(op.keys, variables)) : "";
      return keys ? `${session}: ${keys}` : session;
    }
    case "tmux_capture": {
      const session = typeof op?.session_name === "string" ? interpolateTemplate(op.session_name, variables) : "";
      const lines = typeof op?.lines === "number" ? op.lines : null;
      return lines ? `${session}: last ${lines} lines` : `${session}: capture`;
    }
    case "tmux_kill": {
      const session = typeof op?.session_name === "string" ? interpolateTemplate(op.session_name, variables) : "";
      return session;
    }
    case "gdrive_mount": {
      const mount = typeof op?.mount_path === "string" ? interpolateTemplate(op.mount_path, variables) : "";
      return mount || "/content/drive/MyDrive";
    }
    case "gdrive_unmount": {
      const mount = typeof op?.mount_path === "string" ? interpolateTemplate(op.mount_path, variables) : "";
      return mount;
    }
    case "sleep": {
      const seconds = typeof op?.duration_secs === "number" ? op.duration_secs : null;
      return seconds != null ? `${seconds}s` : "";
    }
    case "wait_condition": {
      const cond = op?.condition
        ? formatCondition(op.condition as Condition, variables, executionHostId, hostNameById)
        : STEP_TITLE_FALLBACK;
      const timeout = typeof op?.timeout_secs === "number" ? ` (timeout ${op.timeout_secs}s)` : "";
      return `${cond}${timeout}`;
    }
    case "assert": {
      const cond = op?.condition
        ? formatCondition(op.condition as Condition, variables, executionHostId, hostNameById)
        : STEP_TITLE_FALLBACK;
      const message = typeof op?.message === "string" ? interpolateTemplate(op.message, variables) : "";
      return message ? `${cond} (${message})` : cond;
    }
    case "set_var": {
      const name = typeof op?.name === "string" ? interpolateTemplate(op.name, variables) : "";
      const value = typeof op?.value === "string" ? interpolateTemplate(op.value, variables) : "";
      const oneLine = value.replace(/\s+/g, " ").trim();
      return name ? `${name}=${oneLine}` : oneLine;
    }
    case "get_value": {
      const varName = typeof op?.var_name === "string" ? interpolateTemplate(op.var_name, variables) : "";
      const src = op?.source
        ? formatValueSource(op.source as ValueSource, variables, executionHostId, hostNameById)
        : STEP_TITLE_FALLBACK;
      return varName ? `${varName} <- ${src}` : src;
    }
    case "http_request": {
      const method = typeof op?.method === "string" ? op.method : "HTTP";
      const url = typeof op?.url === "string" ? interpolateTemplate(op.url, variables) : "";
      return `${method} ${url}`.trim();
    }
    case "notify": {
      const title = typeof op?.title === "string" ? interpolateTemplate(op.title, variables) : "";
      return title;
    }
    case "group": {
      const mode = typeof op?.mode === "string" ? op.mode : "sequential";
      const steps = Array.isArray(op?.steps) ? op.steps.join(", ") : "";
      return steps ? `${mode}: ${steps}` : mode;
    }
  }
}

function formatStepTitleLine(
  stepId: string,
  defStep: SkillStep | undefined,
  variables: Record<string, string>,
  executionHostId: string,
  hostNameById: Map<string, string>
) {
  if (!defStep) return stepId;
  const key = getOperationKey(defStep);
  const actionName = key ? key.replace(/_/g, "-") : stepId;
  const shortCmd = formatShortCommandForStep(defStep, variables, executionHostId, hostNameById);
  return shortCmd ? `${actionName}: ${shortCmd}` : actionName;
}

export function SkillRunPage() {
  const { id } = useParams({ from: "/skills/runs/$id" });
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: execution, isLoading, isError, error } = useInteractiveExecution(id);
  const { data: skill } = useSkill(execution?.skill_path ?? null);
  const { data: hosts } = useHosts();

  const [logEntries, setLogEntries] = useState<SkillRunLogEntry[]>([]);
  const [logCursor, setLogCursor] = useState(0);
  const [logLoading, setLogLoading] = useState(false);
  const logCursorRef = useRef(0);
  const logLoadingRef = useRef(false);
  const pendingLogRefreshRef = useRef(false);

  const logViewportsRef = useRef<Record<string, HTMLDivElement | null>>({});
  const logAutoScrollRef = useRef<Record<string, boolean>>({});

  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    [RUN_SECTION_KEY]: true,
  });
  const [rightSidebarOpen, setRightSidebarOpen] = useState(true);

  useEffect(() => {
    logCursorRef.current = logCursor;
  }, [logCursor]);

  const loadLogs = async (opts?: { reset?: boolean }) => {
    if (logLoadingRef.current) return;
    logLoadingRef.current = true;
    setLogLoading(true);
    try {
      const reset = opts?.reset ?? false;
      if (reset) {
        pendingLogRefreshRef.current = false;
      }
      const startCursor = reset ? 0 : logCursorRef.current;
      const chunk = await interactiveSkillApi.logRead({
        executionId: id,
        cursor: startCursor,
        maxBytes: 256 * 1024,
      });
      setLogEntries((prev) => (reset ? chunk.entries : [...prev, ...chunk.entries]));
      setLogCursor(chunk.next_cursor);
      logCursorRef.current = chunk.next_cursor;
    } finally {
      logLoadingRef.current = false;
      setLogLoading(false);
      if (pendingLogRefreshRef.current) {
        pendingLogRefreshRef.current = false;
        setTimeout(() => void loadLogs(), 0);
      }
    }
  };

  useEffect(() => {
    setLogEntries([]);
    setLogCursor(0);
    logCursorRef.current = 0;
    pendingLogRefreshRef.current = false;
    logAutoScrollRef.current = { [RUN_SECTION_KEY]: true };
    logViewportsRef.current = {};
    setExpandedSections({ [RUN_SECTION_KEY]: true });
    void loadLogs({ reset: true });
  }, [id]);

  useEffect(() => {
    if (!execution?.current_step) return;
    const stepId = execution.current_step;
    setExpandedSections((prev) => (prev[stepId] ? prev : { ...prev, [stepId]: true }));
    logAutoScrollRef.current[stepId] = true;
  }, [execution?.current_step]);

  useEffect(() => {
    let unlisten: (() => void) | null = null;
    (async () => {
      unlisten = await listenSkillLogAppended((payload) => {
        if (payload.execution_id !== id) return;
        if (logLoadingRef.current) {
          pendingLogRefreshRef.current = true;
          return;
        }
        void loadLogs();
      });
    })();
    return () => {
      if (unlisten) unlisten();
    };
  }, [id]);

  useEffect(() => {
    for (const [key, isOpen] of Object.entries(expandedSections)) {
      if (!isOpen) continue;
      if (!logAutoScrollRef.current[key]) continue;
      const el = logViewportsRef.current[key];
      if (!el) continue;
      el.scrollTop = el.scrollHeight;
    }
  }, [expandedSections, logEntries.length, rightSidebarOpen]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.metaKey && e.key === "]") {
        e.preventDefault();
        e.stopPropagation();
        setRightSidebarOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, []);

  useEffect(() => {
    const onToggle = () => setRightSidebarOpen((prev) => !prev);
    window.addEventListener("skillrun:toggle_right_sidebar", onToggle as EventListener);
    return () => window.removeEventListener("skillrun:toggle_right_sidebar", onToggle as EventListener);
  }, []);

  const logsByStep = useMemo(() => {
    const logs = new Map<string, SkillRunLogEntry[]>();

    for (const entry of logEntries) {
      const key = entry.step_id ?? RUN_SECTION_KEY;

      const existing = logs.get(key);
      if (existing) existing.push(entry);
      else logs.set(key, [entry]);
    }

    return logs;
  }, [logEntries]);

  const hostNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const host of hosts ?? []) {
      map.set(host.id, host.name);
    }
    return map;
  }, [hosts]);

  const skillStepsById = useMemo(() => {
    const map = new Map<string, SkillStep>();
    for (const step of skill?.steps ?? []) {
      map.set(step.id, step);
    }
    return map;
  }, [skill?.steps]);

  const [action, setAction] = useState<null | "pause" | "resume" | "interrupt" | "cancel" | "restart" | "start" | "reconnect">(null);
  const [stepAction, setStepAction] = useState<null | { stepId: string; action: "rerun" | "skip" }>(null);
  const canPause =
    execution?.status === "running" ||
    execution?.status === "connecting" ||
    execution?.status === "pending";
  const canResume = execution?.status === "paused";
  const canCancel =
    execution?.status === "running" ||
    execution?.status === "connecting" ||
    execution?.status === "pending" ||
    execution?.status === "paused" ||
    execution?.status === "waiting_for_input";
  const isPending = execution?.status === "pending";
  const canReconnect =
    execution?.status !== "completed" && execution?.status !== "failed" && execution?.status !== "cancelled";

  const doPause = async () => {
    if (!execution) return;
    setAction("pause");
    try {
      await interactiveSkillApi.pause(execution.id);
    } finally {
      setAction(null);
    }
  };
  const doResume = async () => {
    if (!execution) return;
    setAction("resume");
    try {
      await interactiveSkillApi.resume(execution.id);
    } finally {
      setAction(null);
    }
  };
  const doInterrupt = async () => {
    if (!execution) return;
    setAction("interrupt");
    try {
      await interactiveSkillApi.interrupt(execution.id);
    } finally {
      setAction(null);
    }
  };
  const doCancel = async () => {
    if (!execution) return;
    setAction("cancel");
    try {
      await interactiveSkillApi.cancel(execution.id);
    } finally {
      setAction(null);
    }
  };

  const sanitizeVariables = (vars: Record<string, string> | null | undefined) => {
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(vars ?? {})) {
      if (k === "target") continue;
      if (k.startsWith("_doppio_")) continue;
      out[k] = v;
    }
    return out;
  };

  const doRestart = async (startStepId?: string | null) => {
    if (!execution) return;
    setAction("restart");
    try {
      if (canCancel) {
        try {
          await interactiveSkillApi.cancel(execution.id);
        } catch {
          // Ignore and still restart.
        }
      }

      const restarted = await interactiveSkillApi.prepare({
        path: execution.skill_path,
        hostId: execution.host_id,
        variables: sanitizeVariables(execution.variables),
        cols: execution.terminal?.cols ?? 120,
        rows: execution.terminal?.rows ?? 32,
        startStepId: startStepId ?? null,
      });
      navigate({ to: `/skills/runs/${restarted.id}` });
    } finally {
      setAction(null);
    }
  };

  const doStart = async () => {
    if (!execution) return;
    setAction("start");
    try {
      await interactiveSkillApi.start(execution.id);
    } finally {
      setAction(null);
    }
  };

  const doReconnectTerminal = async () => {
    if (!execution) return;
    setAction("reconnect");
    try {
      const updated = await interactiveSkillApi.reconnectTerminal(execution.id);
      queryClient.setQueryData(["interactive-executions", updated.id], updated);
    } finally {
      setAction(null);
    }
  };

  const doToggleSkipStep = async (stepId: string) => {
    if (!execution) return;
    setStepAction({ stepId, action: "skip" });
    try {
      await interactiveSkillApi.toggleSkipStep(execution.id, stepId);
    } finally {
      setStepAction(null);
    }
  };

  const accentStyle = useMemo(() => {
    const key = execution?.skill_path || execution?.skill_name || execution?.id || "skill";
    const variable = projectAccentVar(key);
    const style: CSSProperties & Record<string, string> = {
      borderLeftColor: `rgb(var(${variable}))`,
      "--skill-accent": `var(${variable})`,
    };
    return style;
  }, [execution?.id, execution?.skill_name, execution?.skill_path]);

  if (isError) {
    const msg =
      typeof error === "object" && error !== null && "message" in error
        ? String((error as { message: unknown }).message)
        : String(error);
    return (
      <div className="h-full p-6">
        <Card>
          <CardHeader>
            <CardTitle>Skill Run</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="text-sm text-destructive">Failed to load execution: {msg}</div>
            <Button onClick={() => navigate({ to: "/skills" })}>Back to Skills</Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (isLoading || !execution) {
    return (
      <div className="h-full p-4 space-y-3">
        <Skeleton className="h-10 w-full" />
        <div className="flex gap-3 h-[calc(100%-52px)]">
          <Skeleton className="h-full flex-1" />
          <Skeleton className="h-full w-[480px]" />
        </div>
      </div>
    );
  }

  const toggleSection = (key: string) => {
    setExpandedSections((prev) => {
      const next = { ...prev, [key]: !prev[key] };
      if (next[key]) {
        logAutoScrollRef.current[key] = true;
      }
      return next;
    });
  };

  const onSectionLogScroll = (key: string) => {
    const el = logViewportsRef.current[key];
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    logAutoScrollRef.current[key] = distance < 48;
  };

  return (
    <div className="h-full min-h-0 flex gap-3 p-3">
        <Card className="flex-1 min-h-0 overflow-hidden flex flex-col rounded-none">
          <CardContent className="p-0 min-h-0 flex-1">
            {execution.terminal_id ? (
              <SkillRunTerminal
                terminalId={execution.terminal_id}
                interventionLocked={execution.intervention_locked}
              />
            ) : (
              <div className="h-full flex items-center justify-center text-sm text-muted-foreground">
                No terminal attached.
              </div>
            )}
          </CardContent>
        </Card>

        <AnimatePresence initial={false}>
          {rightSidebarOpen ? (
            <motion.div
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 480, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ duration: 0.2, ease: "easeInOut" }}
              className="min-h-0 overflow-hidden"
            >
              <Card className="h-full min-h-0 overflow-hidden flex flex-col rounded-none">
                <CardContent className="p-0 min-h-0 flex-1">
                  <div className="h-full flex flex-col min-h-0">
                    <div className="flex-1 min-h-0 overflow-auto select-text">
	                    {(() => {
	                      const runLogs = logsByStep.get(RUN_SECTION_KEY) ?? [];
	                      const isOpen = !!expandedSections[RUN_SECTION_KEY];
	                      const headerProgress = null;
	                      return (
	                        <div className="border-b border-border/40">
	                    <button
	                      type="button"
	                      onClick={() => toggleSection(RUN_SECTION_KEY)}
                      style={accentStyle}
                      className={cn(
                        "w-full text-left flex items-center gap-2 px-3 h-7 transition-colors border-l-2",
                        "bg-[rgb(var(--skill-accent)/0.08)] hover:bg-[rgb(var(--skill-accent)/0.12)]",
                        isOpen && "bg-[rgb(var(--skill-accent)/0.16)]"
                      )}
                    >
                      <div className="flex items-center">
                        <StepStatusDot status="success" />
                      </div>
	                            <div className="min-w-0 flex-1">
	                              <div className="flex items-center justify-between gap-2">
	                                {headerProgress ? (
	                                  <div
	                                    className="text-[10px] font-mono text-muted-foreground truncate"
	                                    title={headerProgress}
	                                  >
	                                    {headerProgress}
	                                  </div>
	                                ) : (
	                                  <div className="text-xs font-medium truncate" title="run: system logs">
	                                    run: system logs
	                                  </div>
	                                )}
	                                <div className="flex items-center gap-2">
	                                  <div className="text-[10px] text-muted-foreground tabular-nums">{runLogs.length}</div>
	                                  <ChevronDown
	                                    className={cn(
	                                      "size-4 text-muted-foreground transition-transform",
	                                      isOpen && "rotate-180"
                                    )}
                                  />
                                </div>
                              </div>
                            </div>
                          </button>
                          <AnimatePresence initial={false}>
                            {isOpen ? (
                              <motion.div
                                initial={{ height: 0, opacity: 0 }}
                                animate={{ height: "auto", opacity: 1 }}
                                exit={{ height: 0, opacity: 0 }}
                                transition={{ duration: 0.15, ease: "easeOut" }}
                                className="overflow-hidden bg-muted/10"
                              >
	                                <div
	                                  ref={(el) => {
	                                    logViewportsRef.current[RUN_SECTION_KEY] = el;
	                                  }}
	                                  onScroll={() => onSectionLogScroll(RUN_SECTION_KEY)}
	                                  className="max-h-72 overflow-auto"
	                                >
	                                  {runLogs.length === 0 ? (
	                                    <div className="px-3 py-2 text-xs text-muted-foreground">
	                                      No logs yet.
	                                    </div>
	                                  ) : (
                                    runLogs.map((entry, idx) => (
                                      <div
                                        key={`${entry.timestamp}-${entry.stream}-${idx}`}
                                        className={cn(
                                          "px-3 py-2 even:bg-muted/5 select-text cursor-text",
                                          idx > 0 &&
                                            !(
                                              isMetaLogStream(runLogs[idx - 1].stream) &&
                                              isMetaLogStream(entry.stream)
                                            ) &&
                                            "border-t border-border/60"
                                        )}
                                      >
                                        <div className="flex items-center gap-2 text-[10px] text-muted-foreground font-mono tabular-nums select-text cursor-text">
                                          <span
                                            className={cn(
                                              "inline-flex items-center rounded border px-1.5 py-0.5 leading-none",
                                              streamBadgeClass(entry.stream)
                                            )}
                                          >
                                            {entry.stream}
                                          </span>
                                          <span>{formatLogTimestamp(entry.timestamp)}</span>
                                        </div>
                                        <pre className="mt-1 whitespace-pre-wrap break-words font-mono text-xs text-foreground/90 select-text cursor-text">
                                          {normalizeLogMessage(entry.message)}
                                        </pre>
                                      </div>
                                    ))
                                  )}
                                </div>
                              </motion.div>
                            ) : null}
                          </AnimatePresence>
                        </div>
                      );
                    })()}

	                    {execution.steps.map((step) => {
	                      const stepLogs = logsByStep.get(step.step_id) ?? [];
	                      const isOpen = !!expandedSections[step.step_id];
	                      const headerProgress = execution.step_progress?.[step.step_id] ?? null;
	                      const defStep = skillStepsById.get(step.step_id);
	                      const title = formatStepTitleLine(
	                        step.step_id,
	                        defStep,
                        execution.variables ?? {},
                        execution.host_id,
                        hostNameById
                      );
                      const canSkip = step.status === "pending" || step.status === "waiting" || step.status === "skipped";
                      const stepBusy =
                        stepAction?.stepId === step.step_id ? stepAction.action : null;
                      const isSkipped = step.status === "skipped";
	                      return (
	                        <div key={step.step_id} className="border-b border-border/40 last:border-b-0">
	                    <button
	                      type="button"
	                      onClick={() => toggleSection(step.step_id)}
	                      style={accentStyle}
	                      className={cn(
	                        "w-full text-left flex items-center gap-2 px-3 h-9 transition-colors border-l-2",
	                        "group",
	                        "bg-[rgb(var(--skill-accent)/0.08)] hover:bg-[rgb(var(--skill-accent)/0.12)]",
	                        isOpen && "bg-[rgb(var(--skill-accent)/0.16)]"
	                      )}
	                    >
                      <div className="flex items-center">
                        <StepStatusDot status={step.status} />
                      </div>
	                            <div className="min-w-0 flex-1">
	                              <div className="flex items-center justify-between gap-2">
	                                <div className="min-w-0 flex-1">
	                                  <div
	                                    className={cn(
	                                      "text-xs font-medium truncate",
	                                      isSkipped && "text-muted-foreground line-through"
	                                    )}
	                                    title={title}
	                                  >
	                                    {title}
	                                  </div>
	                                  {headerProgress ? (
	                                    <div
	                                      className="mt-0.5 text-[10px] font-mono text-muted-foreground truncate"
	                                      title={headerProgress}
	                                    >
	                                      {headerProgress}
	                                    </div>
	                                  ) : null}
	                                </div>
	                                <div className="flex items-center gap-2">
	                                  <div
	                                    className={cn(
	                                      "flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity",
                                      isOpen && "opacity-100"
                                    )}
                                    onClick={(e) => e.stopPropagation()}
                                  >
                                    <Button
                                      type="button"
                                      size="icon"
                                      variant="ghost"
                                      className="h-6 w-6 p-0"
                                      onClick={() => {
                                        setStepAction({ stepId: step.step_id, action: "rerun" });
                                        void doRestart(step.step_id).finally(() => setStepAction(null));
                                      }}
                                      disabled={action !== null || stepBusy !== null}
                                      aria-label="Rerun from this step"
                                      title="Rerun from this step"
                                    >
                                      {stepBusy === "rerun" ? (
                                        <Loader2 className="size-4 animate-spin" />
                                      ) : (
                                        <RotateCcw className="size-3.5" />
                                      )}
                                    </Button>

                                    <Button
                                      type="button"
                                      size="icon"
                                      variant="ghost"
                                      className="h-6 w-6 p-0"
                                      onClick={() => void doToggleSkipStep(step.step_id)}
                                      disabled={!canSkip || action !== null || stepBusy !== null}
                                      aria-pressed={isSkipped}
                                      aria-label="Skip this step"
                                      title={canSkip ? "Skip this step" : "Only pending/waiting steps can be skipped"}
                                    >
                                      {stepBusy === "skip" ? (
                                        <Loader2 className="size-4 animate-spin" />
                                      ) : (
                                        <SkipForward className={cn("size-3.5", isSkipped && "text-primary")} />
                                      )}
                                    </Button>

                                    <DropdownMenu>
                                      <DropdownMenuTrigger asChild>
                                        <Button
                                          type="button"
                                          size="icon"
                                          variant="ghost"
                                          className="h-6 w-6 p-0"
                                          aria-label="More step actions"
                                          title="More"
                                        >
                                          <MoreHorizontal className="size-3.5" />
                                        </Button>
                                      </DropdownMenuTrigger>
                                      <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                                        <DropdownMenuItem onClick={() => void copyText(step.step_id)}>
                                          Copy step id
                                        </DropdownMenuItem>
                                        <DropdownMenuItem onClick={() => void copyText(title)}>
                                          Copy step title
                                        </DropdownMenuItem>
                                      </DropdownMenuContent>
                                    </DropdownMenu>
                                  </div>
                                  {step.status === "running" ? (
                                    <span className="h-5 inline-flex items-center rounded border border-primary/20 bg-primary/10 px-1.5 text-[10px] font-mono leading-none text-primary">
                                      Running
                                    </span>
	                                  ) : step.status === "skipped" ? (
	                                    <span className="h-5 inline-flex items-center rounded border border-muted-foreground/30 bg-muted/40 px-1.5 text-[10px] font-mono leading-none text-muted-foreground">
	                                      Skipped
	                                    </span>
	                                  ) : null}
	                                  <div className="text-[10px] text-muted-foreground tabular-nums">
	                                    {stepLogs.length}
	                                  </div>
	                                  <ChevronDown
                                    className={cn(
                                      "size-4 text-muted-foreground transition-transform",
                                      isOpen && "rotate-180"
                                    )}
                                  />
                                </div>
                              </div>
                            </div>
                          </button>

                          <AnimatePresence initial={false}>
                            {isOpen ? (
                              <motion.div
                                initial={{ height: 0, opacity: 0 }}
                                animate={{ height: "auto", opacity: 1 }}
                                exit={{ height: 0, opacity: 0 }}
                                transition={{ duration: 0.15, ease: "easeOut" }}
                                className="overflow-hidden bg-muted/10"
                              >
                                <div
	                                  ref={(el) => {
	                                    logViewportsRef.current[step.step_id] = el;
	                                  }}
	                                  onScroll={() => onSectionLogScroll(step.step_id)}
	                                  className="max-h-72 overflow-auto"
	                                >
	                                  {execution.step_progress?.[step.step_id] ? (
	                                    <div className="px-3 py-2 bg-muted/10 border-b border-border/60">
	                                      <div className="flex items-center gap-2 text-[10px] text-muted-foreground font-mono tabular-nums select-text cursor-text">
	                                        <span className="inline-flex items-center rounded border px-1.5 py-0.5 leading-none bg-primary/10 text-primary border-primary/20">
	                                          progress
	                                        </span>
	                                      </div>
	                                      <pre className="mt-1 whitespace-pre-wrap break-words font-mono text-xs text-foreground/90 select-text cursor-text">
	                                        {execution.step_progress?.[step.step_id]}
	                                      </pre>
	                                    </div>
	                                  ) : null}
	                                  {stepLogs.length === 0 ? (
	                                    <div className="px-3 py-2 text-xs text-muted-foreground">
	                                      No logs yet.
	                                    </div>
	                                  ) : (
                                    stepLogs.map((entry, idx) => (
                                      <div
                                        key={`${entry.timestamp}-${entry.stream}-${idx}`}
                                        className={cn(
                                          "px-3 py-2 even:bg-muted/5 select-text cursor-text",
                                          idx > 0 &&
                                            !(
                                              isMetaLogStream(stepLogs[idx - 1].stream) &&
                                              isMetaLogStream(entry.stream)
                                            ) &&
                                            "border-t border-border/60"
                                        )}
                                      >
                                        <div className="flex items-center gap-2 text-[10px] text-muted-foreground font-mono tabular-nums select-text cursor-text">
                                          <span
                                            className={cn(
                                              "inline-flex items-center rounded border px-1.5 py-0.5 leading-none",
                                              streamBadgeClass(entry.stream)
                                            )}
                                          >
                                            {entry.stream}
                                          </span>
                                          <span>{formatLogTimestamp(entry.timestamp)}</span>
                                        </div>
                                        <pre className="mt-1 whitespace-pre-wrap break-words font-mono text-xs text-foreground/90 select-text cursor-text">
                                          {normalizeLogMessage(entry.message)}
                                        </pre>
                                      </div>
                                    ))
                                  )}
                                </div>
                              </motion.div>
                            ) : null}
                          </AnimatePresence>
                        </div>
                      );
                    })}
                    </div>

	                    <div className="shrink-0 border-t border-border bg-background/60 backdrop-blur">
	                      <div className="flex items-center gap-2 px-2 py-2">
	                        <Button
	                          type="button"
	                          size="sm"
	                          variant="outline"
	                          onClick={() => void doRestart(null)}
	                          disabled={action !== null}
	                          className="h-7 px-2 text-xs gap-1.5"
	                        >
	                          {action === "restart" ? (
	                            <Loader2 className="size-3.5 animate-spin" />
	                          ) : (
	                            <RotateCcw className="size-3.5" />
	                          )}
	                          Restart
	                        </Button>
	                        <Button
	                          type="button"
	                          size="sm"
	                          variant="outline"
	                          onClick={() => void doReconnectTerminal()}
	                          disabled={!canReconnect || action !== null}
	                          className="h-7 px-2 text-xs gap-1.5"
	                          title={canReconnect ? "Reconnect terminal" : "Reconnect is available before starting the skill"}
	                        >
	                          {action === "reconnect" ? (
	                            <Loader2 className="size-3.5 animate-spin" />
	                          ) : (
	                            <Cable className="size-3.5" />
	                          )}
	                          Reconnect
	                        </Button>
	
	                        <div className="flex-1" />

                        {isPending ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="default"
                            onClick={() => void doStart()}
                            disabled={action !== null}
                            className="h-7 px-2 text-xs gap-1.5"
                          >
                            {action === "start" ? (
                              <Loader2 className="size-3.5 animate-spin" />
                            ) : null}
                            Start
                          </Button>
                        ) : (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => void doInterrupt()}
                            disabled={!canCancel || action !== null}
                            className="h-7 px-2 text-xs gap-1.5"
                          >
                            {action === "interrupt" ? (
                              <Loader2 className="size-3.5 animate-spin" />
                            ) : (
                              <Square className="size-3.5" />
                            )}
                            Ctrl+C
                          </Button>
                        )}

                        {!isPending && canPause ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => void doPause()}
                            disabled={action !== null}
                            className="h-7 px-2 text-xs gap-1.5"
                          >
                            {action === "pause" ? (
                              <Loader2 className="size-3.5 animate-spin" />
                            ) : (
                              <Pause className="size-3.5" />
                            )}
                            Pause
                          </Button>
                        ) : null}

                        {!isPending && canResume ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => void doResume()}
                            disabled={action !== null}
                            className="h-7 px-2 text-xs gap-1.5"
                          >
                            {action === "resume" ? (
                              <Loader2 className="size-3.5 animate-spin" />
                            ) : (
                              <Play className="size-3.5" />
                            )}
                            Resume
                          </Button>
                        ) : null}

                        <Button
                          type="button"
                          size="sm"
                          variant="destructive"
                          onClick={() => void doCancel()}
                          disabled={!canCancel || action !== null}
                          className="h-7 px-2 text-xs gap-1.5"
                        >
                          {action === "cancel" ? (
                            <Loader2 className="size-3.5 animate-spin" />
                          ) : (
                            <X className="size-3.5" />
                          )}
                          Cancel
                        </Button>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          ) : null}
        </AnimatePresence>
    </div>
  );
}

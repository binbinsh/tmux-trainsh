import "@xterm/xterm/css/xterm.css";
import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { type ISearchOptions } from "@xterm/addon-search";
import { TerminalInstance } from "@/lib/terminal-instance";
import { DEFAULT_TERMINAL_THEME, type TerminalThemeName } from "@/lib/terminal-themes";
import { useQuery } from "@tanstack/react-query";
import {
  getConfig,
  interactiveSkillApi,
  hostApi,
  sshCheck,
  termOpenSshTmux,
  termOpenLocal,
  useHosts,
  useInteractiveExecutions,
  useVastInstances,
  vastAttachSshKey,
  vastGetInstance,
  type RemoteTmuxSession,
} from "@/lib/tauri-api";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { useTerminal } from "@/contexts/TerminalContext";
import { AnimatePresence, motion } from "framer-motion";
import { TmuxSessionSelectModal } from "@/components/host/TmuxSessionSelectModal";
import { copyText } from "@/lib/clipboard";
import { AppIcon, type AppIconName } from "@/components/AppIcon";
import { EmptyHostState, HostRow, HostSection } from "@/components/shared/HostCard";
import { SkillRunSidebar } from "@/components/skill/SkillRunSidebar";
import { formatGpuCountLabel } from "@/lib/gpu";
import {
  loadRecentConnections,
  removeRecentConnection,
  saveRecentConnections,
  upsertRecentConnection,
  type RecentConnection,
} from "@/lib/terminal-recents";
import type { InteractiveExecution, InteractiveStatus, VastInstance } from "@/lib/types";
import { Button, Input, Card, CardContent, Badge } from "@/components/ui";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { Search, ChevronUp, ChevronDown, X, Terminal as TerminalIcon, Server, Folder, Play, Pencil, Trash2, Copy, Check, Loader2 } from "lucide-react";

// Split pane types
type SplitDirection = "horizontal" | "vertical";

interface SplitPane {
  id: string;
  terminalId: string;
}

interface SplitConfig {
  direction: SplitDirection;
  panes: SplitPane[];
}

interface TerminalPaneProps {
  id: string;
  active: boolean;
  searchQuery: string;
  onSearchResult: (current: number, total: number) => void;
  searchDirection: "next" | "prev" | null;
  onSearchComplete: () => void;
  skillExecutionId?: string | null;
  interventionLocked?: boolean;
  themeName?: TerminalThemeName;
  onClose: () => void;
  // Split pane support
  splitConfig?: SplitConfig | null;
  onSplit?: (direction: SplitDirection) => void;
  onUnsplit?: () => void;
  isSplit?: boolean;
}

// Search options for terminal search
const DEFAULT_SEARCH_OPTIONS: ISearchOptions = {
  regex: false,
  wholeWord: false,
  caseSensitive: false,
  incremental: true,
  decorations: {
    matchBackground: "#ffe79280",
    matchBorder: "#fd971f",
    matchOverviewRuler: "#fd971f",
    activeMatchBackground: "#f25a00",
    activeMatchBorder: "#000000",
    activeMatchColorOverviewRuler: "#f25a00",
  },
};

/**
 * Optimized terminal pane using TerminalInstance class
 * Key improvements over the previous implementation:
 * 1. Uses TerminalInstance with ~4ms input buffering (vs ~16ms RAF)
 * 2. ~8ms output rendering throttle (vs 33ms)
 * 3. Proper Unicode11 support for emoji/CJK
 * 4. Better WebGL fallback handling
 */
function TerminalPane(props: TerminalPaneProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const instanceRef = useRef<TerminalInstance | null>(null);

  // Track intervention lock state changes
  useEffect(() => {
    if (instanceRef.current) {
      instanceRef.current.setInterventionLocked(props.interventionLocked ?? false);
    }
  }, [props.interventionLocked]);

  // Handle search query changes
  useEffect(() => {
    if (!instanceRef.current) return;

    if (props.searchQuery) {
      instanceRef.current.search(props.searchQuery, DEFAULT_SEARCH_OPTIONS);
    } else {
      instanceRef.current.clearSearch();
    }
  }, [props.searchQuery]);

  // Handle search direction (next/prev)
  useEffect(() => {
    if (!instanceRef.current || !props.searchQuery || !props.searchDirection) return;

    if (props.searchDirection === "next") {
      instanceRef.current.findNext(props.searchQuery, DEFAULT_SEARCH_OPTIONS);
    } else {
      instanceRef.current.findPrevious(props.searchQuery, DEFAULT_SEARCH_OPTIONS);
    }
    props.onSearchComplete();
  }, [props.searchDirection, props.searchQuery, props.onSearchComplete]);

  // Initialize terminal instance
  useEffect(() => {
    const container = hostRef.current;
    if (!container) return;
    if (instanceRef.current) return;

    const instance = new TerminalInstance({
      id: props.id,
      container,
      interventionLocked: props.interventionLocked,
      themeName: props.themeName,
      onSearchResult: props.onSearchResult,
      onExit: () => {
        // Session ended - could trigger auto-close here if desired
      },
    });

    instanceRef.current = instance;

    // Initialize asynchronously
    void instance.initialize();

    return () => {
      instance.dispose();
      instanceRef.current = null;
    };
  }, [props.id]);

  // Handle theme changes
  useEffect(() => {
    if (instanceRef.current && props.themeName) {
      instanceRef.current.setTheme(props.themeName);
    }
  }, [props.themeName]);

  // Handle active state changes
  useEffect(() => {
    if (props.active && instanceRef.current) {
      void instanceRef.current.activate();
    }
  }, [props.active, props.id]);

  return <div ref={hostRef} className="h-full w-full bg-card overflow-hidden absolute inset-0" />;
}

function getErrorMessage(error: unknown): string {
  if (typeof error === "string") return error;
  if (typeof error === "object" && error !== null && "message" in error && typeof (error as { message: unknown }).message === "string") {
    return (error as { message: string }).message;
  }
  return String(error);
}

function extractErrorCode(message: string): string | null {
  const patterns = [
    /code=Some\((\d+)\)/,
    /\bcode=(\d+)\b/,
    /\bexit\s*code[:=]\s*(\d+)\b/i,
  ];
  for (const pattern of patterns) {
    const match = message.match(pattern);
    if (match?.[1]) return match[1];
  }
  return null;
}

function getVastLabel(inst: VastInstance): string {
  return inst.label?.trim() || `vast #${inst.id}`;
}

function isVastInstanceOnline(inst: VastInstance): boolean {
  const v = (inst.actual_status ?? "").toLowerCase();
  return v.includes("running") || v.includes("active") || v.includes("online");
}

function getExecutionStatusLabel(status: InteractiveStatus): string {
  switch (status) {
    case "pending": return "Pending";
    case "connecting": return "Connecting";
    case "running": return "Running";
    case "waiting_for_input": return "Waiting";
    case "paused": return "Paused";
    case "completed": return "Completed";
    case "failed": return "Failed";
    case "cancelled": return "Cancelled";
    default: return status;
  }
}

function getExecutionTagVariant(status: InteractiveStatus): "default" | "secondary" | "warning" | "destructive" {
  switch (status) {
    case "running":
    case "waiting_for_input":
      return "default";
    case "paused":
    case "connecting":
    case "pending":
      return "warning";
    case "failed":
      return "destructive";
    default:
      return "secondary";
  }
}

function CopyIconButton({ text, tooltip }: { text: string; tooltip: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await copyText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={handleCopy}>
          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{copied ? "Copied!" : tooltip}</TooltipContent>
    </Tooltip>
  );
}

export function TerminalPage() {
  const navigate = useNavigate();
  const search = useSearch({ from: "/terminal" }) as {
    connectHostId?: string;
    connectVastInstanceId?: string;
    connectLabel?: string;
  };
  const {
    sessions,
    activeId,
    setActiveId,
    openLocalTerminal,
    closeSession,
    refreshSessions,
    isLoading,
    workspaceVisible,
    setWorkspaceVisible,
    removeCurrentPlaceholder,
    createNewTab,
  } = useTerminal();
  const hostsQuery = useHosts();
  const vastQuery = useVastInstances();
  const executionsQuery = useInteractiveExecutions();
  const [isPreparingSkill, setIsPreparingSkill] = useState(false);

  // Fetch terminal theme from config
  const configQuery = useQuery({
    queryKey: ["config"],
    queryFn: getConfig,
  });
  const terminalTheme = configQuery.data?.terminal?.theme ?? DEFAULT_TERMINAL_THEME;

  const [connectState, setConnectState] = useState<
    | { status: "idle" }
    | { status: "connecting"; label: string; detail?: string | null }
    | { status: "select_tmux"; label: string }
    | { status: "error"; label?: string | null; message: string }
  >({ status: "idle" });
  const [launcherQuery, setLauncherQuery] = useState("");
  const [launcherError, setLauncherError] = useState<string | null>(null);
  const [recentConnections, setRecentConnections] = useState<RecentConnection[]>(() => loadRecentConnections());
  const [selectedRecentId, setSelectedRecentId] = useState<string | null>(null);
  const [selectedSkillPath, setSelectedSkillPath] = useState<string | null>(null);

  const [tmuxSelect, setTmuxSelect] = useState<{
    kind: "host" | "vast";
    hostId: string | null;
    vastInstanceId: number | null;
    hostName: string;
    ssh: { host: string; port: number; user: string; keyPath?: string | null; extraArgs?: string[] };
    envVars: Record<string, string> | null;
    sessions: RemoteTmuxSession[];
  } | null>(null);

  function persistRecentConnections(updater: (prev: RecentConnection[]) => RecentConnection[]) {
    setRecentConnections((prev) => {
      const next = updater(prev);
      saveRecentConnections(next);
      return next;
    });
  }

  function recordLocalConnection() {
    persistRecentConnections((prev) =>
      upsertRecentConnection(prev, { id: "__local__", kind: "local", label: "Local" })
    );
  }

  function recordHostConnection(hostId: string, label: string) {
    persistRecentConnections((prev) =>
      upsertRecentConnection(prev, { id: `host:${hostId}` as `host:${string}`, kind: "host", host_id: hostId, label })
    );
  }

  function recordVastConnection(instanceId: number, label: string) {
    persistRecentConnections((prev) =>
      upsertRecentConnection(prev, { id: `vast:${instanceId}` as `vast:${number}`, kind: "vast", vast_instance_id: instanceId, label })
    );
  }

  const connectHandledRef = useRef<string | null>(null);
  const pendingConnectKey =
    typeof search.connectHostId === "string"
      ? `host:${search.connectHostId}`
      : typeof search.connectVastInstanceId === "string"
        ? `vast:${search.connectVastInstanceId}`
        : null;
  const shouldShowConnectUi =
    connectState.status !== "idle" ||
    (pendingConnectKey != null && connectHandledRef.current !== pendingConnectKey);
  const pendingConnectLabel =
    typeof search.connectLabel === "string" && search.connectLabel.trim()
      ? search.connectLabel
      : typeof search.connectHostId === "string"
        ? "Connecting to host…"
        : typeof search.connectVastInstanceId === "string"
          ? "Connecting to Vast…"
          : "Connecting…";
  const connectErrorCode =
    connectState.status === "error" ? extractErrorCode(connectState.message) : null;
  const hosts = hostsQuery.data ?? [];
  const vastInstances = vastQuery.data ?? [];
  const executions = executionsQuery.data ?? [];

  const filteredRecentConnections = useMemo(() => {
    const needle = launcherQuery.trim().toLowerCase();
    if (!needle) return recentConnections;

    return recentConnections.filter((conn) => {
      const tokens: string[] = [conn.label];
      if (conn.kind === "host") {
        const host = hosts.find((h) => h.id === conn.host_id) ?? null;
        if (host?.ssh) tokens.push(`${host.ssh.user}@${host.ssh.host}:${host.ssh.port}`);
      }
      if (conn.kind === "vast") tokens.push(String(conn.vast_instance_id));
      return tokens.join(" ").toLowerCase().includes(needle);
    });
  }, [hosts, launcherQuery, recentConnections]);

  useEffect(() => {
    if (!selectedRecentId) return;
    if (!filteredRecentConnections.some((c) => c.id === selectedRecentId)) {
      setSelectedRecentId(null);
    }
  }, [filteredRecentConnections, selectedRecentId]);

  const skillHistory = useMemo(() => {
    const sorted = [...executions].sort((a, b) => b.created_at.localeCompare(a.created_at));
    const seen = new Set<string>();
    const out: InteractiveExecution[] = [];
    for (const exec of sorted) {
      if (seen.has(exec.skill_path)) continue;
      seen.add(exec.skill_path);
      out.push(exec);
      if (out.length >= 12) break;
    }

    const needle = launcherQuery.trim().toLowerCase();
    if (!needle) return out;
    return out.filter((exec) => {
      const haystack = `${exec.skill_name} ${exec.skill_path} ${exec.host_id} ${exec.status}`.toLowerCase();
      return haystack.includes(needle);
    });
  }, [executions, launcherQuery]);

  useEffect(() => {
    if (!selectedSkillPath) return;
    if (!skillHistory.some((e) => e.skill_path === selectedSkillPath)) {
      setSelectedSkillPath(null);
    }
  }, [skillHistory, selectedSkillPath]);

  const hostNameById = useMemo(() => {
    const map = new Map<string, string>();
    map.set("__local__", "Local");
    for (const h of hosts) map.set(h.id, h.name);
    for (const inst of vastInstances) map.set(`vast:${inst.id}`, getVastLabel(inst));
    return map;
  }, [hosts, vastInstances]);

  const launcherIsLoading = hostsQuery.isLoading || vastQuery.isLoading || executionsQuery.isLoading;

  const selectedRecent = useMemo(() => {
    if (!selectedRecentId) return null;
    return recentConnections.find((c) => c.id === selectedRecentId) ?? null;
  }, [recentConnections, selectedRecentId]);

  const selectedExecution = useMemo(() => {
    if (!selectedSkillPath) return null;
    return skillHistory.find((e) => e.skill_path === selectedSkillPath) ?? null;
  }, [skillHistory, selectedSkillPath]);

  function parseVastHostId(hostId: string): number | null {
    if (!hostId.startsWith("vast:")) return null;
    const n = Number(hostId.slice("vast:".length));
    if (!Number.isFinite(n) || n <= 0) return null;
    return n;
  }

  function recordConnectionByHostId(hostId: string) {
    if (hostId === "__local__") {
      recordLocalConnection();
      return;
    }

    const vastId = parseVastHostId(hostId);
    if (vastId != null) {
      recordVastConnection(vastId, hostNameById.get(`vast:${vastId}`) ?? `vast #${vastId}`);
      return;
    }

    recordHostConnection(hostId, hostNameById.get(hostId) ?? hostId);
  }

  const launchLocalTerminal = useCallback(async () => {
    setLauncherError(null);
    removeCurrentPlaceholder();
    setActiveId(null);
    setWorkspaceVisible(false);
    await openLocalTerminal();
    recordLocalConnection();
  }, [openLocalTerminal, removeCurrentPlaceholder, setActiveId, setWorkspaceVisible]);

  const launchExecution = useCallback(async (exec: InteractiveExecution) => {
    setLauncherError(null);
    removeCurrentPlaceholder();
    setActiveId(null);
    setWorkspaceVisible(false);

    try {
      const variables: Record<string, string> = { ...(exec.variables ?? {}) };
      if (exec.host_id && exec.host_id !== "__local__" && variables.target == null) {
        variables.target = exec.host_id;
      }

      setIsPreparingSkill(true);
      const execution = await interactiveSkillApi.prepare({
        path: exec.skill_path,
        hostId: exec.host_id,
        variables,
      });
      recordConnectionByHostId(execution.host_id);
      navigate({ to: "/skills/runs/$id", params: { id: execution.id } });
    } catch (e) {
      console.error("Failed to run skill from terminal launcher:", e);
      setLauncherError(getErrorMessage(e));
    } finally {
      setIsPreparingSkill(false);
    }
  }, [navigate, removeCurrentPlaceholder, setActiveId, setWorkspaceVisible]);

  const launcherPrimaryLabel = selectedSkillPath ? "Run" : "Connect";
  const canLauncherPrimary = Boolean(selectedSkillPath ? selectedExecution : selectedRecent);
  const launcherPrimaryLoading = selectedSkillPath ? isPreparingSkill : false;

  const [showSearch, setShowSearch] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResult, setSearchResult] = useState({ current: 0, total: 0 });
  const [searchDirection, setSearchDirection] = useState<"next" | "prev" | null>(null);
  const [skillSidebarOpen, setSkillSidebarOpen] = useState(true);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const showSearchRef = useRef(showSearch);

  // Get the skillExecutionId for the active session
  const activeSession = sessions.find((s) => s.id === activeId);
  const activeSkillExecutionId = activeSession?.skillExecutionId ?? null;

  useEffect(() => {
    showSearchRef.current = showSearch;
  }, [showSearch]);

  // Listen for skill sidebar toggle event from TitleBar
  useEffect(() => {
    const onToggle = () => setSkillSidebarOpen((prev) => !prev);
    window.addEventListener("skillrun:toggle_right_sidebar", onToggle as EventListener);
    return () => window.removeEventListener("skillrun:toggle_right_sidebar", onToggle as EventListener);
  }, []);

  useEffect(() => {
    void refreshSessions();
  }, [refreshSessions]);

  const openSshTmux = useCallback(
    async (params: {
      ssh: { host: string; port: number; user: string; keyPath?: string | null; extraArgs?: string[] };
      tmuxSession: string;
      title: string;
      envVars?: Record<string, string> | null;
    }) => {
      await termOpenSshTmux({
        ssh: {
          host: params.ssh.host,
          port: params.ssh.port,
          user: params.ssh.user,
          keyPath: params.ssh.keyPath ?? null,
          extraArgs: params.ssh.extraArgs ?? [],
        },
        tmuxSession: params.tmuxSession,
        title: params.title,
        cols: 120,
        rows: 32,
        envVars: params.envVars ?? null,
      });
      await refreshSessions();
    },
    [refreshSessions]
  );

  const connectToSavedHost = useCallback(
    async (hostId: string, label?: string) => {
      removeCurrentPlaceholder();
      setConnectState({ status: "connecting", label: label ?? "Connecting…", detail: "Fetching host info…" });
      setTmuxSelect(null);
      setActiveId(null);
      setWorkspaceVisible(false);

      const host = await hostApi.get(hostId);
      if (!host.ssh) {
        throw new Error("No SSH configuration for this host");
      }

      const ssh = {
        host: host.ssh.host,
        port: host.ssh.port,
        user: host.ssh.user,
        keyPath: host.ssh.keyPath ?? host.ssh.key_path ?? null,
        extraArgs: host.ssh.extraArgs ?? host.ssh.extra_args ?? [],
      };

      let tmuxSessions: RemoteTmuxSession[] = [];
      try {
        setConnectState({ status: "connecting", label: host.name, detail: "Checking tmux sessions…" });
        tmuxSessions = await hostApi.listTmuxSessions(hostId);
      } catch (e) {
        console.error("Failed to list tmux sessions:", e);
        tmuxSessions = [];
      }

      if (tmuxSessions.length >= 1) {
        setTmuxSelect({
          kind: "host",
          hostId,
          vastInstanceId: null,
          hostName: host.name,
          ssh,
          envVars: host.env_vars ?? null,
          sessions: tmuxSessions,
        });
        setConnectState({ status: "select_tmux", label: host.name });
        return;
      }

      const sessionName = "main";
      setConnectState({ status: "connecting", label: host.name, detail: `Connecting to tmux: ${sessionName}` });
      await openSshTmux({
        ssh,
        tmuxSession: sessionName,
        title: `${host.name} · ${sessionName}`,
        envVars: host.env_vars ?? null,
      });
      recordHostConnection(hostId, host.name);
      setConnectState({ status: "idle" });
    },
    [openSshTmux, removeCurrentPlaceholder, setActiveId]
  );

  const connectToVastInstance = useCallback(
    async (instanceId: number, label?: string) => {
      removeCurrentPlaceholder();
      setConnectState({ status: "connecting", label: label ?? `Vast #${instanceId}`, detail: "Loading Vast instance…" });
      setTmuxSelect(null);
      setActiveId(null);
      setWorkspaceVisible(false);

      const cfg = await getConfig();
      if (!cfg.vast.ssh_key_path) {
        throw new Error("Missing Vast SSH key path. Configure it in Settings → Vast.ai → SSH Key Path.");
      }

      const instance = await vastGetInstance(instanceId);

      const vastUser = cfg.vast.ssh_user?.trim() || "root";
      setConnectState({ status: "connecting", label: label ?? `Vast #${instanceId}`, detail: "Attaching SSH key…" });
      const keyPath = await vastAttachSshKey(instanceId, cfg.vast.ssh_key_path);

      await new Promise((r) => setTimeout(r, 1200));

      const sshExtraArgs = [
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "PreferredAuthentications=publickey",
        "-o",
        "PasswordAuthentication=no",
        "-o",
        "BatchMode=yes",
      ];

      const rawSshPort = instance.ssh_port ?? null;
      const directHost = instance.public_ipaddr?.trim() || null;
      const directPort = instance.machine_dir_ssh_port ?? null;

      const sshIdx = instance.ssh_idx ?? null;
      const normalizedSshIdx = sshIdx
        ? sshIdx.startsWith("ssh")
          ? sshIdx
          : `ssh${sshIdx}`
        : null;

      const proxyHostFromApi = instance.ssh_host ?? null;
      const vastProxyHost = proxyHostFromApi?.includes("vast.ai")
        ? proxyHostFromApi
        : normalizedSshIdx
          ? `${normalizedSshIdx}.vast.ai`
          : null;
      const proxyHost = (vastProxyHost ?? proxyHostFromApi)?.trim() || null;
      const proxyPort = rawSshPort != null ? rawSshPort : null;

      const candidates: Array<{ mode: "proxy" | "direct"; host: string; port: number }> = [];
      const addCandidate = (mode: "proxy" | "direct") => {
        if (mode === "proxy") {
          if (proxyHost && proxyPort) candidates.push({ mode, host: proxyHost, port: proxyPort });
          return;
        }
        if (directHost && directPort) candidates.push({ mode, host: directHost, port: directPort });
      };

      const pref = cfg.vast.ssh_connection_preference === "direct" ? "direct" : "proxy";
      addCandidate(pref);
      addCandidate(pref === "direct" ? "proxy" : "direct");

      if (candidates.length === 0) {
        throw new Error("No available SSH route for this instance (proxy/direct SSH not available yet).");
      }

      let lastError: unknown = null;
      for (const cand of candidates) {
        try {
          setConnectState({
            status: "connecting",
            label: label ?? `Vast #${instanceId}`,
            detail: `Checking SSH (${cand.mode})…`,
          });
          const ssh = { host: cand.host, port: cand.port, user: vastUser, keyPath, extraArgs: sshExtraArgs };
          await sshCheck(ssh);

          setConnectState({
            status: "connecting",
            label: label ?? `Vast #${instanceId}`,
            detail: "Checking tmux sessions…",
          });

          let tmuxSessions: RemoteTmuxSession[] = [];
          try {
            tmuxSessions = await hostApi.listTmuxSessionsBySsh(ssh);
          } catch (e) {
            console.error("Failed to list tmux sessions:", e);
            tmuxSessions = [];
          }

          if (tmuxSessions.length >= 1) {
            setTmuxSelect({
              kind: "vast",
              hostId: null,
              vastInstanceId: instanceId,
              hostName: label ?? `Vast #${instanceId}`,
              ssh,
              envVars: null,
              sessions: tmuxSessions,
            });
            setConnectState({ status: "select_tmux", label: label ?? `Vast #${instanceId}` });
            return;
          }

          setConnectState({
            status: "connecting",
            label: label ?? `Vast #${instanceId}`,
            detail: "Opening terminal…",
          });
          await openSshTmux({
            ssh,
            tmuxSession: "main",
            title: `${label ?? `Vast #${instanceId}`} · main`,
            envVars: null,
          });
          recordVastConnection(instanceId, label ?? `Vast #${instanceId}`);
          setConnectState({ status: "idle" });
          return;
        } catch (e) {
          lastError = e;
        }
      }

      throw lastError ?? new Error("SSH connection failed");
    },
    [openSshTmux, removeCurrentPlaceholder, setActiveId]
  );

  const launchRecentConnection = useCallback(async (conn: RecentConnection) => {
    setLauncherError(null);
    if (conn.kind === "local") {
      await launchLocalTerminal();
      return;
    }

    try {
      if (conn.kind === "host") {
        const vastId = parseVastHostId(conn.host_id);
        if (vastId != null) {
          await connectToVastInstance(vastId, hostNameById.get(`vast:${vastId}`) ?? conn.label);
          return;
        }
        await connectToSavedHost(conn.host_id, hostNameById.get(conn.host_id) ?? conn.label);
        return;
      }

      await connectToVastInstance(conn.vast_instance_id, hostNameById.get(`vast:${conn.vast_instance_id}`) ?? conn.label);
    } catch (e) {
      setConnectState({ status: "error", label: conn.label, message: getErrorMessage(e) });
    }
  }, [connectToSavedHost, connectToVastInstance, hostNameById, launchLocalTerminal]);

  const handleLauncherPrimary = useCallback(async () => {
    if (selectedExecution) {
      await launchExecution(selectedExecution);
      return;
    }
    if (selectedRecent) {
      await launchRecentConnection(selectedRecent);
    }
  }, [launchExecution, launchRecentConnection, selectedExecution, selectedRecent]);

  useEffect(() => {
    const connectHostId = typeof search.connectHostId === "string" ? search.connectHostId : null;
    const connectVastIdStr =
      typeof search.connectVastInstanceId === "string" ? search.connectVastInstanceId : null;
    const connectLabel = typeof search.connectLabel === "string" ? search.connectLabel : null;

    const key = connectHostId ? `host:${connectHostId}` : connectVastIdStr ? `vast:${connectVastIdStr}` : null;
    if (!key || connectHandledRef.current === key) return;

    connectHandledRef.current = key;
    navigate({ to: "/terminal", search: { connectHostId: undefined, connectVastInstanceId: undefined, connectLabel: undefined }, replace: true });

    (async () => {
      try {
        if (connectHostId) {
          await connectToSavedHost(connectHostId, connectLabel ?? undefined);
        } else if (connectVastIdStr) {
          const instanceId = Number(connectVastIdStr);
          if (!Number.isFinite(instanceId) || instanceId <= 0) {
            throw new Error("Invalid Vast instance ID");
          }
          await connectToVastInstance(instanceId, connectLabel ?? undefined);
        }
      } catch (e) {
        setConnectState({ status: "error", label: connectLabel, message: getErrorMessage(e) });
      }
    })();
  }, [connectToSavedHost, connectToVastInstance, navigate, search.connectHostId, search.connectLabel, search.connectVastInstanceId]);

  const activeIdRef = useRef(activeId);
  useEffect(() => {
    activeIdRef.current = activeId;
  }, [activeId]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.metaKey && !e.ctrlKey && e.key === "f") {
        e.preventDefault();
        e.stopPropagation();
        setShowSearch((prev) => {
          if (!prev) {
            setTimeout(() => searchInputRef.current?.focus(), 50);
          } else {
            setSearchQuery("");
          }
          return !prev;
        });
        return;
      }

      if (e.metaKey && e.key === "]") {
        e.preventDefault();
        e.stopPropagation();
        setSkillSidebarOpen((prev) => !prev);
        return;
      }

      if (e.metaKey && e.key === "w") {
        e.preventDefault();
        e.stopPropagation();
        if (activeIdRef.current) {
          void closeSession(activeIdRef.current);
        }
        return;
      }

      if (e.metaKey && e.key === "t") {
        e.preventDefault();
        e.stopPropagation();
        createNewTab();
        return;
      }

      // Cmd+Enter: Quick launch local terminal (when in workspace/launcher view)
      if (e.metaKey && e.key === "Enter" && workspaceVisible) {
        e.preventDefault();
        e.stopPropagation();
        void openLocalTerminal();
        return;
      }

      if (e.key === "Escape" && showSearchRef.current) {
        e.preventDefault();
        e.stopPropagation();
        setShowSearch(false);
        setSearchQuery("");
      }
    };

    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, [closeSession, createNewTab, workspaceVisible, openLocalTerminal]);

  const handleSearchResult = useCallback((current: number, total: number) => {
    setSearchResult({ current, total });
  }, []);

  const handleSearchComplete = useCallback(() => {
    setSearchDirection(null);
  }, []);

  const handleFindNext = () => setSearchDirection("next");
  const handleFindPrev = () => setSearchDirection("prev");

  const handleCloseSearch = () => {
    setShowSearch(false);
    setSearchQuery("");
  };

  const handleSearchKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      if (e.shiftKey) {
        handleFindPrev();
      } else {
        handleFindNext();
      }
    }
  };

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-muted-foreground">Loading...</div>
      </div>
    );
  }

  return (
    <div className="h-full flex text-foreground">
      <div className="flex-1 flex flex-col min-w-0">
        <AnimatePresence>
          {showSearch && sessions.length > 0 && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="overflow-hidden bg-card/90 backdrop-blur-md border-b border-border"
            >
              <div className="flex items-center gap-2 px-3 py-2">
                <div className="relative max-w-xs">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                  <Input
                    ref={searchInputRef}
                    placeholder="Search in terminal..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onKeyDown={handleSearchKeyDown}
                    className="h-8 pl-9 pr-16"
                  />
                  <div className="absolute right-3 top-1/2 -translate-y-1/2">
                    {searchQuery && searchResult.total > 0 ? (
                      <span className="text-xs text-muted-foreground whitespace-nowrap">
                        {searchResult.current}/{searchResult.total}
                      </span>
                    ) : searchQuery ? (
                      <span className="text-xs text-destructive whitespace-nowrap">No results</span>
                    ) : null}
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8"
                    onClick={handleFindPrev}
                    disabled={!searchQuery || searchResult.total === 0}
                  >
                    <ChevronUp className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8"
                    onClick={handleFindNext}
                    disabled={!searchQuery || searchResult.total === 0}
                  >
                    <ChevronDown className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8"
                    onClick={handleCloseSearch}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {shouldShowConnectUi ? (
          <Card className="flex-1 m-4">
            <CardContent className="flex flex-col items-center justify-center gap-3 text-center h-full py-6">
              {connectState.status === "error" ? (
                <div className="w-12 h-12 rounded-full bg-destructive/10 text-destructive flex items-center justify-center text-xl">
                  !
                </div>
              ) : (
                <Loader2 className="h-8 w-8 animate-spin" />
              )}
              <div className="text-center">
                <p className="text-lg font-medium">
                  {connectState.status === "error" ? "Failed to connect" : "Connecting…"}
                </p>
                {"label" in connectState && connectState.label ? (
                  <p className="text-sm text-muted-foreground">{connectState.label}</p>
                ) : (
                  <p className="text-sm text-muted-foreground">{pendingConnectLabel}</p>
                )}
                {"detail" in connectState && connectState.detail && (
                  <p className="text-xs text-muted-foreground mt-2">{connectState.detail}</p>
                )}
                {connectState.status === "error" && (
                  <div className="mt-3 flex flex-col items-center gap-2">
                    {connectErrorCode && (
                      <div className="flex items-center justify-center gap-2">
                        <span className="text-xs text-muted-foreground">Error code</span>
                        <Badge variant="secondary" className="font-mono">
                          {connectErrorCode}
                        </Badge>
                        <CopyIconButton text={connectErrorCode} tooltip="Copy error code" />
                      </div>
                    )}
                    <div className="flex items-center justify-center gap-2">
                      <CopyIconButton text={connectState.message} tooltip="Copy error details" />
                      <span className="text-xs text-muted-foreground">Copy details</span>
                    </div>
                    <p className="text-xs text-destructive mt-2 font-mono break-all select-text">
                      {connectState.message}
                    </p>
                  </div>
                )}
              </div>
              <div className="flex gap-3">
                <Button
                  onClick={() => {
                    setConnectState({ status: "idle" });
                    setTmuxSelect(null);
                  }}
                >
                  Dismiss
                </Button>
                <Button variant="outline" asChild>
                  <Link to="/hosts">Go to Hosts</Link>
                </Button>
              </div>
            </CardContent>
          </Card>
        ) : sessions.length === 0 || workspaceVisible ? (
          <div className="doppio-page">
            <div className="doppio-page-content">
              <div className="termius-toolbar">
                <div className="termius-toolbar-row">
                  <div className="termius-search-bar">
                    <div className="relative flex-1 min-w-0">
                      <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-muted-foreground pointer-events-none" />
                      <Input
                        placeholder="Search recent connections & skills..."
                        value={launcherQuery}
                        onChange={(e) => setLauncherQuery(e.target.value)}
                        className="h-12 w-full pl-10 pr-28"
                      />
                      <div className="absolute right-2 top-1/2 -translate-y-1/2">
                        <Button
                          size="sm"
                          className="h-8 px-4"
                          onClick={() => void handleLauncherPrimary()}
                          disabled={!canLauncherPrimary || launcherPrimaryLoading}
                        >
                          {launcherPrimaryLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                          {launcherPrimaryLabel}
                        </Button>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="termius-toolbar-row justify-between">
                  <div className="termius-quick-actions">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button variant="outline" size="sm" className="gap-1.5" onClick={() => void launchLocalTerminal()}>
                          <TerminalIcon className="w-4 h-4" />
                          <span>Local</span>
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent className="flex items-center gap-2">
                        <span>Open local terminal</span>
                        <kbd className="text-[10px] font-mono bg-muted px-1.5 py-0.5 rounded">⌘⏎</kbd>
                      </TooltipContent>
                    </Tooltip>
                    <Button variant="outline" size="sm" className="gap-1.5" onClick={() => navigate({ to: "/hosts" })}>
                      <Server className="w-4 h-4" />
                      <span>Hosts</span>
                    </Button>
                    <Button variant="outline" size="sm" className="gap-1.5" onClick={() => navigate({ to: "/skills" })}>
                      <Folder className="w-4 h-4" />
                      <span>Skills</span>
                    </Button>
                  </div>

                  {sessions.length > 0 && (
                    <Button variant="outline" size="sm" onClick={() => setWorkspaceVisible(false)}>
                      <span>Back</span>
                    </Button>
                  )}
                </div>
              </div>

              {(launcherError ||
                hostsQuery.error ||
                vastQuery.error ||
                executionsQuery.error) && (
                <Card className="mb-4">
                  <CardContent className="py-3">
                    {launcherError && (
                      <p className="text-sm text-destructive whitespace-pre-wrap">{launcherError}</p>
                    )}
                    {!launcherError && (
                      <p className="text-sm text-destructive whitespace-pre-wrap">
                        {getErrorMessage(hostsQuery.error ?? vastQuery.error ?? executionsQuery.error)}
                      </p>
                    )}
                  </CardContent>
                </Card>
              )}

              {launcherIsLoading ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="h-8 w-8 animate-spin" />
                </div>
              ) : (
                <>
                  {filteredRecentConnections.length > 0 && (
                    <HostSection title="RECENT CONNECTIONS" count={filteredRecentConnections.length}>
                      {filteredRecentConnections.map((conn) => {
                        const isSelected = selectedRecentId === conn.id;

                        if (conn.kind === "local") {
                          return (
                            <HostRow
                              key={conn.id}
                              icon={<AppIcon name="ssh" className="w-5 h-5" alt="Local" />}
                              title="Local"
                              subtitle="On this machine"
                              isOnline={true}
                              isSelected={isSelected}
                              onClick={() => {
                                setSelectedRecentId(conn.id);
                                setSelectedSkillPath(null);
                              }}
                              onDoubleClick={() => void launchRecentConnection(conn)}
                              hoverActions={
                                <div
                                  className="flex items-center gap-1"
                                  onMouseDown={(e) => e.stopPropagation()}
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  <Tooltip>
                                    <TooltipTrigger asChild>
                                      <Button
                                        variant="ghost"
                                        size="icon"
                                        className="w-7 h-7 opacity-60 hover:opacity-100 text-destructive"
                                        onClick={() => {
                                          persistRecentConnections((prev) => removeRecentConnection(prev, conn.id));
                                          setSelectedRecentId((prev) => (prev === conn.id ? null : prev));
                                        }}
                                      >
                                        <Trash2 className="w-3.5 h-3.5" />
                                      </Button>
                                    </TooltipTrigger>
                                    <TooltipContent>Forget</TooltipContent>
                                  </Tooltip>
                                </div>
                              }
                            />
                          );
                        }

                        if (conn.kind === "host") {
                          const host = hosts.find((h) => h.id === conn.host_id) ?? null;
                          const title = host?.name ?? conn.label;
                          const subtitle = host?.ssh ? `${host.ssh.user}@${host.ssh.host}:${host.ssh.port}` : undefined;
                          const rightTags: { label: string; color?: "default" | "primary" | "warning" }[] = [];
                          if (host?.gpu_name) {
                            rightTags.push({ label: formatGpuCountLabel(host.gpu_name, host.num_gpus), color: "primary" });
                          }

                          const iconName: AppIconName =
                            host?.type === "colab" ? "colab" : host?.type === "vast" ? "vast" : "host";

                          return (
                            <HostRow
                              key={conn.id}
                              icon={<AppIcon name={iconName} className="w-5 h-5" alt={host?.type ?? "Host"} />}
                              title={title}
                              subtitle={subtitle}
                              rightTags={rightTags}
                              isOnline={host?.status === "online"}
                              isSelected={isSelected}
                              onClick={() => {
                                setSelectedRecentId(conn.id);
                                setSelectedSkillPath(null);
                              }}
                              onDoubleClick={() => void launchRecentConnection(conn)}
                              hoverActions={
                                <div
                                  className="flex items-center gap-1"
                                  onMouseDown={(e) => e.stopPropagation()}
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  <Tooltip>
                                    <TooltipTrigger asChild>
                                      <Button
                                        variant="ghost"
                                        size="icon"
                                        className="w-7 h-7 opacity-60 hover:opacity-100 text-destructive"
                                        onClick={() => {
                                          persistRecentConnections((prev) => removeRecentConnection(prev, conn.id));
                                          setSelectedRecentId((prev) => (prev === conn.id ? null : prev));
                                        }}
                                      >
                                        <Trash2 className="w-3.5 h-3.5" />
                                      </Button>
                                    </TooltipTrigger>
                                    <TooltipContent>Forget</TooltipContent>
                                  </Tooltip>
                                </div>
                              }
                            />
                          );
                        }

                        const inst = vastInstances.find((i) => i.id === conn.vast_instance_id) ?? null;
                        const title = inst ? getVastLabel(inst) : conn.label;
                        const subtitle =
                          inst?.ssh_host && inst.ssh_port ? `root@${inst.ssh_host}:${inst.ssh_port}` : `Instance #${conn.vast_instance_id}`;
                        const rightTags: { label: string; color?: "default" | "primary" | "warning" }[] = [];
                        if (inst?.gpu_name) {
                          rightTags.push({ label: formatGpuCountLabel(inst.gpu_name, inst.num_gpus), color: "primary" });
                        }

                        return (
                          <HostRow
                            key={conn.id}
                            icon={<AppIcon name="vast" className="w-5 h-5" alt="Vast.ai" />}
                            title={title}
                            subtitle={subtitle}
                            rightTags={rightTags}
                            isOnline={inst ? isVastInstanceOnline(inst) : false}
                            isSelected={isSelected}
                            onClick={() => {
                              setSelectedRecentId(conn.id);
                              setSelectedSkillPath(null);
                            }}
                            onDoubleClick={() => void launchRecentConnection(conn)}
                            hoverActions={
                              <div
                                className="flex items-center gap-1"
                                onMouseDown={(e) => e.stopPropagation()}
                                onClick={(e) => e.stopPropagation()}
                              >
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      className="w-7 h-7 opacity-60 hover:opacity-100 text-destructive"
                                      onClick={() => {
                                        persistRecentConnections((prev) => removeRecentConnection(prev, conn.id));
                                        setSelectedRecentId((prev) => (prev === conn.id ? null : prev));
                                      }}
                                    >
                                      <Trash2 className="w-3.5 h-3.5" />
                                    </Button>
                                  </TooltipTrigger>
                                  <TooltipContent>Forget</TooltipContent>
                                </Tooltip>
                              </div>
                            }
                          />
                        );
                      })}
                    </HostSection>
                  )}

                  {skillHistory.length > 0 && (
                    <HostSection title="RECENT SKILLS" count={skillHistory.length}>
                      {skillHistory.map((exec) => {
                        const hostName = hostNameById.get(exec.host_id) || exec.host_id;
                        const isSelected = selectedSkillPath === exec.skill_path;
                        const rightTags: { label: string; color?: "default" | "primary" | "warning" }[] = [
                          { label: getExecutionStatusLabel(exec.status), color: exec.status === "running" || exec.status === "waiting_for_input" ? "primary" : "default" },
                        ];

                        return (
                          <HostRow
                            key={exec.skill_path}
                            icon={<span className="text-lg">📜</span>}
                            title={exec.skill_name}
                            subtitle={`${hostName} · ${new Date(exec.created_at).toLocaleString()}`}
                            rightTags={rightTags}
                            isOnline={exec.status === "running" || exec.status === "waiting_for_input"}
                            isSelected={isSelected}
                            onClick={() => {
                              setSelectedSkillPath(exec.skill_path);
                              setSelectedRecentId(null);
                            }}
                            onDoubleClick={() => void launchExecution(exec)}
                            hoverActions={
                              <div
                                className="flex items-center gap-1"
                                onMouseDown={(e) => e.stopPropagation()}
                                onClick={(e) => e.stopPropagation()}
                              >
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      className="w-7 h-7 opacity-60 hover:opacity-100"
                                      onClick={() => void launchExecution(exec)}
                                    >
                                      <Play className="w-3.5 h-3.5" />
                                    </Button>
                                  </TooltipTrigger>
                                  <TooltipContent>Run</TooltipContent>
                                </Tooltip>
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      className="w-7 h-7 opacity-60 hover:opacity-100"
                                      onClick={() => {
                                        navigate({ to: "/skills/$path", params: { path: encodeURIComponent(exec.skill_path) } });
                                      }}
                                    >
                                      <Pencil className="w-3.5 h-3.5" />
                                    </Button>
                                  </TooltipTrigger>
                                  <TooltipContent>Open</TooltipContent>
                                </Tooltip>
                              </div>
                            }
                          />
                        );
                      })}
                    </HostSection>
                  )}

                  {filteredRecentConnections.length === 0 && skillHistory.length === 0 && (
                    <EmptyHostState
                      icon={<TerminalIcon className="w-5 h-5" />}
                      title={launcherQuery ? "No matches" : "Nothing recent yet"}
                      description={launcherQuery ? "Try a different search term." : "Connect to a host or run a skill to see it here."}
                      action={
                        !launcherQuery ? (
                          <div className="flex items-center gap-2">
                            <Button variant="outline" asChild>
                              <Link to="/hosts">Go to Hosts</Link>
                            </Button>
                            <Button variant="outline" asChild>
                              <Link to="/skills">Go to Skills</Link>
                            </Button>
                          </div>
                        ) : null
                      }
                    />
                  )}
                </>
              )}
            </div>
          </div>
        ) : (
          <div className="flex-1 min-h-0 flex gap-3 p-3">
            <div
              className="flex-1 min-h-0 relative border border-border overflow-hidden bg-card"
            >
              {sessions.map((s) => (
                <div
                  key={s.id}
                  className="absolute inset-0"
                  style={{
                    visibility: activeId === s.id ? "visible" : "hidden",
                    zIndex: activeId === s.id ? 1 : 0,
                  }}
                >
                  <TerminalPane
                    id={s.id}
                    active={activeId === s.id}
                    searchQuery={activeId === s.id ? searchQuery : ""}
                    onSearchResult={handleSearchResult}
                    searchDirection={activeId === s.id ? searchDirection : null}
                    onSearchComplete={handleSearchComplete}
                    skillExecutionId={s.skillExecutionId}
                    interventionLocked={s.interventionLocked}
                    themeName={terminalTheme}
                    onClose={() => void closeSession(s.id)}
                  />
                </div>
              ))}
            </div>

            <AnimatePresence initial={false}>
              {activeSkillExecutionId && skillSidebarOpen ? (
                <motion.div
                  initial={{ width: 0, opacity: 0 }}
                  animate={{ width: 480, opacity: 1 }}
                  exit={{ width: 0, opacity: 0 }}
                  transition={{ duration: 0.2, ease: "easeInOut" }}
                  className="min-h-0 overflow-hidden"
                >
                  <SkillRunSidebar executionId={activeSkillExecutionId} />
                </motion.div>
              ) : null}
            </AnimatePresence>
          </div>
        )}
      </div>

      <TmuxSessionSelectModal
        sessions={tmuxSelect?.sessions ?? []}
        isOpen={tmuxSelect != null}
        onClose={() => {
          setTmuxSelect(null);
          setConnectState({ status: "idle" });
        }}
        onSelect={(name) => {
          const current = tmuxSelect;
          if (!current) return;
          setTmuxSelect(null);
          void (async () => {
            try {
              setConnectState({ status: "connecting", label: current.hostName, detail: `Connecting to tmux: ${name}` });
              await openSshTmux({
                ssh: current.ssh,
                tmuxSession: name,
                title: `${current.hostName} · ${name}`,
                envVars: current.envVars,
              });
              if (current.kind === "host" && current.hostId) {
                recordHostConnection(current.hostId, current.hostName);
              }
              if (current.kind === "vast" && current.vastInstanceId != null) {
                recordVastConnection(current.vastInstanceId, current.hostName);
              }
              setWorkspaceVisible(false);
              setConnectState({ status: "idle" });
            } catch (e) {
              setConnectState({ status: "error", label: current.hostName, message: getErrorMessage(e) });
            }
          })();
        }}
        onCreate={(name) => {
          const current = tmuxSelect;
          if (!current) return;
          setTmuxSelect(null);
          void (async () => {
            try {
              setConnectState({ status: "connecting", label: current.hostName, detail: `Connecting to tmux: ${name}` });
              await openSshTmux({
                ssh: current.ssh,
                tmuxSession: name,
                title: `${current.hostName} · ${name}`,
                envVars: current.envVars,
              });
              if (current.kind === "host" && current.hostId) {
                recordHostConnection(current.hostId, current.hostName);
              }
              if (current.kind === "vast" && current.vastInstanceId != null) {
                recordVastConnection(current.vastInstanceId, current.hostName);
              }
              setWorkspaceVisible(false);
              setConnectState({ status: "idle" });
            } catch (e) {
              setConnectState({ status: "error", label: current.hostName, message: getErrorMessage(e) });
            }
          })();
        }}
        isLoading={false}
      />
    </div>
  );
}

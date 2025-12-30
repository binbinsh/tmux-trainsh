import { Card, CardBody, CardHeader, Chip, Divider, Input, Kbd, Skeleton, Spinner, Tooltip } from "@nextui-org/react";
import { Button } from "../components/ui";
import { listen } from "@tauri-apps/api/event";
import { FitAddon } from "@xterm/addon-fit";
import { WebglAddon } from "@xterm/addon-webgl";
import { SearchAddon, type ISearchOptions } from "@xterm/addon-search";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { getConfig, hostApi, sshCheck, termOpenSshTmux, termResize, termWrite, useHosts, useVastInstances, vastAttachSshKey, vastGetInstance, type RemoteTmuxSession } from "../lib/tauri-api";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { useTerminal } from "../contexts/TerminalContext";
import { AnimatePresence, motion } from "framer-motion";
import { RecipeAutomationPanel } from "../components/recipe/RecipeAutomationPanel";
import { TerminalHistoryPanel } from "../components/terminal/TerminalHistoryPanel";
import { TmuxSessionSelectModal } from "../components/host/TmuxSessionSelectModal";
import { copyText } from "../lib/clipboard";
import { AppIcon, type AppIconName } from "../components/AppIcon";
import { StatusBadge } from "../components/shared/StatusBadge";
import type { Host, HostStatus, VastInstance } from "../lib/types";

interface TerminalPaneProps {
  id: string;
  active: boolean;
  searchQuery: string;
  onSearchResult: (current: number, total: number) => void;
  searchDirection: "next" | "prev" | null;
  onSearchComplete: () => void;
  /** Associated recipe execution ID */
  recipeExecutionId?: string | null;
  /** Whether intervention is locked (for recipe terminals) */
  interventionLocked?: boolean;
  /** Called when the terminal session exits (e.g., user pressed Ctrl+D) */
  onClose: () => void;
}

// Render throttle interval in ms (higher value = less flashing during fast output)
const RENDER_THROTTLE_MS = 24;
// Flush immediately when buffered data grows beyond this size
const MAX_BUFFERED_CHARS = 64 * 1024;

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

const HOST_STATUS_ORDER: Record<HostStatus, number> = {
  online: 0,
  connecting: 1,
  offline: 2,
  error: 3,
};

function getHostIconName(host: Host): AppIconName {
  if (host.type === "colab") return "colab";
  if (host.type === "vast") return "vast";
  return "host";
}

function getVastStatus(inst: VastInstance): HostStatus {
  const v = (inst.actual_status ?? "").toLowerCase();
  if (v.includes("error") || v.includes("failed")) return "error";
  if (v.includes("running") || v.includes("active") || v.includes("online")) return "online";
  if (v.includes("stopped") || v.includes("exited") || v.includes("offline")) return "offline";
  return "connecting";
}

function getVastLabel(inst: VastInstance): string {
  return inst.label?.trim() || `vast #${inst.id}`;
}


function IconCopy() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" />
    </svg>
  );
}

function IconCheck() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
    </svg>
  );
}


function CopyIconButton({ text, tooltip }: { text: string; tooltip: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await copyText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Tooltip content={copied ? "Copied!" : tooltip}>
      <Button isIconOnly size="sm" variant="flat" onPress={handleCopy}>
        {copied ? <IconCheck /> : <IconCopy />}
      </Button>
    </Tooltip>
  );
}

function TerminalPane(props: TerminalPaneProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const searchRef = useRef<SearchAddon | null>(null);
  const webglRef = useRef<WebglAddon | null>(null);
  const hasExitedRef = useRef(false);
  
  // Data batching refs for smooth rendering
  const dataChunksRef = useRef<string[]>([]);
  const dataBufferSizeRef = useRef(0);
  const rafIdRef = useRef<number | null>(null);
  const lastFlushRef = useRef<number>(0);
  
  // Use ref for intervention lock to avoid re-creating terminal on lock state change
  const interventionLockedRef = useRef(props.interventionLocked);
  useEffect(() => {
    interventionLockedRef.current = props.interventionLocked;
  }, [props.interventionLocked]);

  // Search options with highlight decorations
  const searchOptions: ISearchOptions = {
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

  // Handle search query changes
  useEffect(() => {
    if (!searchRef.current) return;
    
    if (props.searchQuery) {
      searchRef.current.findNext(props.searchQuery, searchOptions);
    } else {
      searchRef.current.clearDecorations();
      props.onSearchResult(0, 0);
    }
  }, [props.searchQuery]);

  // Handle search direction (next/prev)
  useEffect(() => {
    if (!searchRef.current || !props.searchQuery || !props.searchDirection) return;
    
    if (props.searchDirection === "next") {
      searchRef.current.findNext(props.searchQuery, searchOptions);
    } else {
      searchRef.current.findPrevious(props.searchQuery, searchOptions);
    }
    props.onSearchComplete();
  }, [props.searchDirection]);

  useEffect(() => {
    if (!hostRef.current) return;
    if (termRef.current) return;

    const term = new Terminal({
      scrollback: 100000,
      convertEol: true,
      cursorBlink: true,
      cursorStyle: "bar",
      fontFamily: "'JetBrains Mono', 'Fira Code', 'SF Mono', Menlo, Monaco, monospace",
      fontSize: 14,
      fontWeight: "400",
      fontWeightBold: "600",
      lineHeight: 1.3,
      letterSpacing: 0.2,
      macOptionIsMeta: true,
      macOptionClickForcesSelection: true,
      allowProposedApi: true, // Required for search decorations
      minimumContrastRatio: 2,
      theme: {
        background: "#d6d8df",
        foreground: "#343b58",
        cursor: "#707280",
        cursorAccent: "#d6d8df",
        selectionBackground: "#acb0bf40",
        selectionForeground: "#343b58",
        selectionInactiveBackground: "#acb0bf33",
        black: "#343b58",
        red: "#8c4351",
        green: "#33635c",
        yellow: "#8f5e15",
        blue: "#2959aa",
        magenta: "#7b43ba",
        cyan: "#006c86",
        white: "#707280",
        brightBlack: "#343b58",
        brightRed: "#8c4351",
        brightGreen: "#33635c",
        brightYellow: "#8f5e15",
        brightBlue: "#2959aa",
        brightMagenta: "#7b43ba",
        brightCyan: "#006c86",
        brightWhite: "#707280",
      },
    });

    // Load FitAddon
    const fit = new FitAddon();
    term.loadAddon(fit);

    // Load SearchAddon
    const search = new SearchAddon();
    term.loadAddon(search);
    searchRef.current = search;

    // Listen to search results
    search.onDidChangeResults((e) => {
      if (e) {
        props.onSearchResult(e.resultIndex + 1, e.resultCount);
      } else {
        props.onSearchResult(0, 0);
      }
    });

    term.open(hostRef.current);

    // Ensure wheel always scrolls terminal buffer (not shell history)
    const onWheel = (e: WheelEvent) => {
      if (!termRef.current) return;
      const lines = Math.max(1, Math.round(Math.abs(e.deltaY) / 40));
      termRef.current.scrollLines(e.deltaY > 0 ? lines : -lines);
      e.preventDefault();
    };
    hostRef.current.addEventListener("wheel", onWheel, { passive: false });

    // Load WebGL addon for hardware acceleration (after terminal is opened)
    try {
      const webgl = new WebglAddon();
      term.loadAddon(webgl);
      webglRef.current = webgl;
      console.log("[Terminal] WebGL renderer enabled");

      // Handle WebGL context loss
      webgl.onContextLoss(() => {
        console.warn("[Terminal] WebGL context lost, falling back to canvas renderer");
        webgl.dispose();
        webglRef.current = null;

        // Try to restore after a delay
        setTimeout(() => {
          try {
            const newWebgl = new WebglAddon();
            term.loadAddon(newWebgl);
            webglRef.current = newWebgl;
            console.log("[Terminal] WebGL renderer restored");
          } catch (e) {
            console.error("[Terminal] Failed to restore WebGL:", e);
          }
        }, 2000);
      });
    } catch (e) {
      console.warn("[Terminal] WebGL not supported, using canvas renderer:", e);
    }
    
    // Fit after a short delay to ensure container is fully rendered
    const doFit = () => {
      try {
        fit.fit();
        void termResize(props.id, term.cols, term.rows);
      } catch {
        // ignore
      }
    };
    
    // Initial fit with delay
    setTimeout(doFit, 50);
    // Fit again after a longer delay to catch late layout changes
    setTimeout(doFit, 200);

    const onDataDispose = term.onData((data) => {
      // Check if this is a recipe terminal with intervention locked
      if (interventionLockedRef.current) {
        // Still allow Ctrl+C (ASCII 0x03) to interrupt
        if (data === "\x03") {
          void termWrite(props.id, data);
        }
        // Otherwise, ignore input when locked
        return;
      }
      void termWrite(props.id, data);
    });

    const ro = new ResizeObserver(() => {
      doFit();
    });
    ro.observe(hostRef.current);
    
    // Also listen for window resize
    const handleWindowResize = () => doFit();
    window.addEventListener("resize", handleWindowResize);

    termRef.current = term;
    fitRef.current = fit;

    // Track if component is still mounted (for async cleanup)
    let isMounted = true;
    let unlistenData: (() => void) | null = null;
    let unlistenExit: (() => void) | null = null;

    // Flush buffered data to terminal with throttling
    const flushBuffer = () => {
      if (dataChunksRef.current.length > 0 && termRef.current) {
        const chunk = dataChunksRef.current.join("");
        dataChunksRef.current = [];
        dataBufferSizeRef.current = 0;
        termRef.current.write(chunk);
        lastFlushRef.current = performance.now();
      }
      rafIdRef.current = null;
    };

    // Schedule a flush with throttling
    const scheduleFlush = () => {
      const shouldFlushNow = dataBufferSizeRef.current >= MAX_BUFFERED_CHARS;
      if (rafIdRef.current !== null) {
        if (shouldFlushNow) {
          cancelAnimationFrame(rafIdRef.current);
          clearTimeout(rafIdRef.current);
          rafIdRef.current = requestAnimationFrame(flushBuffer);
        }
        return;
      }
      
      const now = performance.now();
      const elapsed = now - lastFlushRef.current;
      
      if (shouldFlushNow || elapsed >= RENDER_THROTTLE_MS) {
        // Enough time passed, flush immediately on next frame
        rafIdRef.current = requestAnimationFrame(flushBuffer);
      } else {
        // Schedule flush after remaining throttle time
        const delay = RENDER_THROTTLE_MS - elapsed;
        rafIdRef.current = window.setTimeout(() => {
          rafIdRef.current = requestAnimationFrame(flushBuffer);
        }, delay) as unknown as number;
      }
    };

    // Set up event listeners
    (async () => {
      // Check if already unmounted before setting up listeners
      if (!isMounted) return;
      
      const dataUnlisten = await listen<{ id: string; data: string }>("term:data", (evt) => {
        if (evt.payload.id === props.id) {
          // Buffer data instead of writing immediately
          dataChunksRef.current.push(evt.payload.data);
          dataBufferSizeRef.current += evt.payload.data.length;
          scheduleFlush();
        }
      });
      
      // Check again after await - component might have unmounted
      if (!isMounted) {
        dataUnlisten();
        return;
      }
      unlistenData = dataUnlisten;
      
      // Listen for terminal exit and keep the tab open for debugging
      const exitUnlisten = await listen<{ id: string }>("term:exit", (evt) => {
        if (evt.payload.id === props.id) {
          // Flush any remaining data first
          if (dataChunksRef.current.length > 0 && termRef.current) {
            termRef.current.write(dataChunksRef.current.join(""));
            dataChunksRef.current = [];
            dataBufferSizeRef.current = 0;
          }
          if (termRef.current && !hasExitedRef.current) {
            termRef.current.write("\r\n[Session ended] Terminal tab kept open for debugging.\r\n");
            hasExitedRef.current = true;
          }
        }
      });
      
      if (!isMounted) {
        exitUnlisten();
        return;
      }
      unlistenExit = exitUnlisten;
    })();

    return () => {
      // Mark as unmounted first to prevent new listeners from being set up
      isMounted = false;
      
      // Cancel any pending flush
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current);
        clearTimeout(rafIdRef.current);
        rafIdRef.current = null;
      }
      // Flush remaining buffer before cleanup
      if (dataChunksRef.current.length > 0 && termRef.current) {
        termRef.current.write(dataChunksRef.current.join(""));
        dataChunksRef.current = [];
        dataBufferSizeRef.current = 0;
      }
      ro.disconnect();
      window.removeEventListener("resize", handleWindowResize);
      onDataDispose.dispose();
      if (unlistenData) unlistenData();
      if (unlistenExit) unlistenExit();
      hostRef.current?.removeEventListener("wheel", onWheel);
      if (webglRef.current) webglRef.current.dispose();
      if (searchRef.current) searchRef.current.dispose();
      term.dispose();
      termRef.current = null;
      fitRef.current = null;
      searchRef.current = null;
      webglRef.current = null;
    };
  }, [props.id]);

  useEffect(() => {
    if (props.active && termRef.current && fitRef.current) {
      termRef.current.focus();
      // Re-fit when becoming active (tab switch)
      // Use requestAnimationFrame for smoother transition
      requestAnimationFrame(() => {
        try {
          fitRef.current?.fit();
          if (termRef.current) {
            void termResize(props.id, termRef.current.cols, termRef.current.rows);
          }
        } catch {
          // ignore
        }
      });
    }
  }, [props.active, props.id]);

  return <div ref={hostRef} className="h-full w-full bg-content1" />;
}

// Search bar icons
function SearchIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  );
}

function ChevronUpIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m18 15-6-6-6 6" />
    </svg>
  );
}

function ChevronDownIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

function CloseIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 6 6 18" />
      <path d="m6 6 12 12" />
    </svg>
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
    recipePanelVisible,
    toggleRecipePanel,
    historyPanelVisible,
    workspaceVisible,
    setWorkspaceVisible,
  } = useTerminal();
  const hostsQuery = useHosts();
  const vastQuery = useVastInstances();

  const [connectState, setConnectState] = useState<
    | { status: "idle" }
    | { status: "connecting"; label: string; detail?: string | null }
    | { status: "select_tmux"; label: string }
    | { status: "error"; label?: string | null; message: string }
  >({ status: "idle" });
  const [quickFilter, setQuickFilter] = useState("");

  const [tmuxSelect, setTmuxSelect] = useState<{
    hostId: string | null;
    hostName: string;
    ssh: { host: string; port: number; user: string; keyPath?: string | null; extraArgs?: string[] };
    envVars: Record<string, string> | null;
    sessions: RemoteTmuxSession[];
  } | null>(null);

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
  const hasQuickFilter = quickFilter.trim().length > 0;
  const hosts = hostsQuery.data ?? [];
  const filteredHosts = useMemo(() => {
    const needle = quickFilter.trim().toLowerCase();
    const base = needle
      ? hosts.filter((host) => {
          const tokens = [
            host.name,
            host.type,
            host.status,
            host.ssh?.host,
            host.ssh?.user,
            host.ssh?.port != null ? String(host.ssh.port) : null,
            host.cloudflared_hostname,
          ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase();
          return tokens.includes(needle);
        })
      : hosts;

    return [...base].sort((a, b) => {
      const statusDelta = HOST_STATUS_ORDER[a.status] - HOST_STATUS_ORDER[b.status];
      if (statusDelta !== 0) return statusDelta;
      return a.name.localeCompare(b.name);
    });
  }, [hosts, quickFilter]);

  const vastInstances = vastQuery.data ?? [];
  const filteredVastInstances = useMemo(() => {
    const needle = quickFilter.trim().toLowerCase();
    const base = needle
      ? vastInstances.filter((inst) => {
          const tokens = [
            getVastLabel(inst),
            inst.gpu_name,
            inst.actual_status,
            String(inst.id),
          ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase();
          return tokens.includes(needle);
        })
      : vastInstances;

    return [...base].sort((a, b) => {
      const statusDelta = HOST_STATUS_ORDER[getVastStatus(a)] - HOST_STATUS_ORDER[getVastStatus(b)];
      if (statusDelta !== 0) return statusDelta;
      return getVastLabel(a).localeCompare(getVastLabel(b));
    });
  }, [quickFilter, vastInstances]);
  const hostCountLabel = hostsQuery.isLoading
    ? "Loading..."
    : `${filteredHosts.length} host${filteredHosts.length === 1 ? "" : "s"}${hasQuickFilter ? " matched" : ""}`;
  const vastCountLabel = vastQuery.isLoading
    ? "Loading..."
    : `${filteredVastInstances.length} instance${filteredVastInstances.length === 1 ? "" : "s"}${hasQuickFilter ? " matched" : ""}`;

  // Search state
  const [showSearch, setShowSearch] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResult, setSearchResult] = useState({ current: 0, total: 0 });
  const [searchDirection, setSearchDirection] = useState<"next" | "prev" | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const showSearchRef = useRef(showSearch);
  
  // Keep ref in sync with state
  useEffect(() => {
    showSearchRef.current = showSearch;
  }, [showSearch]);

  // Refresh sessions when page mounts (to pick up sessions created from host page)
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

      // If there are existing sessions, show the selection modal to let user choose
      // or create a new session
      if (tmuxSessions.length >= 1) {
        setTmuxSelect({
          hostId,
          hostName: host.name,
          ssh,
          envVars: host.env_vars ?? null,
          sessions: tmuxSessions,
        });
        setConnectState({ status: "select_tmux", label: host.name });
        return;
      }

      // No existing sessions - create a new "main" session
      const sessionName = "main";
      setConnectState({ status: "connecting", label: host.name, detail: `Connecting to tmux: ${sessionName}` });
      await openSshTmux({
        ssh,
        tmuxSession: sessionName,
        title: `${host.name} · ${sessionName}`,
        envVars: host.env_vars ?? null,
      });
      setConnectState({ status: "idle" });
    },
    [openSshTmux, setActiveId]
  );

  const connectToVastInstance = useCallback(
    async (instanceId: number, label?: string) => {
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

          // SSH connection successful - now check for existing tmux sessions
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

          // If there are existing sessions, show the selection modal
          if (tmuxSessions.length >= 1) {
            setTmuxSelect({
              hostId: null, // No host ID for Vast instances
              hostName: label ?? `Vast #${instanceId}`,
              ssh,
              envVars: null,
              sessions: tmuxSessions,
            });
            setConnectState({ status: "select_tmux", label: label ?? `Vast #${instanceId}` });
            return;
          }

          // No existing sessions - create a new "main" session
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
          setConnectState({ status: "idle" });
          return;
        } catch (e) {
          lastError = e;
        }
      }

      throw lastError ?? new Error("SSH connection failed");
    },
    [openSshTmux, setActiveId]
  );

  const handleQuickConnectHost = useCallback(
    async (host: Host) => {
      try {
        await connectToSavedHost(host.id, host.name);
      } catch (e) {
        setConnectState({ status: "error", label: host.name, message: getErrorMessage(e) });
      }
    },
    [connectToSavedHost]
  );

  const handleQuickConnectVast = useCallback(
    async (inst: VastInstance) => {
      const label = getVastLabel(inst);
      try {
        await connectToVastInstance(inst.id, label);
      } catch (e) {
        setConnectState({ status: "error", label, message: getErrorMessage(e) });
      }
    },
    [connectToVastInstance]
  );

  // If navigated here with a connect request, start connecting immediately and show the waiting UI here.
  useEffect(() => {
    const connectHostId = typeof search.connectHostId === "string" ? search.connectHostId : null;
    const connectVastIdStr =
      typeof search.connectVastInstanceId === "string" ? search.connectVastInstanceId : null;
    const connectLabel = typeof search.connectLabel === "string" ? search.connectLabel : null;

    const key = connectHostId ? `host:${connectHostId}` : connectVastIdStr ? `vast:${connectVastIdStr}` : null;
    if (!key || connectHandledRef.current === key) return;

    connectHandledRef.current = key;
    navigate({ to: "/terminal", search: {}, replace: true });

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

  // Keep refs in sync with state for keyboard handler
  const activeIdRef = useRef(activeId);
  useEffect(() => {
    activeIdRef.current = activeId;
  }, [activeId]);

  // Toggle search with Cmd/Ctrl+F, toggle automation panel with Cmd/Ctrl+], close search with Escape
  // Close terminal with Cmd+W, open new terminal with Cmd+T
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Toggle search with Cmd/Ctrl+F
      if ((e.metaKey || e.ctrlKey) && e.key === "f") {
        e.preventDefault();
        e.stopPropagation();
        setShowSearch((prev) => {
          if (!prev) {
            // Focus input when opening
            setTimeout(() => searchInputRef.current?.focus(), 50);
          } else {
            // Clear search when closing
            setSearchQuery("");
          }
          return !prev;
        });
        return;
      }
      
      // Toggle automation panel with Cmd/Ctrl+]
      if ((e.metaKey || e.ctrlKey) && e.key === "]") {
        e.preventDefault();
        e.stopPropagation();
        toggleRecipePanel();
        return;
      }
      
      // Close current terminal with Cmd+W
      if ((e.metaKey || e.ctrlKey) && e.key === "w") {
        e.preventDefault();
        e.stopPropagation();
        if (activeIdRef.current) {
          void closeSession(activeIdRef.current);
        }
        return;
      }
      
      // Open new terminal tab with Cmd+T
      if ((e.metaKey || e.ctrlKey) && e.key === "t") {
        e.preventDefault();
        e.stopPropagation();
        void openLocalTerminal();
        return;
      }
      
      // Close search with Escape (use ref to get current value)
      if (e.key === "Escape" && showSearchRef.current) {
        e.preventDefault();
        e.stopPropagation();
        setShowSearch(false);
        setSearchQuery("");
      }
    };
    
    // Use capture phase to intercept before terminal
    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, [closeSession, openLocalTerminal, toggleRecipePanel]); // Stable callbacks from context

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
        <div className="text-foreground/60">Loading...</div>
      </div>
    );
  }

  return (
    <div className="h-full flex text-foreground">
      {/* Main Terminal Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Search Bar */}
        <AnimatePresence>
          {showSearch && sessions.length > 0 && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="overflow-hidden bg-content1/90 backdrop-blur-md border-b border-divider"
            >
              <div className="flex items-center gap-2 px-3 py-2">
                <Input labelPlacement="inside" ref={searchInputRef}
                size="sm"
                placeholder="Search in terminal..."
                value={searchQuery}
                onValueChange={setSearchQuery}
                onKeyDown={handleSearchKeyDown}
                startContent={<SearchIcon className="text-foreground/50" />}
                endContent={
                  searchQuery && searchResult.total > 0 ? (
                    <span className="text-xs text-foreground/60 whitespace-nowrap">
                      {searchResult.current}/{searchResult.total}
                    </span>
                  ) : searchQuery ? (
                    <span className="text-xs text-danger whitespace-nowrap">No results</span>
                  ) : null
                }
                classNames={{
                  base: "max-w-xs",
                  inputWrapper: "h-8 bg-content2 border border-divider",
                  input: "text-sm text-foreground/80",
                }} />
                <div className="flex items-center gap-1">
                  <Button
                    isIconOnly
                    size="sm"
                    variant="light"
                    onPress={handleFindPrev}
                    isDisabled={!searchQuery || searchResult.total === 0}
                    aria-label="Previous match"
                  >
                    <ChevronUpIcon />
                  </Button>
                  <Button
                    isIconOnly
                    size="sm"
                    variant="light"
                    onPress={handleFindNext}
                    isDisabled={!searchQuery || searchResult.total === 0}
                    aria-label="Next match"
                  >
                    <ChevronDownIcon />
                  </Button>
                  <Button
                    isIconOnly
                    size="sm"
                    variant="light"
                    onPress={handleCloseSearch}
                    aria-label="Close search"
                  >
                    <CloseIcon />
                  </Button>
                </div>
                <div className="hidden sm:flex items-center gap-1 text-xs text-foreground/40 ml-2">
                  <Kbd keys={["command"]}>F</Kbd>
                  <span>to toggle</span>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {shouldShowConnectUi ? (
          <Card className="flex-1 m-4 border border-divider">
            <CardBody className="flex flex-col items-center justify-center gap-3 text-center">
              {connectState.status === "error" ? (
                <div className="w-12 h-12 rounded-full bg-danger/10 text-danger flex items-center justify-center text-xl">
                  !
                </div>
              ) : (
                <Spinner size="lg" />
              )}
              <div className="text-center">
                <p className="text-lg font-medium">
                  {connectState.status === "error" ? "Failed to connect" : "Connecting…"}
                </p>
                {"label" in connectState && connectState.label ? (
                  <p className="text-sm text-foreground/60">{connectState.label}</p>
                ) : (
                  <p className="text-sm text-foreground/60">{pendingConnectLabel}</p>
                )}
                {"detail" in connectState && connectState.detail && (
                  <p className="text-xs text-foreground/50 mt-2">{connectState.detail}</p>
                )}
                {connectState.status === "error" && (
                  <div className="mt-3 flex flex-col items-center gap-2">
                    {connectErrorCode && (
                      <div className="flex items-center justify-center gap-2">
                        <span className="text-xs text-foreground/60">Error code</span>
                        <Chip size="sm" variant="flat" className="font-mono select-text">
                          {connectErrorCode}
                        </Chip>
                        <CopyIconButton text={connectErrorCode} tooltip="Copy error code" />
                      </div>
                    )}
                    <div className="flex items-center justify-center gap-2">
                      <CopyIconButton text={connectState.message} tooltip="Copy error details" />
                      <span className="text-xs text-foreground/60">Copy details</span>
                    </div>
                    <p className="text-xs text-danger mt-2 font-mono break-all select-text">
                      {connectState.message}
                    </p>
                  </div>
                )}
              </div>
              <div className="flex gap-3">
                <Button
                  color="primary"
                  onPress={() => {
                    setConnectState({ status: "idle" });
                    setTmuxSelect(null);
                  }}
                >
                  Dismiss
                </Button>
                <Button as={Link} to="/hosts" variant="flat">
                  Go to Hosts
                </Button>
              </div>
            </CardBody>
          </Card>
        ) : sessions.length === 0 || workspaceVisible ? (
          <div className="doppio-page">
            <div className="doppio-page-content">
              {/* Header */}
              <div className="doppio-page-header">
                <div>
                  <h1 className="doppio-page-title">Terminal</h1>
                  <p className="doppio-page-subtitle">Open local shells or connect to remote hosts</p>
                </div>
                <div className="flex gap-2">
                  <Button color="primary" onPress={() => void openLocalTerminal()}>
                    Local Terminal
                  </Button>
                  <Button as={Link} to="/hosts" variant="flat">
                    Manage Hosts
                  </Button>
                </div>
              </div>

              {/* Filter */}
              <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-6">
                <Input
                  labelPlacement="inside"
                  placeholder="Filter hosts and instances..."
                  value={quickFilter}
                  onValueChange={setQuickFilter}
                  startContent={<SearchIcon className="text-foreground/50" />}
                  classNames={{
                    base: "max-w-md",
                    inputWrapper: "bg-content2 border border-divider rounded-full",
                    input: "text-sm text-foreground/80",
                  }}
                />
                <div className="flex items-center gap-2 text-xs text-foreground/50">
                  <Kbd keys={["command"]}>T</Kbd>
                  <span>new local</span>
                  <Kbd keys={["command"]}>F</Kbd>
                  <span>search terminal</span>
                </div>
              </div>

              {/* Host Cards Grid */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="doppio-card">
                  <div className="flex items-center justify-between p-4 border-b border-divider">
                    <div>
                      <h3 className="text-sm font-semibold">Saved Hosts</h3>
                      <p className="text-xs text-foreground/50">{hostCountLabel}</p>
                    </div>
                    <Button as={Link} to="/hosts" size="sm" variant="flat">
                      View All
                    </Button>
                  </div>
                  <div className="p-4 space-y-3">
                      {hostsQuery.isLoading ? (
                        <div className="space-y-3">
                          {Array.from({ length: 3 }).map((_, idx) => (
                            <div key={idx} className="flex items-center gap-3 rounded-lg border border-divider bg-content2 p-3">
                              <Skeleton className="h-9 w-9 rounded-md" />
                              <div className="flex-1 space-y-2">
                                <Skeleton className="h-3 w-36 rounded-md" />
                                <Skeleton className="h-2 w-44 rounded-md" />
                              </div>
                              <Skeleton className="h-8 w-20 rounded-md" />
                            </div>
                          ))}
                        </div>
                      ) : hostsQuery.error ? (
                        <p className="text-sm text-danger">Failed to load hosts.</p>
                      ) : filteredHosts.length === 0 ? (
                        <div className="text-sm text-foreground/60">
                          {hasQuickFilter ? "No matching hosts." : "No hosts yet. Add one to get started."}
                        </div>
                      ) : (
                        <div className="space-y-3">
                          {filteredHosts.map((host, index) => {
                            const sshAddress = host.ssh ? `${host.ssh.user}@${host.ssh.host}:${host.ssh.port}` : null;
                            return (
                              <motion.div
                                key={host.id}
                                initial={{ opacity: 0, y: 8 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: index * 0.03 }}
                              >
                                <div className="flex items-center justify-between gap-3 rounded-lg border border-divider bg-content2 p-3 hover:border-primary/40 transition-colors">
                                  <div className="flex items-start gap-3 min-w-0">
                                    <AppIcon
                                      name={getHostIconName(host)}
                                      className="w-8 h-8 shrink-0"
                                      alt={`${host.type} icon`}
                                    />
                                    <div className="min-w-0">
                                      <div className="flex items-center gap-2 flex-wrap">
                                        <p className="font-medium text-sm">{host.name}</p>
                                        <StatusBadge status={host.status} size="sm" />
                                        <Chip size="sm" variant="flat">
                                          {host.type}
                                        </Chip>
                                      </div>
                                      {sshAddress ? (
                                        <p className="text-xs font-mono text-foreground/50 truncate">{sshAddress}</p>
                                      ) : (
                                        <p className="text-xs text-foreground/50">SSH not configured</p>
                                      )}
                                      <p className="text-xs text-foreground/40">
                                        {host.last_seen_at
                                          ? `Last seen: ${new Date(host.last_seen_at).toLocaleDateString()}`
                                          : "Never seen"}
                                      </p>
                                    </div>
                                  </div>
                                  <Button
                                    size="sm"
                                    color="primary"
                                    variant="flat"
                                    onPress={() => void handleQuickConnectHost(host)}
                                    isDisabled={!host.ssh}
                                  >
                                    Connect
                                  </Button>
                                </div>
                              </motion.div>
                            );
                          })}
                        </div>
                      )}
                  </div>
                </div>

                <div className="doppio-card">
                  <div className="flex items-center justify-between p-4 border-b border-divider">
                    <div>
                      <h3 className="text-sm font-semibold">Vast.ai Instances</h3>
                      <p className="text-xs text-foreground/50">{vastCountLabel}</p>
                    </div>
                    <Button as={Link} to="/hosts" size="sm" variant="flat">
                      Manage
                    </Button>
                  </div>
                  <div className="p-4 space-y-3">
                      {vastQuery.isLoading ? (
                        <div className="space-y-3">
                          {Array.from({ length: 2 }).map((_, idx) => (
                            <div key={idx} className="flex items-center gap-3 rounded-lg border border-divider bg-content2 p-3">
                              <Skeleton className="h-9 w-9 rounded-md" />
                              <div className="flex-1 space-y-2">
                                <Skeleton className="h-3 w-40 rounded-md" />
                                <Skeleton className="h-2 w-36 rounded-md" />
                              </div>
                              <Skeleton className="h-8 w-20 rounded-md" />
                            </div>
                          ))}
                        </div>
                      ) : vastQuery.error ? (
                        <div className="text-sm text-foreground/60">
                          Failed to load. Check your Vast.ai API key in Settings.
                        </div>
                      ) : filteredVastInstances.length === 0 ? (
                        <div className="text-sm text-foreground/60">
                          {hasQuickFilter ? "No matching instances." : "No active instances."}
                        </div>
                      ) : (
                        <div className="space-y-3">
                          {filteredVastInstances.map((inst, index) => {
                            const status = getVastStatus(inst);
                            const canConnect = status === "online" || status === "connecting";
                            const gpuLabel = inst.gpu_name
                              ? `${inst.num_gpus ?? 1}x ${inst.gpu_name}`
                              : "GPU info pending";
                            return (
                              <motion.div
                                key={inst.id}
                                initial={{ opacity: 0, y: 8 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: index * 0.03 }}
                              >
                                <div className="flex items-center justify-between gap-3 rounded-lg border border-divider bg-content2 p-3 hover:border-primary/40 transition-colors">
                                  <div className="flex items-start gap-3 min-w-0">
                                    <AppIcon name="vast" className="w-8 h-8 shrink-0" alt="Vast.ai icon" />
                                    <div className="min-w-0">
                                      <div className="flex items-center gap-2 flex-wrap">
                                        <p className="font-medium text-sm">{getVastLabel(inst)}</p>
                                        <StatusBadge status={status} size="sm" />
                                      </div>
                                      <p className="text-xs text-foreground/50 truncate">{gpuLabel}</p>
                                      <p className="text-xs text-foreground/40">Instance #{inst.id}</p>
                                    </div>
                                  </div>
                                  <Button
                                    size="sm"
                                    color="primary"
                                    variant="flat"
                                    onPress={() => void handleQuickConnectVast(inst)}
                                    isDisabled={!canConnect}
                                  >
                                    Connect
                                  </Button>
                                </div>
                              </motion.div>
                            );
                          })}
                        </div>
                      )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <>
            {/* Terminal area - full height, tabs are now in the title bar */}
            {/* Use visibility instead of display:none to maintain container dimensions */}
            <div
              className="flex-1 min-h-0 relative border border-divider overflow-hidden bg-content1"
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
                    recipeExecutionId={s.recipeExecutionId}
                    interventionLocked={s.interventionLocked}
                    onClose={() => void closeSession(s.id)}
                  />
                </div>
              ))}
              <AnimatePresence>
                {historyPanelVisible && <TerminalHistoryPanel />}
              </AnimatePresence>
            </div>
          </>
        )}
      </div>

      {/* Recipe Automation Panel - Right Sidebar */}
      <AnimatePresence>
        {recipePanelVisible && (
          <RecipeAutomationPanel />
        )}
      </AnimatePresence>

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

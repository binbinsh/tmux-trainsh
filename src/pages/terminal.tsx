import { Card, CardBody, Chip, Input, Spinner, Tooltip } from "@nextui-org/react";
import { Button } from "../components/ui";
import { listen } from "@tauri-apps/api/event";
import { FitAddon } from "@xterm/addon-fit";
import { WebglAddon } from "@xterm/addon-webgl";
import { SearchAddon, type ISearchOptions } from "@xterm/addon-search";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import {
  getConfig,
  hostApi,
  sshCheck,
  termOpenSshTmux,
  termResize,
  termWrite,
  useHosts,
  useInteractiveExecutions,
  useRunInteractiveRecipe,
  useVastInstances,
  vastAttachSshKey,
  vastGetInstance,
  type RemoteTmuxSession,
} from "../lib/tauri-api";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { useTerminal } from "../contexts/TerminalContext";
import { AnimatePresence, motion } from "framer-motion";
import { RecipeTerminalControls } from "../components/recipe/RecipeTerminalControls";
import { TmuxSessionSelectModal } from "../components/host/TmuxSessionSelectModal";
import { copyText } from "../lib/clipboard";
import { AppIcon, type AppIconName } from "../components/AppIcon";
import { EmptyHostState, HostRow, HostSection } from "../components/shared/HostCard";
import { formatGpuCountLabel } from "../lib/gpu";
import {
  loadRecentConnections,
  removeRecentConnection,
  saveRecentConnections,
  upsertRecentConnection,
  type RecentConnection,
} from "../lib/terminal-recents";
import type { InteractiveExecution, InteractiveStatus, VastInstance } from "../lib/types";

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

// Render throttle interval in ms - target ~30fps for smooth animation (1000/30 ≈ 33ms)
// This prevents flashing during fast output like terminal animations
const RENDER_THROTTLE_MS = 33;
// Flush immediately when buffered data grows beyond this size
const MAX_BUFFERED_CHARS = 128 * 1024;

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
    case "pending":
      return "Pending";
    case "connecting":
      return "Connecting";
    case "running":
      return "Running";
    case "waiting_for_input":
      return "Waiting";
    case "paused":
      return "Paused";
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    case "cancelled":
      return "Cancelled";
    default:
      return status;
  }
}

function getExecutionTagColor(status: InteractiveStatus): "default" | "primary" | "warning" {
  switch (status) {
    case "running":
    case "waiting_for_input":
      return "primary";
    case "paused":
    case "connecting":
    case "pending":
      return "warning";
    default:
      return "default";
  }
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

function IconTerminal({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 7.5l3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0021 18V6a2.25 2.25 0 00-2.25-2.25H5.25A2.25 2.25 0 003 6v12a2.25 2.25 0 002.25 2.25z" />
    </svg>
  );
}

function IconServer({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21.75 17.25v-.228a4.5 4.5 0 00-.12-1.03l-2.268-9.64a3.375 3.375 0 00-3.285-2.602H7.923a3.375 3.375 0 00-3.285 2.602l-2.268 9.64a4.5 4.5 0 00-.12 1.03v.228m19.5 0a3 3 0 01-3 3H5.25a3 3 0 01-3-3m19.5 0a3 3 0 00-3-3H5.25a3 3 0 00-3 3m16.5 0h.008v.008h-.008v-.008zm-3 0h.008v.008h-.008v-.008z" />
    </svg>
  );
}

function IconFolder({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 6.75A2.25 2.25 0 014.5 4.5h4.379c.597 0 1.17.237 1.591.659l.621.621c.422.422.994.659 1.591.659H19.5A2.25 2.25 0 0121.75 8.25v9A2.25 2.25 0 0119.5 19.5h-15A2.25 2.25 0 012.25 17.25v-10.5z" />
    </svg>
  );
}

function IconPlay({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
    </svg>
  );
}

function IconPencil({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125" />
    </svg>
  );
}

function IconTrash({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
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
      convertEol: false, // Don't convert LF to CRLF - let the PTY handle it
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
      overviewRulerWidth: 0, // Disable overview ruler to prevent width issues
      // Monokai Light theme
      theme: {
        background: "#FFFFFF",
        foreground: "#272822",
        cursor: "#272822",
        cursorAccent: "#FFFFFF",
        selectionBackground: "#C2E8FF80",
        selectionForeground: "#272822",
        selectionInactiveBackground: "#C2E8FF50",
        // ANSI colors - Monokai Light palette
        black: "#272822",
        red: "#F92672",       // Monokai keyword pink
        green: "#A6E22E",     // Monokai green
        yellow: "#FD971F",    // Monokai param orange
        blue: "#66D9EF",      // Monokai cyan
        magenta: "#AE81FF",   // Monokai purple
        cyan: "#28C6E4",      // Monokai type cyan
        white: "#F8F8F2",
        brightBlack: "#75715E",   // Monokai comment
        brightRed: "#F92672",
        brightGreen: "#A6E22E",
        brightYellow: "#E6DB74",  // Monokai string yellow
        brightBlue: "#66D9EF",
        brightMagenta: "#AE81FF",
        brightCyan: "#28C6E4",
        brightWhite: "#F8F8F2",
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

    // Load WebGL addon for hardware acceleration (after terminal is opened)
    try {
      const webgl = new WebglAddon();
      term.loadAddon(webgl);
      webglRef.current = webgl;

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
    
    // Custom fit function that reserves extra padding to avoid edge-case jitter
    // The standard FitAddon can cause resize loops when width is at a boundary
    const customFit = () => {
      if (!termRef.current || !hostRef.current) return { cols: 0, rows: 0 };

      const term = termRef.current;
      const core = (term as unknown as { _core: { _renderService: { dimensions: { css: { cell: { width: number; height: number } } } } } })._core;
      const dims = core._renderService.dimensions;

      if (!dims?.css?.cell?.width || !dims?.css?.cell?.height) {
        return { cols: term.cols, rows: term.rows };
      }

      const cellWidth = dims.css.cell.width;
      const cellHeight = dims.css.cell.height;

      const parentElement = hostRef.current;
      const style = window.getComputedStyle(parentElement);
      const width = parentElement.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      const height = parentElement.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);

      // Calculate actual terminal dimensions
      const cols = Math.max(2, Math.floor(width / cellWidth));
      const rows = Math.max(1, Math.floor(height / cellHeight));

      if (cols !== term.cols || rows !== term.rows) {
        term.resize(cols, rows);
      }

      // IMPORTANT: Report cols-2 to PTY instead of actual cols
      //
      // Why? Full-screen terminal programs (like `uvx ny2026`) use os.get_terminal_size()
      // to determine their rendering width, then output content that fills exactly
      // that many columns. If there's any sub-pixel rounding difference between
      // what xterm.js calculates and what the program outputs, the content can
      // wrap to the next line, causing visible "jumping" or flickering.
      //
      // By telling the PTY we have 2 fewer columns than xterm.js actually renders,
      // programs will leave a 2-character margin on the right side, preventing
      // any edge-case wrapping issues.
      //
      // This was discovered while debugging `uvx ny2026` - a 60fps terminal animation
      // that would flicker unless the window was slightly widened. Termius doesn't
      // have this issue likely because they use a similar margin strategy.
      return { cols: Math.max(2, cols - 2), rows };
    };

    // Track last dimensions to avoid unnecessary resize calls
    let lastCols = 0;
    let lastRows = 0;
    let fitDebounceTimer: ReturnType<typeof setTimeout> | null = null;
    let stableSizeTimer: ReturnType<typeof setTimeout> | null = null;
    let pendingResize: { cols: number; rows: number } | null = null;

    // Send resize to PTY only after size has been stable for a period
    const sendResizeIfStable = (cols: number, rows: number) => {
      pendingResize = { cols, rows };

      if (stableSizeTimer) {
        clearTimeout(stableSizeTimer);
      }

      // Wait 100ms for size to stabilize before sending resize
      stableSizeTimer = setTimeout(() => {
        if (pendingResize && (pendingResize.cols !== lastCols || pendingResize.rows !== lastRows)) {
          lastCols = pendingResize.cols;
          lastRows = pendingResize.rows;
          void termResize(props.id, pendingResize.cols, pendingResize.rows);
        }
        pendingResize = null;
        stableSizeTimer = null;
      }, 100);
    };

    // Fit after a short delay to ensure container is fully rendered
    const doFit = () => {
      try {
        const { cols, rows } = customFit();
        // Queue resize, will only be sent after size stabilizes
        if (cols !== lastCols || rows !== lastRows) {
          sendResizeIfStable(cols, rows);
        }
      } catch {
        // ignore
      }
    };

    // Debounced fit for resize events to prevent rapid-fire resize loops
    const debouncedFit = () => {
      if (fitDebounceTimer) {
        clearTimeout(fitDebounceTimer);
      }
      fitDebounceTimer = setTimeout(doFit, 50);
    };

    // Flag to track if initial layout is complete
    let initialLayoutComplete = false;

    // Wait for container to have valid dimensions before first fit
    const waitForValidSize = (callback: () => void, maxAttempts = 10, attempt = 0) => {
      const container = hostRef.current;
      if (!container) return;

      const rect = container.getBoundingClientRect();
      // Container needs to have reasonable size (at least 100x100 pixels)
      if (rect.width >= 100 && rect.height >= 100) {
        callback();
      } else if (attempt < maxAttempts) {
        // Wait and retry
        setTimeout(() => waitForValidSize(callback, maxAttempts, attempt + 1), 50);
      } else {
        // Give up waiting, just do the fit anyway
        callback();
      }
    };

    // Initial fit after container is ready
    // Use longer delay to let React Strict Mode double-render settle
    // and for any dynamic layout elements to stabilize
    const initialFitTimer = setTimeout(() => {
      waitForValidSize(() => {
        doFit();
        // Mark layout as complete after a short delay
        setTimeout(() => {
          initialLayoutComplete = true;
        }, 150);
      });
    }, 200);

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

    // Disable ResizeObserver - it causes resize loops with terminal animations
    // Only respond to explicit window resize events
    // const parentContainer = hostRef.current.parentElement;
    const ro = new ResizeObserver(() => {
      // Intentionally empty - we only use window resize event now
    });
    // Don't observe anything

    // Also listen for window resize
    const handleWindowResize = () => {
      if (initialLayoutComplete) {
        debouncedFit();
      }
    };
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

    // Schedule a flush with simple throttling using requestAnimationFrame
    // This provides smoother animation by syncing with display refresh
    const scheduleFlush = () => {
      // If we already have a pending flush, just let it handle the accumulated data
      if (rafIdRef.current !== null) {
        return;
      }

      const now = performance.now();
      const elapsed = now - lastFlushRef.current;

      // Force immediate flush for large buffers
      if (dataBufferSizeRef.current >= MAX_BUFFERED_CHARS) {
        rafIdRef.current = requestAnimationFrame(flushBuffer);
        return;
      }

      // Throttle: wait until enough time has passed since last flush
      if (elapsed >= RENDER_THROTTLE_MS) {
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

      // Cancel any pending timers
      if (fitDebounceTimer) {
        clearTimeout(fitDebounceTimer);
      }
      if (stableSizeTimer) {
        clearTimeout(stableSizeTimer);
      }
      clearTimeout(initialFitTimer);

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
      if (webglRef.current) webglRef.current.dispose();
      if (searchRef.current) searchRef.current.dispose();
      term.dispose();
      termRef.current = null;
      fitRef.current = null;
      searchRef.current = null;
      webglRef.current = null;
    };
  }, [props.id]);

  // Track previous active state to only trigger on actual activation
  const wasActiveRef = useRef(props.active);

  useEffect(() => {
    const wasActive = wasActiveRef.current;
    wasActiveRef.current = props.active;

    if (props.active && termRef.current && fitRef.current) {
      termRef.current.focus();

      // Only re-fit if we're transitioning from inactive to active (not on initial render)
      // This prevents double-fitting when switching from other pages
      if (!wasActive) {
        // Use a single RAF to batch the fit and refresh together
        requestAnimationFrame(() => {
          if (!termRef.current) return;
          try {
            // Just refresh, don't resize - size should already be correct
            // Resizing here can cause jitter with full-screen terminal apps
            termRef.current.refresh(0, termRef.current.rows - 1);
          } catch {
            // ignore
          }
        });
      }
    }
  }, [props.active, props.id]);

  return <div ref={hostRef} className="h-full w-full bg-content1 overflow-hidden absolute inset-0" />;
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
    addRecipeTerminal,
    isLoading,
    recipeDetailsExpanded,
    toggleRecipeDetails,
    workspaceVisible,
    setWorkspaceVisible,
    removeCurrentPlaceholder,
    createNewTab,
  } = useTerminal();
  const hostsQuery = useHosts();
  const vastQuery = useVastInstances();
  const executionsQuery = useInteractiveExecutions();
  const runRecipeMutation = useRunInteractiveRecipe();

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
  const [selectedRecipePath, setSelectedRecipePath] = useState<string | null>(null);

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
      upsertRecentConnection(prev, { id: `host:${hostId}`, kind: "host", host_id: hostId, label })
    );
  }

  function recordVastConnection(instanceId: number, label: string) {
    persistRecentConnections((prev) =>
      upsertRecentConnection(prev, { id: `vast:${instanceId}`, kind: "vast", vast_instance_id: instanceId, label })
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

  const recipeHistory = useMemo(() => {
    const sorted = [...executions].sort((a, b) => b.created_at.localeCompare(a.created_at));
    const seen = new Set<string>();
    const out: InteractiveExecution[] = [];
    for (const exec of sorted) {
      if (seen.has(exec.recipe_path)) continue;
      seen.add(exec.recipe_path);
      out.push(exec);
      if (out.length >= 12) break;
    }

    const needle = launcherQuery.trim().toLowerCase();
    if (!needle) return out;
    return out.filter((exec) => {
      const haystack = `${exec.recipe_name} ${exec.recipe_path} ${exec.host_id} ${exec.status}`.toLowerCase();
      return haystack.includes(needle);
    });
  }, [executions, launcherQuery]);

  useEffect(() => {
    if (!selectedRecipePath) return;
    if (!recipeHistory.some((e) => e.recipe_path === selectedRecipePath)) {
      setSelectedRecipePath(null);
    }
  }, [recipeHistory, selectedRecipePath]);

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
    if (!selectedRecipePath) return null;
    return recipeHistory.find((e) => e.recipe_path === selectedRecipePath) ?? null;
  }, [recipeHistory, selectedRecipePath]);

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
  }, [openLocalTerminal, recordLocalConnection, removeCurrentPlaceholder, setActiveId, setWorkspaceVisible]);

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

      const execution = await runRecipeMutation.mutateAsync({
        path: exec.recipe_path,
        hostId: exec.host_id,
        variables,
      });

      if (!execution.terminal_id) {
        throw new Error("Execution did not return a terminal session");
      }

      addRecipeTerminal({
        id: execution.terminal_id,
        title: `Recipe: ${execution.recipe_name}`,
        recipeExecutionId: execution.id,
        hostId: execution.host_id,
      });
      recordConnectionByHostId(execution.host_id);
    } catch (e) {
      console.error("Failed to run recipe from terminal launcher:", e);
      setLauncherError(getErrorMessage(e));
    }
  }, [addRecipeTerminal, recordConnectionByHostId, removeCurrentPlaceholder, runRecipeMutation, setActiveId, setWorkspaceVisible]);

  const launcherPrimaryLabel = selectedRecipePath ? "Run" : "Connect";
  const canLauncherPrimary = Boolean(selectedRecipePath ? selectedExecution : selectedRecent);
  const launcherPrimaryLoading = selectedRecipePath ? runRecipeMutation.isPending : false;

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
      // Remove placeholder tab before connecting
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

      // If there are existing sessions, show the selection modal to let user choose
      // or create a new session
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

      // No existing sessions - create a new "main" session
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
    [openSshTmux, recordHostConnection, removeCurrentPlaceholder, setActiveId]
  );

  const connectToVastInstance = useCallback(
    async (instanceId: number, label?: string) => {
      // Remove placeholder tab before connecting
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
              kind: "vast",
              hostId: null, // No host ID for Vast instances
              vastInstanceId: instanceId,
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
          recordVastConnection(instanceId, label ?? `Vast #${instanceId}`);
          setConnectState({ status: "idle" });
          return;
        } catch (e) {
          lastError = e;
        }
      }

      throw lastError ?? new Error("SSH connection failed");
    },
    [openSshTmux, recordVastConnection, removeCurrentPlaceholder, setActiveId]
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

  // If navigated here with a connect request, start connecting immediately and show the waiting UI here.
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

  // Keep refs in sync with state for keyboard handler
  const activeIdRef = useRef(activeId);
  useEffect(() => {
    activeIdRef.current = activeId;
  }, [activeId]);

  // Toggle search with Cmd+F (not Ctrl+F to allow emacs keybinding), toggle recipe details with Cmd+]
  // Close terminal with Cmd+W, open new terminal with Cmd+T
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Toggle search with Cmd+F only (Ctrl+F reserved for emacs forward)
      if (e.metaKey && !e.ctrlKey && e.key === "f") {
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

      // Toggle recipe details with Cmd+]
      if (e.metaKey && e.key === "]") {
        e.preventDefault();
        e.stopPropagation();
        toggleRecipeDetails();
        return;
      }

      // Close current terminal with Cmd+W
      if (e.metaKey && e.key === "w") {
        e.preventDefault();
        e.stopPropagation();
        if (activeIdRef.current) {
          void closeSession(activeIdRef.current);
        }
        return;
      }

      // Open new tab with Cmd+T (same as + button - shows workspace)
      if (e.metaKey && e.key === "t") {
        e.preventDefault();
        e.stopPropagation();
        createNewTab();
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
  }, [closeSession, createNewTab, toggleRecipeDetails]); // Stable callbacks from context

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
              {/* Termius-style Toolbar */}
              <div className="termius-toolbar">
                {/* Row 1: Search + Primary Action */}
                <div className="termius-toolbar-row">
                  <div className="termius-search-bar">
                    <Input
                      size="lg"
                      placeholder="Search recent connections & recipes..."
                      value={launcherQuery}
                      onValueChange={setLauncherQuery}
                      startContent={<SearchIcon className="w-5 h-5 text-foreground/40" />}
                      endContent={
                        <Button
                          color="primary"
                          size="sm"
                          className="h-8 px-4"
                          onPress={() => void handleLauncherPrimary()}
                          isDisabled={!canLauncherPrimary || launcherPrimaryLoading}
                          isLoading={launcherPrimaryLoading}
                        >
                          {launcherPrimaryLabel}
                        </Button>
                      }
                      classNames={{
                        base: "flex-1",
                        inputWrapper: "bg-content2 h-12",
                        input: "text-base",
                      }}
                    />
                  </div>
                </div>

                {/* Row 2: Quick Actions */}
                <div className="termius-toolbar-row justify-between">
                  <div className="termius-quick-actions">
                    <button
                      className="termius-quick-action"
                      onClick={() => void launchLocalTerminal()}
                    >
                      <IconTerminal className="w-4 h-4" />
                      <span>Local Terminal</span>
                    </button>
                    <button className="termius-quick-action" onClick={() => navigate({ to: "/hosts" })}>
                      <IconServer className="w-4 h-4" />
                      <span>Hosts</span>
                    </button>
                    <button className="termius-quick-action" onClick={() => navigate({ to: "/recipes" })}>
                      <IconFolder className="w-4 h-4" />
                      <span>Recipes</span>
                    </button>
                  </div>

                  {sessions.length > 0 && (
                    <button
                      className="termius-quick-action"
                      onClick={() => setWorkspaceVisible(false)}
                    >
                      <span>Back</span>
                    </button>
                  )}
                </div>
              </div>

              {(launcherError ||
                hostsQuery.error ||
                vastQuery.error ||
                executionsQuery.error) && (
                <Card className="mb-4 border border-divider">
                  <CardBody className="py-3">
                    {launcherError && (
                      <p className="text-sm text-danger whitespace-pre-wrap">{launcherError}</p>
                    )}
                    {!launcherError && (
                      <p className="text-sm text-danger whitespace-pre-wrap">
                        {getErrorMessage(hostsQuery.error ?? vastQuery.error ?? executionsQuery.error)}
                      </p>
                    )}
                  </CardBody>
                </Card>
              )}

              {launcherIsLoading ? (
                <div className="flex items-center justify-center py-12">
                  <Spinner size="lg" />
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
                              icon={<AppIcon name="ssh" className="w-4 h-4" alt="Local" />}
                              title="Local"
                              subtitle="On this machine"
                              isOnline={true}
                              isSelected={isSelected}
                              onClick={() => {
                                setSelectedRecentId(conn.id);
                                setSelectedRecipePath(null);
                              }}
                              onDoubleClick={() => void launchRecentConnection(conn)}
                              hoverActions={
                                <div
                                  className="flex items-center gap-1"
                                  onMouseDown={(e) => e.stopPropagation()}
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  <Tooltip content="Forget" delay={500}>
                                    <Button
                                      size="sm"
                                      variant="light"
                                      isIconOnly
                                      className="w-7 h-7 min-w-7 opacity-60 hover:opacity-100 text-danger"
                                      onPress={() => {
                                        persistRecentConnections((prev) => removeRecentConnection(prev, conn.id));
                                        setSelectedRecentId((prev) => (prev === conn.id ? null : prev));
                                      }}
                                    >
                                      <IconTrash className="w-3.5 h-3.5" />
                                    </Button>
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
                              icon={<AppIcon name={iconName} className="w-4 h-4" alt={host?.type ?? "Host"} />}
                              title={title}
                              subtitle={subtitle}
                              rightTags={rightTags}
                              isOnline={host?.status === "online"}
                              isSelected={isSelected}
                              onClick={() => {
                                setSelectedRecentId(conn.id);
                                setSelectedRecipePath(null);
                              }}
                              onDoubleClick={() => void launchRecentConnection(conn)}
                              hoverActions={
                                <div
                                  className="flex items-center gap-1"
                                  onMouseDown={(e) => e.stopPropagation()}
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  <Tooltip content="Forget" delay={500}>
                                    <Button
                                      size="sm"
                                      variant="light"
                                      isIconOnly
                                      className="w-7 h-7 min-w-7 opacity-60 hover:opacity-100 text-danger"
                                      onPress={() => {
                                        persistRecentConnections((prev) => removeRecentConnection(prev, conn.id));
                                        setSelectedRecentId((prev) => (prev === conn.id ? null : prev));
                                      }}
                                    >
                                      <IconTrash className="w-3.5 h-3.5" />
                                    </Button>
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
                            icon={<AppIcon name="vast" className="w-4 h-4" alt="Vast.ai" />}
                            title={title}
                            subtitle={subtitle}
                            rightTags={rightTags}
                            isOnline={inst ? isVastInstanceOnline(inst) : false}
                            isSelected={isSelected}
                            onClick={() => {
                              setSelectedRecentId(conn.id);
                              setSelectedRecipePath(null);
                            }}
                            onDoubleClick={() => void launchRecentConnection(conn)}
                            hoverActions={
                              <div
                                className="flex items-center gap-1"
                                onMouseDown={(e) => e.stopPropagation()}
                                onClick={(e) => e.stopPropagation()}
                              >
                                <Tooltip content="Forget" delay={500}>
                                  <Button
                                    size="sm"
                                    variant="light"
                                    isIconOnly
                                    className="w-7 h-7 min-w-7 opacity-60 hover:opacity-100 text-danger"
                                    onPress={() => {
                                      persistRecentConnections((prev) => removeRecentConnection(prev, conn.id));
                                      setSelectedRecentId((prev) => (prev === conn.id ? null : prev));
                                    }}
                                  >
                                    <IconTrash className="w-3.5 h-3.5" />
                                  </Button>
                                </Tooltip>
                              </div>
                            }
                          />
                        );
                      })}
                    </HostSection>
                  )}

                  {recipeHistory.length > 0 && (
                    <HostSection title="RECENT RECIPES" count={recipeHistory.length}>
                      {recipeHistory.map((exec) => {
                        const hostName = hostNameById.get(exec.host_id) || exec.host_id;
                        const isSelected = selectedRecipePath === exec.recipe_path;
                        const rightTags: { label: string; color?: "default" | "primary" | "warning" }[] = [
                          { label: getExecutionStatusLabel(exec.status), color: getExecutionTagColor(exec.status) },
                        ];

                        return (
                          <HostRow
                            key={exec.recipe_path}
                            icon={<span className="text-lg">📜</span>}
                            title={exec.recipe_name}
                            subtitle={`${hostName} · ${new Date(exec.created_at).toLocaleString()}`}
                            rightTags={rightTags}
                            isOnline={exec.status === "running" || exec.status === "waiting_for_input"}
                            isSelected={isSelected}
                            onClick={() => {
                              setSelectedRecipePath(exec.recipe_path);
                              setSelectedRecentId(null);
                            }}
                            onDoubleClick={() => void launchExecution(exec)}
                            hoverActions={
                              <div
                                className="flex items-center gap-1"
                                onMouseDown={(e) => e.stopPropagation()}
                                onClick={(e) => e.stopPropagation()}
                              >
                                <Tooltip content="Run" delay={500}>
                                  <Button
                                    size="sm"
                                    variant="light"
                                    isIconOnly
                                    className="w-7 h-7 min-w-7 opacity-60 hover:opacity-100"
                                    onPress={() => void launchExecution(exec)}
                                  >
                                    <IconPlay className="w-3.5 h-3.5" />
                                  </Button>
                                </Tooltip>
                                <Tooltip content="Open" delay={500}>
                                  <Button
                                    size="sm"
                                    variant="light"
                                    isIconOnly
                                    className="w-7 h-7 min-w-7 opacity-60 hover:opacity-100"
                                    onPress={() => {
                                      navigate({ to: "/recipes/$path", params: { path: encodeURIComponent(exec.recipe_path) } });
                                    }}
                                  >
                                    <IconPencil className="w-3.5 h-3.5" />
                                  </Button>
                                </Tooltip>
                              </div>
                            }
                          />
                        );
                      })}
                    </HostSection>
                  )}

                  {filteredRecentConnections.length === 0 && recipeHistory.length === 0 && (
                    <EmptyHostState
                      icon={<IconTerminal className="w-5 h-5" />}
                      title={launcherQuery ? "No matches" : "Nothing recent yet"}
                      description={launcherQuery ? "Try a different search term." : "Connect to a host or run a recipe to see it here."}
                      action={
                        !launcherQuery ? (
                          <div className="flex items-center gap-2">
                            <Button as={Link} to="/hosts" variant="flat">
                              Go to Hosts
                            </Button>
                            <Button as={Link} to="/recipes" variant="flat">
                              Go to Recipes
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
          <>
            {/* Recipe Terminal Controls - shows when active terminal has a recipe */}
            {activeId && sessions.find((s) => s.id === activeId)?.recipeExecutionId && (
              <RecipeTerminalControls
                terminalId={activeId}
                executionId={sessions.find((s) => s.id === activeId)?.recipeExecutionId}
              />
            )}
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
            </div>
          </>
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

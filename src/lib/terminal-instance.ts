/**
 * Terminal Instance - VSCode-level optimized terminal handling
 *
 * Features:
 * - WebGL GPU-accelerated rendering with automatic fallback
 * - Smart resize debouncing based on buffer size
 * - Output buffering for high-throughput scenarios
 * - Adaptive smooth scrolling (mouse wheel vs trackpad)
 * - Unicode11 support for emoji/CJK characters
 */

import { Terminal, type ITerminalOptions, type IDisposable, type ITheme } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { SearchAddon, type ISearchOptions } from "@xterm/addon-search";
import { SerializeAddon } from "@xterm/addon-serialize";
import { WebglAddon } from "@xterm/addon-webgl";
import { Unicode11Addon } from "@xterm/addon-unicode11";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { termWrite, termResize, termHistoryTail } from "./tauri-api";
import { getTerminalTheme, DEFAULT_TERMINAL_THEME, type TerminalThemeName } from "./terminal-themes";
import { getTerminalSnapshot, setTerminalSnapshot } from "./terminal-state-cache";

// Performance constants
const RESIZE_DEBOUNCE_MS = 50;       // Faster resize response (was 100ms)
const BACKEND_RESIZE_DEBOUNCE_MS = 100; // Debounce PTY resize calls (horizontal reflow is expensive)
const HISTORY_LOAD_LIMIT = 256 * 1024; // Load up to 256KB of history on init
const FIT_RETRY_FRAMES = 30; // Retry fit across frames when metrics are not ready (was 20)
const MIN_CONTAINER_SIZE = 50; // Minimum container size in pixels (was 80)
const OUTPUT_THROTTLE_MS = 8; // Buffer PTY output for smoother rendering under high throughput
const START_DEBOUNCING_THRESHOLD = 200; // Only debounce resize if buffer has >= this many lines (VSCode strategy)
const SMOOTH_SCROLL_DURATION = 125; // Smooth scrolling duration for physical mouse wheel (ms)

// Base terminal options (theme applied separately)
const BASE_TERMINAL_OPTIONS: Omit<ITerminalOptions, "theme"> = {
  scrollback: 10000,
  convertEol: false,
  cursorBlink: true,
  cursorStyle: "bar",
  fontFamily: "'JetBrains Mono', 'Fira Code', 'SF Mono', Menlo, Monaco, monospace",
  fontSize: 14,
  fontWeight: "400",
  fontWeightBold: "600",
  lineHeight: 1.25,
  letterSpacing: 0,
  macOptionIsMeta: true,
  macOptionClickForcesSelection: true,
  allowProposedApi: true,
  minimumContrastRatio: 4.5,
  smoothScrollDuration: 0,
  // Performance and UX options (VSCode parity)
  fastScrollSensitivity: 5,
  scrollSensitivity: 1,
  altClickMovesCursor: true,
  drawBoldTextInBrightColors: true,
  rescaleOverlappingGlyphs: true,
  cursorInactiveStyle: "outline",
  tabStopWidth: 8,
  windowOptions: {
    getWinSizePixels: true,
    getWinSizeChars: true,
    getCellSizePixels: true,
  },
};

function stripTerminalQuerySequences(data: string): string {
  return data
    .replaceAll("\x1b[c", "") // DA1 request
    .replaceAll("\x1b[>c", "") // DA2 request
    .replaceAll("\x1b[>0c", "") // DA2 request (param 0)
    .replaceAll("\x1b[6n", "") // DSR cursor position request
    .replaceAll("\x1b[5n", "") // DSR status request
    .replaceAll("\x9bc", "") // 8-bit CSI DA1
    .replaceAll("\x9b>c", "") // 8-bit CSI DA2
    .replaceAll("\x9b6n", "") // 8-bit CSI DSR cursor position
    .replaceAll("\x9b5n", ""); // 8-bit CSI DSR status
}

function trimHistoryToSafeBoundary(data: string): string {
  if (data.length === 0) return data;
  const firstChar = data[0];
  if (firstChar === "\x1b" || firstChar === "\n" || firstChar === "\r") return data;

  const lookahead = data.slice(0, 4096);
  const escIndex = lookahead.indexOf("\x1b");
  if (escIndex <= 0) return data;

  const newlineIndex = lookahead.lastIndexOf("\n", escIndex);
  if (newlineIndex >= 0) {
    return data.slice(newlineIndex + 1);
  }
  return data.slice(escIndex);
}

export interface TerminalInstanceConfig {
  id: string;
  container: HTMLElement;
  interventionLocked?: boolean;
  themeName?: TerminalThemeName;
  onSearchResult?: (current: number, total: number) => void;
  onExit?: () => void;
  onAltBufferChange?: (active: boolean) => void; // Called when alt buffer state changes (tmux, vim, etc.)
}

export interface SearchState {
  query: string;
  options: ISearchOptions;
}

/**
 * Terminal instance with VSCode-level optimizations
 */
export class TerminalInstance {
  // Static WebGL fallback state - shared across all terminals
  // If WebGL fails once, all future terminals use DOM renderer to avoid repeated failures
  private static _suggestedRendererType: "webgl" | "dom" | undefined = undefined;

  private readonly id: string;
  private readonly container: HTMLElement;
  private terminal: Terminal | null = null;
  private fitAddon: FitAddon | null = null;
  private searchAddon: SearchAddon | null = null;
  private serializeAddon: SerializeAddon | null = null;
  private webglAddon: WebglAddon | null = null;
  private unicode11Addon: Unicode11Addon | null = null;

  // Resize handling
  private fitTimer: number | null = null;
  private backendResizeTimer: number | null = null;
  private lastCols = 0;
  private lastRows = 0;
  private fitRetryRaf: number | null = null;
  private fitRetryRunId = 0;

  // Smooth scrolling - track mouse wheel type
  private isPhysicalMouseWheel = true;

  // Event listeners
  private unlistenData: UnlistenFn | null = null;
  private unlistenExit: UnlistenFn | null = null;
  private resizeObserver: ResizeObserver | null = null;
  private terminalDataDisposable: IDisposable | null = null;

  // State
  private interventionLocked: boolean;
  private themeName: TerminalThemeName;
  private hasExited = false;
  private isDisposed = false;
  private historyLoaded = false;
  private isReplayingHistory = false;
  private restoredFromSnapshot = false; // Track if restored from snapshot (avoid redundant PTY resize)
  private initializing = false; // Track if we're still in initialization phase
  private altBufferActive = false; // Track alt buffer state (tmux, vim, etc.)

  // Output buffering for high-throughput scenarios
  private outputBuffer: string[] = [];
  private outputTimer: number | null = null;

  // Callbacks
  private onSearchResult?: (current: number, total: number) => void;
  private onExit?: () => void;
  private onAltBufferChange?: (active: boolean) => void;

  constructor(config: TerminalInstanceConfig) {
    this.id = config.id;
    this.container = config.container;
    this.interventionLocked = config.interventionLocked ?? false;
    this.themeName = config.themeName ?? DEFAULT_TERMINAL_THEME;
    this.onSearchResult = config.onSearchResult;
    this.onExit = config.onExit;
    this.onAltBufferChange = config.onAltBufferChange;
  }

  /**
   * Initialize the terminal and all addons
   */
  async initialize(): Promise<void> {
    if (this.isDisposed) return;
    this.initializing = true;

    // Create terminal with base options and current theme
    const options: ITerminalOptions = {
      ...BASE_TERMINAL_OPTIONS,
      theme: getTerminalTheme(this.themeName),
    };
    this.terminal = new Terminal(options);

    // Load FitAddon first (required for proper sizing)
    this.fitAddon = new FitAddon();
    this.terminal.loadAddon(this.fitAddon);

    // Load SearchAddon
    this.searchAddon = new SearchAddon();
    this.terminal.loadAddon(this.searchAddon);

    // Load SerializeAddon (for state snapshots)
    this.serializeAddon = new SerializeAddon();
    this.terminal.loadAddon(this.serializeAddon);

    // Load Unicode11Addon for proper emoji/CJK support
    this.unicode11Addon = new Unicode11Addon();
    this.terminal.loadAddon(this.unicode11Addon);
    this.terminal.unicode.activeVersion = "11";

    if (this.onSearchResult) {
      this.searchAddon.onDidChangeResults((e) => {
        if (e) {
          this.onSearchResult?.(e.resultIndex + 1, e.resultCount);
        } else {
          this.onSearchResult?.(0, 0);
        }
      });
    }

    // Open terminal in container
    this.terminal.open(this.container);

    // Load WebglAddon for GPU-accelerated rendering (must be after open)
    this.loadWebglAddon();

    // Setup alt buffer detection (for tmux, vim, etc.)
    this.setupAltBufferDetection();

    // Setup direct input handling (no buffering)
    this.setupInputHandling();

    // Setup event listeners
    await this.setupEventListeners();

    // Restore previous snapshot (route switches, tab switches)
    const snapshot = getTerminalSnapshot(this.id);
    if (snapshot) {
      this.isReplayingHistory = true;
      this.restoredFromSnapshot = true; // Mark that PTY size is already synced from previous session
      await new Promise<void>((resolve) => {
        if (this.isDisposed || !this.terminal) {
          resolve();
          return;
        }
        this.terminal.write(snapshot, () => resolve());
      });
      this.isReplayingHistory = false;
      this.historyLoaded = true;
    }

    // Load terminal history from backend
    await this.loadHistory();

    // Setup resize handling after history/snapshot replay to avoid SIGWINCH/redraw noise
    // during initialization (especially under React StrictMode dev remounts).
    this.setupResizeHandling();

    // Initial fit with multiple attempts to ensure container is properly sized
    // Use requestAnimationFrame for better timing with browser layout
    const performInitialFit = () => {
      if (this.isDisposed) return;
      this.fit();
      this.terminal?.scrollToBottom();
      this.refresh();
      this.focus();
    };

    // First attempt after initial layout
    requestAnimationFrame(() => {
      performInitialFit();
      // Second attempt after a short delay for edge cases (sidebar animations, etc.)
      setTimeout(() => {
        if (!this.isDisposed) {
          this.fit();
          // Mark initialization as complete after all initial fits are done
          // This allows subsequent resize events to send to backend
          this.initializing = false;
        }
      }, 100);
    });
  }

  /**
   * Load terminal history from backend
   * This ensures terminal content is preserved when switching tabs
   */
  private async loadHistory(): Promise<void> {
    if (this.isDisposed || !this.terminal || this.historyLoaded) return;

    try {
      const history = await termHistoryTail({ id: this.id, limit: HISTORY_LOAD_LIMIT });
      if (!history.data || history.data.length === 0) {
        this.historyLoaded = true;
        return;
      }

      const sanitized = trimHistoryToSafeBoundary(stripTerminalQuerySequences(history.data));
      if (sanitized.length === 0) {
        this.historyLoaded = true;
        return;
      }

      this.isReplayingHistory = true;
      await new Promise<void>((resolve) => {
        if (this.isDisposed || !this.terminal) {
          resolve();
          return;
        }
        this.terminal.write(sanitized, () => resolve());
      });
      this.isReplayingHistory = false;
      this.historyLoaded = true;
    } catch (e) {
      console.warn("[TerminalInstance] Failed to load history:", e);
      // Don't mark as loaded on error - we may want to retry
    } finally {
      this.isReplayingHistory = false;
    }
  }

  /**
   * Load WebGL addon for GPU-accelerated rendering
   * Falls back to DOM renderer on failure or context loss
   * Uses static fallback state to avoid repeated failures across terminals
   */
  private loadWebglAddon(): void {
    if (!this.terminal) return;

    // Skip WebGL if it previously failed (VSCode strategy)
    if (TerminalInstance._suggestedRendererType === "dom") {
      return;
    }

    try {
      // Note: customGlyphs option requires newer WebglAddon version
      // Current version (0.19.0) only supports preserveDrawingBuffer
      this.webglAddon = new WebglAddon();

      // Handle WebGL context loss - fall back to DOM renderer
      this.webglAddon.onContextLoss(() => {
        console.warn("[TerminalInstance] WebGL context lost, falling back to DOM renderer");
        TerminalInstance._suggestedRendererType = "dom";
        this.webglAddon?.dispose();
        this.webglAddon = null;
      });

      this.terminal.loadAddon(this.webglAddon);
      TerminalInstance._suggestedRendererType = "webgl";
    } catch (e) {
      console.warn("[TerminalInstance] WebGL not available, using DOM renderer:", e);
      TerminalInstance._suggestedRendererType = "dom";
      this.webglAddon = null;
    }
  }

  /**
   * Setup alt buffer detection for tmux, vim, and other full-screen applications
   * Alt buffer is used by applications that need a separate screen (tmux, vim, less, etc.)
   * This allows the parent component to adjust behavior (e.g., disable certain shortcuts)
   */
  private setupAltBufferDetection(): void {
    if (!this.terminal) return;

    // xterm.js buffer object provides activeBuffer type
    // When alt buffer is active, buffer.active.type === 'alternate'
    // We check on each write since there's no direct event for buffer switch
    const checkAltBuffer = () => {
      if (!this.terminal) return;
      const isAlt = this.terminal.buffer.active.type === "alternate";
      if (isAlt !== this.altBufferActive) {
        this.altBufferActive = isAlt;
        this.onAltBufferChange?.(isAlt);
      }
    };

    // Check after each write completes
    const originalWrite = this.terminal.write.bind(this.terminal);
    this.terminal.write = (data: string | Uint8Array, callback?: () => void) => {
      originalWrite(data, () => {
        checkAltBuffer();
        callback?.();
      });
    };
  }

  /**
   * Setup direct input handling - no buffering for instant responsiveness
   */
  private setupInputHandling(): void {
    if (!this.terminal) return;

    this.terminalDataDisposable = this.terminal.onData((data) => {
      if (this.isReplayingHistory) {
        return;
      }

      // Block input when intervention is locked (except Ctrl+C for interrupts)
      if (this.interventionLocked && data !== "\x03") {
        return;
      }

      // Send directly to backend - no buffering
      void termWrite(this.id, data);
    });
  }

  /**
   * Setup resize handling with smart debouncing (VSCode strategy)
   * - Rows resize immediately (cheap)
   * - Cols resize debounced (expensive due to text reflow)
   * - Small buffers resize immediately
   */
  private setupResizeHandling(): void {
    if (!this.container) return;

    this.resizeObserver = new ResizeObserver(() => {
      this.scheduleResize();
    });
    this.resizeObserver.observe(this.container);

    // Also listen for window resize
    window.addEventListener("resize", this.handleWindowResize);

    // Setup smooth scrolling detection (VSCode strategy)
    // Physical mouse wheels get smooth scrolling, trackpads don't
    this.container.addEventListener("wheel", this.handleWheel, { passive: true });
  }

  private handleWindowResize = (): void => {
    this.scheduleResize();
  };

  private handleWheel = (e: WheelEvent): void => {
    // Simplified mouse wheel classification (inspired by VSCode's MouseWheelClassifier)
    // Physical mouse wheels typically:
    // - Have deltaMode === 1 (lines) or large discrete deltaY values
    // - Move on only one axis at a time
    // - Have integer delta values
    // Trackpads typically:
    // - Have deltaMode === 0 (pixels)
    // - Have small, fractional delta values
    // - May move on both axes simultaneously

    const hasBothAxes = Math.abs(e.deltaX) > 0 && Math.abs(e.deltaY) > 0;
    const isLineDeltaMode = e.deltaMode === 1; // DOM_DELTA_LINE
    const hasNonIntegerDelta = !Number.isInteger(e.deltaX) || !Number.isInteger(e.deltaY);

    // If moving on both axes or has non-integer deltas, likely trackpad
    if (hasBothAxes || hasNonIntegerDelta) {
      this.isPhysicalMouseWheel = false;
    } else if (isLineDeltaMode) {
      // Line delta mode is typically physical mouse wheel
      this.isPhysicalMouseWheel = true;
    }
    // Otherwise keep previous state (don't flip-flop)

    if (this.terminal) {
      this.terminal.options.smoothScrollDuration =
        this.isPhysicalMouseWheel ? SMOOTH_SCROLL_DURATION : 0;
    }
  };

  private scheduleResize(): void {
    if (!this.terminal) return;

    // VSCode strategy: small buffers resize immediately (no debounce)
    const bufferLines = this.terminal.buffer.active.length;
    if (bufferLines < START_DEBOUNCING_THRESHOLD) {
      this.fit();
      return;
    }

    // Large buffers: debounce to avoid expensive reflow
    if (this.fitTimer !== null) {
      clearTimeout(this.fitTimer);
    }

    this.fitTimer = window.setTimeout(() => {
      this.fitTimer = null;
      this.fit();
    }, RESIZE_DEBOUNCE_MS);
  }

  /**
   * Setup event listeners for PTY output and exit
   */
  private async setupEventListeners(): Promise<void> {
    // Listen for output data
    const unlistenData = await listen<{ id: string; data: string }>("term:data", (evt) => {
      if (evt.payload.id === this.id) {
        this.handleOutput(evt.payload.data);
      }
    });
    if (this.isDisposed) {
      unlistenData();
      return;
    }
    this.unlistenData = unlistenData;

    // Listen for exit
    const unlistenExit = await listen<{ id: string }>("term:exit", (evt) => {
      if (evt.payload.id === this.id) {
        this.handleExit();
      }
    });
    if (this.isDisposed) {
      unlistenExit();
      this.unlistenData?.();
      this.unlistenData = null;
      return;
    }
    this.unlistenExit = unlistenExit;
  }

  /**
   * Handle output data - buffered write for smoother rendering under high throughput
   */
  private handleOutput(data: string): void {
    if (this.isDisposed || !this.terminal) return;
    // Skip output during history/snapshot replay to avoid duplicates
    if (this.isReplayingHistory) return;

    // Buffer output and flush after a short delay for smoother rendering
    this.outputBuffer.push(data);
    if (this.outputTimer === null) {
      this.outputTimer = window.setTimeout(() => {
        this.flushOutput();
      }, OUTPUT_THROTTLE_MS);
    }
  }

  /**
   * Flush buffered output to terminal
   */
  private flushOutput(): void {
    if (this.isDisposed || !this.terminal || this.outputBuffer.length === 0) return;
    const data = this.outputBuffer.join("");
    this.outputBuffer = [];
    this.outputTimer = null;
    this.terminal.write(data);
  }

  /**
   * Handle terminal exit
   */
  private handleExit(): void {
    if (this.hasExited) return;
    this.hasExited = true;

    if (this.terminal) {
      this.terminal.write("\r\n[Session ended] Terminal tab kept open for debugging.\r\n");
    }

    this.onExit?.();
  }

  /**
   * Fit terminal to container and notify backend of new size
   */
  fit(): void {
    if (this.isDisposed || !this.terminal || !this.fitAddon || !this.container) return;

    // Cancel any in-flight retry loop and start a fresh run.
    this.fitRetryRunId += 1;
    const runId = this.fitRetryRunId;

    if (this.fitRetryRaf !== null) {
      cancelAnimationFrame(this.fitRetryRaf);
      this.fitRetryRaf = null;
    }

    const attemptFit = (attempt: number): void => {
      if (this.isDisposed || runId !== this.fitRetryRunId) return;

      const ok = this.fitOnce();
      if (ok || attempt >= FIT_RETRY_FRAMES) return;

      this.fitRetryRaf = requestAnimationFrame(() => {
        this.fitRetryRaf = null;
        attemptFit(attempt + 1);
      });
    };

    attemptFit(0);
  }

  private fitOnce(): boolean {
    if (this.isDisposed || !this.terminal || !this.fitAddon || !this.container) return false;

    const rect = this.container.getBoundingClientRect();
    if (rect.width < MIN_CONTAINER_SIZE || rect.height < MIN_CONTAINER_SIZE) return false;

    try {
      const proposed = this.fitAddon.proposeDimensions();
      if (!proposed) return false;

      const cols = Math.max(2, proposed.cols);
      const rows = Math.max(1, proposed.rows);

      // Only resize if dimensions changed
      if (cols !== this.terminal.cols || rows !== this.terminal.rows) {
        this.terminal.resize(cols, rows);
      }

      // Sync PTY size after a successful fit calculation.
      // This prevents tmux/shell from keeping the old 80x24 after remount.
      // IMPORTANT: Skip backend resize during initialization if restored from snapshot -
      // the PTY already has the correct size from the previous session, and sending
      // resize would trigger SIGWINCH causing extra PS1 prompt redraws.
      if (cols !== this.lastCols || rows !== this.lastRows) {
        this.lastCols = cols;
        this.lastRows = rows;

        // Skip ALL backend resizes during initialization if we restored from snapshot
        // This prevents multiple SIGWINCH signals from the multiple fit() calls
        if (this.restoredFromSnapshot && this.initializing) {
          return true;
        }

        // Clear the snapshot flag after initialization completes
        if (this.restoredFromSnapshot && !this.initializing) {
          this.restoredFromSnapshot = false;
        }

        if (this.backendResizeTimer !== null) {
          clearTimeout(this.backendResizeTimer);
        }
        this.backendResizeTimer = window.setTimeout(() => {
          this.backendResizeTimer = null;
          void termResize(this.id, cols, rows).catch((e) => {
            console.warn("[TerminalInstance] Backend resize failed:", e);
          });
        }, BACKEND_RESIZE_DEBOUNCE_MS);
      }
      return true;
    } catch (e) {
      console.warn("[TerminalInstance] Fit error:", e);
      return false;
    }
  }

  /**
   * Focus the terminal
   */
  focus(): void {
    if (this.isDisposed) return;
    this.terminal?.focus();
  }

  /**
   * Refresh the terminal display
   */
  refresh(): void {
    if (this.isDisposed || !this.terminal) return;
    try {
      this.terminal.refresh(0, this.terminal.rows - 1);
    } catch (e) {
      // Ignore refresh errors
    }
  }

  /**
   * Activate the terminal - called when it becomes visible/active
   * Ensures history is loaded and display is refreshed
   */
  async activate(): Promise<void> {
    if (this.isDisposed || !this.terminal) return;

    // Load history if not already loaded
    if (!this.historyLoaded) {
      await this.loadHistory();
    }

    // Fit and refresh
    this.fit();
    this.terminal.scrollToBottom();
    this.refresh();
    this.focus();
  }

  /**
   * Update intervention lock state
   */
  setInterventionLocked(locked: boolean): void {
    this.interventionLocked = locked;
  }

  /**
   * Update terminal theme
   */
  setTheme(themeName: TerminalThemeName): void {
    if (this.isDisposed || !this.terminal) return;
    this.themeName = themeName;
    this.terminal.options.theme = getTerminalTheme(themeName);
    this.refresh();
  }

  /**
   * Get current theme name
   */
  getThemeName(): TerminalThemeName {
    return this.themeName;
  }

  /**
   * Check if alt buffer is active (tmux, vim, less, etc.)
   */
  isAltBufferActive(): boolean {
    return this.altBufferActive;
  }

  /**
   * Search in terminal
   */
  search(query: string, options: ISearchOptions): void {
    if (!this.searchAddon) return;

    if (query) {
      this.searchAddon.findNext(query, options);
    } else {
      this.searchAddon.clearDecorations();
      this.onSearchResult?.(0, 0);
    }
  }

  /**
   * Find next search result
   */
  findNext(query: string, options: ISearchOptions): void {
    this.searchAddon?.findNext(query, options);
  }

  /**
   * Find previous search result
   */
  findPrevious(query: string, options: ISearchOptions): void {
    this.searchAddon?.findPrevious(query, options);
  }

  /**
   * Clear search decorations
   */
  clearSearch(): void {
    this.searchAddon?.clearDecorations();
    this.onSearchResult?.(0, 0);
  }

  /**
   * Dispose all resources
   */
  dispose(): void {
    if (this.isDisposed) return;
    this.isDisposed = true;

    if (this.historyLoaded) {
      try {
        const snapshot = this.serializeAddon?.serialize({
          scrollback: 0,
          excludeAltBuffer: false,
          excludeModes: false,
        });
        if (snapshot) {
          setTerminalSnapshot(this.id, snapshot);
        }
      } catch {
        // Ignore snapshot errors
      }
    }

    // Cancel pending timers and flush any remaining output
    if (this.fitTimer !== null) clearTimeout(this.fitTimer);
    if (this.backendResizeTimer !== null) clearTimeout(this.backendResizeTimer);
    if (this.fitRetryRaf !== null) cancelAnimationFrame(this.fitRetryRaf);
    if (this.outputTimer !== null) {
      clearTimeout(this.outputTimer);
      this.outputTimer = null;
      // Flush remaining output before dispose
      if (this.outputBuffer.length > 0 && this.terminal) {
        this.terminal.write(this.outputBuffer.join(""));
        this.outputBuffer = [];
      }
    }

    // Remove event listeners
    window.removeEventListener("resize", this.handleWindowResize);
    this.container.removeEventListener("wheel", this.handleWheel);
    this.resizeObserver?.disconnect();
    this.unlistenData?.();
    this.unlistenExit?.();
    this.terminalDataDisposable?.dispose();

    // Dispose addons
    this.webglAddon?.dispose();
    this.unicode11Addon?.dispose();
    this.searchAddon?.dispose();
    this.fitAddon?.dispose();
    this.serializeAddon?.dispose();

    // Dispose terminal
    this.terminal?.dispose();

    // Clear references
    this.terminal = null;
    this.fitAddon = null;
    this.searchAddon = null;
    this.serializeAddon = null;
    this.webglAddon = null;
    this.unicode11Addon = null;
    this.resizeObserver = null;
    this.unlistenData = null;
    this.unlistenExit = null;
    this.terminalDataDisposable = null;
    this.fitTimer = null;
    this.backendResizeTimer = null;
    this.fitRetryRaf = null;
    this.outputTimer = null;
    this.outputBuffer = [];
  }
}

import { Card, CardBody, Input, Kbd } from "@nextui-org/react";
import { Button } from "../components/ui";
import { listen } from "@tauri-apps/api/event";
import { FitAddon } from "@xterm/addon-fit";
import { WebglAddon } from "@xterm/addon-webgl";
import { SearchAddon, type ISearchOptions } from "@xterm/addon-search";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { useEffect, useRef, useState, useCallback } from "react";
import { termResize, termWrite } from "../lib/tauri-api";
import { Link } from "@tanstack/react-router";
import { useTerminal } from "../contexts/TerminalContext";
import { AnimatePresence, motion } from "framer-motion";
import { RecipeAutomationPanel } from "../components/recipe/RecipeAutomationPanel";

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

function TerminalPane(props: TerminalPaneProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const searchRef = useRef<SearchAddon | null>(null);
  const webglRef = useRef<WebglAddon | null>(null);
  
  // Data batching refs for smooth rendering
  const dataBufferRef = useRef<string>("");
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
      matchBackground: "#fbbf2480",
      matchBorder: "#fbbf24",
      matchOverviewRuler: "#fbbf24",
      activeMatchBackground: "#f97316",
      activeMatchBorder: "#ffffff",
      activeMatchColorOverviewRuler: "#f97316",
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
      convertEol: true,
      cursorBlink: true,
      cursorStyle: "bar",
      fontFamily: "'JetBrains Mono', 'Fira Code', 'SF Mono', Menlo, Monaco, monospace",
      fontSize: 15,
      fontWeight: "400",
      fontWeightBold: "600",
      lineHeight: 1.2,
      letterSpacing: 0,
      macOptionIsMeta: true,
      macOptionClickForcesSelection: true,
      allowProposedApi: true, // Required for search decorations
      theme: {
        background: "#0d1117",
        foreground: "#c9d1d9",
        cursor: "#58a6ff",
        cursorAccent: "#0d1117",
        selectionBackground: "#264f78",
        selectionForeground: "#ffffff",
        black: "#484f58",
        red: "#ff7b72",
        green: "#3fb950",
        yellow: "#d29922",
        blue: "#58a6ff",
        magenta: "#bc8cff",
        cyan: "#39c5cf",
        white: "#b1bac4",
        brightBlack: "#6e7681",
        brightRed: "#ffa198",
        brightGreen: "#56d364",
        brightYellow: "#e3b341",
        brightBlue: "#79c0ff",
        brightMagenta: "#d2a8ff",
        brightCyan: "#56d4dd",
        brightWhite: "#f0f6fc",
      }
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
      if (dataBufferRef.current && termRef.current) {
        termRef.current.write(dataBufferRef.current);
        dataBufferRef.current = "";
        lastFlushRef.current = performance.now();
      }
      rafIdRef.current = null;
    };

    // Schedule a flush with throttling
    const scheduleFlush = () => {
      if (rafIdRef.current !== null) return; // Already scheduled
      
      const now = performance.now();
      const elapsed = now - lastFlushRef.current;
      
      if (elapsed >= RENDER_THROTTLE_MS) {
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
          dataBufferRef.current += evt.payload.data;
          scheduleFlush();
        }
      });
      
      // Check again after await - component might have unmounted
      if (!isMounted) {
        dataUnlisten();
        return;
      }
      unlistenData = dataUnlisten;
      
      // Listen for terminal exit and close the tab
      const exitUnlisten = await listen<{ id: string }>("term:exit", (evt) => {
        if (evt.payload.id === props.id) {
          // Flush any remaining data first
          if (dataBufferRef.current && termRef.current) {
            termRef.current.write(dataBufferRef.current);
            dataBufferRef.current = "";
          }
          // Close the tab
          props.onClose();
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
      if (dataBufferRef.current && termRef.current) {
        termRef.current.write(dataBufferRef.current);
        dataBufferRef.current = "";
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

  return <div ref={hostRef} className="h-full w-full bg-[#0d1117]" />;
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
  const { 
    sessions, 
    activeId, 
    openLocalTerminal, 
    closeSession,
    refreshSessions, 
    isLoading,
    recipePanelVisible,
    toggleRecipePanel,
  } = useTerminal();
  
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
    <div className="h-full flex">
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
              className="overflow-hidden bg-content1/80 backdrop-blur-md border-b border-divider"
            >
              <div className="flex items-center gap-2 px-3 py-2">
                <Input
                  ref={searchInputRef}
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
                    inputWrapper: "h-8 bg-content2/50",
                    input: "text-sm",
                  }}
                />
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

        {sessions.length === 0 ? (
          <Card className="flex-1 m-4">
            <CardBody className="flex flex-col items-center justify-center gap-4">
              <div className="text-center">
                <p className="text-lg font-medium mb-2">No Active Sessions</p>
                <p className="text-sm text-foreground/60">
                  Open a local terminal or connect to a remote host
                </p>
              </div>
              <div className="flex gap-3">
                <Button color="primary" onPress={() => void openLocalTerminal()}>
                  Local Terminal
                </Button>
                <Button as={Link} to="/hosts" variant="flat">
                  Go to Hosts
                </Button>
              </div>
            </CardBody>
          </Card>
        ) : (
          <>
            {/* Terminal area - full height, tabs are now in the title bar */}
            {/* Use visibility instead of display:none to maintain container dimensions */}
            <div className="flex-1 min-h-0 relative">
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

      {/* Recipe Automation Panel - Right Sidebar */}
      <AnimatePresence>
        {recipePanelVisible && (
          <RecipeAutomationPanel />
        )}
      </AnimatePresence>
    </div>
  );
}



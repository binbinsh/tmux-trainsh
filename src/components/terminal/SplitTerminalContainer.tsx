/**
 * Split Terminal Container - VSCode-style terminal split pane support
 *
 * Features:
 * 1. Horizontal and vertical splits
 * 2. Resizable panes with drag handles
 * 3. Keyboard shortcuts for navigation (Cmd+Opt+Arrow)
 * 4. Automatic cleanup when panes are closed
 */

import { useState, useCallback, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { SplitSquareHorizontal, SplitSquareVertical, X, Maximize2 } from "lucide-react";

type SplitDirection = "horizontal" | "vertical";

interface SplitPane {
  id: string;
  terminalId: string;
  ratio: number; // 0 to 1, represents percentage of space
}

interface SplitTerminalContainerProps {
  /** The primary terminal ID */
  primaryTerminalId: string;
  /** Whether this container is currently active/focused */
  isActive: boolean;
  /** Callback to create a new terminal for splitting */
  onCreateTerminal: () => Promise<string>;
  /** Callback when a terminal in a split is closed */
  onCloseTerminal: (terminalId: string) => void;
  /** Render function for a terminal pane */
  renderTerminal: (terminalId: string, isActive: boolean) => React.ReactNode;
  /** Current active pane ID within this split */
  activePaneId?: string;
  /** Callback when active pane changes */
  onActivePaneChange?: (paneId: string) => void;
}

interface SplitState {
  direction: SplitDirection;
  panes: SplitPane[];
}

/**
 * Container that manages split terminal panes
 */
export function SplitTerminalContainer({
  primaryTerminalId,
  isActive,
  onCreateTerminal,
  onCloseTerminal,
  renderTerminal,
  activePaneId: externalActivePaneId,
  onActivePaneChange,
}: SplitTerminalContainerProps) {
  const [splitState, setSplitState] = useState<SplitState | null>(null);
  const [activePaneId, setActivePaneId] = useState<string>(() => `pane-${primaryTerminalId}`);
  const [isDragging, setIsDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Sync with external active pane
  useEffect(() => {
    if (externalActivePaneId && externalActivePaneId !== activePaneId) {
      setActivePaneId(externalActivePaneId);
    }
  }, [externalActivePaneId, activePaneId]);

  // Handle split creation
  const handleSplit = useCallback(async (direction: SplitDirection) => {
    try {
      const newTerminalId = await onCreateTerminal();
      const newPaneId = `pane-${newTerminalId}`;

      if (!splitState) {
        // First split
        setSplitState({
          direction,
          panes: [
            { id: `pane-${primaryTerminalId}`, terminalId: primaryTerminalId, ratio: 0.5 },
            { id: newPaneId, terminalId: newTerminalId, ratio: 0.5 },
          ],
        });
      } else if (splitState.direction === direction) {
        // Same direction - add another pane
        const newRatio = 1 / (splitState.panes.length + 1);
        const scaleFactor = 1 - newRatio;
        setSplitState({
          direction,
          panes: [
            ...splitState.panes.map((p) => ({ ...p, ratio: p.ratio * scaleFactor })),
            { id: newPaneId, terminalId: newTerminalId, ratio: newRatio },
          ],
        });
      } else {
        // Different direction - for simplicity, replace split with new direction
        // In a more complex implementation, you'd create nested splits
        setSplitState({
          direction,
          panes: [
            { id: `pane-${primaryTerminalId}`, terminalId: primaryTerminalId, ratio: 0.5 },
            { id: newPaneId, terminalId: newTerminalId, ratio: 0.5 },
          ],
        });
      }

      // Focus the new pane
      setActivePaneId(newPaneId);
      onActivePaneChange?.(newPaneId);
    } catch (e) {
      console.error("[SplitTerminalContainer] Failed to create terminal for split:", e);
    }
  }, [splitState, primaryTerminalId, onCreateTerminal, onActivePaneChange]);

  // Handle closing a split pane
  const handleClosePane = useCallback((paneId: string) => {
    if (!splitState) return;

    const pane = splitState.panes.find((p) => p.id === paneId);
    if (!pane) return;

    // Close the terminal
    onCloseTerminal(pane.terminalId);

    // Remove the pane
    const remainingPanes = splitState.panes.filter((p) => p.id !== paneId);

    if (remainingPanes.length <= 1) {
      // Only one pane left - remove split
      setSplitState(null);
      if (remainingPanes[0]) {
        setActivePaneId(remainingPanes[0].id);
      }
    } else {
      // Redistribute ratios
      const totalRatio = remainingPanes.reduce((sum, p) => sum + p.ratio, 0);
      setSplitState({
        direction: splitState.direction,
        panes: remainingPanes.map((p) => ({ ...p, ratio: p.ratio / totalRatio })),
      });

      // Focus another pane if we closed the active one
      if (activePaneId === paneId) {
        setActivePaneId(remainingPanes[0].id);
      }
    }
  }, [splitState, activePaneId, onCloseTerminal]);

  // Handle unsplit (maximize active pane)
  const handleUnsplit = useCallback(() => {
    if (!splitState) return;

    // Close all panes except the active one
    const activePane = splitState.panes.find((p) => p.id === activePaneId);
    if (!activePane) return;

    for (const pane of splitState.panes) {
      if (pane.id !== activePaneId) {
        onCloseTerminal(pane.terminalId);
      }
    }

    setSplitState(null);
  }, [splitState, activePaneId, onCloseTerminal]);

  // Handle drag resize
  const handleDragStart = useCallback((e: React.MouseEvent, index: number) => {
    if (!splitState || !containerRef.current) return;

    e.preventDefault();
    setIsDragging(true);

    const startX = e.clientX;
    const startY = e.clientY;
    const containerRect = containerRef.current.getBoundingClientRect();
    const isHorizontal = splitState.direction === "horizontal";
    const containerSize = isHorizontal ? containerRect.width : containerRect.height;

    const handleMouseMove = (moveEvent: MouseEvent) => {
      const delta = isHorizontal
        ? moveEvent.clientX - startX
        : moveEvent.clientY - startY;
      const deltaRatio = delta / containerSize;

      setSplitState((prev) => {
        if (!prev) return prev;

        const newPanes = [...prev.panes];
        const leftPane = newPanes[index];
        const rightPane = newPanes[index + 1];

        if (!leftPane || !rightPane) return prev;

        const minRatio = 0.1; // Minimum 10% for each pane
        const newLeftRatio = Math.max(minRatio, Math.min(leftPane.ratio + deltaRatio, 1 - minRatio));
        const ratioDiff = newLeftRatio - leftPane.ratio;
        const newRightRatio = rightPane.ratio - ratioDiff;

        if (newRightRatio < minRatio) return prev;

        newPanes[index] = { ...leftPane, ratio: newLeftRatio };
        newPanes[index + 1] = { ...rightPane, ratio: newRightRatio };

        return { ...prev, panes: newPanes };
      });
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
  }, [splitState]);

  // Keyboard navigation
  useEffect(() => {
    if (!isActive || !splitState) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      // Cmd+Opt+Arrow to navigate between panes
      if ((e.metaKey || e.ctrlKey) && e.altKey) {
        const currentIndex = splitState.panes.findIndex((p) => p.id === activePaneId);
        let newIndex = currentIndex;

        if (splitState.direction === "horizontal") {
          if (e.key === "ArrowLeft") newIndex = Math.max(0, currentIndex - 1);
          if (e.key === "ArrowRight") newIndex = Math.min(splitState.panes.length - 1, currentIndex + 1);
        } else {
          if (e.key === "ArrowUp") newIndex = Math.max(0, currentIndex - 1);
          if (e.key === "ArrowDown") newIndex = Math.min(splitState.panes.length - 1, currentIndex + 1);
        }

        if (newIndex !== currentIndex) {
          e.preventDefault();
          const newPane = splitState.panes[newIndex];
          if (newPane) {
            setActivePaneId(newPane.id);
            onActivePaneChange?.(newPane.id);
          }
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isActive, splitState, activePaneId, onActivePaneChange]);

  // No split - render single terminal with split controls
  if (!splitState) {
    return (
      <div className="h-full w-full relative group" ref={containerRef}>
        {renderTerminal(primaryTerminalId, isActive)}

        {/* Split controls - shown on hover */}
        <div className="absolute top-2 right-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity z-10">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="secondary"
                size="icon"
                className="h-7 w-7 bg-background/80 backdrop-blur-sm"
                onClick={() => void handleSplit("horizontal")}
              >
                <SplitSquareHorizontal className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Split Horizontally</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="secondary"
                size="icon"
                className="h-7 w-7 bg-background/80 backdrop-blur-sm"
                onClick={() => void handleSplit("vertical")}
              >
                <SplitSquareVertical className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Split Vertically</TooltipContent>
          </Tooltip>
        </div>
      </div>
    );
  }

  // Render split panes
  const isHorizontal = splitState.direction === "horizontal";

  return (
    <div
      ref={containerRef}
      className={`h-full w-full flex ${isHorizontal ? "flex-row" : "flex-col"} ${isDragging ? "select-none" : ""}`}
    >
      {splitState.panes.map((pane, index) => (
        <div key={pane.id} className="flex" style={{ flex: `0 0 ${pane.ratio * 100}%` }}>
          {/* Pane content */}
          <div
            className={`flex-1 relative group ${activePaneId === pane.id ? "ring-1 ring-primary/50" : ""}`}
            onClick={() => {
              setActivePaneId(pane.id);
              onActivePaneChange?.(pane.id);
            }}
          >
            {renderTerminal(pane.terminalId, isActive && activePaneId === pane.id)}

            {/* Pane controls - shown on hover */}
            <div className="absolute top-2 right-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity z-10">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="secondary"
                    size="icon"
                    className="h-6 w-6 bg-background/80 backdrop-blur-sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleSplit("horizontal");
                    }}
                  >
                    <SplitSquareHorizontal className="h-3 w-3" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Split Horizontally</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="secondary"
                    size="icon"
                    className="h-6 w-6 bg-background/80 backdrop-blur-sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleSplit("vertical");
                    }}
                  >
                    <SplitSquareVertical className="h-3 w-3" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Split Vertically</TooltipContent>
              </Tooltip>
              {splitState.panes.length > 1 && (
                <>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="secondary"
                        size="icon"
                        className="h-6 w-6 bg-background/80 backdrop-blur-sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleUnsplit();
                        }}
                      >
                        <Maximize2 className="h-3 w-3" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Maximize Pane</TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="secondary"
                        size="icon"
                        className="h-6 w-6 bg-background/80 backdrop-blur-sm text-destructive"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleClosePane(pane.id);
                        }}
                      >
                        <X className="h-3 w-3" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Close Pane</TooltipContent>
                  </Tooltip>
                </>
              )}
            </div>
          </div>

          {/* Resize handle */}
          {index < splitState.panes.length - 1 && (
            <div
              className={`${isHorizontal ? "w-1 cursor-col-resize" : "h-1 cursor-row-resize"} bg-border hover:bg-primary/50 transition-colors flex-shrink-0`}
              onMouseDown={(e) => handleDragStart(e, index)}
            />
          )}
        </div>
      ))}
    </div>
  );
}

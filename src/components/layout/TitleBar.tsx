import { useLocation } from "@tanstack/react-router";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { motion, AnimatePresence, Reorder } from "framer-motion";
import { Plus, X, Terminal, SquareTerminal, FlaskConical, GripVertical } from "lucide-react";
import { useTerminalOptional, type TerminalSession } from "@/contexts/TerminalContext";
import { Button } from "@/components/ui/button";
import { SidebarTrigger, useSidebar } from "@/components/ui/sidebar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useState, useRef, useEffect, useCallback, useMemo } from "react";

function TerminalTab({
  session,
  isActive,
  onClick,
  onClose,
  isDragging = false,
}: {
  session: TerminalSession;
  isActive: boolean;
  onClick: () => void;
  onClose: () => void;
  isDragging?: boolean;
}) {
  const isRecipe = !!session.recipeExecutionId;
  const isPlaceholder = session.isPlaceholder;

  // Determine icon based on session type
  const TabIcon = isRecipe ? FlaskConical : isPlaceholder ? Plus : SquareTerminal;

  return (
    <motion.div
      layout
      layoutId={`tab-${session.id}`}
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9 }}
      transition={{ duration: 0.15 }}
      onClick={onClick}
      className={cn(
        "group relative flex items-center gap-2 px-2.5 h-7 min-w-[140px] max-w-[220px] flex-shrink-0 rounded-md cursor-pointer",
        "transition-all duration-150 select-none border",
        isDragging && "opacity-50",
        isActive
          ? "bg-card text-foreground border-border shadow-sm"
          : "bg-transparent text-[rgb(var(--doppio-titlebar-text))]/50 border-transparent hover:text-[rgb(var(--doppio-titlebar-text))]/80 hover:bg-[rgb(var(--doppio-titlebar-tab-hover))]"
      )}
    >
      {/* Icon / Close Button Container */}
      <div className="relative w-4 h-4 flex-shrink-0">
        {/* Tab Icon - hidden when close button is visible */}
        <TabIcon className={cn(
          "w-4 h-4 absolute inset-0 transition-opacity duration-150",
          isActive ? "text-foreground" : "text-[rgb(var(--doppio-titlebar-text))]/40",
          !isPlaceholder && "group-hover:opacity-0"
        )} />

        {/* Close Button - shows on hover, replaces icon */}
        {!isPlaceholder && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={(e) => {
              e.stopPropagation();
              onClose();
            }}
            className={cn(
              "h-4 w-4 rounded-sm p-0 absolute inset-0 transition-opacity duration-150",
              isActive
                ? "opacity-0 group-hover:opacity-100 text-foreground/70 hover:text-foreground hover:bg-foreground/10"
                : "opacity-0 group-hover:opacity-100 text-[rgb(var(--doppio-titlebar-text))]/50 hover:text-[rgb(var(--doppio-titlebar-text))] hover:bg-white/10"
            )}
            aria-label="Close terminal"
          >
            <X className="w-3 h-3" />
          </Button>
        )}
      </div>

      {/* Tab Title */}
      <span className="text-xs font-medium truncate min-w-0 flex-1">{session.title}</span>
    </motion.div>
  );
}

export function TitleBar() {
  const location = useLocation();
  const isTerminalPage = location.pathname.startsWith("/terminal");
  const terminal = useTerminalOptional();
  const sidebar = useSidebar();
  const titleBarClassName = "h-9 flex items-center bg-[rgb(var(--doppio-titlebar-bg))] text-[rgb(var(--doppio-titlebar-text))] pr-3 border-b border-[rgb(var(--doppio-titlebar-tab-border))]/50";
  const sidebarCollapsed = sidebar.state === "collapsed";

  const handleMouseDown = async (e: React.MouseEvent) => {
    if (e.buttons === 1) {
      if (e.detail === 2) {
        const win = getCurrentWindow();
        if (await win.isMaximized()) {
          await win.unmaximize();
        } else {
          await win.maximize();
        }
      } else {
        await getCurrentWindow().startDragging();
      }
    }
  };

  return (
    <div
      data-tauri-drag-region
      onMouseDown={handleMouseDown}
      className={cn(titleBarClassName, "backdrop-blur-md")}
      style={{ paddingLeft: 80 }}
    >
      <div onMouseDown={(e) => e.stopPropagation()}>
        <SidebarTrigger
          className={cn(
            "min-w-7 w-7 h-7 mr-2",
            sidebarCollapsed ? "text-[rgb(var(--doppio-titlebar-text))]/40" : "text-[rgb(var(--doppio-titlebar-text))]/60",
            "hover:text-[rgb(var(--doppio-titlebar-text))]"
          )}
        />
      </div>

      {isTerminalPage && terminal && terminal.sessions.length > 0 ? (
        <>
          <div
            className="flex items-center gap-2 overflow-x-auto shrink-0 py-0.5"
            onMouseDown={(e) => e.stopPropagation()}
          >
            <AnimatePresence mode="popLayout">
              {terminal.sessions.map((s) => (
                <TerminalTab
                  key={s.id}
                  session={s}
                  isActive={terminal.activeId === s.id}
                  onClick={() => terminal.setActiveId(s.id)}
                  onClose={() => void terminal.closeSession(s.id)}
                />
              ))}
            </AnimatePresence>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => terminal.createNewTab()}
                  className="min-w-7 w-7 h-7 text-[rgb(var(--doppio-titlebar-text))]/50 hover:text-[rgb(var(--doppio-titlebar-text))] hover:bg-black/5 transition-colors"
                >
                  <Plus className="w-3.5 h-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent className="flex items-center gap-2">
                <span>New Tab</span>
                <kbd className="text-[10px] font-mono bg-muted px-1.5 py-0.5 rounded">⌘T</kbd>
              </TooltipContent>
            </Tooltip>
          </div>

          <div className="flex-1 h-full" />
        </>
      ) : (
        <div className="flex-1 h-full" />
      )}
    </div>
  );
}

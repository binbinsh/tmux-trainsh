import { Tooltip } from "@nextui-org/react";
import { Button } from "../ui";
import { useLocation } from "@tanstack/react-router";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { motion, AnimatePresence } from "framer-motion";
import { useTerminalOptional, type TerminalSession } from "../../contexts/TerminalContext";

function IconPlus() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
    </svg>
  );
}

function IconClose() {
  return (
    <svg className="w-2.5 h-2.5" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth={1.5}>
      <path d="M2 2l6 6M8 2l-6 6" strokeLinecap="round" />
    </svg>
  );
}

function IconTerminal() {
  return (
    <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <polyline points="4 17 10 11 4 5" />
      <line x1="12" y1="19" x2="20" y2="19" />
    </svg>
  );
}

function IconSidebar() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M9 3v18" />
    </svg>
  );
}

// Terminal tab component - pill style with icon/close button on left
function TerminalTab({
  session,
  isActive,
  onClick,
  onClose
}: {
  session: TerminalSession;
  isActive: boolean;
  onClick: () => void;
  onClose: () => void;
}) {
  return (
    <motion.div
      layout
      layoutId={`tab-${session.id}`}
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9 }}
      transition={{ duration: 0.15 }}
      onClick={onClick}
      className={`
        group relative flex items-center gap-2 pl-2.5 pr-3 h-7 w-52 flex-shrink-0 rounded-lg cursor-pointer
        transition-all duration-150 border
        ${isActive
          ? "bg-[rgb(var(--doppio-titlebar-tab-active))] text-[rgb(var(--doppio-titlebar-text))] font-medium shadow-md border-[rgb(var(--doppio-titlebar-tab-border))]"
          : "bg-[rgb(var(--doppio-titlebar-tab-inactive))] text-[rgb(var(--doppio-titlebar-text))]/50 hover:bg-[rgb(var(--doppio-titlebar-tab-hover))] hover:text-[rgb(var(--doppio-titlebar-text))]/70 border-[rgb(var(--doppio-titlebar-tab-border))]/50 hover:border-[rgb(var(--doppio-titlebar-tab-border))]"
        }
      `}
    >
      {/* Icon/Close button area - shows terminal icon by default, close button on hover for inactive tabs */}
      <div className="w-4 h-4 flex items-center justify-center flex-shrink-0 relative">
        {isActive ? (
          /* Active tab: always show close button */
          <button
            onClick={(e) => {
              e.stopPropagation();
              onClose();
            }}
            className="w-4 h-4 rounded-full flex items-center justify-center transition-all duration-150 text-[rgb(var(--doppio-titlebar-text))]/50 hover:text-[rgb(var(--doppio-titlebar-text))] hover:bg-black/10"
            aria-label="Close terminal"
          >
            <IconClose />
          </button>
        ) : (
          /* Inactive tab: show terminal icon, close button on hover */
          <>
            <span className="absolute inset-0 flex items-center justify-center text-[rgb(var(--doppio-titlebar-text))]/30 group-hover:opacity-0 transition-opacity duration-150">
              <IconTerminal />
            </span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onClose();
              }}
              className="absolute inset-0 rounded-full flex items-center justify-center transition-all duration-150 text-[rgb(var(--doppio-titlebar-text))]/30 hover:text-[rgb(var(--doppio-titlebar-text))] hover:bg-black/10 opacity-0 group-hover:opacity-100"
              aria-label="Close terminal"
            >
              <IconClose />
            </button>
          </>
        )}
      </div>

      {/* Title */}
      <span className="text-xs font-medium truncate min-w-0 flex-1">{session.title}</span>
    </motion.div>
  );
}

export function TitleBar() {
  const location = useLocation();
  const isTerminalPage = location.pathname.startsWith("/terminal");
  const terminal = useTerminalOptional();
  const titleBarClassName = "h-9 flex items-center bg-[rgb(var(--doppio-titlebar-bg))] text-[rgb(var(--doppio-titlebar-text))] pr-3 border-b border-[rgb(var(--doppio-titlebar-tab-border))]/50";

  // Handle drag on mousedown - more reliable than data-tauri-drag-region
  const handleMouseDown = async (e: React.MouseEvent) => {
    // Only start dragging on primary button (left click)
    if (e.buttons === 1) {
      if (e.detail === 2) {
        // Double click - toggle maximize
        const win = getCurrentWindow();
        if (await win.isMaximized()) {
          await win.unmaximize();
        } else {
          await win.maximize();
        }
      } else {
        // Single click - start dragging
        await getCurrentWindow().startDragging();
      }
    }
  };

  return (
    <div
      data-tauri-drag-region
      onMouseDown={handleMouseDown}
      className={`${titleBarClassName} backdrop-blur-md`}
      style={{ paddingLeft: 80 }} // Space for native macOS traffic lights
    >
      {/* Sidebar toggle button - always visible */}
      <div onMouseDown={(e) => e.stopPropagation()}>
        <Tooltip content={terminal?.sidebarCollapsed ? "Show Sidebar" : "Hide Sidebar"} delay={500}>
          <Button
            isIconOnly
            size="sm"
            variant="light"
            onPress={terminal?.toggleSidebar}
            className={`min-w-7 w-7 h-7 mr-2 ${terminal?.sidebarCollapsed ? "text-[rgb(var(--doppio-titlebar-text))]/40" : "text-[rgb(var(--doppio-titlebar-text))]/60"} hover:text-[rgb(var(--doppio-titlebar-text))]`}
          >
            <IconSidebar />
          </Button>
        </Tooltip>
      </div>

      {/* Terminal tabs - only show on terminal page */}
      {isTerminalPage && terminal && terminal.sessions.length > 0 ? (
        <>
          {/* Tabs area - NOT draggable, stop propagation */}
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

            {/* New terminal button */}
            <Tooltip content="New Tab" delay={500}>
              <Button
                isIconOnly
                size="sm"
                variant="light"
                onPress={() => terminal.createNewTab()}
                className="min-w-7 w-7 h-7 text-[rgb(var(--doppio-titlebar-text))]/50 hover:text-[rgb(var(--doppio-titlebar-text))] hover:bg-black/5 transition-colors"
              >
                <IconPlus />
              </Button>
            </Tooltip>
          </div>

          {/* Remaining space is draggable (inherits from parent) */}
          <div className="flex-1 h-full" />
        </>
      ) : (
        /* Non-terminal pages: just an empty draggable area */
        <div className="flex-1 h-full" />
      )}
    </div>
  );
}

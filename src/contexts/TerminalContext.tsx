import { createContext, useContext, useState, useCallback, useEffect, useRef, type ReactNode } from "react";
import { listen } from "@tauri-apps/api/event";
import { termClose, termList, termOpenLocal } from "../lib/tauri-api";

export type TerminalSession = {
  id: string;
  title: string;
  /** Associated recipe execution ID (if this terminal is running a recipe) */
  recipeExecutionId?: string | null;
  /** Host ID for the connection */
  hostId?: string | null;
  /** Whether intervention is currently locked */
  interventionLocked?: boolean;
  /** Whether this is a placeholder tab (not yet connected) */
  isPlaceholder?: boolean;
};

type TerminalContextType = {
  sessions: TerminalSession[];
  activeId: string | null;
  setActiveId: (id: string | null) => void;
  openLocalTerminal: () => Promise<void>;
  closeSession: (id: string) => Promise<void>;
  refreshSessions: () => Promise<void>;
  /** Add a recipe terminal session */
  addRecipeTerminal: (session: TerminalSession) => void;
  /** Update intervention lock state for a session */
  setInterventionLocked: (sessionId: string, locked: boolean) => void;
  /** Get session by terminal ID */
  getSession: (id: string) => TerminalSession | undefined;
  isLoading: boolean;
  /** Check if current terminal has an associated recipe */
  hasActiveRecipe: boolean;
  /** Whether the workspace panel is visible (for connecting to hosts) */
  workspaceVisible: boolean;
  setWorkspaceVisible: (visible: boolean) => void;
  showWorkspace: () => void;
  /** Create a new tab placeholder and show workspace */
  createNewTab: () => void;
  /** Remove the current placeholder tab (if any) */
  removeCurrentPlaceholder: () => void;
};

const TerminalContext = createContext<TerminalContextType | null>(null);

export function useTerminal() {
  const ctx = useContext(TerminalContext);
  if (!ctx) {
    throw new Error("useTerminal must be used within TerminalProvider");
  }
  return ctx;
}

export function useTerminalOptional() {
  return useContext(TerminalContext);
}

export function TerminalProvider({ children }: { children: ReactNode }) {
  const [sessions, setSessions] = useState<TerminalSession[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [workspaceVisible, setWorkspaceVisible] = useState(false);
  const lastSessionCount = useRef(0);

  // Check if current terminal has an associated recipe
  const hasActiveRecipe = sessions.some(
    (s) => s.id === activeId && s.recipeExecutionId
  );

  // Show workspace panel (hides terminal, shows host connection UI)
  const showWorkspace = useCallback(() => {
    setWorkspaceVisible(true);
  }, []);

  // Create a new placeholder tab and show workspace
  const createNewTab = useCallback(() => {
    const placeholderId = `placeholder-${Date.now()}`;
    const placeholderSession: TerminalSession = {
      id: placeholderId,
      title: "New Tab",
      isPlaceholder: true,
    };
    setSessions((prev) => [...prev, placeholderSession]);
    setActiveId(placeholderId);
    setWorkspaceVisible(true);
  }, []);

  // Remove the current placeholder tab (if active tab is a placeholder)
  const removeCurrentPlaceholder = useCallback(() => {
    setSessions((prev) => {
      const currentSession = prev.find((s) => s.id === activeId);
      if (currentSession?.isPlaceholder) {
        return prev.filter((s) => s.id !== activeId);
      }
      return prev;
    });
  }, [activeId]);

  // Wrapper for setActiveId that manages workspace visibility
  const handleSetActiveId = useCallback((id: string | null) => {
    if (id !== null) {
      // Check if this is a placeholder tab - read sessions directly without triggering setState
      const session = sessions.find((s) => s.id === id);
      if (session?.isPlaceholder) {
        setWorkspaceVisible(true);
      } else {
        setWorkspaceVisible(false);
      }
    }
    setActiveId(id);
  }, [sessions]);

  // Refresh sessions from backend
  const refreshSessions = useCallback(async () => {
    try {
      const existing = await termList();
      // Merge backend sessions with local state to preserve recipeExecutionId, order, and other frontend-only data
      setSessions((prev) => {
        // Keep local order: update existing sessions, append truly new ones
        const existingIds = new Set(existing.map((s) => s.id));
        const prevIds = new Set(prev.map((s) => s.id));
        
        // Update existing sessions (preserve order from prev)
        const updated = prev
          .filter((s) => existingIds.has(s.id))
          .map((localSession) => {
            const backendSession = existing.find((s) => s.id === localSession.id);
            return backendSession
              ? {
                  ...backendSession,
                  recipeExecutionId: localSession.recipeExecutionId,
                  hostId: localSession.hostId,
                  interventionLocked: localSession.interventionLocked,
                }
              : localSession;
          });
        
        // Append new sessions from backend (not in prev) at the end
        const newSessions = existing.filter((s) => !prevIds.has(s.id));
        const merged = [...updated, ...newSessions];
        
        lastSessionCount.current = merged.length;
        
        // If new sessions were added, switch to the newest one
        if (newSessions.length > 0) {
          setActiveId(newSessions[newSessions.length - 1].id);
        } else if (merged.length > 0 && !prev.some((s) => s.id === merged[0]?.id)) {
          // Only set activeId if we don't have any active session
          setActiveId((currentActive) => currentActive ?? merged[0]?.id ?? null);
        }
        
        return merged;
      });
    } catch (e) {
      console.error("[TerminalProvider] Failed to refresh sessions:", e);
    }
  }, []);

  // Fetch existing sessions on mount
  useEffect(() => {
    (async () => {
      try {
        const existing = await termList();
        setSessions(existing);
        setActiveId(existing[0]?.id ?? null);
        lastSessionCount.current = existing.length;
      } catch (e) {
        console.error("[TerminalProvider] Failed to fetch sessions:", e);
      } finally {
        setIsLoading(false);
      }
    })();
  }, []);

  const closeSession = useCallback(async (id: string) => {
    // Check if this is a placeholder session (doesn't need backend call)
    const session = sessions.find((s) => s.id === id);
    if (!session?.isPlaceholder) {
      await termClose(id);
    }
    setSessions((prev) => {
      const next = prev.filter((s) => s.id !== id);
      lastSessionCount.current = next.length;
      setActiveId((prevActive) => (prevActive === id ? next[0]?.id ?? null : prevActive));
      return next;
    });
  }, [sessions]);

  const openLocalTerminal = useCallback(async () => {
    try {
      // Use smaller initial size - xterm.js will resize to actual size after fit()
      // This prevents the "jump" when initial PTY size doesn't match actual terminal size
      const session = await termOpenLocal({ cols: 80, rows: 24 });
      setSessions((prev) => {
        const next = [...prev, session];
        lastSessionCount.current = next.length;
        return next;
      });
      setActiveId(session.id);
    } catch (e) {
      console.error("[TerminalProvider] Failed to open local terminal:", e);
    }
  }, []);

  /** Add a recipe terminal session (created externally by recipe runner) */
  const addRecipeTerminal = useCallback((session: TerminalSession) => {
    console.log("[TerminalProvider] Adding recipe terminal:", session);
    setSessions((prev) => {
      // Check if session already exists
      const existingIndex = prev.findIndex((s) => s.id === session.id);
      if (existingIndex >= 0) {
        // Update existing session with recipe info
        const updated = [...prev];
        updated[existingIndex] = { ...updated[existingIndex], ...session };
        return updated;
      }
      const next = [...prev, session];
      lastSessionCount.current = next.length;
      return next;
    });
    setActiveId(session.id);
  }, []);

  /** Update intervention lock state for a session */
  const setInterventionLocked = useCallback((sessionId: string, locked: boolean) => {
    setSessions((prev) =>
      prev.map((s) =>
        s.id === sessionId ? { ...s, interventionLocked: locked } : s
      )
    );
  }, []);

  // Listen for intervention lock changes from backend
  // This is critical to block user input while recipe is sending commands
  useEffect(() => {
    let unlisten: (() => void) | null = null;
    
    (async () => {
      unlisten = await listen<{ execution_id: string; locked: boolean; terminal_id?: string }>(
        "recipe:intervention_lock_changed",
        (event) => {
          // Find the terminal session with this execution_id and update its lock state
          setSessions((prev) => {
            return prev.map((s) => {
              // Match by terminal_id if provided, otherwise by recipeExecutionId
              if (
                (event.payload.terminal_id && s.id === event.payload.terminal_id) ||
                s.recipeExecutionId === event.payload.execution_id
              ) {
                return { ...s, interventionLocked: event.payload.locked };
              }
              return s;
            });
          });
        }
      );
    })();

    return () => {
      if (unlisten) unlisten();
    };
  }, []);


  /** Get session by terminal ID */
  const getSession = useCallback(
    (id: string) => sessions.find((s) => s.id === id),
    [sessions]
  );

  return (
    <TerminalContext.Provider
      value={{
        sessions,
        activeId,
        setActiveId: handleSetActiveId,
        openLocalTerminal,
        closeSession,
        refreshSessions,
        addRecipeTerminal,
        setInterventionLocked,
        getSession,
        isLoading,
        hasActiveRecipe,
        workspaceVisible,
        setWorkspaceVisible,
        showWorkspace,
        createNewTab,
        removeCurrentPlaceholder,
      }}
    >
      {children}
    </TerminalContext.Provider>
  );
}

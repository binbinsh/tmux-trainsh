import { Outlet, useLocation } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState, useEffect, createContext, useContext } from "react";
import { Sidebar } from "./Sidebar";
import { TitleBar } from "./TitleBar";
import { TerminalProvider } from "../../contexts/TerminalContext";
import { hostApi, recipeApi } from "../../lib/tauri-api";

// Context for sidebar state
type SidebarContextType = {
  isCollapsed: boolean;
  setIsCollapsed: (v: boolean) => void;
  toggle: () => void;
};

const SidebarContext = createContext<SidebarContextType>({
  isCollapsed: false,
  setIsCollapsed: () => {},
  toggle: () => {},
});

export const useSidebar = () => useContext(SidebarContext);

export function RootLayout() {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const location = useLocation();
  
  // Keyboard shortcut: ⌘\ to toggle sidebar
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "\\") {
        e.preventDefault();
        setIsCollapsed((v) => !v);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);
  
  // Auto-collapse on terminal page for maximum space
  useEffect(() => {
    const isTerminal = location.pathname.startsWith("/terminal");
    // Don't auto-expand when leaving terminal, let user control it
    if (isTerminal && !isCollapsed) {
      // Optional: auto-collapse on terminal page
      // setIsCollapsed(true);
    }
  }, [location.pathname, isCollapsed]);

  const hostsQuery = useQuery({
    queryKey: ["hosts"],
    queryFn: hostApi.list,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  const executionsQuery = useQuery({
    queryKey: ["recipe-executions"],
    queryFn: recipeApi.listExecutions,
    refetchInterval: 3_000,
  });

  const recipesQuery = useQuery({
    queryKey: ["recipes"],
    queryFn: recipeApi.list,
    staleTime: 30_000,
  });

  const sidebarContext: SidebarContextType = {
    isCollapsed,
    setIsCollapsed,
    toggle: () => setIsCollapsed((v) => !v),
  };

  return (
    <TerminalProvider>
      <SidebarContext.Provider value={sidebarContext}>
        <div className="h-screen flex flex-col overflow-hidden select-none cursor-default">
          {/* Custom title bar with drag region */}
          <TitleBar />
          
          {/* Main content below title bar */}
          <div className="flex-1 flex overflow-hidden">
            <Sidebar
              hosts={hostsQuery.data ?? []}
              recipes={recipesQuery.data ?? []}
              executions={executionsQuery.data ?? []}
              isLoadingHosts={hostsQuery.isLoading}
              isLoadingRecipes={recipesQuery.isLoading}
              isCollapsed={isCollapsed}
              onToggle={() => setIsCollapsed((v) => !v)}
            />
            <main className="flex-1 overflow-hidden bg-background">
              <Outlet />
            </main>
          </div>
        </div>
      </SidebarContext.Provider>
    </TerminalProvider>
  );
}

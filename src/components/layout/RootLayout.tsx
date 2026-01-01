import { Outlet } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Sidebar } from "./Sidebar";
import { TitleBar } from "./TitleBar";
import { TerminalProvider, useTerminalOptional } from "../../contexts/TerminalContext";
import { hostApi, recipeApi, useInteractiveExecutions } from "../../lib/tauri-api";

export function RootLayout() {
  return (
    <TerminalProvider>
      <RootLayoutShell />
    </TerminalProvider>
  );
}

function RootLayoutShell() {
  const terminal = useTerminalOptional();
  const isCollapsed = terminal?.sidebarCollapsed ?? false;

  const hostsQuery = useQuery({
    queryKey: ["hosts"],
    queryFn: hostApi.list,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  const executionsQuery = useInteractiveExecutions();

  const recipesQuery = useQuery({
    queryKey: ["recipes"],
    queryFn: recipeApi.list,
    staleTime: 30_000,
  });

  return (
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
        />
        <main className="flex-1 overflow-hidden bg-background">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

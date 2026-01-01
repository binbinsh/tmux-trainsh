import { Outlet, useLocation } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Sidebar } from "./Sidebar";
import { TitleBar } from "./TitleBar";
import { TerminalProvider, useTerminalOptional } from "../../contexts/TerminalContext";
import { hostApi, recipeApi, useInteractiveExecutions } from "../../lib/tauri-api";

// Page transition variants
const pageTransitionVariants = {
  initial: {
    opacity: 0,
    y: 6,
  },
  animate: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.18,
      ease: [0.25, 0.1, 0.25, 1],
    },
  },
  exit: {
    opacity: 0,
    y: -4,
    transition: {
      duration: 0.12,
      ease: [0.25, 0.1, 0.25, 1],
    },
  },
};

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
  const location = useLocation();

  // Determine if we should animate page transitions
  // Terminal page manages its own state, so we skip animation there
  const isTerminalPage = location.pathname === "/terminal";

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
          <AnimatePresence mode="wait">
            {isTerminalPage ? (
              // Terminal page - no animation wrapper to preserve xterm state
              <Outlet />
            ) : (
              // Other pages - apply page transition animation
              <motion.div
                key={location.pathname}
                variants={pageTransitionVariants}
                initial="initial"
                animate="animate"
                exit="exit"
                className="h-full"
              >
                <Outlet />
              </motion.div>
            )}
          </AnimatePresence>
        </main>
      </div>
    </div>
  );
}

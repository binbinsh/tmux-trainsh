import { Outlet, useLocation } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useLayoutEffect } from "react";
import { Sidebar } from "./Sidebar";
import { TitleBar } from "./TitleBar";
import { TerminalProvider } from "@/contexts/TerminalContext";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { getConfig, hostApi, recipeApi, useInteractiveExecutions } from "@/lib/tauri-api";
import { applyAppTheme, getStoredAppTheme, DEFAULT_APP_THEME } from "@/lib/terminal-themes";

const pageTransitionVariants = {
  initial: {
    opacity: 0,
  },
  animate: {
    opacity: 1,
    transition: {
      duration: 0.1,
      ease: "easeOut",
    },
  },
  exit: {
    opacity: 0,
    transition: {
      duration: 0.05,
      ease: "easeIn",
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
  const location = useLocation();

  const isTerminalPage = location.pathname === "/terminal";

  useLayoutEffect(() => {
    applyAppTheme(getStoredAppTheme() ?? DEFAULT_APP_THEME);
  }, []);

  const configQuery = useQuery({
    queryKey: ["config"],
    queryFn: getConfig,
    staleTime: 30_000,
  });

  useEffect(() => {
    const theme = configQuery.data?.terminal?.theme;
    if (!theme) return;
    applyAppTheme(theme);
  }, [configQuery.data?.terminal?.theme]);

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
    <SidebarProvider className="h-screen overflow-hidden select-none cursor-default flex-col">
      <TitleBar />

      <div className="flex flex-1 min-h-0 overflow-hidden">
        <Sidebar
          hosts={hostsQuery.data ?? []}
          recipes={recipesQuery.data ?? []}
          executions={executionsQuery.data ?? []}
          isLoadingHosts={hostsQuery.isLoading}
          isLoadingRecipes={recipesQuery.isLoading}
        />

        <SidebarInset className="min-h-0 overflow-hidden">
          {isTerminalPage ? (
            <Outlet />
          ) : (
            <AnimatePresence mode="popLayout">
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
            </AnimatePresence>
          )}
        </SidebarInset>
      </div>
    </SidebarProvider>
  );
}

import { Link, useLocation, useNavigate } from "@tanstack/react-router";
import { useMemo, useCallback, memo } from "react";
import { Plus, Settings, Database, Terminal, FlaskConical, X, SquareTerminal, Server } from "lucide-react";
import type { Host, InteractiveExecution, RecipeSummary } from "@/lib/types";
import { useTerminalOptional, type TerminalSession } from "@/contexts/TerminalContext";
import {
  Sidebar as UiSidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
  SidebarRail,
  SidebarSeparator,
} from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";
import appLogo from "@/assets/icons/app-logo.png";

type SidebarProps = {
  hosts: Host[];
  recipes: RecipeSummary[];
  executions: InteractiveExecution[];
  isLoadingHosts?: boolean;
  isLoadingRecipes?: boolean;
};

// Terminal session item in sidebar
const TerminalSessionItem = memo(function TerminalSessionItem({
  session,
  isActive,
  onClick,
  onClose,
}: {
  session: TerminalSession;
  isActive: boolean;
  onClick: () => void;
  onClose: () => void;
}) {
  const isRecipe = !!session.recipeExecutionId;
  const isPlaceholder = session.isPlaceholder;

  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        size="sm"
        isActive={isActive}
        onClick={onClick}
        tooltip={session.title}
      >
        {isRecipe ? (
          <FlaskConical className="size-3.5" />
        ) : isPlaceholder ? (
          <Plus className="size-3.5" />
        ) : (
          <SquareTerminal className="size-3.5" />
        )}
        <span className="truncate">{session.title}</span>
      </SidebarMenuButton>
      {!isPlaceholder && (
        <SidebarMenuAction
          showOnHover
          onClick={(e) => {
            e.stopPropagation();
            onClose();
          }}
          className="text-muted-foreground hover:text-destructive"
        >
          <X className="size-3" />
        </SidebarMenuAction>
      )}
    </SidebarMenuItem>
  );
});

export const Sidebar = memo(function Sidebar({ hosts, recipes, executions }: SidebarProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const currentPath = location.pathname;
  const terminal = useTerminalOptional();

  const activeHosts = useMemo(
    () => hosts.filter((h) => h.status === "online"),
    [hosts]
  );

  const activeExecutions = useMemo(
    () =>
      executions.filter(
        (e) =>
          !!e.terminal_id &&
          (e.status === "running" ||
            e.status === "paused" ||
            e.status === "waiting_for_input" ||
            e.status === "connecting")
      ),
    [executions]
  );

  const terminalSessions = useMemo(
    () => terminal?.sessions ?? [],
    [terminal?.sessions]
  );

  const realTerminalSessionCount = useMemo(
    () => terminalSessions.filter((s) => !s.isPlaceholder).length,
    [terminalSessions]
  );

  const handleTerminalSessionClick = useCallback((sessionId: string) => {
    if (!terminal) return;
    terminal.setActiveId(sessionId);
    // Navigate to terminal page if not already there
    if (currentPath !== "/terminal") {
      navigate({ to: "/terminal", search: { connectHostId: undefined, connectVastInstanceId: undefined, connectLabel: undefined } });
    }
  }, [terminal, currentPath, navigate]);

  const handleCloseSession = useCallback((sessionId: string) => {
    if (!terminal) return;
    void terminal.closeSession(sessionId);
  }, [terminal]);

  const handleNewTerminal = useCallback(() => {
    if (!terminal) return;
    terminal.createNewTab();
    if (currentPath !== "/terminal") {
      navigate({ to: "/terminal", search: { connectHostId: undefined, connectVastInstanceId: undefined, connectLabel: undefined } });
    }
  }, [terminal, currentPath, navigate]);

  function isActive(path: string) {
    return currentPath === path || currentPath.startsWith(path + "/");
  }

  return (
    <UiSidebar collapsible="icon" variant="floating" className="top-9">
      <SidebarHeader data-tauri-drag-region>
        <div className="flex items-center gap-2 px-2 py-1.5 pointer-events-none group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0">
          <img src={appLogo} alt="Doppio" className="size-6" />
          <span className="text-sm font-semibold tracking-tight group-data-[collapsible=icon]:hidden">Doppio</span>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Application</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={isActive("/terminal")} tooltip="Terminal">
                  <Link to="/terminal" search={{ connectHostId: undefined, connectVastInstanceId: undefined, connectLabel: undefined }}>
                    <Terminal />
                    <span>Terminal</span>
                  </Link>
                </SidebarMenuButton>
                {realTerminalSessionCount > 0 && (
                  <SidebarMenuBadge className={isActive("/terminal") ? "text-[rgb(var(--doppio-accent-blue))]" : ""}>
                    {realTerminalSessionCount}
                  </SidebarMenuBadge>
                )}
              </SidebarMenuItem>

              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={isActive("/hosts")} tooltip="Hosts">
                  <Link to="/hosts">
                    <Server />
                    <span>Hosts</span>
                  </Link>
                </SidebarMenuButton>
                {activeHosts.length > 0 && (
                  <SidebarMenuBadge className={isActive("/hosts") ? "text-[rgb(var(--doppio-accent-blue))]" : ""}>
                    {activeHosts.length}
                  </SidebarMenuBadge>
                )}
              </SidebarMenuItem>

              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={isActive("/recipes")} tooltip="Recipes">
                  <Link to="/recipes">
                    <FlaskConical />
                    <span>Recipes</span>
                  </Link>
                </SidebarMenuButton>
                {activeExecutions.length > 0 && (
                  <SidebarMenuBadge className={isActive("/recipes") ? "text-[rgb(var(--doppio-accent-blue))]" : ""}>
                    {activeExecutions.length}
                  </SidebarMenuBadge>
                )}
              </SidebarMenuItem>

              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={isActive("/storage")} tooltip="Storage">
                  <Link to="/storage">
                    <Database />
                    <span>Storage</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {/* Terminal Sessions - Quick access to open terminals */}
        {terminalSessions.length > 0 && (
          <>
            <SidebarSeparator className="group-data-[collapsible=icon]:hidden" />
            <SidebarGroup className="group-data-[collapsible=icon]:hidden">
              <SidebarGroupLabel>Sessions</SidebarGroupLabel>
              <SidebarGroupAction
                title="New Terminal (⌘T)"
                onClick={handleNewTerminal}
              >
                <Plus />
              </SidebarGroupAction>
              <SidebarGroupContent>
                <SidebarMenu>
                  {terminalSessions.map((session) => (
                    <TerminalSessionItem
                      key={session.id}
                      session={session}
                      isActive={currentPath === "/terminal" && terminal?.activeId === session.id}
                      onClick={() => handleTerminalSessionClick(session.id)}
                      onClose={() => handleCloseSession(session.id)}
                    />
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          </>
        )}

        {activeExecutions.length > 0 && (
          <>
            <SidebarSeparator className="group-data-[collapsible=icon]:hidden" />
            <SidebarGroup className="group-data-[collapsible=icon]:hidden">
              <SidebarGroupLabel>Running</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {activeExecutions.map((execution) => {
                    const stepsCompleted = execution.steps.filter((s) => s.status === "success").length;
                    const stepsTotal = execution.steps.length;
                    const statusColor =
                      execution.status === "running" || execution.status === "waiting_for_input"
                        ? "bg-success animate-pulse"
                        : execution.status === "connecting"
                        ? "bg-warning animate-pulse"
                        : execution.status === "paused"
                        ? "bg-warning"
                        : execution.status === "failed"
                        ? "bg-destructive"
                        : "bg-foreground/20";

                    return (
                      <SidebarMenuItem key={execution.id}>
                        <SidebarMenuButton
                          asChild
                          size="sm"
                          isActive={currentPath === "/terminal" && execution.terminal_id === terminal?.activeId}
                          tooltip={execution.recipe_name}
                        >
                          <Link
                            to="/terminal"
                            search={{ connectHostId: undefined, connectVastInstanceId: undefined, connectLabel: undefined }}
                            onClick={() => {
                              if (terminal && execution.terminal_id) {
                                terminal.setActiveId(execution.terminal_id);
                              }
                            }}
                          >
                            <span className={cn("size-2 rounded-full", statusColor)} />
                            <span>{execution.recipe_name}</span>
                          </Link>
                        </SidebarMenuButton>
                        <SidebarMenuBadge>
                          {stepsCompleted}/{stepsTotal}
                        </SidebarMenuBadge>
                      </SidebarMenuItem>
                    );
                  })}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          </>
        )}
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild isActive={isActive("/settings")} tooltip="Settings">
              <Link to="/settings">
                <Settings />
                <span>Settings</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>

      <SidebarRail />
    </UiSidebar>
  );
});

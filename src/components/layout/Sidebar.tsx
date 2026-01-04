import { Link, useLocation, useNavigate } from "@tanstack/react-router";
import { useMemo, useCallback, memo } from "react";
import { Plus, Settings, Database, Terminal, FlaskConical, X, SquareTerminal, Server, ArrowLeftRight } from "lucide-react";
import type { Host, InteractiveExecution, SkillSummary } from "@/lib/types";
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
import appLogo from "@/assets/icons/app-logo.png";

type SidebarProps = {
  hosts: Host[];
  skills: SkillSummary[];
  executions: InteractiveExecution[];
  isLoadingHosts?: boolean;
  isLoadingSkills?: boolean;
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
  const isSkill = !!session.skillExecutionId;
  const isPlaceholder = session.isPlaceholder;

  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        size="sm"
        isActive={isActive}
        onClick={onClick}
        tooltip={session.title}
      >
        {isSkill ? (
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

export const Sidebar = memo(function Sidebar({ hosts }: SidebarProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const currentPath = location.pathname;
  const terminal = useTerminalOptional();

  const activeHosts = useMemo(
    () => hosts.filter((h) => h.status === "online"),
    [hosts]
  );

  const terminalSessions = useMemo(
    () => terminal?.sessions ?? [],
    [terminal?.sessions]
  );

  const realTerminalSessionCount = useMemo(
    () => terminalSessions.filter((s) => !s.isPlaceholder).length,
    [terminalSessions]
  );

  const handleTerminalSessionClick = useCallback((session: TerminalSession) => {
    if (!terminal) return;
    terminal.setActiveId(session.id);

    if (session.skillExecutionId) {
      navigate({ to: "/skills/runs/$id", params: { id: session.skillExecutionId } });
      return;
    }

    if (currentPath !== "/terminal") {
      navigate({
        to: "/terminal",
        search: { connectHostId: undefined, connectVastInstanceId: undefined, connectLabel: undefined },
      });
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
                <SidebarMenuButton asChild isActive={isActive("/storage")} tooltip="Storage">
                  <Link to="/storage">
                    <Database />
                    <span>Storage</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>

              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={isActive("/transfer")} tooltip="Transfer">
                  <Link to="/transfer">
                    <ArrowLeftRight />
                    <span>Transfer</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>

              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={isActive("/skills")} tooltip="Skills">
                  <Link to="/skills">
                    <FlaskConical />
                    <span>Skills</span>
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
                      onClick={() => handleTerminalSessionClick(session)}
                      onClose={() => handleCloseSession(session.id)}
                    />
                  ))}
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

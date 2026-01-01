import { ScrollShadow, Tooltip } from "@nextui-org/react";
import { Button } from "../ui";
import { Link, useLocation } from "@tanstack/react-router";
import { useMemo } from "react";
import type { Host, InteractiveExecution, RecipeSummary } from "../../lib/types";
import { useTerminalOptional } from "../../contexts/TerminalContext";
import appLogo from "../../assets/icons/app-logo.png";

// Icons
function IconServer() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21.75 17.25v-.228a4.5 4.5 0 00-.12-1.03l-2.268-9.64a3.375 3.375 0 00-3.285-2.602H7.923a3.375 3.375 0 00-3.285 2.602l-2.268 9.64a4.5 4.5 0 00-.12 1.03v.228m19.5 0a3 3 0 01-3 3H5.25a3 3 0 01-3-3m19.5 0a3 3 0 00-3-3H5.25a3 3 0 00-3 3m16.5 0h.008v.008h-.008v-.008zm-3 0h.008v.008h-.008v-.008z" />
    </svg>
  );
}

function IconPlus() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
    </svg>
  );
}

function IconSettings() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  );
}

function IconStorage() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
    </svg>
  );
}

function IconTerminal() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 7.5l3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0021 18V6a2.25 2.25 0 00-2.25-2.25H5.25A2.25 2.25 0 003 6v12a2.25 2.25 0 002.25 2.25z" />
    </svg>
  );
}

function IconRecipe() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611l-.417.07a9.092 9.092 0 01-3.064.04L14.25 20M5 14.5l-1.402 1.402c-1.232 1.232-.65 3.318 1.067 3.611l.417.07a9.09 9.09 0 003.064.04l2.404-.403" />
    </svg>
  );
}

type SidebarProps = {
  hosts: Host[];
  recipes: RecipeSummary[];
  executions: InteractiveExecution[];
  isLoadingHosts?: boolean;
  isLoadingRecipes?: boolean;
  isCollapsed?: boolean;
};

export function Sidebar({ hosts, recipes, executions, isLoadingHosts, isLoadingRecipes, isCollapsed = false }: SidebarProps) {
  const location = useLocation();
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

  // Count active terminal sessions (non-placeholder)
  const terminalSessionCount = useMemo(
    () => terminal?.sessions.filter((s) => !s.isPlaceholder).length ?? 0,
    [terminal?.sessions]
  );

  function isActive(path: string) {
    return currentPath === path || currentPath.startsWith(path + "/");
  }

  if (isCollapsed) {
    return (
      <aside className="doppio-sidebar w-14 border-r border-black/5">
        {/* App Icon Header */}
        <div className="h-12 flex-shrink-0 flex items-end justify-center pb-2" data-tauri-drag-region>
          <img src={appLogo} alt="Doppio" className="w-6 h-6 pointer-events-none" />
        </div>

        {/* Collapsed Navigation */}
        <nav className="p-1.5 flex flex-col items-center gap-0.5">
          <CollapsedNavItem to="/terminal" icon={<IconTerminal />} label="Terminal" isActive={isActive("/terminal")} badge={terminalSessionCount > 0 ? String(terminalSessionCount) : undefined} />
          <CollapsedNavItem to="/hosts" icon={<IconServer />} label="Hosts" isActive={isActive("/hosts")} badge={activeHosts.length > 0 ? String(activeHosts.length) : undefined} />
          <CollapsedNavItem to="/recipes" icon={<IconRecipe />} label="Recipes" isActive={isActive("/recipes")} badge={activeExecutions.length > 0 ? String(activeExecutions.length) : undefined} />
          <CollapsedNavItem to="/storage" icon={<IconStorage />} label="Storage" isActive={isActive("/storage")} />
        </nav>

        <div className="flex-1" />

        {/* Footer */}
        <div className="p-1.5 flex justify-center">
          <CollapsedNavItem to="/settings" icon={<IconSettings />} label="Settings" isActive={isActive("/settings")} />
        </div>
      </aside>
    );
  }

  return (
    <aside className="doppio-sidebar w-56 border-r border-black/5">
      {/* App Header with logo and name */}
      <div className="h-12 flex-shrink-0 flex items-end pb-2 px-2" data-tauri-drag-region>
        <div className="flex items-center gap-2.5 px-2.5 pointer-events-none">
          <img src={appLogo} alt="Doppio" className="w-6 h-6" />
          <span className="text-[15px] font-semibold text-[rgb(var(--doppio-sidebar-text))]/80">Doppio</span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="px-2 py-1">
        <NavItem
          to="/terminal"
          icon={<IconTerminal />}
          label="Terminal"
          isActive={isActive("/terminal")}
          badge={terminalSessionCount > 0 ? String(terminalSessionCount) : undefined}
        />
        <NavItem
          to="/hosts"
          icon={<IconServer />}
          label="Hosts"
          isActive={isActive("/hosts")}
          badge={activeHosts.length > 0 ? String(activeHosts.length) : undefined}
        />
        <NavItem
          to="/recipes"
          icon={<IconRecipe />}
          label="Recipes"
          isActive={isActive("/recipes")}
          badge={activeExecutions.length > 0 ? String(activeExecutions.length) : undefined}
        />
        <NavItem
          to="/storage"
          icon={<IconStorage />}
          label="Storage"
          isActive={isActive("/storage")}
        />
      </nav>

      {/* Hosts list */}
      <div className="flex-1 overflow-hidden flex flex-col mt-2">
        <div className="px-3 py-1.5 flex items-center justify-between">
          <span className="doppio-sidebar-section-header">
            Hosts
          </span>
          <Tooltip content="Add Host">
            <Button
              as={Link}
              to="/hosts/new"
              isIconOnly
              size="sm"
              variant="light"
              className="min-w-5 w-5 h-5 text-[rgb(var(--doppio-sidebar-text))]/40 hover:text-[rgb(var(--doppio-sidebar-text))]"
            >
              <IconPlus />
            </Button>
          </Tooltip>
        </div>
        <ScrollShadow className="flex-1 px-2" hideScrollBar>
          {isLoadingHosts ? (
            <div className="px-2 py-1 text-xs text-[rgb(var(--doppio-sidebar-text-muted))]">Loading...</div>
          ) : hosts.length === 0 ? (
            <div className="px-2 py-1 text-xs text-[rgb(var(--doppio-sidebar-text-muted))]">No hosts yet</div>
          ) : (
            hosts.slice(0, 10).map((host) => (
              <HostItem key={host.id} host={host} isActive={currentPath === `/hosts/${host.id}`} />
            ))
          )}
        </ScrollShadow>

        {/* Running Executions only */}
        {activeExecutions.length > 0 && (
          <>
            <div className="px-3 py-1.5 flex items-center justify-between mt-2">
              <span className="doppio-sidebar-section-header">
                Running
              </span>
              <span className="text-[11px] text-primary/80 font-medium">{activeExecutions.length}</span>
            </div>
            <ScrollShadow className="flex-1 px-2" hideScrollBar>
              {activeExecutions.map((exec) => (
                <ExecutionItem
                  key={exec.id}
                  execution={exec}
                  isActive={currentPath === "/terminal" && exec.terminal_id === terminal?.activeId}
                />
              ))}
            </ScrollShadow>
          </>
        )}
      </div>

      {/* Footer */}
      <div className="px-2 py-2">
        <NavItem
          to="/settings"
          icon={<IconSettings />}
          label="Settings"
          isActive={isActive("/settings")}
        />
      </div>
    </aside>
  );
}

// Nav Item Component
type NavItemProps = {
  to: string;
  icon: React.ReactNode;
  label: string;
  isActive: boolean;
  badge?: string;
};

function NavItem({ to, icon, label, isActive, badge }: NavItemProps) {
  return (
    <Link
      to={to}
      className={`
        flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg transition-all duration-150 cursor-default
        ${isActive
          ? "bg-[rgb(var(--doppio-sidebar-item-active))] text-[rgb(var(--doppio-sidebar-icon-active))] font-medium"
          : "text-[rgb(var(--doppio-sidebar-text))]/70 hover:bg-[rgb(var(--doppio-sidebar-item-hover))] hover:text-[rgb(var(--doppio-sidebar-text))]"
        }
      `}
    >
      <span className="w-5 h-5 flex items-center justify-center">{icon}</span>
      <span className={`text-[13px] ${isActive ? "text-[rgb(var(--doppio-sidebar-text))]" : ""}`}>{label}</span>
      {badge && (
        <span className="ml-auto text-[10px] bg-black/5 text-[rgb(var(--doppio-sidebar-text))]/60 px-1.5 py-0.5 rounded-full font-medium">
          {badge}
        </span>
      )}
    </Link>
  );
}

// Host Item Component
function HostItem({ host, isActive }: { host: Host; isActive: boolean }) {
  return (
    <Link
      to="/hosts/$id"
      params={{ id: host.id }}
      className={`
        flex items-center gap-2 px-2 py-1 rounded-md transition-all duration-150 text-[12px] cursor-default
        ${isActive
          ? "bg-[rgb(var(--doppio-sidebar-item-active))] text-[rgb(var(--doppio-sidebar-text))]"
          : "text-[rgb(var(--doppio-sidebar-text))]/60 hover:bg-[rgb(var(--doppio-sidebar-item-hover))] hover:text-[rgb(var(--doppio-sidebar-text))]/80"
        }
      `}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
          host.status === "online" ? "bg-success" : host.status === "connecting" ? "bg-warning animate-pulse" : "bg-black/20"
        }`}
      />
      <span className="truncate flex-1">{host.name}</span>
      <span className="text-[10px] text-[rgb(var(--doppio-sidebar-text))]/40">{host.type}</span>
    </Link>
  );
}

// Recipe Item Component
function RecipeItem({ recipe, isActive }: { recipe: RecipeSummary; isActive: boolean }) {
  return (
    <Link
      to="/recipes/$path"
      params={{ path: encodeURIComponent(recipe.path) }}
      className={`
        flex items-center gap-2 px-2 py-1.5 rounded-md transition-colors text-sm
        ${isActive ? "bg-primary/10 text-primary" : "text-foreground/70 hover:bg-default/40"}
      `}
    >
      <span className="text-base">📜</span>
      <span className="truncate flex-1">{recipe.name}</span>
      <span className="text-xs text-foreground/50">{recipe.step_count}</span>
    </Link>
  );
}

// Execution Item Component
function ExecutionItem({ execution, isActive }: { execution: InteractiveExecution; isActive: boolean }) {
  const terminal = useTerminalOptional();
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
      ? "bg-danger"
      : "bg-foreground/20";

  return (
    <Link
      to="/terminal"
      search={{ connectHostId: undefined, connectVastInstanceId: undefined, connectLabel: undefined }}
      onClick={() => {
        if (terminal && execution.terminal_id) {
          terminal.setActiveId(execution.terminal_id);
        }
      }}
      className={`
        flex items-center gap-2 px-2 py-1 rounded-md transition-all duration-150 text-[12px] cursor-default
        ${isActive
          ? "bg-[rgb(var(--doppio-sidebar-item-active))] text-[rgb(var(--doppio-sidebar-text))]"
          : "text-[rgb(var(--doppio-sidebar-text))]/60 hover:bg-[rgb(var(--doppio-sidebar-item-hover))] hover:text-[rgb(var(--doppio-sidebar-text))]/80"
        }
      `}
    >
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${statusColor}`} />
      <span className="truncate flex-1">{execution.recipe_name}</span>
      <span className="text-[10px] text-[rgb(var(--doppio-sidebar-text))]/40">
        {stepsCompleted}/{stepsTotal}
      </span>
    </Link>
  );
}

type CollapsedNavItemProps = {
  to: string;
  icon: React.ReactNode;
  label: string;
  isActive: boolean;
  badge?: string;
};

function CollapsedNavItem({ to, icon, label, isActive, badge }: CollapsedNavItemProps) {
  return (
    <Tooltip content={label} placement="right">
      <Link
        to={to}
        className={`
          relative flex items-center justify-center w-9 h-9 rounded-lg transition-all duration-150 cursor-default
          ${isActive
            ? "bg-[rgb(var(--doppio-sidebar-item-active))] text-[rgb(var(--doppio-sidebar-icon-active))]"
            : "text-[rgb(var(--doppio-sidebar-text))]/50 hover:bg-[rgb(var(--doppio-sidebar-item-hover))] hover:text-[rgb(var(--doppio-sidebar-text))]/70"
          }
        `}
      >
        {icon}
        {badge && (
          <span className="absolute -top-0.5 -right-0.5 text-[9px] bg-primary text-primary-foreground w-3.5 h-3.5 rounded-full flex items-center justify-center font-medium">
            {badge}
          </span>
        )}
      </Link>
    </Tooltip>
  );
}

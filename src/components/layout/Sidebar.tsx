import { Divider, ScrollShadow, Tooltip } from "@nextui-org/react";
import { Button } from "../ui";
import { Link, useLocation } from "@tanstack/react-router";
import { motion } from "framer-motion";
import { useMemo } from "react";
import type { ExecutionSummary, Host, RecipeSummary } from "../../lib/types";

// Icons
function IconDashboard() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
    </svg>
  );
}

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
  executions: ExecutionSummary[];
  isLoadingHosts?: boolean;
  isLoadingRecipes?: boolean;
  isCollapsed?: boolean;
  onToggle?: () => void;
};

export function Sidebar({ hosts, recipes, executions, isLoadingHosts, isLoadingRecipes, isCollapsed = false, onToggle }: SidebarProps) {
  const location = useLocation();
  const currentPath = location.pathname;

  const activeHosts = useMemo(
    () => hosts.filter((h) => h.status === "online"),
    [hosts]
  );

  const activeExecutions = useMemo(
    () => executions.filter((e) => e.status === "running" || e.status === "paused"),
    [executions]
  );

  function isActive(path: string) {
    return currentPath === path || currentPath.startsWith(path + "/");
  }

  // Collapsed sidebar - just icons
  if (isCollapsed) {
    return (
      <aside className="w-14 h-full flex flex-col border-r border-divider bg-content1 transition-all duration-200">
        {/* Logo */}
        <div className="p-2 border-b border-divider flex flex-col items-center">
          <Link to="/dashboard" className="flex items-center justify-center">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center">
              <span className="text-white font-bold text-sm">D</span>
            </div>
          </Link>
        </div>

        {/* Collapsed Navigation */}
        <nav className="p-1 flex flex-col items-center gap-1">
          <CollapsedNavItem to="/dashboard" icon={<IconDashboard />} label="Dashboard" isActive={isActive("/dashboard")} />
          <CollapsedNavItem to="/hosts" icon={<IconServer />} label="Hosts" isActive={isActive("/hosts")} badge={activeHosts.length > 0 ? String(activeHosts.length) : undefined} />
          <CollapsedNavItem to="/storage" icon={<IconStorage />} label="Storage" isActive={isActive("/storage")} />
          <CollapsedNavItem to="/recipes" icon={<IconRecipe />} label="Recipes" isActive={isActive("/recipes")} badge={activeExecutions.length > 0 ? String(activeExecutions.length) : undefined} />
          <CollapsedNavItem to="/terminal" icon={<IconTerminal />} label="Terminal" isActive={isActive("/terminal")} />
        </nav>

        <div className="flex-1" />

        {/* Footer */}
        <div className="p-1 border-t border-divider flex justify-center">
          <CollapsedNavItem to="/settings" icon={<IconSettings />} label="Settings" isActive={isActive("/settings")} />
        </div>
      </aside>
    );
  }

  return (
    <aside className="w-64 h-full flex flex-col border-r border-divider bg-content1 transition-all duration-200">
      {/* Logo */}
      <div className="p-4 border-b border-divider">
        <Link to="/dashboard" className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center">
            <span className="text-white font-bold text-sm">D</span>
          </div>
          <span className="font-semibold text-lg">Doppio</span>
        </Link>
      </div>

      {/* Navigation */}
      <nav className="p-2">
        <NavItem
          to="/dashboard"
          icon={<IconDashboard />}
          label="Dashboard"
          isActive={isActive("/dashboard")}
        />
        <NavItem
          to="/hosts"
          icon={<IconServer />}
          label="Hosts"
          isActive={isActive("/hosts")}
          badge={activeHosts.length > 0 ? String(activeHosts.length) : undefined}
        />
        <NavItem
          to="/storage"
          icon={<IconStorage />}
          label="Storage"
          isActive={isActive("/storage")}
        />
        <NavItem
          to="/recipes"
          icon={<IconRecipe />}
          label="Recipes"
          isActive={isActive("/recipes")}
          badge={activeExecutions.length > 0 ? String(activeExecutions.length) : undefined}
        />
        <NavItem
          to="/terminal"
          icon={<IconTerminal />}
          label="Terminal"
          isActive={isActive("/terminal")}
        />
      </nav>

      <Divider />

      {/* Hosts list */}
      <div className="flex-1 overflow-hidden flex flex-col">
        <div className="px-4 py-2 flex items-center justify-between">
          <span className="text-xs font-semibold text-foreground/60 uppercase tracking-wider">
            Hosts
          </span>
          <Tooltip content="Add Host">
            <Button
              as={Link}
              to="/hosts/new"
              isIconOnly
              size="sm"
              variant="light"
              className="min-w-6 w-6 h-6"
            >
              <IconPlus />
            </Button>
          </Tooltip>
        </div>
        <ScrollShadow className="flex-1 px-2" hideScrollBar>
          {isLoadingHosts ? (
            <div className="px-2 py-1 text-xs text-foreground/50">Loading...</div>
          ) : hosts.length === 0 ? (
            <div className="px-2 py-1 text-xs text-foreground/50">No hosts yet</div>
          ) : (
            hosts.slice(0, 10).map((host) => (
              <HostItem key={host.id} host={host} isActive={currentPath === `/hosts/${host.id}`} />
            ))
          )}
        </ScrollShadow>

        <Divider />

        {/* Running Executions only */}
        {activeExecutions.length > 0 && (
          <>
            <div className="px-4 py-2 flex items-center justify-between">
              <span className="text-xs font-semibold text-foreground/60 uppercase tracking-wider">
                Running
              </span>
              <span className="text-xs text-primary font-medium">{activeExecutions.length}</span>
            </div>
            <ScrollShadow className="flex-1 px-2" hideScrollBar>
              {activeExecutions.map((exec) => (
                <ExecutionItem
                  key={exec.id}
                  execution={exec}
                  isActive={currentPath === `/recipes/executions/${exec.id}`}
                />
              ))}
            </ScrollShadow>
          </>
        )}
      </div>

      {/* Footer */}
      <div className="p-2 border-t border-divider">
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
        flex items-center gap-3 px-3 py-2 rounded-lg transition-colors relative
        ${isActive ? "bg-primary/10 text-primary" : "text-foreground/70 hover:bg-default/40 hover:text-foreground"}
      `}
    >
      {icon}
      <span className="text-sm font-medium">{label}</span>
      {badge && (
        <span className="ml-auto text-xs bg-primary/20 text-primary px-1.5 py-0.5 rounded-full">
          {badge}
        </span>
      )}
      {isActive && (
        <motion.div
          layoutId="sidebar-indicator"
          className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-5 bg-primary rounded-r-full"
          transition={{ type: "spring", bounce: 0.2, duration: 0.4 }}
        />
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
        flex items-center gap-2 px-2 py-1.5 rounded-md transition-colors text-sm
        ${isActive ? "bg-primary/10 text-primary" : "text-foreground/70 hover:bg-default/40"}
      `}
    >
      <span
        className={`w-2 h-2 rounded-full ${
          host.status === "online" ? "bg-success" : host.status === "connecting" ? "bg-warning animate-pulse" : "bg-default"
        }`}
      />
      <span className="truncate flex-1">{host.name}</span>
      <span className="text-xs text-foreground/50">{host.type}</span>
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
function ExecutionItem({ execution, isActive }: { execution: ExecutionSummary; isActive: boolean }) {
  const statusColor = execution.status === "running"
    ? "bg-success animate-pulse"
    : execution.status === "paused"
    ? "bg-warning"
    : execution.status === "failed"
    ? "bg-danger"
    : "bg-default";

  return (
    <Link
      to="/recipes/executions/$id"
      params={{ id: execution.id }}
      className={`
        flex items-center gap-2 px-2 py-1.5 rounded-md transition-colors text-sm
        ${isActive ? "bg-primary/10 text-primary" : "text-foreground/70 hover:bg-default/40"}
      `}
    >
      <span className={`w-2 h-2 rounded-full ${statusColor}`} />
      <span className="truncate flex-1">{execution.recipe_name}</span>
      <span className="text-xs text-foreground/50">
        {execution.steps_completed}/{execution.steps_total}
      </span>
    </Link>
  );
}

// Collapsed Nav Item Component (icon only with tooltip)
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
          relative flex items-center justify-center w-10 h-10 rounded-lg transition-colors
          ${isActive ? "bg-primary/10 text-primary" : "text-foreground/70 hover:bg-default/40 hover:text-foreground"}
        `}
      >
        {icon}
        {badge && (
          <span className="absolute -top-1 -right-1 text-[10px] bg-primary text-primary-foreground w-4 h-4 rounded-full flex items-center justify-center">
            {badge}
          </span>
        )}
        {isActive && (
          <motion.div
            layoutId="sidebar-indicator-collapsed"
            className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-5 bg-primary rounded-r-full"
            transition={{ type: "spring", bounce: 0.2, duration: 0.4 }}
          />
        )}
      </Link>
    </Tooltip>
  );
}

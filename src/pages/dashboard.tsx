import {
  Card,
  CardBody,
  CardHeader,
  Chip,
  Divider,
  Progress,
  Spinner,
} from "@nextui-org/react";
import { Button } from "../components/ui";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { motion } from "framer-motion";
import { useMemo } from "react";
import { hostApi, recipeApi, useVastInstances } from "../lib/tauri-api";
import type { ExecutionSummary, ExecutionStatus, RecipeSummary } from "../lib/types";
import { StatusBadge } from "../components/shared/StatusBadge";

// Animation variants
const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.08,
      delayChildren: 0.1,
    },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 16, scale: 0.98 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] },
  },
};

// Icons
function IconServer() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21.75 17.25v-.228a4.5 4.5 0 00-.12-1.03l-2.268-9.64a3.375 3.375 0 00-3.285-2.602H7.923a3.375 3.375 0 00-3.285 2.602l-2.268 9.64a4.5 4.5 0 00-.12 1.03v.228m19.5 0a3 3 0 01-3 3H5.25a3 3 0 01-3-3m19.5 0a3 3 0 00-3-3H5.25a3 3 0 00-3 3m16.5 0h.008v.008h-.008v-.008zm-3 0h.008v.008h-.008v-.008z" />
    </svg>
  );
}

function IconPlay() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
    </svg>
  );
}

function IconGpu() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 3v1.5M4.5 8.25H3m18 0h-1.5M4.5 12H3m18 0h-1.5m-15 3.75H3m18 0h-1.5M8.25 19.5V21M12 3v1.5m0 15V21m3.75-18v1.5m0 15V21m-9-1.5h10.5a2.25 2.25 0 002.25-2.25V6.75a2.25 2.25 0 00-2.25-2.25H6.75A2.25 2.25 0 004.5 6.75v10.5a2.25 2.25 0 002.25 2.25zm.75-12h9v9h-9v-9z" />
    </svg>
  );
}

function IconClock() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  );
}

function IconPlus() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
    </svg>
  );
}

function IconSettings() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.212-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
    </svg>
  );
}

function IconArrowRight() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" />
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

// Stats Card Component
type StatsCardProps = {
  title: string;
  value: string | number;
  icon: React.ReactNode;
  description: string;
  color: "primary" | "success" | "warning" | "secondary";
};

function StatsCard({ title, value, icon, description, color }: StatsCardProps) {
  const colorClasses = {
    primary: "bg-primary/10 text-primary border-primary/20",
    success: "bg-success/10 text-success border-success/20",
    warning: "bg-warning/10 text-warning border-warning/20",
    secondary: "bg-secondary/10 text-secondary border-secondary/20",
  };

  return (
    <Card className="border border-divider/50 shadow-sm hover:shadow-md transition-shadow">
      <CardBody className="flex flex-row items-center gap-4 p-4">
        <div className={`flex items-center justify-center w-11 h-11 rounded-xl border ${colorClasses[color]}`}>
          {icon}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs text-foreground/50 uppercase tracking-wide font-medium">{title}</p>
          <p className="text-2xl font-bold tabular-nums">{value}</p>
          <p className="text-xs text-foreground/40 truncate">{description}</p>
        </div>
      </CardBody>
    </Card>
  );
}

// Quick Action Button Component
type QuickActionProps = {
  icon: React.ReactNode;
  label: string;
  to: string;
  description?: string;
};

function QuickActionButton({ icon, label, to, description }: QuickActionProps) {
  return (
    <Button
      as={Link}
      to={to}
      variant="flat"
      className="h-auto py-5 px-4 flex-col gap-2 bg-default-100/50 hover:bg-default-200/70 border border-transparent hover:border-primary/30 transition-all group"
    >
      <span className="text-foreground/70 group-hover:text-primary transition-colors">
        {icon}
      </span>
      <span className="font-medium">{label}</span>
      {description && (
        <span className="text-xs text-foreground/40">{description}</span>
      )}
    </Button>
  );
}

function getStatusColor(status: ExecutionStatus): "default" | "primary" | "secondary" | "success" | "warning" | "danger" {
  switch (status) {
    case "completed": return "success";
    case "running": return "primary";
    case "failed": return "danger";
    case "paused": return "warning";
    case "cancelled": return "default";
    default: return "default";
  }
}

function ExecutionCard({ execution }: { execution: ExecutionSummary }) {
  const progress = execution.steps_total > 0
    ? ((execution.steps_completed + execution.steps_failed) / execution.steps_total) * 100
    : 0;

  return (
    <Link
      to="/recipes/executions/$id"
      params={{ id: execution.id }}
      className="block"
    >
      <Card className="border border-divider hover:border-primary/50 transition-colors">
        <CardBody className="p-4">
          <div className="flex items-center justify-between gap-3 mb-2">
            <h4 className="font-medium truncate">{execution.recipe_name}</h4>
            <Chip size="sm" color={getStatusColor(execution.status)} variant="flat">
              {execution.status}
            </Chip>
          </div>
          
          <Progress
            size="sm"
            value={progress}
            color={execution.status === "failed" ? "danger" : "primary"}
            className="mb-2"
          />
          
          <div className="flex items-center justify-between text-xs text-foreground/60">
            <span>
              {execution.steps_completed}/{execution.steps_total} steps
            </span>
            <span>{new Date(execution.created_at).toLocaleString()}</span>
          </div>
        </CardBody>
      </Card>
    </Link>
  );
}

function RecipeCard({ recipe }: { recipe: RecipeSummary }) {
  return (
    <Link
      to="/recipes/$path"
      params={{ path: encodeURIComponent(recipe.path) }}
      className="flex items-center justify-between p-3 rounded-lg hover:bg-default-100/70 transition-colors group"
    >
      <div className="flex items-center gap-3 min-w-0">
        <span className="text-xl">📜</span>
        <div className="min-w-0">
          <p className="font-medium text-sm truncate group-hover:text-primary transition-colors">
            {recipe.name}
          </p>
          <p className="text-xs text-foreground/40 truncate">
            {recipe.step_count} steps • v{recipe.version}
          </p>
        </div>
      </div>
      <IconArrowRight />
    </Link>
  );
}

export function DashboardPage() {
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

  const vastQuery = useVastInstances();

  const activeHosts = useMemo(
    () => (hostsQuery.data ?? []).filter((h) => h.status === "online"),
    [hostsQuery.data]
  );

  const runningExecutions = useMemo(
    () => (executionsQuery.data ?? []).filter((e) => e.status === "running" || e.status === "paused"),
    [executionsQuery.data]
  );

  const recentExecutions = useMemo(
    () => (executionsQuery.data ?? []).slice(0, 5),
    [executionsQuery.data]
  );

  const recipes = recipesQuery.data ?? [];

  return (
    <div className="h-full p-6 overflow-auto">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <motion.div
          className="flex items-center justify-between"
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
        >
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
            <p className="text-sm text-foreground/50 mt-0.5">
              Overview of your training infrastructure
            </p>
          </div>
          <Button
            as={Link}
            to="/recipes"
            color="primary"
            startContent={<IconPlus />}
            className="font-medium shadow-md shadow-primary/20"
          >
            New Recipe
          </Button>
        </motion.div>

        {/* Stats Grid */}
        <motion.div
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"
          variants={containerVariants}
          initial="hidden"
          animate="visible"
        >
          <motion.div variants={itemVariants}>
            <StatsCard
              title="Active Hosts"
              value={activeHosts.length}
              icon={<IconServer />}
              description={`${hostsQuery.data?.length ?? 0} total hosts`}
              color="primary"
            />
          </motion.div>

          <motion.div variants={itemVariants}>
            <StatsCard
              title="Running Recipes"
              value={runningExecutions.length}
              icon={<IconPlay />}
              description={`${executionsQuery.data?.length ?? 0} total runs`}
              color="success"
            />
          </motion.div>

          <motion.div variants={itemVariants}>
            <StatsCard
              title="Vast.ai Instances"
              value={vastQuery.data?.length ?? 0}
              icon={<IconGpu />}
              description={`${vastQuery.data?.filter((i) => i.actual_status === "running").length ?? 0} running`}
              color="warning"
            />
          </motion.div>

          <motion.div variants={itemVariants}>
            <StatsCard
              title="Total Recipes"
              value={recipes.length}
              icon={<IconRecipe />}
              description="Automation workflows"
              color="secondary"
            />
          </motion.div>
        </motion.div>

        {/* Main Content Grid - Improved layout */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Recent Executions - Left side */}
          <motion.div
            className="lg:col-span-7"
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.3, duration: 0.4 }}
          >
            <Card className="h-full border border-divider/50">
              <CardHeader className="flex items-center justify-between px-5 py-4">
                <div className="flex items-center gap-2">
                  <span className="font-semibold">Recent Runs</span>
                  {runningExecutions.length > 0 && (
                    <Chip size="sm" color="success" variant="flat" className="h-5">
                      {runningExecutions.length} active
                    </Chip>
                  )}
                </div>
                <Button
                  as={Link}
                  to="/recipes"
                  size="sm"
                  variant="light"
                  endContent={<IconArrowRight />}
                  className="text-foreground/60 hover:text-primary"
                >
                  View All
                </Button>
              </CardHeader>
              <Divider />
              <CardBody className="p-4">
                {executionsQuery.isLoading ? (
                  <div className="flex items-center justify-center py-12">
                    <Spinner size="lg" />
                  </div>
                ) : recentExecutions.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-12 px-4">
                    <div className="w-16 h-16 rounded-2xl bg-default-100 flex items-center justify-center mb-4">
                      <IconPlay />
                    </div>
                    <p className="text-foreground/60 mb-1 font-medium">No recipe runs yet</p>
                    <p className="text-foreground/40 text-sm text-center mb-4">
                      Create and run your first recipe to automate training
                    </p>
                    <Button as={Link} to="/recipes" color="primary" size="sm" startContent={<IconPlus />}>
                      Create Recipe
                    </Button>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {recentExecutions.map((exec) => (
                      <ExecutionCard key={exec.id} execution={exec} />
                    ))}
                  </div>
                )}
              </CardBody>
            </Card>
          </motion.div>

          {/* Right side - Hosts + Quick Actions stacked */}
          <div className="lg:col-span-5 flex flex-col gap-6">
            {/* Active Hosts */}
            <motion.div
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.35, duration: 0.4 }}
            >
              <Card className="border border-divider/50">
                <CardHeader className="flex items-center justify-between px-5 py-4">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">Hosts</span>
                    <Chip size="sm" variant="flat" className="h-5 bg-default-100">
                      {hostsQuery.data?.length ?? 0}
                    </Chip>
                  </div>
                  <Button
                    as={Link}
                    to="/hosts"
                    size="sm"
                    variant="light"
                    endContent={<IconArrowRight />}
                    className="text-foreground/60 hover:text-primary"
                  >
                    Manage
                  </Button>
                </CardHeader>
                <Divider />
                <CardBody className="px-3 py-2">
                  {hostsQuery.isLoading ? (
                    <div className="flex items-center justify-center py-6">
                      <Spinner />
                    </div>
                  ) : (hostsQuery.data ?? []).length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-6">
                      <p className="text-foreground/50 text-sm mb-3">No hosts configured</p>
                      <Button as={Link} to="/hosts" color="primary" size="sm" variant="flat">
                        Add Host
                      </Button>
                    </div>
                  ) : (
                    <div className="space-y-1">
                      {(hostsQuery.data ?? []).slice(0, 4).map((host) => (
                        <Link
                          key={host.id}
                          to="/hosts/$id"
                          params={{ id: host.id }}
                          className="flex items-center justify-between p-3 rounded-lg hover:bg-default-100/70 transition-colors group"
                        >
                          <div className="flex items-center gap-3 min-w-0">
                            <span
                              className={`w-2 h-2 rounded-full flex-shrink-0 ${
                                host.status === "online"
                                  ? "bg-success shadow-sm shadow-success/50"
                                  : host.status === "connecting"
                                  ? "bg-warning animate-pulse"
                                  : "bg-default-300"
                              }`}
                            />
                            <div className="min-w-0">
                              <p className="font-medium text-sm truncate group-hover:text-primary transition-colors">
                                {host.name}
                              </p>
                              <p className="text-xs text-foreground/40 truncate">
                                {host.gpu_name
                                  ? `${host.num_gpus}x ${host.gpu_name}`
                                  : host.type}
                              </p>
                            </div>
                          </div>
                          <StatusBadge status={host.status} size="sm" variant="dot" />
                        </Link>
                      ))}
                      {(hostsQuery.data?.length ?? 0) > 4 && (
                        <div className="text-center py-2">
                          <span className="text-xs text-foreground/40">
                            +{(hostsQuery.data?.length ?? 0) - 4} more hosts
                          </span>
                        </div>
                      )}
                    </div>
                  )}
                </CardBody>
              </Card>
            </motion.div>

            {/* Recipes */}
            <motion.div
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.38, duration: 0.4 }}
            >
              <Card className="border border-divider/50">
                <CardHeader className="flex items-center justify-between px-5 py-4">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">Recipes</span>
                    <Chip size="sm" variant="flat" className="h-5 bg-default-100">
                      {recipes.length}
                    </Chip>
                  </div>
                  <Button
                    as={Link}
                    to="/recipes"
                    size="sm"
                    variant="light"
                    endContent={<IconArrowRight />}
                    className="text-foreground/60 hover:text-primary"
                  >
                    View All
                  </Button>
                </CardHeader>
                <Divider />
                <CardBody className="px-3 py-2">
                  {recipesQuery.isLoading ? (
                    <div className="flex items-center justify-center py-6">
                      <Spinner />
                    </div>
                  ) : recipes.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-6">
                      <p className="text-foreground/50 text-sm mb-3">No recipes yet</p>
                      <Button as={Link} to="/recipes" color="primary" size="sm" variant="flat">
                        Create Recipe
                      </Button>
                    </div>
                  ) : (
                    <div className="space-y-1">
                      {recipes.slice(0, 1).map((recipe) => (
                        <RecipeCard key={recipe.path} recipe={recipe} />
                      ))}
                    </div>
                  )}
                </CardBody>
              </Card>
            </motion.div>

            {/* Quick Actions */}
            <motion.div
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.4, duration: 0.4 }}
            >
              <Card className="border border-divider/50">
                <CardHeader className="px-5 py-4">
                  <span className="font-semibold">Quick Actions</span>
                </CardHeader>
                <Divider />
                <CardBody className="p-3">
                  <div className="grid grid-cols-2 gap-2">
                    <QuickActionButton
                      icon={<IconRecipe />}
                      label="New Recipe"
                      to="/recipes"
                    />
                    <QuickActionButton
                      icon={<IconServer />}
                      label="Hosts"
                      to="/hosts"
                    />
                    <QuickActionButton
                      icon={<IconGpu />}
                      label="Vast.ai"
                      to="/vast"
                    />
                    <QuickActionButton
                      icon={<IconSettings />}
                      label="Settings"
                      to="/settings"
                    />
                  </div>
                </CardBody>
              </Card>
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  );
}

import {
  Chip,
  Input,
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
  useDisclosure,
} from "@nextui-org/react";
import { Button } from "../components/ui";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  interactiveRecipeApi,
  recipeApi,
  useCreateRecipe,
  useDeleteRecipe,
  useDuplicateRecipe,
  useHosts,
  useInteractiveExecutions,
  useVastInstances,
  useRecipes,
} from "../lib/tauri-api";
import { useTerminalOptional } from "../contexts/TerminalContext";
import type {
  Host,
  InteractiveExecution,
  InteractiveStatus,
  Recipe,
  RecipeSummary,
} from "../lib/types";
import { vastInstanceToHostCandidate } from "../lib/vast-host";
import { PageLayout, PageSection } from "../components/shared/PageLayout";
import { StatsCard } from "../components/shared/StatsCard";
import { DataTable, CellWithIcon, StatusChip, ActionButton, type ColumnDef, type RowAction } from "../components/shared/DataTable";
import { getStatusBadgeColor } from "../components/shared/StatusBadge";

// Icons
function IconPlus() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
    </svg>
  );
}

function IconPlay() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
    </svg>
  );
}

function IconUpload() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
    </svg>
  );
}

function getStatusColor(status: InteractiveStatus): "default" | "primary" | "secondary" | "success" | "warning" | "danger" {
  switch (status) {
    case "completed":
      return "success";
    case "running":
    case "waiting_for_input":
      return "primary";
    case "failed":
      return "danger";
    case "paused":
    case "connecting":
      return "warning";
    case "cancelled":
      return "default";
    default:
      return "default";
  }
}

function getStatusLabel(status: InteractiveStatus): string {
  switch (status) {
    case "pending":
      return "Pending";
    case "connecting":
      return "Connecting";
    case "running":
      return "Running";
    case "waiting_for_input":
      return "Waiting";
    case "paused":
      return "Paused";
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    case "cancelled":
      return "Cancelled";
    default:
      return status;
  }
}

// ============================================================
// Recipes Table Component
// ============================================================

function RecipesTable({
  recipes,
  isLoading,
  onRun,
  onEdit,
  onDuplicate,
  onDelete,
}: {
  recipes: RecipeSummary[];
  isLoading: boolean;
  onRun: (recipe: RecipeSummary) => void;
  onEdit: (recipe: RecipeSummary) => void;
  onDuplicate: (recipe: RecipeSummary) => void;
  onDelete: (recipe: RecipeSummary) => void;
}) {
  const columns: ColumnDef<RecipeSummary>[] = [
    {
      key: "name",
      header: "Name",
      grow: true,
      minWidth: "180px",
      nowrap: false,
      sortable: true,
      render: (recipe) => (
        <CellWithIcon
          icon={<span className="text-lg">📜</span>}
          title={recipe.name}
          subtitle={recipe.description || undefined}
        />
      ),
    },
    {
      key: "version",
      header: "Version",
      render: (recipe) => <span className="text-foreground/60">v{recipe.version}</span>,
    },
    {
      key: "steps",
      header: "Steps",
      render: (recipe) => <span>{recipe.step_count}</span>,
    },
    {
      key: "actions",
      header: "",
      render: (recipe) => (
        <div className="flex justify-end">
          <ActionButton
            label="Run"
            icon={<IconPlay />}
            color="primary"
            variant="flat"
            onPress={() => onRun(recipe)}
          />
        </div>
      ),
    },
  ];

  const actions: RowAction<RecipeSummary>[] = [
    { key: "edit", label: "Edit", onPress: onEdit },
    { key: "duplicate", label: "Duplicate", onPress: onDuplicate },
    { key: "delete", label: "Delete", color: "danger", onPress: onDelete },
  ];

  return (
    <DataTable
      data={recipes}
      columns={columns}
      rowKey={(recipe) => recipe.path}
      actions={actions}
      onRowClick={onEdit}
      isLoading={isLoading}
      emptyContent="No recipes yet. Create your first recipe to automate training workflows."
      compact
    />
  );
}

// ============================================================
// Executions Table Component
// ============================================================

function ExecutionsTable({
  executions,
  isLoading,
  onClick,
  showProgress = true,
}: {
  executions: InteractiveExecution[];
  isLoading?: boolean;
  onClick: (execution: InteractiveExecution) => void;
  showProgress?: boolean;
}) {
  const columns: ColumnDef<InteractiveExecution>[] = [
    {
      key: "name",
      header: "Recipe",
      grow: true,
      minWidth: "150px",
      nowrap: false,
      render: (exec) => (
        <CellWithIcon
          icon={<span className="text-lg">⚡</span>}
          title={exec.recipe_name}
        />
      ),
    },
    {
      key: "status",
      header: "Status",
      render: (exec) => {
        const badge = getStatusBadgeColor(exec.status);
        return <StatusChip label={badge.label} color={badge.color} />;
      },
    },
    {
      key: "progress",
      header: "Progress",
      minWidth: "100px",
      render: (exec) => {
        const stepsCompleted = exec.steps.filter((s) => s.status === "success").length;
        const stepsFailed = exec.steps.filter((s) => s.status === "failed").length;
        const stepsTotal = exec.steps.length;
        const progressPct = stepsTotal > 0
          ? Math.round(((stepsCompleted + stepsFailed) / stepsTotal) * 100)
          : 0;
        return (
          <div className="flex items-center gap-2">
            <div className="flex-1 h-1.5 bg-content3 rounded-full overflow-hidden min-w-[60px]">
              <div
                className={`h-full rounded-full ${exec.status === "failed" ? "bg-danger" : "bg-primary"}`}
                style={{ width: `${progressPct}%` }}
              />
            </div>
            <span className="text-xs text-foreground/60">{progressPct}%</span>
          </div>
        );
      },
    },
    {
      key: "steps",
      header: "Steps",
      render: (exec) => {
        const stepsCompleted = exec.steps.filter((s) => s.status === "success").length;
        const stepsFailed = exec.steps.filter((s) => s.status === "failed").length;
        const stepsTotal = exec.steps.length;
        if (stepsFailed > 0) {
          return <span className="text-danger">{stepsCompleted}/{stepsTotal} ({stepsFailed} failed)</span>;
        }
        return <span>{stepsCompleted}/{stepsTotal}</span>;
      },
    },
    {
      key: "createdAt",
      header: "Started",
      sortable: true,
      render: (exec) => (
        <span className="text-foreground/60 text-xs">
          {new Date(exec.created_at).toLocaleString()}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      render: (exec) => (
        <div className="flex justify-end">
          <ActionButton
            label="Open"
            variant="flat"
            onPress={() => onClick(exec)}
          />
        </div>
      ),
    },
  ];

  return (
    <DataTable
      data={executions}
      columns={columns}
      rowKey={(exec) => exec.id}
      onRowClick={onClick}
      isLoading={isLoading}
      emptyContent="No executions yet"
      compact
    />
  );
}

export function RecipesPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const terminalContext = useTerminalOptional();
  const { isOpen, onOpen, onClose } = useDisclosure();
  const { isOpen: isRunErrorOpen, onOpen: onRunErrorOpen, onClose: onRunErrorClose } = useDisclosure();
  const [newRecipeName, setNewRecipeName] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  
  const recipesQuery = useRecipes();
  const executionsQuery = useInteractiveExecutions();
  const createMutation = useCreateRecipe();
  const deleteMutation = useDeleteRecipe();
  const duplicateMutation = useDuplicateRecipe();
  
  // Delete confirmation modal
  const { isOpen: isDeleteOpen, onOpen: onDeleteOpen, onClose: onDeleteClose } = useDisclosure();
  const [recipeToDelete, setRecipeToDelete] = useState<string | null>(null);
  
  // Host selection modal for running recipes with targets
  const { isOpen: isHostSelectOpen, onOpen: onHostSelectOpen, onClose: onHostSelectClose } = useDisclosure();
  const [recipeToRun, setRecipeToRun] = useState<{ path: string; recipe: Recipe } | null>(null);
  const [selectedHostId, setSelectedHostId] = useState<string | null>(null);
  const { data: hosts = [] } = useHosts();
  const vastQuery = useVastInstances();
  
  const handleCreate = async () => {
    if (!newRecipeName.trim()) return;
    
    try {
      const path = await createMutation.mutateAsync(newRecipeName);
      onClose();
      setNewRecipeName("");
      navigate({ to: "/recipes/$path", params: { path: encodeURIComponent(path) } });
    } catch (e) {
      console.error("Failed to create recipe:", e);
    }
  };
  
  const handleRunClick = async (path: string) => {
    try {
      // Load the recipe to check if it has a target
      const recipe = await recipeApi.get(path);
      
      if (recipe.target) {
        // Show host selection modal
        setRecipeToRun({ path, recipe });
        setSelectedHostId(null);
        onHostSelectOpen();
      } else {
        // No target, run directly with local execution
        await executeRecipe(path, "__local__");
      }
    } catch (e) {
      console.error("Failed to run recipe:", e);
      const msg =
        typeof e === "object" && e !== null && "message" in e
          ? String((e as { message: unknown }).message)
          : e instanceof Error
            ? e.message
            : String(e);
      setRunError(msg);
      onRunErrorOpen();
    }
  };
  
  const executeRecipe = async (recipePath: string, hostId: string) => {
    setIsRunning(true);
    try {
      const variables: Record<string, string> = {};
      if (hostId && hostId !== "__local__") {
        variables.target = hostId;
      }
      
      // Use interactive execution to run in terminal
      const execution = await interactiveRecipeApi.run({
        path: recipePath,
        hostId,
        variables,
      });
      
      // Immediately seed the query cache with execution data
      // This allows the sidebar to show recipe info instantly
      queryClient.setQueryData(
        ["interactive-executions", execution.id],
        execution
      );
      
      // Add terminal session to context and navigate
      if (terminalContext) {
        if (!execution.terminal_id) {
          throw new Error("Execution did not return a terminal session");
        }
        terminalContext.addRecipeTerminal({
          id: execution.terminal_id,
          title: `Recipe: ${execution.recipe_name}`,
          recipeExecutionId: execution.id,
          hostId: execution.host_id,
        });
      }
      
      // Navigate to terminal page
      navigate({ to: "/terminal" });
    } catch (e) {
      console.error("Failed to run recipe:", e);
      const msg =
        typeof e === "object" && e !== null && "message" in e
          ? String((e as { message: unknown }).message)
          : e instanceof Error
            ? e.message
            : String(e);
      setRunError(msg);
      onRunErrorOpen();
    } finally {
      setIsRunning(false);
    }
  };
  
  const handleConfirmRun = async () => {
    if (!recipeToRun) return;
    if (!selectedHostId && recipeToRun.recipe.target) return; // Must select a host or local
    
    onHostSelectClose();
    await executeRecipe(recipeToRun.path, selectedHostId || "__local__");
    setRecipeToRun(null);
  };

  const handleExecutionClick = async (execution: InteractiveExecution) => {
    try {
      if (execution.terminal_id) {
        if (terminalContext) {
          const existing = terminalContext.getSession(execution.terminal_id);
          if (!existing) {
            terminalContext.addRecipeTerminal({
              id: execution.terminal_id,
              title: `Recipe: ${execution.recipe_name}`,
              recipeExecutionId: execution.id,
              hostId: execution.host_id,
            });
          } else {
            terminalContext.setActiveId(execution.terminal_id);
          }
        }
        navigate({ to: "/terminal" });
        return;
      }

      const resumed = await interactiveRecipeApi.resume(execution.id);
      queryClient.setQueryData(["interactive-executions", resumed.id], resumed);
      queryClient.invalidateQueries({ queryKey: ["interactive-executions"] });
      if (terminalContext && resumed.terminal_id) {
        terminalContext.addRecipeTerminal({
          id: resumed.terminal_id,
          title: `Recipe: ${resumed.recipe_name}`,
          recipeExecutionId: resumed.id,
          hostId: resumed.host_id,
        });
      }
      navigate({ to: "/terminal" });
    } catch (e) {
      console.error("Failed to open execution:", e);
      const msg =
        typeof e === "object" && e !== null && "message" in e
          ? String((e as { message: unknown }).message)
          : e instanceof Error
            ? e.message
            : String(e);
      setRunError(msg);
      onRunErrorOpen();
    }
  };
  
  // Filter hosts based on target requirements
  const allHosts: Host[] = [
    ...hosts,
    ...(vastQuery.data ?? []).map(vastInstanceToHostCandidate),
  ];

  const compatibleHosts = allHosts.filter((host: Host) => {
    if (!recipeToRun?.recipe.target) return true;
    const target = recipeToRun.recipe.target;
    
    // "any" type allows all hosts
    if (target.type === "any") {
      // Still apply GPU/memory filters if specified
    } else if (target.type === "local") {
      // Local target doesn't need remote hosts
      return false;
    } else {
      // Check host type for specific types
      if (target.type !== host.type) return false;
    }
    
    // Check GPU count
    if (target.min_gpus && (host.num_gpus ?? 0) < target.min_gpus) return false;
    
    // Check GPU type (case-insensitive partial match)
    if (target.gpu_type && host.gpu_name) {
      if (!host.gpu_name.toLowerCase().includes(target.gpu_type.toLowerCase())) {
        return false;
      }
    }
    
    // Check memory
    if (target.min_memory_gb && host.system_info?.memory_total_gb) {
      if (host.system_info.memory_total_gb < target.min_memory_gb) return false;
    }
    
    return true;
  });
  
  // Check if Local option should be shown (for "any" or "local" target types)
  const showLocalOption = recipeToRun?.recipe.target?.type === "any" || recipeToRun?.recipe.target?.type === "local";
  
  const handleEdit = (path: string) => {
    navigate({ to: "/recipes/$path", params: { path: encodeURIComponent(path) } });
  };
  
  const handleDuplicate = async (path: string, name: string) => {
    try {
      await duplicateMutation.mutateAsync({ path, newName: `${name} Copy` });
    } catch (e) {
      console.error("Failed to duplicate recipe:", e);
    }
  };
  
  const handleDeleteClick = (path: string) => {
    setRecipeToDelete(path);
    onDeleteOpen();
  };
  
  const handleDeleteConfirm = async () => {
    if (!recipeToDelete) return;
    try {
      await deleteMutation.mutateAsync(recipeToDelete);
      onDeleteClose();
      setRecipeToDelete(null);
    } catch (e) {
      console.error("Failed to delete recipe:", e);
    }
  };
  
  const handleImport = async () => {
    // TODO: Open file picker and import
    console.log("Import recipe");
  };
  
  const recipes = recipesQuery.data ?? [];
  const executions = executionsQuery.data ?? [];
  const activeStatuses: InteractiveStatus[] = [
    "running",
    "paused",
    "waiting_for_input",
    "connecting",
  ];
  const activeExecutions = executions.filter((e) => activeStatuses.includes(e.status));
  const recentExecutions = executions
    .filter((e) => !activeStatuses.includes(e.status))
    .slice(0, 5);
  const completedExecutions = executions.filter(e => e.status === "completed").length;
  const failedExecutions = executions.filter(e => e.status === "failed").length;
  
  return (
    <PageLayout
      title="Recipes"
      subtitle="Automate your training workflows"
      actions={
        <>
          <Button variant="flat" startContent={<IconUpload />} onPress={handleImport}>
            Import
          </Button>
          <Button color="primary" startContent={<IconPlus />} onPress={onOpen}>
            New Recipe
          </Button>
        </>
      }
    >
      {/* Stats */}
      <div className="doppio-stats-grid">
        <StatsCard title="Total Recipes" value={recipes.length} />
        <StatsCard title="Running" value={activeExecutions.length} valueColor="primary" />
        <StatsCard title="Completed" value={completedExecutions} valueColor="success" />
        <StatsCard title="Failed" value={failedExecutions} valueColor="danger" />
      </div>

      {/* Active Executions */}
      {activeExecutions.length > 0 && (
        <PageSection
          title="Running"
          titleRight={
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-primary" />
            </span>
          }
        >
          <ExecutionsTable
            executions={activeExecutions}
            onClick={handleExecutionClick}
          />
        </PageSection>
      )}

      {/* Recipes */}
      <PageSection title="My Recipes">
        <RecipesTable
          recipes={recipes}
          isLoading={recipesQuery.isLoading}
          onRun={(recipe) => handleRunClick(recipe.path)}
          onEdit={(recipe) => handleEdit(recipe.path)}
          onDuplicate={(recipe) => handleDuplicate(recipe.path, recipe.name)}
          onDelete={(recipe) => handleDeleteClick(recipe.path)}
        />
      </PageSection>

      {/* Recent Executions */}
      {recentExecutions.length > 0 && (
        <PageSection title="Recent Runs">
          <ExecutionsTable
            executions={recentExecutions}
            onClick={handleExecutionClick}
          />
        </PageSection>
      )}
      
      {/* Create Recipe Modal */}
      <Modal isOpen={isOpen} onClose={onClose}>
        <ModalContent>
          <ModalHeader>Create New Recipe</ModalHeader>
          <ModalBody>
            <Input labelPlacement="inside" label="Recipe Name"
            placeholder="my-training-recipe"
            value={newRecipeName}
            onValueChange={setNewRecipeName}
            autoFocus />
          </ModalBody>
          <ModalFooter>
            <Button variant="flat" onPress={onClose}>
              Cancel
            </Button>
            <Button
              color="primary"
              onPress={handleCreate}
              isLoading={createMutation.isPending}
              isDisabled={!newRecipeName.trim()}
            >
              Create
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
      
      {/* Delete Confirmation Modal */}
      <Modal isOpen={isDeleteOpen} onClose={onDeleteClose}>
        <ModalContent>
          <ModalHeader>Delete Recipe</ModalHeader>
          <ModalBody>
            <p>Are you sure you want to delete this recipe? This action cannot be undone.</p>
          </ModalBody>
          <ModalFooter>
            <Button variant="flat" onPress={onDeleteClose}>
              Cancel
            </Button>
            <Button
              color="danger"
              onPress={handleDeleteConfirm}
              isLoading={deleteMutation.isPending}
            >
              Delete
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
      
      {/* Host Selection Modal for Running Recipes */}
      <Modal isOpen={isHostSelectOpen} onClose={onHostSelectClose} size="lg">
        <ModalContent>
          <ModalHeader>Select Target Host</ModalHeader>
          <ModalBody>
            {recipeToRun?.recipe.target && (
              <div className="mb-4 p-3 bg-default-100 rounded-lg">
                <p className="text-sm text-foreground/70 mb-2">Recipe requires:</p>
                <div className="flex flex-wrap gap-2">
                  <Chip size="sm" variant="flat">{recipeToRun.recipe.target.type}</Chip>
                  {recipeToRun.recipe.target.gpu_type && (
                    <Chip size="sm" variant="flat">GPU: {recipeToRun.recipe.target.gpu_type}</Chip>
                  )}
                  {recipeToRun.recipe.target.min_gpus && (
                    <Chip size="sm" variant="flat">Min GPUs: {recipeToRun.recipe.target.min_gpus}</Chip>
                  )}
                </div>
              </div>
            )}
            
            <p className="text-sm text-foreground/70 mb-2">Select a compatible host:</p>
            
            {compatibleHosts.length === 0 && !showLocalOption ? (
              <div className="text-center py-8 text-foreground/50">
                <p>No compatible hosts found.</p>
                <p className="text-sm mt-1">Add a {recipeToRun?.recipe.target?.type} host first.</p>
              </div>
            ) : (
              <div className="space-y-2">
                {/* Local option */}
                {showLocalOption && (
                  <div
                    key="__local__"
                    className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                      selectedHostId === "__local__"
                        ? "border-primary bg-primary/10"
                        : "border-default-200 hover:border-default-400"
                    }`}
                    onClick={() => setSelectedHostId("__local__")}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium">Local</span>
                      <Chip size="sm" color="success" variant="flat">ready</Chip>
                    </div>
                    <p className="text-sm text-foreground/60 mt-1">
                      Run on this machine (no SSH)
                    </p>
                  </div>
                )}
                {/* Remote hosts */}
                {compatibleHosts.map((host: Host) => (
                  <div
                    key={host.id}
                    className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                      selectedHostId === host.id
                        ? "border-primary bg-primary/10"
                        : "border-default-200 hover:border-default-400"
                    }`}
                    onClick={() => setSelectedHostId(host.id)}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium">{host.name}</span>
                      <Chip size="sm" variant="flat">{host.type}</Chip>
                    </div>
                    {host.gpu_name && (
                      <p className="text-sm text-foreground/60 mt-1">
                        {host.num_gpus}x {host.gpu_name}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </ModalBody>
          <ModalFooter>
            <Button variant="flat" onPress={onHostSelectClose}>
              Cancel
            </Button>
            <Button
              color="primary"
              onPress={handleConfirmRun}
              isDisabled={!selectedHostId}
              isLoading={isRunning}
            >
              {selectedHostId === "__local__" ? "Run Locally" : "Run Recipe"}
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>

      <Modal isOpen={isRunErrorOpen} onClose={onRunErrorClose} size="lg">
        <ModalContent>
          <ModalHeader>Failed to run recipe</ModalHeader>
          <ModalBody>
            <p className="text-sm text-danger whitespace-pre-wrap">{runError ?? "Unknown error"}</p>
          </ModalBody>
          <ModalFooter>
            <Button variant="flat" onPress={onRunErrorClose}>
              Close
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </PageLayout>
  );
}

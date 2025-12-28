import {
  Card,
  CardBody,
  CardHeader,
  Chip,
  Divider,
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
  Input,
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
  Progress,
  Spinner,
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
  useRecipeExecutions,
  useRecipes,
} from "../lib/tauri-api";
import { useTerminalOptional } from "../contexts/TerminalContext";
import type { ExecutionStatus, ExecutionSummary, Host, Recipe, RecipeSummary } from "../lib/types";

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

function IconDots() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 12.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 18.75a.75.75 0 110-1.5.75.75 0 010 1.5z" />
    </svg>
  );
}

function IconDocument() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
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

function getStatusLabel(status: ExecutionStatus): string {
  switch (status) {
    case "pending": return "Pending";
    case "running": return "Running";
    case "paused": return "Paused";
    case "completed": return "Completed";
    case "failed": return "Failed";
    case "cancelled": return "Cancelled";
    default: return status;
  }
}

function RecipeCard({ recipe, onRun, onEdit, onDuplicate, onDelete }: {
  recipe: RecipeSummary;
  onRun: () => void;
  onEdit: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
}) {
  return (
    <Card className="h-full border border-divider hover:border-primary/50 transition-colors">
      <CardBody className="flex flex-col gap-3">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl">📜</span>
            <div>
              <h3 className="font-semibold">{recipe.name}</h3>
              <p className="text-xs text-foreground/60">v{recipe.version} • {recipe.step_count} steps</p>
            </div>
          </div>
          <Dropdown>
            <DropdownTrigger>
              <Button isIconOnly size="sm" variant="light">
                <IconDots />
              </Button>
            </DropdownTrigger>
            <DropdownMenu aria-label="Recipe actions">
              <DropdownItem key="edit" onPress={onEdit}>Edit</DropdownItem>
              <DropdownItem key="duplicate" onPress={onDuplicate}>Duplicate</DropdownItem>
              <DropdownItem key="delete" className="text-danger" color="danger" onPress={onDelete}>
                Delete
              </DropdownItem>
            </DropdownMenu>
          </Dropdown>
        </div>

        {recipe.description && (
          <p className="text-sm text-foreground/70 truncate" title={recipe.description}>
            {recipe.description}
          </p>
        )}

        {/* Spacer to push buttons to bottom */}
        <div className="flex-1" />

        <div className="flex gap-2">
          <Button
            size="sm"
            color="primary"
            variant="flat"
            startContent={<IconPlay />}
            onPress={onRun}
          >
            Run
          </Button>
          <Button
            size="sm"
            variant="flat"
            onPress={onEdit}
          >
            Edit
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

function ExecutionCard({ execution, onClick }: {
  execution: ExecutionSummary;
  onClick: () => void;
}) {
  const progress = execution.steps_total > 0
    ? ((execution.steps_completed + execution.steps_failed) / execution.steps_total) * 100
    : 0;
  
  return (
    <Card 
      isPressable 
      onPress={onClick}
      className="border border-divider hover:border-primary/50 transition-colors"
    >
      <CardBody className="p-4">
        <div className="flex items-center justify-between gap-3 mb-2">
          <h4 className="font-medium truncate">{execution.recipe_name}</h4>
          <Chip size="sm" color={getStatusColor(execution.status)} variant="flat">
            {getStatusLabel(execution.status)}
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
            {execution.steps_failed > 0 && ` (${execution.steps_failed} failed)`}
          </span>
          <span>{new Date(execution.created_at).toLocaleString()}</span>
        </div>
      </CardBody>
    </Card>
  );
}

export function RecipesPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const terminalContext = useTerminalOptional();
  const { isOpen, onOpen, onClose } = useDisclosure();
  const [newRecipeName, setNewRecipeName] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  
  const recipesQuery = useRecipes();
  const executionsQuery = useRecipeExecutions();
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
  
  // Filter hosts based on target requirements
  const compatibleHosts = hosts.filter((host: Host) => {
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
  const activeExecutions = executions.filter(e => e.status === "running" || e.status === "paused");
  const recentExecutions = executions.filter(e => e.status !== "running" && e.status !== "paused").slice(0, 5);
  const completedExecutions = executions.filter(e => e.status === "completed").length;
  const failedExecutions = executions.filter(e => e.status === "failed").length;
  
  return (
    <div className="h-full p-6 overflow-auto">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold">Recipes</h1>
            <p className="text-sm text-foreground/60">Automate your training workflows</p>
          </div>
          <div className="flex gap-2">
            <Button variant="flat" startContent={<IconUpload />} onPress={handleImport}>
              Import
            </Button>
            <Button color="primary" startContent={<IconPlus />} onPress={onOpen}>
              New Recipe
            </Button>
          </div>
        </div>
        
        {/* Stats */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
          <Card>
            <CardBody>
              <p className="text-sm text-foreground/60">Total Recipes</p>
              <p className="text-2xl font-bold">{recipes.length}</p>
            </CardBody>
          </Card>
          <Card>
            <CardBody>
              <p className="text-sm text-foreground/60">Running</p>
              <p className="text-2xl font-bold text-primary">{activeExecutions.length}</p>
            </CardBody>
          </Card>
          <Card>
            <CardBody>
              <p className="text-sm text-foreground/60">Completed</p>
              <p className="text-2xl font-bold text-success">{completedExecutions}</p>
            </CardBody>
          </Card>
          <Card>
            <CardBody>
              <p className="text-sm text-foreground/60">Failed</p>
              <p className="text-2xl font-bold text-danger">{failedExecutions}</p>
            </CardBody>
          </Card>
        </div>
        
        {/* Active Executions */}
        {activeExecutions.length > 0 && (
          <div className="mb-8">
            <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-primary" />
              </span>
              Running
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {activeExecutions.map(exec => (
                <ExecutionCard
                  key={exec.id}
                  execution={exec}
                  onClick={() => navigate({ to: "/recipes/executions/$id", params: { id: exec.id } })}
                />
              ))}
            </div>
          </div>
        )}
        
        {/* Recipes */}
        <div className="mb-8">
          <h2 className="text-lg font-semibold mb-4">My Recipes</h2>
            
            {recipesQuery.isLoading ? (
              <div className="flex items-center justify-center py-12">
                <Spinner size="lg" />
              </div>
            ) : recipes.length === 0 ? (
              <Card className="border border-dashed border-divider">
                <CardBody className="text-center py-12">
                  <div className="flex justify-center mb-4 text-foreground/40">
                    <IconDocument />
                  </div>
                  <h3 className="font-semibold mb-2">No recipes yet</h3>
                  <p className="text-sm text-foreground/60 mb-4">
                    Create your first recipe to automate training workflows
                  </p>
                  <Button color="primary" onPress={onOpen}>
                    Create Recipe
                  </Button>
                </CardBody>
              </Card>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {recipes.map(recipe => (
                  <RecipeCard
                    key={recipe.path}
                    recipe={recipe}
                    onRun={() => handleRunClick(recipe.path)}
                    onEdit={() => handleEdit(recipe.path)}
                    onDuplicate={() => handleDuplicate(recipe.path, recipe.name)}
                    onDelete={() => handleDeleteClick(recipe.path)}
                  />
                ))}
              </div>
            )}
        </div>
        
        {/* Recent Executions */}
        {recentExecutions.length > 0 && (
          <div className="mb-8">
            <h2 className="text-lg font-semibold mb-4">Recent Runs</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {recentExecutions.map(exec => (
                <ExecutionCard
                  key={exec.id}
                  execution={exec}
                  onClick={() => navigate({ to: "/recipes/executions/$id", params: { id: exec.id } })}
                />
              ))}
            </div>
          </div>
        )}
      </div>
      
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
    </div>
  );
}


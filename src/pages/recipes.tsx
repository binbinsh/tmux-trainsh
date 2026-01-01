import {
  Chip,
  Input,
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
  Select,
  SelectItem,
  Spinner,
  Tooltip,
  useDisclosure,
} from "@nextui-org/react";
import { Button } from "../components/ui";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
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
} from "../lib/types";
import { vastInstanceToHostCandidate } from "../lib/vast-host";
import { EmptyHostState, HostRow, HostSection } from "../components/shared/HostCard";
import type { RecipeFolder } from "../lib/recipe-folders";
import {
  getAssignedFolderId,
  loadRecipeFolderAssignments,
  loadRecipeFolders,
  saveRecipeFolderAssignments,
  saveRecipeFolders,
  setAssignedFolderId,
} from "../lib/recipe-folders";

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

function IconFolder({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 6.75A2.25 2.25 0 014.5 4.5h4.379c.597 0 1.17.237 1.591.659l.621.621c.422.422.994.659 1.591.659H19.5A2.25 2.25 0 0121.75 8.25v9A2.25 2.25 0 0119.5 19.5h-15A2.25 2.25 0 012.25 17.25v-10.5z" />
    </svg>
  );
}

function IconArchive({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 7.5l-.72-3.6A1.5 1.5 0 0018.06 2.75H5.94A1.5 1.5 0 004.47 3.9l-.72 3.6m16.5 0H3.75m16.5 0v12A1.5 1.5 0 0118.75 21h-13.5A1.5 1.5 0 013.75 19.5v-12m8.25 4.5v4.5m0 0l-2.25-2.25M12 16.5l2.25-2.25" />
    </svg>
  );
}

function IconRestore({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9.03 3.376c-.866 1.5-2.9 3.374-4.631 3.374H7.601c-1.73 0-3.564-1.874-4.43-3.374L1.5 12l1.671-3.376C4.037 7.124 5.87 5.25 7.6 5.25h8.799c1.73 0 3.765 1.874 4.631 3.374L22.5 12l-1.47 3.376z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 9.75L12 7.5l2.25 2.25" />
    </svg>
  );
}

function IconTerminal({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 7.5l3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0021 18V6a2.25 2.25 0 00-2.25-2.25H5.25A2.25 2.25 0 003 6v12a2.25 2.25 0 002.25 2.25z" />
    </svg>
  );
}

function IconCancel() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
    </svg>
  );
}

function IconSearch({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
    </svg>
  );
}

function IconFilter({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 3c2.755 0 5.455.232 8.083.678.533.09.917.556.917 1.096v1.044a2.25 2.25 0 01-.659 1.591l-5.432 5.432a2.25 2.25 0 00-.659 1.591v2.927a2.25 2.25 0 01-1.244 2.013L9.75 21v-6.568a2.25 2.25 0 00-.659-1.591L3.659 7.409A2.25 2.25 0 013 5.818V4.774c0-.54.384-1.006.917-1.096A48.32 48.32 0 0112 3z" />
    </svg>
  );
}

function IconSort({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 7.5L7.5 3m0 0L12 7.5M7.5 3v13.5m13.5 0L16.5 21m0 0L12 16.5m4.5 4.5V7.5" />
    </svg>
  );
}

function IconEllipsis({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 12.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 18.75a.75.75 0 110-1.5.75.75 0 010 1.5z" />
    </svg>
  );
}

function IconEdit({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125" />
    </svg>
  );
}

function IconTrash({ className }: { className?: string }) {
  return (
    <svg className={className ?? "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
    </svg>
  );
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

function getExecutionProgressLabel(execution: InteractiveExecution): string {
  const stepsCompleted = execution.steps.filter((s) => s.status === "success").length;
  const stepsFailed = execution.steps.filter((s) => s.status === "failed").length;
  const stepsTotal = execution.steps.length;
  return stepsTotal > 0
    ? `${stepsCompleted + stepsFailed}/${stepsTotal}`
    : "0/0";
}

function getExecutionTagColor(status: InteractiveStatus): "default" | "primary" | "warning" {
  switch (status) {
    case "running":
    case "waiting_for_input":
      return "primary";
    case "paused":
    case "connecting":
    case "pending":
      return "warning";
    default:
      return "default";
  }
}

export function RecipesPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const terminalContext = useTerminalOptional();
  const createRecipeModal = useDisclosure();
  const createFolderModal = useDisclosure();
  const deleteFolderModal = useDisclosure();
  const moveRecipeModal = useDisclosure();
  const { isOpen: isRunErrorOpen, onOpen: onRunErrorOpen, onClose: onRunErrorClose } = useDisclosure();
  const [newRecipeName, setNewRecipeName] = useState("");
  const [newRecipeFolderKey, setNewRecipeFolderKey] = useState<string>("__root__");
  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const [folders, setFolders] = useState<RecipeFolder[]>(() => loadRecipeFolders());
  const [folderAssignments, setFolderAssignments] = useState<Record<string, string>>(
    () => loadRecipeFolderAssignments()
  );
  const [folderScopeKey, setFolderScopeKey] = useState<string>("all");
  const [newFolderName, setNewFolderName] = useState("");
  const [folderError, setFolderError] = useState<string | null>(null);
  const [folderToDelete, setFolderToDelete] = useState<RecipeFolder | null>(null);
  const [deletingFolder, setDeletingFolder] = useState(false);
  const [moveRecipePath, setMoveRecipePath] = useState<string | null>(null);
  const [moveTargetFolderKey, setMoveTargetFolderKey] = useState<string>("__root__");
  
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

  function safeUuid(): string {
    try {
      return crypto.randomUUID();
    } catch {
      return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }
  }

  const foldersById = useMemo(() => new Map(folders.map((f) => [f.id, f])), [folders]);
  const activeFolders = useMemo(
    () => [...folders].filter((f) => f.status === "active").sort((a, b) => a.name.localeCompare(b.name)),
    [folders]
  );
  const archivedFolders = useMemo(
    () => [...folders].filter((f) => f.status === "archived").sort((a, b) => a.name.localeCompare(b.name)),
    [folders]
  );

  function persistFolders(updater: (prev: RecipeFolder[]) => RecipeFolder[]) {
    setFolders((prev) => {
      const next = updater(prev);
      saveRecipeFolders(next);
      return next;
    });
  }

  function persistAssignments(updater: (prev: Record<string, string>) => Record<string, string>) {
    setFolderAssignments((prev) => {
      const next = updater(prev);
      saveRecipeFolderAssignments(next);
      return next;
    });
  }

  const folderScopeFolderId =
    folderScopeKey.startsWith("folder:") ? folderScopeKey.slice("folder:".length) : null;
  const folderScopeFolder = folderScopeFolderId ? foldersById.get(folderScopeFolderId) ?? null : null;
  const folderScopeLabel =
    folderScopeKey === "all"
      ? "All"
      : folderScopeKey === "recipes"
        ? "Recipes"
        : folderScopeFolder
          ? folderScopeFolder.status === "archived"
            ? `${folderScopeFolder.name} (archived)`
            : folderScopeFolder.name
          : "Folder";

  function openCreateRecipeModalWithContext() {
    setNewRecipeName("");
    setFolderError(null);
    setNewRecipeFolderKey(folderScopeKey.startsWith("folder:") ? folderScopeKey : "__root__");
    createRecipeModal.onOpen();
  }

  function openCreateFolderModal() {
    setNewFolderName("");
    setFolderError(null);
    createFolderModal.onOpen();
  }
  
  const handleCreate = async () => {
    if (!newRecipeName.trim()) return;
    
    try {
      const path = await createMutation.mutateAsync(newRecipeName);
      const folderId = newRecipeFolderKey.startsWith("folder:")
        ? newRecipeFolderKey.slice("folder:".length)
        : null;
      if (folderId) {
        persistAssignments((prev) => setAssignedFolderId(prev, path, folderId));
      }
      createRecipeModal.onClose();
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

  const handleCancelExecution = async (execution: InteractiveExecution) => {
    try {
      await interactiveRecipeApi.cancel(execution.id);
      queryClient.invalidateQueries({ queryKey: ["interactive-executions"] });
    } catch (e) {
      console.error("Failed to cancel execution:", e);
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
      const newPath = await duplicateMutation.mutateAsync({ path, newName: `${name} Copy` });
      persistAssignments((prev) => {
        const folderId = getAssignedFolderId(prev, path);
        return folderId ? setAssignedFolderId(prev, newPath, folderId) : prev;
      });
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
      persistAssignments((prev) => setAssignedFolderId(prev, recipeToDelete, null));
      setSelectedRecipePath((prev) => (prev === recipeToDelete ? null : prev));
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

  function folderKeyFromId(folderId: string | null): string {
    return folderId ? `folder:${folderId}` : "__root__";
  }

  function folderIdFromKey(folderKey: string): string | null {
    return folderKey.startsWith("folder:") ? folderKey.slice("folder:".length) : null;
  }

  const handleCreateFolder = async () => {
    const name = newFolderName.trim();
    if (!name) {
      setFolderError("Folder name is required.");
      return;
    }
    const exists = folders.some((f) => f.name.trim().toLowerCase() === name.toLowerCase());
    if (exists) {
      setFolderError("A folder with this name already exists.");
      return;
    }

    const newFolder: RecipeFolder = {
      id: safeUuid(),
      name,
      status: "active",
      created_at: new Date().toISOString(),
    };

    persistFolders((prev) => [...prev, newFolder].sort((a, b) => a.name.localeCompare(b.name)));
    createFolderModal.onClose();
    setFolderScopeKey(`folder:${newFolder.id}`);
  };

  const handleToggleArchiveFolder = (folderId: string) => {
    persistFolders((prev) =>
      prev.map((f) =>
        f.id === folderId
          ? { ...f, status: f.status === "archived" ? "active" : "archived" }
          : f
      )
    );
  };

  const handleRequestDeleteFolder = (folder: RecipeFolder) => {
    setFolderError(null);
    setFolderToDelete(folder);
    deleteFolderModal.onOpen();
  };

  const handleConfirmDeleteFolder = async () => {
    if (!folderToDelete) return;
    if (!recipesQuery.data) return;

    setFolderError(null);
    setDeletingFolder(true);
    try {
      const targetFolderId = folderToDelete.id;
      const pathsToDelete = recipes
        .filter((r) => folderAssignments[r.path] === targetFolderId)
        .map((r) => r.path);

      await Promise.all(pathsToDelete.map((p) => recipeApi.delete(p)));
      await queryClient.invalidateQueries({ queryKey: ["recipes"] });

      persistAssignments((prev) => {
        const next = { ...prev };
        for (const p of pathsToDelete) delete next[p];
        return next;
      });

      persistFolders((prev) => prev.filter((f) => f.id !== targetFolderId));

      setSelectedRecipePath((prev) => (pathsToDelete.includes(prev ?? "") ? null : prev));
      setFolderScopeKey((prev) => (prev === `folder:${targetFolderId}` ? "all" : prev));
      deleteFolderModal.onClose();
      setFolderToDelete(null);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setFolderError(msg);
    } finally {
      setDeletingFolder(false);
    }
  };

  const handleOpenMoveRecipe = (recipePath: string) => {
    setFolderError(null);
    setMoveRecipePath(recipePath);
    setMoveTargetFolderKey(folderKeyFromId(getAssignedFolderId(folderAssignments, recipePath)));
    moveRecipeModal.onOpen();
  };

  const handleConfirmMoveRecipe = async () => {
    if (!moveRecipePath) return;
    const folderId = folderIdFromKey(moveTargetFolderKey);
    persistAssignments((prev) => setAssignedFolderId(prev, moveRecipePath, folderId));
    moveRecipeModal.onClose();
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

  const [searchQuery, setSearchQuery] = useState("");
  const [selectedRecipePath, setSelectedRecipePath] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState<"all" | "running" | "idle">("all");
  const [sortBy, setSortBy] = useState<"name" | "steps">("name");

  const activeByRecipePath = useMemo(() => {
    const map = new Map<string, number>();
    for (const exec of activeExecutions) {
      map.set(exec.recipe_path, (map.get(exec.recipe_path) || 0) + 1);
    }
    return map;
  }, [activeExecutions]);

  const filteredRecipes = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    let list = recipes;
    if (q) {
      list = list.filter((r) => {
        const haystack = `${r.name} ${r.description ?? ""} ${r.path}`.toLowerCase();
        return haystack.includes(q);
      });
    }
    if (filterStatus === "running") {
      list = list.filter((r) => (activeByRecipePath.get(r.path) || 0) > 0);
    }
    if (filterStatus === "idle") {
      list = list.filter((r) => (activeByRecipePath.get(r.path) || 0) === 0);
    }
    const sorted = [...list];
    sorted.sort((a, b) => {
      if (sortBy === "steps") return b.step_count - a.step_count;
      return a.name.localeCompare(b.name);
    });
    return sorted;
  }, [activeByRecipePath, filterStatus, recipes, searchQuery, sortBy]);

  useEffect(() => {
    if (!recipesQuery.data) return;
    const recipePaths = new Set(recipes.map((r) => r.path));
    const folderIds = new Set(folders.map((f) => f.id));
    setFolderAssignments((prev) => {
      let changed = false;
      const next: Record<string, string> = {};
      for (const [recipePath, folderId] of Object.entries(prev)) {
        if (!recipePaths.has(recipePath)) {
          changed = true;
          continue;
        }
        if (!folderIds.has(folderId)) {
          changed = true;
          continue;
        }
        next[recipePath] = folderId;
      }
      if (!changed) return prev;
      saveRecipeFolderAssignments(next);
      return next;
    });
  }, [folders, recipes, recipesQuery.data]);

  const recipeSections = useMemo(() => {
    const rootRecipes: typeof filteredRecipes = [];
    const byFolder = new Map<string, typeof filteredRecipes>();

    if (folderScopeKey.startsWith("folder:")) {
      const folderId = folderScopeKey.slice("folder:".length);
      const folder = foldersById.get(folderId) ?? null;
      const list = filteredRecipes.filter((r) => folderAssignments[r.path] === folderId);
      return {
        rootRecipes: [],
        folderSections: folder ? [{ folder, recipes: list }] : [],
      };
    }

    for (const recipe of filteredRecipes) {
      const assignedFolderId = folderAssignments[recipe.path] ?? null;
      if (!assignedFolderId) {
        if (folderScopeKey !== "recipes") {
          rootRecipes.push(recipe);
        } else {
          rootRecipes.push(recipe);
        }
        continue;
      }

      if (folderScopeKey === "recipes") {
        continue;
      }

      const folder = foldersById.get(assignedFolderId) ?? null;
      if (!folder) {
        rootRecipes.push(recipe);
        continue;
      }

      if (folder.status === "archived") {
        continue;
      }

      const arr = byFolder.get(folder.id) ?? [];
      arr.push(recipe);
      byFolder.set(folder.id, arr);
    }

    const folderSections = activeFolders
      .map((folder) => ({ folder, recipes: byFolder.get(folder.id) ?? [] }))
      .filter((s) => s.recipes.length > 0);

    return { rootRecipes, folderSections };
  }, [activeFolders, filteredRecipes, folderAssignments, folderScopeKey, foldersById]);

  const visibleRecipePathSet = useMemo(() => {
    const s = new Set<string>();
    for (const r of recipeSections.rootRecipes) s.add(r.path);
    for (const section of recipeSections.folderSections) {
      for (const r of section.recipes) s.add(r.path);
    }
    return s;
  }, [recipeSections]);

  useEffect(() => {
    if (!selectedRecipePath) return;
    const exists = visibleRecipePathSet.has(selectedRecipePath);
    if (!exists) setSelectedRecipePath(null);
  }, [selectedRecipePath, visibleRecipePathSet]);

  const canRunSelected = Boolean(selectedRecipePath);

  const hostNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const h of allHosts) map.set(h.id, h.name);
    map.set("__local__", "Local");
    return map;
  }, [allHosts]);
  
  const isLoading = recipesQuery.isLoading || executionsQuery.isLoading;

  return (
    <div className="doppio-page">
      <div className="doppio-page-content">
        {/* Termius-style Toolbar */}
        <div className="termius-toolbar">
          {/* Row 1: Search + Run */}
          <div className="termius-toolbar-row">
            <div className="termius-search-bar">
              <Input
                size="lg"
                placeholder="Search recipes..."
                value={searchQuery}
                onValueChange={setSearchQuery}
                startContent={<IconSearch className="w-5 h-5 text-foreground/40" />}
                endContent={
                  <Button
                    color="primary"
                    size="sm"
                    className="h-8 px-4"
                    onPress={() => {
                      if (!selectedRecipePath) return;
                      void handleRunClick(selectedRecipePath);
                    }}
                    isDisabled={!canRunSelected}
                  >
                    Run
                  </Button>
                }
                classNames={{
                  base: "flex-1",
                  inputWrapper: "bg-content2 h-12",
                  input: "text-base",
                }}
              />
            </div>
          </div>

          {/* Row 2: Quick Actions + Filters */}
          <div className="termius-toolbar-row justify-between">
            <div className="termius-quick-actions">
              <button className="termius-quick-action" onClick={openCreateRecipeModalWithContext}>
                <IconPlus className="w-4 h-4" />
                <span>New Recipe</span>
              </button>
              <button className="termius-quick-action" onClick={openCreateFolderModal}>
                <IconFolder className="w-4 h-4" />
                <span>New Folder</span>
              </button>
              <button className="termius-quick-action" onClick={() => void handleImport()}>
                <IconUpload className="w-4 h-4" />
                <span>Import</span>
              </button>
              <button
                className="termius-quick-action"
                onClick={() => navigate({ to: "/terminal", search: { connectHostId: undefined, connectVastInstanceId: undefined, connectLabel: undefined } })}
              >
                <IconTerminal className="w-4 h-4" />
                <span>Terminal</span>
              </button>
            </div>

            <div className="flex items-center gap-1">
              <Dropdown>
                <DropdownTrigger>
                  <button className={`termius-quick-action ${folderScopeKey !== "all" ? "termius-quick-action-primary" : ""}`}>
                    <IconFolder className="w-4 h-4" />
                    <span>{folderScopeLabel}</span>
                  </button>
                </DropdownTrigger>
                <DropdownMenu
                  selectionMode="single"
                  selectedKeys={new Set([folderScopeKey])}
                  onSelectionChange={(keys) => {
                    const selected = Array.from(keys)[0] as string;
                    setFolderScopeKey(selected);
                  }}
                >
                  <DropdownItem key="all">All</DropdownItem>
                  <DropdownItem key="recipes">Recipes</DropdownItem>
                  {activeFolders.map((f) => (
                    <DropdownItem key={`folder:${f.id}`}>{f.name}</DropdownItem>
                  ))}
                  {archivedFolders.map((f) => (
                    <DropdownItem key={`folder:${f.id}`}>{f.name} (archived)</DropdownItem>
                  ))}
                </DropdownMenu>
              </Dropdown>

              <Dropdown>
                <DropdownTrigger>
                  <button className={`termius-quick-action ${filterStatus !== "all" ? "termius-quick-action-primary" : ""}`}>
                    <IconFilter className="w-4 h-4" />
                    <span>{filterStatus === "all" ? "Filter" : filterStatus}</span>
                  </button>
                </DropdownTrigger>
                <DropdownMenu
                  selectionMode="single"
                  selectedKeys={new Set([filterStatus])}
                  onSelectionChange={(keys) => {
                    const selected = Array.from(keys)[0] as "all" | "running" | "idle";
                    setFilterStatus(selected);
                  }}
                >
                  <DropdownItem key="all">All</DropdownItem>
                  <DropdownItem key="running">Running</DropdownItem>
                  <DropdownItem key="idle">Idle</DropdownItem>
                </DropdownMenu>
              </Dropdown>

              <Dropdown>
                <DropdownTrigger>
                  <button className="termius-quick-action">
                    <IconSort className="w-4 h-4" />
                    <span>{sortBy === "name" ? "Name" : "Steps"}</span>
                  </button>
                </DropdownTrigger>
                <DropdownMenu
                  selectionMode="single"
                  selectedKeys={new Set([sortBy])}
                  onSelectionChange={(keys) => {
                    const selected = Array.from(keys)[0] as "name" | "steps";
                    setSortBy(selected);
                  }}
                >
                  <DropdownItem key="name">Name</DropdownItem>
                  <DropdownItem key="steps">Steps</DropdownItem>
                </DropdownMenu>
              </Dropdown>
            </div>
          </div>
        </div>

        {/* Content */}
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Spinner size="lg" />
          </div>
        ) : (
          <>
            {activeExecutions.length > 0 && (
              <HostSection title="RUNNING" count={activeExecutions.length}>
                {activeExecutions.map((exec) => {
                  const hostName = hostNameById.get(exec.host_id) || exec.host_id;
                  const rightTags: { label: string; color?: "default" | "primary" | "warning" }[] = [
                    { label: getStatusLabel(exec.status), color: getExecutionTagColor(exec.status) },
                    { label: getExecutionProgressLabel(exec), color: "default" },
                  ];

                  return (
                    <HostRow
                      key={exec.id}
                      icon={<span className="text-lg">⚡</span>}
                      title={exec.recipe_name}
                      subtitle={`${hostName} · ${new Date(exec.created_at).toLocaleString()}`}
                      rightTags={rightTags}
                      isOnline={true}
                      onClick={() => void handleExecutionClick(exec)}
                      hoverActions={
                        <div
                          className="flex items-center gap-1"
                          onMouseDown={(e) => e.stopPropagation()}
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Tooltip content="Cancel" delay={500}>
                            <Button
                              size="sm"
                              variant="light"
                              isIconOnly
                              className="w-7 h-7 min-w-7 opacity-60 hover:opacity-100 text-danger"
                              onPress={() => void handleCancelExecution(exec)}
                            >
                              <IconCancel />
                            </Button>
                          </Tooltip>
                        </div>
                      }
                    />
                  );
                })}
              </HostSection>
            )}

            {(recipeSections.rootRecipes.length > 0 || recipeSections.folderSections.length > 0) ? (
              <>
                {recipeSections.rootRecipes.length > 0 && (
                  <HostSection title="RECIPES" count={recipeSections.rootRecipes.length}>
                    {recipeSections.rootRecipes.map((recipe) => {
                      const activeCount = activeByRecipePath.get(recipe.path) || 0;
                      const rightTags: { label: string; color?: "default" | "primary" | "warning" }[] = [];
                      if (activeCount > 0) {
                        rightTags.push({ label: `${activeCount} running`, color: "warning" });
                      }

                      return (
                        <HostRow
                          key={recipe.path}
                          icon={<span className="text-lg">📜</span>}
                          title={recipe.name}
                          subtitle={recipe.description || undefined}
                          rightTags={rightTags}
                          isOnline={activeCount > 0}
                          isSelected={selectedRecipePath === recipe.path}
                          onClick={() => setSelectedRecipePath(recipe.path)}
                          onDoubleClick={() => handleEdit(recipe.path)}
                          hoverActions={
                            <div
                              className="flex items-center gap-1"
                              onMouseDown={(e) => e.stopPropagation()}
                              onClick={(e) => e.stopPropagation()}
                            >
                              <Tooltip content="Run" delay={500}>
                                <Button
                                  size="sm"
                                  variant="light"
                                  isIconOnly
                                  className="w-7 h-7 min-w-7 opacity-60 hover:opacity-100"
                                  onPress={() => void handleRunClick(recipe.path)}
                                >
                                  <IconPlay />
                                </Button>
                              </Tooltip>

                              <Tooltip content="Edit" delay={500}>
                                <Button
                                  size="sm"
                                  variant="light"
                                  isIconOnly
                                  className="w-7 h-7 min-w-7 opacity-60 hover:opacity-100"
                                  onPress={() => handleEdit(recipe.path)}
                                >
                                  <IconEdit />
                                </Button>
                              </Tooltip>

                              <Dropdown placement="bottom-end">
                                <DropdownTrigger>
                                  <Button
                                    size="sm"
                                    variant="light"
                                    isIconOnly
                                    className="w-7 h-7 min-w-7 opacity-60 hover:opacity-100"
                                  >
                                    <IconEllipsis />
                                  </Button>
                                </DropdownTrigger>
                                <DropdownMenu aria-label="Recipe actions">
                                  <DropdownItem
                                    key="move"
                                    onPress={() => handleOpenMoveRecipe(recipe.path)}
                                  >
                                    Move to folder…
                                  </DropdownItem>
                                  <DropdownItem
                                    key="duplicate"
                                    onPress={() => void handleDuplicate(recipe.path, recipe.name)}
                                  >
                                    Duplicate
                                  </DropdownItem>
                                  <DropdownItem
                                    key="delete"
                                    color="danger"
                                    className="text-danger"
                                    startContent={<IconTrash className="w-4 h-4" />}
                                    onPress={() => handleDeleteClick(recipe.path)}
                                  >
                                    Delete
                                  </DropdownItem>
                                </DropdownMenu>
                              </Dropdown>
                            </div>
                          }
                        />
                      );
                    })}
                  </HostSection>
                )}

                {recipeSections.folderSections.map(({ folder, recipes }) => (
                  <HostSection
                    key={folder.id}
                    title={folder.name}
                    count={recipes.length}
                    actions={
                      <div className="flex items-center gap-1">
                        <Tooltip content={folder.status === "archived" ? "Restore" : "Archive"} delay={500}>
                          <Button
                            size="sm"
                            variant="light"
                            isIconOnly
                            className="w-7 h-7 min-w-7 opacity-60 hover:opacity-100"
                            onPress={() => handleToggleArchiveFolder(folder.id)}
                          >
                            {folder.status === "archived" ? <IconRestore /> : <IconArchive />}
                          </Button>
                        </Tooltip>
                        <Tooltip content="Delete folder" delay={500}>
                          <Button
                            size="sm"
                            variant="light"
                            isIconOnly
                            className="w-7 h-7 min-w-7 opacity-60 hover:opacity-100 text-danger"
                            onPress={() => handleRequestDeleteFolder(folder)}
                          >
                            <IconTrash />
                          </Button>
                        </Tooltip>
                      </div>
                    }
                  >
                    {recipes.length > 0 ? (
                      recipes.map((recipe) => {
                        const activeCount = activeByRecipePath.get(recipe.path) || 0;
                        const rightTags: { label: string; color?: "default" | "primary" | "warning" }[] = [];
                        if (activeCount > 0) {
                          rightTags.push({ label: `${activeCount} running`, color: "warning" });
                        }

                        return (
                          <HostRow
                            key={recipe.path}
                            icon={<span className="text-lg">📜</span>}
                            title={recipe.name}
                            subtitle={recipe.description || undefined}
                            rightTags={rightTags}
                            isOnline={activeCount > 0}
                            isSelected={selectedRecipePath === recipe.path}
                            onClick={() => setSelectedRecipePath(recipe.path)}
                            onDoubleClick={() => handleEdit(recipe.path)}
                            hoverActions={
                              <div
                                className="flex items-center gap-1"
                                onMouseDown={(e) => e.stopPropagation()}
                                onClick={(e) => e.stopPropagation()}
                              >
                                <Tooltip content="Run" delay={500}>
                                  <Button
                                    size="sm"
                                    variant="light"
                                    isIconOnly
                                    className="w-7 h-7 min-w-7 opacity-60 hover:opacity-100"
                                    onPress={() => void handleRunClick(recipe.path)}
                                  >
                                    <IconPlay />
                                  </Button>
                                </Tooltip>

                                <Tooltip content="Edit" delay={500}>
                                  <Button
                                    size="sm"
                                    variant="light"
                                    isIconOnly
                                    className="w-7 h-7 min-w-7 opacity-60 hover:opacity-100"
                                    onPress={() => handleEdit(recipe.path)}
                                  >
                                    <IconEdit />
                                  </Button>
                                </Tooltip>

                                <Dropdown placement="bottom-end">
                                  <DropdownTrigger>
                                    <Button
                                      size="sm"
                                      variant="light"
                                      isIconOnly
                                      className="w-7 h-7 min-w-7 opacity-60 hover:opacity-100"
                                    >
                                      <IconEllipsis />
                                    </Button>
                                  </DropdownTrigger>
                                  <DropdownMenu aria-label="Recipe actions">
                                    <DropdownItem
                                      key="move"
                                      onPress={() => handleOpenMoveRecipe(recipe.path)}
                                    >
                                      Move to folder…
                                    </DropdownItem>
                                    <DropdownItem
                                      key="duplicate"
                                      onPress={() => void handleDuplicate(recipe.path, recipe.name)}
                                    >
                                      Duplicate
                                    </DropdownItem>
                                    <DropdownItem
                                      key="delete"
                                      color="danger"
                                      className="text-danger"
                                      startContent={<IconTrash className="w-4 h-4" />}
                                      onPress={() => handleDeleteClick(recipe.path)}
                                    >
                                      Delete
                                    </DropdownItem>
                                  </DropdownMenu>
                                </Dropdown>
                              </div>
                            }
                          />
                        );
                      })
                    ) : (
                      <div className="w-full">
                        <EmptyHostState
                          icon={<IconFolder className="w-5 h-5" />}
                          title="No recipes in this folder"
                          description="Create a recipe and assign it to this folder."
                          action={
                            <Button size="sm" color="primary" onPress={openCreateRecipeModalWithContext}>
                              New Recipe
                            </Button>
                          }
                        />
                      </div>
                    )}
                  </HostSection>
                ))}
              </>
            ) : (
              <EmptyHostState
                icon={<span className="text-lg">📜</span>}
                title={searchQuery ? "No recipes match your search" : "No recipes yet"}
                description={searchQuery ? undefined : "Create a recipe to automate training workflows."}
                action={
                  !searchQuery ? (
                    <Button size="sm" color="primary" onPress={openCreateRecipeModalWithContext}>
                      New Recipe
                    </Button>
                  ) : undefined
                }
              />
            )}
          </>
        )}

        {/* Create Recipe Modal */}
        <Modal isOpen={createRecipeModal.isOpen} onClose={createRecipeModal.onClose}>
          <ModalContent>
            <ModalHeader>Create New Recipe</ModalHeader>
            <ModalBody className="space-y-3">
              <Input
                labelPlacement="inside"
                label="Recipe Name"
                placeholder="my-training-recipe"
                value={newRecipeName}
                onValueChange={setNewRecipeName}
                autoFocus
              />

              <Select
                labelPlacement="inside"
                label="Folder"
                placeholder="Recipes"
                selectedKeys={new Set([newRecipeFolderKey])}
                onSelectionChange={(keys) => {
                  const selected = Array.from(keys)[0] as string | undefined;
                  if (selected) setNewRecipeFolderKey(selected);
                }}
              >
                <SelectItem key="__root__">Recipes</SelectItem>
                {activeFolders.map((f) => (
                  <SelectItem key={`folder:${f.id}`}>{f.name}</SelectItem>
                ))}
                {archivedFolders.map((f) => (
                  <SelectItem key={`folder:${f.id}`}>{f.name} (archived)</SelectItem>
                ))}
              </Select>
            </ModalBody>
            <ModalFooter>
              <Button variant="flat" onPress={createRecipeModal.onClose}>
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

        {/* Create Folder Modal */}
        <Modal isOpen={createFolderModal.isOpen} onClose={createFolderModal.onClose}>
          <ModalContent>
            <ModalHeader>Create Folder</ModalHeader>
            <ModalBody className="space-y-3">
              <Input
                labelPlacement="inside"
                label="Folder Name"
                placeholder="my-project"
                value={newFolderName}
                onValueChange={setNewFolderName}
                autoFocus
              />
              {folderError && (
                <p className="text-sm text-danger whitespace-pre-wrap">{folderError}</p>
              )}
            </ModalBody>
            <ModalFooter>
              <Button variant="flat" onPress={createFolderModal.onClose}>
                Cancel
              </Button>
              <Button
                color="primary"
                onPress={handleCreateFolder}
                isDisabled={!newFolderName.trim()}
              >
                Create
              </Button>
            </ModalFooter>
          </ModalContent>
        </Modal>

        {/* Delete Folder Modal */}
        <Modal isOpen={deleteFolderModal.isOpen} onClose={deleteFolderModal.onClose}>
          <ModalContent>
            <ModalHeader>Delete Folder</ModalHeader>
            <ModalBody className="space-y-3">
              <p className="text-sm text-foreground/70">
                {folderToDelete
                  ? `Delete "${folderToDelete.name}"? This will also delete all recipes in this folder.`
                  : "Delete this folder?"}
              </p>
              {folderToDelete && (
                <p className="text-xs text-foreground/50">
                  {recipes.filter((r) => folderAssignments[r.path] === folderToDelete.id).length} recipes will be deleted.
                </p>
              )}
              {folderError && (
                <p className="text-sm text-danger whitespace-pre-wrap">{folderError}</p>
              )}
            </ModalBody>
            <ModalFooter>
              <Button variant="flat" onPress={deleteFolderModal.onClose} isDisabled={deletingFolder}>
                Cancel
              </Button>
              <Button
                color="danger"
                onPress={() => void handleConfirmDeleteFolder()}
                isLoading={deletingFolder}
              >
                Delete
              </Button>
            </ModalFooter>
          </ModalContent>
        </Modal>

        {/* Move Recipe Modal */}
        <Modal isOpen={moveRecipeModal.isOpen} onClose={moveRecipeModal.onClose}>
          <ModalContent>
            <ModalHeader>Move Recipe</ModalHeader>
            <ModalBody className="space-y-3">
              <Select
                labelPlacement="inside"
                label="Target Folder"
                placeholder="Recipes"
                selectedKeys={new Set([moveTargetFolderKey])}
                onSelectionChange={(keys) => {
                  const selected = Array.from(keys)[0] as string | undefined;
                  if (selected) setMoveTargetFolderKey(selected);
                }}
              >
                <SelectItem key="__root__">Recipes</SelectItem>
                {activeFolders.map((f) => (
                  <SelectItem key={`folder:${f.id}`}>{f.name}</SelectItem>
                ))}
                {archivedFolders.map((f) => (
                  <SelectItem key={`folder:${f.id}`}>{f.name} (archived)</SelectItem>
                ))}
              </Select>

              {folderError && (
                <p className="text-sm text-danger whitespace-pre-wrap">{folderError}</p>
              )}
            </ModalBody>
            <ModalFooter>
              <Button variant="flat" onPress={moveRecipeModal.onClose}>
                Cancel
              </Button>
              <Button
                color="primary"
                onPress={() => void handleConfirmMoveRecipe()}
                isDisabled={!moveRecipePath}
              >
                Move
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
      </div>
    </div>
  );
}

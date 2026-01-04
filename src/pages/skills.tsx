import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  interactiveSkillApi,
  skillApi,
  useCreateSkill,
  useDeleteSkill,
  useDuplicateSkill,
  useHosts,
  useInteractiveExecutions,
  useVastInstances,
  useSkills,
  vastAttachSshKey,
} from "../lib/tauri-api";
import { useTerminalOptional } from "../contexts/TerminalContext";
import type {
  Host,
  InteractiveExecution,
  InteractiveStatus,
  Skill,
} from "../lib/types";
import { vastInstanceToHostCandidate } from "../lib/vast-host";
import { EmptyHostState, HostRow, HostSection } from "../components/shared/HostCard";
import type { SkillFolder } from "../lib/skill-folders";
import {
  getAssignedFolderId,
  loadSkillFolderAssignments,
  loadSkillFolders,
  saveSkillFolderAssignments,
  saveSkillFolders,
  setAssignedFolderId,
} from "../lib/skill-folders";
import { cn } from "@/lib/utils";
import {
  Plus,
  Play,
  Pause,
  Upload,
  FlaskConical,
  Folder,
  Archive,
  RotateCcw,
  Terminal,
  Square,
  X,
  Search,
  Filter,
  ArrowUpDown,
  MoreHorizontal,
  Edit,
  Trash2,
  Loader2,
} from "lucide-react";

// Icons have been replaced with lucide-react imports above

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

function getExecutionTagColor(status: InteractiveStatus): "default" | "destructive" | "secondary" {
  switch (status) {
    case "running":
    case "waiting_for_input":
      return "default";
    case "paused":
    case "connecting":
    case "pending":
      return "secondary";
    default:
      return "default";
  }
}

function SkeletonSection({ itemCount }: { itemCount: number }) {
  return (
    <div className="space-y-4">
      <Skeleton className="h-6 w-32" />
      <div className="space-y-2">
        {Array.from({ length: itemCount }).map((_, i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    </div>
  );
}

export function SkillsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const terminalContext = useTerminalOptional();
  const [createSkillModalOpen, setCreateSkillModalOpen] = useState(false);
  const [createFolderModalOpen, setCreateFolderModalOpen] = useState(false);
  const [deleteFolderModalOpen, setDeleteFolderModalOpen] = useState(false);
  const [moveSkillModalOpen, setMoveSkillModalOpen] = useState(false);
  const [isRunErrorOpen, setIsRunErrorOpen] = useState(false);
  const [newSkillName, setNewSkillName] = useState("");
  const [newSkillFolderKey, setNewSkillFolderKey] = useState<string>("__root__");
  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [executionActions, setExecutionActions] = useState<
    Record<string, null | "pause" | "resume" | "interrupt" | "cancel">
  >({});

  const [folders, setFolders] = useState<SkillFolder[]>(() => loadSkillFolders());
  const [folderAssignments, setFolderAssignments] = useState<Record<string, string>>(
    () => loadSkillFolderAssignments()
  );
  const [folderScopeKey, setFolderScopeKey] = useState<string>("all");
  const [newFolderName, setNewFolderName] = useState("");
  const [folderError, setFolderError] = useState<string | null>(null);
  const [folderToDelete, setFolderToDelete] = useState<SkillFolder | null>(null);
  const [deletingFolder, setDeletingFolder] = useState(false);
  const [moveSkillPath, setMoveSkillPath] = useState<string | null>(null);
  const [moveTargetFolderKey, setMoveTargetFolderKey] = useState<string>("__root__");

  const skillsQuery = useSkills();
  const executionsQuery = useInteractiveExecutions();
  const createMutation = useCreateSkill();
  const deleteMutation = useDeleteSkill();
  const duplicateMutation = useDuplicateSkill();

  // Delete confirmation modal
  const [isDeleteOpen, setIsDeleteOpen] = useState(false);
  const [skillToDelete, setSkillToDelete] = useState<string | null>(null);

  // Host selection modal for running skills with targets
  const [isHostSelectOpen, setIsHostSelectOpen] = useState(false);
  const [skillToRun, setSkillToRun] = useState<{ path: string; skill: Skill } | null>(null);
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

  function persistFolders(updater: (prev: SkillFolder[]) => SkillFolder[]) {
    setFolders((prev) => {
      const next = updater(prev);
      saveSkillFolders(next);
      return next;
    });
  }

  function persistAssignments(updater: (prev: Record<string, string>) => Record<string, string>) {
    setFolderAssignments((prev) => {
      const next = updater(prev);
      saveSkillFolderAssignments(next);
      return next;
    });
  }

  const folderScopeFolderId =
    folderScopeKey.startsWith("folder:") ? folderScopeKey.slice("folder:".length) : null;
  const folderScopeFolder = folderScopeFolderId ? foldersById.get(folderScopeFolderId) ?? null : null;
  const folderScopeLabel =
    folderScopeKey === "all"
      ? "All"
      : folderScopeKey === "skills"
        ? "Skills"
        : folderScopeFolder
          ? folderScopeFolder.status === "archived"
            ? `${folderScopeFolder.name} (archived)`
            : folderScopeFolder.name
          : "Folder";

  function openCreateSkillModalWithContext() {
    setNewSkillName("");
    setFolderError(null);
    setNewSkillFolderKey(folderScopeKey.startsWith("folder:") ? folderScopeKey : "__root__");
    setCreateSkillModalOpen(true);
  }

  function openCreateFolderModal() {
    setNewFolderName("");
    setFolderError(null);
    setCreateFolderModalOpen(true);
  }

  const handleCreate = async () => {
    if (!newSkillName.trim()) return;

    try {
      const path = await createMutation.mutateAsync(newSkillName);
      const folderId = newSkillFolderKey.startsWith("folder:")
        ? newSkillFolderKey.slice("folder:".length)
        : null;
      if (folderId) {
        persistAssignments((prev) => setAssignedFolderId(prev, path, folderId));
      }
      setCreateSkillModalOpen(false);
      setNewSkillName("");
      navigate({ to: "/skills/$path", params: { path: encodeURIComponent(path) } });
    } catch (e) {
      console.error("Failed to create skill:", e);
    }
  };

  const handleRunClick = async (path: string) => {
    try {
      // Load the skill to check if it has a target
      const skill = await skillApi.get(path);

      if (skill.target) {
        // Show host selection modal
        setSkillToRun({ path, skill });
        setSelectedHostId(null);
        setIsHostSelectOpen(true);
      } else {
        // No target, run directly with local execution
        await executeSkill(path, "__local__");
      }
    } catch (e) {
      console.error("Failed to run skill:", e);
      const msg =
        typeof e === "object" && e !== null && "message" in e
          ? String((e as { message: unknown }).message)
          : e instanceof Error
            ? e.message
            : String(e);
      setRunError(msg);
      setIsRunErrorOpen(true);
    }
  };

  const executeSkill = async (skillPath: string, hostId: string) => {
    setIsRunning(true);
    try {
      const variables: Record<string, string> = {};
      if (hostId && hostId !== "__local__") {
        variables.target = hostId;
      }

      // For Vast targets, proactively attach the configured SSH key via API.
      if (hostId && hostId !== "__local__") {
        const vastInstanceId = hostId.startsWith("vast:")
          ? Number(hostId.slice("vast:".length))
          : (hosts.find((h) => h.id === hostId)?.vast_instance_id ?? null);
        if (typeof vastInstanceId === "number" && Number.isFinite(vastInstanceId) && vastInstanceId > 0) {
          await vastAttachSshKey(vastInstanceId);
          await new Promise((r) => setTimeout(r, 1200));
        }
      }

      // Prepare interactive execution (pending, manual start)
      const execution = await interactiveSkillApi.prepare({
        path: skillPath,
        hostId,
        variables,
      });

      // Immediately seed the query cache with execution data
      // This allows the sidebar to show skill info instantly
      queryClient.setQueryData(
        ["interactive-executions", execution.id],
        execution
      );

      // Navigate to run page
      navigate({ to: "/skills/runs/$id", params: { id: execution.id } });
    } catch (e) {
      console.error("Failed to run skill:", e);
      const msg =
        typeof e === "object" && e !== null && "message" in e
          ? String((e as { message: unknown }).message)
          : e instanceof Error
            ? e.message
            : String(e);
      setRunError(msg);
      setIsRunErrorOpen(true);
    } finally {
      setIsRunning(false);
    }
  };

  const handleConfirmRun = async () => {
    if (!skillToRun) return;
    if (!selectedHostId && skillToRun.skill.target) return; // Must select a host or local

    setIsHostSelectOpen(false);
    await executeSkill(skillToRun.path, selectedHostId || "__local__");
    setSkillToRun(null);
  };

  const handleExecutionClick = async (execution: InteractiveExecution) => {
    try {
      if (execution.terminal_id) {
        navigate({ to: "/skills/runs/$id", params: { id: execution.id } });
        return;
      }

      const resumed = await interactiveSkillApi.resume(execution.id);
      queryClient.setQueryData(["interactive-executions", resumed.id], resumed);
      queryClient.invalidateQueries({ queryKey: ["interactive-executions"] });
      navigate({ to: "/skills/runs/$id", params: { id: resumed.id } });
    } catch (e) {
      console.error("Failed to open execution:", e);
      const msg =
        typeof e === "object" && e !== null && "message" in e
          ? String((e as { message: unknown }).message)
          : e instanceof Error
            ? e.message
            : String(e);
      setRunError(msg);
      setIsRunErrorOpen(true);
    }
  };

  const setExecutionAction = (
    executionId: string,
    action: null | "pause" | "resume" | "interrupt" | "cancel"
  ) => {
    setExecutionActions((prev) => ({ ...prev, [executionId]: action }));
  };

  const handleInterruptExecution = async (execution: InteractiveExecution) => {
    try {
      setExecutionAction(execution.id, "interrupt");
      await interactiveSkillApi.interrupt(execution.id);
      queryClient.invalidateQueries({ queryKey: ["interactive-executions"] });
    } catch (e) {
      console.error("Failed to interrupt execution:", e);
      const msg =
        typeof e === "object" && e !== null && "message" in e
          ? String((e as { message: unknown }).message)
          : e instanceof Error
            ? e.message
            : String(e);
      setRunError(msg);
      setIsRunErrorOpen(true);
    } finally {
      setExecutionAction(execution.id, null);
    }
  };

  const handlePauseExecution = async (execution: InteractiveExecution) => {
    try {
      setExecutionAction(execution.id, "pause");
      await interactiveSkillApi.pause(execution.id);
      queryClient.invalidateQueries({ queryKey: ["interactive-executions"] });
    } catch (e) {
      console.error("Failed to pause execution:", e);
      const msg =
        typeof e === "object" && e !== null && "message" in e
          ? String((e as { message: unknown }).message)
          : e instanceof Error
            ? e.message
            : String(e);
      setRunError(msg);
      setIsRunErrorOpen(true);
    } finally {
      setExecutionAction(execution.id, null);
    }
  };

  const handleResumeExecution = async (execution: InteractiveExecution) => {
    try {
      setExecutionAction(execution.id, "resume");
      await interactiveSkillApi.resume(execution.id);
      queryClient.invalidateQueries({ queryKey: ["interactive-executions"] });
    } catch (e) {
      console.error("Failed to resume execution:", e);
      const msg =
        typeof e === "object" && e !== null && "message" in e
          ? String((e as { message: unknown }).message)
          : e instanceof Error
            ? e.message
            : String(e);
      setRunError(msg);
      setIsRunErrorOpen(true);
    } finally {
      setExecutionAction(execution.id, null);
    }
  };

  const handleCancelExecution = async (execution: InteractiveExecution) => {
    try {
      setExecutionAction(execution.id, "cancel");
      await interactiveSkillApi.cancel(execution.id);
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
      setIsRunErrorOpen(true);
    } finally {
      setExecutionAction(execution.id, null);
    }
  };

  // Filter hosts based on target requirements
  const allHosts: Host[] = [
    ...hosts,
    ...(vastQuery.data ?? []).map(vastInstanceToHostCandidate),
  ];

  const compatibleHosts = allHosts.filter((host: Host) => {
    if (!skillToRun?.skill.target) return true;
    const target = skillToRun.skill.target;

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
  const showLocalOption = skillToRun?.skill.target?.type === "any" || skillToRun?.skill.target?.type === "local";

  const handleEdit = (path: string) => {
    navigate({ to: "/skills/$path", params: { path: encodeURIComponent(path) } });
  };

  const handleDuplicate = async (path: string, name: string) => {
    try {
      const newPath = await duplicateMutation.mutateAsync({ path, newName: `${name} Copy` });
      persistAssignments((prev) => {
        const folderId = getAssignedFolderId(prev, path);
        return folderId ? setAssignedFolderId(prev, newPath, folderId) : prev;
      });
    } catch (e) {
      console.error("Failed to duplicate skill:", e);
    }
  };

  const handleDeleteClick = (path: string) => {
    setSkillToDelete(path);
    setIsDeleteOpen(true);
  };

  const handleDeleteConfirm = async () => {
    if (!skillToDelete) return;
    try {
      await deleteMutation.mutateAsync(skillToDelete);
      persistAssignments((prev) => setAssignedFolderId(prev, skillToDelete, null));
      setSelectedSkillPath((prev) => (prev === skillToDelete ? null : prev));
      setIsDeleteOpen(false);
      setSkillToDelete(null);
    } catch (e) {
      console.error("Failed to delete skill:", e);
    }
  };

  const handleImport = async () => {
    // TODO: Open file picker and import
    console.log("Import skill");
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

    const newFolder: SkillFolder = {
      id: safeUuid(),
      name,
      status: "active",
      created_at: new Date().toISOString(),
    };

    persistFolders((prev) => [...prev, newFolder].sort((a, b) => a.name.localeCompare(b.name)));
    setCreateFolderModalOpen(false);
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

  const handleRequestDeleteFolder = (folder: SkillFolder) => {
    setFolderError(null);
    setFolderToDelete(folder);
    setDeleteFolderModalOpen(true);
  };

  const handleConfirmDeleteFolder = async () => {
    if (!folderToDelete) return;
    if (!skillsQuery.data) return;

    setFolderError(null);
    setDeletingFolder(true);
    try {
      const targetFolderId = folderToDelete.id;
      const pathsToDelete = skills
        .filter((r) => folderAssignments[r.path] === targetFolderId)
        .map((r) => r.path);

      await Promise.all(pathsToDelete.map((p) => skillApi.delete(p)));
      await queryClient.invalidateQueries({ queryKey: ["skills"] });

      persistAssignments((prev) => {
        const next = { ...prev };
        for (const p of pathsToDelete) delete next[p];
        return next;
      });

      persistFolders((prev) => prev.filter((f) => f.id !== targetFolderId));

      setSelectedSkillPath((prev) => (pathsToDelete.includes(prev ?? "") ? null : prev));
      setFolderScopeKey((prev) => (prev === `folder:${targetFolderId}` ? "all" : prev));
      setDeleteFolderModalOpen(false);
      setFolderToDelete(null);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setFolderError(msg);
    } finally {
      setDeletingFolder(false);
    }
  };

  const handleOpenMoveSkill = (skillPath: string) => {
    setFolderError(null);
    setMoveSkillPath(skillPath);
    setMoveTargetFolderKey(folderKeyFromId(getAssignedFolderId(folderAssignments, skillPath)));
    setMoveSkillModalOpen(true);
  };

  const handleConfirmMoveSkill = async () => {
    if (!moveSkillPath) return;
    const folderId = folderIdFromKey(moveTargetFolderKey);
    persistAssignments((prev) => setAssignedFolderId(prev, moveSkillPath, folderId));
    setMoveSkillModalOpen(false);
  };

  const skills = skillsQuery.data ?? [];
  const executions = executionsQuery.data ?? [];
  const activeStatuses: InteractiveStatus[] = [
    "running",
    "paused",
    "waiting_for_input",
    "connecting",
  ];
  const activeExecutions = executions.filter((e) => activeStatuses.includes(e.status));

  const [searchQuery, setSearchQuery] = useState("");
  const [selectedSkillPath, setSelectedSkillPath] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState<"all" | "running" | "idle">("all");
  const [sortBy, setSortBy] = useState<"name" | "steps">("name");

  const activeBySkillPath = useMemo(() => {
    const map = new Map<string, number>();
    for (const exec of activeExecutions) {
      map.set(exec.skill_path, (map.get(exec.skill_path) || 0) + 1);
    }
    return map;
  }, [activeExecutions]);

  const filteredSkills = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    let list = skills;
    if (q) {
      list = list.filter((r) => {
        const haystack = `${r.name} ${r.description ?? ""} ${r.path}`.toLowerCase();
        return haystack.includes(q);
      });
    }
    if (filterStatus === "running") {
      list = list.filter((r) => (activeBySkillPath.get(r.path) || 0) > 0);
    }
    if (filterStatus === "idle") {
      list = list.filter((r) => (activeBySkillPath.get(r.path) || 0) === 0);
    }
    const sorted = [...list];
    sorted.sort((a, b) => {
      if (sortBy === "steps") return b.step_count - a.step_count;
      return a.name.localeCompare(b.name);
    });
    return sorted;
  }, [activeBySkillPath, filterStatus, skills, searchQuery, sortBy]);

  useEffect(() => {
    if (!skillsQuery.data) return;
    const skillPaths = new Set(skills.map((r) => r.path));
    const folderIds = new Set(folders.map((f) => f.id));
    setFolderAssignments((prev) => {
      let changed = false;
      const next: Record<string, string> = {};
      for (const [skillPath, folderId] of Object.entries(prev)) {
        if (!skillPaths.has(skillPath)) {
          changed = true;
          continue;
        }
        if (!folderIds.has(folderId)) {
          changed = true;
          continue;
        }
        next[skillPath] = folderId;
      }
      if (!changed) return prev;
      saveSkillFolderAssignments(next);
      return next;
    });
  }, [folders, skills, skillsQuery.data]);

  const skillSections = useMemo(() => {
    const rootSkills: typeof filteredSkills = [];
    const byFolder = new Map<string, typeof filteredSkills>();

    if (folderScopeKey.startsWith("folder:")) {
      const folderId = folderScopeKey.slice("folder:".length);
      const folder = foldersById.get(folderId) ?? null;
      const list = filteredSkills.filter((r) => folderAssignments[r.path] === folderId);
      return {
        rootSkills: [],
        folderSections: folder ? [{ folder, skills: list }] : [],
      };
    }

    for (const skill of filteredSkills) {
      const assignedFolderId = folderAssignments[skill.path] ?? null;
      if (!assignedFolderId) {
        if (folderScopeKey !== "skills") {
          rootSkills.push(skill);
        } else {
          rootSkills.push(skill);
        }
        continue;
      }

      if (folderScopeKey === "skills") {
        continue;
      }

      const folder = foldersById.get(assignedFolderId) ?? null;
      if (!folder) {
        rootSkills.push(skill);
        continue;
      }

      if (folder.status === "archived") {
        continue;
      }

      const arr = byFolder.get(folder.id) ?? [];
      arr.push(skill);
      byFolder.set(folder.id, arr);
    }

    const folderSections = activeFolders
      .map((folder) => ({ folder, skills: byFolder.get(folder.id) ?? [] }))
      .filter((s) => s.skills.length > 0);

    return { rootSkills, folderSections };
  }, [activeFolders, filteredSkills, folderAssignments, folderScopeKey, foldersById]);

  const visibleSkillPathSet = useMemo(() => {
    const s = new Set<string>();
    for (const r of skillSections.rootSkills) s.add(r.path);
    for (const section of skillSections.folderSections) {
      for (const r of section.skills) s.add(r.path);
    }
    return s;
  }, [skillSections]);

  useEffect(() => {
    if (!selectedSkillPath) return;
    const exists = visibleSkillPathSet.has(selectedSkillPath);
    if (!exists) setSelectedSkillPath(null);
  }, [selectedSkillPath, visibleSkillPathSet]);

  const canRunSelected = Boolean(selectedSkillPath);

  const hostNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const h of allHosts) map.set(h.id, h.name);
    map.set("__local__", "Local");
    return map;
  }, [allHosts]);

  const isLoading = skillsQuery.isLoading || executionsQuery.isLoading;

  return (
    <div className="doppio-page">
      <div className="doppio-page-content">
        {/* Termius-style Toolbar */}
        <div className="termius-toolbar">
          {/* Row 1: Search + Run */}
          <div className="termius-toolbar-row">
            <div className="termius-search-bar">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
                <Input
                  placeholder="Search skills..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-10 pr-24 h-12 text-base bg-muted/50"
                />
                <Button
                  size="sm"
                  className="absolute right-2 top-1/2 -translate-y-1/2 h-8 px-4"
                  onClick={() => {
                    if (!selectedSkillPath) return;
                    void handleRunClick(selectedSkillPath);
                  }}
                  disabled={!canRunSelected}
                >
                  Run
                </Button>
              </div>
            </div>
          </div>

          {/* Row 2: Quick Actions + Filters */}
          <div className="termius-toolbar-row justify-between">
            <div className="termius-quick-actions">
              <Button variant="outline" size="sm" className="gap-1.5" type="button" onClick={openCreateSkillModalWithContext}>
                <Plus className="w-4 h-4" />
                <span>New Skill</span>
              </Button>
              <Button variant="outline" size="sm" className="gap-1.5" type="button" onClick={openCreateFolderModal}>
                <Folder className="w-4 h-4" />
                <span>New Folder</span>
              </Button>
              <Button variant="outline" size="sm" className="gap-1.5" type="button" onClick={() => void handleImport()}>
                <Upload className="w-4 h-4" />
                <span>Import</span>
              </Button>
              <Button
                variant="outline" size="sm" className="gap-1.5"
                type="button"
                onClick={() => navigate({ to: "/terminal", search: { connectHostId: undefined, connectVastInstanceId: undefined, connectLabel: undefined } })}
              >
                <Terminal className="w-4 h-4" />
                <span>Terminal</span>
              </Button>
            </div>

            <div className="flex items-center gap-1">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" className={cn("gap-1.5", folderScopeKey !== "all" && "bg-primary text-primary-foreground")} type="button">
                    <Folder className="w-4 h-4" />
                    <span>{folderScopeLabel}</span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                  <DropdownMenuItem onClick={() => setFolderScopeKey("all")}>All</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setFolderScopeKey("skills")}>Skills</DropdownMenuItem>
                  {activeFolders.map((f) => (
                    <DropdownMenuItem key={f.id} onClick={() => setFolderScopeKey(`folder:${f.id}`)}>
                      {f.name}
                    </DropdownMenuItem>
                  ))}
                  {archivedFolders.map((f) => (
                    <DropdownMenuItem key={f.id} onClick={() => setFolderScopeKey(`folder:${f.id}`)}>
                      {f.name} (archived)
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" className={cn("gap-1.5", filterStatus !== "all" && "bg-primary text-primary-foreground")} type="button">
                    <Filter className="w-4 h-4" />
                    <span>{filterStatus === "all" ? "Filter" : filterStatus}</span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                  <DropdownMenuItem onClick={() => setFilterStatus("all")}>All</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setFilterStatus("running")}>Running</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setFilterStatus("idle")}>Idle</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" className="gap-1.5" type="button">
                    <ArrowUpDown className="w-4 h-4" />
                    <span>{sortBy === "name" ? "Name" : "Steps"}</span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                  <DropdownMenuItem onClick={() => setSortBy("name")}>Name</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setSortBy("steps")}>Steps</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        </div>

        {/* Content */}
        {isLoading ? (
          <>
            <SkeletonSection itemCount={2} />
            <SkeletonSection itemCount={3} />
          </>
        ) : (
          <>
            {activeExecutions.length > 0 && (
              <HostSection title="RUNNING" count={activeExecutions.length}>
                {activeExecutions.map((exec) => {
                  const hostName = hostNameById.get(exec.host_id) || exec.host_id;
                  const rightTags: { label: string; color?: "default" | "destructive" | "secondary" }[] = [
                    { label: getStatusLabel(exec.status), color: getExecutionTagColor(exec.status) },
                    { label: getExecutionProgressLabel(exec), color: "default" },
                  ];
                  const action = executionActions[exec.id] ?? null;
                  const isBusy = action !== null;
                  const canPause = exec.status === "running" || exec.status === "connecting" || exec.status === "pending";
                  const canResume = exec.status === "paused";
                  const canInterrupt = !!exec.terminal_id && (exec.status === "running" || exec.status === "waiting_for_input" || exec.status === "paused");

                  return (
                    <HostRow
                      key={exec.id}
                      icon={<FlaskConical className="w-4 h-4 text-primary" />}
                      title={exec.skill_name}
                      subtitle={`${hostName} · ${new Date(exec.created_at).toLocaleString()}`}
                      titleClampLines={2}
                      rightTags={rightTags}
                      isOnline={true}
                      onClick={() => void handleExecutionClick(exec)}
                      hoverActions={
                        <div
                          className="flex items-center gap-1"
                          onMouseDown={(e) => e.stopPropagation()}
                          onClick={(e) => e.stopPropagation()}
                        >
                          {canInterrupt ? (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  type="button"
                                  size="icon"
                                  variant="ghost"
                                  className="w-7 h-7 opacity-60 hover:opacity-100 text-warning"
                                  disabled={isBusy}
                                  onClick={() => void handleInterruptExecution(exec)}
                                >
                                  {action === "interrupt" ? (
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                  ) : (
                                    <Square className="w-4 h-4" />
                                  )}
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>Ctrl+C</TooltipContent>
                            </Tooltip>
                          ) : null}

                          {canPause ? (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  type="button"
                                  size="icon"
                                  variant="ghost"
                                  className="w-7 h-7 opacity-60 hover:opacity-100 text-warning"
                                  disabled={isBusy}
                                  onClick={() => void handlePauseExecution(exec)}
                                >
                                  {action === "pause" ? (
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                  ) : (
                                    <Pause className="w-4 h-4" />
                                  )}
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>Pause</TooltipContent>
                            </Tooltip>
                          ) : null}

                          {canResume ? (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  type="button"
                                  size="icon"
                                  variant="ghost"
                                  className="w-7 h-7 opacity-60 hover:opacity-100 text-success"
                                  disabled={isBusy}
                                  onClick={() => void handleResumeExecution(exec)}
                                >
                                  {action === "resume" ? (
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                  ) : (
                                    <Play className="w-4 h-4" />
                                  )}
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>Resume</TooltipContent>
                            </Tooltip>
                          ) : null}

                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                type="button"
                                size="icon"
                                variant="ghost"
                                className="w-7 h-7 opacity-60 hover:opacity-100 text-destructive"
                                disabled={isBusy}
                                onClick={() => void handleCancelExecution(exec)}
                              >
                                {action === "cancel" ? (
                                  <Loader2 className="w-4 h-4 animate-spin" />
                                ) : (
                                  <X className="w-4 h-4" />
                                )}
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>Cancel</TooltipContent>
                          </Tooltip>
                        </div>
                      }
                    />
                  );
                })}
              </HostSection>
            )}

            {(skillSections.rootSkills.length > 0 || skillSections.folderSections.length > 0) ? (
              <>
                {skillSections.rootSkills.length > 0 && (
                  <HostSection title="SKILLS" count={skillSections.rootSkills.length}>
                    {skillSections.rootSkills.map((skill) => {
                      const activeCount = activeBySkillPath.get(skill.path) || 0;
                      const rightTags: { label: string; color?: "default" | "destructive" | "secondary" }[] = [];
                      if (activeCount > 0) {
                        rightTags.push({ label: `${activeCount} running`, color: "secondary" });
                      }

                      return (
                        <HostRow
                          key={skill.path}
                          icon={<FlaskConical className="w-4 h-4 text-primary" />}
                          title={skill.name}
                          subtitle={skill.description || undefined}
                          rightTags={rightTags}
                          isOnline={activeCount > 0}
                          isSelected={selectedSkillPath === skill.path}
                          onClick={() => setSelectedSkillPath(skill.path)}
                          onDoubleClick={() => handleEdit(skill.path)}
                          hoverActions={
                            <div
                              className="flex items-center gap-1"
                              onMouseDown={(e) => e.stopPropagation()}
                              onClick={(e) => e.stopPropagation()}
                            >
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Button
                                    size="icon"
                                    variant="ghost"
                                    className="w-7 h-7 opacity-60 hover:opacity-100"
                                    onClick={() => void handleRunClick(skill.path)}
                                  >
                                    <Play className="w-4 h-4" />
                                  </Button>
                                </TooltipTrigger>
                                <TooltipContent>Run</TooltipContent>
                              </Tooltip>

                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Button
                                    size="icon"
                                    variant="ghost"
                                    className="w-7 h-7 opacity-60 hover:opacity-100"
                                    onClick={() => handleEdit(skill.path)}
                                  >
                                    <Edit className="w-4 h-4" />
                                  </Button>
                                </TooltipTrigger>
                                <TooltipContent>Edit</TooltipContent>
                              </Tooltip>

                              <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                  <Button
                                    size="icon"
                                    variant="ghost"
                                    className="w-7 h-7 opacity-60 hover:opacity-100"
                                  >
                                    <MoreHorizontal className="w-4 h-4" />
                                  </Button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end">
                                  <DropdownMenuItem onClick={() => handleOpenMoveSkill(skill.path)}>
                                    Move to folder…
                                  </DropdownMenuItem>
                                  <DropdownMenuItem onClick={() => void handleDuplicate(skill.path, skill.name)}>
                                    Duplicate
                                  </DropdownMenuItem>
                                  <DropdownMenuItem
                                    className="text-destructive"
                                    onClick={() => handleDeleteClick(skill.path)}
                                  >
                                    <Trash2 className="w-4 h-4 mr-2" />
                                    Delete
                                  </DropdownMenuItem>
                                </DropdownMenuContent>
                              </DropdownMenu>
                            </div>
                          }
                        />
                      );
                    })}
                  </HostSection>
                )}

                {skillSections.folderSections.map(({ folder, skills }) => (
                  <HostSection
                    key={folder.id}
                    title={folder.name}
                    count={skills.length}
                    actions={
                      <div className="flex items-center gap-1">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              size="icon"
                              variant="ghost"
                              className="w-7 h-7 opacity-60 hover:opacity-100"
                              onClick={() => handleToggleArchiveFolder(folder.id)}
                            >
                              {folder.status === "archived" ? <RotateCcw className="w-4 h-4" /> : <Archive className="w-4 h-4" />}
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>{folder.status === "archived" ? "Restore" : "Archive"}</TooltipContent>
                        </Tooltip>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              size="icon"
                              variant="ghost"
                              className="w-7 h-7 opacity-60 hover:opacity-100 text-destructive"
                              onClick={() => handleRequestDeleteFolder(folder)}
                            >
                              <Trash2 className="w-4 h-4" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Delete folder</TooltipContent>
                        </Tooltip>
                      </div>
                    }
                  >
                    {skills.length > 0 ? (
                      skills.map((skill) => {
                        const activeCount = activeBySkillPath.get(skill.path) || 0;
                        const rightTags: { label: string; color?: "default" | "destructive" | "secondary" }[] = [];
                        if (activeCount > 0) {
                          rightTags.push({ label: `${activeCount} running`, color: "secondary" });
                        }

                        return (
                          <HostRow
                            key={skill.path}
                            icon={<span className="text-lg">📜</span>}
                            title={skill.name}
                            subtitle={skill.description || undefined}
                            titleClampLines={1}
                            rightTags={rightTags}
                            isOnline={activeCount > 0}
                            isSelected={selectedSkillPath === skill.path}
                            onClick={() => setSelectedSkillPath(skill.path)}
                            onDoubleClick={() => handleEdit(skill.path)}
                            hoverActions={
                              <div
                                className="flex items-center gap-1"
                                onMouseDown={(e) => e.stopPropagation()}
                                onClick={(e) => e.stopPropagation()}
                              >
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <Button
                                      size="icon"
                                      variant="ghost"
                                      className="w-7 h-7 opacity-60 hover:opacity-100"
                                      onClick={() => void handleRunClick(skill.path)}
                                    >
                                      <Play className="w-4 h-4" />
                                    </Button>
                                  </TooltipTrigger>
                                  <TooltipContent>Run</TooltipContent>
                                </Tooltip>

                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <Button
                                      size="icon"
                                      variant="ghost"
                                      className="w-7 h-7 opacity-60 hover:opacity-100"
                                      onClick={() => handleEdit(skill.path)}
                                    >
                                      <Edit className="w-4 h-4" />
                                    </Button>
                                  </TooltipTrigger>
                                  <TooltipContent>Edit</TooltipContent>
                                </Tooltip>

                                <DropdownMenu>
                                  <DropdownMenuTrigger asChild>
                                    <Button
                                      size="icon"
                                      variant="ghost"
                                      className="w-7 h-7 opacity-60 hover:opacity-100"
                                    >
                                      <MoreHorizontal className="w-4 h-4" />
                                    </Button>
                                  </DropdownMenuTrigger>
                                  <DropdownMenuContent align="end">
                                    <DropdownMenuItem onClick={() => handleOpenMoveSkill(skill.path)}>
                                      Move to folder…
                                    </DropdownMenuItem>
                                    <DropdownMenuItem onClick={() => void handleDuplicate(skill.path, skill.name)}>
                                      Duplicate
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                      className="text-destructive"
                                      onClick={() => handleDeleteClick(skill.path)}
                                    >
                                      <Trash2 className="w-4 h-4 mr-2" />
                                      Delete
                                    </DropdownMenuItem>
                                  </DropdownMenuContent>
                                </DropdownMenu>
                              </div>
                            }
                          />
                        );
                      })
                    ) : (
                      <div className="w-full">
                        <EmptyHostState
                          icon={<Folder className="w-5 h-5" />}
                          title="No skills in this folder"
                          description="Create a skill and assign it to this folder."
                          action={
                            <Button size="sm" onClick={openCreateSkillModalWithContext}>
                              New Skill
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
                title={searchQuery ? "No skills match your search" : "No skills yet"}
                description={searchQuery ? undefined : "Create a skill to automate training workflows."}
                action={
                  !searchQuery ? (
                    <Button size="sm" onClick={openCreateSkillModalWithContext}>
                      New Skill
                    </Button>
                  ) : undefined
                }
              />
            )}
          </>
        )}

        {/* Create Skill Dialog */}
        <Dialog open={createSkillModalOpen} onOpenChange={setCreateSkillModalOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Create New Skill</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="skill-name">Skill Name</Label>
                <Input
                  id="skill-name"
                  placeholder="my-training-skill"
                  value={newSkillName}
                  onChange={(e) => setNewSkillName(e.target.value)}
                  autoFocus
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="folder-select">Folder</Label>
                <Select value={newSkillFolderKey} onValueChange={setNewSkillFolderKey}>
                  <SelectTrigger id="folder-select">
                    <SelectValue placeholder="Skills" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__root__">Skills</SelectItem>
                    {activeFolders.map((f) => (
                      <SelectItem key={f.id} value={`folder:${f.id}`}>
                        {f.name}
                      </SelectItem>
                    ))}
                    {archivedFolders.map((f) => (
                      <SelectItem key={f.id} value={`folder:${f.id}`}>
                        {f.name} (archived)
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setCreateSkillModalOpen(false)}>
                Cancel
              </Button>
              <Button
                onClick={handleCreate}
                disabled={!newSkillName.trim() || createMutation.isPending}
              >
                {createMutation.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
                Create
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* Create Folder Dialog */}
        <Dialog open={createFolderModalOpen} onOpenChange={setCreateFolderModalOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Create Folder</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="folder-name">Folder Name</Label>
                <Input
                  id="folder-name"
                  placeholder="my-project"
                  value={newFolderName}
                  onChange={(e) => setNewFolderName(e.target.value)}
                  autoFocus
                />
              </div>
              {folderError && (
                <p className="text-sm text-destructive whitespace-pre-wrap">{folderError}</p>
              )}
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setCreateFolderModalOpen(false)}>
                Cancel
              </Button>
              <Button
                onClick={handleCreateFolder}
                disabled={!newFolderName.trim()}
              >
                Create
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* Delete Folder Dialog */}
        <Dialog open={deleteFolderModalOpen} onOpenChange={setDeleteFolderModalOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Delete Folder</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <p className="text-sm text-muted-foreground">
                {folderToDelete
                  ? `Delete "${folderToDelete.name}"? This will also delete all skills in this folder.`
                  : "Delete this folder?"}
              </p>
              {folderToDelete && (
                <p className="text-xs text-muted-foreground">
                  {skills.filter((r) => folderAssignments[r.path] === folderToDelete.id).length} skills will be deleted.
                </p>
              )}
              {folderError && (
                <p className="text-sm text-destructive whitespace-pre-wrap">{folderError}</p>
              )}
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDeleteFolderModalOpen(false)} disabled={deletingFolder}>
                Cancel
              </Button>
              <Button
                variant="destructive"
                onClick={() => void handleConfirmDeleteFolder()}
                disabled={deletingFolder}
              >
                {deletingFolder && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
                Delete
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* Move Skill Dialog */}
        <Dialog open={moveSkillModalOpen} onOpenChange={setMoveSkillModalOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Move Skill</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="target-folder">Target Folder</Label>
                <Select value={moveTargetFolderKey} onValueChange={setMoveTargetFolderKey}>
                  <SelectTrigger id="target-folder">
                    <SelectValue placeholder="Skills" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__root__">Skills</SelectItem>
                    {activeFolders.map((f) => (
                      <SelectItem key={f.id} value={`folder:${f.id}`}>
                        {f.name}
                      </SelectItem>
                    ))}
                    {archivedFolders.map((f) => (
                      <SelectItem key={f.id} value={`folder:${f.id}`}>
                        {f.name} (archived)
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {folderError && (
                <p className="text-sm text-destructive whitespace-pre-wrap">{folderError}</p>
              )}
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setMoveSkillModalOpen(false)}>
                Cancel
              </Button>
              <Button
                onClick={() => void handleConfirmMoveSkill()}
                disabled={!moveSkillPath}
              >
                Move
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={isDeleteOpen} onOpenChange={setIsDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Skill</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <p>Are you sure you want to delete this skill? This action cannot be undone.</p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsDeleteOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteConfirm}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Host Selection Dialog for Running Skills */}
      <Dialog open={isHostSelectOpen} onOpenChange={setIsHostSelectOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Select Target Host</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            {skillToRun?.skill.target && (
              <div className="mb-4 p-3 bg-primary/10 border border-primary/20 rounded-lg">
                <p className="text-sm text-muted-foreground mb-2">Skill requires:</p>
                <div className="flex flex-wrap gap-2">
                  <Badge variant="secondary">{skillToRun.skill.target.type}</Badge>
                  {skillToRun.skill.target.gpu_type && (
                    <Badge variant="secondary">GPU: {skillToRun.skill.target.gpu_type}</Badge>
                  )}
                  {skillToRun.skill.target.min_gpus && (
                    <Badge variant="secondary">Min GPUs: {skillToRun.skill.target.min_gpus}</Badge>
                  )}
                </div>
              </div>
            )}

            <p className="text-sm text-muted-foreground mb-2">Select a compatible host:</p>

            {compatibleHosts.length === 0 && !showLocalOption ? (
              <div className="text-center py-8 text-muted-foreground">
                <p>No compatible hosts found.</p>
                <p className="text-sm mt-1">Add a {skillToRun?.skill.target?.type} host first.</p>
              </div>
            ) : (
              <div className="space-y-2">
                {/* Local option */}
                {showLocalOption && (
                  <div
                    className={cn(
                      "p-3 rounded-lg border cursor-pointer transition-colors",
                      selectedHostId === "__local__"
                        ? "border-primary bg-primary/10"
                        : "border-border hover:border-muted-foreground"
                    )}
                    onClick={() => setSelectedHostId("__local__")}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium">Local</span>
                      <Badge variant="secondary">ready</Badge>
                    </div>
                    <p className="text-sm text-muted-foreground mt-1">
                      Run on this machine (no SSH)
                    </p>
                  </div>
                )}
                {/* Remote hosts */}
                {compatibleHosts.map((host: Host) => (
                  <div
                    key={host.id}
                    className={cn(
                      "p-3 rounded-lg border cursor-pointer transition-colors",
                      selectedHostId === host.id
                        ? "border-primary bg-primary/10"
                        : "border-border hover:border-muted-foreground"
                    )}
                    onClick={() => setSelectedHostId(host.id)}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium">{host.name}</span>
                      <Badge variant="secondary">{host.type}</Badge>
                    </div>
                    {host.gpu_name && (
                      <p className="text-sm text-muted-foreground mt-1">
                        {host.num_gpus}x {host.gpu_name}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsHostSelectOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleConfirmRun}
              disabled={!selectedHostId || isRunning}
            >
              {isRunning && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              {selectedHostId === "__local__" ? "Run Locally" : "Run Skill"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={isRunErrorOpen} onOpenChange={setIsRunErrorOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Failed to run skill</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <p className="text-sm text-destructive whitespace-pre-wrap">{runError ?? "Unknown error"}</p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsRunErrorOpen(false)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      </div>
    </div>
  );
}

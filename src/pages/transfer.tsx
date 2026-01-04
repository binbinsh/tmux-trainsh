import {
  Badge,
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Progress,
  ScrollArea,
} from "@/components/ui";
import { AppIcon } from "../components/AppIcon";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Check,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Copy,
  Eye,
  EyeOff,
  Folder,
  FolderPlus,
  HardDrive,
  Loader2,
  Monitor,
  Move,
  Pause,
  RefreshCw,
  Search,
  Server,
  Trash2,
  X,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { cn } from "@/lib/utils";
import {
  DndContext,
  DragOverlay,
  useDraggable,
  useDroppable,
  type DragEndEvent,
  type DragStartEvent,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  createHostDir,
  createLocalDir,
  deleteHostFile,
  deleteLocalFile,
  deleteVastFile,
  listHostFiles,
  listLocalFiles,
  listVastFiles,
  listenAllTransferProgress,
  storageApi,
  transferApi,
  useHosts,
  useStorageFiles,
  useStorages,
  useTransfers,
  useVastInstances,
} from "../lib/tauri-api";
import type { FileEntry, Host, Storage, TransferOperation, TransferProgress, TransferTask, UnifiedEndpoint, VastInstance } from "../lib/types";
import { motion, AnimatePresence } from "framer-motion";

// ============================================================
// Types
// ============================================================

type Endpoint =
  | { type: "storage"; storageId: string }
  | { type: "host"; hostId: string }
  | { type: "vast"; instanceId: number }
  | { type: "local" };

// ============================================================
// Icons
// ============================================================

function IconFolder() {
  return (
    <svg className="w-4 h-4 text-warning flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
    </svg>
  );
}

function IconFile() {
  return (
    <svg className="w-4 h-4 text-muted-foreground flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
    </svg>
  );
}

function getStorageIconNode(storage: Storage, sizeClass = "w-4 h-4") {
  switch (storage.backend.type) {
    case "google_drive":
      return <AppIcon name="googledrive" className={sizeClass} alt="Google Drive" />;
    case "cloudflare_r2":
      return <AppIcon name="cloudflare" className={sizeClass} alt="Cloudflare R2" />;
    case "ssh_remote":
      return <AppIcon name="ssh" className={sizeClass} alt="SSH" />;
    case "smb":
      return <AppIcon name="smb" className={sizeClass} alt="SMB" />;
    case "local":
      return <Monitor className={sizeClass} />;
    default:
      return <HardDrive className={sizeClass} />;
  }
}

function getHostStatusColor(status: Host["status"]): string {
  switch (status) {
    case "online":
      return "bg-green-500";
    case "offline":
      return "bg-gray-400";
    case "connecting":
      return "bg-yellow-500";
    case "error":
      return "bg-red-500";
    default:
      return "bg-gray-400";
  }
}

function getVastStatusColor(status: string | null): string {
  if (!status) return "bg-gray-400";
  const s = status.toLowerCase();
  if (s === "running") return "bg-green-500";
  if (s === "exited" || s === "stopped" || s === "inactive") return "bg-orange-500";
  if (s === "loading" || s === "initializing") return "bg-yellow-500";
  if (s === "error") return "bg-red-500";
  return "bg-gray-400";
}

function isVastInstanceRunning(inst: VastInstance): boolean {
  const status = inst.actual_status?.toLowerCase() ?? "";
  return status === "running";
}

// ============================================================
// Helpers
// ============================================================

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function formatSpeed(bps: number): string {
  if (bps === 0) return "-";
  const k = 1024;
  const sizes = ["B/s", "KB/s", "MB/s", "GB/s"];
  const i = Math.floor(Math.log(bps) / Math.log(k));
  return `${parseFloat((bps / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function formatEta(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0) return "-";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${mins}m`;
}

function getEndpointKey(endpoint: Endpoint): string {
  switch (endpoint.type) {
    case "storage":
      return `storage:${endpoint.storageId}`;
    case "host":
      return `host:${endpoint.hostId}`;
    case "vast":
      return `vast:${endpoint.instanceId}`;
    case "local":
      return "local";
  }
}

function getEndpointLabel(endpoint: Endpoint, storages: Storage[], hosts: Host[], vastInstances: VastInstance[]): string {
  switch (endpoint.type) {
    case "storage":
      return storages.find((s) => s.id === endpoint.storageId)?.name ?? "Unknown Storage";
    case "host":
      return hosts.find((h) => h.id === endpoint.hostId)?.name ?? "Unknown Host";
    case "vast": {
      const inst = vastInstances.find((i) => i.id === endpoint.instanceId);
      return inst?.label || `Vast #${endpoint.instanceId}`;
    }
    case "local":
      return "Local";
  }
}

function getEndpointIcon(endpoint: Endpoint, storages: Storage[], _hosts: Host[], _vastInstances: VastInstance[]) {
  switch (endpoint.type) {
    case "storage": {
      const storage = storages.find((s) => s.id === endpoint.storageId);
      return storage ? getStorageIconNode(storage, "w-4 h-4") : <HardDrive className="w-4 h-4" />;
    }
    case "host":
      return <Server className="w-4 h-4" />;
    case "vast":
      return <AppIcon name="vast" className="w-4 h-4" alt="Vast" />;
    case "local":
      return <Monitor className="w-4 h-4" />;
  }
}

// ============================================================
// Hooks for file listing
// ============================================================

function useEndpointFiles(endpoint: Endpoint | null, path: string, vastInstances: VastInstance[]) {
  const isVastRunning = useMemo(() => {
    if (endpoint?.type !== "vast") return true;
    const inst = vastInstances.find((i) => i.id === endpoint.instanceId);
    return inst ? isVastInstanceRunning(inst) : false;
  }, [endpoint, vastInstances]);

  const storageFilesQuery = useStorageFiles(
    endpoint?.type === "storage" ? endpoint.storageId : "",
    path
  );

  const hostFilesQuery = useQuery({
    queryKey: ["host-files", endpoint?.type === "host" ? endpoint.hostId : "", path],
    queryFn: () => listHostFiles((endpoint as { type: "host"; hostId: string }).hostId, path),
    enabled: endpoint?.type === "host",
    staleTime: 10_000,
  });

  const vastFilesQuery = useQuery({
    queryKey: ["vast-files", endpoint?.type === "vast" ? endpoint.instanceId : 0, path],
    queryFn: () => listVastFiles((endpoint as { type: "vast"; instanceId: number }).instanceId, path),
    enabled: endpoint?.type === "vast" && isVastRunning,
    staleTime: 10_000,
    retry: 1,
  });

  const localFilesQuery = useQuery({
    queryKey: ["local-files", path],
    queryFn: () => listLocalFiles(path || "/"),
    enabled: endpoint?.type === "local",
    staleTime: 10_000,
  });

  if (!endpoint) {
    return {
      data: [] as FileEntry[],
      isLoading: false,
      isFetching: false,
      error: null,
      refetch: () => {},
      isVastStopped: false,
    };
  }

  if (endpoint.type === "vast" && !isVastRunning) {
    return {
      data: [] as FileEntry[],
      isLoading: false,
      isFetching: false,
      error: null,
      refetch: () => {},
      isVastStopped: true,
    };
  }

  const baseQuery = (() => {
    switch (endpoint.type) {
      case "storage":
        return storageFilesQuery;
      case "host":
        return hostFilesQuery;
      case "vast":
        return vastFilesQuery;
      case "local":
        return localFilesQuery;
    }
  })();

  return { ...baseQuery, isVastStopped: false };
}

/** Convert frontend Endpoint to backend UnifiedEndpoint */
function toTransferEndpoint(endpoint: Endpoint): UnifiedEndpoint {
  switch (endpoint.type) {
    case "storage":
      return { type: "storage", storage_id: endpoint.storageId };
    case "host":
      return { type: "host", host_id: endpoint.hostId };
    case "vast":
      return { type: "vast", instance_id: endpoint.instanceId };
    case "local":
      return { type: "local" };
  }
}

// ============================================================
// Unified Endpoint Picker Component
// ============================================================

type EndpointPickerProps = {
  storages: Storage[];
  hosts: Host[];
  vastInstances: VastInstance[];
  value: Endpoint | null;
  onChange: (endpoint: Endpoint) => void;
};

function EndpointPicker({ storages, hosts, vastInstances, value, onChange }: EndpointPickerProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const onlineHosts = useMemo(() => hosts.filter((h) => h.status === "online"), [hosts]);
  const sortedVastInstances = useMemo(() => {
    return [...vastInstances].sort((a, b) => {
      const aRunning = isVastInstanceRunning(a);
      const bRunning = isVastInstanceRunning(b);
      if (aRunning && !bRunning) return -1;
      if (!aRunning && bRunning) return 1;
      return b.id - a.id;
    });
  }, [vastInstances]);

  // Filter items by search
  const filteredStorages = useMemo(() => {
    if (!search) return storages;
    const q = search.toLowerCase();
    return storages.filter((s) => s.name.toLowerCase().includes(q));
  }, [storages, search]);

  const filteredHosts = useMemo(() => {
    if (!search) return onlineHosts;
    const q = search.toLowerCase();
    return onlineHosts.filter((h) => h.name.toLowerCase().includes(q));
  }, [onlineHosts, search]);

  const filteredVast = useMemo(() => {
    if (!search) return sortedVastInstances;
    const q = search.toLowerCase();
    return sortedVastInstances.filter((v) =>
      (v.label?.toLowerCase().includes(q)) ||
      String(v.id).includes(q) ||
      v.gpu_name?.toLowerCase().includes(q)
    );
  }, [sortedVastInstances, search]);

  const showLocal = !search || "local".includes(search.toLowerCase());

  useEffect(() => {
    if (open && inputRef.current) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  function handleSelect(endpoint: Endpoint) {
    onChange(endpoint);
    setOpen(false);
    setSearch("");
  }

  const displayLabel = value ? getEndpointLabel(value, storages, hosts, vastInstances) : "Select endpoint";
  const displayIcon = value ? getEndpointIcon(value, storages, hosts, vastInstances) : <Folder className="w-4 h-4" />;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className="h-8 justify-between w-full text-left font-normal"
        >
          <span className="flex items-center gap-2 truncate">
            {displayIcon}
            <span className="truncate">{displayLabel}</span>
          </span>
          <ChevronDown className="ml-2 h-3 w-3 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0" align="start">
        <div className="p-2 border-b">
          <div className="flex items-center gap-2 px-2 py-1 rounded-md bg-muted/50">
            <Search className="h-3.5 w-3.5 text-muted-foreground" />
            <input
              ref={inputRef}
              type="text"
              placeholder="Search endpoints..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
            {search && (
              <button type="button" onClick={() => setSearch("")} className="text-muted-foreground hover:text-foreground">
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        </div>
        <ScrollArea className="h-64">
          <div className="p-1">
            {/* Local */}
            {showLocal && (
              <div className="mb-1">
                <div className="px-2 py-1 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                  Local
                </div>
                <button
                  type="button"
                  onClick={() => handleSelect({ type: "local" })}
                  className={cn(
                    "w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-sm hover:bg-muted/50 transition-colors",
                    value?.type === "local" && "bg-primary/10"
                  )}
                >
                  <Monitor className="h-4 w-4" />
                  <span>Local Machine</span>
                </button>
              </div>
            )}

            {/* Storages */}
            {filteredStorages.length > 0 && (
              <div className="mb-1">
                <div className="px-2 py-1 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                  Storage ({filteredStorages.length})
                </div>
                {filteredStorages.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => handleSelect({ type: "storage", storageId: s.id })}
                    className={cn(
                      "w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-sm hover:bg-muted/50 transition-colors",
                      value?.type === "storage" && value.storageId === s.id && "bg-primary/10"
                    )}
                  >
                    {getStorageIconNode(s, "h-4 w-4")}
                    <span className="truncate flex-1 text-left">{s.name}</span>
                  </button>
                ))}
              </div>
            )}

            {/* Hosts */}
            {filteredHosts.length > 0 && (
              <div className="mb-1">
                <div className="px-2 py-1 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                  SSH Hosts ({filteredHosts.length})
                </div>
                {filteredHosts.map((h) => (
                  <button
                    key={h.id}
                    type="button"
                    onClick={() => handleSelect({ type: "host", hostId: h.id })}
                    className={cn(
                      "w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-sm hover:bg-muted/50 transition-colors",
                      value?.type === "host" && value.hostId === h.id && "bg-primary/10"
                    )}
                  >
                    <span className={cn("w-2 h-2 rounded-full flex-shrink-0", getHostStatusColor(h.status))} />
                    <Server className="h-4 w-4 flex-shrink-0" />
                    <span className="truncate flex-1 text-left">{h.name}</span>
                    {h.gpu_name && (
                      <span className="text-[10px] text-muted-foreground flex-shrink-0">
                        {h.num_gpus}x {h.gpu_name}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}

            {/* Vast.ai */}
            {filteredVast.length > 0 && (
              <div className="mb-1">
                <div className="px-2 py-1 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                  Vast.ai ({filteredVast.length})
                </div>
                {filteredVast.map((inst) => {
                  const running = isVastInstanceRunning(inst);
                  const displayName = inst.label || `#${inst.id}`;
                  return (
                    <button
                      key={inst.id}
                      type="button"
                      onClick={() => handleSelect({ type: "vast", instanceId: inst.id })}
                      className={cn(
                        "w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-sm hover:bg-muted/50 transition-colors",
                        value?.type === "vast" && value.instanceId === inst.id && "bg-primary/10",
                        !running && "opacity-60"
                      )}
                    >
                      <span className={cn("w-2 h-2 rounded-full flex-shrink-0", getVastStatusColor(inst.actual_status))} />
                      <AppIcon name="vast" className="h-4 w-4 flex-shrink-0" alt="Vast" />
                      <span className="truncate flex-1 text-left">{displayName}</span>
                      {inst.gpu_name && (
                        <span className="text-[10px] text-muted-foreground flex-shrink-0">
                          {inst.num_gpus}x {inst.gpu_name}
                        </span>
                      )}
                      {!running && (
                        <Badge variant="outline" className="text-[9px] px-1 py-0 h-4 flex-shrink-0">
                          {inst.actual_status || "stopped"}
                        </Badge>
                      )}
                    </button>
                  );
                })}
              </div>
            )}

            {/* Empty state */}
            {!showLocal && filteredStorages.length === 0 && filteredHosts.length === 0 && filteredVast.length === 0 && (
              <div className="p-4 text-center text-sm text-muted-foreground">
                No endpoints found
              </div>
            )}
          </div>
        </ScrollArea>
      </PopoverContent>
    </Popover>
  );
}

// ============================================================
// File Row Component (Whole row draggable with dnd-kit)
// ============================================================

type FileRowProps = {
  entry: FileEntry;
  side: "left" | "right";
  isSelected: boolean;
  selectedCount: number;
  onSelect: (e: React.MouseEvent) => void;
  onNavigate: () => void;
};

function FileRow({ entry, side, isSelected, selectedCount, onSelect, onNavigate }: FileRowProps) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `${side}:${entry.path}`,
    data: {
      entry,
      side,
      isSelected,
      selectedCount,
    },
  });

  return (
    <div
      ref={setNodeRef}
      onClick={onSelect}
      onDoubleClick={entry.is_dir ? onNavigate : undefined}
      className={cn(
        "flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer select-none transition-colors",
        "hover:bg-muted/50",
        isSelected && "bg-primary/10 ring-1 ring-primary/30",
        isDragging && "opacity-50"
      )}
      {...listeners}
      {...attributes}
    >
      <Checkbox
        checked={isSelected}
        onCheckedChange={() => {}}
        onClick={(e) => {
          // Let the click bubble up to the row's onClick handler
          // Don't stop propagation - the row handler will handle selection
        }}
        className="flex-shrink-0"
      />
      {entry.is_dir ? <IconFolder /> : <IconFile />}
      <span className={cn("flex-1 text-sm truncate", entry.is_dir && "font-medium")}>
        {entry.name}
      </span>
      <span className="text-xs text-muted-foreground flex-shrink-0">
        {entry.is_dir ? "-" : formatBytes(entry.size)}
      </span>
    </div>
  );
}

// ============================================================
// File Pane Component
// ============================================================

type FilePaneProps = {
  side: "left" | "right";
  storages: Storage[];
  hosts: Host[];
  vastInstances: VastInstance[];
  endpoint: Endpoint | null;
  onEndpointChange: (endpoint: Endpoint) => void;
  currentPath: string;
  onPathChange: (path: string) => void;
  selectedFiles: Set<string>;
  onSelectionChange: (files: Set<string>) => void;
  isDropTarget: boolean;
};

function FilePane({
  side,
  storages,
  hosts,
  vastInstances,
  endpoint,
  onEndpointChange,
  currentPath,
  onPathChange,
  selectedFiles,
  onSelectionChange,
  isDropTarget,
}: FilePaneProps) {
  // Setup droppable
  const { setNodeRef, isOver } = useDroppable({
    id: `drop-${side}`,
    data: { side, currentPath },
  });

  const filesQuery = useEndpointFiles(endpoint, currentPath, vastInstances);
  const queryClient = useQueryClient();
  const [newFolderOpen, setNewFolderOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [showHiddenFiles, setShowHiddenFiles] = useState(false);
  const [lastSelectedIndex, setLastSelectedIndex] = useState<number | null>(null);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  // Editable path bar state
  const [isEditingPath, setIsEditingPath] = useState(false);
  const [editPathValue, setEditPathValue] = useState("");
  const pathInputRef = useRef<HTMLInputElement>(null);

  // Filter hidden files
  const allFiles = (filesQuery.data ?? []) as FileEntry[];
  const files = useMemo(() => {
    if (showHiddenFiles) return allFiles;
    return allFiles.filter((f) => !f.name.startsWith("."));
  }, [allFiles, showHiddenFiles]);

  // Selection helpers
  const allSelected = files.length > 0 && files.every((f) => selectedFiles.has(f.path));

  // Handle selection with Shift+Click range selection
  const handleSelect = useCallback((index: number, e: React.MouseEvent) => {
    const entry = files[index];
    if (!entry) return;

    if (e.shiftKey && lastSelectedIndex !== null) {
      // Range selection
      const start = Math.min(lastSelectedIndex, index);
      const end = Math.max(lastSelectedIndex, index);
      const next = new Set(selectedFiles);
      for (let i = start; i <= end; i++) {
        next.add(files[i].path);
      }
      onSelectionChange(next);
    } else if (e.metaKey || e.ctrlKey) {
      // Toggle selection
      const next = new Set(selectedFiles);
      if (next.has(entry.path)) {
        next.delete(entry.path);
      } else {
        next.add(entry.path);
      }
      onSelectionChange(next);
      setLastSelectedIndex(index);
    } else {
      // Single selection - toggle if already selected alone
      if (selectedFiles.size === 1 && selectedFiles.has(entry.path)) {
        onSelectionChange(new Set());
        setLastSelectedIndex(null);
      } else {
        onSelectionChange(new Set([entry.path]));
        setLastSelectedIndex(index);
      }
    }
  }, [files, lastSelectedIndex, selectedFiles, onSelectionChange]);

  function toggleSelectAll() {
    if (allSelected) {
      onSelectionChange(new Set());
    } else {
      onSelectionChange(new Set(files.map((f) => f.path)));
    }
  }

  // Keyboard shortcuts
  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLDivElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "a") {
      e.preventDefault();
      onSelectionChange(new Set(files.map((f) => f.path)));
    }
  }, [files, onSelectionChange]);

  // Navigation
  function navigateToPath(path: string) {
    onPathChange(path);
    onSelectionChange(new Set());
    setLastSelectedIndex(null);
  }

  function navigateUp() {
    if (currentPath === "/" || currentPath === "" || currentPath === "~") return;

    if (currentPath.startsWith("~/")) {
      const parts = currentPath.slice(2).split("/").filter(Boolean);
      parts.pop();
      navigateToPath(parts.length === 0 ? "~" : "~/" + parts.join("/"));
      return;
    }

    const parts = currentPath.split("/").filter(Boolean);
    parts.pop();
    navigateToPath(parts.length === 0 ? "/" : "/" + parts.join("/"));
  }

  // Editable path bar
  function startEditingPath() {
    setEditPathValue(currentPath);
    setIsEditingPath(true);
    setTimeout(() => pathInputRef.current?.select(), 50);
  }

  function handlePathSubmit() {
    if (editPathValue.trim()) {
      navigateToPath(editPathValue.trim());
    }
    setIsEditingPath(false);
  }

  function handlePathKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      handlePathSubmit();
    } else if (e.key === "Escape") {
      setIsEditingPath(false);
    }
  }

  // Create folder
  const createFolderMutation = useMutation({
    mutationFn: async () => {
      if (!endpoint) return;
      const folderPath = currentPath === "/" ? `/${newFolderName}` : `${currentPath}/${newFolderName}`;

      if (endpoint.type === "storage") {
        await storageApi.mkdir(endpoint.storageId, folderPath);
      } else if (endpoint.type === "host") {
        await createHostDir(endpoint.hostId, folderPath);
      } else if (endpoint.type === "local") {
        await createLocalDir(folderPath);
      }
    },
    onSuccess: () => {
      if (endpoint?.type === "storage") {
        queryClient.invalidateQueries({ queryKey: ["storages", endpoint.storageId, "files"] });
      } else if (endpoint?.type === "host") {
        queryClient.invalidateQueries({ queryKey: ["host-files", endpoint.hostId] });
      } else if (endpoint?.type === "local") {
        queryClient.invalidateQueries({ queryKey: ["local-files"] });
      }
      setNewFolderOpen(false);
      setNewFolderName("");
    },
  });

  // Delete files
  const deleteMutation = useMutation({
    mutationFn: async () => {
      if (!endpoint) return;
      const pathsToDelete = Array.from(selectedFiles);

      for (const path of pathsToDelete) {
        if (endpoint.type === "storage") {
          await storageApi.deleteFile(endpoint.storageId, path);
        } else if (endpoint.type === "host") {
          await deleteHostFile(endpoint.hostId, path);
        } else if (endpoint.type === "local") {
          await deleteLocalFile(path);
        } else if (endpoint.type === "vast") {
          await deleteVastFile(endpoint.instanceId, path);
        }
      }
    },
    onSuccess: () => {
      if (endpoint?.type === "storage") {
        queryClient.invalidateQueries({ queryKey: ["storages", endpoint.storageId, "files"] });
      } else if (endpoint?.type === "host") {
        queryClient.invalidateQueries({ queryKey: ["host-files", endpoint.hostId] });
      } else if (endpoint?.type === "local") {
        queryClient.invalidateQueries({ queryKey: ["local-files"] });
      } else if (endpoint?.type === "vast") {
        queryClient.invalidateQueries({ queryKey: ["vast-files", endpoint.instanceId] });
      }
      setDeleteConfirmOpen(false);
      onSelectionChange(new Set());
    },
  });

  // Breadcrumbs
  const breadcrumbs = useMemo(() => {
    if (currentPath === "~") {
      return [{ name: "~", path: "~" }];
    }
    if (currentPath.startsWith("~/")) {
      const parts = currentPath.slice(2).split("/").filter(Boolean);
      const items: { name: string; path: string }[] = [{ name: "~", path: "~" }];
      let acc = "~";
      for (const part of parts) {
        acc += "/" + part;
        items.push({ name: part, path: acc });
      }
      return items;
    }

    const parts = currentPath.split("/").filter(Boolean);
    const items: { name: string; path: string }[] = [{ name: "/", path: "/" }];
    let acc = "";
    for (const part of parts) {
      acc += "/" + part;
      items.push({ name: part, path: acc });
    }
    return items;
  }, [currentPath]);

  const showDropOverlay = isDropTarget && isOver;

  return (
    <div
      ref={setNodeRef}
      tabIndex={0}
      onKeyDown={handleKeyDown}
      className={cn(
        "flex flex-col h-full border rounded-lg bg-background transition-colors outline-none relative",
        showDropOverlay && "ring-2 ring-primary/50"
      )}
    >
      {/* Drop overlay - shows when dragging over */}
      {showDropOverlay && (
        <div
          className="absolute inset-0 z-50 bg-primary/10 flex items-center justify-center pointer-events-none rounded-lg"
        >
          <div className="bg-background/90 px-4 py-2 rounded-lg shadow-lg border">
            <span className="text-sm font-medium">Drop files here</span>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex-shrink-0 p-2 border-b border-border space-y-2">
        {/* Unified endpoint picker */}
        <EndpointPicker
          storages={storages}
          hosts={hosts}
          vastInstances={vastInstances}
          value={endpoint}
          onChange={(ep) => {
            onEndpointChange(ep);
            onPathChange("/");
            onSelectionChange(new Set());
          }}
        />

        {/* Breadcrumbs and actions */}
        <div className="flex items-center gap-1">
          <Button
            size="icon"
            variant="ghost"
            className="h-6 w-6 flex-shrink-0"
            onClick={() => setNewFolderOpen(true)}
            disabled={!endpoint}
            title="New folder"
          >
            <FolderPlus className="h-3 w-3" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="h-6 w-6 flex-shrink-0"
            onClick={navigateUp}
            disabled={currentPath === "/" || currentPath === ""}
            title="Go up"
          >
            <ArrowUp className="h-3 w-3" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="h-6 w-6 flex-shrink-0"
            onClick={() => filesQuery.refetch()}
            disabled={filesQuery.isFetching}
            title="Refresh"
          >
            <RefreshCw className={cn("h-3 w-3", filesQuery.isFetching && "animate-spin")} />
          </Button>
          <Button
            size="icon"
            variant={showHiddenFiles ? "secondary" : "ghost"}
            className="h-6 w-6 flex-shrink-0"
            onClick={() => setShowHiddenFiles(!showHiddenFiles)}
            title={showHiddenFiles ? "Hide hidden files" : "Show hidden files"}
          >
            {showHiddenFiles ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="h-6 w-6 flex-shrink-0 text-destructive hover:text-destructive hover:bg-destructive/10"
            onClick={() => setDeleteConfirmOpen(true)}
            disabled={selectedFiles.size === 0 || deleteMutation.isPending}
            title="Delete selected"
          >
            {deleteMutation.isPending ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Trash2 className="h-3 w-3" />
            )}
          </Button>

          {/* Editable path bar */}
          <div className="flex-1 min-w-0">
            {isEditingPath ? (
              <Input
                ref={pathInputRef}
                value={editPathValue}
                onChange={(e) => setEditPathValue(e.target.value)}
                onBlur={handlePathSubmit}
                onKeyDown={handlePathKeyDown}
                className="h-6 text-xs font-mono"
                autoFocus
              />
            ) : (
              <div
                onClick={startEditingPath}
                className="flex items-center gap-0.5 text-xs whitespace-nowrap overflow-x-auto cursor-text hover:bg-muted/30 rounded px-1 py-0.5"
              >
                {breadcrumbs.map((b, idx) => (
                  <div key={b.path} className="flex items-center">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        navigateToPath(b.path);
                      }}
                      disabled={b.path === currentPath}
                      className={cn(
                        "px-1 py-0 rounded text-xs transition-colors",
                        b.path === currentPath
                          ? "text-foreground font-medium"
                          : "text-muted-foreground hover:text-foreground hover:bg-muted"
                      )}
                    >
                      {b.name}
                    </button>
                    {idx < breadcrumbs.length - 1 && (
                      <ChevronRight className="h-3 w-3 text-muted-foreground/40" />
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* File List */}
      <ScrollArea className="flex-1 min-h-0">
        <div className="p-1">
          {!endpoint ? (
            <div className="p-4 text-center text-xs text-muted-foreground">
              Select an endpoint to browse files
            </div>
          ) : filesQuery.isVastStopped ? (
            <div className="p-4 text-center text-xs text-muted-foreground">
              <div className="mb-2">Instance is stopped</div>
              <div className="text-[10px] text-muted-foreground/70">
                Start the instance to browse files
              </div>
            </div>
          ) : filesQuery.isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
            </div>
          ) : filesQuery.error ? (
            <div className="p-2 text-xs text-destructive">
              Error: {String(filesQuery.error)}
            </div>
          ) : files.length === 0 ? (
            <div className="p-4 text-center text-xs text-muted-foreground">
              Empty folder
            </div>
          ) : (
            <div className="space-y-0.5">
              {/* Select all header */}
              <div className="flex items-center gap-2 px-2 py-1 border-b border-border/50 mb-1">
                <Checkbox
                  checked={allSelected ? true : selectedFiles.size > 0 ? "indeterminate" : false}
                  onCheckedChange={() => toggleSelectAll()}
                />
                <span className="text-xs text-muted-foreground">
                  {selectedFiles.size > 0 ? `${selectedFiles.size} selected` : `${files.length} items`}
                </span>
              </div>
              {files.map((entry, index) => (
                <FileRow
                  key={entry.path}
                  entry={entry}
                  side={side}
                  isSelected={selectedFiles.has(entry.path)}
                  selectedCount={selectedFiles.size}
                  onSelect={(e) => handleSelect(index, e)}
                  onNavigate={() => navigateToPath(entry.path)}
                />
              ))}
            </div>
          )}
        </div>
      </ScrollArea>

      {/* New folder dialog */}
      <Dialog open={newFolderOpen} onOpenChange={setNewFolderOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>New Folder</DialogTitle>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor={`new-folder-${side}`}>Folder Name</Label>
            <Input
              id={`new-folder-${side}`}
              placeholder="my-folder"
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setNewFolderOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => createFolderMutation.mutate()}
              disabled={!newFolderName.trim() || createFolderMutation.isPending}
            >
              {createFolderMutation.isPending && <Loader2 className="h-4 w-4 animate-spin mr-1" />}
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation dialog */}
      <Dialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Delete {selectedFiles.size} {selectedFiles.size === 1 ? "item" : "items"}?</DialogTitle>
          </DialogHeader>
          <div className="text-sm text-muted-foreground">
            This action cannot be undone. The following will be permanently deleted:
            <ul className="mt-2 max-h-32 overflow-y-auto space-y-1">
              {Array.from(selectedFiles).slice(0, 5).map((path) => (
                <li key={path} className="font-mono text-xs truncate">
                  {path.split("/").pop()}
                </li>
              ))}
              {selectedFiles.size > 5 && (
                <li className="text-xs text-muted-foreground/70">
                  ...and {selectedFiles.size - 5} more
                </li>
              )}
            </ul>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteConfirmOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteMutation.mutate()}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending && <Loader2 className="h-4 w-4 animate-spin mr-1" />}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ============================================================
// Transfer Queue Component (Compact List View)
// ============================================================

function TransferQueue() {
  const transfersQuery = useTransfers();
  const queryClient = useQueryClient();
  const [progressMap, setProgressMap] = useState<Record<string, TransferProgress>>({});
  const [isExpanded, setIsExpanded] = useState(false);

  useEffect(() => {
    let unlisten: (() => void) | null = null;

    listenAllTransferProgress((data) => {
      setProgressMap((prev) => ({
        ...prev,
        [data.task_id]: data.progress,
      }));
    }).then((fn) => {
      unlisten = fn;
    });

    return () => {
      if (unlisten) unlisten();
    };
  }, []);

  const cancelMutation = useMutation({
    mutationFn: transferApi.cancel,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
    },
  });

  const clearCompletedMutation = useMutation({
    mutationFn: transferApi.clearCompleted,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
    },
  });

  const tasks = transfersQuery.data ?? [];
  const runningTasks = tasks.filter((t) => t.status === "running");
  const queuedTasks = tasks.filter((t) => t.status === "queued");
  const completedTasks = tasks.filter((t) => t.status !== "queued" && t.status !== "running");

  function getStatusIcon(status: TransferTask["status"]) {
    switch (status) {
      case "queued":
        return <Pause className="h-3 w-3 text-muted-foreground" />;
      case "running":
        return <Loader2 className="h-3 w-3 animate-spin text-primary" />;
      case "completed":
        return <Check className="h-3 w-3 text-green-500" />;
      case "failed":
        return <X className="h-3 w-3 text-destructive" />;
      case "cancelled":
        return <X className="h-3 w-3 text-muted-foreground" />;
      default:
        return null;
    }
  }

  const summaryText = tasks.length === 0
    ? "No transfers"
    : `${runningTasks.length} running, ${queuedTasks.length} queued`;

  return (
    <div className="flex flex-col border rounded-lg bg-background overflow-hidden">
      {/* Header bar */}
      <button
        type="button"
        className="flex items-center justify-between px-3 py-2 hover:bg-muted/50 transition-colors cursor-pointer w-full text-left"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-3">
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronUp className="h-4 w-4 text-muted-foreground" />
          )}
          <span className="text-sm font-medium">Transfers</span>
          <span className="text-xs text-muted-foreground">{summaryText}</span>
          {runningTasks.length > 0 && (
            <Loader2 className="h-3 w-3 animate-spin text-primary" />
          )}
        </div>
        <div className="flex items-center gap-2">
          {completedTasks.length > 0 && (
            <Button
              size="sm"
              variant="ghost"
              className="h-6 text-xs"
              onClick={(e) => {
                e.stopPropagation();
                clearCompletedMutation.mutate();
              }}
              disabled={clearCompletedMutation.isPending}
            >
              <Check className="h-3 w-3 mr-1" />
              Clear
            </Button>
          )}
        </div>
      </button>

      {/* Expanded list view */}
      {isExpanded && (
        <div className="border-t border-border">
          <ScrollArea className="max-h-48">
            <div className="divide-y divide-border">
              {tasks.length === 0 ? (
                <div className="p-4 text-center text-xs text-muted-foreground">
                  No transfers in queue
                </div>
              ) : (
                tasks.map((task) => {
                  const progress = progressMap[task.id] ?? task.progress;
                  const percent = progress.bytes_total > 0
                    ? Math.round((progress.bytes_done / progress.bytes_total) * 100)
                    : 0;
                  const fileName = task.source_path.split("/").pop() || task.source_path;

                  return (
                    <div key={task.id} className="flex items-center gap-3 px-3 py-2">
                      {/* Status icon */}
                      <div className="flex-shrink-0 w-4">
                        {getStatusIcon(task.status)}
                      </div>

                      {/* File name and destination */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 text-sm">
                          <span className="font-medium truncate">{fileName}</span>
                          <ArrowRight className="h-3 w-3 text-muted-foreground flex-shrink-0" />
                          <span className="text-muted-foreground truncate text-xs">
                            {task.dest_path}
                          </span>
                        </div>
                        {task.status === "running" && (
                          <>
                            {progress.status_message && (
                              <div className="text-[10px] text-muted-foreground mt-0.5">
                                {progress.status_message}
                              </div>
                            )}
                            <div className="mt-1">
                              <Progress value={percent} className="h-1.5" />
                            </div>
                          </>
                        )}
                        {task.error && (
                          <div className="text-[10px] text-destructive truncate mt-0.5">
                            {task.error}
                          </div>
                        )}
                      </div>

                      {/* Progress info */}
                      {task.status === "running" && (
                        <div className="flex items-center gap-3 text-[10px] text-muted-foreground flex-shrink-0">
                          <span className="font-medium w-8">{percent}%</span>
                          <span className="w-14">{formatSpeed(progress.speed_bps)}</span>
                          <span className="w-10">{formatEta(progress.eta_seconds)}</span>
                        </div>
                      )}

                      {/* Cancel button */}
                      {(task.status === "queued" || task.status === "running") && (
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-6 w-6 flex-shrink-0"
                          onClick={() => cancelMutation.mutate(task.id)}
                          title="Cancel"
                        >
                          <X className="h-3 w-3" />
                        </Button>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </ScrollArea>
        </div>
      )}
    </div>
  );
}

// ============================================================
// Inline Transfer Action Bar
// ============================================================

type TransferActionBarProps = {
  files: FileEntry[];
  sourceEndpoint: Endpoint;
  destEndpoint: Endpoint;
  destPath: string;
  storages: Storage[];
  hosts: Host[];
  vastInstances: VastInstance[];
  onConfirm: (operation: TransferOperation) => void;
  onCancel: () => void;
  isPending: boolean;
};

function TransferActionBar({
  files,
  sourceEndpoint,
  destEndpoint,
  destPath,
  storages,
  hosts,
  vastInstances,
  onConfirm,
  onCancel,
  isPending,
}: TransferActionBarProps) {
  const sourceLabel = getEndpointLabel(sourceEndpoint, storages, hosts, vastInstances);
  const destLabel = getEndpointLabel(destEndpoint, storages, hosts, vastInstances);

  // Keyboard shortcuts
  useEffect(() => {
    function handleKeyDown(e: globalThis.KeyboardEvent) {
      if (e.key === "Enter" && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        onConfirm("copy");
      } else if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onConfirm, onCancel]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 20 }}
      className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50"
    >
      <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-card border border-border shadow-lg">
        <div className="text-sm">
          <span className="text-muted-foreground">Transfer </span>
          <span className="font-medium">{files.length} {files.length === 1 ? "file" : "files"}</span>
          <span className="text-muted-foreground"> from </span>
          <span className="font-medium">{sourceLabel}</span>
          <span className="text-muted-foreground"> to </span>
          <span className="font-medium">{destLabel}</span>
          <span className="text-muted-foreground font-mono text-xs ml-1">{destPath}</span>
        </div>

        <div className="flex items-center gap-2">
          <Button
            size="sm"
            onClick={() => onConfirm("copy")}
            disabled={isPending}
            className="gap-1"
          >
            {isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Copy className="h-3 w-3" />}
            Copy
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => onConfirm("move")}
            disabled={isPending}
            className="gap-1"
          >
            <Move className="h-3 w-3" />
            Move
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={onCancel}
            disabled={isPending}
          >
            <X className="h-3 w-3" />
          </Button>
        </div>
      </div>
    </motion.div>
  );
}

// ============================================================
// Main Transfer Page
// ============================================================

export function TransferPage() {
  const storagesQuery = useStorages();
  const hostsQuery = useHosts();
  const vastQuery = useVastInstances();
  const queryClient = useQueryClient();

  const storages = storagesQuery.data ?? [];
  const hosts = hostsQuery.data ?? [];
  const vastInstances = vastQuery.data ?? [];

  // Left pane state
  const [leftEndpoint, setLeftEndpoint] = useState<Endpoint | null>(null);
  const [leftPath, setLeftPath] = useState("/");
  const [leftSelected, setLeftSelected] = useState<Set<string>>(new Set());

  // Right pane state
  const [rightEndpoint, setRightEndpoint] = useState<Endpoint | null>(null);
  const [rightPath, setRightPath] = useState("/");
  const [rightSelected, setRightSelected] = useState<Set<string>>(new Set());

  // Drag state
  const [dragSource, setDragSource] = useState<{ files: FileEntry[]; side: "left" | "right" } | null>(null);

  // Pending transfer (for inline action bar)
  const [pendingTransfer, setPendingTransfer] = useState<{
    files: FileEntry[];
    sourceEndpoint: Endpoint;
    destEndpoint: Endpoint;
    destPath: string;
  } | null>(null);

  // Initialize endpoints
  useEffect(() => {
    if (!leftEndpoint) {
      setLeftEndpoint({ type: "local" });
    }
    if (!rightEndpoint) {
      if (storages.length > 0) {
        setRightEndpoint({ type: "storage", storageId: storages[0].id });
      } else {
        const onlineHost = hosts.find((h) => h.status === "online");
        if (onlineHost) {
          setRightEndpoint({ type: "host", hostId: onlineHost.id });
        }
      }
    }
  }, [storages, hosts, leftEndpoint, rightEndpoint]);

  // Get files for drag source
  const leftFilesQuery = useEndpointFiles(leftEndpoint, leftPath, vastInstances);
  const rightFilesQuery = useEndpointFiles(rightEndpoint, rightPath, vastInstances);

  // Track completed transfers to auto-refresh file lists
  const transfersQuery = useTransfers();
  const prevTransfersRef = useRef<Map<string, string>>(new Map());

  useEffect(() => {
    const currentTasks = transfersQuery.data ?? [];
    const prevStatuses = prevTransfersRef.current;
    let shouldRefresh = false;

    for (const task of currentTasks) {
      const prevStatus = prevStatuses.get(task.id);
      // If task was running/queued and is now completed, refresh files
      if (prevStatus && (prevStatus === "running" || prevStatus === "queued") &&
          (task.status === "completed" || task.status === "failed")) {
        shouldRefresh = true;
      }
    }

    // Update prev statuses
    const newStatuses = new Map<string, string>();
    for (const task of currentTasks) {
      newStatuses.set(task.id, task.status);
    }
    prevTransfersRef.current = newStatuses;

    // Refresh all file queries if any transfer completed
    if (shouldRefresh) {
      queryClient.invalidateQueries({ queryKey: ["local-files"] });
      queryClient.invalidateQueries({ queryKey: ["host-files"] });
      queryClient.invalidateQueries({ queryKey: ["vast-files"] });
      queryClient.invalidateQueries({ queryKey: ["storages"] });
    }
  }, [transfersQuery.data, queryClient]);

  // Create transfer mutation
  const createTransferMutation = useMutation({
    mutationFn: async (params: {
      sourceEndpoint: Endpoint;
      destEndpoint: Endpoint;
      sourcePaths: string[];
      destPath: string;
      operation: TransferOperation;
    }) => {
      return transferApi.createUnified({
        source: toTransferEndpoint(params.sourceEndpoint),
        source_paths: params.sourcePaths,
        dest: toTransferEndpoint(params.destEndpoint),
        dest_path: params.destPath,
        operation: params.operation,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
      setPendingTransfer(null);
      setLeftSelected(new Set());
      setRightSelected(new Set());
    },
  });

  // DnD-kit sensors with activation distance
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8, // Require 8px movement before starting drag
      },
    })
  );

  // Active drag item for overlay
  const [activeDragData, setActiveDragData] = useState<{
    entry: FileEntry;
    side: "left" | "right";
    selectedCount: number;
  } | null>(null);

  // DnD handlers
  function handleDragStart(event: DragStartEvent) {
    const { active } = event;
    const data = active.data.current as {
      entry: FileEntry;
      side: "left" | "right";
      isSelected: boolean;
      selectedCount: number;
    };

    console.log("[Transfer] Drag started:", { entry: data.entry.name, side: data.side });

    // Get selected files for this side
    const selectedSet = data.side === "left" ? leftSelected : rightSelected;
    const files = data.side === "left" ? leftFilesQuery.data as FileEntry[] ?? [] : rightFilesQuery.data as FileEntry[] ?? [];

    let filesToDrag: FileEntry[];
    if (selectedSet.has(data.entry.path)) {
      filesToDrag = files.filter((f) => selectedSet.has(f.path));
    } else {
      filesToDrag = [data.entry];
    }

    setDragSource({ files: filesToDrag, side: data.side });
    setActiveDragData({
      entry: data.entry,
      side: data.side,
      selectedCount: filesToDrag.length,
    });
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;

    console.log("[Transfer] Drag ended:", { active: active.id, over: over?.id });

    setActiveDragData(null);

    if (!over || !dragSource) {
      setDragSource(null);
      return;
    }

    // Parse the drop target
    const dropId = over.id as string;
    if (!dropId.startsWith("drop-")) {
      setDragSource(null);
      return;
    }

    const dropSide = dropId.replace("drop-", "") as "left" | "right";
    const dropData = over.data.current as { side: string; currentPath: string };

    // Don't allow drop on same side
    if (dragSource.side === dropSide) {
      console.log("[Transfer] Drop ignored - same side");
      setDragSource(null);
      return;
    }

    const sourceEndpoint = dragSource.side === "left" ? leftEndpoint : rightEndpoint;
    const destEndpoint = dropSide === "left" ? leftEndpoint : rightEndpoint;
    const destPath = dropData.currentPath;

    if (!sourceEndpoint || !destEndpoint) {
      setDragSource(null);
      return;
    }

    console.log("[Transfer] Drop successful:", {
      files: dragSource.files.length,
      from: dragSource.side,
      to: dropSide,
      destPath,
    });

    setPendingTransfer({
      files: dragSource.files,
      sourceEndpoint,
      destEndpoint,
      destPath,
    });
    setDragSource(null);
  }

  function handleConfirmTransfer(operation: TransferOperation) {
    if (!pendingTransfer) return;

    createTransferMutation.mutate({
      sourceEndpoint: pendingTransfer.sourceEndpoint,
      destEndpoint: pendingTransfer.destEndpoint,
      sourcePaths: pendingTransfer.files.map((f) => f.path),
      destPath: pendingTransfer.destPath,
      operation,
    });
  }

  // Quick transfer buttons
  function handleTransferToRight() {
    if (!leftEndpoint || !rightEndpoint) return;

    const files = ((leftFilesQuery.data ?? []) as FileEntry[]).filter((f) => leftSelected.has(f.path));
    if (files.length === 0) return;

    setPendingTransfer({
      files,
      sourceEndpoint: leftEndpoint,
      destEndpoint: rightEndpoint,
      destPath: rightPath,
    });
  }

  function handleTransferToLeft() {
    if (!leftEndpoint || !rightEndpoint) return;

    const files = ((rightFilesQuery.data ?? []) as FileEntry[]).filter((f) => rightSelected.has(f.path));
    if (files.length === 0) return;

    setPendingTransfer({
      files,
      sourceEndpoint: rightEndpoint,
      destEndpoint: leftEndpoint,
      destPath: leftPath,
    });
  }

  const isLoading = storagesQuery.isLoading || hostsQuery.isLoading || vastQuery.isLoading;

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  const canTransferToRight = leftSelected.size > 0 && leftEndpoint && rightEndpoint &&
    getEndpointKey(leftEndpoint) !== getEndpointKey(rightEndpoint);
  const canTransferToLeft = rightSelected.size > 0 && leftEndpoint && rightEndpoint &&
    getEndpointKey(leftEndpoint) !== getEndpointKey(rightEndpoint);

  return (
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div className="h-full flex flex-col p-4 gap-4">
        {/* Header */}
        <div className="flex-shrink-0 flex items-center justify-between">
          <h1 className="text-lg font-semibold">File Transfer</h1>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>Drag files or use arrows</span>
            <span className="text-muted-foreground/50">|</span>
            <span className="font-mono">Shift+Click</span>
            <span>range select</span>
            <span className="text-muted-foreground/50">|</span>
            <span className="font-mono">Cmd+A</span>
            <span>select all</span>
          </div>
        </div>

        {/* File panes */}
        <div className="flex-1 grid grid-cols-[1fr_auto_1fr] gap-4 min-h-0">
          {/* Left pane */}
          <div className="min-w-0 min-h-0 h-full">
            <FilePane
              side="left"
              storages={storages}
              hosts={hosts}
              vastInstances={vastInstances}
              endpoint={leftEndpoint}
              onEndpointChange={(ep) => {
                setLeftEndpoint(ep);
                setLeftPath("/");
                setLeftSelected(new Set());
              }}
              currentPath={leftPath}
              onPathChange={setLeftPath}
              selectedFiles={leftSelected}
              onSelectionChange={setLeftSelected}
              isDropTarget={dragSource?.side === "right"}
            />
          </div>

          {/* Center controls */}
          <div className="flex flex-col items-center justify-center gap-2">
            <Button
              size="icon"
              variant="outline"
              onClick={handleTransferToRight}
            disabled={!canTransferToRight}
            title="Copy to right"
          >
            <ArrowRight className="h-4 w-4" />
          </Button>
          <Button
            size="icon"
            variant="outline"
            onClick={handleTransferToLeft}
            disabled={!canTransferToLeft}
            title="Copy to left"
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </div>

        {/* Right pane */}
        <div className="min-w-0 min-h-0 h-full">
          <FilePane
            side="right"
            storages={storages}
            hosts={hosts}
            vastInstances={vastInstances}
            endpoint={rightEndpoint}
            onEndpointChange={(ep) => {
              setRightEndpoint(ep);
              setRightPath("/");
              setRightSelected(new Set());
            }}
            currentPath={rightPath}
            onPathChange={setRightPath}
            selectedFiles={rightSelected}
            onSelectionChange={setRightSelected}
            isDropTarget={dragSource?.side === "left"}
          />
        </div>
      </div>

      {/* Transfer queue at bottom */}
      <div className="flex-shrink-0">
        <TransferQueue />
      </div>

      {/* Inline transfer action bar */}
      <AnimatePresence>
        {pendingTransfer && (
          <TransferActionBar
            files={pendingTransfer.files}
            sourceEndpoint={pendingTransfer.sourceEndpoint}
            destEndpoint={pendingTransfer.destEndpoint}
            destPath={pendingTransfer.destPath}
            storages={storages}
            hosts={hosts}
            vastInstances={vastInstances}
            onConfirm={handleConfirmTransfer}
            onCancel={() => setPendingTransfer(null)}
            isPending={createTransferMutation.isPending}
          />
        )}
      </AnimatePresence>

      {/* Drag overlay */}
      <DragOverlay>
        {activeDragData && (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-background border shadow-lg">
            {activeDragData.entry.is_dir ? <IconFolder /> : <IconFile />}
            <span className="text-sm font-medium">{activeDragData.entry.name}</span>
            {activeDragData.selectedCount > 1 && (
              <Badge className="ml-1">{activeDragData.selectedCount}</Badge>
            )}
          </div>
        )}
      </DragOverlay>
    </div>
    </DndContext>
  );
}

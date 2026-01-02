/**
 * FilePicker - A reusable modal for browsing and selecting files/folders
 * Supports: Local filesystem, Hosts (SSH), Storage backends
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, useEffect, useMemo } from "react";
import {
  Folder,
  File,
  ChevronRight,
  ArrowUp,
  Home,
  FolderPlus,
  Loader2,
} from "lucide-react";
import {
  createHostDir,
  createLocalDir,
  listLocalFiles,
  listHostFiles,
  storageApi,
  useHosts,
  useStorages,
} from "@/lib/tauri-api";
import type { FileEntry, Host, Storage } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

// ============================================================
// Types
// ============================================================

export type EndpointType = "local" | "host" | "storage";

export type SelectedEndpoint =
  | { type: "local"; path: string }
  | { type: "host"; hostId: string; path: string }
  | { type: "storage"; storageId: string; path: string };

interface FilePickerProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (endpoint: SelectedEndpoint, selectedPaths: string[]) => void;
  title?: string;
  mode?: "file" | "folder" | "both";
  multiple?: boolean;
  defaultEndpointType?: EndpointType;
  defaultHostId?: string;
  defaultStorageId?: string;
  defaultPath?: string;
}

// ============================================================
// Utilities
// ============================================================

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function getParentPath(path: string): string {
  if (!path || path === "/" || path === "") return "/";
  const parts = path.split("/").filter(Boolean);
  parts.pop();
  return parts.length === 0 ? "/" : "/" + parts.join("/");
}

// ============================================================
// Component
// ============================================================

export function FilePicker({
  isOpen,
  onClose,
  onSelect,
  title = "Select Files",
  mode = "both",
  multiple = true,
  defaultEndpointType = "local",
  defaultHostId = "",
  defaultStorageId = "",
  defaultPath = "",
}: FilePickerProps) {
  const [endpointType, setEndpointType] = useState<EndpointType>(defaultEndpointType);
  const [hostId, setHostId] = useState<string>(defaultHostId);
  const [storageId, setStorageId] = useState<string>(defaultStorageId);
  const [currentPath, setCurrentPath] = useState(defaultPath || "/");
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const [newFolderOpen, setNewFolderOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [newFolderError, setNewFolderError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  // Reset when opening
  useEffect(() => {
    if (isOpen) {
      setEndpointType(defaultEndpointType);
      setHostId(defaultHostId);
      setStorageId(defaultStorageId);
      setCurrentPath(defaultPath || "/");
      setSelectedPaths(new Set());
      setNewFolderOpen(false);
      setNewFolderName("");
      setNewFolderError(null);
    } else {
      setNewFolderOpen(false);
    }
  }, [isOpen, defaultEndpointType, defaultHostId, defaultStorageId, defaultPath]);

  // Load hosts and storages
  const { data: hosts = [] } = useHosts();
  const { data: storages = [] } = useStorages();

  // Load files based on endpoint type
  const { data: files = [], isLoading } = useQuery({
    queryKey: ["file-picker", endpointType, hostId, storageId, currentPath],
    queryFn: async () => {
      if (endpointType === "local") {
        return await listLocalFiles(currentPath);
      } else if (endpointType === "storage" && storageId) {
        return await storageApi.listFiles(storageId, currentPath);
      } else if (endpointType === "host" && hostId) {
        return await listHostFiles(hostId, currentPath);
      }
      return [];
    },
    enabled:
      isOpen &&
      (endpointType === "local" ||
        (endpointType === "storage" && !!storageId) ||
        (endpointType === "host" && !!hostId)),
  });

  // Filter and sort files
  const sortedFiles = useMemo(() => {
    let filtered = files;
    if (mode === "file") {
      // Show all but only allow selecting files
    } else if (mode === "folder") {
      // Show only folders
      filtered = files.filter((f) => f.is_dir);
    }
    // Sort: folders first, then by name
    return [...filtered].sort((a, b) => {
      if (a.is_dir && !b.is_dir) return -1;
      if (!a.is_dir && b.is_dir) return 1;
      return a.name.localeCompare(b.name);
    });
  }, [files, mode]);

  const handleNavigate = (path: string) => {
    setCurrentPath(path);
    setSelectedPaths(new Set());
  };

  const handleToggleSelect = (file: FileEntry) => {
    if (mode === "file" && file.is_dir) {
      // Navigate into folder
      handleNavigate(file.path);
      return;
    }
    if (mode === "folder" && !file.is_dir) {
      return; // Can't select files in folder mode
    }

    const newSelected = new Set(selectedPaths);
    if (newSelected.has(file.path)) {
      newSelected.delete(file.path);
    } else {
      if (!multiple) {
        newSelected.clear();
      }
      newSelected.add(file.path);
    }
    setSelectedPaths(newSelected);
  };

  const handleDoubleClick = (file: FileEntry) => {
    if (file.is_dir) {
      handleNavigate(file.path);
    }
  };

  const handleConfirm = () => {
    const paths = Array.from(selectedPaths);

    let endpoint: SelectedEndpoint;
    if (endpointType === "local") {
      endpoint = { type: "local", path: currentPath };
    } else if (endpointType === "host") {
      endpoint = { type: "host", hostId, path: currentPath };
    } else {
      endpoint = { type: "storage", storageId, path: currentPath };
    }

    onSelect(endpoint, paths);
    onClose();
  };

  const createFolderMutation = useMutation({
    mutationFn: async (path: string) => {
      if (endpointType === "local") {
        await createLocalDir(path);
      } else if (endpointType === "host") {
        if (!hostId) {
          throw new Error("Please select a host.");
        }
        await createHostDir(hostId, path);
      } else {
        if (!storageId) {
          throw new Error("Please select a storage.");
        }
        await storageApi.mkdir(storageId, path);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["file-picker"] });
      setNewFolderName("");
      setNewFolderError(null);
      setNewFolderOpen(false);
    },
    onError: (e) => {
      const msg = e instanceof Error ? e.message : String(e);
      setNewFolderError(msg);
    },
  });

  const canCreateFolder =
    endpointType === "local" ||
    (endpointType === "host" && !!hostId) ||
    (endpointType === "storage" && !!storageId);

  const handleCreateFolder = () => {
    const name = newFolderName.trim();
    if (!name) {
      setNewFolderError("Folder name is required.");
      return;
    }
    if (name.includes("/")) {
      setNewFolderError("Folder name cannot include '/'.");
      return;
    }
    const path = currentPath === "/" ? `/${name}` : `${currentPath}/${name}`;
    setNewFolderError(null);
    createFolderMutation.mutate(path);
  };

  // Get home directory for local file browsing
  const handleGoHome = () => {
    // ~ will be resolved on the backend
    setCurrentPath("~");
  };

  // Path breadcrumbs
  const pathParts = currentPath.split("/").filter(Boolean);

  return (
    <>
      <Dialog open={isOpen} onOpenChange={onClose}>
        <DialogContent className="max-w-3xl max-h-[80vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription className="flex flex-col gap-2 pt-2">
              {/* Endpoint selector */}
              <div className="flex items-center gap-2 flex-wrap">
                <div className="w-[140px]">
                  <Label className="text-xs mb-1 block">Source</Label>
                  <Select
                    value={endpointType}
                    onValueChange={(value) => {
                      setEndpointType(value as EndpointType);
                      setCurrentPath("/");
                      setSelectedPaths(new Set());
                    }}
                  >
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="local">Local</SelectItem>
                      <SelectItem value="host">Host</SelectItem>
                      <SelectItem value="storage">Storage</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {endpointType === "host" && (
                  <div className="w-[200px]">
                    <Label className="text-xs mb-1 block">Host</Label>
                    <Select
                      value={hostId}
                      onValueChange={(value) => {
                        setHostId(value);
                        setCurrentPath("/");
                      }}
                    >
                      <SelectTrigger className="h-8 text-xs">
                        <SelectValue placeholder="Select host..." />
                      </SelectTrigger>
                      <SelectContent>
                        {hosts.map((h: Host) => (
                          <SelectItem key={h.id} value={h.id}>
                            {h.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}

                {endpointType === "storage" && (
                  <div className="w-[200px]">
                    <Label className="text-xs mb-1 block">Storage</Label>
                    <Select
                      value={storageId}
                      onValueChange={(value) => {
                        setStorageId(value);
                        setCurrentPath("/");
                      }}
                    >
                      <SelectTrigger className="h-8 text-xs">
                        <SelectValue placeholder="Select storage..." />
                      </SelectTrigger>
                      <SelectContent>
                        {storages.map((s: Storage) => (
                          <SelectItem key={s.id} value={s.id}>
                            {s.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}

                {endpointType === "local" && (
                  <Button size="sm" variant="ghost" onClick={handleGoHome} className="mt-5">
                    <Home className="h-4 w-4 mr-2" />
                    Go to Home
                  </Button>
                )}

                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setNewFolderError(null);
                    setNewFolderName("");
                    setNewFolderOpen(true);
                  }}
                  disabled={!canCreateFolder}
                  className="mt-5"
                >
                  <FolderPlus className="h-4 w-4 mr-2" />
                  New Folder
                </Button>
              </div>
            </DialogDescription>
          </DialogHeader>

          <div className="flex-1 overflow-hidden flex flex-col gap-4">
            {/* Path bar */}
            <div className="flex items-center gap-1 p-2 bg-muted rounded-lg overflow-x-auto">
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7"
                onClick={() => handleNavigate(getParentPath(currentPath))}
                disabled={currentPath === "/" || currentPath === ""}
              >
                <ArrowUp className="h-4 w-4" />
              </Button>

              <Button
                type="button"
                variant="link"
                className="h-auto p-0 px-1 text-sm"
                onClick={() => handleNavigate("/")}
              >
                /
              </Button>

              {pathParts.map((part, i) => (
                <div key={i} className="flex items-center">
                  <ChevronRight className="h-4 w-4" />
                  <Button
                    type="button"
                    variant="link"
                    className="h-auto p-0 px-1 text-sm"
                    onClick={() => handleNavigate("/" + pathParts.slice(0, i + 1).join("/"))}
                  >
                    {part}
                  </Button>
                </div>
              ))}
            </div>

            {/* File list */}
            <ScrollArea className="flex-1 h-[400px]">
              {isLoading ? (
                <div className="flex items-center justify-center h-full">
                  <Loader2 className="h-6 w-6 animate-spin" />
                </div>
              ) : sortedFiles.length === 0 ? (
                <div className="flex items-center justify-center h-full text-muted-foreground">
                  No files found
                </div>
              ) : (
                <div className="space-y-1 pr-4">
                  {sortedFiles.map((file) => {
                    const isSelected = selectedPaths.has(file.path);
                    const canSelect =
                      mode === "both" ||
                      (mode === "file" && !file.is_dir) ||
                      (mode === "folder" && file.is_dir);

                    return (
                      <div
                        key={file.path}
                        className={cn(
                          "flex items-center gap-3 p-2 rounded-lg cursor-pointer transition-colors",
                          isSelected
                            ? "bg-primary/10 border border-primary/30"
                            : "hover:bg-accent"
                        )}
                        onClick={() => handleToggleSelect(file)}
                        onDoubleClick={() => handleDoubleClick(file)}
                      >
                        {canSelect && (
                          <Checkbox
                            checked={isSelected}
                            onCheckedChange={() => handleToggleSelect(file)}
                          />
                        )}

                        {file.is_dir ? (
                          <Folder className="h-5 w-5 text-yellow-500" />
                        ) : (
                          <File className="h-5 w-5 text-muted-foreground" />
                        )}

                        <div className="flex-1 min-w-0">
                          <p className="text-sm truncate">{file.name}</p>
                        </div>

                        {!file.is_dir && (
                          <span className="text-xs text-muted-foreground">
                            {formatBytes(file.size)}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </ScrollArea>
          </div>

          <DialogFooter>
            <div className="flex-1 text-sm text-muted-foreground">
              {selectedPaths.size > 0 && `${selectedPaths.size} selected`}
            </div>
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button onClick={handleConfirm} disabled={selectedPaths.size === 0}>
              Select
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={newFolderOpen} onOpenChange={setNewFolderOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New Folder</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="folder-name">Folder Name</Label>
              <Input
                id="folder-name"
                placeholder="my-folder"
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleCreateFolder();
                }}
                autoFocus
              />
            </div>
            {newFolderError && <p className="text-sm text-destructive">{newFolderError}</p>}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setNewFolderOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleCreateFolder}
              disabled={!newFolderName.trim() || createFolderMutation.isPending}
            >
              {createFolderMutation.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

export default FilePicker;

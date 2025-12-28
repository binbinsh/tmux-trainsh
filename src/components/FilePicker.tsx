/**
 * FilePicker - A reusable modal for browsing and selecting files/folders
 * Supports: Local filesystem, Hosts (SSH), Storage backends
 */

import {
  Checkbox,
  Input,
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ScrollShadow,
  Select,
  SelectItem,
  Spinner,
} from "@nextui-org/react";
import { Button } from "./ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, useEffect, useMemo } from "react";
import { createHostDir, createLocalDir, listLocalFiles, listHostFiles, storageApi, useHosts, useStorages } from "../lib/tauri-api";
import type { FileEntry, Host, Storage } from "../lib/types";

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
// Icons
// ============================================================

function IconFolder() {
  return (
    <svg className="w-5 h-5 text-warning" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
    </svg>
  );
}

function IconFile() {
  return (
    <svg className="w-5 h-5 text-default-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
    </svg>
  );
}

function IconChevronRight() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
    </svg>
  );
}

function IconUp() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 10.5L12 3m0 0l7.5 7.5M12 3v18" />
    </svg>
  );
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
    enabled: isOpen && (
      endpointType === "local" ||
      (endpointType === "storage" && !!storageId) ||
      (endpointType === "host" && !!hostId)
    ),
  });

  // Filter and sort files
  const sortedFiles = useMemo(() => {
    let filtered = files;
    if (mode === "file") {
      // Show all but only allow selecting files
    } else if (mode === "folder") {
      // Show only folders
      filtered = files.filter(f => f.is_dir);
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
      <Modal isOpen={isOpen} onClose={onClose} size="3xl" scrollBehavior="inside">
        <ModalContent>
          <ModalHeader className="flex flex-col gap-2">
            <span>{title}</span>
            
            {/* Endpoint selector */}
            <div className="flex items-center gap-2 flex-wrap">
              <Select labelPlacement="inside" selectedKeys={[endpointType]}
              onSelectionChange={(keys) => {
                const type = Array.from(keys)[0] as EndpointType;
                setEndpointType(type);
                setCurrentPath("/");
                setSelectedPaths(new Set());
              }}
              size="sm"
              variant="bordered"
              className="max-w-[140px]"
              label="Source"><SelectItem key="local">Local</SelectItem>
              <SelectItem key="host">Host</SelectItem>
              <SelectItem key="storage">Storage</SelectItem></Select>
              
              {endpointType === "host" && (
                <Select labelPlacement="inside" selectedKeys={hostId ? [hostId] : []}
                onSelectionChange={(keys) => {
                  const id = Array.from(keys)[0] as string;
                  setHostId(id);
                  setCurrentPath("/");
                }}
                size="sm"
                variant="bordered"
                className="max-w-[200px]"
                label="Host"
                placeholder="Select host...">{hosts.map((h: Host) => (
                  <SelectItem key={h.id}>{h.name}</SelectItem>
                ))}</Select>
              )}
              
              {endpointType === "storage" && (
                <Select labelPlacement="inside" selectedKeys={storageId ? [storageId] : []}
                onSelectionChange={(keys) => {
                  const id = Array.from(keys)[0] as string;
                  setStorageId(id);
                  setCurrentPath("/");
                }}
                size="sm"
                variant="bordered"
                className="max-w-[200px]"
                label="Storage"
                placeholder="Select storage...">{storages.map((s: Storage) => (
                  <SelectItem key={s.id}>{s.name}</SelectItem>
                ))}</Select>
              )}
              
              {endpointType === "local" && (
                <Button
                  size="sm"
                  variant="flat"
                  onPress={handleGoHome}
                >
                  Go to Home
                </Button>
              )}

              <Button
                size="sm"
                variant="flat"
                onPress={() => {
                  setNewFolderError(null);
                  setNewFolderName("");
                  setNewFolderOpen(true);
                }}
                isDisabled={!canCreateFolder}
              >
                New Folder
              </Button>
            </div>
          </ModalHeader>
          
          <ModalBody>
            {/* Path bar */}
            <div className="flex items-center gap-1 mb-4 p-2 bg-default-100 rounded-lg overflow-x-auto">
              <Button
                isIconOnly
                size="sm"
                variant="light"
                onPress={() => handleNavigate(getParentPath(currentPath))}
                isDisabled={currentPath === "/" || currentPath === ""}
              >
                <IconUp />
              </Button>
              
              <button
                className="text-sm text-primary hover:underline px-1"
                onClick={() => handleNavigate("/")}
              >
                /
              </button>
              
              {pathParts.map((part, i) => (
                <div key={i} className="flex items-center">
                  <IconChevronRight />
                  <button
                    className="text-sm text-primary hover:underline px-1"
                    onClick={() => handleNavigate("/" + pathParts.slice(0, i + 1).join("/"))}
                  >
                    {part}
                  </button>
                </div>
              ))}
            </div>
            
            {/* File list */}
            <ScrollShadow className="h-[400px]">
              {isLoading ? (
                <div className="flex items-center justify-center h-full">
                  <Spinner />
                </div>
              ) : sortedFiles.length === 0 ? (
                <div className="flex items-center justify-center h-full text-foreground/50">
                  No files found
                </div>
              ) : (
                <div className="space-y-1">
                  {sortedFiles.map((file) => {
                    const isSelected = selectedPaths.has(file.path);
                    const canSelect = mode === "both" || 
                      (mode === "file" && !file.is_dir) ||
                      (mode === "folder" && file.is_dir);
                    
                    return (
                      <div
                        key={file.path}
                        className={`flex items-center gap-3 p-2 rounded-lg cursor-pointer transition-colors ${
                          isSelected 
                            ? "bg-primary/10 border border-primary/30" 
                            : "hover:bg-default-100"
                        }`}
                        onClick={() => handleToggleSelect(file)}
                        onDoubleClick={() => handleDoubleClick(file)}
                      >
                        {canSelect && (
                          <Checkbox
                            isSelected={isSelected}
                            onValueChange={() => handleToggleSelect(file)}
                            size="sm"
                          />
                        )}
                        
                        {file.is_dir ? <IconFolder /> : <IconFile />}
                        
                        <div className="flex-1 min-w-0">
                          <p className="text-sm truncate">{file.name}</p>
                        </div>
                        
                        {!file.is_dir && (
                          <span className="text-xs text-foreground/50">
                            {formatBytes(file.size)}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </ScrollShadow>
          </ModalBody>
          
          <ModalFooter>
            <div className="flex-1 text-sm text-foreground/60">
              {selectedPaths.size > 0 && `${selectedPaths.size} selected`}
            </div>
            <Button variant="light" onPress={onClose}>
              Cancel
            </Button>
            <Button
              color="primary"
              onPress={handleConfirm}
              isDisabled={selectedPaths.size === 0}
            >
              Select
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>

      <Modal isOpen={newFolderOpen} onOpenChange={setNewFolderOpen} isDismissable={true}>
        <ModalContent>
          {(onCloseModal) => (
            <>
              <ModalHeader>New Folder</ModalHeader>
              <ModalBody>
                <Input
                  labelPlacement="inside"
                  label="Folder Name"
                  placeholder="my-folder"
                  value={newFolderName}
                  onValueChange={setNewFolderName}
                  autoFocus
                  isRequired
                />
                {newFolderError && <p className="text-sm text-danger">{newFolderError}</p>}
              </ModalBody>
              <ModalFooter>
                <Button variant="light" onPress={onCloseModal}>
                  Cancel
                </Button>
                <Button
                  color="primary"
                  onPress={handleCreateFolder}
                  isLoading={createFolderMutation.isPending}
                  isDisabled={!newFolderName.trim()}
                >
                  Create
                </Button>
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>
    </>
  );
}

export default FilePicker;

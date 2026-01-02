import {
  Badge,
  Button,
  Card,
  CardContent,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
} from "@/components/ui";
import { AppIcon } from "../components/AppIcon";
import { Loader2 } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "@tanstack/react-router";
import { motion, AnimatePresence } from "framer-motion";
import { useCallback, useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import {
  storageApi,
  transferApi,
  useStorage,
  useStorageFiles,
  useStorages,
} from "../lib/tauri-api";
import type { FileEntry, Storage, TransferOperation } from "../lib/types";
import { DataTable, type ColumnDef } from "../components/shared/DataTable";

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
    <svg className="w-5 h-5 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
    </svg>
  );
}

function IconRefresh() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
    </svg>
  );
}

function getStorageIconNode(storage: Storage, sizeClass = "w-7 h-7") {
  switch (storage.backend.type) {
    case "google_drive":
      return <AppIcon name="googledrive" className={sizeClass} alt="Google Drive" />;
    case "cloudflare_r2":
      return <AppIcon name="cloudflare" className={sizeClass} alt="Cloudflare R2" />;
    case "ssh_remote":
      return <AppIcon name="ssh" className={sizeClass} alt="SSH" />;
    case "smb":
      return <AppIcon name="smb" className={sizeClass} alt="SMB" />;
    default:
      return (
        <span className={sizeClass.includes("w-4") ? "text-sm" : "text-2xl"}>
          {storage.icon || "📁"}
        </span>
      );
  }
}

function IconNewFolder() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 10.5v6m3-3H9m4.06-7.19l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
    </svg>
  );
}

function IconTrash() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
    </svg>
  );
}

function IconCopy() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 01-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 011.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 00-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 01-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 00-3.375-3.375h-1.5a1.125 1.125 0 01-1.125-1.125v-1.5a3.375 3.375 0 00-3.375-3.375H9.75" />
    </svg>
  );
}

function IconArrowLeft() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
    </svg>
  );
}

function IconArrowUp() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 10.5L12 3m0 0l7.5 7.5M12 3v18" />
    </svg>
  );
}

function IconSync() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
    </svg>
  );
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

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "-";
  return new Date(dateStr).toLocaleString();
}

// ============================================================
// Transfer Modal
// ============================================================

function TransferModal({
  isOpen,
  onOpenChange,
  sourceStorage: srcStorage,
  selectedFiles,
  currentPath,
  onSuccess,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  sourceStorage: Storage | null;
  selectedFiles: FileEntry[];
  currentPath: string;
  onSuccess: () => void;
}) {
  const storages = useStorages();
  const queryClient = useQueryClient();

  const [destStorageId, setDestStorageId] = useState("");
  const [destPath, setDestPath] = useState("/");
  const [operation, setOperation] = useState<TransferOperation>("copy");
  const [error, setError] = useState<string | null>(null);

  const createTransfer = useMutation({
    mutationFn: transferApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
      onSuccess();
      onOpenChange(false);
    },
    onError: (e) => setError(String(e)),
  });

  function handleTransfer() {
    if (!srcStorage || !destStorageId) {
      setError("Please select source and destination");
      return;
    }

    createTransfer.mutate({
      source_storage_id: srcStorage.id,
      source_paths: selectedFiles.map((f) => f.path),
      dest_storage_id: destStorageId,
      dest_path: destPath || "/",
      operation,
    });
  }

  const otherStorages = (storages.data ?? []).filter(
    (s) => s.id !== srcStorage?.id
  );

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Transfer Files</DialogTitle>
          <DialogDescription>
            Selected {selectedFiles.length} item(s) from{" "}
            <span className="font-medium text-foreground">{srcStorage?.name}</span>
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          <div className="grid gap-2">
            <Label>Selected paths</Label>
            <div className="max-h-32 overflow-auto rounded-lg border border-border bg-muted/50 p-2">
              {selectedFiles.map((f) => (
                <div key={f.path} className="text-xs font-mono truncate">
                  {f.path}
                </div>
              ))}
            </div>
          </div>

          <div className="grid gap-2">
            <Label>Destination Storage</Label>
            <Select value={destStorageId} onValueChange={setDestStorageId}>
              <SelectTrigger>
                <SelectValue placeholder="Select destination" />
              </SelectTrigger>
              <SelectContent>
                {otherStorages.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    <span className="flex items-center gap-2">
                      {getStorageIconNode(s, "w-4 h-4")}
                      {s.name}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="transfer-dest-path">Destination Path</Label>
            <Input
              id="transfer-dest-path"
              placeholder="/"
              value={destPath}
              onChange={(e) => setDestPath(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">Path on destination storage</p>
          </div>

          <div className="grid gap-2">
            <Label>Operation</Label>
            <Select value={operation} onValueChange={(value) => setOperation(value as TransferOperation)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="copy">Copy (keep source)</SelectItem>
                <SelectItem value="move">Move (delete source after)</SelectItem>
                <SelectItem value="sync">Sync (mirror with delete)</SelectItem>
                <SelectItem value="sync_no_delete">Sync (no delete)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {error && <p className="text-sm text-danger">{error}</p>}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleTransfer}
            disabled={!destStorageId || selectedFiles.length === 0 || createTransfer.isPending}
          >
            {createTransfer.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
            Start Transfer
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ============================================================
// New Folder Modal
// ============================================================

function NewFolderModal({
  isOpen,
  onOpenChange,
  storageId,
  currentPath,
  onSuccess,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  storageId: string;
  currentPath: string;
  onSuccess: () => void;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const createMutation = useMutation({
    mutationFn: async () => {
      const path = currentPath === "/" ? `/${name}` : `${currentPath}/${name}`;
      await storageApi.mkdir(storageId, path);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["storages", storageId, "files"] });
      onSuccess();
      setName("");
      onOpenChange(false);
    },
    onError: (e) => setError(String(e)),
  });

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New Folder</DialogTitle>
        </DialogHeader>

        <div className="grid gap-2">
          <Label htmlFor="new-folder-name">Folder Name</Label>
          <Input
            id="new-folder-name"
            placeholder="my-folder"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
          {error && <p className="text-sm text-danger">{error}</p>}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => createMutation.mutate()}
            disabled={!name.trim() || createMutation.isPending}
          >
            {createMutation.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ============================================================
// File Browser Page
// ============================================================

export function FileBrowserPage() {
  const navigate = useNavigate();
  const { id } = useParams({ from: "/storage/$id" });
  const [currentPath, setCurrentPath] = useState("/");
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());

  const [newFolderOpen, setNewFolderOpen] = useState(false);
  const [transferOpen, setTransferOpen] = useState(false);

  const storageQuery = useStorage(id);
  const filesQuery = useStorageFiles(id, currentPath);
  const queryClient = useQueryClient();

  const storage = storageQuery.data;
  const files = filesQuery.data ?? [];

  // Selection helpers
  const selectedFiles = useMemo(
    () => files.filter((f) => selectedPaths.has(f.path)),
    [files, selectedPaths]
  );

  const allSelected = files.length > 0 && files.every((f) => selectedPaths.has(f.path));

  function toggleSelection(path: string) {
    const next = new Set(selectedPaths);
    if (next.has(path)) {
      next.delete(path);
    } else {
      next.add(path);
    }
    setSelectedPaths(next);
  }

  function toggleSelectAll() {
    if (allSelected) {
      setSelectedPaths(new Set());
    } else {
      setSelectedPaths(new Set(files.map((f) => f.path)));
    }
  }

  function clearSelection() {
    setSelectedPaths(new Set());
  }

  // Navigation
  function navigateToPath(path: string) {
    setCurrentPath(path);
    clearSelection();
  }

  function navigateUp() {
    if (currentPath === "/") return;
    const parts = currentPath.split("/").filter(Boolean);
    parts.pop();
    navigateToPath(parts.length === 0 ? "/" : "/" + parts.join("/"));
  }

  function handleRowClick(entry: FileEntry) {
    if (entry.is_dir) {
      navigateToPath(entry.path);
    }
  }

  // Delete
  const deleteMutation = useMutation({
    mutationFn: async (paths: string[]) => {
      for (const path of paths) {
        await storageApi.deleteFile(id, path);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["storages", id, "files"] });
      clearSelection();
    },
  });

  function handleDelete() {
    if (selectedFiles.length === 0) return;
    if (!confirm(`Delete ${selectedFiles.length} item(s)?`)) return;
    deleteMutation.mutate(selectedFiles.map((f) => f.path));
  }

  // Breadcrumbs
  const breadcrumbs = useMemo(() => {
    const parts = currentPath.split("/").filter(Boolean);
    const items: { name: string; path: string }[] = [{ name: "Root", path: "/" }];
    let acc = "";
    for (const part of parts) {
      acc += "/" + part;
      items.push({ name: part, path: acc });
    }
    return items;
  }, [currentPath]);

  // File table columns for DataTable
  const fileColumns: ColumnDef<FileEntry>[] = useMemo(() => [
    {
      key: "select",
      header: (
        <Checkbox
          checked={allSelected ? true : selectedPaths.size > 0 ? "indeterminate" : false}
          onCheckedChange={() => toggleSelectAll()}
          aria-label="Select all"
        />
      ),
      width: "40px",
      render: (entry) => (
        <Checkbox
          checked={selectedPaths.has(entry.path)}
          onCheckedChange={() => toggleSelection(entry.path)}
          onClick={(e) => e.stopPropagation()}
          aria-label={`Select ${entry.name}`}
        />
      ),
    },
    {
      key: "name",
      header: "Name",
      grow: true,
      render: (entry) => (
        <div className="flex items-center gap-2">
          {entry.is_dir ? <IconFolder /> : <IconFile />}
          <span className={entry.is_dir ? "font-medium" : ""}>
            {entry.name}
          </span>
        </div>
      ),
    },
    {
      key: "size",
      header: "Size",
      width: "120px",
      render: (entry) => (
        <span className="text-sm text-foreground/60">
          {entry.is_dir ? "-" : formatBytes(entry.size)}
        </span>
      ),
    },
    {
      key: "modified",
      header: "Modified",
      width: "180px",
      render: (entry) => (
        <span className="text-sm text-muted-foreground">
          {formatDate(entry.modified_at)}
        </span>
      ),
    },
  ], [allSelected, selectedPaths, toggleSelectAll, toggleSelection]);

  if (storageQuery.isLoading) {
    return (
      <div className="h-full flex flex-col">
        {/* Skeleton Header */}
        <div className="flex-shrink-0 p-4 border-b border-border">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-3">
              <Skeleton className="w-9 h-9 rounded-lg" />
              <Skeleton className="w-8 h-8 rounded-lg" />
              <div>
                <Skeleton className="h-6 w-40 rounded-lg mb-1" />
                <Skeleton className="h-4 w-56 rounded-lg" />
              </div>
            </div>
            <div className="flex gap-2">
              <Skeleton className="w-9 h-9 rounded-lg" />
              <Skeleton className="w-9 h-9 rounded-lg" />
            </div>
          </div>
          {/* Breadcrumbs skeleton */}
          <div className="flex gap-2">
            <Skeleton className="h-6 w-16 rounded-lg" />
            <Skeleton className="h-6 w-24 rounded-lg" />
            <Skeleton className="h-6 w-20 rounded-lg" />
          </div>
        </div>
        {/* Skeleton File List */}
        <div className="flex-1 p-4">
          <div className="space-y-2">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="flex items-center gap-3 p-3 rounded-lg border border-border">
                <Skeleton className="w-8 h-8 rounded" />
                <Skeleton className="h-5 flex-1 rounded-lg" />
                <Skeleton className="h-4 w-20 rounded-lg" />
                <Skeleton className="h-4 w-32 rounded-lg" />
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!storage) {
    return (
      <div className="h-full flex items-center justify-center">
        <p className="text-foreground/60">Storage not found</p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex-shrink-0 p-4 border-b border-border">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <Button
              size="icon"
              variant="ghost"
              onClick={() => navigate({ to: "/storage" })}
              aria-label="Back"
            >
              <IconArrowLeft />
            </Button>
            {getStorageIconNode(storage)}
            <div>
              <h1 className="text-lg font-semibold">{storage.name}</h1>
              <p className="text-xs text-muted-foreground">
                {storage.backend.type === "local" && storage.backend.root_path}
                {storage.backend.type === "ssh_remote" && `SSH: ${storage.backend.host_id}`}
                {storage.backend.type === "cloudflare_r2" && `R2: ${storage.backend.bucket}`}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => filesQuery.refetch()}
              disabled={filesQuery.isFetching}
            >
              {filesQuery.isFetching ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <IconRefresh />}
              Refresh
            </Button>
            {!storage.readonly && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setNewFolderOpen(true)}
              >
                <IconNewFolder />
                New Folder
              </Button>
            )}
          </div>
        </div>

        {/* Breadcrumbs */}
        <div className="flex items-center gap-2">
          <Button
            size="icon"
            variant="outline"
            className="h-8 w-8"
            onClick={navigateUp}
            disabled={currentPath === "/"}
            aria-label="Up"
          >
            <IconArrowUp />
          </Button>
          <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-xs">
            {breadcrumbs.map((b, idx) => (
              <div key={b.path} className="flex items-center gap-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => navigateToPath(b.path)}
                  disabled={b.path === currentPath}
                  className={cn(
                    "h-auto px-1.5 py-0.5 rounded text-xs font-normal transition-colors disabled:opacity-100",
                    b.path === currentPath
                      ? "text-foreground font-medium"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                >
                  {b.name}
                </Button>
                {idx < breadcrumbs.length - 1 && (
                  <span className="text-muted-foreground/40">/</span>
                )}
              </div>
            ))}
          </nav>
        </div>
      </div>

      {/* Selection Actions */}
      {selectedFiles.length > 0 && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          className="flex-shrink-0 px-4 py-2 bg-primary/10 border-b border-border"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Badge variant="outline">{selectedFiles.length} selected</Badge>
              <Button size="sm" variant="ghost" onClick={clearSelection}>
                Clear
              </Button>
            </div>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => setTransferOpen(true)}
              >
                <IconCopy />
                Copy/Move to...
              </Button>
              {!storage.readonly && (
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={handleDelete}
                  disabled={deleteMutation.isPending}
                >
                  {deleteMutation.isPending && <Loader2 className="h-4 w-4 animate-spin mr-1" />}
                  <IconTrash />
                  Delete
                </Button>
              )}
            </div>
          </div>
        </motion.div>
      )}

      {/* File List */}
      <div className="flex-1 overflow-auto p-4">
        {filesQuery.isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        ) : filesQuery.error ? (
          <Card>
            <CardContent className="pt-6">
              <p className="text-danger whitespace-pre-wrap">
                Error loading files: {
                  typeof filesQuery.error === 'object' && filesQuery.error !== null && 'message' in filesQuery.error
                    ? String((filesQuery.error as { message: string }).message)
                    : String(filesQuery.error)
                }
              </p>
            </CardContent>
          </Card>
        ) : files.length === 0 ? (
          <Card>
            <CardContent className="text-center py-12">
              <p className="text-muted-foreground">This folder is empty</p>
            </CardContent>
          </Card>
        ) : (
          <DataTable
            data={files}
            columns={fileColumns}
            rowKey={(entry) => entry.path}
            onRowClick={handleRowClick}
            emptyContent="This folder is empty"
            compact
          />
        )}
      </div>

      {/* Modals */}
      <NewFolderModal
        isOpen={newFolderOpen}
        onOpenChange={setNewFolderOpen}
        storageId={id}
        currentPath={currentPath}
        onSuccess={() => filesQuery.refetch()}
      />

      <TransferModal
        isOpen={transferOpen}
        onOpenChange={setTransferOpen}
        sourceStorage={storage}
        selectedFiles={selectedFiles}
        currentPath={currentPath}
        onSuccess={() => {
          clearSelection();
          filesQuery.refetch();
        }}
      />
    </div>
  );
}

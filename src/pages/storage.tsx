import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Skeleton } from "@/components/ui/skeleton";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  storageApi,
  pricingApi,
  usePricingSettings,
  useStorages,
  useHosts,
} from "../lib/tauri-api";
import type { Host, Storage, StorageBackend, StorageCreateInput, StorageUpdateInput, StorageUsage } from "../lib/types";
import { calculateR2BucketCost } from "../components/r2-pricing";
import { GoogleDriveWizard } from "../components/GoogleDriveWizard";
import { formatPriceWithRates } from "../lib/currency";
import { AppIcon } from "../components/AppIcon";
import { EmptyHostState, HostRow, HostSection } from "../components/shared/HostCard";
import { cn } from "@/lib/utils";
import {
  Plus,
  RefreshCw,
  MoreVertical,
  Search,
  Filter,
  ArrowUpDown,
  FolderOpen,
  Pencil,
  Trash2,
  Loader2,
} from "lucide-react";

// ============================================================
// Helper Functions
// ============================================================

function SkeletonSection({ itemCount = 3 }: { itemCount?: number }) {
  return (
    <div className="space-y-2 mb-6">
      <Skeleton className="h-6 w-32 mb-3" />
      {Array.from({ length: itemCount }).map((_, i) => (
        <Skeleton key={i} className="h-14 w-full" />
      ))}
    </div>
  );
}

function getBackendTypeName(backend: StorageBackend): string {
  switch (backend.type) {
    case "local": return "Local";
    case "ssh_remote": return "SSH Remote";
    case "google_drive": return "Google Drive";
    case "cloudflare_r2": return "Cloudflare R2";
    case "google_cloud_storage": return "Google Cloud Storage";
    case "smb": return "SMB/NAS";
    default: return "Unknown";
  }
}

function getBackendFallbackEmoji(backend: StorageBackend): string {
  switch (backend.type) {
    case "local": return "💻";
    case "ssh_remote": return "🖥️";
    case "google_drive": return "📁";
    case "cloudflare_r2": return "☁️";
    case "google_cloud_storage": return "🌐";
    case "smb": return "🗄️";
    default: return "📦";
  }
}

function getBackendIconNode(backend: StorageBackend, customIcon?: string | null): ReactNode {
  switch (backend.type) {
    case "ssh_remote":
      return <AppIcon name="ssh" className="w-6 h-6" alt="SSH" />;
    case "google_drive":
      return <AppIcon name="googledrive" className="w-6 h-6" alt="Google Drive" />;
    case "cloudflare_r2":
      return <AppIcon name="cloudflare" className="w-6 h-6" alt="Cloudflare R2" />;
    case "smb":
      return <AppIcon name="smb" className="w-6 h-6" alt="SMB" />;
    default:
      return <span className="text-2xl">{customIcon || getBackendFallbackEmoji(backend)}</span>;
  }
}

function getBackendDescription(backend: StorageBackend, hosts?: Host[]): string {
  switch (backend.type) {
    case "local": return backend.root_path;
    case "ssh_remote": {
      const host = hosts?.find(h => h.id === backend.host_id);
      const hostName = host?.name || backend.host_id.slice(0, 8) + "...";
      return `${hostName}:${backend.root_path}`;
    }
    case "google_drive":
      return backend.root_folder_id ? "Folder selected" : "My Drive";
    case "cloudflare_r2": return `Bucket: ${backend.bucket}`;
    case "google_cloud_storage": return `Bucket: ${backend.bucket}`;
    case "smb": return backend.share ? `//${backend.host}/${backend.share}` : `//${backend.host}`;
    default: return "";
  }
}

/**
 * Format storage size in GB, automatically switching to TB if >= 1000 GB
 */
function formatStorageSize(gb: number, decimals = 2): string {
  if (gb >= 1000) {
    return `${(gb / 1024).toFixed(decimals)} TB`;
  }
  return `${gb.toFixed(decimals)} GB`;
}

// ============================================================
// Add Storage Modal
// ============================================================

function AddStorageModal({
  isOpen,
  onOpenChange,
  onSuccess,
  setShowGDriveWizard,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
  setShowGDriveWizard: (show: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const hosts = useHosts();

  const [storageType, setStorageType] = useState<string>("local");
  const [name, setName] = useState("");
  const [icon, setIcon] = useState("");
  const [readonly, setReadonly] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Local backend
  const [localPath, setLocalPath] = useState("");

  // SSH Remote backend
  const [sshHostId, setSshHostId] = useState("");
  const [sshRootPath, setSshRootPath] = useState("/root");

  // Cloudflare R2 backend
  const [r2AccountId, setR2AccountId] = useState("");
  const [r2AccessKeyId, setR2AccessKeyId] = useState("");
  const [r2SecretAccessKey, setR2SecretAccessKey] = useState("");
  const [r2Bucket, setR2Bucket] = useState("");

  // Google Drive
  const [gdClientId, setGdClientId] = useState("");
  const [gdClientSecret, setGdClientSecret] = useState("");

  // SMB
  const [smbHost, setSmbHost] = useState("");
  const [smbShare, setSmbShare] = useState("");
  const [smbUser, setSmbUser] = useState("");
  const [smbPassword, setSmbPassword] = useState("");

  const createMutation = useMutation({
    mutationFn: storageApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["storages"] });
      resetForm();
      onSuccess();
    },
    onError: (e) => {
      setError(String(e));
    },
  });

  function resetForm() {
    setName("");
    setIcon("");
    setStorageType("local");
    setLocalPath("");
    setSshHostId("");
    setSshRootPath("/root");
    setR2AccountId("");
    setR2AccessKeyId("");
    setR2SecretAccessKey("");
    setR2Bucket("");
    setGdClientId("");
    setGdClientSecret("");
    setSmbHost("");
    setSmbShare("");
    setSmbUser("");
    setSmbPassword("");
    setReadonly(false);
    setError(null);
  }

  // Handle modal close - reset form when closing
  const handleOpenChange = (open: boolean) => {
    if (!open) {
      resetForm();
    }
    onOpenChange(open);
  };

  function buildBackend(): StorageBackend | null {
    switch (storageType) {
      case "local":
        if (!localPath) return null;
        return { type: "local", root_path: localPath };
      case "ssh_remote":
        if (!sshHostId) return null;
        return { type: "ssh_remote", host_id: sshHostId, root_path: sshRootPath };
      case "cloudflare_r2":
        if (!r2AccountId || !r2AccessKeyId || !r2SecretAccessKey || !r2Bucket) return null;
        return {
          type: "cloudflare_r2",
          account_id: r2AccountId,
          access_key_id: r2AccessKeyId,
          secret_access_key: r2SecretAccessKey,
          bucket: r2Bucket,
        };
      case "google_drive":
        return {
          type: "google_drive",
          client_id: gdClientId || null,
          client_secret: gdClientSecret || null,
          token: null,
          root_folder_id: null,
        };
      case "smb":
        if (!smbHost) return null;
        return {
          type: "smb",
          host: smbHost,
          share: smbShare,
          user: smbUser || null,
          password: smbPassword || null,
          domain: null,
        };
      default:
        return null;
    }
  }

  function handleCreate() {
    setError(null);
    if (!name.trim()) {
      setError("Name is required");
      return;
    }
    const backend = buildBackend();
    if (!backend) {
      setError("Please fill in all required fields");
      return;
    }

    const input: StorageCreateInput = {
      name: name.trim(),
      icon: icon.trim() || null,
      backend,
      readonly,
    };

    createMutation.mutate(input);
  }

  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Add Storage</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="storage-name">Name *</Label>
            <Input
              id="storage-name"
              placeholder="My Storage"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          <IconPicker value={icon} onChange={setIcon} />

          <Separator />

          <Tabs value={storageType} onValueChange={setStorageType}>
            <TabsList className="grid w-full grid-cols-5">
              <TabsTrigger value="local">💻 Local</TabsTrigger>
              <TabsTrigger value="ssh_remote">
                <span className="flex items-center gap-1">
                  <AppIcon name="ssh" className="w-3 h-3" alt="" />
                  SSH
                </span>
              </TabsTrigger>
              <TabsTrigger value="cloudflare_r2">
                <span className="flex items-center gap-1">
                  <AppIcon name="cloudflare" className="w-3 h-3" alt="" />
                  R2
                </span>
              </TabsTrigger>
              <TabsTrigger value="google_drive">
                <span className="flex items-center gap-1">
                  <AppIcon name="googledrive" className="w-3 h-3" alt="" />
                  Drive
                </span>
              </TabsTrigger>
              <TabsTrigger value="smb">
                <span className="flex items-center gap-1">
                  <AppIcon name="smb" className="w-3 h-3" alt="" />
                  SMB
                </span>
              </TabsTrigger>
            </TabsList>

            <TabsContent value="local" className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="local-path">Root Path *</Label>
                <Input
                  id="local-path"
                  placeholder="/Users/me/Projects"
                  value={localPath}
                  onChange={(e) => setLocalPath(e.target.value)}
                />
                <p className="text-sm text-muted-foreground">Absolute path to local directory</p>
              </div>
            </TabsContent>

            <TabsContent value="ssh_remote" className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="ssh-host">Host *</Label>
                <Select value={sshHostId} onValueChange={setSshHostId}>
                  <SelectTrigger id="ssh-host">
                    <SelectValue placeholder="Select a host" />
                  </SelectTrigger>
                  <SelectContent>
                    {(hosts.data ?? []).map((host) => (
                      <SelectItem key={host.id} value={host.id}>
                        {host.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="ssh-root-path">Root Path</Label>
                <Input
                  id="ssh-root-path"
                  placeholder="/root"
                  value={sshRootPath}
                  onChange={(e) => setSshRootPath(e.target.value)}
                />
                <p className="text-sm text-muted-foreground">Path on remote host</p>
              </div>
            </TabsContent>

            <TabsContent value="cloudflare_r2" className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="r2-account-id">Account ID *</Label>
                <Input
                  id="r2-account-id"
                  placeholder="Your Cloudflare account ID"
                  value={r2AccountId}
                  onChange={(e) => setR2AccountId(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="r2-bucket">Bucket *</Label>
                <Input
                  id="r2-bucket"
                  placeholder="my-bucket"
                  value={r2Bucket}
                  onChange={(e) => setR2Bucket(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="r2-access-key">Access Key ID *</Label>
                <Input
                  id="r2-access-key"
                  value={r2AccessKeyId}
                  onChange={(e) => setR2AccessKeyId(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="r2-secret-key">Secret Access Key *</Label>
                <Input
                  id="r2-secret-key"
                  type="password"
                  value={r2SecretAccessKey}
                  onChange={(e) => setR2SecretAccessKey(e.target.value)}
                />
              </div>
            </TabsContent>

            <TabsContent value="google_drive" className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Google Drive uses OAuth and requires browser authorization.
              </p>
              <Card className="bg-primary/5 border-primary/20">
                <CardContent className="text-center py-6">
                  <span className="text-4xl mb-3 block">🔐</span>
                  <p className="font-medium mb-2">OAuth Setup</p>
                  <p className="text-sm text-muted-foreground mb-4">
                    Follow the wizard to authorize access.
                  </p>
                  <Button
                    onClick={() => {
                      onOpenChange(false);
                      setShowGDriveWizard(true);
                    }}
                  >
                    Open Setup Wizard
                  </Button>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="smb" className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="smb-host">Host *</Label>
                  <Input
                    id="smb-host"
                    placeholder="192.168.1.100"
                    value={smbHost}
                    onChange={(e) => setSmbHost(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="smb-share">Share</Label>
                  <Input
                    id="smb-share"
                    placeholder="shared"
                    value={smbShare}
                    onChange={(e) => setSmbShare(e.target.value)}
                  />
                  <p className="text-sm text-muted-foreground">Leave empty to browse all shares</p>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="smb-user">Username (optional)</Label>
                  <Input
                    id="smb-user"
                    value={smbUser}
                    onChange={(e) => setSmbUser(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="smb-password">Password (optional)</Label>
                  <Input
                    id="smb-password"
                    type="password"
                    value={smbPassword}
                    onChange={(e) => setSmbPassword(e.target.value)}
                  />
                </div>
              </div>
            </TabsContent>
          </Tabs>

          <Separator />

          <div className="flex items-center gap-4">
            <Switch
              id="readonly-switch"
              checked={readonly}
              onCheckedChange={setReadonly}
            />
            <Label htmlFor="readonly-switch" className="cursor-pointer">
              Read-only
            </Label>
            <span className="text-xs text-muted-foreground">
              Prevent write operations to this storage
            </span>
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleCreate}
            disabled={createMutation.isPending || storageType === "google_drive"}
          >
            {createMutation.isPending && (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            )}
            {createMutation.isPending ? "Adding..." : "Add Storage"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ============================================================
// Icon Picker
// ============================================================

const STORAGE_ICONS = [
  { emoji: "💻", label: "Computer" },
  { emoji: "🖥️", label: "Desktop" },
  { emoji: "📁", label: "Folder" },
  { emoji: "📂", label: "Open Folder" },
  { emoji: "☁️", label: "Cloud" },
  { emoji: "🌐", label: "Globe" },
  { emoji: "🗄️", label: "Cabinet" },
  { emoji: "💾", label: "Floppy" },
  { emoji: "🔌", label: "Plug" },
  { emoji: "🖧", label: "Network" },
  { emoji: "📦", label: "Package" },
  { emoji: "🗃️", label: "Card Box" },
  { emoji: "💿", label: "CD" },
  { emoji: "📀", label: "DVD" },
  { emoji: "🎞️", label: "Film" },
  { emoji: "🔒", label: "Lock" },
  { emoji: "🔐", label: "Key Lock" },
  { emoji: "⚡", label: "Lightning" },
  { emoji: "🚀", label: "Rocket" },
  { emoji: "🏠", label: "Home" },
  { emoji: "🏢", label: "Office" },
  { emoji: "🔧", label: "Wrench" },
  { emoji: "⚙️", label: "Gear" },
  { emoji: "🎯", label: "Target" },
];

function IconPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (icon: string) => void;
}) {
  return (
    <div className="space-y-2">
      <Label>Icon</Label>
      <div className="flex flex-wrap gap-1 p-2 bg-muted rounded-lg max-h-32 overflow-auto">
        {STORAGE_ICONS.map(({ emoji, label }) => (
          <Button
            key={emoji}
            type="button"
            variant="ghost"
            size="icon"
            title={label}
            onClick={() => onChange(emoji)}
            className={cn(
              "h-8 w-8 p-0 text-lg rounded-md transition-all hover:bg-muted-foreground/10",
              value === emoji && "bg-primary/20 ring-2 ring-primary"
            )}
          >
            {emoji}
          </Button>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <Input
          placeholder="Custom emoji..."
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="flex-1"
        />
        {value && (
          <span className="text-xl">{value}</span>
        )}
      </div>
    </div>
  );
}

// ============================================================
// Edit Storage Modal
// ============================================================

function EditStorageModal({
  storage,
  isOpen,
  onOpenChange,
  onSuccess,
}: {
  storage: Storage;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
}) {
  const queryClient = useQueryClient();
  const hosts = useHosts();

  // Basic info
  const [name, setName] = useState(storage.name);
  const [icon, setIcon] = useState(storage.icon || "");
  const [readonly, setReadonly] = useState(storage.readonly);
  const [error, setError] = useState<string | null>(null);

  // Get the current storage type
  const storageType = storage.backend.type;

  // Local backend
  const [localPath, setLocalPath] = useState(
    storage.backend.type === "local" ? storage.backend.root_path : ""
  );

  // SSH Remote backend
  const [sshHostId, setSshHostId] = useState(
    storage.backend.type === "ssh_remote" ? storage.backend.host_id : ""
  );
  const [sshRootPath, setSshRootPath] = useState(
    storage.backend.type === "ssh_remote" ? storage.backend.root_path : "/root"
  );

  // Cloudflare R2 backend
  const [r2AccountId, setR2AccountId] = useState(
    storage.backend.type === "cloudflare_r2" ? storage.backend.account_id : ""
  );
  const [r2AccessKeyId, setR2AccessKeyId] = useState(
    storage.backend.type === "cloudflare_r2" ? storage.backend.access_key_id : ""
  );
  const [r2SecretAccessKey, setR2SecretAccessKey] = useState(
    storage.backend.type === "cloudflare_r2" ? storage.backend.secret_access_key : ""
  );
  const [r2Bucket, setR2Bucket] = useState(
    storage.backend.type === "cloudflare_r2" ? storage.backend.bucket : ""
  );

  // Google Drive
  const [gdClientId, setGdClientId] = useState(
    storage.backend.type === "google_drive" ? (storage.backend.client_id || "") : ""
  );
  const [gdClientSecret, setGdClientSecret] = useState(
    storage.backend.type === "google_drive" ? (storage.backend.client_secret || "") : ""
  );
  // Preserve existing token and root_folder_id when editing
  const existingGdToken = storage.backend.type === "google_drive" ? storage.backend.token : null;
  const existingGdRootFolderId = storage.backend.type === "google_drive" ? storage.backend.root_folder_id : null;

  // SMB
  const [smbHost, setSmbHost] = useState(
    storage.backend.type === "smb" ? storage.backend.host : ""
  );
  const [smbShare, setSmbShare] = useState(
    storage.backend.type === "smb" ? storage.backend.share : ""
  );
  const [smbUser, setSmbUser] = useState(
    storage.backend.type === "smb" ? (storage.backend.user || "") : ""
  );
  const [smbPassword, setSmbPassword] = useState(
    storage.backend.type === "smb" ? (storage.backend.password || "") : ""
  );

  const updateMutation = useMutation({
    mutationFn: (input: StorageUpdateInput) => storageApi.update(storage.id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["storages"] });
      onSuccess();
    },
    onError: (e) => {
      setError(String(e));
    },
  });

  function buildBackend(): StorageBackend | null {
    switch (storageType) {
      case "local":
        if (!localPath) return null;
        return { type: "local", root_path: localPath };
      case "ssh_remote":
        if (!sshHostId) return null;
        return { type: "ssh_remote", host_id: sshHostId, root_path: sshRootPath };
      case "cloudflare_r2":
        if (!r2AccountId || !r2AccessKeyId || !r2SecretAccessKey || !r2Bucket) return null;
        return {
          type: "cloudflare_r2",
          account_id: r2AccountId,
          access_key_id: r2AccessKeyId,
          secret_access_key: r2SecretAccessKey,
          bucket: r2Bucket,
        };
      case "google_drive":
        return {
          type: "google_drive",
          client_id: gdClientId || null,
          client_secret: gdClientSecret || null,
          token: existingGdToken,  // Preserve existing OAuth token
          root_folder_id: existingGdRootFolderId,  // Preserve existing root folder
        };
      case "smb":
        if (!smbHost) return null;
        return {
          type: "smb",
          host: smbHost,
          share: smbShare,
          user: smbUser || null,
          password: smbPassword || null,
          domain: null,
        };
      default:
        return null;
    }
  }

  function handleUpdate() {
    setError(null);
    if (!name.trim()) {
      setError("Name is required");
      return;
    }

    const backend = buildBackend();
    if (!backend) {
      setError("Please fill in all required fields");
      return;
    }

    const input: StorageUpdateInput = {
      name: name.trim(),
      icon: icon.trim() || null,
      readonly,
      backend,
    };

    updateMutation.mutate(input);
  }

  function renderBackendFields() {
    switch (storageType) {
      case "local":
        return (
          <div className="space-y-2">
            <Label htmlFor="edit-local-path">Root Path *</Label>
            <Input
              id="edit-local-path"
              placeholder="/Users/me/Projects"
              value={localPath}
              onChange={(e) => setLocalPath(e.target.value)}
            />
            <p className="text-sm text-muted-foreground">Absolute path to local directory</p>
          </div>
        );
      case "ssh_remote":
        return (
          <>
            <div className="space-y-2">
              <Label htmlFor="edit-ssh-host">Host *</Label>
              <Select value={sshHostId} onValueChange={setSshHostId}>
                <SelectTrigger id="edit-ssh-host">
                  <SelectValue placeholder="Select a host" />
                </SelectTrigger>
                <SelectContent>
                  {(hosts.data ?? []).map((host) => (
                    <SelectItem key={host.id} value={host.id}>
                      {host.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-ssh-root-path">Root Path</Label>
              <Input
                id="edit-ssh-root-path"
                placeholder="/root"
                value={sshRootPath}
                onChange={(e) => setSshRootPath(e.target.value)}
              />
              <p className="text-sm text-muted-foreground">Path on remote host</p>
            </div>
          </>
        );
      case "cloudflare_r2":
        return (
          <>
            <div className="space-y-2">
              <Label htmlFor="edit-r2-account-id">Account ID *</Label>
              <Input
                id="edit-r2-account-id"
                placeholder="Your Cloudflare account ID"
                value={r2AccountId}
                onChange={(e) => setR2AccountId(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-r2-bucket">Bucket *</Label>
              <Input
                id="edit-r2-bucket"
                placeholder="my-bucket"
                value={r2Bucket}
                onChange={(e) => setR2Bucket(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-r2-access-key">Access Key ID *</Label>
              <Input
                id="edit-r2-access-key"
                value={r2AccessKeyId}
                onChange={(e) => setR2AccessKeyId(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-r2-secret-key">Secret Access Key *</Label>
              <Input
                id="edit-r2-secret-key"
                type="password"
                value={r2SecretAccessKey}
                onChange={(e) => setR2SecretAccessKey(e.target.value)}
              />
            </div>
          </>
        );
      case "google_drive":
        return (
          <>
            <p className="text-sm text-muted-foreground">
              Google Drive requires OAuth authentication. Leave Client ID/Secret empty to use rclone's defaults.
            </p>
            <div className="space-y-2">
              <Label htmlFor="edit-gd-client-id">Client ID (optional)</Label>
              <Input
                id="edit-gd-client-id"
                value={gdClientId}
                onChange={(e) => setGdClientId(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-gd-client-secret">Client Secret (optional)</Label>
              <Input
                id="edit-gd-client-secret"
                type="password"
                value={gdClientSecret}
                onChange={(e) => setGdClientSecret(e.target.value)}
              />
            </div>
          </>
        );
      case "smb":
        return (
          <>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="edit-smb-host">Host *</Label>
                <Input
                  id="edit-smb-host"
                  placeholder="192.168.1.100"
                  value={smbHost}
                  onChange={(e) => setSmbHost(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="edit-smb-share">Share</Label>
                <Input
                  id="edit-smb-share"
                  placeholder="shared"
                  value={smbShare}
                  onChange={(e) => setSmbShare(e.target.value)}
                />
                <p className="text-sm text-muted-foreground">Leave empty to browse all shares</p>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="edit-smb-user">Username (optional)</Label>
                <Input
                  id="edit-smb-user"
                  value={smbUser}
                  onChange={(e) => setSmbUser(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="edit-smb-password">Password (optional)</Label>
                <Input
                  id="edit-smb-password"
                  type="password"
                  value={smbPassword}
                  onChange={(e) => setSmbPassword(e.target.value)}
                />
              </div>
            </div>
          </>
        );
      default:
        return <p className="text-sm text-muted-foreground">Unknown storage type</p>;
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Edit Storage</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          {/* Basic Info */}
          <div className="space-y-2">
            <Label htmlFor="edit-storage-name">Name *</Label>
            <Input
              id="edit-storage-name"
              placeholder="My Storage"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          <IconPicker value={icon} onChange={setIcon} />

          <Separator />

          {/* Backend Type Display */}
          <div className="flex items-center gap-2 p-3 bg-muted rounded-lg">
            {getBackendIconNode(storage.backend)}
            <div>
              <p className="font-medium">{getBackendTypeName(storage.backend)}</p>
              <p className="text-xs text-muted-foreground">Storage type cannot be changed</p>
            </div>
          </div>

          {/* Backend Settings */}
          <div className="space-y-4">
            <h4 className="text-sm font-medium text-muted-foreground">Backend Settings</h4>
            {renderBackendFields()}
          </div>

          <Separator />

          {/* Options */}
          <div className="flex items-center gap-4">
            <Switch
              id="edit-readonly-switch"
              checked={readonly}
              onCheckedChange={setReadonly}
            />
            <Label htmlFor="edit-readonly-switch" className="cursor-pointer">
              Read-only
            </Label>
            <span className="text-xs text-muted-foreground">
              Prevent write operations to this storage
            </span>
          </div>

          {error && <p className="text-sm text-destructive whitespace-pre-wrap">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleUpdate}
            disabled={updateMutation.isPending}
          >
            {updateMutation.isPending && (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            )}
            {updateMutation.isPending ? "Saving..." : "Save Changes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ============================================================
// Main Page Component
// ============================================================

export function StoragePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const storagesQuery = useStorages();
  const hostsQuery = useHosts();
  const pricingQuery = usePricingSettings();
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingStorage, setEditingStorage] = useState<Storage | null>(null);

  // Google Drive wizard state
  const [showGDriveWizard, setShowGDriveWizard] = useState(false);

  // Storage usage state with backend cache persistence
  const [storageUsages, setStorageUsages] = useState<Map<string, StorageUsage>>(new Map());
  const [usageLoading, setUsageLoading] = useState(false);

  // Load cached R2 usages from backend on mount
  useEffect(() => {
    pricingApi.r2Cache.get().then((cached) => {
      if (cached.length > 0) {
        const map = new Map<string, StorageUsage>();
        for (const usage of cached) {
          map.set(usage.storage_id, usage);
        }
        setStorageUsages(map);
      }
    }).catch((e) => {
      console.error("Failed to load R2 usages from cache:", e);
    });
  }, []);

  const deleteMutation = useMutation({
    mutationFn: storageApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["storages"] });
    },
  });

  // Fetch usages for all storages that support it (R2, SMB, SSH)
  const fetchStorageUsages = async () => {
    const currentStorages = storagesQuery.data ?? [];
    if (currentStorages.length === 0) return;

    setUsageLoading(true);
    try {
      // Fetch R2 usages (batch)
      const r2Usages = await storageApi.getR2Usages();
      const usageMap = new Map<string, StorageUsage>();
      for (const usage of r2Usages) {
        usageMap.set(usage.storage_id, usage);
      }

      // Fetch SMB/SSH usages individually (with timeout)
      const smbSshStorages = currentStorages.filter(
        (s) => s.backend.type === "smb" || s.backend.type === "ssh_remote"
      );

      await Promise.all(
        smbSshStorages.map(async (storage) => {
          try {
            // Add timeout for slow connections
            const timeoutPromise = new Promise<null>((_, reject) =>
              setTimeout(() => reject(new Error("Timeout")), 10000)
            );
            const usage = await Promise.race([
              storageApi.getUsage(storage.id),
              timeoutPromise
            ]) as StorageUsage | null;

            if (usage && usage.total_bytes != null) {
              usageMap.set(storage.id, usage);
            }
          } catch (e) {
            console.error(`Failed to get usage for ${storage.name}:`, e);
          }
        })
      );

      setStorageUsages(usageMap);
      // Save ALL usages to backend cache
      await pricingApi.r2Cache.save(Array.from(usageMap.values()));
    } catch (e) {
      console.error("Failed to fetch storage usages:", e);
    } finally {
      setUsageLoading(false);
    }
  };

  function handleEdit(storage: Storage) {
    setEditingStorage(storage);
    setEditModalOpen(true);
  }

  async function handleRefresh() {
    await storagesQuery.refetch();
    // Also refresh storage usages
    fetchStorageUsages();
  }

  const storages = storagesQuery.data ?? [];
  const hosts = hostsQuery.data ?? [];

  const displayCurrency = pricingQuery.data?.display_currency ?? "USD";
  const exchangeRates = pricingQuery.data?.exchange_rates;
  const formatUsd = (value: number, decimals = 2) =>
    formatPriceWithRates(value, "USD", displayCurrency, exchangeRates, decimals);

  const [searchQuery, setSearchQuery] = useState("");
  const [selectedStorageId, setSelectedStorageId] = useState<string | null>(null);
  const [filterType, setFilterType] = useState<"all" | StorageBackend["type"]>("all");
  const [sortBy, setSortBy] = useState<"name" | "recent">("name");

  function getFilterLabel(key: "all" | StorageBackend["type"]): string {
    switch (key) {
      case "all":
        return "Filter";
      case "local":
        return "Local";
      case "ssh_remote":
        return "SSH Remote";
      case "smb":
        return "SMB/NAS";
      case "google_drive":
        return "Google Drive";
      case "cloudflare_r2":
        return "Cloudflare R2";
      case "google_cloud_storage":
        return "Google Cloud Storage";
      default:
        return String(key);
    }
  }

  const filteredStorages = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    let list = storages;

    if (q) {
      list = list.filter((s) => {
        const description = getBackendDescription(s.backend, hosts);
        const haystack = `${s.name} ${description} ${getBackendTypeName(s.backend)}`.toLowerCase();
        return haystack.includes(q);
      });
    }

    if (filterType !== "all") {
      list = list.filter((s) => s.backend.type === filterType);
    }

    const sorted = [...list];
    sorted.sort((a, b) => {
      if (sortBy === "recent") {
        const at = a.last_accessed_at ? new Date(a.last_accessed_at).getTime() : 0;
        const bt = b.last_accessed_at ? new Date(b.last_accessed_at).getTime() : 0;
        return bt - at || a.name.localeCompare(b.name);
      }
      return a.name.localeCompare(b.name);
    });
    return sorted;
  }, [filterType, hosts, searchQuery, sortBy, storages]);

  const visibleStorageIdSet = useMemo(
    () => new Set(filteredStorages.map((s) => s.id)),
    [filteredStorages]
  );

  useEffect(() => {
    if (!selectedStorageId) return;
    if (!visibleStorageIdSet.has(selectedStorageId)) {
      setSelectedStorageId(null);
    }
  }, [selectedStorageId, visibleStorageIdSet]);

  const localStorages = useMemo(() => filteredStorages.filter((s) => s.backend.type === "local"), [filteredStorages]);
  const sshRemoteStorages = useMemo(() => filteredStorages.filter((s) => s.backend.type === "ssh_remote"), [filteredStorages]);
  const smbStorages = useMemo(() => filteredStorages.filter((s) => s.backend.type === "smb"), [filteredStorages]);
  const googleDriveStorages = useMemo(() => filteredStorages.filter((s) => s.backend.type === "google_drive"), [filteredStorages]);
  const cloudflareR2Storages = useMemo(() => filteredStorages.filter((s) => s.backend.type === "cloudflare_r2"), [filteredStorages]);
  const googleCloudStorageStorages = useMemo(
    () => filteredStorages.filter((s) => s.backend.type === "google_cloud_storage"),
    [filteredStorages]
  );

  const selectedStorage = selectedStorageId
    ? filteredStorages.find((s) => s.id === selectedStorageId) ?? null
    : null;
  const canBrowseSelected = Boolean(selectedStorage);
  const isLoading = storagesQuery.isLoading || hostsQuery.isLoading;

  function openBrowse(storage: Storage) {
    navigate({ to: "/storage/$id", params: { id: storage.id } });
  }

  function buildRightTags(storage: Storage): { label: string; variant?: "default" | "primary" | "warning" }[] {
    const tags: { label: string; variant?: "default" | "primary" | "warning" }[] = [];

    if (storage.readonly) {
      tags.push({ label: "Read-only", variant: "warning" });
    }

    const usage = storageUsages.get(storage.id);
    const supportsUsage =
      storage.backend.type === "cloudflare_r2" ||
      storage.backend.type === "smb" ||
      storage.backend.type === "ssh_remote";

    if (supportsUsage) {
      if (usageLoading && !usage) {
        tags.push({ label: "...", variant: "default" });
      } else if (usage) {
        if (storage.backend.type === "cloudflare_r2") {
          tags.push({ label: formatStorageSize(usage.used_gb), variant: "primary" });
        } else if ((storage.backend.type === "smb" || storage.backend.type === "ssh_remote") && usage.total_gb != null) {
          tags.push({
            label: `${formatStorageSize(usage.used_gb, 1)} / ${formatStorageSize(usage.total_gb, 1)}`,
            variant: "primary",
          });
        }
      }
    }

    if (storage.backend.type === "cloudflare_r2" && usage) {
      const r2MonthlyCost = calculateR2BucketCost(usage.used_gb);
      tags.push({ label: `${formatUsd(r2MonthlyCost)}/mo`, variant: "warning" });
    }

    return tags;
  }

  function renderStorageRow(storage: Storage) {
    const rightTags = buildRightTags(storage);
    return (
      <HostRow
        key={storage.id}
        icon={getBackendIconNode(storage.backend, storage.icon)}
        title={storage.name}
        subtitle={getBackendDescription(storage.backend, hosts)}
        rightTags={rightTags}
        isSelected={selectedStorageId === storage.id}
        onClick={() => setSelectedStorageId(storage.id)}
        onDoubleClick={() => openBrowse(storage)}
        hoverActions={
          <TooltipProvider>
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
                    onClick={() => openBrowse(storage)}
                  >
                    <FolderOpen className="w-4 h-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Browse</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="w-7 h-7 opacity-60 hover:opacity-100"
                    onClick={() => handleEdit(storage)}
                  >
                    <Pencil className="w-4 h-4" />
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
                    <MoreVertical className="w-4 h-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    className="text-destructive focus:text-destructive"
                    onClick={() => {
                      deleteMutation.mutate(storage.id);
                      setSelectedStorageId((prev) => (prev === storage.id ? null : prev));
                    }}
                  >
                    <Trash2 className="w-4 h-4 mr-2" />
                    Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </TooltipProvider>
        }
      />
    );
  }

  function renderStorageSection(title: string, sectionStorages: Storage[]) {
    if (sectionStorages.length === 0) return null;
    return (
      <HostSection title={title} count={sectionStorages.length}>
        {sectionStorages.map((storage) => renderStorageRow(storage))}
      </HostSection>
    );
  }

  return (
    <div className="doppio-page">
      <div className="doppio-page-content">
        {/* Termius-style Toolbar */}
        <div className="termius-toolbar">
          {/* Row 1: Search + Browse */}
          <div className="termius-toolbar-row">
            <div className="termius-search-bar">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
                <Input
                  className="h-12 pl-10 pr-24 text-base bg-muted"
                  placeholder="Search storages..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
                <div className="absolute right-2 top-1/2 -translate-y-1/2">
                  <Button
                    size="sm"
                    className="h-8 px-4"
                    onClick={() => {
                      if (!selectedStorage) return;
                      openBrowse(selectedStorage);
                    }}
                    disabled={!canBrowseSelected}
                  >
                    Browse
                  </Button>
                </div>
              </div>
            </div>
          </div>

          {/* Row 2: Quick Actions + Filters */}
          <div className="termius-toolbar-row justify-between">
            <div className="termius-quick-actions">
              <Button type="button" variant="outline" size="sm" onClick={() => setAddModalOpen(true)}>
                <Plus className="w-4 h-4" />
                <span>New Storage</span>
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void handleRefresh()}
                disabled={storagesQuery.isFetching || usageLoading}
              >
                <RefreshCw className="w-4 h-4" />
                <span>Refresh</span>
              </Button>
            </div>

            <div className="flex items-center gap-1">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button type="button" variant="outline" size="sm">
                    <Filter className="w-4 h-4" />
                    <span>{getFilterLabel(filterType)}</span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                  <DropdownMenuItem onClick={() => setFilterType("all")}>All</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setFilterType("local")}>Local</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setFilterType("ssh_remote")}>SSH Remote</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setFilterType("smb")}>SMB/NAS</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setFilterType("google_drive")}>Google Drive</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setFilterType("cloudflare_r2")}>Cloudflare R2</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setFilterType("google_cloud_storage")}>Google Cloud Storage</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button type="button" variant="outline" size="sm">
                    <ArrowUpDown className="w-4 h-4" />
                    <span>{sortBy === "name" ? "Name" : "Recent"}</span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                  <DropdownMenuItem onClick={() => setSortBy("name")}>Name</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setSortBy("recent")}>Recent</DropdownMenuItem>
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
        ) : filteredStorages.length === 0 ? (
          <EmptyHostState
            icon={<span className="text-lg">🗄️</span>}
            title={searchQuery ? "No storages match your search" : "No storages yet"}
            description={searchQuery ? undefined : "Add a storage location to get started."}
            action={
              !searchQuery ? (
                <Button size="sm" onClick={() => setAddModalOpen(true)}>
                  New Storage
                </Button>
              ) : undefined
            }
          />
        ) : (
          <>
            {renderStorageSection("LOCAL", localStorages)}
            {renderStorageSection("SSH REMOTE", sshRemoteStorages)}
            {renderStorageSection("SMB/NAS", smbStorages)}
            {renderStorageSection("GOOGLE DRIVE", googleDriveStorages)}
            {renderStorageSection("CLOUDFLARE R2", cloudflareR2Storages)}
            {renderStorageSection("GOOGLE CLOUD STORAGE", googleCloudStorageStorages)}
          </>
        )}

        {/* Add Storage Modal */}
        <AddStorageModal
          isOpen={addModalOpen}
          onOpenChange={setAddModalOpen}
          onSuccess={() => setAddModalOpen(false)}
          setShowGDriveWizard={setShowGDriveWizard}
        />

        {/* Google Drive OAuth Wizard */}
        <GoogleDriveWizard
          isOpen={showGDriveWizard}
          onOpenChange={setShowGDriveWizard}
          onSuccess={() => {
            queryClient.invalidateQueries({ queryKey: ["storages"] });
          }}
        />

        {/* Edit Storage Modal */}
        {editingStorage && (
          <EditStorageModal
            storage={editingStorage}
            isOpen={editModalOpen}
            onOpenChange={(open) => {
              setEditModalOpen(open);
              if (!open) {
                setEditingStorage(null);
              }
            }}
            onSuccess={() => {
              setEditModalOpen(false);
              setEditingStorage(null);
            }}
          />
        )}
      </div>
    </div>
  );
}

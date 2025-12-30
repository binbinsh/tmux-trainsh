import {
  Card,
  CardBody,
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
  Select,
  SelectItem,
  Spinner,
  Switch,
  Tab,
  Tabs,
  useDisclosure,
} from "@nextui-org/react";
import { Button } from "../components/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { motion, AnimatePresence } from "framer-motion";
import { useState, useEffect, type ReactNode } from "react";
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
import { PageLayout, PageSection } from "../components/shared/PageLayout";
import { StatsCard } from "../components/shared/StatsCard";
import { UnifiedCard, EmptyState, type CardAction, type CardBadge, type CardButton } from "../components/shared/UnifiedCard";

// ============================================================
// Icons
// ============================================================

function IconPlus() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
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

function IconEllipsis() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 12.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 18.75a.75.75 0 110-1.5.75.75 0 010 1.5z" />
    </svg>
  );
}

function IconCheck() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
    </svg>
  );
}

function IconX() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
    </svg>
  );
}

// ============================================================
// Helper Functions
// ============================================================

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
    case "google_drive": return "Google Drive";
    case "cloudflare_r2": return `Bucket: ${backend.bucket}`;
    case "google_cloud_storage": return `Bucket: ${backend.bucket}`;
    case "smb": return backend.share ? `//${backend.host}/${backend.share}` : `//${backend.host}`;
    default: return "";
  }
}

// ============================================================
// Storage Card Component
// ============================================================

function StorageCard({
  storage,
  hosts,
  onDelete,
  onEdit,
  usage,
  usageLoading,
}: {
  storage: Storage;
  hosts: Host[];
  onDelete: () => void;
  onEdit: () => void;
  usage?: StorageUsage | null;
  usageLoading?: boolean;
}) {
  const navigate = useNavigate();
  const pricingQuery = usePricingSettings();
  const displayCurrency = pricingQuery.data?.display_currency ?? "USD";
  const exchangeRates = pricingQuery.data?.exchange_rates;
  const formatUsd = (value: number, decimals = 2) =>
    formatPriceWithRates(value, "USD", displayCurrency, exchangeRates, decimals);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [testing, setTesting] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Calculate R2 monthly cost (per bucket, no free tier deduction)
  const isR2 = storage.backend.type === "cloudflare_r2";
  const isSmbOrSsh = storage.backend.type === "smb" || storage.backend.type === "ssh_remote";
  const r2MonthlyCost = usage && isR2 ? calculateR2BucketCost(usage.used_gb) : null;

  const openBrowse = () => {
    navigate({ to: "/storage/$id", params: { id: storage.id } });
  };

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await storageApi.test(storage.id);
      let message = result.message;
      if (!result.success && message.includes("{")) {
        try {
          const jsonMatch = message.match(/\{[\s\S]*\}/);
          if (jsonMatch) {
            const parsed = JSON.parse(jsonMatch[0]);
            message = parsed.error || parsed.message || message;
          }
        } catch {
          // Keep original message
        }
      }
      setTestResult({ success: result.success, message });
    } catch (e) {
      const errStr = String(e);
      let message = errStr;
      if (errStr.includes("message")) {
        try {
          const parsed = JSON.parse(errStr);
          message = parsed.message || errStr;
        } catch {
          // Keep original
        }
      }
      setTestResult({ success: false, message });
    } finally {
      setTesting(false);
    }
  }

  // Build icon
  const icon = getBackendIconNode(storage.backend, storage.icon);

  // Build type badge
  const typeBadge: CardBadge = {
    label: getBackendTypeName(storage.backend),
  };

  // Build tags
  const tags: CardBadge[] = [];

  if (usageLoading && (isR2 || isSmbOrSsh)) {
    tags.push({ label: "Loading..." });
  } else if (usage) {
    if (isR2) {
      tags.push({ label: `${usage.used_gb.toFixed(2)} GB` });
      if (r2MonthlyCost != null) {
        tags.push({ label: `${formatUsd(r2MonthlyCost, 2)}/mo`, color: "warning" });
      }
    } else if (isSmbOrSsh && usage.total_gb != null) {
      tags.push({ label: `${usage.used_gb.toFixed(1)} / ${usage.total_gb.toFixed(1)} GB` });
    }
  }

  if (storage.readonly) {
    tags.push({ label: "Read-only", color: "warning" });
  }

  // Build actions
  const actions: CardAction[] = [
    { key: "test", label: "Test Connection", onPress: handleTest, isDisabled: testing },
    { key: "edit", label: "Edit", onPress: onEdit },
    { key: "delete", label: "Delete", color: "danger", onPress: () => setShowDeleteConfirm(true) },
  ];

  // Test result display
  const testResultContent = testResult && (
    <div className={`text-xs ${testResult.success ? "text-success" : "text-danger"}`}>
      <div className="flex items-center gap-2">
        {testResult.success ? <IconCheck /> : <IconX />}
        <span>{testResult.success ? "Connected" : "Connection failed"}</span>
      </div>
      {!testResult.success && (
        <pre className="mt-1 p-2 bg-danger/10 rounded text-[10px] whitespace-pre-wrap break-all max-h-24 overflow-auto">
          {testResult.message}
        </pre>
      )}
    </div>
  );

  return (
    <>
      <UnifiedCard
        icon={icon}
        title={storage.name}
        type={typeBadge}
        actions={actions}
        onPress={openBrowse}
        actionGuardAttr="data-storage-card-action"
        subtitle={getBackendDescription(storage.backend, hosts)}
        tags={tags.length > 0 ? tags : undefined}
        footer={storage.last_accessed_at
          ? `Last accessed: ${new Date(storage.last_accessed_at).toLocaleString()}`
          : "Never accessed"}
      >
        {testResultContent}
      </UnifiedCard>

      {/* Delete Confirmation Modal */}
      <Modal isOpen={showDeleteConfirm} onOpenChange={setShowDeleteConfirm} isDismissable={true} size="sm">
        <ModalContent>
          {(onClose) => (
            <>
              <ModalHeader>Delete Storage</ModalHeader>
              <ModalBody>
                <p>
                  Are you sure you want to delete <strong>{storage.name}</strong>?
                </p>
                <p className="text-sm text-foreground/60">
                  This action cannot be undone.
                </p>
              </ModalBody>
              <ModalFooter>
                <Button variant="flat" onPress={onClose}>
                  Cancel
                </Button>
                <Button
                  color="danger"
                  isLoading={deleting}
                  onPress={() => {
                    setDeleting(true);
                    onDelete();
                    setTimeout(() => {
                      setDeleting(false);
                      onClose();
                    }, 100);
                  }}
                >
                  Delete
                </Button>
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>
    </>
  );
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
    <Modal 
      isOpen={isOpen} 
      onOpenChange={handleOpenChange} 
      size="2xl" 
      scrollBehavior="inside"
      isDismissable={true}
      isKeyboardDismissDisabled={false}
    >
      <ModalContent>
        {(onClose) => (
          <>
            <ModalHeader>Add Storage</ModalHeader>
            <ModalBody>
              <div className="space-y-4">
                <Input labelPlacement="inside" label="Name"
                placeholder="My Storage"
                value={name}
                onValueChange={setName}
                isRequired />

                <IconPicker value={icon} onChange={setIcon} />

                <Divider />

                <Tabs selectedKey={storageType} onSelectionChange={(k) => setStorageType(k as string)}>
                  <Tab key="local" title="💻 Local">
                    <div className="pt-4 space-y-4">
                      <Input labelPlacement="inside" label="Root Path"
                      placeholder="/Users/me/Projects"
                      value={localPath}
                      onValueChange={setLocalPath}
                      isRequired
                      description="Absolute path to local directory" />
                    </div>
                  </Tab>

                  <Tab
                    key="ssh_remote"
                    title={(
                      <span className="flex items-center gap-2">
                        <AppIcon name="ssh" className="w-4 h-4" alt="SSH" />
                        SSH Remote
                      </span>
                    )}
                  >
                    <div className="pt-4 space-y-4">
                      <Select labelPlacement="inside" label="Host"
                      placeholder="Select a host"
                      selectedKeys={sshHostId ? [sshHostId] : []}
                      onSelectionChange={(keys) => {
                        const id = Array.from(keys)[0] as string;
                        setSshHostId(id);
                      }}
                      isRequired>{(hosts.data ?? []).map((host) => (
                        <SelectItem key={host.id}>
                          {host.name}
                        </SelectItem>
                      ))}</Select>
                      <Input labelPlacement="inside" label="Root Path"
                      placeholder="/root"
                      value={sshRootPath}
                      onValueChange={setSshRootPath}
                      description="Path on remote host" />
                    </div>
                  </Tab>

                  <Tab
                    key="cloudflare_r2"
                    title={(
                      <span className="flex items-center gap-2">
                        <AppIcon name="cloudflare" className="w-4 h-4" alt="Cloudflare R2" />
                        Cloudflare R2
                      </span>
                    )}
                  >
                    <div className="pt-4 space-y-4">
                      <Input labelPlacement="inside" label="Account ID"
                      placeholder="Your Cloudflare account ID"
                      value={r2AccountId}
                      onValueChange={setR2AccountId}
                      isRequired />
                      <Input labelPlacement="inside" label="Bucket"
                      placeholder="my-bucket"
                      value={r2Bucket}
                      onValueChange={setR2Bucket}
                      isRequired />
                      <Input labelPlacement="inside" label="Access Key ID"
                      value={r2AccessKeyId}
                      onValueChange={setR2AccessKeyId}
                      isRequired />
                      <Input labelPlacement="inside" label="Secret Access Key"
                      type="password"
                      value={r2SecretAccessKey}
                      onValueChange={setR2SecretAccessKey}
                      isRequired />
                    </div>
                  </Tab>

                  <Tab
                    key="google_drive"
                    title={(
                      <span className="flex items-center gap-2">
                        <AppIcon name="googledrive" className="w-4 h-4" alt="Google Drive" />
                        Google Drive
                      </span>
                    )}
                  >
                    <div className="pt-4 space-y-4">
                      <p className="text-sm text-foreground/60">
                        Google Drive uses OAuth and requires browser authorization.
                      </p>
                      <Card className="bg-primary/5 border border-primary/20">
                        <CardBody className="text-center py-6">
                          <span className="text-4xl mb-3 block">🔐</span>
                          <p className="font-medium mb-2">OAuth Setup</p>
                          <p className="text-sm text-foreground/60 mb-4">
                            Follow the wizard to authorize access.
                          </p>
                          <Button
                            color="primary"
                            onPress={() => {
                              onClose();
                              setShowGDriveWizard(true);
                            }}
                          >
                            Open Setup Wizard
                          </Button>
                        </CardBody>
                      </Card>
                    </div>
                  </Tab>

                  <Tab
                    key="smb"
                    title={(
                      <span className="flex items-center gap-2">
                        <AppIcon name="smb" className="w-4 h-4" alt="SMB" />
                        SMB/NAS
                      </span>
                    )}
                  >
                    <div className="pt-4 space-y-4">
                      <div className="grid grid-cols-2 gap-4">
                        <Input labelPlacement="inside" label="Host"
                        placeholder="192.168.1.100"
                        value={smbHost}
                        onValueChange={setSmbHost}
                        isRequired />
                        <Input labelPlacement="inside" label="Share"
                        placeholder="shared"
                        value={smbShare}
                        onValueChange={setSmbShare}
                        description="Leave empty to browse all shares" />
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        <Input labelPlacement="inside" label="Username (optional)"
                        value={smbUser}
                        onValueChange={setSmbUser} />
                        <Input labelPlacement="inside" label="Password (optional)"
                        type="password"
                        value={smbPassword}
                        onValueChange={setSmbPassword} />
                      </div>
                    </div>
                  </Tab>
                </Tabs>

                <Divider />

                <div className="flex items-center gap-4">
                  <Switch size="sm" isSelected={readonly} onValueChange={setReadonly}>
                    Read-only
                  </Switch>
                  <span className="text-xs text-foreground/60">
                    Prevent write operations to this storage
                  </span>
                </div>

                {error && <p className="text-sm text-danger">{error}</p>}
              </div>
            </ModalBody>
            <ModalFooter>
              <Button variant="flat" onPress={onClose}>
                Cancel
              </Button>
              <Button
                color="primary"
                onPress={handleCreate}
                isLoading={createMutation.isPending}
                isDisabled={storageType === "google_drive"}
              >
                Add Storage
              </Button>
            </ModalFooter>
          </>
        )}
      </ModalContent>
    </Modal>
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
      <label className="text-sm text-foreground/70">Icon</label>
      <div className="flex flex-wrap gap-1 p-2 bg-content2 rounded-lg max-h-32 overflow-auto">
        {STORAGE_ICONS.map(({ emoji, label }) => (
          <button
            key={emoji}
            type="button"
            title={label}
            onClick={() => onChange(emoji)}
            className={`p-1.5 text-lg rounded-md transition-all hover:bg-content3 ${
              value === emoji ? "bg-primary/20 ring-2 ring-primary" : ""
            }`}
          >
            {emoji}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <Input labelPlacement="inside" size="sm"
        placeholder="Custom emoji..."
        value={value}
        onValueChange={onChange}
        className="flex-1" />
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
          <Input labelPlacement="inside" label="Root Path"
          placeholder="/Users/me/Projects"
          value={localPath}
          onValueChange={setLocalPath}
          isRequired
          description="Absolute path to local directory" />
        );
      case "ssh_remote":
        return (
          <>
            <Select labelPlacement="inside" label="Host"
            placeholder="Select a host"
            selectedKeys={sshHostId ? [sshHostId] : []}
            onSelectionChange={(keys) => {
              const id = Array.from(keys)[0] as string;
              setSshHostId(id);
            }}
            isRequired>{(hosts.data ?? []).map((host) => (
              <SelectItem key={host.id}>
                {host.name}
              </SelectItem>
            ))}</Select>
            <Input labelPlacement="inside" label="Root Path"
            placeholder="/root"
            value={sshRootPath}
            onValueChange={setSshRootPath}
            description="Path on remote host" />
          </>
        );
      case "cloudflare_r2":
        return (
          <>
            <Input labelPlacement="inside" label="Account ID"
            placeholder="Your Cloudflare account ID"
            value={r2AccountId}
            onValueChange={setR2AccountId}
            isRequired />
            <Input labelPlacement="inside" label="Bucket"
            placeholder="my-bucket"
            value={r2Bucket}
            onValueChange={setR2Bucket}
            isRequired />
            <Input labelPlacement="inside" label="Access Key ID"
            value={r2AccessKeyId}
            onValueChange={setR2AccessKeyId}
            isRequired />
            <Input labelPlacement="inside" label="Secret Access Key"
            type="password"
            value={r2SecretAccessKey}
            onValueChange={setR2SecretAccessKey}
            isRequired />
          </>
        );
      case "google_drive":
        return (
          <>
            <p className="text-sm text-foreground/60">
              Google Drive requires OAuth authentication. Leave Client ID/Secret empty to use rclone's defaults.
            </p>
            <Input labelPlacement="inside" label="Client ID (optional)"
            value={gdClientId}
            onValueChange={setGdClientId} />
            <Input labelPlacement="inside" label="Client Secret (optional)"
            type="password"
            value={gdClientSecret}
            onValueChange={setGdClientSecret} />
          </>
        );
      case "smb":
        return (
          <>
            <div className="grid grid-cols-2 gap-4">
              <Input labelPlacement="inside" label="Host"
              placeholder="192.168.1.100"
              value={smbHost}
              onValueChange={setSmbHost}
              isRequired />
              <Input labelPlacement="inside" label="Share"
              placeholder="shared"
              value={smbShare}
              onValueChange={setSmbShare}
              description="Leave empty to browse all shares" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Input labelPlacement="inside" label="Username (optional)"
              value={smbUser}
              onValueChange={setSmbUser} />
              <Input labelPlacement="inside" label="Password (optional)"
              type="password"
              value={smbPassword}
              onValueChange={setSmbPassword} />
            </div>
          </>
        );
      default:
        return <p className="text-sm text-foreground/60">Unknown storage type</p>;
    }
  }

  return (
    <Modal 
      isOpen={isOpen} 
      onOpenChange={onOpenChange} 
      isDismissable={true} 
      size="2xl"
      scrollBehavior="inside"
    >
      <ModalContent>
        {(onClose) => (
          <>
            <ModalHeader>Edit Storage</ModalHeader>
            <ModalBody>
              <div className="space-y-4">
                {/* Basic Info */}
                <Input labelPlacement="inside" label="Name"
                placeholder="My Storage"
                value={name}
                onValueChange={setName}
                isRequired />

                <IconPicker value={icon} onChange={setIcon} />

                <Divider />

                {/* Backend Type Display */}
                <div className="flex items-center gap-2 p-3 bg-content2 rounded-lg">
                  {getBackendIconNode(storage.backend)}
                  <div>
                    <p className="font-medium">{getBackendTypeName(storage.backend)}</p>
                    <p className="text-xs text-foreground/60">Storage type cannot be changed</p>
                  </div>
                </div>

                {/* Backend Settings */}
                <div className="space-y-4">
                  <h4 className="text-sm font-medium text-foreground/80">Backend Settings</h4>
                  {renderBackendFields()}
                </div>

                <Divider />

                {/* Options */}
                <div className="flex items-center gap-4">
                  <Switch size="sm" isSelected={readonly} onValueChange={setReadonly}>
                    Read-only
                  </Switch>
                  <span className="text-xs text-foreground/60">
                    Prevent write operations to this storage
                  </span>
                </div>

                {error && <p className="text-sm text-danger whitespace-pre-wrap">{error}</p>}
              </div>
            </ModalBody>
            <ModalFooter>
              <Button variant="flat" onPress={onClose}>
                Cancel
              </Button>
              <Button
                color="primary"
                onPress={handleUpdate}
                isLoading={updateMutation.isPending}
              >
                Save Changes
              </Button>
            </ModalFooter>
          </>
        )}
      </ModalContent>
    </Modal>
  );
}

// ============================================================
// Main Page Component
// ============================================================

export function StoragePage() {
  const queryClient = useQueryClient();
  const storagesQuery = useStorages();
  const hostsQuery = useHosts();
  const addModal = useDisclosure();
  const editModal = useDisclosure();
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
    editModal.onOpen();
  }
  
  async function handleRefresh() {
    await storagesQuery.refetch();
    // Also refresh storage usages
    fetchStorageUsages();
  }

  const storages = storagesQuery.data ?? [];
  const hosts = hostsQuery.data ?? [];
  const localCount = storages.filter((s) => s.backend.type === "local").length;
  const remoteCount = storages.filter((s) => s.backend.type === "ssh_remote").length;
  const cloudCount = storages.filter(
    (s) =>
      s.backend.type === "google_drive" ||
      s.backend.type === "cloudflare_r2" ||
      s.backend.type === "google_cloud_storage"
  ).length;

  return (
    <PageLayout
      title="Storage"
      subtitle="Manage local, remote, and cloud storage locations"
      actions={
        <>
          <Button
            variant="flat"
            startContent={<IconRefresh />}
            onPress={handleRefresh}
            isLoading={storagesQuery.isFetching || usageLoading}
          >
            Refresh
          </Button>
          <Button color="primary" startContent={<IconPlus />} onPress={addModal.onOpen}>
            Add Storage
          </Button>
        </>
      }
    >
      {/* Stats */}
      <div className="doppio-stats-grid">
        <StatsCard title="Total Storages" value={storages.length} />
        <StatsCard
          title="Local"
          value={localCount}
          icon={<span className="text-lg">💻</span>}
        />
        <StatsCard
          title="Remote"
          value={remoteCount}
          icon={<AppIcon name="ssh" className="w-5 h-5" alt="SSH" />}
        />
        <StatsCard
          title="Cloud"
          value={cloudCount}
          icon={<AppIcon name="cloudflare" className="w-5 h-5" alt="Cloud" />}
        />
      </div>

      {/* Storage Grid */}
      <PageSection>
        {storagesQuery.isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Spinner size="lg" />
          </div>
        ) : storages.length === 0 ? (
          <EmptyState
            title="No storage locations configured"
            description="Add a storage location to get started"
            action={{
              label: "Add your first storage",
              onPress: addModal.onOpen,
            }}
          />
        ) : (
          <div className="doppio-card-grid">
            <AnimatePresence>
              {storages.map((storage, index) => (
                <motion.div
                  key={storage.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.95 }}
                  transition={{ delay: index * 0.05 }}
                  className="h-full"
                >
                  <StorageCard
                    storage={storage}
                    hosts={hosts}
                    onDelete={() => deleteMutation.mutate(storage.id)}
                    onEdit={() => handleEdit(storage)}
                    usage={storageUsages.get(storage.id)}
                    usageLoading={usageLoading && (storage.backend.type === "cloudflare_r2" || storage.backend.type === "smb" || storage.backend.type === "ssh_remote")}
                  />
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        )}
      </PageSection>

      {/* Add Storage Modal */}
      <AddStorageModal
        isOpen={addModal.isOpen}
        onOpenChange={(open) => {
          if (open) {
            addModal.onOpen();
          } else {
            addModal.onClose();
          }
        }}
        onSuccess={addModal.onClose}
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
          isOpen={editModal.isOpen}
          onOpenChange={(open) => {
            if (open) {
              editModal.onOpen();
            } else {
              editModal.onClose();
              setEditingStorage(null);
            }
          }}
          onSuccess={() => {
            editModal.onClose();
            setEditingStorage(null);
          }}
        />
      )}
    </PageLayout>
  );
}

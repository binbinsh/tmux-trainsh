import {
  Badge,
  Button,
  Card,
  CardContent,
  Checkbox,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  RadioGroup,
  RadioGroupItem,
  ScrollArea,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
  Textarea,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui";
import { Loader2 } from "lucide-react";
import { AppIcon } from "../components/AppIcon";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { motion, Reorder, useDragControls } from "framer-motion";
import { useEffect, useRef, useState, useCallback, type ReactNode } from "react";
import { useDebouncedCallback } from "use-debounce";
import {
  interactiveRecipeApi,
  openInExternalEditor,
  useHosts,
  useRecipe,
  useSaveRecipe,
  useStorages,
  useVastInstances,
  useValidateRecipe,
} from "../lib/tauri-api";
import { useTerminalOptional } from "../contexts/TerminalContext";
import type { Host, Recipe, Step, Storage, TargetHostType, TargetRequirements, ValidationResult } from "../lib/types";
import { vastInstanceToHostCandidate } from "../lib/vast-host";
import { FilePicker, type EndpointType, type SelectedEndpoint } from "../components/FilePicker";
import { cn } from "@/lib/utils";

// Icons
function IconArrowLeft() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
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

function IconPlus() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
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

function IconCheck({ className }: { className?: string }) {
  return (
    <svg className={cn("w-4 h-4", className)} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
    </svg>
  );
}

function IconWarning({ className }: { className?: string }) {
  return (
    <svg className={cn("w-4 h-4", className)} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
    </svg>
  );
}

function IconDrag() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
      <circle cx="9" cy="6" r="1.5" />
      <circle cx="15" cy="6" r="1.5" />
      <circle cx="9" cy="12" r="1.5" />
      <circle cx="15" cy="12" r="1.5" />
      <circle cx="9" cy="18" r="1.5" />
      <circle cx="15" cy="18" r="1.5" />
    </svg>
  );
}

function IconChevronDown() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
    </svg>
  );
}

function IconVariable() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.745 3A23.933 23.933 0 003 12c0 3.183.62 6.22 1.745 9M19.5 3c.967 2.78 1.5 5.817 1.5 9s-.533 6.22-1.5 9M8.25 8.885l1.444-.89a.75.75 0 011.105.402l2.402 7.206a.75.75 0 001.104.401l1.445-.889m-8.25.75l.213.09a1.687 1.687 0 002.062-.617l4.45-6.676a1.688 1.688 0 012.062-.618l.213.09" />
    </svg>
  );
}

function IconTarget() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z" />
    </svg>
  );
}

function IconExternalEditor() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
    </svg>
  );
}

function IconFolderOpen() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 9.776c.112-.017.227-.026.344-.026h15.812c.117 0 .232.009.344.026m-16.5 0a2.25 2.25 0 00-1.883 2.542l.857 6a2.25 2.25 0 002.227 1.932H19.05a2.25 2.25 0 002.227-1.932l.857-6a2.25 2.25 0 00-1.883-2.542m-16.5 0V6A2.25 2.25 0 016 3.75h3.879a1.5 1.5 0 011.06.44l2.122 2.12a1.5 1.5 0 001.06.44H18A2.25 2.25 0 0120.25 9v.776" />
    </svg>
  );
}

// External editor button component
function ExternalEditorButton({ content, onChange }: { content: string; onChange: (value: string) => void }) {
  const [isLoading, setIsLoading] = useState(false);
  
  const handleOpenEditor = async () => {
    setIsLoading(true);
    try {
      const updatedContent = await openInExternalEditor(content, "sh");
      onChange(updatedContent);
    } catch (e) {
      console.error("Failed to open external editor:", e);
    } finally {
      setIsLoading(false);
    }
  };
  
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-2 text-xs gap-1"
          onClick={handleOpenEditor}
          disabled={isLoading}
        >
          {isLoading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <IconExternalEditor />
          )}
          External Editor
        </Button>
      </TooltipTrigger>
      <TooltipContent>Open in external editor ($EDITOR)</TooltipContent>
    </Tooltip>
  );
}

// Operation categories and definitions
type OperationCategory = "commands" | "transfer" | "vastai" | "tmux" | "gdrive" | "git" | "control" | "utility";

type OperationDef = {
  key: string;
  label: string;
  icon: ReactNode;
  category: OperationCategory;
  description: string;
};

const OPERATION_CATEGORIES: Record<OperationCategory, { label: string; color: string; lightColor: string; bgClass: string }> = {
  commands: { label: "Commands", color: "#66D9EF", lightColor: "#E3F9FE", bgClass: "bg-cyan-100" },       // Monokai cyan
  transfer: { label: "Transfer", color: "#A6E22E", lightColor: "#E8F9DC", bgClass: "bg-green-100" },      // Monokai green
  vastai: { label: "Vast.ai", color: "#FD971F", lightColor: "#FEF3E1", bgClass: "bg-orange-100" },        // Monokai param orange
  tmux: { label: "Tmux", color: "#AE81FF", lightColor: "#F0E8FE", bgClass: "bg-purple-100" },             // Monokai purple
  gdrive: { label: "Google Drive", color: "#28C6E4", lightColor: "#E3F5FA", bgClass: "bg-blue-50" },      // Monokai type cyan
  git: { label: "Git & ML", color: "#F25A00", lightColor: "#FEE8DC", bgClass: "bg-orange-100" },          // Monokai string orange
  control: { label: "Control", color: "#F92672", lightColor: "#FEE7F0", bgClass: "bg-pink-100" },         // Monokai keyword pink
  utility: { label: "Utility", color: "#75715E", lightColor: "#F3F2EF", bgClass: "bg-gray-100" },         // Monokai comment
};

const OPERATION_TYPES: OperationDef[] = [
  // Commands
  { key: "run_commands", label: "Run Commands", icon: "💻", category: "commands", description: "Execute commands on target host" },
  // Transfer
  { key: "transfer", label: "Transfer Files", icon: "📦", category: "transfer", description: "Transfer files between hosts/storage" },
  // Vast.ai
  { key: "vast_start", label: "Start Target Host", icon: <AppIcon name="vast" className="w-5 h-5" alt="Vast.ai" />, category: "vastai", description: "Start the target Vast.ai host" },
  { key: "vast_stop", label: "Stop Target Host", icon: <AppIcon name="vast" className="w-5 h-5" alt="Vast.ai" />, category: "vastai", description: "Stop the target Vast.ai host" },
  { key: "vast_destroy", label: "Destroy Target Host", icon: <AppIcon name="vast" className="w-5 h-5" alt="Vast.ai" />, category: "vastai", description: "Destroy the target Vast.ai host" },
  { key: "vast_copy", label: "Vast Copy", icon: <AppIcon name="vast" className="w-5 h-5" alt="Vast.ai" />, category: "vastai", description: "Copy data via Vast.ai copy API" },
  // Tmux
  { key: "tmux_new", label: "New Session", icon: "📺", category: "tmux", description: "Create new tmux session" },
  { key: "tmux_send", label: "Send Keys", icon: "⌨️", category: "tmux", description: "Send keys to tmux session" },
  { key: "tmux_capture", label: "Capture Output", icon: "📷", category: "tmux", description: "Capture tmux session output" },
  { key: "tmux_kill", label: "Kill Session", icon: "❌", category: "tmux", description: "Kill tmux session" },
  // Google Drive
  { key: "gdrive_mount", label: "Mount Google Drive", icon: <AppIcon name="googledrive" className="w-5 h-5" alt="Google Drive" />, category: "gdrive", description: "Mount Google Drive on target host" },
  { key: "gdrive_unmount", label: "Unmount Drive", icon: <AppIcon name="googledrive" className="w-5 h-5" alt="Google Drive" />, category: "gdrive", description: "Unmount Google Drive" },
  // Git & ML
  { key: "git_clone", label: "Git Clone", icon: "📥", category: "git", description: "Clone a Git repository" },
  { key: "hf_download", label: "HF Download", icon: "🤗", category: "git", description: "Download from HuggingFace" },
  // Control
  { key: "sleep", label: "Wait", icon: "💤", category: "control", description: "Wait for specified duration" },
  { key: "wait_condition", label: "Wait Until", icon: "⏳", category: "control", description: "Wait for condition to be true" },
  { key: "assert", label: "Assert", icon: "✅", category: "control", description: "Assert a condition is true" },
  // Utility
  { key: "set_var", label: "Set Variable", icon: "📝", category: "utility", description: "Set a variable value" },
  { key: "http_request", label: "HTTP Request", icon: "🌐", category: "utility", description: "Make HTTP request" },
  { key: "notify", label: "Notification", icon: "🔔", category: "utility", description: "Send notification" },
];

function getOperationType(step: Step): string {
  for (const opType of OPERATION_TYPES) {
    if (opType.key in step) {
      return opType.key;
    }
  }
  return "unknown";
}

// Helper to get endpoint display name
function getEndpointDisplay(endpoint: { local?: { path: string }; host?: { host_id?: string | null; path: string }; storage?: { storage_id: string; path: string } }): string {
  if ('local' in endpoint && endpoint.local) return `Local: ${endpoint.local.path || '...'}`;
  if ('host' in endpoint && endpoint.host) return `Host: ${endpoint.host.host_id || '${target}'} → ${endpoint.host.path || '...'}`;
  if ('storage' in endpoint && endpoint.storage) return `Storage: ${endpoint.storage.storage_id} → ${endpoint.storage.path || '...'}`;
  return 'Select...';
}

// Generate summary for each operation type (shown when collapsed)
function getOperationSummary(opType: string, opData: Record<string, unknown> | undefined): string {
  if (!opData) return '';
  
  switch (opType) {
    case 'run_commands': {
      const commands = (opData.commands as string) || '';
      const lines = commands.split('\n').filter(l => l.trim());
      const firstLine = lines[0]?.trim() || '';
      if (!firstLine) return '';
      return lines.length > 1 ? `${firstLine} (+${lines.length - 1})` : firstLine;
    }
    
    case 'git_clone': {
      const url = (opData.repo_url as string) || '';
      const dest = (opData.destination as string) || '';
      const branch = (opData.branch as string) || '';
      if (!url) return '';
      // Extract owner/repo from URL (support both https and ssh formats)
      // https://github.com/owner/repo.git or git@github.com:owner/repo.git
      const match = url.match(/(?:github\.com[/:])([^/]+\/[^/.]+)/);
      const shortUrl = match ? match[1] : url.replace(/^https?:\/\//, '').replace(/\.git$/, '');
      const parts = [shortUrl];
      if (dest) parts.push(`→ ${dest}`);
      if (branch) parts.push(`(${branch})`);
      return parts.join(' ');
    }
    
    case 'hf_download': {
      const repoId = (opData.repo_id as string) || '';
      const dest = (opData.destination as string) || '';
      if (!repoId) return '';
      return dest ? `${repoId} → ${dest}` : repoId;
    }
    
    case 'transfer': {
      const source = opData.source as { local?: { path: string }; host?: { host_id?: string | null; path: string }; storage?: { storage_id: string; path: string } } | undefined;
      const dest = opData.destination as { local?: { path: string }; host?: { host_id?: string | null; path: string }; storage?: { storage_id: string; path: string } } | undefined;
      
      const getEndpointSummary = (ep: typeof source, label: string) => {
        if (!ep) return '';
        if (ep.local) return ep.local.path || 'local';
        if (ep.host) {
          const path = ep.host.path || '';
          // null or undefined host_id means target
          if (ep.host.host_id === null || ep.host.host_id === undefined) {
            return path ? `target:${path}` : 'target';
          }
          return path ? `${path}` : 'host';
        }
        if (ep.storage) return ep.storage.path || 'storage';
        return '';
      };
      
      const srcSummary = getEndpointSummary(source, 'src');
      const dstSummary = getEndpointSummary(dest, 'dst');
      if (!srcSummary && !dstSummary) return '';
      return `${srcSummary || '?'} → ${dstSummary || '?'}`;
    }
    
    case 'ssh_command': {
      const cmd = (opData.command as string) || '';
      const firstLine = cmd.split('\n')[0]?.trim() || '';
      return firstLine;
    }
    
    case 'rsync_upload': {
      const localPath = (opData.local_path as string) || '';
      const remotePath = (opData.remote_path as string) || '';
      if (!localPath && !remotePath) return '';
      return `${localPath || '?'} → ${remotePath || '?'}`;
    }
    
    case 'rsync_download': {
      const localPath = (opData.local_path as string) || '';
      const remotePath = (opData.remote_path as string) || '';
      if (!localPath && !remotePath) return '';
      return `${remotePath || '?'} → ${localPath || '?'}`;
    }
    
    case 'vast_start':
    case 'vast_stop':
    case 'vast_destroy': {
      return 'target';
    }

    case 'vast_copy': {
      const src = (opData.src as string) || '';
      const dst = (opData.dst as string) || '';
      if (!src && !dst) return '';
      return `${src || '?'} → ${dst || '?'}`;
    }
    
    case 'tmux_new': {
      const session = (opData.session_name as string) || '';
      return session ? `session: ${session}` : '';
    }
    
    case 'tmux_send': {
      const session = (opData.session_name as string) || '';
      const keys = (opData.keys as string) || '';
      if (!keys) return session ? `→ ${session}` : '';
      const shortKeys = keys.length > 25 ? keys.slice(0, 25) + '...' : keys;
      return session ? `${session}: ${shortKeys}` : shortKeys;
    }
    
    case 'tmux_capture':
    case 'tmux_kill': {
      const session = (opData.session_name as string) || '';
      return session;
    }
    
    case 'gdrive_mount': {
      const mountPath = (opData.mount_path as string) || '/content/drive/MyDrive';
      return mountPath;
    }
    
    case 'gdrive_unmount': {
      const mountPath = (opData.mount_path as string) || '';
      return mountPath;
    }
    
    case 'sleep': {
      const secs = opData.duration_secs as number;
      if (!secs) return '';
      if (secs >= 3600) return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
      if (secs >= 60) return `${Math.floor(secs / 60)}m ${secs % 60}s`;
      return `${secs}s`;
    }
    
    case 'wait_condition':
    case 'assert': {
      const condition = opData.condition;
      if (typeof condition === 'string') return condition;
      if (condition && typeof condition === 'object') {
        const condObj = condition as Record<string, unknown>;
        const type = Object.keys(condObj)[0];
        if (!type) return '';
        // Show condition type and first arg if available
        const arg = condObj[type];
        if (typeof arg === 'object' && arg !== null) {
          const argObj = arg as Record<string, unknown>;
          const firstVal = Object.values(argObj)[0];
          if (typeof firstVal === 'string') return `${type}: ${firstVal.slice(0, 20)}`;
        }
        return type;
      }
      return '';
    }
    
    case 'set_var': {
      const name = (opData.name as string) || '';
      const value = (opData.value as string) || '';
      if (!name) return '';
      const shortVal = value.length > 15 ? value.slice(0, 15) + '...' : value;
      return `${name}=${shortVal}`;
    }
    
    case 'http_request': {
      const method = (opData.method as string) || 'GET';
      const url = (opData.url as string) || '';
      if (!url) return '';
      // Shorten URL for display
      try {
        const parsed = new URL(url);
        return `${method} ${parsed.host}${parsed.pathname}`;
      } catch {
        return `${method} ${url}`;
      }
    }
    
    case 'notify': {
      const title = (opData.title as string) || '';
      const message = (opData.message as string) || '';
      return title || message?.slice(0, 30) || '';
    }
    
    default:
      return '';
  }
}

// Transfer operation fields component
function TransferOpFields({ opData, updateOp }: { opData: Record<string, unknown>; updateOp: (field: string, value: unknown) => void }) {
  const { data: hosts = [] } = useHosts();
  const { data: storages = [] } = useStorages();
  
  // File picker state
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerTarget, setPickerTarget] = useState<'source' | 'destination'>('source');
  
  const source = opData.source as { local?: { path: string }; host?: { host_id?: string | null; path: string }; storage?: { storage_id: string; path: string } };
  const destination = opData.destination as { local?: { path: string }; host?: { host_id?: string | null; path: string }; storage?: { storage_id: string; path: string } };
  const includePaths = (opData.include_paths as string[]) || [];
  const excludePatterns = (opData.exclude_patterns as string[]) || [];

  // "target" is represented as host with host_id = null
  const getSourceType = () => {
    if (source?.local) return 'local';
    if (source?.host) {
      return source.host.host_id === null || source.host.host_id === undefined ? 'target' : 'host';
    }
    if (source?.storage) return 'storage';
    return 'local';
  };

  const getDestType = () => {
    if (destination?.local) return 'local';
    if (destination?.host) {
      return destination.host.host_id === null || destination.host.host_id === undefined ? 'target' : 'host';
    }
    if (destination?.storage) return 'storage';
    return 'target';
  };

  const updateSource = (type: string, data: Record<string, unknown>) => {
    if (type === 'target') {
      // Target is stored as host with null host_id
      updateOp('source', { host: { host_id: null, ...data } });
    } else {
      updateOp('source', { [type]: data });
    }
  };

  const updateDest = (type: string, data: Record<string, unknown>) => {
    if (type === 'target') {
      // Target is stored as host with null host_id
      updateOp('destination', { host: { host_id: null, ...data } });
    } else {
      updateOp('destination', { [type]: data });
    }
  };

  // Get path for target endpoint
  const getSourcePath = () => source?.host?.path ?? source?.local?.path ?? source?.storage?.path ?? '';
  const getDestPath = () => destination?.host?.path ?? destination?.local?.path ?? destination?.storage?.path ?? '';

  // Open file picker for source or destination
  const openPicker = (target: 'source' | 'destination') => {
    setPickerTarget(target);
    setPickerOpen(true);
  };
  
  // Get default endpoint type for picker based on current selection
  const getPickerDefaultType = (): EndpointType => {
    const type = pickerTarget === 'source' ? getSourceType() : getDestType();
    if (type === 'target') return 'host'; // target uses host picker
    if (type === 'local') return 'local';
    if (type === 'host') return 'host';
    if (type === 'storage') return 'storage';
    return 'local';
  };
  
  // Get current host/storage ID for picker
  const getPickerHostId = () => {
    const ep = pickerTarget === 'source' ? source : destination;
    if (ep?.host?.host_id) return ep.host.host_id;
    return '';
  };
  
  const getPickerStorageId = () => {
    const ep = pickerTarget === 'source' ? source : destination;
    if (ep?.storage?.storage_id) return ep.storage.storage_id;
    return '';
  };
  
  // Handle file picker selection
  const handlePickerSelect = (endpoint: SelectedEndpoint, selectedPaths: string[]) => {
    if (selectedPaths.length === 0) return;
    
    // Use the first selected path (or join multiple paths)
    const path = selectedPaths.length === 1 ? selectedPaths[0] : selectedPaths.join(', ');
    
    if (pickerTarget === 'source') {
      if (endpoint.type === 'local') {
        updateOp('source', { local: { path } });
      } else if (endpoint.type === 'host') {
        updateOp('source', { host: { host_id: endpoint.hostId, path } });
      } else if (endpoint.type === 'storage') {
        updateOp('source', { storage: { storage_id: endpoint.storageId, path } });
      }
    } else {
      if (endpoint.type === 'local') {
        updateOp('destination', { local: { path } });
      } else if (endpoint.type === 'host') {
        updateOp('destination', { host: { host_id: endpoint.hostId, path } });
      } else if (endpoint.type === 'storage') {
        updateOp('destination', { storage: { storage_id: endpoint.storageId, path } });
      }
    }
  };

  // Browse button component
  const BrowseButton = ({ target }: { target: 'source' | 'destination' }) => (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          size="icon"
          variant="outline"
          className="h-8 w-8"
          onClick={() => openPicker(target)}
          aria-label="Browse files"
        >
          <IconFolderOpen />
        </Button>
      </TooltipTrigger>
      <TooltipContent>Browse files</TooltipContent>
    </Tooltip>
  );

  return (
    <div className="space-y-4">
      {/* Source */}
      <div className="space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm text-muted-foreground w-20">Source</span>
          <Select
            value={getSourceType()}
            onValueChange={(type) => {
              if (type === "local") updateOp("source", { local: { path: "" } });
              else if (type === "target") updateOp("source", { host: { host_id: null, path: "" } });
              else if (type === "host") updateOp("source", { host: { host_id: "", path: "" } });
              else if (type === "storage") updateOp("source", { storage: { storage_id: "", path: "" } });
            }}
          >
            <SelectTrigger className="max-w-[140px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="local">Local</SelectItem>
              <SelectItem value="target">Target Host</SelectItem>
              <SelectItem value="host">Host</SelectItem>
              <SelectItem value="storage">Storage</SelectItem>
            </SelectContent>
          </Select>
          
          {/* Target: just path input */}
          {getSourceType() === 'target' && (
            <div className="relative flex-1 min-w-[200px]">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-primary whitespace-nowrap">${"{target}"}:</span>
              <Input
                placeholder="/workspace/data"
                value={source?.host?.path ?? ""}
                onChange={(e) => updateSource("target", { path: e.target.value })}
                className="pl-24"
              />
            </div>
          )}
          
          {/* Local: path input + browse */}
          {getSourceType() === 'local' && (
            <>
              <Input
                placeholder="/path/to/local"
                value={source?.local?.path ?? ""}
                onChange={(e) => updateSource("local", { path: e.target.value })}
                className="flex-1 min-w-[200px]"
              />
              <BrowseButton target="source" />
            </>
          )}
          
          {/* Host: dropdown + path + browse */}
          {getSourceType() === 'host' && (
            <>
              <Select
                value={source?.host?.host_id || "__none__"}
                onValueChange={(value) => {
                  const hostId = value === "__none__" ? "" : value;
                  updateOp("source", { host: { ...source?.host, host_id: hostId } });
                }}
              >
                <SelectTrigger className="w-40">
                  <SelectValue placeholder="Select host..." />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">Select host...</SelectItem>
                  {hosts.map((h: Host) => (
                    <SelectItem key={h.id} value={h.id}>
                      {h.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Input
                placeholder="/remote/path"
                value={source?.host?.path ?? ""}
                onChange={(e) => updateOp("source", { host: { ...source?.host, path: e.target.value } })}
                className="flex-1 min-w-[150px]"
              />
              <BrowseButton target="source" />
            </>
          )}
          
          {/* Storage: dropdown + path + browse */}
          {getSourceType() === 'storage' && (
            <>
              <Select
                value={source?.storage?.storage_id || "__none__"}
                onValueChange={(value) => {
                  const storageId = value === "__none__" ? "" : value;
                  updateOp("source", { storage: { ...source?.storage, storage_id: storageId } });
                }}
              >
                <SelectTrigger className="w-40">
                  <SelectValue placeholder="Select storage..." />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">Select storage...</SelectItem>
                  {storages.map((s: Storage) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Input
                placeholder="/path/in/storage"
                value={source?.storage?.path ?? ""}
                onChange={(e) => updateOp("source", { storage: { ...source?.storage, path: e.target.value } })}
                className="flex-1 min-w-[150px]"
              />
              <BrowseButton target="source" />
            </>
          )}
        </div>
      </div>

      {/* Destination */}
      <div className="space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm text-muted-foreground w-20">Destination</span>
          <Select
            value={getDestType()}
            onValueChange={(type) => {
              if (type === "local") updateOp("destination", { local: { path: "" } });
              else if (type === "target") updateOp("destination", { host: { host_id: null, path: "" } });
              else if (type === "host") updateOp("destination", { host: { host_id: "", path: "" } });
              else if (type === "storage") updateOp("destination", { storage: { storage_id: "", path: "" } });
            }}
          >
            <SelectTrigger className="max-w-[140px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="local">Local</SelectItem>
              <SelectItem value="target">Target Host</SelectItem>
              <SelectItem value="host">Host</SelectItem>
              <SelectItem value="storage">Storage</SelectItem>
            </SelectContent>
          </Select>
          
          {/* Target: just path input */}
          {getDestType() === 'target' && (
            <div className="relative flex-1 min-w-[200px]">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-primary whitespace-nowrap">${"{target}"}:</span>
              <Input
                placeholder="/workspace/data"
                value={destination?.host?.path ?? ""}
                onChange={(e) => updateDest("target", { path: e.target.value })}
                className="pl-24"
              />
            </div>
          )}
          
          {/* Local: path input + browse */}
          {getDestType() === 'local' && (
            <>
              <Input
                placeholder="/path/to/local"
                value={destination?.local?.path ?? ""}
                onChange={(e) => updateDest("local", { path: e.target.value })}
                className="flex-1 min-w-[200px]"
              />
              <BrowseButton target="destination" />
            </>
          )}
          
          {/* Host: dropdown + path + browse */}
          {getDestType() === 'host' && (
            <>
              <Select
                value={destination?.host?.host_id || "__none__"}
                onValueChange={(value) => {
                  const hostId = value === "__none__" ? "" : value;
                  updateOp("destination", { host: { ...destination?.host, host_id: hostId } });
                }}
              >
                <SelectTrigger className="w-40">
                  <SelectValue placeholder="Select host..." />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">Select host...</SelectItem>
                  {hosts.map((h: Host) => (
                    <SelectItem key={h.id} value={h.id}>
                      {h.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Input
                placeholder="/remote/path"
                value={destination?.host?.path ?? ""}
                onChange={(e) => updateOp("destination", { host: { ...destination?.host, path: e.target.value } })}
                className="flex-1 min-w-[150px]"
              />
              <BrowseButton target="destination" />
            </>
          )}
          
          {/* Storage: dropdown + path + browse */}
          {getDestType() === 'storage' && (
            <>
              <Select
                value={destination?.storage?.storage_id || "__none__"}
                onValueChange={(value) => {
                  const storageId = value === "__none__" ? "" : value;
                  updateOp("destination", { storage: { ...destination?.storage, storage_id: storageId } });
                }}
              >
                <SelectTrigger className="w-40">
                  <SelectValue placeholder="Select storage..." />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">Select storage...</SelectItem>
                  {storages.map((s: Storage) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Input
                placeholder="/path/in/storage"
                value={destination?.storage?.path ?? ""}
                onChange={(e) => updateOp("destination", { storage: { ...destination?.storage, path: e.target.value } })}
                className="flex-1 min-w-[150px]"
              />
              <BrowseButton target="destination" />
            </>
          )}
        </div>
      </div>

      {/* Include/Exclude patterns in two columns */}
      <div className="grid grid-cols-2 gap-4">
        {/* Include paths */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground font-medium">Include Paths</span>
            <Button
              size="sm"
              variant="outline"
              className="h-6 px-2 text-xs"
              onClick={() => updateOp('include_paths', [...includePaths, ''])}
            >
              + Add
            </Button>
          </div>
          <div className="space-y-1 max-h-32 overflow-y-auto">
            {includePaths.length === 0 ? (
              <p className="text-xs text-muted-foreground italic">All files (no filter)</p>
            ) : (
              includePaths.map((p, i) => (
                <div key={i} className="flex items-center gap-1">
                  <Input
                    placeholder="src/"
                    value={p}
                    onChange={(e) => {
                      const newPaths = [...includePaths];
                      newPaths[i] = e.target.value;
                      updateOp("include_paths", newPaths);
                    }}
                    className="flex-1 h-7 text-xs"
                  />
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-6 w-6 min-w-6"
                    onClick={() => {
                      const newPaths = includePaths.filter((_, idx) => idx !== i);
                      updateOp('include_paths', newPaths);
                    }}
                    aria-label="Remove include path"
                  >
                    <IconTrash />
                  </Button>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Exclude patterns */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground font-medium">Exclude Patterns</span>
            <Button
              size="sm"
              variant="outline"
              className="h-6 px-2 text-xs"
              onClick={() => updateOp('exclude_patterns', [...excludePatterns, ''])}
            >
              + Add
            </Button>
          </div>
          <div className="space-y-1 max-h-32 overflow-y-auto">
            {excludePatterns.length === 0 ? (
              <p className="text-xs text-muted-foreground italic">No exclusions</p>
            ) : (
              excludePatterns.map((p, i) => (
                <div key={i} className="flex items-center gap-1">
                  <Input
                    placeholder="*.pyc"
                    value={p}
                    onChange={(e) => {
                      const newPatterns = [...excludePatterns];
                      newPatterns[i] = e.target.value;
                      updateOp("exclude_patterns", newPatterns);
                    }}
                    className="flex-1 h-7 text-xs"
                  />
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-6 w-6 min-w-6"
                    onClick={() => {
                      const newPatterns = excludePatterns.filter((_, idx) => idx !== i);
                      updateOp('exclude_patterns', newPatterns);
                    }}
                    aria-label="Remove exclude pattern"
                  >
                    <IconTrash />
                  </Button>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Options */}
      <div className="flex items-center gap-4 pt-2">
        <Label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
          <Checkbox
            checked={(opData.use_gitignore as boolean) ?? false}
            onCheckedChange={(checked) => updateOp("use_gitignore", checked === true)}
          />
          Use .gitignore
        </Label>
        <Label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
          <Checkbox
            checked={(opData.delete as boolean) ?? false}
            onCheckedChange={(checked) => updateOp("delete", checked === true)}
          />
          Delete extraneous
        </Label>
      </div>
      
      {/* File Picker Modal */}
      <FilePicker
        isOpen={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onSelect={handlePickerSelect}
        title={pickerTarget === 'source' ? 'Select Source Files' : 'Select Destination Folder'}
        mode="both"
        multiple={true}
        defaultEndpointType={getPickerDefaultType()}
        defaultHostId={getPickerHostId()}
        defaultStorageId={getPickerStorageId()}
      />
    </div>
  );
}

type VastCopyEndpointType = "target" | "host" | "local";

type VastCopyEndpointState = {
  type: VastCopyEndpointType;
  hostId?: string | null;
  instanceId?: string | null;
  path: string;
};

function findVastHostByInstanceId(hosts: Host[], instanceId: string): Host | undefined {
  const trimmed = instanceId.trim();
  if (!trimmed) return undefined;
  return hosts.find(
    (host) => host.type === "vast" && host.vast_instance_id?.toString() === trimmed
  );
}

function parseVastCopyLocation(value: string, vastHosts: Host[]): VastCopyEndpointState {
  const trimmed = value?.trim() ?? "";
  if (!trimmed) {
    return { type: "target", hostId: null, instanceId: null, path: "" };
  }

  const [prefixRaw, pathRaw = ""] = trimmed.split(":", 2);
  const prefix = prefixRaw.trim();
  const path = pathRaw;
  const prefixLower = prefix.toLowerCase();

  if (prefixLower === "local") {
    return { type: "local", hostId: null, instanceId: null, path };
  }
  if (prefixLower === "target" || prefixLower === "c.target" || prefixLower === "c.") {
    return { type: "target", hostId: null, instanceId: null, path };
  }

  if (prefixLower.startsWith("c.")) {
    const instanceId = prefix.slice(2);
    const host = findVastHostByInstanceId(vastHosts, instanceId);
    return { type: "host", hostId: host?.id ?? null, instanceId, path };
  }

  if (/^\d+$/.test(prefix)) {
    const host = findVastHostByInstanceId(vastHosts, prefix);
    return { type: "host", hostId: host?.id ?? null, instanceId: prefix, path };
  }

  const host = vastHosts.find((candidate) => candidate.id === prefix);
  if (host) {
    return {
      type: "host",
      hostId: host.id,
      instanceId: host.vast_instance_id?.toString() ?? null,
      path,
    };
  }

  return { type: "target", hostId: null, instanceId: null, path };
}

function buildVastCopyLocation(state: VastCopyEndpointState, vastHosts: Host[]): string {
  const path = state.path ?? "";
  if (state.type === "local") return `local:${path}`;
  if (state.type === "target") return `C.target:${path}`;
  const host = vastHosts.find((candidate) => candidate.id === state.hostId);
  const instanceId = host?.vast_instance_id?.toString() ?? state.instanceId ?? "";
  if (!instanceId) return "";
  return `C.${instanceId}:${path}`;
}

function VastCopyOpFields({ opData, updateOp }: { opData: Record<string, unknown>; updateOp: (field: string, value: unknown) => void }) {
  const { data: hosts = [] } = useHosts();
  const vastHosts = hosts.filter((host) => host.type === "vast" && host.vast_instance_id);

  const srcValue = (opData.src as string) ?? "";
  const dstValue = (opData.dst as string) ?? "";

  const srcState = parseVastCopyLocation(srcValue, vastHosts);
  const dstState = parseVastCopyLocation(dstValue, vastHosts);

  const updateEndpoint = (field: "src" | "dst", next: VastCopyEndpointState) => {
    const value = buildVastCopyLocation(next, vastHosts);
    updateOp(field, value);
  };

  const updateType = (field: "src" | "dst", type: VastCopyEndpointType) => {
    const current = field === "src" ? srcState : dstState;
    if (type !== "host") {
      updateEndpoint(field, { ...current, type, hostId: null, instanceId: null });
      return;
    }

    const nextHostId = current.hostId || vastHosts[0]?.id || null;
    const nextHost = vastHosts.find((host) => host.id === nextHostId);
    const nextInstanceId =
      nextHost?.vast_instance_id?.toString() ?? current.instanceId ?? null;
    updateEndpoint(field, {
      ...current,
      type,
      hostId: nextHostId,
      instanceId: nextInstanceId,
    });
  };

  const updateHost = (field: "src" | "dst", hostId: string) => {
    const current = field === "src" ? srcState : dstState;
    const host = vastHosts.find((candidate) => candidate.id === hostId);
    updateEndpoint(field, {
      ...current,
      type: "host",
      hostId,
      instanceId: host?.vast_instance_id?.toString() ?? null,
    });
  };

  const updatePath = (field: "src" | "dst", path: string) => {
    const current = field === "src" ? srcState : dstState;
    updateEndpoint(field, { ...current, path });
  };

  const renderHostSelect = (field: "src" | "dst", state: VastCopyEndpointState) => (
    <Select
      value={state.hostId ?? "__none__"}
      onValueChange={(value) => {
        if (value === "__none__") return;
        updateHost(field, value);
      }}
      disabled={vastHosts.length === 0}
    >
      <SelectTrigger className="w-40">
        <SelectValue placeholder={vastHosts.length === 0 ? "No Vast hosts" : "Select Vast host"} />
      </SelectTrigger>
      <SelectContent>
        {vastHosts.length === 0 ? (
          <SelectItem value="__none__" disabled>
            No Vast hosts
          </SelectItem>
        ) : (
          <>
            <SelectItem value="__none__">Select Vast host</SelectItem>
            {vastHosts.map((host) => (
              <SelectItem key={host.id} value={host.id}>
                {host.name}
              </SelectItem>
            ))}
          </>
        )}
      </SelectContent>
    </Select>
  );

  return (
    <div className="space-y-4">
      <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg">
        <p className="text-sm text-blue-700">
          Target uses the host you select when running the recipe. Paths map to
          Vast copy prefixes like <code>C.target:/workspace/</code>. SSH uses
          the Vast key from Settings.
        </p>
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm text-muted-foreground w-20">Source</span>
          <Select value={srcState.type} onValueChange={(value) => updateType("src", value as VastCopyEndpointType)}>
            <SelectTrigger className="max-w-[140px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="target">Target Host</SelectItem>
              <SelectItem value="host">Vast Host</SelectItem>
              <SelectItem value="local">Local</SelectItem>
            </SelectContent>
          </Select>

          {srcState.type === "host" && renderHostSelect("src", srcState)}

          <Input
            placeholder={srcState.type === "local" ? "/path/to/local" : "/workspace/data"}
            value={srcState.path}
            onChange={(e) => updatePath("src", e.target.value)}
            className="flex-1 min-w-[200px]"
          />
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm text-muted-foreground w-20">Destination</span>
          <Select value={dstState.type} onValueChange={(value) => updateType("dst", value as VastCopyEndpointType)}>
            <SelectTrigger className="max-w-[140px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="target">Target Host</SelectItem>
              <SelectItem value="host">Vast Host</SelectItem>
              <SelectItem value="local">Local</SelectItem>
            </SelectContent>
          </Select>

          {dstState.type === "host" && renderHostSelect("dst", dstState)}

          <Input
            placeholder={dstState.type === "local" ? "/path/to/local" : "/workspace/data"}
            value={dstState.path}
            onChange={(e) => updatePath("dst", e.target.value)}
            className="flex-1 min-w-[200px]"
          />
        </div>
      </div>
    </div>
  );
}

// Condition types for the condition editor
const CONDITION_TYPES = [
  { key: 'file_exists', label: 'File Exists', fields: ['host_id', 'path'] },
  { key: 'file_contains', label: 'File Contains', fields: ['host_id', 'path', 'pattern'] },
  { key: 'command_succeeds', label: 'Command Succeeds', fields: ['host_id', 'command'] },
  { key: 'output_matches', label: 'Output Matches', fields: ['host_id', 'command', 'pattern'] },
  { key: 'var_equals', label: 'Variable Equals', fields: ['name', 'value'] },
  { key: 'var_matches', label: 'Variable Matches', fields: ['name', 'pattern'] },
  { key: 'host_online', label: 'Host Online', fields: ['host_id'] },
  { key: 'tmux_alive', label: 'Tmux Alive', fields: ['host_id', 'session_name'] },
  { key: 'gpu_available', label: 'GPU Available', fields: ['host_id', 'min_count'] },
  { key: 'gdrive_mounted', label: 'GDrive Mounted', fields: ['host_id', 'mount_path'] },
  { key: 'always', label: 'Always True', fields: [] },
  { key: 'never', label: 'Always False', fields: [] },
] as const;

type ConditionType = typeof CONDITION_TYPES[number]['key'];

// Condition editor component
function ConditionEditor({ condition, onChange }: { condition: unknown; onChange: (c: unknown) => void }) {
  // Determine current condition type
  const getConditionType = (): ConditionType => {
    if (condition === 'always') return 'always';
    if (condition === 'never') return 'never';
    if (typeof condition === 'object' && condition !== null) {
      const keys = Object.keys(condition);
      if (keys.length === 1) {
        const key = keys[0];
        if (CONDITION_TYPES.find(c => c.key === key)) return key as ConditionType;
      }
    }
    return 'always';
  };

  const conditionType = getConditionType();
  const conditionData = (typeof condition === 'object' && condition !== null && conditionType !== 'always' && conditionType !== 'never')
    ? (condition as Record<string, Record<string, unknown>>)[conditionType] ?? {}
    : {};

  const updateConditionType = (type: ConditionType) => {
    if (type === 'always' || type === 'never') {
      onChange(type);
    } else {
      // Create empty condition with default fields
      const defaults: Record<string, unknown> = {};
      const typeDef = CONDITION_TYPES.find(c => c.key === type);
      typeDef?.fields.forEach(f => {
        if (f === 'min_count') defaults[f] = 1;
        else defaults[f] = '';
      });
      onChange({ [type]: defaults });
    }
  };

  const updateField = (field: string, value: unknown) => {
    if (conditionType === 'always' || conditionType === 'never') return;
    onChange({ [conditionType]: { ...conditionData, [field]: value } });
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-sm text-muted-foreground w-20">Condition</span>
        <Select value={conditionType} onValueChange={(value) => updateConditionType(value as ConditionType)}>
          <SelectTrigger className="max-w-[260px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CONDITION_TYPES.map((c) => (
              <SelectItem key={c.key} value={c.key}>
                {c.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Render fields based on condition type */}
      {conditionType !== 'always' && conditionType !== 'never' && (
        <div className="space-y-2 pl-[88px]">
          {CONDITION_TYPES.find(c => c.key === conditionType)?.fields.map(field => (
            <div key={field} className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground w-20 capitalize">{field.replace('_', ' ')}</span>
              {field === 'min_count' ? (
                <Input
                  type="number"
                  inputMode="numeric"
                  placeholder="1"
                  value={String(conditionData[field] ?? 1)}
                  onChange={(e) => updateField(field, parseInt(e.target.value, 10) || 1)}
                  className="max-w-[100px]"
                />
              ) : field === 'command' ? (
                <Textarea
                  placeholder="command to run"
                  value={(conditionData[field] as string) ?? ""}
                  onChange={(e) => updateField(field, e.target.value)}
                  className="flex-1 font-mono text-xs"
                  rows={2}
                />
              ) : (
                <Input
                  placeholder={field === "host_id" ? "${target}" : field === "pattern" ? "regex pattern" : field}
                  value={(conditionData[field] as string) ?? ""}
                  onChange={(e) => updateField(field, e.target.value)}
                  className="flex-1"
                />
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function getOperationDef(opType: string): OperationDef {
  return OPERATION_TYPES.find(t => t.key === opType) ?? { 
    key: opType, label: opType, icon: "❓", category: "utility", description: "" 
  };
}

function createEmptyStep(id: string, opType: string): Step {
  const baseStep = {
    id,
    name: null,
    depends_on: [],
    retry: null,
    timeout_secs: null,
    when: null,
    continue_on_failure: false,
  };
  
  switch (opType) {
    // New unified operations
    case "run_commands":
      return { ...baseStep, run_commands: { commands: "", tmux_mode: "none" } };
    case "transfer":
      return { ...baseStep, transfer: { 
        source: { local: { path: "" } }, 
        destination: { host: { host_id: null, path: "" } },  // null host_id = target
        include_paths: [],
        exclude_patterns: [],
      } };
    // Git & ML
    case "git_clone":
      return { ...baseStep, git_clone: { repo_url: "", destination: "" } };
    case "hf_download":
      return { ...baseStep, hf_download: { repo_id: "", destination: "", repo_type: "model" } };
    // Legacy operations
    case "ssh_command":
      return { ...baseStep, ssh_command: { host_id: "", command: "" } };
    case "rsync_upload":
      return { ...baseStep, rsync_upload: { host_id: "", local_path: "", remote_path: "" } };
    case "rsync_download":
      return { ...baseStep, rsync_download: { host_id: "", remote_path: "", local_path: "" } };
    // Vast.ai
    case "vast_start":
      return { ...baseStep, vast_start: {} };
    case "vast_stop":
      return { ...baseStep, vast_stop: {} };
    case "vast_destroy":
      return { ...baseStep, vast_destroy: {} };
    case "vast_copy":
      return { ...baseStep, vast_copy: { src: "", dst: "", identity_file: null } };
    // Tmux
    case "tmux_new":
      return { ...baseStep, tmux_new: { host_id: "", session_name: "" } };
    case "tmux_send":
      return { ...baseStep, tmux_send: { host_id: "", session_name: "", keys: "" } };
    case "tmux_capture":
      return { ...baseStep, tmux_capture: { host_id: "", session_name: "" } };
    case "tmux_kill":
      return { ...baseStep, tmux_kill: { host_id: "", session_name: "" } };
    // Google Drive
    case "gdrive_mount":
      return { ...baseStep, gdrive_mount: { mount_path: "/content/drive/MyDrive" } };
    case "gdrive_unmount":
      return { ...baseStep, gdrive_unmount: { host_id: "", mount_path: "/mnt/gdrive" } };
    // Control
    case "sleep":
      return { ...baseStep, sleep: { duration_secs: 5 } };
    case "wait_condition":
      return { ...baseStep, wait_condition: { condition: "always", timeout_secs: 300, poll_interval_secs: 10 } };
    case "assert":
      return { ...baseStep, assert: { condition: "always" } };
    // Utility
    case "set_var":
      return { ...baseStep, set_var: { name: "", value: "" } };
    case "http_request":
      return { ...baseStep, http_request: { method: "GET", url: "" } };
    case "notify":
      return { ...baseStep, notify: { title: "" } };
    default:
      return { ...baseStep, run_commands: { commands: "", tmux_mode: "none" } };
  }
}

// Step Block Component (Apple Shortcuts style)
function StepBlock({ 
  step, 
  onChange, 
  onDelete,
  isFirst,
  isLast,
}: {
  step: Step;
  onChange: (step: Step) => void;
  onDelete: () => void;
  isFirst: boolean;
  isLast: boolean;
}) {
  const [isExpanded, setIsExpanded] = useState(true);
  const dragControls = useDragControls();
  
  const opType = getOperationType(step);
  const opDef = getOperationDef(opType);
  const category = OPERATION_CATEGORIES[opDef.category];
  const opData = (step as Record<string, unknown>)[opType] as Record<string, unknown> | undefined;
  
  const updateOp = (field: string, value: unknown) => {
    onChange({
      ...step,
      [opType]: { ...opData, [field]: value },
    });
  };
  
  const renderOperationFields = () => {
    if (!opData) return null;
    
    switch (opType) {
      // New unified run_commands
      case "run_commands":
        return (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Host</span>
              <Input
                placeholder="${target} (uses recipe target)"
                value={(opData.host_id as string) ?? ""}
                onChange={(e) => updateOp("host_id", e.target.value.trim() ? e.target.value : null)}
              />
            </div>
            <div className="flex items-start gap-2">
              <span className="text-sm text-muted-foreground w-20 pt-2">Commands</span>
              <div className="flex-1 flex flex-col gap-1">
                <Textarea
                  placeholder={"cd /workspace\npip install -r requirements.txt\npython train.py"}
                  value={opData.commands as string}
                  onChange={(e) => updateOp("commands", e.target.value)}
                  rows={4}
                  className="font-mono text-sm"
                />
                <div className="flex justify-end">
                  <ExternalEditorButton 
                    content={opData.commands as string}
                    onChange={(v) => updateOp("commands", v)}
                  />
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Tmux Mode</span>
              <Select
                value={(opData.tmux_mode as string) || "none"}
                onValueChange={(value) => updateOp("tmux_mode", value)}
              >
                <SelectTrigger className="max-w-[220px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Direct (blocks)</SelectItem>
                  <SelectItem value="new">New tmux session</SelectItem>
                  <SelectItem value="existing">Existing tmux</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {((opData.tmux_mode as string) === "new" || (opData.tmux_mode as string) === "existing") && (
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground w-20">Session</span>
                <Input
                  placeholder="train"
                  value={(opData.session_name as string) ?? ""}
                  onChange={(e) => updateOp("session_name", e.target.value.trim() ? e.target.value : null)}
                />
              </div>
            )}
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Directory</span>
              <Input
                placeholder="/workspace"
                value={(opData.workdir as string) ?? ""}
                onChange={(e) => updateOp("workdir", e.target.value.trim() ? e.target.value : null)}
              />
            </div>
          </div>
        );

      // New unified transfer
      case "transfer":
        return <TransferOpFields opData={opData} updateOp={updateOp} />;

      // Git clone
      case "git_clone":
        return (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Host</span>
              <Input
                placeholder="${target} (uses recipe target)"
                value={(opData.host_id as string) ?? ""}
                onChange={(e) => updateOp("host_id", e.target.value.trim() ? e.target.value : null)}
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Repo URL</span>
              <Input
                placeholder="https://github.com/user/repo.git"
                value={opData.repo_url as string}
                onChange={(e) => updateOp("repo_url", e.target.value)}
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Destination</span>
              <Input
                placeholder="/workspace/project"
                value={opData.destination as string}
                onChange={(e) => updateOp("destination", e.target.value)}
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Branch</span>
              <Input
                placeholder="main (optional)"
                value={(opData.branch as string) ?? ""}
                onChange={(e) => updateOp("branch", e.target.value.trim() ? e.target.value : null)}
                className="max-w-[200px]"
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Auth Token</span>
              <Input
                placeholder="${secret:github/token}"
                value={(opData.auth_token as string) ?? ""}
                onChange={(e) => updateOp("auth_token", e.target.value.trim() ? e.target.value : null)}
              />
            </div>
          </div>
        );

      // HuggingFace download
      case "hf_download":
        return (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Host</span>
              <Input
                placeholder="${target} (uses recipe target)"
                value={(opData.host_id as string) ?? ""}
                onChange={(e) => updateOp("host_id", e.target.value.trim() ? e.target.value : null)}
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Repo ID</span>
              <Input
                placeholder="meta-llama/Llama-2-7b"
                value={opData.repo_id as string}
                onChange={(e) => updateOp("repo_id", e.target.value)}
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Destination</span>
              <Input
                placeholder="/workspace/models/llama2"
                value={opData.destination as string}
                onChange={(e) => updateOp("destination", e.target.value)}
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Type</span>
              <Select
                value={(opData.repo_type as string) || "model"}
                onValueChange={(value) => updateOp("repo_type", value)}
              >
                <SelectTrigger className="max-w-[180px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="model">Model</SelectItem>
                  <SelectItem value="dataset">Dataset</SelectItem>
                  <SelectItem value="space">Space</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Auth Token</span>
              <Input
                placeholder="${secret:huggingface/token}"
                value={(opData.auth_token as string) ?? ""}
                onChange={(e) => updateOp("auth_token", e.target.value.trim() ? e.target.value : null)}
              />
            </div>
          </div>
        );

      // Legacy ssh_command
      case "ssh_command":
        return (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Host</span>
              <Input
                placeholder="${host}"
                value={opData.host_id as string}
                onChange={(e) => updateOp("host_id", e.target.value)}
              />
            </div>
            <div className="flex items-start gap-2">
              <span className="text-sm text-muted-foreground w-20 pt-2">Command</span>
              <Textarea
                placeholder="python train.py"
                value={opData.command as string}
                onChange={(e) => updateOp("command", e.target.value)}
                rows={2}
                className="flex-1 font-mono text-sm"
              />
            </div>
            {opData.workdir !== undefined && (
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground w-20">Directory</span>
                <Input
                  placeholder="/workspace"
                  value={(opData.workdir as string) ?? ""}
                  onChange={(e) => updateOp("workdir", e.target.value.trim() ? e.target.value : null)}
                />
              </div>
            )}
          </div>
        );
        
      case "rsync_upload":
      case "rsync_download":
        return (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Host</span>
              <Input
                placeholder="${host}"
                value={opData.host_id as string}
                onChange={(e) => updateOp("host_id", e.target.value)}
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Local</span>
              <Input
                placeholder="/path/to/local"
                value={opData.local_path as string}
                onChange={(e) => updateOp("local_path", e.target.value)}
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Remote</span>
              <Input
                placeholder="/workspace/remote"
                value={opData.remote_path as string}
                onChange={(e) => updateOp("remote_path", e.target.value)}
              />
            </div>
          </div>
        );

      // Google Drive mount
      case "gdrive_mount":
        return (
          <div className="space-y-3">
            <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg">
              <p className="text-sm text-blue-700">
                Will mount your Google Drive on the target host. Make sure you've connected Google Drive in the Storage settings.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-24">Mount Path</span>
              <Input
                placeholder="/content/drive/MyDrive"
                value={(opData.mount_path as string) || "/content/drive/MyDrive"}
                onChange={(e) => updateOp("mount_path", e.target.value)}
              />
            </div>
          </div>
        );

      case "gdrive_unmount":
        return (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Host</span>
              <Input
                placeholder="${target}"
                value={opData.host_id as string}
                onChange={(e) => updateOp("host_id", e.target.value)}
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Mount Path</span>
              <Input
                placeholder="/mnt/gdrive"
                value={opData.mount_path as string}
                onChange={(e) => updateOp("mount_path", e.target.value)}
              />
            </div>
          </div>
        );
        
      case "vast_start":
      case "vast_stop":
      case "vast_destroy":
        return (
          <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg">
            <p className="text-sm text-blue-700">
              Uses the recipe target host (selected when you run the recipe).
            </p>
          </div>
        );

      case "vast_copy":
        return <VastCopyOpFields opData={opData} updateOp={updateOp} />;
        
      case "tmux_new":
        return (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Host</span>
              <Input
                placeholder="${host}"
                value={opData.host_id as string}
                onChange={(e) => updateOp("host_id", e.target.value)}
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Session</span>
              <Input
                placeholder="train"
                value={opData.session_name as string}
                onChange={(e) => updateOp("session_name", e.target.value)}
              />
            </div>
            <div className="flex items-start gap-2">
              <span className="text-sm text-muted-foreground w-20 pt-2">Command</span>
              <Textarea
                placeholder="Optional initial command"
                value={(opData.command as string) ?? ""}
                onChange={(e) => updateOp("command", e.target.value.trim() ? e.target.value : null)}
                rows={2}
                className="flex-1 font-mono text-sm"
              />
            </div>
          </div>
        );
        
      case "tmux_send":
        return (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Host</span>
              <Input
                placeholder="${host}"
                value={opData.host_id as string}
                onChange={(e) => updateOp("host_id", e.target.value)}
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Session</span>
              <Input
                placeholder="train"
                value={opData.session_name as string}
                onChange={(e) => updateOp("session_name", e.target.value)}
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Keys</span>
              <Input
                placeholder="C-c or Enter"
                value={opData.keys as string}
                onChange={(e) => updateOp("keys", e.target.value)}
                className="font-mono"
              />
            </div>
          </div>
        );
        
      case "sleep":
        return (
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground w-20">Duration</span>
            <div className="relative max-w-[120px]">
              <Input
                type="number"
                inputMode="numeric"
                placeholder="60"
                value={String(opData.duration_secs ?? 5)}
                onChange={(e) => updateOp("duration_secs", parseInt(e.target.value, 10) || 5)}
                className="pr-10"
              />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">sec</span>
            </div>
          </div>
        );

      case "wait_condition":
        return (
          <div className="space-y-3">
            <ConditionEditor
              condition={opData.condition}
              onChange={(c) => updateOp("condition", c)}
            />
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground w-20">Timeout</span>
                <div className="relative max-w-[100px]">
                  <Input
                    type="number"
                    inputMode="numeric"
                    placeholder="300"
                    value={String(opData.timeout_secs ?? 300)}
                    onChange={(e) => updateOp("timeout_secs", parseInt(e.target.value, 10) || 300)}
                    className="pr-10"
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground text-xs">sec</span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">Poll every</span>
                <div className="relative max-w-[80px]">
                  <Input
                    type="number"
                    inputMode="numeric"
                    placeholder="10"
                    value={String(opData.poll_interval_secs ?? 10)}
                    onChange={(e) => updateOp("poll_interval_secs", parseInt(e.target.value, 10) || 10)}
                    className="pr-10"
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground text-xs">sec</span>
                </div>
              </div>
            </div>
          </div>
        );

      case "assert":
        return (
          <div className="space-y-3">
            <ConditionEditor
              condition={opData.condition}
              onChange={(c) => updateOp("condition", c)}
            />
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Message</span>
              <Input
                placeholder="Error message if assertion fails"
                value={(opData.message as string) ?? ""}
                onChange={(e) => updateOp("message", e.target.value.trim() ? e.target.value : null)}
              />
            </div>
          </div>
        );
        
      case "set_var":
        return (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Name</span>
              <Input
                placeholder="my_var"
                value={opData.name as string}
                onChange={(e) => updateOp("name", e.target.value)}
                className="font-mono"
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Value</span>
              <Input
                placeholder="value"
                value={opData.value as string}
                onChange={(e) => updateOp("value", e.target.value)}
              />
            </div>
          </div>
        );
        
      case "http_request":
        return (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Method</span>
              <Select value={(opData.method as string) || "GET"} onValueChange={(value) => updateOp("method", value)}>
                <SelectTrigger className="max-w-[140px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="GET">GET</SelectItem>
                  <SelectItem value="POST">POST</SelectItem>
                  <SelectItem value="PUT">PUT</SelectItem>
                  <SelectItem value="DELETE">DELETE</SelectItem>
                  <SelectItem value="PATCH">PATCH</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">URL</span>
              <Input
                placeholder="https://api.example.com"
                value={opData.url as string}
                onChange={(e) => updateOp("url", e.target.value)}
              />
            </div>
          </div>
        );
        
      case "notify":
        return (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-20">Title</span>
              <Input
                placeholder="Training Complete"
                value={opData.title as string}
                onChange={(e) => updateOp("title", e.target.value)}
              />
            </div>
            <div className="flex items-start gap-2">
              <span className="text-sm text-muted-foreground w-20 pt-2">Message</span>
              <Textarea
                placeholder="Optional message body"
                value={(opData.message as string) ?? ""}
                onChange={(e) => updateOp("message", e.target.value.trim() ? e.target.value : null)}
                rows={2}
                className="flex-1"
              />
            </div>
          </div>
        );
        
      default:
        return <p className="text-sm text-muted-foreground">No parameters</p>;
    }
  };
  
  return (
    <Reorder.Item
      value={step}
      dragListener={false}
      dragControls={dragControls}
      className="relative"
    >
      {/* Flow connector line */}
      {!isFirst && (
        <div className="absolute left-1/2 -translate-x-1/2 -top-4 w-0.5 h-4 bg-foreground/20" />
      )}
      
      <motion.div
        className="rounded-2xl overflow-hidden shadow-md border"
        style={{ 
          backgroundColor: category.lightColor,
          borderColor: category.color + "40",
        }}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -20 }}
        whileHover={{ scale: 1.01 }}
        transition={{ duration: 0.2 }}
      >
        {/* Header */}
        <div 
          className={`flex items-center gap-3 px-4 cursor-pointer select-none transition-all ${isExpanded ? 'py-3' : 'py-2'}`}
          onClick={() => setIsExpanded(!isExpanded)}
        >
          {/* Drag handle */}
          <div
            className="cursor-grab active:cursor-grabbing transition-colors"
            style={{ color: category.color + "80" }}
            onPointerDown={(e) => dragControls.start(e)}
          >
            <IconDrag />
          </div>
          
          {/* Icon */}
          <span className={`transition-all ${isExpanded ? 'text-2xl' : 'text-xl'}`}>{opDef.icon}</span>
          
          {/* Title, ID, and Summary */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h4 
                className={`font-semibold truncate transition-all flex-shrink-0 ${isExpanded ? 'text-base' : 'text-sm'}`}
                style={{ color: category.color }}
              >
                {step.name || opDef.label}
              </h4>
              {/* Summary when collapsed */}
              {!isExpanded && opData && (
                <span 
                  className="text-xs truncate opacity-60 font-mono"
                  style={{ color: category.color }}
                >
                  {getOperationSummary(opType, opData)}
                </span>
              )}
            </div>
            {isExpanded && (
              <p className="text-xs font-mono" style={{ color: category.color + "80" }}>{step.id}</p>
            )}
          </div>
          
          {/* Actions */}
          <div className="flex items-center gap-1">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8 hover:bg-black/5"
                  style={{ color: category.color + "80" }}
                  onClick={onDelete}
                  aria-label="Delete step"
                >
                  <IconTrash />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Delete step</TooltipContent>
            </Tooltip>
            
            <motion.div
              animate={{ rotate: isExpanded ? 180 : 0 }}
              transition={{ duration: 0.2 }}
              style={{ color: category.color + "80" }}
            >
              <IconChevronDown />
            </motion.div>
          </div>
        </div>
        
        {/* Content */}
        <motion.div
          initial={false}
          animate={{ 
            height: isExpanded ? "auto" : 0,
            opacity: isExpanded ? 1 : 0,
          }}
          transition={{ duration: 0.2 }}
          className="overflow-hidden"
        >
          <div className="px-4 pb-4 space-y-4">
            {/* Operation fields */}
            {renderOperationFields()}
            
            {/* Dependencies */}
            {step.depends_on.length > 0 && (
              <div 
                className="flex items-center gap-2 pt-2 border-t"
                style={{ borderColor: category.color + "20" }}
              >
                <span className="text-xs" style={{ color: category.color + "80" }}>Depends on:</span>
                {step.depends_on.map((dep) => (
                  <Badge
                    key={dep} 
                    variant="outline"
                    className="text-xs border-transparent"
                    style={{ 
                      backgroundColor: category.color + "20",
                      color: category.color,
                    }}
                  >
                    {dep}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        </motion.div>
      </motion.div>
      
      {/* Add step button between blocks */}
      {!isLast && (
        <div className="absolute left-1/2 -translate-x-1/2 -bottom-4 z-10 opacity-0 hover:opacity-100 transition-opacity">
          <div className="w-0.5 h-4 bg-foreground/20 mx-auto" />
        </div>
      )}
    </Reorder.Item>
  );
}

// Action Palette Component
function ActionPalette({ onSelect }: { onSelect: (opType: string) => void }) {
  const groupedOps = OPERATION_TYPES.reduce((acc, op) => {
    if (!acc[op.category]) acc[op.category] = [];
    acc[op.category].push(op);
    return acc;
  }, {} as Record<OperationCategory, OperationDef[]>);
  
  return (
    <div className="space-y-4">
      {(Object.entries(groupedOps) as [OperationCategory, OperationDef[]][]).map(([cat, ops]) => (
        <div key={cat}>
          <h4 className="text-xs font-semibold text-foreground/50 uppercase tracking-wider mb-2 px-2">
            {OPERATION_CATEGORIES[cat].label}
          </h4>
          <div className="space-y-1">
            {ops.map((op) => (
              <Button
                key={op.key}
                type="button"
                variant="ghost"
                className="w-full justify-start h-auto gap-3 px-3 py-2.5 rounded-xl hover:bg-accent transition-colors text-left group"
                onClick={() => onSelect(op.key)}
              >
                <span 
                  className="w-8 h-8 rounded-lg flex items-center justify-center text-lg"
                  style={{ backgroundColor: OPERATION_CATEGORIES[op.category].color + "20" }}
                >
                  {op.icon}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-sm">{op.label}</p>
                  <p className="text-xs text-foreground/50 truncate">{op.description}</p>
                </div>
              </Button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export function RecipeEditorPage() {
  const params = useParams({ from: "/recipes/$path" });
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const routePath = decodeURIComponent(params.path);
  const terminalContext = useTerminalOptional();
  
  const recipePathRef = useRef(routePath);
  useEffect(() => {
    recipePathRef.current = routePath;
  }, [routePath]);

  const recipeQuery = useRecipe(routePath);
  const saveMutation = useSaveRecipe();
  const validateMutation = useValidateRecipe();
  
  const [isVarsOpen, setIsVarsOpen] = useState(false);
  const [isTargetOpen, setIsTargetOpen] = useState(false);
  const [isHostSelectOpen, setIsHostSelectOpen] = useState(false);
  const [isRunErrorOpen, setIsRunErrorOpen] = useState(false);

  const onVarsOpen = () => setIsVarsOpen(true);
  const onVarsClose = () => setIsVarsOpen(false);
  const onTargetOpen = () => setIsTargetOpen(true);
  const onTargetClose = () => setIsTargetOpen(false);
  const onHostSelectOpen = () => setIsHostSelectOpen(true);
  const onHostSelectClose = () => setIsHostSelectOpen(false);
  const onRunErrorOpen = () => setIsRunErrorOpen(true);
  const onRunErrorClose = () => setIsRunErrorOpen(false);
  
  const [recipe, setRecipe] = useState<Recipe | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [saveStatus, setSaveStatus] = useState<'saved' | 'saving' | 'error'>('saved');
  const [selectedHostId, setSelectedHostId] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  
  // Ref to track last saved recipe for comparison
  const lastSavedRecipeRef = useRef<string>('');
  // Track if we've loaded data (to skip initial save)
  const hasLoadedRef = useRef(false);
  
  // Load hosts for selection
  const { data: hosts = [] } = useHosts();
  const vastQuery = useVastInstances();
  
  // Debounced save function using use-debounce
  // This is more reliable than manual setTimeout as it properly handles closure values
  const debouncedSave = useDebouncedCallback(
    async (recipeToSave: Recipe) => {
      const recipeJson = JSON.stringify(recipeToSave);
      
      // Skip if no actual changes
      if (recipeJson === lastSavedRecipeRef.current) {
        return;
      }
      
      setSaveStatus('saving');
      try {
        const currentPath = recipePathRef.current;
        const newPath = await saveMutation.mutateAsync({ path: currentPath, recipe: recipeToSave });
        if (newPath !== currentPath) {
          recipePathRef.current = newPath;
          navigate({
            to: "/recipes/$path",
            params: { path: encodeURIComponent(newPath) },
            replace: true,
          });
        }
        lastSavedRecipeRef.current = recipeJson;
        setSaveStatus('saved');
      } catch (e) {
        console.error("Failed to save recipe:", e);
        setSaveStatus('error');
      }
    },
    500, // 500ms debounce
    { maxWait: 2000 } // Max 2s wait to ensure saves happen
  );
  
  // Load (and refresh) recipe data from the query cache.
  // If the user has unsaved local edits, don't overwrite the editor state.
  useEffect(() => {
    if (!recipeQuery.data) return;

    const incomingJson = JSON.stringify(recipeQuery.data);

    setRecipe((current) => {
      if (!current) {
        lastSavedRecipeRef.current = incomingJson;
        hasLoadedRef.current = true;
        return recipeQuery.data;
      }

      const currentJson = JSON.stringify(current);
      const hasUnsavedChanges = currentJson !== lastSavedRecipeRef.current;
      if (hasUnsavedChanges || currentJson === incomingJson) {
        return current;
      }

      lastSavedRecipeRef.current = incomingJson;
      return recipeQuery.data;
    });
  }, [recipeQuery.data]);
  
  // Auto-save effect - triggers debounced save when recipe changes
  useEffect(() => {
    if (!recipe || !hasLoadedRef.current) return;
    
    // Check if recipe actually changed from last saved version
    const recipeJson = JSON.stringify(recipe);
    if (recipeJson === lastSavedRecipeRef.current) {
      return; // No changes, skip save
    }
    
    // Trigger debounced save with current recipe
    debouncedSave(recipe);
  }, [recipe, debouncedSave]);
  
  // Flush pending saves on unmount
  useEffect(() => {
    return () => {
      debouncedSave.flush();
    };
  }, [debouncedSave]);
  
  // Validate on changes
  useEffect(() => {
    if (recipe) {
      validateMutation.mutate(recipe, {
        onSuccess: setValidation,
      });
    }
  }, [recipe]);
  
  const handleRunClick = () => {
    if (!recipe) return;
    if (!validation?.valid) {
      setRunError("Recipe is invalid. Fix validation errors before running.");
      onRunErrorOpen();
      return;
    }
    
    // If recipe has a target defined, show host selection modal
    if (recipe.target) {
      setSelectedHostId(null);
      onHostSelectOpen();
    } else {
      // No target, run directly
      executeRun();
    }
  };
  
  const executeRun = async (targetHostId?: string) => {
    if (!recipe || !validation?.valid) return;
    
    setIsRunning(true);
    try {
      // Ensure any pending save is completed before running
      await debouncedSave.flush();
      const runPath = recipePathRef.current;
      
      // Build variables with target host if selected
      const variables: Record<string, string> = {};
      if (targetHostId) {
        variables.target = targetHostId;
      }
      
      // Use interactive execution to run in terminal
      const execution = await interactiveRecipeApi.run({
        path: runPath,
        hostId: targetHostId || "__local__",
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
      navigate({ to: "/terminal", search: { connectHostId: undefined, connectVastInstanceId: undefined, connectLabel: undefined } });
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
  
  const handleConfirmRun = () => {
    if (!selectedHostId && recipe?.target) {
      return; // Must select a host or local
    }
    onHostSelectClose();
    // Pass __local__ for local execution, or the host id
    executeRun(selectedHostId || undefined);
  };
  
  // Filter hosts based on target requirements
  const allHosts: Host[] = [
    ...hosts,
    ...(vastQuery.data ?? []).map(vastInstanceToHostCandidate),
  ];

  const compatibleHosts = allHosts.filter((host: Host) => {
    if (!recipe?.target) return true;
    
    // "any" type allows all hosts
    if (recipe.target.type === "any") {
      // Still apply GPU/memory filters if specified
    } else if (recipe.target.type === "local") {
      // Local target doesn't need remote hosts
      return false;
    } else {
      // Check host type for specific types
      if (recipe.target.type !== host.type) return false;
    }
    
    // Check GPU count
    if (recipe.target.min_gpus && (host.num_gpus ?? 0) < recipe.target.min_gpus) return false;
    
    // Check GPU type (case-insensitive partial match)
    if (recipe.target.gpu_type && host.gpu_name) {
      if (!host.gpu_name.toLowerCase().includes(recipe.target.gpu_type.toLowerCase())) {
        return false;
      }
    }
    
    // Check memory
    if (recipe.target.min_memory_gb && host.system_info?.memory_total_gb) {
      if (host.system_info.memory_total_gb < recipe.target.min_memory_gb) return false;
    }
    
    return true;
  });
  
  // Check if Local option should be shown (for "any" or "local" target types)
  const showLocalOption = recipe?.target?.type === "any" || recipe?.target?.type === "local";
  
  const updateRecipe = (updates: Partial<Recipe>) => {
    if (!recipe) return;
    setRecipe({ ...recipe, ...updates });
  };
  
  const addStep = (opType: string) => {
    if (!recipe) return;
    
    // Generate step ID based on operation type
    // Convert underscores to hyphens (e.g., "run_commands" -> "run-commands", "tmux_new" -> "tmux-new")
    const prefix = opType.replace(/_/g, "-");
    
    // Count existing steps with the same prefix
    const existingCount = recipe.steps.filter(s => s.id.startsWith(prefix + "-")).length;
    const newId = `${prefix}-${existingCount + 1}`;
    
    const newStep = createEmptyStep(newId, opType);
    
    // Auto-add dependency on previous step for sequential execution
    if (recipe.steps.length > 0) {
      const lastStep = recipe.steps[recipe.steps.length - 1];
      newStep.depends_on = [lastStep.id];
    }
    
    updateRecipe({ steps: [...recipe.steps, newStep] });
  };
  
  const updateStep = (stepId: string, newStep: Step) => {
    if (!recipe) return;
    const steps = recipe.steps.map(s => s.id === stepId ? newStep : s);
    updateRecipe({ steps });
  };
  
  const deleteStep = (stepId: string) => {
    if (!recipe) return;
    
    // Find the step being deleted and its position
    const stepIndex = recipe.steps.findIndex(s => s.id === stepId);
    if (stepIndex === -1) return;
    
    // Get remaining steps
    let newSteps = recipe.steps.filter(s => s.id !== stepId);
    
    // Fix broken dependencies: if a step depended on the deleted step,
    // make it depend on what the deleted step depended on
    const deletedStep = recipe.steps[stepIndex];
    newSteps = newSteps.map(s => {
      if (s.depends_on.includes(stepId)) {
        // Replace dependency on deleted step with deleted step's dependencies
        const newDeps = s.depends_on.filter(d => d !== stepId);
        newDeps.push(...deletedStep.depends_on);
        return { ...s, depends_on: [...new Set(newDeps)] };
      }
      return s;
    });
    
    updateRecipe({ steps: newSteps });
  };
  
  const handleReorder = (newOrder: Step[]) => {
    // Update dependencies to maintain sequential order
    const updatedSteps = newOrder.map((step, index) => {
      if (index === 0) {
        // First step has no dependencies
        return { ...step, depends_on: [] };
      } else {
        // Each step depends on the previous one
        return { ...step, depends_on: [newOrder[index - 1].id] };
      }
    });
    updateRecipe({ steps: updatedSteps });
  };
  
  const updateVariable = (key: string, value: string) => {
    if (!recipe) return;
    const variables = { ...recipe.variables };
    if (value) {
      variables[key] = value;
    } else {
      delete variables[key];
    }
    updateRecipe({ variables });
  };
  
  if (recipeQuery.isLoading || !recipe) {
    return (
      <div className="h-full flex flex-col overflow-hidden">
        {/* Skeleton Header */}
        <header className="flex items-center gap-4 px-4 h-14 border-b border-border bg-background">
          <Skeleton className="w-8 h-8 rounded-lg" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3">
              <Skeleton className="h-6 w-48 rounded-lg" />
              <Skeleton className="h-5 w-20 rounded-lg" />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Skeleton className="h-8 w-24 rounded-lg" />
            <Skeleton className="h-8 w-28 rounded-lg" />
            <Skeleton className="h-8 w-16 rounded-lg" />
          </div>
        </header>

        {/* Skeleton Main Content */}
        <div className="flex-1 flex overflow-hidden">
          {/* Steps Canvas */}
          <div className="flex-1 overflow-auto">
            <div className="p-8 max-w-2xl mx-auto space-y-6">
              {[1, 2, 3].map((i) => (
                <div key={i} className="rounded-2xl overflow-hidden shadow-md border border-border p-4">
                  <div className="flex items-center gap-3 mb-4">
                    <Skeleton className="w-6 h-6 rounded" />
                    <Skeleton className="w-10 h-10 rounded-lg" />
                    <div className="flex-1">
                      <Skeleton className="h-5 w-32 rounded-lg mb-1" />
                      <Skeleton className="h-3 w-24 rounded-lg" />
                    </div>
                    <Skeleton className="w-8 h-8 rounded-lg" />
                  </div>
                  <div className="space-y-3">
                    <Skeleton className="h-10 w-full rounded-lg" />
                    <Skeleton className="h-24 w-full rounded-lg" />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Action Palette Sidebar Skeleton */}
          <div className="w-72 border-l border-border bg-background flex flex-col">
            <div className="p-4 border-b border-border">
              <Skeleton className="h-5 w-20 rounded-lg mb-1" />
              <Skeleton className="h-3 w-32 rounded-lg" />
            </div>
            <div className="flex-1 p-3 space-y-4">
              {[1, 2, 3, 4].map((i) => (
                <div key={i}>
                  <Skeleton className="h-3 w-16 rounded mb-2" />
                  <div className="space-y-1">
                    {[1, 2].map((j) => (
                      <div key={j} className="flex items-center gap-3 px-3 py-2.5">
                        <Skeleton className="w-8 h-8 rounded-lg" />
                        <div className="flex-1">
                          <Skeleton className="h-4 w-20 rounded mb-1" />
                          <Skeleton className="h-3 w-32 rounded" />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }
  
  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <header className="flex items-center gap-4 px-4 h-14 border-b border-border bg-background">
        {/* Left: Back button */}
        <Button asChild variant="ghost" size="icon" className="h-8 w-8">
          <Link to="/recipes">
            <IconArrowLeft />
          </Link>
        </Button>
        
        {/* Center: Title and info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3">
            <Input
              type="text"
              value={recipe.name}
              onChange={(e) => updateRecipe({ name: e.target.value })}
              className="h-9 px-0 py-0 text-lg font-semibold bg-transparent border-0 shadow-none focus-visible:ring-0 focus-visible:ring-offset-0 min-w-0 max-w-[300px]"
              placeholder="Recipe name"
            />
            {saveStatus === 'saving' && (
              <Badge variant="outline" className="gap-1 bg-primary/10 border-primary/20 text-primary">
                <Loader2 className="w-3 h-3 animate-spin" />
                Saving...
              </Badge>
            )}
            {saveStatus === 'error' && (
              <Badge variant="destructive">Save failed</Badge>
            )}
            <span className="text-xs text-muted-foreground flex items-center gap-1">
              {recipe.steps.length} steps •
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="inline-flex items-center gap-1">
                    <span>v</span>
                  <Input
                    type="text"
                    value={recipe.version}
                    onChange={(e) => updateRecipe({ version: e.target.value })}
                    className="h-6 w-12 text-xs bg-transparent border-0 shadow-none px-1 py-0 hover:bg-muted focus:bg-muted focus-visible:ring-0 focus-visible:ring-offset-0"
                    placeholder="1.0.0"
                  />
                  </span>
                </TooltipTrigger>
                <TooltipContent>Recipe version (for tracking changes)</TooltipContent>
              </Tooltip>
            </span>
          </div>
        </div>
        
        {/* Right: Status and actions */}
        <div className="flex items-center gap-2">
          {validation && !validation.valid && (
            <Badge variant="destructive" className="gap-1">
              <IconWarning className="w-3.5 h-3.5" />
              {validation.errors.length} errors
            </Badge>
          )}
          {validation?.valid && (
            <Badge className="gap-1 bg-green-500 text-white border-transparent">
              <IconCheck className="w-3.5 h-3.5" />
              Valid
            </Badge>
          )}
          
          <Button
            size="sm"
            variant="outline"
            onClick={onTargetOpen}
          >
            <IconTarget />
            Target
            {recipe?.target && (
              <Badge variant="outline" className="ml-1">
                {recipe.target.type}
              </Badge>
            )}
          </Button>
          
          <Button
            size="sm"
            variant="outline"
            onClick={onVarsOpen}
          >
            <IconVariable />
            Variables
          </Button>
          
          <Button
            size="sm"
            onClick={handleRunClick}
            disabled={!validation?.valid || isRunning}
          >
            {isRunning ? <Loader2 className="w-4 h-4 animate-spin" /> : <IconPlay />}
            Run
          </Button>
        </div>
      </header>
      
      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Steps Canvas */}
        <div className="flex-1 overflow-auto">
          <div className="p-8 max-w-2xl mx-auto">
            {recipe.steps.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20">
                <div className="w-20 h-20 rounded-3xl bg-muted/50 border border-border flex items-center justify-center mb-4">
                  <span className="text-4xl">📜</span>
                </div>
                <h3 className="text-lg font-semibold mb-2">No steps yet</h3>
                <p className="text-muted-foreground text-center mb-6 max-w-sm">
                  Add actions from the palette on the right to build your recipe workflow.
                </p>
              </div>
            ) : (
              <Reorder.Group
                axis="y"
                values={recipe.steps}
                onReorder={handleReorder}
                className="space-y-6"
              >
                {recipe.steps.map((step, index) => (
                  <StepBlock
                    key={step.id}
                    step={step}
                    onChange={(s) => updateStep(step.id, s)}
                    onDelete={() => deleteStep(step.id)}
                    isFirst={index === 0}
                    isLast={index === recipe.steps.length - 1}
                  />
                ))}
              </Reorder.Group>
            )}
            
            {/* Validation Errors */}
            {validation && validation.errors.length > 0 && (
              <Card className="mt-8 border border-danger/50 bg-danger/5">
                <div className="p-4">
                  <h3 className="font-semibold text-danger mb-2 flex items-center gap-2">
                    <IconWarning />
                    Validation Errors
                  </h3>
                  <ul className="list-disc list-inside space-y-1">
                    {validation.errors.map((error, i) => (
                      <li key={i} className="text-sm text-danger">
                        {error.step_id && <span className="font-mono">[{error.step_id}]</span>} {error.message}
                      </li>
                    ))}
                  </ul>
                </div>
              </Card>
            )}
          </div>
        </div>
        
        {/* Action Palette Sidebar */}
        <div className="w-72 border-l border-border bg-background flex flex-col">
          <div className="p-4 border-b border-border">
            <h3 className="font-semibold">Actions</h3>
            <p className="text-xs text-muted-foreground">Click to add to recipe</p>
          </div>
          <ScrollArea className="flex-1 p-3">
            <ActionPalette onSelect={addStep} />
          </ScrollArea>
        </div>
      </div>
      
      {/* Variables Modal */}
      <Dialog open={isVarsOpen} onOpenChange={setIsVarsOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <IconVariable />
              Variables
            </DialogTitle>
          </DialogHeader>

          <div className="grid gap-4">
            <p className="text-sm text-muted-foreground">
              Define variables that can be used in step parameters with{" "}
              <code className="rounded bg-muted px-1 font-mono text-xs">${"{name}"}</code> syntax.
            </p>
            
            {Object.keys(recipe.variables).length === 0 ? (
              <div className="text-center py-8">
                <p className="text-muted-foreground mb-4">No variables defined yet.</p>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => updateVariable(`var_${Object.keys(recipe.variables).length + 1}`, "")}
                >
                  <IconPlus />
                  Add Variable
                </Button>
              </div>
            ) : (
              <div className="space-y-3">
                {Object.entries(recipe.variables).map(([key, value]) => (
                  <div key={key} className="flex items-center gap-2">
                    <div className="relative flex-1">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground">$</span>
                      <Input
                        placeholder="name"
                        value={key}
                        onChange={(e) => {
                          const newKey = e.target.value;
                          const vars = { ...recipe.variables };
                          delete vars[key];
                          vars[newKey] = value;
                          updateRecipe({ variables: vars });
                        }}
                        className="pl-7"
                      />
                    </div>
                    <Input
                      placeholder="value"
                      value={value}
                      onChange={(e) => updateVariable(key, e.target.value)}
                      className="flex-1"
                    />
                    <Button
                      size="icon"
                      variant="ghost"
                      className="text-danger hover:text-danger"
                      onClick={() => {
                        const vars = { ...recipe.variables };
                        delete vars[key];
                        updateRecipe({ variables: vars });
                      }}
                      aria-label={`Delete variable ${key}`}
                    >
                      <IconTrash />
                    </Button>
                  </div>
                ))}
                
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => updateVariable(`var_${Object.keys(recipe.variables).length + 1}`, "")}
                  className="w-full mt-2"
                >
                  <IconPlus />
                  Add Variable
                </Button>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button onClick={onVarsClose}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      
      {/* Target Requirements Modal */}
      <Dialog open={isTargetOpen} onOpenChange={setIsTargetOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <IconTarget />
              Target Host Requirements
            </DialogTitle>
          </DialogHeader>

          <div className="grid gap-4">
            <p className="text-sm text-muted-foreground">
              Define requirements for the target host. The actual host will be selected when running the recipe.
            </p>
            
            <div className="space-y-4">
              {/* Host Type */}
              <div className="flex items-center gap-4">
                <span className="text-sm font-medium w-24">Host Type</span>
                <Select
                  value={recipe?.target?.type ?? "__none__"}
                  onValueChange={(value) => {
                    if (value === "__none__") {
                      updateRecipe({ target: null });
                      return;
                    }

                    updateRecipe({
                      target: {
                        ...(recipe?.target ?? {}),
                        type: value as TargetHostType,
                      } as TargetRequirements,
                    });
                  }}
                >
                  <SelectTrigger className="flex-1">
                    <SelectValue placeholder="Select host type..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">None</SelectItem>
                    <SelectItem value="any">Any (All hosts + Local)</SelectItem>
                    <SelectItem value="local">Local</SelectItem>
                    <SelectItem value="colab">Colab</SelectItem>
                    <SelectItem value="vast">Vast.ai</SelectItem>
                    <SelectItem value="custom">Custom SSH</SelectItem>
                  </SelectContent>
                </Select>
                {recipe?.target && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-danger hover:text-danger"
                    onClick={() => updateRecipe({ target: null })}
                  >
                    Clear
                  </Button>
                )}
              </div>
              
              {recipe?.target && (
                <>
                  {/* GPU Type */}
                  <div className="flex items-center gap-4">
                    <span className="text-sm font-medium w-24">GPU Type</span>
                    <Input
                      placeholder="Any (e.g., T4, A100, H100)"
                      value={recipe.target.gpu_type ?? ""}
                      onChange={(e) =>
                        updateRecipe({
                          target: {
                            ...recipe.target!,
                            gpu_type: e.target.value.trim() ? e.target.value : null,
                          },
                        })
                      }
                      className="flex-1"
                    />
                  </div>
                  
                  {/* Min GPUs */}
                  <div className="flex items-center gap-4">
                    <span className="text-sm font-medium w-24">Min GPUs</span>
                    <Input
                      type="number"
                      inputMode="numeric"
                      placeholder="1"
                      value={recipe.target.min_gpus?.toString() ?? ""}
                      onChange={(e) =>
                        updateRecipe({
                          target: {
                            ...recipe.target!,
                            min_gpus: e.target.value ? parseInt(e.target.value, 10) : null,
                          },
                        })
                      }
                      className="max-w-[100px]"
                    />
                  </div>
                  
                  {/* Min Memory */}
                  <div className="flex items-center gap-4">
                    <span className="text-sm font-medium w-24">Min Memory</span>
                    <div className="relative max-w-[100px]">
                      <Input
                        type="number"
                        inputMode="decimal"
                        placeholder="16"
                        value={recipe.target.min_memory_gb?.toString() ?? ""}
                        onChange={(e) =>
                          updateRecipe({
                            target: {
                              ...recipe.target!,
                              min_memory_gb: e.target.value ? parseFloat(e.target.value) : null,
                            },
                          })
                        }
                        className="pr-10"
                      />
                      <span className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground text-xs">GB</span>
                    </div>
                  </div>
                </>
              )}
            </div>
            
            {!recipe?.target && (
              <div className="mt-2 p-4 bg-warning/10 border border-warning/20 rounded-lg">
                <p className="text-sm text-warning">
                  No target defined. Operations that use{" "}
                  <code className="rounded bg-warning/15 px-1 font-mono text-xs">${"{target}"}</code>{" "}
                  will require a host_id to be specified.
                </p>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button onClick={onTargetClose}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      
      {/* Host Selection Modal (shown when running a recipe with target) */}
      <Dialog open={isHostSelectOpen} onOpenChange={setIsHostSelectOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <IconPlay />
              Select Target Host
            </DialogTitle>
          </DialogHeader>

          <div className="grid gap-4">
            {recipe?.target && (
              <div className="rounded-lg border border-primary/20 bg-primary/5 p-3">
                <p className="text-sm font-medium text-primary mb-1">Target Requirements</p>
                <div className="text-sm text-muted-foreground space-y-0.5">
                  <p>
                    Type: <span className="font-medium text-foreground">{recipe.target.type}</span>
                  </p>
                  {recipe.target.gpu_type && (
                    <p>
                      GPU: <span className="font-medium text-foreground">{recipe.target.gpu_type}</span>
                    </p>
                  )}
                  {recipe.target.min_gpus && (
                    <p>
                      Min GPUs: <span className="font-medium text-foreground">{recipe.target.min_gpus}</span>
                    </p>
                  )}
                  {recipe.target.min_memory_gb && (
                    <p>
                      Min Memory:{" "}
                      <span className="font-medium text-foreground">{recipe.target.min_memory_gb} GB</span>
                    </p>
                  )}
                </div>
              </div>
            )}

            {compatibleHosts.length === 0 && !showLocalOption ? (
              <div className="p-6 text-center text-muted-foreground">
                <p className="mb-2">No compatible hosts found</p>
                <p className="text-xs">Add a host that matches the target requirements, or modify the requirements.</p>
              </div>
            ) : (
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground mb-2">
                  Select a target to run this recipe on:
                </p>
                <RadioGroup
                  value={selectedHostId ?? ""}
                  onValueChange={(value) => setSelectedHostId(value || null)}
                >
                  {/* Local option */}
                  {showLocalOption && (
                    <div
                      className={cn(
                        "flex items-start gap-3 rounded-lg border p-3 transition-colors",
                        selectedHostId === "__local__"
                          ? "border-primary bg-primary/5"
                          : "border-border hover:bg-muted/50"
                      )}
                    >
                      <RadioGroupItem value="__local__" id="recipe-target-local" className="mt-0.5" />
                      <Label htmlFor="recipe-target-local" className="flex-1 cursor-pointer font-normal">
                        <div className="flex items-center gap-3">
                          <div className="flex-1">
                            <p className="font-medium text-foreground">Local</p>
                            <p className="text-xs text-muted-foreground">
                              Run on this machine (no SSH)
                            </p>
                          </div>
                          <Badge className="bg-green-500 text-white border-transparent">ready</Badge>
                        </div>
                      </Label>
                    </div>
                  )}

                  {/* Remote hosts */}
                  {compatibleHosts.map((host: Host) => {
                    const id = `recipe-target-${host.id}`;
                    const isSelected = selectedHostId === host.id;
                    const statusVariant =
                      host.status === "offline"
                        ? ("destructive" as const)
                        : ("outline" as const);
                    const statusClassName =
                      host.status === "online"
                        ? "bg-green-500 text-white hover:bg-green-600 border-transparent"
                        : "";

                    return (
                      <div
                        key={host.id}
                        className={cn(
                          "flex items-start gap-3 rounded-lg border p-3 transition-colors",
                          isSelected ? "border-primary bg-primary/5" : "border-border hover:bg-muted/50"
                        )}
                      >
                        <RadioGroupItem value={host.id} id={id} className="mt-0.5" />
                        <Label htmlFor={id} className="flex-1 cursor-pointer font-normal">
                          <div className="flex items-center gap-3">
                            <div className="flex-1">
                              <p className="font-medium text-foreground">{host.name}</p>
                              <p className="text-xs text-muted-foreground">
                                {host.type}
                                {host.gpu_name && ` • ${host.gpu_name}`}
                                {host.num_gpus && host.num_gpus > 1 && ` (×${host.num_gpus})`}
                                {host.system_info?.memory_total_gb &&
                                  ` • ${host.system_info.memory_total_gb.toFixed(0)} GB RAM`}
                              </p>
                            </div>
                            <Badge variant={statusVariant} className={statusClassName}>{host.status}</Badge>
                          </div>
                        </Label>
                      </div>
                    );
                  })}
                </RadioGroup>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={onHostSelectClose}>
              Cancel
            </Button>
            <Button
              onClick={handleConfirmRun}
              disabled={(!selectedHostId && recipe?.target !== undefined) || isRunning}
            >
              {isRunning && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
              {selectedHostId === "__local__" ? "Run Locally" : "Run on Selected Host"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={isRunErrorOpen} onOpenChange={setIsRunErrorOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Failed to run recipe</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-danger whitespace-pre-wrap">{runError ?? "Unknown error"}</p>
          <DialogFooter>
            <Button variant="outline" onClick={onRunErrorClose}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

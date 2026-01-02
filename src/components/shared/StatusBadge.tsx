import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { HostStatus, InteractiveStatus } from "../../lib/types";

type StatusType = HostStatus | InteractiveStatus | "uploading" | "created" | "stopped";

type StatusBadgeVariant =
  | "default"
  | "secondary"
  | "destructive"
  | "outline";

const statusConfig: Record<StatusType, { variant: StatusBadgeVariant; label: string; className?: string }> = {
  pending: { variant: "outline", label: "Pending" },
  running: { variant: "default", label: "Running", className: "bg-success text-success-foreground hover:bg-success/90" },
  paused: { variant: "secondary", label: "Paused", className: "bg-warning text-warning-foreground hover:bg-warning/90" },
  completed: { variant: "secondary", label: "Completed" },
  failed: { variant: "destructive", label: "Failed" },
  cancelled: { variant: "outline", label: "Cancelled" },
  waiting_for_input: { variant: "secondary", label: "Waiting for Input" },
  created: { variant: "outline", label: "Created" },
  uploading: { variant: "default", label: "Uploading" },
  stopped: { variant: "secondary", label: "Stopped", className: "bg-warning text-warning-foreground hover:bg-warning/90" },
  online: { variant: "default", label: "Online", className: "bg-success text-success-foreground hover:bg-success/90" },
  offline: { variant: "outline", label: "Offline" },
  connecting: { variant: "default", label: "Connecting" },
  error: { variant: "destructive", label: "Error" },
};

type StatusBadgeProps = {
  status: StatusType;
  size?: "sm" | "md" | "lg";
  className?: string;
};

export function StatusBadge({ status, size = "sm", className }: StatusBadgeProps) {
  const cfg = statusConfig[status] ?? { variant: "outline" as const, label: String(status) };

  const sizeClassName =
    size === "lg"
      ? "px-3 py-1 text-sm"
      : size === "md"
      ? "px-2.5 py-0.5 text-xs"
      : "px-2 py-0.5 text-xs";

  return (
    <Badge variant={cfg.variant} className={cn("gap-1", sizeClassName, cfg.className, className)}>
      {cfg.label}
    </Badge>
  );
}

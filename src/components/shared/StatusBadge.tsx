import { Chip } from "@nextui-org/react";
import type { ExecutionStatus, HostStatus } from "../../lib/types";

type StatusType = ExecutionStatus | HostStatus | "uploading" | "created" | "stopped";

const statusConfig: Record<StatusType, { color: "success" | "warning" | "danger" | "default" | "primary" | "secondary"; label: string }> = {
  // Execution statuses
  pending: { color: "default", label: "Pending" },
  running: { color: "success", label: "Running" },
  paused: { color: "warning", label: "Paused" },
  completed: { color: "secondary", label: "Completed" },
  failed: { color: "danger", label: "Failed" },
  cancelled: { color: "default", label: "Cancelled" },
  // Legacy/compat statuses
  created: { color: "default", label: "Created" },
  uploading: { color: "primary", label: "Uploading" },
  stopped: { color: "warning", label: "Stopped" },
  // Host statuses
  online: { color: "success", label: "Online" },
  offline: { color: "default", label: "Offline" },
  connecting: { color: "primary", label: "Connecting" },
  error: { color: "danger", label: "Error" },
};

type StatusBadgeProps = {
  status: StatusType;
  size?: "sm" | "md" | "lg";
  variant?: "flat" | "solid" | "bordered" | "light" | "faded" | "shadow" | "dot";
};

export function StatusBadge({ status, size = "sm", variant = "flat" }: StatusBadgeProps) {
  const config = statusConfig[status] ?? { color: "default", label: status };

  return (
    <Chip size={size} variant={variant} color={config.color}>
      {config.label}
    </Chip>
  );
}

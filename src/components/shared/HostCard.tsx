import { useState, type ReactNode } from "react";
import { Edit2 } from "lucide-react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { AppIcon } from "@/components/AppIcon";
import type { Host, VastInstance } from "@/lib/types";
import { getGpuModelShortName } from "@/lib/gpu";
import { cn } from "@/lib/utils";

// Small tag component
function Tag({ children, variant = "default" }: { children: ReactNode; variant?: "default" | "primary" | "warning" }) {
  const colors = {
    default: "bg-muted/40 text-muted-foreground",
    primary: "bg-muted/40 text-muted-foreground",
    warning: "bg-muted/40 text-muted-foreground",
  };
  return (
    <span className={cn("inline-flex items-center px-1 py-px rounded text-[10px] font-normal whitespace-nowrap", colors[variant])}>
      {children}
    </span>
  );
}

// Termius-style minimal host row/card - max 2 lines
type HostRowProps = {
  icon: ReactNode;
  title: string;
  subtitle?: string;
  rightTags?: { label: string; variant?: "default" | "primary" | "warning" }[];
  isOnline?: boolean;
  isSelected?: boolean;
  onClick?: () => void;
  onDoubleClick?: () => void;
  onEdit?: () => void;
  hoverActions?: ReactNode;
  className?: string;
};

export function HostRow({
  icon,
  title,
  subtitle,
  rightTags,
  isOnline = false,
  isSelected = false,
  onClick,
  onDoubleClick,
  onEdit,
  hoverActions,
  className = "",
}: HostRowProps) {
  const [isHovered, setIsHovered] = useState(false);

  return (
    <div
      className={cn(
        "termius-host-row",
        isSelected && "termius-host-row-selected",
        isHovered && "termius-host-row-hover",
        className
      )}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
    >
      {/* Icon with status dot */}
      <div className="relative flex-shrink-0">
        <div className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center">
          {icon}
        </div>
        {/* Status dot */}
        <span
          className={cn(
            "absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-muted",
            isOnline ? "bg-success" : "bg-foreground/30"
          )}
        />
      </div>

      {/* Info - left side */}
      <div className="flex-1 min-w-0 ml-3">
        <h3 className="text-sm font-normal text-foreground/70 truncate leading-tight">{title}</h3>
        {subtitle && (
          <p className="text-[11px] text-foreground/50 truncate leading-tight">{subtitle}</p>
        )}
      </div>

      {/* Right side - tags or hover actions (fixed size container) */}
      <div className="flex items-center justify-end ml-2 flex-shrink-0 min-w-[80px]">
        {isHovered && (hoverActions || onEdit) ? (
          <div className="flex items-center">
            {hoverActions ? (
              hoverActions
            ) : onEdit ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="w-7 h-7 min-w-7 opacity-60 hover:opacity-100 p-0"
                    onClick={(e) => {
                      e.stopPropagation();
                      onEdit();
                    }}
                  >
                    <Edit2 className="w-3.5 h-3.5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Edit</TooltipContent>
              </Tooltip>
            ) : null}
          </div>
        ) : (
          <div className="flex flex-col items-end gap-0.5 max-h-[36px] overflow-hidden">
            {rightTags && rightTags.length > 0 && rightTags.slice(0, 2).map((tag, i) => (
              <Tag key={i} variant={tag.variant}>{tag.label}</Tag>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// Saved Host row
type SavedHostRowProps = {
  host: Host;
  isSelected?: boolean;
  onClick?: () => void;
  onDoubleClick?: () => void;
  onEdit?: () => void;
};

export function SavedHostRow({
  host,
  isSelected,
  onClick,
  onDoubleClick,
  onEdit,
}: SavedHostRowProps) {
  const hostIcon = host.type === "vast" ? "vast" : host.type === "colab" ? "colab" : "host";
  const sshAddress = host.ssh ? `${host.ssh.user}@${host.ssh.host}:${host.ssh.port}` : undefined;

  // Build right tags array (GPU info from system_info.gpu_list)
  const rightTags: { label: string; variant?: "default" | "primary" | "warning" }[] = [];
  const gpuList = host.system_info?.gpu_list;
  if (gpuList && gpuList.length > 0) {
    // Group GPUs by name
    const gpuCounts = new Map<string, number>();
    for (const gpu of gpuList) {
      const shortName = getGpuModelShortName(gpu.name);
      gpuCounts.set(shortName, (gpuCounts.get(shortName) || 0) + 1);
    }
    // Create labels
    for (const [name, count] of gpuCounts) {
      const label = count > 1 ? `${count}x ${name}` : name;
      rightTags.push({ label, variant: "default" });
    }
  }

  return (
    <HostRow
      icon={<AppIcon name={hostIcon} className="w-4 h-4" alt={host.type} />}
      title={host.name}
      subtitle={sshAddress}
      rightTags={rightTags}
      isOnline={host.status === "online"}
      isSelected={isSelected}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      onEdit={onEdit}
    />
  );
}

// Vast instance row with GPU and price on right side
type VastInstanceRowProps = {
  instance: VastInstance;
  sshAddress?: string | null;
  gpuLabel?: string;
  costLabel?: string;
  isOnline?: boolean;
  isSelected?: boolean;
  onClick?: () => void;
  onDoubleClick?: () => void;
  onEdit?: () => void;
};

export function VastInstanceRow({
  instance,
  sshAddress,
  gpuLabel,
  costLabel,
  isOnline = false,
  isSelected,
  onClick,
  onDoubleClick,
  onEdit,
}: VastInstanceRowProps) {
  const title = instance.label?.trim() || `vast #${instance.id}`;

  // Build right tags array (GPU + price)
  const rightTags: { label: string; variant?: "default" | "primary" | "warning" }[] = [];
  if (gpuLabel) {
    rightTags.push({ label: gpuLabel, variant: "default" });
  }
  if (costLabel) {
    rightTags.push({ label: costLabel, variant: "warning" });
  }

  return (
    <HostRow
      icon={<AppIcon name="vast" className="w-4 h-4" alt="Vast.ai" />}
      title={title}
      subtitle={sshAddress ?? undefined}
      rightTags={rightTags}
      isOnline={isOnline}
      isSelected={isSelected}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      onEdit={onEdit}
    />
  );
}

// Host list container
type HostListProps = {
  children: ReactNode;
  className?: string;
};

export function HostList({ children, className = "" }: HostListProps) {
  return (
    <div className={cn("termius-host-list", className)}>
      {children}
    </div>
  );
}

// Section header - Termius style (e.g., "LOCAL", "VAST.AI")
type HostSectionProps = {
  title: string;
  count?: number;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
};

export function HostSection({ title, count, actions, children, className = "" }: HostSectionProps) {
  return (
    <div className={cn("mb-4", className)}>
      <div className="flex items-center justify-between mb-2 px-1">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-semibold text-foreground/40 uppercase tracking-wider">
            {title}
          </span>
          {count !== undefined && (
            <span className="text-[10px] text-foreground/30">
              {count}
            </span>
          )}
        </div>
        {actions}
      </div>
      <HostList>{children}</HostList>
    </div>
  );
}

// Empty state
type EmptyHostStateProps = {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
};

export function EmptyHostState({ icon, title, description, action }: EmptyHostStateProps) {
  return (
    <motion.div
      className="flex flex-col items-center justify-center py-8 px-4 text-center"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: [0.25, 0.1, 0.25, 1] }}
    >
      {icon && (
        <motion.div
          className="w-10 h-10 rounded-lg bg-muted flex items-center justify-center mb-3 text-foreground/40"
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 0.3, delay: 0.1, type: "spring", stiffness: 300, damping: 20 }}
        >
          {icon}
        </motion.div>
      )}
      <h3 className="text-sm font-medium text-foreground/60 mb-1">{title}</h3>
      {description && (
        <p className="text-xs text-foreground/40 mb-3 max-w-xs">{description}</p>
      )}
      {action && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.2 }}
        >
          {action}
        </motion.div>
      )}
    </motion.div>
  );
}

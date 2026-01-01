import { useState, type ReactNode } from "react";
import { Tooltip } from "@nextui-org/react";
import { Button } from "../ui";
import { AppIcon } from "../AppIcon";
import type { Host, VastInstance } from "../../lib/types";
import { getGpuModelShortName } from "../../lib/gpu";

// Icons
function IconEdit({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125" />
    </svg>
  );
}

// Small tag component
function Tag({ children, color = "default" }: { children: ReactNode; color?: "default" | "primary" | "warning" }) {
  const colors = {
    default: "bg-foreground/10 text-foreground/60",
    primary: "bg-primary/15 text-primary",
    warning: "bg-warning/15 text-warning",
  };
  return (
    <span className={`inline-flex items-center px-1 py-0 rounded text-[9px] font-medium whitespace-nowrap ${colors[color]}`}>
      {children}
    </span>
  );
}

// Termius-style minimal host row/card - max 2 lines
type HostRowProps = {
  icon: ReactNode;
  title: string;
  subtitle?: string;
  rightTags?: { label: string; color?: "default" | "primary" | "warning" }[];
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
      className={`
        termius-host-row
        ${isSelected ? "termius-host-row-selected" : ""}
        ${isHovered ? "termius-host-row-hover" : ""}
        ${className}
      `}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
    >
      {/* Icon with status dot */}
      <div className="relative flex-shrink-0">
        <div className="w-8 h-8 rounded-lg bg-content3 flex items-center justify-center">
          {icon}
        </div>
        {/* Status dot */}
        <span
          className={`absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-content2
            ${isOnline ? "bg-success" : "bg-foreground/30"}
          `}
        />
      </div>

      {/* Info - left side */}
      <div className="flex-1 min-w-0 ml-3">
        <h3 className="text-sm font-normal text-foreground/70 truncate leading-tight">{title}</h3>
        {subtitle && (
          <p className="text-[11px] text-foreground/50 truncate leading-tight">{subtitle}</p>
        )}
      </div>

      {/* Right side - tags and edit button */}
      <div className="flex items-center gap-1.5 ml-2 flex-shrink-0">
        {rightTags && rightTags.length > 0 && !isHovered && (
          <div className="flex flex-col items-end gap-0.5">
            {rightTags.map((tag, i) => (
              <Tag key={i} color={tag.color}>{tag.label}</Tag>
            ))}
          </div>
        )}
        {hoverActions && isHovered ? (
          hoverActions
        ) : onEdit && isHovered ? (
          <Tooltip content="Edit">
            <Button
              size="sm"
              variant="light"
              isIconOnly
              className="w-7 h-7 min-w-7 opacity-60 hover:opacity-100"
              onPress={() => {
                onEdit();
              }}
            >
              <IconEdit className="w-3.5 h-3.5" />
            </Button>
          </Tooltip>
        ) : null}
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
  const rightTags: { label: string; color?: "default" | "primary" | "warning" }[] = [];
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
      rightTags.push({ label, color: "primary" });
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
  const rightTags: { label: string; color?: "default" | "primary" | "warning" }[] = [];
  if (gpuLabel) {
    rightTags.push({ label: gpuLabel, color: "primary" });
  }
  if (costLabel) {
    rightTags.push({ label: costLabel, color: "warning" });
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
    <div className={`termius-host-list ${className}`}>
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
    <div className={`mb-4 ${className}`}>
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
    <div className="flex flex-col items-center justify-center py-8 px-4 text-center">
      {icon && (
        <div className="w-10 h-10 rounded-lg bg-content2 flex items-center justify-center mb-3 text-foreground/40">
          {icon}
        </div>
      )}
      <h3 className="text-sm font-medium text-foreground/60 mb-1">{title}</h3>
      {description && (
        <p className="text-xs text-foreground/40 mb-3 max-w-xs">{description}</p>
      )}
      {action}
    </div>
  );
}

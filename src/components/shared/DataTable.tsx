import type { ReactNode } from "react";
import { useState } from "react";
import { MoreVertical, ChevronUp, ChevronDown, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

// ============================================================
// Type Definitions
// ============================================================

export type ColumnDef<T> = {
  key: string;
  header: ReactNode;
  width?: string;
  minWidth?: string;
  /** If true, content will not wrap (default: true for most columns) */
  nowrap?: boolean;
  /** If true, this column will grow to fill available space */
  grow?: boolean;
  sortable?: boolean;
  render: (item: T, index: number) => ReactNode;
};

export type RowAction<T> = {
  key: string;
  label: string;
  onClick: (item: T) => void;
  variant?: "default" | "destructive";
  disabled?: (item: T) => boolean;
};

type DataTableProps<T> = {
  data: T[];
  columns: ColumnDef<T>[];
  rowKey: (item: T) => string;
  actions?: RowAction<T>[];
  onRowClick?: (item: T) => void;
  isLoading?: boolean;
  emptyContent?: ReactNode;
  className?: string;
  compact?: boolean;
  /** Disable row hover effect */
  noHover?: boolean;
};

// ============================================================
// StatusChip Component
// ============================================================

export type StatusChipProps = {
  label: string;
  variant?: "default" | "secondary" | "destructive" | "outline";
};

export function StatusChip({ label, variant = "default" }: StatusChipProps) {
  return (
    <Badge variant={variant} className="text-xs font-medium px-2">
      {label}
    </Badge>
  );
}

// ============================================================
// TagList Component (for multiple chips in a cell)
// ============================================================

export type Tag = {
  label: string;
  variant?: "default" | "secondary" | "destructive" | "outline";
};

export function TagList({ tags, max = 3 }: { tags: Tag[]; max?: number }) {
  const displayTags = tags.slice(0, max);
  const remaining = tags.length - max;

  return (
    <div className="flex flex-wrap gap-1">
      {displayTags.map((tag, idx) => (
        <Badge key={idx} variant={tag.variant || "default"} className="text-xs px-2">
          {tag.label}
        </Badge>
      ))}
      {remaining > 0 && (
        <Badge variant="outline" className="text-xs px-2">
          +{remaining}
        </Badge>
      )}
    </div>
  );
}

// ============================================================
// CellWithIcon Component
// ============================================================

export function CellWithIcon({ icon, title, subtitle }: {
  icon: ReactNode;
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="flex items-center gap-2.5 min-w-0">
      <div className="shrink-0">
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <div className="font-medium text-sm truncate">{title}</div>
        {subtitle && (
          <div className="text-xs text-muted-foreground font-mono truncate">{subtitle}</div>
        )}
      </div>
    </div>
  );
}

// ============================================================
// DataTable Component
// ============================================================

export function DataTable<T>({
  data,
  columns,
  rowKey,
  actions,
  onRowClick,
  isLoading,
  emptyContent,
  className = "",
  compact = false,
  noHover = false,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [hoveredRow, setHoveredRow] = useState<string | null>(null);

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const hasActions = actions && actions.length > 0;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        {emptyContent || "No data"}
      </div>
    );
  }

  const cellPadding = compact ? "px-3 py-2" : "px-4 py-3";
  const headerPadding = compact ? "px-3 py-2" : "px-4 py-2.5";

  return (
    <div className={cn("doppio-card overflow-hidden", className)}>
      <div className="overflow-x-auto">
        <Table className="w-full" style={{ tableLayout: "auto" }}>
          <TableHeader>
            <TableRow className="border-border bg-muted/50 hover:bg-muted/50">
              {columns.map((col) => {
                const shouldNowrap = col.nowrap !== false; // default true
                return (
                  <TableHead
                    key={col.key}
                    className={cn(
                      headerPadding,
                      "text-left text-xs font-semibold text-muted-foreground tracking-wider",
                      shouldNowrap && "whitespace-nowrap"
                    )}
                    style={{
                      width: col.grow ? "auto" : col.width,
                      minWidth: col.minWidth,
                    }}
                  >
                    {col.sortable ? (
                      <Button
                        type="button"
                        variant="ghost"
                        className="h-auto p-0 justify-start gap-1 text-xs font-semibold text-muted-foreground tracking-wider uppercase hover:bg-transparent hover:text-foreground"
                        onClick={() => handleSort(col.key)}
                      >
                        {col.header}
                        {sortKey === col.key && (
                          sortDir === "asc" ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />
                        )}
                      </Button>
                    ) : (
                      <span className="uppercase">{col.header}</span>
                    )}
                  </TableHead>
                );
              })}
              {hasActions && (
                <TableHead className={cn(headerPadding, "w-10")} />
              )}
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.map((item, index) => {
              const key = rowKey(item);
              const isHovered = hoveredRow === key;
              const isClickable = !!onRowClick;

              return (
                <TableRow
                  key={key}
                  className={cn(
                    "group border-border",
                    !noHover && "transition-colors",
                    isClickable && "cursor-pointer",
                    noHover ? "hover:bg-transparent" : (isHovered ? "bg-primary/5" : "hover:bg-muted/50")
                  )}
                  onClick={() => onRowClick?.(item)}
                  onMouseEnter={() => setHoveredRow(key)}
                  onMouseLeave={() => setHoveredRow(null)}
                >
                  {columns.map((col) => {
                    const shouldNowrap = col.nowrap !== false; // default true
                    return (
                      <TableCell
                        key={col.key}
                        className={cn(
                          cellPadding,
                          "text-sm",
                          shouldNowrap && "whitespace-nowrap"
                        )}
                        style={{
                          width: col.grow ? "auto" : col.width,
                          minWidth: col.minWidth,
                        }}
                      >
                        {col.render(item, index)}
                      </TableCell>
                    );
                  })}
                  {hasActions && (
                    <TableCell
                      className={cn(cellPadding, "w-10")}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            size="icon"
                            variant="ghost"
                            className={cn(
                              "h-8 w-8 opacity-0 group-hover:opacity-100 transition-opacity",
                              isHovered && "opacity-100"
                            )}
                          >
                            <MoreVertical className="h-4 w-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          {actions.map((action) => (
                            <DropdownMenuItem
                              key={action.key}
                              onClick={() => action.onClick(item)}
                              className={action.variant === "destructive" ? "text-destructive" : ""}
                              disabled={action.disabled?.(item)}
                            >
                              {action.label}
                            </DropdownMenuItem>
                          ))}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  )}
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

// ============================================================
// ActionButton (inline action for table rows)
// ============================================================

export function ActionButton({
  label,
  icon,
  variant = "default",
  onClick,
  disabled,
  isLoading,
  size = "sm",
}: {
  label?: string;
  icon?: ReactNode;
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link";
  onClick: () => void;
  disabled?: boolean;
  isLoading?: boolean;
  size?: "sm" | "default" | "lg" | "icon";
}) {
  return (
    <Button
      size={size}
      variant={variant}
      onClick={onClick}
      disabled={disabled || isLoading}
    >
      {isLoading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
      {!isLoading && icon && !label && icon}
      {!isLoading && label && (
        <>
          {icon && <span className="mr-1">{icon}</span>}
          {label}
        </>
      )}
    </Button>
  );
}

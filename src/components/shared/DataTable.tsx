import type { ReactNode } from "react";
import { useState } from "react";
import { Chip, Dropdown, DropdownTrigger, DropdownMenu, DropdownItem, Spinner } from "@nextui-org/react";
import { Button } from "../ui";

// ============================================================
// Icons
// ============================================================

function IconEllipsis() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 12.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 18.75a.75.75 0 110-1.5.75.75 0 010 1.5z" />
    </svg>
  );
}

function IconSortAsc() {
  return (
    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 15.75l7.5-7.5 7.5 7.5" />
    </svg>
  );
}

function IconSortDesc() {
  return (
    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
    </svg>
  );
}

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
  onPress: (item: T) => void;
  color?: "default" | "danger";
  isDisabled?: (item: T) => boolean;
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
};

// ============================================================
// StatusChip Component
// ============================================================

export type StatusChipProps = {
  label: string;
  color?: "default" | "primary" | "secondary" | "success" | "warning" | "danger";
  variant?: "flat" | "solid" | "bordered" | "light" | "faded" | "shadow" | "dot";
};

export function StatusChip({ label, color = "default", variant = "flat" }: StatusChipProps) {
  return (
    <Chip
      size="sm"
      variant={variant}
      color={color}
      classNames={{ content: "text-xs font-medium px-0" }}
    >
      {label}
    </Chip>
  );
}

// ============================================================
// TagList Component (for multiple chips in a cell)
// ============================================================

export type Tag = {
  label: string;
  color?: "default" | "primary" | "secondary" | "success" | "warning" | "danger";
};

export function TagList({ tags, max = 3 }: { tags: Tag[]; max?: number }) {
  const displayTags = tags.slice(0, max);
  const remaining = tags.length - max;

  return (
    <div className="flex flex-wrap gap-1">
      {displayTags.map((tag, idx) => (
        <Chip
          key={idx}
          size="sm"
          variant="flat"
          color={tag.color || "default"}
          classNames={{ content: "text-xs px-0" }}
        >
          {tag.label}
        </Chip>
      ))}
      {remaining > 0 && (
        <Chip size="sm" variant="flat" classNames={{ content: "text-xs px-0" }}>
          +{remaining}
        </Chip>
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
          <div className="text-xs text-foreground/50 font-mono truncate">{subtitle}</div>
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
        <Spinner size="lg" />
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="text-center py-12 text-foreground/50">
        {emptyContent || "No data"}
      </div>
    );
  }

  const cellPadding = compact ? "px-3 py-2" : "px-4 py-3";
  const headerPadding = compact ? "px-3 py-2" : "px-4 py-2.5";

  return (
    <div className={`doppio-card overflow-hidden ${className}`}>
      <div className="overflow-x-auto">
        <table className="w-full" style={{ tableLayout: "auto" }}>
          <thead>
            <tr className="border-b border-divider bg-content2/50">
              {columns.map((col) => {
                const shouldNowrap = col.nowrap !== false; // default true
                return (
                  <th
                    key={col.key}
                    className={`${headerPadding} text-left text-xs font-semibold text-foreground/60 tracking-wider ${shouldNowrap ? "whitespace-nowrap" : ""}`}
                    style={{
                      width: col.grow ? "auto" : col.width,
                      minWidth: col.minWidth,
                    }}
                  >
                    {col.sortable ? (
                      <button
                        className="flex items-center gap-1 hover:text-foreground transition-colors uppercase"
                        onClick={() => handleSort(col.key)}
                      >
                        {col.header}
                        {sortKey === col.key && (
                          sortDir === "asc" ? <IconSortAsc /> : <IconSortDesc />
                        )}
                      </button>
                    ) : (
                      <span className="uppercase">{col.header}</span>
                    )}
                  </th>
                );
              })}
              {hasActions && (
                <th className={`${headerPadding} w-10`} />
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-divider">
            {data.map((item, index) => {
              const key = rowKey(item);
              const isHovered = hoveredRow === key;
              const isClickable = !!onRowClick;

              return (
                <tr
                  key={key}
                  className={`
                    transition-colors
                    ${isClickable ? "cursor-pointer" : ""}
                    ${isHovered ? "bg-primary/5" : "hover:bg-content2/50"}
                  `}
                  onClick={() => onRowClick?.(item)}
                  onMouseEnter={() => setHoveredRow(key)}
                  onMouseLeave={() => setHoveredRow(null)}
                >
                  {columns.map((col) => {
                    const shouldNowrap = col.nowrap !== false; // default true
                    return (
                      <td
                        key={col.key}
                        className={`${cellPadding} text-sm ${shouldNowrap ? "whitespace-nowrap" : ""}`}
                        style={{
                          width: col.grow ? "auto" : col.width,
                          minWidth: col.minWidth,
                        }}
                      >
                        {col.render(item, index)}
                      </td>
                    );
                  })}
                  {hasActions && (
                    <td
                      className={`${cellPadding} w-10`}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Dropdown>
                        <DropdownTrigger>
                          <Button
                            isIconOnly
                            size="sm"
                            variant="light"
                            className={`opacity-0 group-hover:opacity-100 transition-opacity ${isHovered ? "opacity-100" : ""}`}
                          >
                            <IconEllipsis />
                          </Button>
                        </DropdownTrigger>
                        <DropdownMenu aria-label="Row actions">
                          {actions.map((action) => (
                            <DropdownItem
                              key={action.key}
                              onPress={() => action.onPress(item)}
                              className={action.color === "danger" ? "text-danger" : ""}
                              color={action.color}
                              isDisabled={action.isDisabled?.(item)}
                            >
                              {action.label}
                            </DropdownItem>
                          ))}
                        </DropdownMenu>
                      </Dropdown>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
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
  color = "primary",
  variant = "flat",
  onPress,
  isDisabled,
  isLoading,
  size = "sm",
}: {
  label?: string;
  icon?: ReactNode;
  color?: "default" | "primary" | "secondary" | "success" | "warning" | "danger";
  variant?: "flat" | "solid" | "bordered" | "light" | "faded" | "shadow" | "ghost";
  onPress: () => void;
  isDisabled?: boolean;
  isLoading?: boolean;
  size?: "sm" | "md";
}) {
  return (
    <Button
      size={size}
      color={color}
      variant={variant}
      onPress={onPress}
      isDisabled={isDisabled}
      isLoading={isLoading}
      isIconOnly={!label && !!icon}
    >
      {icon && !label && icon}
      {label && (
        <>
          {icon && <span className="mr-1">{icon}</span>}
          {label}
        </>
      )}
    </Button>
  );
}

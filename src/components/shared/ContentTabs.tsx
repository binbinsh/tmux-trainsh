import { motion, AnimatePresence } from "framer-motion";
import { type ReactNode } from "react";

// Icons
function IconFilter({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 3c2.755 0 5.455.232 8.083.678.533.09.917.556.917 1.096v1.044a2.25 2.25 0 01-.659 1.591l-5.432 5.432a2.25 2.25 0 00-.659 1.591v2.927a2.25 2.25 0 01-1.244 2.013L9.75 21v-6.568a2.25 2.25 0 00-.659-1.591L3.659 7.409A2.25 2.25 0 013 5.818V4.774c0-.54.384-1.006.917-1.096A48.32 48.32 0 0112 3z" />
    </svg>
  );
}

function IconX({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
    </svg>
  );
}

function IconChevronDown({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
    </svg>
  );
}

// Content Tab component - Termius style tabs
type ContentTab = {
  key: string;
  label: string;
  count?: number;
  icon?: ReactNode;
};

type ContentTabsProps = {
  tabs: ContentTab[];
  activeTab: string;
  onTabChange: (key: string) => void;
  rightContent?: ReactNode;
  className?: string;
};

export function ContentTabs({
  tabs,
  activeTab,
  onTabChange,
  rightContent,
  className = "",
}: ContentTabsProps) {
  return (
    <div className={`doppio-content-tabs ${className}`}>
      <div className="flex items-center gap-1">
        {tabs.map((tab) => (
          <motion.button
            key={tab.key}
            onClick={() => onTabChange(tab.key)}
            className={`
              doppio-content-tab
              ${activeTab === tab.key ? "doppio-content-tab-active" : ""}
            `}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            transition={{ type: "spring", stiffness: 400, damping: 25 }}
          >
            {tab.icon && (
              <motion.span
                className="w-4 h-4"
                whileHover={{ rotate: 5 }}
                transition={{ type: "spring", stiffness: 400, damping: 20 }}
              >
                {tab.icon}
              </motion.span>
            )}
            <span>{tab.label}</span>
            <AnimatePresence mode="wait">
              {tab.count !== undefined && (
                <motion.span
                  className="doppio-content-tab-badge"
                  initial={{ scale: 0, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  exit={{ scale: 0, opacity: 0 }}
                  transition={{ type: "spring", stiffness: 400, damping: 20 }}
                >
                  {tab.count}
                </motion.span>
              )}
            </AnimatePresence>
          </motion.button>
        ))}
      </div>
      {rightContent && (
        <motion.div
          className="flex items-center gap-2"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.2 }}
        >
          {rightContent}
        </motion.div>
      )}
    </div>
  );
}

// Filter panel - Termius style right sidebar
type FilterOption = {
  key: string;
  label: string;
  count?: number;
};

type FilterGroup = {
  key: string;
  label: string;
  options: FilterOption[];
  selectedKeys: string[];
  onSelectionChange: (keys: string[]) => void;
  multiSelect?: boolean;
};

type FilterPanelProps = {
  isOpen: boolean;
  onToggle: () => void;
  groups: FilterGroup[];
  onClearAll?: () => void;
  hasActiveFilters?: boolean;
  className?: string;
};

export function FilterPanel({
  isOpen,
  onToggle,
  groups,
  onClearAll,
  hasActiveFilters,
  className = "",
}: FilterPanelProps) {
  if (!isOpen) {
    return (
      <button
        onClick={onToggle}
        className={`
          doppio-filter-toggle
          ${hasActiveFilters ? "doppio-filter-toggle-active" : ""}
        `}
      >
        <IconFilter className="w-4 h-4" />
        {hasActiveFilters && <span className="doppio-filter-dot" />}
      </button>
    );
  }

  return (
    <aside className={`doppio-filter-panel ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b border-divider">
        <span className="text-sm font-medium">Filters</span>
        <div className="flex items-center gap-1">
          {hasActiveFilters && onClearAll && (
            <button
              onClick={onClearAll}
              className="text-xs text-primary hover:underline"
            >
              Clear all
            </button>
          )}
          <button
            onClick={onToggle}
            className="p-1 rounded hover:bg-content2 transition-colors"
          >
            <IconX className="w-4 h-4 text-foreground/50" />
          </button>
        </div>
      </div>

      {/* Filter groups */}
      <div className="p-3 space-y-4">
        {groups.map((group) => (
          <FilterGroupSection
            key={group.key}
            group={group}
          />
        ))}
      </div>
    </aside>
  );
}

// Filter group section
function FilterGroupSection({ group }: { group: FilterGroup }) {
  const handleToggle = (optionKey: string) => {
    if (group.multiSelect) {
      const newKeys = group.selectedKeys.includes(optionKey)
        ? group.selectedKeys.filter((k) => k !== optionKey)
        : [...group.selectedKeys, optionKey];
      group.onSelectionChange(newKeys);
    } else {
      group.onSelectionChange(
        group.selectedKeys.includes(optionKey) ? [] : [optionKey]
      );
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-foreground/60 uppercase tracking-wide">
          {group.label}
        </span>
      </div>
      <div className="space-y-1">
        {group.options.map((option) => {
          const isSelected = group.selectedKeys.includes(option.key);
          return (
            <button
              key={option.key}
              onClick={() => handleToggle(option.key)}
              className={`
                doppio-filter-option
                ${isSelected ? "doppio-filter-option-active" : ""}
              `}
            >
              <span className="flex-1 text-left">{option.label}</span>
              {option.count !== undefined && (
                <span className="text-foreground/40">{option.count}</span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// Compact filter button for inline use
type FilterButtonProps = {
  label: string;
  isActive?: boolean;
  onClick?: () => void;
  className?: string;
};

export function FilterButton({
  label,
  isActive,
  onClick,
  className = "",
}: FilterButtonProps) {
  return (
    <motion.button
      onClick={onClick}
      className={`
        doppio-filter-button
        ${isActive ? "doppio-filter-button-active" : ""}
        ${className}
      `}
      whileHover={{ scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
      transition={{ type: "spring", stiffness: 400, damping: 25 }}
    >
      {label}
      <motion.span
        animate={{ rotate: isActive ? 180 : 0 }}
        transition={{ type: "spring", stiffness: 300, damping: 20 }}
      >
        <IconChevronDown className="w-3 h-3" />
      </motion.span>
    </motion.button>
  );
}

// Quick filter chips - inline filter options
type QuickFilter = {
  key: string;
  label: string;
  count?: number;
};

type QuickFiltersProps = {
  filters: QuickFilter[];
  selectedKey?: string;
  onSelect: (key: string | undefined) => void;
  className?: string;
};

export function QuickFilters({
  filters,
  selectedKey,
  onSelect,
  className = "",
}: QuickFiltersProps) {
  return (
    <div className={`flex items-center gap-1.5 ${className}`}>
      {filters.map((filter) => (
        <motion.button
          key={filter.key}
          onClick={() => onSelect(selectedKey === filter.key ? undefined : filter.key)}
          className={`
            doppio-quick-filter
            ${selectedKey === filter.key ? "doppio-quick-filter-active" : ""}
          `}
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
          transition={{ type: "spring", stiffness: 400, damping: 25 }}
        >
          {filter.label}
          <AnimatePresence mode="wait">
            {filter.count !== undefined && (
              <motion.span
                className="doppio-quick-filter-count"
                initial={{ scale: 0, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0, opacity: 0 }}
                transition={{ type: "spring", stiffness: 400, damping: 20 }}
              >
                {filter.count}
              </motion.span>
            )}
          </AnimatePresence>
        </motion.button>
      ))}
    </div>
  );
}

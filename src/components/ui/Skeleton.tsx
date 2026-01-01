import { Skeleton } from "@nextui-org/react";
import { motion } from "framer-motion";

/**
 * SkeletonCard - A skeleton placeholder for card-like content
 */
export function SkeletonCard({ className = "" }: { className?: string }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className={`p-4 rounded-lg bg-content2/50 border border-divider ${className}`}
    >
      <div className="flex items-center gap-3">
        <Skeleton className="w-10 h-10 rounded-lg" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-4 w-3/4 rounded-md" />
          <Skeleton className="h-3 w-1/2 rounded-md" />
        </div>
      </div>
    </motion.div>
  );
}

/**
 * SkeletonHostRow - Skeleton for host/storage list rows
 */
export function SkeletonHostRow() {
  return (
    <div className="host-row px-3 py-2.5">
      <div className="flex items-center gap-3">
        <Skeleton className="w-8 h-8 rounded-lg flex-shrink-0" />
        <div className="flex-1 min-w-0 space-y-1.5">
          <Skeleton className="h-4 w-32 rounded-md" />
          <Skeleton className="h-3 w-48 rounded-md" />
        </div>
        <div className="flex items-center gap-2">
          <Skeleton className="h-5 w-16 rounded-full" />
          <Skeleton className="h-5 w-12 rounded-full" />
        </div>
      </div>
    </div>
  );
}

/**
 * SkeletonSection - Skeleton for a section with header and items
 */
export function SkeletonSection({ itemCount = 3 }: { itemCount?: number }) {
  return (
    <div className="host-section">
      <div className="host-section-header">
        <Skeleton className="h-3 w-24 rounded-md" />
        <Skeleton className="h-4 w-6 rounded-full" />
      </div>
      <div className="space-y-1">
        {Array.from({ length: itemCount }).map((_, i) => (
          <SkeletonHostRow key={i} />
        ))}
      </div>
    </div>
  );
}

/**
 * SkeletonToolbar - Skeleton for the termius-style toolbar
 */
export function SkeletonToolbar() {
  return (
    <div className="termius-toolbar">
      {/* Row 1: Search bar */}
      <div className="termius-toolbar-row">
        <div className="termius-search-bar">
          <Skeleton className="h-12 w-full rounded-xl" />
        </div>
      </div>
      {/* Row 2: Quick actions */}
      <div className="termius-toolbar-row justify-between">
        <div className="flex items-center gap-1">
          <Skeleton className="h-8 w-28 rounded-lg" />
          <Skeleton className="h-8 w-20 rounded-lg" />
          <Skeleton className="h-8 w-24 rounded-lg" />
        </div>
        <div className="flex items-center gap-1">
          <Skeleton className="h-8 w-16 rounded-lg" />
          <Skeleton className="h-8 w-16 rounded-lg" />
        </div>
      </div>
    </div>
  );
}

/**
 * SkeletonPage - Full page skeleton with toolbar and sections
 */
export function SkeletonPage({ sectionCount = 2, itemsPerSection = 3 }: { sectionCount?: number; itemsPerSection?: number }) {
  return (
    <div className="doppio-page">
      <div className="doppio-page-content">
        <SkeletonToolbar />
        <div className="space-y-6 mt-4">
          {Array.from({ length: sectionCount }).map((_, i) => (
            <SkeletonSection key={i} itemCount={itemsPerSection} />
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * SkeletonText - Inline text skeleton
 */
export function SkeletonText({ width = "w-24", className = "" }: { width?: string; className?: string }) {
  return <Skeleton className={`h-4 ${width} rounded-md ${className}`} />;
}

/**
 * SkeletonAvatar - Circular skeleton for avatars/icons
 */
export function SkeletonAvatar({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  const sizeClasses = {
    sm: "w-6 h-6",
    md: "w-8 h-8",
    lg: "w-10 h-10",
  };
  return <Skeleton className={`${sizeClasses[size]} rounded-full`} />;
}

import type { ReactNode } from "react";
import { MoreVertical, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

// ============================================================
// Type Definitions
// ============================================================

export type CardAction = {
  key: string;
  label: string;
  onClick: () => void;
  variant?: "default" | "destructive";
  disabled?: boolean;
};

export type CardBadge = {
  label: string;
  variant?: "default" | "secondary" | "destructive" | "outline";
};

export type CardButton = {
  label: string;
  onClick: () => void;
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link";
  startContent?: ReactNode;
  disabled?: boolean;
  isLoading?: boolean;
};

type UnifiedCardProps = {
  /** Icon or image on the left side of the header */
  icon?: ReactNode;
  /** Primary title */
  title: string;
  /** Status badge next to the title */
  status?: CardBadge;
  /** Type/category badge */
  type?: CardBadge;
  /** Dropdown menu actions */
  actions?: CardAction[];
  /** Click handler for the entire card (makes it pressable) */
  onClick?: () => void;
  /** Data attribute for click guard on dropdown area */
  actionGuardAttr?: string;
  /** Secondary info line (e.g., SSH address, path) */
  subtitle?: ReactNode;
  /** Info chips/tags section */
  tags?: CardBadge[];
  /** Custom content in the body area */
  children?: ReactNode;
  /** Action buttons at the bottom */
  buttons?: CardButton[];
  /** Footer text (e.g., "Last seen: ...") */
  footer?: string;
  /** Optional additional className */
  className?: string;
};

// ============================================================
// Unified Card Component
// ============================================================

/**
 * A unified card component that provides consistent styling across all pages.
 *
 * Structure:
 * ┌─────────────────────────────────────────────────┐
 * │ [Icon]  Title  [Status] [Type]        [...Menu] │  <- Header
 * ├─────────────────────────────────────────────────┤
 * │ Subtitle (SSH address, path, etc.)              │  <- Subtitle
 * │ [Tag1] [Tag2] [Tag3]                            │  <- Tags
 * │ {children}                                       │  <- Custom Content
 * ├─────────────────────────────────────────────────┤
 * │ [Button1] [Button2]                             │  <- Buttons
 * │ Footer text                                      │  <- Footer
 * └─────────────────────────────────────────────────┘
 */
export function UnifiedCard({
  icon,
  title,
  status,
  type,
  actions,
  onClick,
  actionGuardAttr = "data-card-action",
  subtitle,
  tags,
  children,
  buttons,
  footer,
  className = "",
}: UnifiedCardProps) {
  const isPressable = !!onClick;
  const hasActions = actions && actions.length > 0;
  const hasTags = tags && tags.length > 0;
  const hasButtons = buttons && buttons.length > 0;

  const cardContent = (
    <CardContent className="p-4 flex flex-col gap-3">
      {/* Header Row: Icon + Title + Status + Type + Actions Menu */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          {icon && (
            <div className="shrink-0 mt-0.5">
              {icon}
            </div>
          )}
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-semibold text-foreground truncate">{title}</h3>
              {status && (
                <Badge
                  variant={status.variant || "default"}
                  className="text-xs font-medium"
                >
                  {status.label}
                </Badge>
              )}
              {type && (
                <Badge
                  variant={type.variant || "default"}
                  className="text-xs"
                >
                  {type.label}
                </Badge>
              )}
            </div>
          </div>
        </div>

        {hasActions && (
          <div className="shrink-0" {...{ [actionGuardAttr]: true }}>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="icon" variant="ghost" className="h-8 w-8">
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {actions.map((action) => (
                  <DropdownMenuItem
                    key={action.key}
                    onClick={action.onClick}
                    className={action.variant === "destructive" ? "text-destructive" : ""}
                    disabled={action.disabled}
                  >
                    {action.label}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
      </div>

      {/* Subtitle */}
      {subtitle && (
        <div className="text-xs font-mono text-muted-foreground truncate select-text">
          {subtitle}
        </div>
      )}

      {/* Tags */}
      {hasTags && (
        <div className="flex flex-wrap gap-1.5">
          {tags.map((tag, idx) => (
            <Badge
              key={idx}
              variant={tag.variant || "default"}
              className="text-xs"
            >
              {tag.label}
            </Badge>
          ))}
        </div>
      )}

      {/* Custom Content */}
      {children}

      {/* Buttons */}
      {hasButtons && (
        <div className="flex items-center gap-2 mt-1" {...{ [actionGuardAttr]: true }}>
          {buttons.map((btn, idx) => (
            <Button
              key={idx}
              size="sm"
              variant={btn.variant || "default"}
              onClick={btn.onClick}
              disabled={btn.disabled || btn.isLoading}
            >
              {btn.isLoading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              {!btn.isLoading && btn.startContent}
              {btn.label}
            </Button>
          ))}
        </div>
      )}

      {/* Spacer to push footer to bottom */}
      {footer && <div className="flex-1" />}

      {/* Footer */}
      {footer && (
        <p className="text-xs text-muted-foreground/60 mt-auto">{footer}</p>
      )}
    </CardContent>
  );

  if (isPressable) {
    return (
      <Card
        className={cn(
          "doppio-card-interactive h-full cursor-pointer hover:border-primary/40 transition-colors",
          className
        )}
        onClick={(event) => {
          // Check if click was on an action area (dropdown, buttons)
          const target = event.target as Element;
          if (target.closest(`[${actionGuardAttr}]`)) {
            return;
          }
          onClick();
        }}
      >
        {cardContent}
      </Card>
    );
  }

  return (
    <Card className={cn("doppio-card h-full", className)}>
      {cardContent}
    </Card>
  );
}

// ============================================================
// Compact List Item Card (for Terminal page host list)
// ============================================================

type ListItemCardProps = {
  icon?: ReactNode;
  title: string;
  status?: CardBadge;
  type?: CardBadge;
  subtitle?: string;
  meta?: string;
  onConnect?: () => void;
  connectLabel?: string;
  connectDisabled?: boolean;
};

/**
 * A compact horizontal card for list displays (e.g., hosts in terminal page).
 */
export function ListItemCard({
  icon,
  title,
  status,
  type,
  subtitle,
  meta,
  onConnect,
  connectLabel = "Connect",
  connectDisabled = false,
}: ListItemCardProps) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-muted p-3 hover:border-primary/40 transition-colors">
      <div className="flex items-start gap-3 min-w-0">
        {icon && (
          <div className="shrink-0">
            {icon}
          </div>
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="font-medium text-sm truncate">{title}</p>
            {status && (
              <Badge
                variant={status.variant || "default"}
                className="text-xs font-medium"
              >
                {status.label}
              </Badge>
            )}
            {type && (
              <Badge
                variant={type.variant || "default"}
                className="text-xs"
              >
                {type.label}
              </Badge>
            )}
          </div>
          {subtitle && (
            <p className="text-xs font-mono text-muted-foreground truncate">{subtitle}</p>
          )}
          {meta && (
            <p className="text-xs text-muted-foreground/60">{meta}</p>
          )}
        </div>
      </div>
      {onConnect && (
        <Button
          size="sm"
          variant="default"
          onClick={onConnect}
          disabled={connectDisabled}
        >
          {connectLabel}
        </Button>
      )}
    </div>
  );
}

// ============================================================
// Empty State Component
// ============================================================

type EmptyStateProps = {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
  };
};

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <Card className="doppio-card border-dashed">
      <CardContent className="text-center py-12">
        {icon && (
          <div className="flex justify-center mb-4 text-muted-foreground/60">
            {icon}
          </div>
        )}
        <h3 className="font-semibold mb-2">{title}</h3>
        {description && (
          <p className="text-sm text-muted-foreground mb-4">{description}</p>
        )}
        {action && (
          <Button variant="default" onClick={action.onClick}>
            {action.label}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

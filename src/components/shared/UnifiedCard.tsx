import type { ReactNode } from "react";
import { Card, CardBody, Chip, Dropdown, DropdownTrigger, DropdownMenu, DropdownItem } from "@nextui-org/react";
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

// ============================================================
// Type Definitions
// ============================================================

export type CardAction = {
  key: string;
  label: string;
  onPress: () => void;
  color?: "default" | "danger";
  isDisabled?: boolean;
};

export type CardBadge = {
  label: string;
  color?: "default" | "primary" | "secondary" | "success" | "warning" | "danger";
  variant?: "flat" | "solid" | "bordered" | "light" | "faded" | "shadow";
};

export type CardButton = {
  label: string;
  onPress: () => void;
  color?: "default" | "primary" | "secondary" | "success" | "warning" | "danger";
  variant?: "flat" | "solid" | "bordered" | "light" | "faded" | "shadow" | "ghost";
  startContent?: ReactNode;
  isDisabled?: boolean;
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
  onPress?: () => void;
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
  onPress,
  actionGuardAttr = "data-card-action",
  subtitle,
  tags,
  children,
  buttons,
  footer,
  className = "",
}: UnifiedCardProps) {
  const isPressable = !!onPress;
  const hasActions = actions && actions.length > 0;
  const hasTags = tags && tags.length > 0;
  const hasButtons = buttons && buttons.length > 0;

  const cardContent = (
    <CardBody className="p-4 flex flex-col gap-3">
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
                <Chip
                  size="sm"
                  variant={status.variant || "flat"}
                  color={status.color || "default"}
                  classNames={{ content: "text-xs font-medium" }}
                >
                  {status.label}
                </Chip>
              )}
              {type && (
                <Chip
                  size="sm"
                  variant={type.variant || "flat"}
                  color={type.color || "default"}
                  classNames={{ content: "text-xs" }}
                >
                  {type.label}
                </Chip>
              )}
            </div>
          </div>
        </div>

        {hasActions && (
          <div className="shrink-0" {...{ [actionGuardAttr]: true }}>
            <Dropdown>
              <DropdownTrigger>
                <Button isIconOnly size="sm" variant="light">
                  <IconEllipsis />
                </Button>
              </DropdownTrigger>
              <DropdownMenu aria-label="Card actions">
                {actions.map((action) => (
                  <DropdownItem
                    key={action.key}
                    onPress={action.onPress}
                    className={action.color === "danger" ? "text-danger" : ""}
                    color={action.color}
                    isDisabled={action.isDisabled}
                  >
                    {action.label}
                  </DropdownItem>
                ))}
              </DropdownMenu>
            </Dropdown>
          </div>
        )}
      </div>

      {/* Subtitle */}
      {subtitle && (
        <div className="text-xs font-mono text-foreground/50 truncate select-text">
          {subtitle}
        </div>
      )}

      {/* Tags */}
      {hasTags && (
        <div className="flex flex-wrap gap-1.5">
          {tags.map((tag, idx) => (
            <Chip
              key={idx}
              size="sm"
              variant={tag.variant || "flat"}
              color={tag.color || "default"}
              classNames={{ content: "text-xs" }}
            >
              {tag.label}
            </Chip>
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
              color={btn.color || "default"}
              variant={btn.variant || "flat"}
              startContent={btn.startContent}
              onPress={btn.onPress}
              isDisabled={btn.isDisabled}
              isLoading={btn.isLoading}
            >
              {btn.label}
            </Button>
          ))}
        </div>
      )}

      {/* Spacer to push footer to bottom */}
      {footer && <div className="flex-1" />}

      {/* Footer */}
      {footer && (
        <p className="text-xs text-foreground/40 mt-auto">{footer}</p>
      )}
    </CardBody>
  );

  if (isPressable) {
    return (
      <Card
        as="div"
        isPressable
        disableAnimation
        disableRipple
        onPress={(event) => {
          // Check if click was on an action area (dropdown, buttons)
          const target = event.target as Element;
          if (target.closest(`[${actionGuardAttr}]`)) {
            return;
          }
          onPress();
        }}
        className={`doppio-card-interactive h-full data-[pressed=true]:scale-100 ${className}`}
      >
        {cardContent}
      </Card>
    );
  }

  return (
    <Card className={`doppio-card h-full ${className}`}>
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
    <div className="flex items-center justify-between gap-3 rounded-lg border border-divider bg-content2 p-3 hover:border-primary/40 transition-colors">
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
              <Chip
                size="sm"
                variant={status.variant || "flat"}
                color={status.color || "default"}
                classNames={{ content: "text-xs font-medium" }}
              >
                {status.label}
              </Chip>
            )}
            {type && (
              <Chip
                size="sm"
                variant={type.variant || "flat"}
                color={type.color || "default"}
                classNames={{ content: "text-xs" }}
              >
                {type.label}
              </Chip>
            )}
          </div>
          {subtitle && (
            <p className="text-xs font-mono text-foreground/50 truncate">{subtitle}</p>
          )}
          {meta && (
            <p className="text-xs text-foreground/40">{meta}</p>
          )}
        </div>
      </div>
      {onConnect && (
        <Button
          size="sm"
          color="primary"
          variant="flat"
          onPress={onConnect}
          isDisabled={connectDisabled}
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
    onPress: () => void;
  };
};

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <Card className="doppio-card border-dashed">
      <CardBody className="text-center py-12">
        {icon && (
          <div className="flex justify-center mb-4 text-foreground/40">
            {icon}
          </div>
        )}
        <h3 className="font-semibold mb-2">{title}</h3>
        {description && (
          <p className="text-sm text-foreground/60 mb-4">{description}</p>
        )}
        {action && (
          <Button color="primary" onPress={action.onPress}>
            {action.label}
          </Button>
        )}
      </CardBody>
    </Card>
  );
}

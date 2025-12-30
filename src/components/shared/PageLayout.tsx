import type { ReactNode } from "react";

type PageLayoutProps = {
  /** Page title */
  title: string;
  /** Optional subtitle/description */
  subtitle?: string;
  /** Action buttons on the right side of header */
  actions?: ReactNode;
  /** Page content */
  children: ReactNode;
};

/**
 * Consistent page layout wrapper for all pages.
 * Provides standardized header, spacing, and max-width container.
 */
export function PageLayout({ title, subtitle, actions, children }: PageLayoutProps) {
  return (
    <div className="doppio-page">
      <div className="doppio-page-content">
        {/* Header */}
        <div className="doppio-page-header">
          <div>
            <h1 className="doppio-page-title">{title}</h1>
            {subtitle && <p className="doppio-page-subtitle">{subtitle}</p>}
          </div>
          {actions && <div className="flex gap-2">{actions}</div>}
        </div>

        {/* Content */}
        {children}
      </div>
    </div>
  );
}

type PageSectionProps = {
  /** Section title */
  title?: string;
  /** Optional content to the right of title */
  titleRight?: ReactNode;
  /** Section content */
  children: ReactNode;
  /** Additional class names */
  className?: string;
};

/**
 * A section within a page with optional title.
 */
export function PageSection({ title, titleRight, children, className = "" }: PageSectionProps) {
  return (
    <div className={`mb-8 ${className}`}>
      {(title || titleRight) && (
        <div className="flex items-center justify-between mb-4">
          {title && <h2 className="doppio-section-header mb-0">{title}</h2>}
          {titleRight}
        </div>
      )}
      {children}
    </div>
  );
}

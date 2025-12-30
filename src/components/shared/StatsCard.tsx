import type { ReactNode } from "react";

type StatsCardProps = {
  title: string;
  value: string | number;
  icon?: ReactNode;
  description?: string;
  /** Color variant for the value */
  valueColor?: "default" | "primary" | "success" | "warning" | "danger";
  trend?: {
    value: number;
    direction: "up" | "down";
  };
};

const VALUE_COLORS = {
  default: "",
  primary: "text-primary",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
};

export function StatsCard({ title, value, icon, description, valueColor = "default", trend }: StatsCardProps) {
  return (
    <div className="doppio-stat-card">
      <div className="flex items-center gap-4">
        {icon && (
          <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-primary/10 text-primary shrink-0">
            {icon}
          </div>
        )}
        <div className="flex-1 min-w-0">
          <p className="doppio-stat-label">{title}</p>
          <div className="flex items-baseline gap-2">
            <p className={`doppio-stat-value ${VALUE_COLORS[valueColor]}`}>{value}</p>
            {trend && (
              <span
                className={`text-xs font-medium ${
                  trend.direction === "up" ? "text-success" : "text-danger"
                }`}
              >
                {trend.direction === "up" ? "↑" : "↓"} {Math.abs(trend.value)}%
              </span>
            )}
          </div>
          {description && (
            <p className="text-xs text-foreground/50 truncate">{description}</p>
          )}
        </div>
      </div>
    </div>
  );
}


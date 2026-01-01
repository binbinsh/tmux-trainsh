import { motion } from "framer-motion";
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
    <motion.div
      className="doppio-stat-card"
      whileHover={{ y: -2 }}
      transition={{ type: "spring", stiffness: 400, damping: 25 }}
    >
      <div className="flex items-center gap-4">
        {icon && (
          <motion.div
            className="flex items-center justify-center w-10 h-10 rounded-lg bg-primary/10 text-primary shrink-0"
            whileHover={{ scale: 1.05, rotate: 3 }}
            transition={{ type: "spring", stiffness: 400, damping: 20 }}
          >
            {icon}
          </motion.div>
        )}
        <div className="flex-1 min-w-0">
          <p className="doppio-stat-label">{title}</p>
          <div className="flex items-baseline gap-2">
            <motion.p
              className={`doppio-stat-value ${VALUE_COLORS[valueColor]}`}
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, ease: [0.25, 0.1, 0.25, 1] }}
            >
              {value}
            </motion.p>
            {trend && (
              <motion.span
                className={`text-xs font-medium ${
                  trend.direction === "up" ? "text-success" : "text-danger"
                }`}
                initial={{ opacity: 0, x: -5 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.3, delay: 0.1, ease: [0.25, 0.1, 0.25, 1] }}
              >
                {trend.direction === "up" ? "↑" : "↓"} {Math.abs(trend.value)}%
              </motion.span>
            )}
          </div>
          {description && (
            <p className="text-xs text-foreground/50 truncate">{description}</p>
          )}
        </div>
      </div>
    </motion.div>
  );
}


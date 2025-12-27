import { Card, CardBody } from "@nextui-org/react";
import type { ReactNode } from "react";

type StatsCardProps = {
  title: string;
  value: string | number;
  icon?: ReactNode;
  description?: string;
  trend?: {
    value: number;
    direction: "up" | "down";
  };
};

export function StatsCard({ title, value, icon, description, trend }: StatsCardProps) {
  return (
    <Card>
      <CardBody className="flex flex-row items-center gap-4">
        {icon && (
          <div className="flex items-center justify-center w-12 h-12 rounded-lg bg-primary/10 text-primary">
            {icon}
          </div>
        )}
        <div className="flex-1 min-w-0">
          <p className="text-sm text-foreground/60">{title}</p>
          <div className="flex items-baseline gap-2">
            <p className="text-2xl font-bold">{value}</p>
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
      </CardBody>
    </Card>
  );
}


import { cn } from "@/lib/utils";
import {
  BADGE_STYLE_MAP,
  BILLING_PAYMENT_STATUS_CONFIG,
  BILLING_STATUS_CONFIG,
  RUN_STATUS_CONFIG,
  STATE_BADGE_CONFIG,
  TASK_STATUS_CONFIG,
} from "@/lib/constants";
import type { BadgeConfig } from "@/lib/constants";

type StatusBadgeProps = {
  state: string;
  variant?: "project" | "run" | "task" | "billing" | "payment";
  className?: string;
};

const CONFIG_MAP: Record<string, Record<string, BadgeConfig>> = {
  project: STATE_BADGE_CONFIG,
  run: RUN_STATUS_CONFIG,
  task: TASK_STATUS_CONFIG,
  billing: BILLING_STATUS_CONFIG,
  payment: BILLING_PAYMENT_STATUS_CONFIG,
};

export function StatusBadge({ state, variant = "project", className }: StatusBadgeProps) {
  const config = CONFIG_MAP[variant]?.[state];
  const label = config?.label ?? state.replaceAll("_", " ");
  const colorClass = config ? BADGE_STYLE_MAP[config.color] : BADGE_STYLE_MAP.gray;

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold",
        colorClass,
        className,
      )}
    >
      {label}
    </span>
  );
}

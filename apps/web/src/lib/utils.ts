import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatBudget(value: string | null): string {
  if (!value) return "—";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return value;

  // Safari/WebKit can render THB currency formatting inconsistently for large
  // values in some locales. Keep the display explicit and stable.
  const grouped = new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 0,
    minimumFractionDigits: 0,
  }).format(amount);
  return `฿${grouped}`;
}

export function formatThaiDate(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("th-TH", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(new Date(value));
}

export function formatRelativeTime(value: string | null): string {
  if (!value) return "—";
  const now = Date.now();
  const then = new Date(value).getTime();
  const diffMs = now - then;
  const diffMin = Math.floor(diffMs / 60000);
  const diffHr = Math.floor(diffMs / 3600000);
  const diffDay = Math.floor(diffMs / 86400000);

  if (diffMin < 1) return "เมื่อสักครู่";
  if (diffMin < 60) return `${diffMin} นาที`;
  if (diffHr < 24) return `${diffHr} ชม.`;
  return `${diffDay} วัน`;
}

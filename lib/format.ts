import type { Category, Finding } from "./api";

export const CATEGORY_LABEL: Record<Category, string> = {
  source: "Source",
  filter: "Filter",
  projection: "Projection",
  join: "Join",
  aggregate: "Aggregate",
  sort: "Sort",
  limit: "Limit",
  reshape: "Reshape",
  mutate: "Mutate",
  other: "Other",
};

// Tailwind-free so React Flow edges/minimap can use them too. Tuned to read on light and dark.
export const CATEGORY_COLOR: Record<Category, string> = {
  source: "#64748b",
  filter: "#0ea5e9",
  projection: "#8b5cf6",
  join: "#f59e0b",
  aggregate: "#10b981",
  sort: "#6366f1",
  limit: "#06b6d4",
  reshape: "#ec4899",
  mutate: "#84cc16",
  other: "#94a3b8",
};

export const nf = new Intl.NumberFormat("en-US");

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let v = bytes / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 ? 1 : 0)} ${units[i]}`;
}

export const SEVERITY_RANK: Record<Finding["severity"], number> = { error: 0, warning: 1, info: 2 };

export function worstSeverity(findings: Finding[]): Finding["severity"] | null {
  if (!findings.length) return null;
  return [...findings].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity])[0]
    .severity;
}

export const SEVERITY_CLASS: Record<Finding["severity"], string> = {
  error: "text-red-600 dark:text-red-400",
  warning: "text-amber-600 dark:text-amber-400",
  info: "text-muted-foreground",
};

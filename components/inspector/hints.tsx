"use client";

import { Lightbulb } from "lucide-react";

import { CopyButton } from "@/components/copy-button";
import type { Hint, TraceNode } from "@/lib/api";

const KIND_LABEL: Record<Hint["kind"], string> = {
  filter_before_join: "Filter before join",
  filter_earlier: "Filter earlier",
  unused_columns: "Unused columns",
  useless_sort: "Unnecessary sort",
  row_apply: "Row-wise apply",
  duplicate_read: "Duplicate read",
  inplace: "inplace=True",
};

export function HintsList({
  hints,
  nodes,
  onSelect,
  showNode = true,
}: {
  hints: Hint[];
  nodes: TraceNode[];
  onSelect?: (id: string) => void;
  showNode?: boolean;
}) {
  if (!hints.length) {
    return <p className="text-sm text-muted-foreground">No hints: nothing obvious to push down or simplify.</p>;
  }
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  return (
    <ul className="space-y-3">
      {hints.map((h, i) => {
        const n = byId[h.node_id];
        return (
          <li key={i} className="space-y-1.5">
            <button
              type="button"
              onClick={() => onSelect?.(h.node_id)}
              className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted"
            >
              <Lightbulb className="mt-0.5 size-4 shrink-0 text-sky-600 dark:text-sky-400" />
              <span className="flex-1">
                <span className="mr-1.5 text-xs font-medium text-sky-700 dark:text-sky-300">{KIND_LABEL[h.kind]}</span>
                {h.message}
              </span>
              {showNode && n && (
                <span className="shrink-0 font-mono text-xs text-muted-foreground">
                  {n.var_name ?? n.op}
                  {n.source_line ? ` · L${n.source_line}` : ""}
                </span>
              )}
            </button>
            {h.suggestion && (
              <div className="group relative ml-8">
                <pre className="overflow-x-auto rounded-md bg-muted p-2 pr-10 font-mono text-xs">{h.suggestion}</pre>
                <div className="absolute top-1 right-1 opacity-60 group-hover:opacity-100">
                  <CopyButton text={h.suggestion} size="icon-xs" variant="ghost" />
                </div>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

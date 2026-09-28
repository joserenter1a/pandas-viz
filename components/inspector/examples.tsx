"use client";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { RowExamples } from "@/lib/api";
import { nf } from "@/lib/format";
import { cn } from "@/lib/utils";

const KIND_TONE: Record<RowExamples["kind"], string> = {
  dropped: "text-red-600 dark:text-red-400",
  unmatched_left: "text-red-600 dark:text-red-400",
  unmatched_right: "text-muted-foreground",
  duplicate_keys_left: "text-amber-600 dark:text-amber-400",
  duplicate_keys_right: "text-amber-600 dark:text-amber-400",
  null_keys_left: "text-amber-600 dark:text-amber-400",
  null_keys_right: "text-amber-600 dark:text-amber-400",
  nulls: "text-amber-600 dark:text-amber-400",
};

export function ExampleTable({ examples, compact = false }: { examples: RowExamples; compact?: boolean }) {
  const highlight = new Set(examples.highlight ?? []);
  return (
    <div className="space-y-1">
      {!compact && (
        <div className="flex items-baseline gap-2 text-xs">
          <span className={cn("font-medium", KIND_TONE[examples.kind])}>{examples.label}</span>
          <span className="text-muted-foreground">
            {examples.rows.length < examples.total
              ? `showing ${examples.rows.length} of ${nf.format(examples.total)}`
              : `${nf.format(examples.total)} row${examples.total === 1 ? "" : "s"}`}
          </span>
        </div>
      )}
      <div className="overflow-x-auto rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="h-7 text-xs text-muted-foreground">index</TableHead>
              {examples.columns.map((c) => (
                <TableHead
                  key={c}
                  className={cn(
                    "h-7 font-mono text-xs",
                    (highlight.has(c) || c === examples.column) && "text-foreground underline decoration-dotted underline-offset-4",
                  )}
                >
                  {c}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {examples.rows.map((row, i) => (
              <TableRow key={i}>
                <TableCell className="py-1 font-mono text-xs text-muted-foreground">
                  {JSON.stringify(examples.index[i])}
                </TableCell>
                {row.map((v, j) => {
                  const col = examples.columns[j];
                  const isNull = v === null;
                  return (
                    <TableCell
                      key={j}
                      className={cn(
                        "py-1 font-mono text-xs",
                        highlight.has(col) && "font-semibold",
                        isNull && "italic text-muted-foreground",
                        isNull && col === examples.column && "bg-amber-500/15 text-amber-700 dark:text-amber-300",
                      )}
                    >
                      {isNull ? "null" : typeof v === "object" ? JSON.stringify(v) : String(v)}
                    </TableCell>
                  );
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

export function ExamplesList({ examples }: { examples: RowExamples[] }) {
  if (!examples.length) return null;
  return (
    <div className="space-y-4">
      <div className="text-xs font-medium">Example rows</div>
      {examples.map((e) => (
        <ExampleTable key={`${e.kind}:${e.column ?? ""}`} examples={e} />
      ))}
    </div>
  );
}

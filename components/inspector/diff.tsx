"use client";

import { ArrowLeftRight, ArrowRight, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { fetchDiff, type ColumnDiff, type NodeDiff, type TraceNode, type TraceResult } from "@/lib/api";
import { formatBytes, nf } from "@/lib/format";
import { cn } from "@/lib/utils";

const STATUS_STYLE: Record<ColumnDiff["status"], string> = {
  added: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  removed: "bg-red-500/15 text-red-700 dark:text-red-300",
  renamed: "bg-violet-500/15 text-violet-700 dark:text-violet-300",
  changed: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  same: "bg-muted text-muted-foreground",
};

const RELATION_TEXT: Record<NodeDiff["relation"], string> = {
  same: "Same step",
  ancestor: "feeds into",
  descendant: "is downstream of",
  unrelated: "is not on the same lineage as",
};

export const nodeName = (n: TraceNode) =>
  `${n.var_name ?? n.op}${n.source_line ? ` · L${n.source_line}` : ""}`;

function Delta({ a, b, format = nf.format }: { a: number; b: number; format?: (v: number) => string }) {
  const d = b - a;
  return (
    <span className="tabular-nums">
      {format(a)} → {format(b)}
      {d !== 0 && (
        <span className={cn("ml-1", d < 0 ? "text-red-600 dark:text-red-400" : "text-amber-600 dark:text-amber-400")}>
          ({d > 0 ? "+" : "−"}
          {format(Math.abs(d))})
        </span>
      )}
    </span>
  );
}

function Pair({ a, b }: { a: number | string | null | undefined; b: number | string | null | undefined }) {
  const show = (v: number | string | null | undefined) =>
    v == null ? "—" : typeof v === "number" ? nf.format(v) : v;
  if (a === b || a == null || b == null) return <span>{show(b ?? a)}</span>;
  return (
    <span className="text-amber-600 dark:text-amber-400">
      {show(a)} → {show(b)}
    </span>
  );
}

export function DiffPanel({
  trace,
  node,
  compareId,
  onCompare,
  onSelect,
}: {
  trace: TraceResult;
  node: TraceNode;
  compareId: string | null;
  onCompare: (id: string | null) => void;
  onSelect: (id: string) => void;
}) {
  const nodes = trace.nodes ?? [];
  const parent = (trace.edges ?? []).find((e) => e.target === node.id && e.role !== "right" && e.role !== "other");
  const otherId = compareId && compareId !== node.id ? compareId : parent?.source ?? null;
  const [diff, setDiff] = useState<NodeDiff | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showSame, setShowSame] = useState(false);

  useEffect(() => {
    if (!otherId) return;
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const d = await fetchDiff(trace, otherId, node.id);
        if (!cancelled) {
          setDiff(d);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [trace, otherId, node.id]);

  const other = nodes.find((n) => n.id === otherId);
  const current = diff && diff.a === otherId && diff.b === node.id ? diff : null;
  const columns = current?.columns.filter((c) => showSame || c.status !== "same") ?? [];
  const sameCount = current?.columns.filter((c) => c.status === "same").length ?? 0;
  const path = current?.path ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">Compare</span>
        <Select value={otherId} onValueChange={(id) => onCompare(id ? String(id) : null)}>
          <SelectTrigger size="sm" className="w-56">
            <SelectValue placeholder="Pick a step…">
              {(id: string | null) => {
                const n = nodes.find((x) => x.id === id);
                return n ? nodeName(n) : "Pick a step…";
              }}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {nodes
              .filter((n) => n.id !== node.id)
              .map((n) => (
                <SelectItem key={n.id} value={n.id}>
                  <span className="font-mono text-xs">{nodeName(n)}</span>
                  <span className="ml-auto truncate pl-3 text-xs text-muted-foreground">{n.label}</span>
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
        <ArrowRight className="size-4 text-muted-foreground" />
        <span className="font-mono text-xs">{nodeName(node)}</span>
        {other && (
          <Button
            size="xs"
            variant="ghost"
            onClick={() => {
              onSelect(other.id);
              onCompare(node.id);
            }}
            title="Swap the two steps"
          >
            <ArrowLeftRight /> swap
          </Button>
        )}
        {loading && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
      </div>

      {!otherId && (
        <p className="text-sm text-muted-foreground">
          Pick a step to compare with, or shift+click one in the graph.
        </p>
      )}
      {error && <p className="text-sm text-red-600">Diff failed: {error}</p>}

      {current && other && (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <div className="rounded-md border px-3 py-2">
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Rows</div>
              <div className="text-sm font-medium"><Delta a={current.rows_a} b={current.rows_b} /></div>
            </div>
            <div className="rounded-md border px-3 py-2">
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Columns</div>
              <div className="text-sm font-medium"><Delta a={current.cols_a} b={current.cols_b} /></div>
            </div>
            <div className="rounded-md border px-3 py-2">
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Memory</div>
              <div className="text-sm font-medium"><Delta a={current.memory_a} b={current.memory_b} format={formatBytes} /></div>
            </div>
          </div>

          <div className="space-y-1.5">
            <div className="text-xs text-muted-foreground">
              <span className="font-mono text-foreground">{other.var_name ?? other.op}</span> {RELATION_TEXT[current.relation]}{" "}
              <span className="font-mono text-foreground">{node.var_name ?? node.op}</span>
              {path.length > 2 && ` through ${path.length - 2} step${path.length > 3 ? "s" : ""}`}
            </div>
            {path.length > 1 && (
              <div className="flex flex-wrap items-center gap-1 text-xs">
                {path.map((s, i) => (
                  <span key={s.node_id} className="flex items-center gap-1">
                    {i > 0 && <ArrowRight className="size-3 text-muted-foreground" />}
                    <button
                      type="button"
                      onClick={() => onSelect(s.node_id)}
                      className="rounded-md border px-1.5 py-0.5 font-mono hover:bg-muted"
                      title={s.label}
                    >
                      {s.var_name ?? s.op} <span className="text-muted-foreground">{nf.format(s.rows)}</span>
                    </button>
                  </span>
                ))}
              </div>
            )}
            {(current.index_a.join() !== current.index_b.join()) && (
              <div className="text-xs text-amber-600 dark:text-amber-400">
                Index changed: {current.index_a.join(", ")} → {current.index_b.join(", ")}
              </div>
            )}
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs">
              <span className="font-medium">Columns</span>
              {(["added", "removed", "renamed", "changed"] as const).map((s) => {
                const count = current.columns.filter((c) => c.status === s).length;
                return count ? <Badge key={s} className={STATUS_STYLE[s]}>{count} {s}</Badge> : null;
              })}
              {sameCount > 0 && (
                <button type="button" className="ml-auto text-muted-foreground underline-offset-2 hover:underline" onClick={() => setShowSame((v) => !v)}>
                  {showSame ? "hide" : "show"} {sameCount} unchanged
                </button>
              )}
            </div>
            {columns.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Column</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>dtype</TableHead>
                    <TableHead className="text-right">Nulls</TableHead>
                    <TableHead className="text-right">Unique</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {columns.map((c) => (
                    <TableRow key={`${c.status}:${c.name}`}>
                      <TableCell className="font-mono text-xs">
                        {c.renamed_from && <span className="text-muted-foreground line-through">{c.renamed_from}</span>}
                        {c.renamed_from && " → "}
                        {c.name}
                      </TableCell>
                      <TableCell><Badge className={STATUS_STYLE[c.status]}>{c.status === "renamed" ? "renamed?" : c.status}</Badge></TableCell>
                      <TableCell className="font-mono text-xs"><Pair a={c.dtype_a} b={c.dtype_b} /></TableCell>
                      <TableCell className="text-right text-xs"><Pair a={c.nulls_a} b={c.nulls_b} /></TableCell>
                      <TableCell className="text-right text-xs text-muted-foreground">
                        {c.unique_a != null && c.unique_b != null && c.unique_a !== c.unique_b
                          ? `${nf.format(c.unique_a)} → ${nf.format(c.unique_b)}`
                          : c.unique_b ?? c.unique_a ?? "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <p className="text-sm text-muted-foreground">No column changes.</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}

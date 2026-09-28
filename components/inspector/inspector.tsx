"use client";

import { AlertTriangle, ChevronDown, CircleX, Info } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Finding, Hint, TraceNode, TraceResult } from "@/lib/api";
import { CATEGORY_COLOR, CATEGORY_LABEL, formatBytes, nf, SEVERITY_CLASS, SEVERITY_RANK } from "@/lib/format";
import { cn } from "@/lib/utils";
import { NodeChecks, PipelineChecks } from "./checks";
import { OpDetails } from "./details";
import { DiffPanel } from "./diff";
import { ExampleTable } from "./examples";
import { HintsList } from "./hints";

const SEVERITY_ICON = { error: CircleX, warning: AlertTriangle, info: Info };

export function FindingsList({
  findings,
  nodes,
  onSelect,
  showNode = true,
}: {
  findings: Finding[];
  nodes: TraceNode[];
  onSelect?: (id: string) => void;
  showNode?: boolean;
}) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  if (!findings.length) return <p className="text-sm text-muted-foreground">No findings. Rows, nulls and dtypes look stable.</p>;
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const sorted = [...findings].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity]);
  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  return (
    <ul className="space-y-1">
      {sorted.map((f) => {
        const Icon = SEVERITY_ICON[f.severity];
        const n = byId[f.node_id];
        const key = `${f.node_id}:${f.kind}:${f.message}`;
        const rows = f.example_kind
          ? n?.examples?.find((e) => e.kind === f.example_kind && (!f.column || f.kind === "join" || !e.column || e.column === f.column))
          : undefined;
        return (
          <li key={key}>
            <div className="flex items-start gap-1 rounded-md hover:bg-muted">
              <button
                type="button"
                onClick={() => onSelect?.(f.node_id)}
                className="flex flex-1 items-start gap-2 px-2 py-1.5 text-left text-sm"
              >
                <Icon className={cn("mt-0.5 size-4 shrink-0", SEVERITY_CLASS[f.severity])} />
                <span className="flex-1">{f.message}</span>
                {showNode && n && (
                  <span className="shrink-0 font-mono text-xs text-muted-foreground">
                    {n.var_name ?? n.op}
                    {n.source_line ? ` · L${n.source_line}` : ""}
                  </span>
                )}
              </button>
              {rows && (
                <button
                  type="button"
                  onClick={() => toggle(key)}
                  aria-expanded={open.has(key)}
                  className="flex shrink-0 items-center gap-0.5 px-2 py-1.5 text-xs text-muted-foreground hover:text-foreground"
                >
                  rows
                  <ChevronDown className={cn("size-3.5 transition-transform", open.has(key) && "rotate-180")} />
                </button>
              )}
            </div>
            {rows && open.has(key) && (
              <div className="mt-1 mb-2 ml-8">
                <ExampleTable examples={rows} />
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function Overview({ node, findings, hints }: { node: TraceNode; findings: Finding[]; hints: Hint[] }) {
  const change = node.schema_change;
  const args = Object.entries(node.args ?? {});
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Box label="Rows" value={node.rows_in != null ? `${nf.format(node.rows_in)} → ${nf.format(node.profile.rows)}` : nf.format(node.profile.rows)} />
        <Box label="Columns" value={nf.format(node.profile.cols)} />
        <Box label="Memory" value={formatBytes(node.profile.memory_bytes)} />
        <Box label="Time" value={`${node.duration_ms.toFixed(2)} ms`} />
      </div>
      {findings.length > 0 && <FindingsList findings={findings} nodes={[node]} showNode={false} />}
      {hints.length > 0 && <HintsList hints={hints} nodes={[node]} showNode={false} />}
      {change && (change.added?.length || change.removed?.length || Object.keys(change.dtype_changed ?? {}).length) ? (
        <div className="space-y-1.5 text-sm">
          <div className="text-xs font-medium">Schema change vs. input</div>
          <div className="flex flex-wrap gap-1.5">
            {change.added?.map((c) => <Badge key={`a${c}`} className="bg-emerald-500/15 text-emerald-700 dark:text-emerald-300">+ {c}</Badge>)}
            {change.removed?.map((c) => <Badge key={`r${c}`} className="bg-red-500/15 text-red-700 dark:text-red-300">− {c}</Badge>)}
            {Object.entries(change.dtype_changed ?? {}).map(([c, [from, to]]) => (
              <Badge key={`d${c}`} className="bg-amber-500/15 text-amber-700 dark:text-amber-300">
                {c}: {from} → {to}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}
      {node.source_text && (
        <div className="space-y-1">
          <div className="text-xs font-medium">Source{node.source_line ? ` (line ${node.source_line})` : ""}</div>
          <pre className="overflow-x-auto rounded-md bg-muted p-2 font-mono text-xs">{node.source_text}</pre>
        </div>
      )}
      {args.length > 0 && (
        <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-xs">
          {args.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-muted-foreground">{k}</dt>
              <dd className="font-mono">{v}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function Box({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-sm font-medium tabular-nums">{value}</div>
    </div>
  );
}

function SchemaTable({ node }: { node: TraceNode }) {
  const added = new Set(node.schema_change?.added ?? []);
  const changed = node.schema_change?.dtype_changed ?? {};
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Column</TableHead>
          <TableHead>dtype</TableHead>
          <TableHead className="text-right">Nulls</TableHead>
          <TableHead className="text-right">Unique</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {node.profile.columns.map((c) => (
          <TableRow key={c.name}>
            <TableCell className="font-mono text-xs">
              {c.name}
              {added.has(c.name) && <span className="ml-1.5 text-emerald-600">new</span>}
            </TableCell>
            <TableCell className={cn("font-mono text-xs", changed[c.name] && "text-amber-600 dark:text-amber-400")}>
              {changed[c.name] ? `${changed[c.name][0]} → ${c.dtype}` : c.dtype}
            </TableCell>
            <TableCell className={cn("text-right tabular-nums", c.null_count > 0 && "text-amber-600 dark:text-amber-400")}>
              {nf.format(c.null_count)}
            </TableCell>
            <TableCell className="text-right tabular-nums">{c.n_unique != null ? nf.format(c.n_unique) : "—"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function SampleTable({ node }: { node: TraceNode }) {
  const p = node.profile;
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        First {p.sample.length} of {nf.format(p.rows)} rows · index {p.index.join(", ")}
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-muted-foreground">index</TableHead>
            {p.sample_columns.map((c) => <TableHead key={c} className="font-mono text-xs">{c}</TableHead>)}
          </TableRow>
        </TableHeader>
        <TableBody>
          {p.sample.map((row, i) => (
            <TableRow key={i}>
              <TableCell className="font-mono text-xs text-muted-foreground">{JSON.stringify(p.sample_index[i])}</TableCell>
              {row.map((v, j) => (
                <TableCell key={j} className={cn("font-mono text-xs", v === null && "text-muted-foreground italic")}>
                  {v === null ? "null" : typeof v === "object" ? JSON.stringify(v) : String(v)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function Inspector({
  trace,
  node,
  tab,
  onTabChange,
  onSelect,
  compareId,
  onCompare,
}: {
  trace: TraceResult;
  node: TraceNode | null;
  tab: string;
  onTabChange: (t: string) => void;
  onSelect: (id: string) => void;
  compareId: string | null;
  onCompare: (id: string | null) => void;
}) {
  const [pipelineTab, setPipelineTab] = useState("findings");
  const findings = trace.findings ?? [];
  const nodeFindings = node ? findings.filter((f) => f.node_id === node.id) : [];
  const allChecks = trace.checks ?? [];
  const nodeChecks = node ? allChecks.filter((c) => c.node_id === node.id) : [];
  const guardCount = allChecks.filter((c) => c.kind !== "pandera").length;
  const hints = trace.hints ?? [];
  const nodeHints = node ? hints.filter((h) => h.node_id === node.id) : [];
  const counts = { error: 0, warning: 0, info: 0 };
  for (const f of findings) counts[f.severity]++;

  if (!node) {
    return (
      <Tabs value={pipelineTab} onValueChange={(v) => setPipelineTab(String(v))} className="flex h-full flex-col gap-0">
        <div className="flex items-center gap-2 border-b px-2">
          <TabsList variant="line">
            <TabsTrigger value="findings">Findings{findings.length ? ` (${findings.length})` : ""}</TabsTrigger>
            <TabsTrigger value="hints">Hints{hints.length ? ` (${hints.length})` : ""}</TabsTrigger>
            <TabsTrigger value="checks">Checks{guardCount ? ` (${guardCount})` : ""}</TabsTrigger>
          </TabsList>
          {counts.error > 0 && <Badge variant="destructive">{counts.error} errors</Badge>}
          {counts.warning > 0 && <Badge className="bg-amber-500/15 text-amber-700 dark:text-amber-300">{counts.warning} warnings</Badge>}
          <span className="ml-auto pr-2 text-xs text-muted-foreground">
            Click a step to inspect it · shift+click another to compare
          </span>
        </div>
        <ScrollArea className="min-h-0 flex-1">
          <div className="p-4">
            <TabsContent value="findings">
              <FindingsList findings={findings} nodes={trace.nodes ?? []} onSelect={onSelect} />
            </TabsContent>
            <TabsContent value="hints">
              <p className="mb-3 text-xs text-muted-foreground">
                pandas runs every step eagerly with no query optimizer. These rewrites keep the result the same and do
                less work.
              </p>
              <HintsList hints={hints} nodes={trace.nodes ?? []} onSelect={onSelect} />
            </TabsContent>
            <TabsContent value="checks">
              <PipelineChecks trace={trace} />
            </TabsContent>
          </div>
        </ScrollArea>
      </Tabs>
    );
  }

  return (
    <Tabs value={tab} onValueChange={(v) => onTabChange(String(v))} className="flex h-full flex-col gap-0">
      <div className="flex items-center gap-3 border-b px-4 py-2">
        <span className="size-2.5 rounded-full" style={{ background: CATEGORY_COLOR[node.category] }} />
        <span className="text-sm font-semibold">{node.var_name ?? node.op}</span>
        <span className="truncate font-mono text-xs text-muted-foreground">{node.label}</span>
        <Badge variant="outline" className="ml-auto">{CATEGORY_LABEL[node.category]}</Badge>
      </div>
      <TabsList variant="line" className="px-2">
        <TabsTrigger value="overview">
          Overview{nodeFindings.length + nodeHints.length ? ` (${nodeFindings.length + nodeHints.length})` : ""}
        </TabsTrigger>
        <TabsTrigger value="details">Details</TabsTrigger>
        <TabsTrigger value="schema">Schema</TabsTrigger>
        <TabsTrigger value="sample">Sample</TabsTrigger>
        <TabsTrigger value="diff">Diff</TabsTrigger>
        <TabsTrigger value="checks">Checks{nodeChecks.length ? ` (${nodeChecks.filter((c) => c.kind !== "pandera").length})` : ""}</TabsTrigger>
      </TabsList>
      <ScrollArea className="min-h-0 flex-1">
        <div className="p-4">
          <TabsContent value="overview"><Overview node={node} findings={nodeFindings} hints={nodeHints} /></TabsContent>
          <TabsContent value="details"><OpDetails node={node} /></TabsContent>
          <TabsContent value="schema"><SchemaTable node={node} /></TabsContent>
          <TabsContent value="sample"><SampleTable node={node} /></TabsContent>
          <TabsContent value="diff">
            <DiffPanel trace={trace} node={node} compareId={compareId} onCompare={onCompare} onSelect={onSelect} />
          </TabsContent>
          <TabsContent value="checks"><NodeChecks checks={nodeChecks} /></TabsContent>
        </div>
      </ScrollArea>
    </Tabs>
  );
}

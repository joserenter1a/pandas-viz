"use client";

import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { AlertTriangle, CircleX, Info, Lightbulb } from "lucide-react";

import type { Finding, TraceNode } from "@/lib/api";
import { CATEGORY_COLOR, CATEGORY_LABEL, nf, worstSeverity } from "@/lib/format";
import { cn } from "@/lib/utils";

export type OpNodeData = {
  node: TraceNode;
  findings: Finding[];
  hinted: boolean;
  selected: boolean;
  comparing: boolean;
};
export type OpFlowNode = Node<OpNodeData, "op">;

export const NODE_WIDTH = 250;
export const NODE_HEIGHT = 84;

export function OpNode({ data }: NodeProps<OpFlowNode>) {
  const { node, findings, hinted, selected, comparing } = data;
  const color = CATEGORY_COLOR[node.category];
  const rowsIn = node.rows_in ?? null;
  const rows = node.profile.rows;
  const delta = rowsIn === null ? 0 : rows - rowsIn;
  const severity = worstSeverity(findings);
  const SeverityIcon = severity === "error" ? CircleX : severity === "warning" ? AlertTriangle : Info;

  return (
    <div
      className={cn(
        "rounded-lg border bg-card text-card-foreground shadow-sm transition-shadow",
        selected ? "ring-2 ring-ring shadow-md" : "hover:shadow-md",
        comparing && "outline-2 outline-offset-2 outline-dashed outline-sky-500",
        severity === "error" && !selected && "border-red-500/70",
      )}
      style={{ width: NODE_WIDTH, height: NODE_HEIGHT, borderLeft: `4px solid ${color}` }}
    >
      <Handle type="target" position={Position.Top} className="!bg-muted-foreground/50 !border-0" />
      <div className="flex h-full flex-col justify-between px-3 py-2">
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          <span className="font-medium uppercase tracking-wide" style={{ color }}>
            {CATEGORY_LABEL[node.category]}
          </span>
          {node.var_name && (
            <span className="truncate rounded bg-muted px-1.5 font-mono text-foreground">
              {node.var_name}
            </span>
          )}
          <span className="ml-auto flex items-center gap-1">
            {node.source_line ? `L${node.source_line}` : null}
            {hinted && <Lightbulb className="size-3.5 text-sky-500" aria-label="has optimization hints" />}
            {severity && (
              <SeverityIcon
                className={cn(
                  "size-3.5",
                  severity === "error" && "text-red-500",
                  severity === "warning" && "text-amber-500",
                )}
                aria-label={`${findings.length} findings`}
              />
            )}
          </span>
        </div>
        <div className="truncate font-mono text-xs" title={node.label}>
          {node.label}
        </div>
        <div className="flex items-baseline gap-2 text-xs tabular-nums">
          <span className="font-medium">
            {nf.format(rows)} × {node.profile.cols}
          </span>
          {delta !== 0 && (
            <span className={delta < 0 ? "text-red-600 dark:text-red-400" : "text-amber-600 dark:text-amber-400"}>
              {delta > 0 ? "+" : "−"}
              {nf.format(Math.abs(delta))} rows
            </span>
          )}
          <span className="ml-auto text-muted-foreground">{node.duration_ms.toFixed(1)} ms</span>
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-muted-foreground/50 !border-0" />
    </div>
  );
}

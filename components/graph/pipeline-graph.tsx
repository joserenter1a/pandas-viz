"use client";

import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import ELK from "elkjs/lib/elk.bundled.js";
import { useEffect, useMemo, useState } from "react";

import type { Finding, TraceResult } from "@/lib/api";
import { CATEGORY_COLOR, nf } from "@/lib/format";
import { NODE_HEIGHT, NODE_WIDTH, OpNode, type OpFlowNode } from "./op-node";

const elk = new ELK();
const nodeTypes = { op: OpNode };

type Props = {
  trace: TraceResult;
  selectedId: string | null;
  compareId: string | null;
  onSelect: (id: string | null) => void;
  onCompare: (id: string) => void;
};

async function layout(trace: TraceResult): Promise<Record<string, { x: number; y: number }>> {
  const graph = await elk.layout({
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "DOWN",
      "elk.layered.spacing.nodeNodeBetweenLayers": "56",
      "elk.spacing.nodeNode": "40",
      "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
      // keep execution order (and left-before-right join inputs) where possible
      "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
    },
    children: (trace.nodes ?? []).map((n) => ({ id: n.id, width: NODE_WIDTH, height: NODE_HEIGHT })),
    edges: [...(trace.edges ?? [])]
      .sort((a, b) => (a.role === "right" ? 1 : 0) - (b.role === "right" ? 1 : 0))
      .map((e, i) => ({ id: `e${i}`, sources: [e.source], targets: [e.target] })),
  });
  return Object.fromEntries((graph.children ?? []).map((c) => [c.id, { x: c.x ?? 0, y: c.y ?? 0 }]));
}

function Graph({ trace, selectedId, compareId, onSelect, onCompare }: Props) {
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});
  const { fitView } = useReactFlow();

  useEffect(() => {
    let cancelled = false;
    layout(trace).then((p) => {
      if (cancelled) return;
      setPositions(p);
      requestAnimationFrame(() => fitView({ padding: 0.15, maxZoom: 1.1 }));
    });
    return () => {
      cancelled = true;
    };
  }, [trace, fitView]);

  const findingsByNode = useMemo(() => {
    const map: Record<string, Finding[]> = {};
    for (const f of trace.findings ?? []) (map[f.node_id] ??= []).push(f);
    return map;
  }, [trace]);

  const hinted = useMemo(() => new Set((trace.hints ?? []).map((h) => h.node_id)), [trace]);

  const nodes: OpFlowNode[] = useMemo(
    () =>
      (trace.nodes ?? [])
        .filter((n) => positions[n.id])
        .map((n) => ({
          id: n.id,
          type: "op",
          position: positions[n.id],
          data: {
            node: n,
            findings: findingsByNode[n.id] ?? [],
            hinted: hinted.has(n.id),
            selected: n.id === selectedId,
            comparing: n.id === compareId,
          },
        })),
    [trace, positions, findingsByNode, hinted, selectedId, compareId],
  );

  // Edge width scales with the rows flowing along it, so drops and explosions stand out.
  const edges: Edge[] = useMemo(() => {
    const byId = Object.fromEntries((trace.nodes ?? []).map((n) => [n.id, n]));
    const maxRows = Math.max(1, ...(trace.nodes ?? []).map((n) => n.profile.rows));
    return (trace.edges ?? []).map((e, i) => {
      const src = byId[e.source];
      const rows = src?.profile.rows ?? 0;
      const width = 1.25 + 7 * (Math.log10(rows + 1) / Math.log10(maxRows + 1));
      const color = src ? CATEGORY_COLOR[src.category] : "#94a3b8";
      const touchesSelection = selectedId !== null && (e.source === selectedId || e.target === selectedId);
      return {
        id: `e${i}`,
        source: e.source,
        target: e.target,
        label: `${e.role && e.role !== "input" ? `${e.role} · ` : ""}${nf.format(rows)}`,
        labelStyle: { fontSize: 10, fill: "var(--muted-foreground)" },
        labelBgStyle: { fill: "var(--background)" },
        style: { stroke: color, strokeWidth: width, opacity: selectedId && !touchesSelection ? 0.35 : 0.8 },
        markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16, markerUnits: "userSpaceOnUse" },
      };
    });
  }, [trace, selectedId]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={(event, n) => (event.shiftKey && selectedId ? onCompare(n.id) : onSelect(n.id))}
      onPaneClick={() => onSelect(null)}
      nodesConnectable={false}
      nodesDraggable
      colorMode="system"
      minZoom={0.2}
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={20} />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

export function PipelineGraph(props: Props) {
  return (
    <ReactFlowProvider>
      <Graph {...props} />
    </ReactFlowProvider>
  );
}

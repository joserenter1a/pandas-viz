import type { components } from "./api-types";

type S = components["schemas"];
export type TraceResult = S["TraceResult"];
export type TraceNode = S["Node"];
export type TraceEdge = S["Edge"];
export type Finding = S["Finding"];
export type Example = S["Example"];
export type FrameProfile = S["FrameProfile"];
export type Category = TraceNode["category"];

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const fetchExamples = () => request<Example[]>("/api/examples");

export const runTrace = (code: string) =>
  request<TraceResult>("/api/trace", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });

export type TraceSummary = S["TraceSummary"];
export type StoredTrace = S["StoredTrace"];

export const fetchTraces = () => request<TraceSummary[]>("/api/traces");

export const fetchStoredTrace = (id: string) =>
  request<StoredTrace>(`/api/traces/${encodeURIComponent(id)}`);
export type Check = S["Check"];

export type NodeDiff = S["NodeDiff"];
export type ColumnDiff = S["ColumnDiff"];

// Diffs only need profiles: drop sample rows to keep the request small.
export const fetchDiff = (trace: TraceResult, a: string, b: string) =>
  request<NodeDiff>("/api/diff", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      a,
      b,
      trace: {
        ...trace,
        nodes: (trace.nodes ?? []).map((n) => ({ ...n, profile: { ...n.profile, sample: [], sample_index: [] } })),
      },
    }),
  });

export type DatasetInfo = S["DatasetInfo"];

export const fetchDatasets = () => request<DatasetInfo[]>("/api/datasets");

export async function uploadDataset(file: File): Promise<DatasetInfo> {
  const body = new FormData();
  body.append("file", file);
  const res = await fetch("/api/datasets", { method: "POST", body });
  if (!res.ok) {
    const detail = await res.json().then((j) => j.detail).catch(() => res.statusText);
    throw new Error(`${file.name}: ${detail}`);
  }
  return res.json();
}

export const deleteDataset = (name: string) =>
  request<{ deleted: boolean }>(`/api/datasets/${encodeURIComponent(name)}`, { method: "DELETE" });
export type RowExamples = S["RowExamples"];
export type Hint = S["Hint"];

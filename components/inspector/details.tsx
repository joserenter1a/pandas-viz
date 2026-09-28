"use client";

import { Badge } from "@/components/ui/badge";
import type { TraceNode } from "@/lib/api";
import { nf } from "@/lib/format";
import { ExamplesList } from "./examples";

type D = Record<string, unknown>;
const num = (v: unknown) => (typeof v === "number" ? v : 0);

function Stat({ label, value, tone }: { label: string; value: React.ReactNode; tone?: "bad" | "warn" }) {
  return (
    <div className="rounded-md border px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div
        className={
          "text-sm font-medium tabular-nums " +
          (tone === "bad" ? "text-red-600 dark:text-red-400" : tone === "warn" ? "text-amber-600 dark:text-amber-400" : "")
        }
      >
        {value}
      </div>
    </div>
  );
}

function SplitBar({ parts }: { parts: { label: string; value: number; className: string }[] }) {
  const total = parts.reduce((s, p) => s + p.value, 0) || 1;
  return (
    <div className="space-y-1">
      <div className="flex h-3 overflow-hidden rounded-full bg-muted">
        {parts.map((p) => (
          <div key={p.label} className={p.className} style={{ width: `${(100 * p.value) / total}%` }} title={`${p.label}: ${nf.format(p.value)}`} />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 text-xs text-muted-foreground">
        {parts.map((p) => (
          <span key={p.label} className="flex items-center gap-1.5">
            <span className={`inline-block size-2 rounded-full ${p.className}`} />
            {p.label} <span className="tabular-nums text-foreground">{nf.format(p.value)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function JoinDetails({ d, op }: { d: D; op: string }) {
  const card = d.cardinality as string | undefined;
  const factor = d.explosion_factor as number | null | undefined;
  const mismatches = (d.key_dtype_mismatches as { left: string; right: string; left_dtype: string; right_dtype: string }[]) ?? [];
  const suffixes = (d.suffix_collisions as string[]) ?? [];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant="outline">{String(d.how)} {op}</Badge>
        {card && <Badge variant={card === "m:m" ? "destructive" : "secondary"}>cardinality {card}</Badge>}
        <span className="font-mono text-xs text-muted-foreground">
          {(d.left_on as string[])?.join(", ")} ⟷ {(d.right_on as string[])?.join(", ")}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Left rows" value={nf.format(num(d.rows_left))} />
        <Stat label="Right rows" value={nf.format(num(d.rows_right))} />
        <Stat label="Output rows" value={nf.format(num(d.rows_out))} />
        <Stat label="Explosion" value={factor != null ? `×${factor.toFixed(2)}` : "—"} tone={factor && factor > 1 ? "warn" : undefined} />
      </div>
      {"left_matched_rows" in d && (
        <div className="space-y-3">
          <div>
            <div className="mb-1 text-xs font-medium">Left rows</div>
            <SplitBar parts={[
              { label: "matched", value: num(d.left_matched_rows), className: "bg-emerald-500" },
              { label: "no match", value: num(d.left_only_rows), className: "bg-red-400" },
            ]} />
          </div>
          <div>
            <div className="mb-1 text-xs font-medium">Right rows</div>
            <SplitBar parts={[
              { label: "matched", value: num(d.right_matched_rows), className: "bg-emerald-500" },
              { label: "no match", value: num(d.right_only_rows), className: "bg-slate-400" },
            ]} />
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat label="Dup keys (left)" value={nf.format(num(d.left_duplicate_keys))} tone={num(d.left_duplicate_keys) ? "warn" : undefined} />
            <Stat label="Dup keys (right)" value={nf.format(num(d.right_duplicate_keys))} tone={num(d.right_duplicate_keys) ? "warn" : undefined} />
            <Stat label="Null keys (left)" value={nf.format(num(d.left_null_keys))} tone={num(d.left_null_keys) ? "warn" : undefined} />
            <Stat label="Null keys (right)" value={nf.format(num(d.right_null_keys))} tone={num(d.right_null_keys) ? "warn" : undefined} />
          </div>
        </div>
      )}
      {d.suggested_validate ? (
        d.validate_passes ? (
          <div className="rounded-md border bg-muted/40 p-3 text-xs">
            <div className="mb-1 font-medium">Lock it in</div>
            <code className="font-mono">validate=&quot;{String(d.suggested_validate)}&quot;</code>
            <span className="text-muted-foreground"> — pandas will raise if a future input breaks this cardinality.</span>
          </div>
        ) : (
          <div className="rounded-md border border-red-500/40 bg-red-500/5 p-3 text-xs">
            <div className="mb-1 font-medium text-red-700 dark:text-red-300">This join should be {String(d.suggested_validate)}, but isn&apos;t</div>
            <code className="font-mono">validate=&quot;{String(d.suggested_validate)}&quot;</code>
            <span className="text-muted-foreground">
              {" "}would raise on this data: the right side has duplicate keys (see the example rows below). Deduplicate it, then add the check.
            </span>
          </div>
        )
      ) : null}
      {mismatches.length > 0 && (
        <div className="text-xs text-amber-600 dark:text-amber-400">
          {mismatches.map((m) => (
            <div key={m.left + m.right}>
              Key dtype mismatch: <code>{m.left}</code> ({m.left_dtype}) vs <code>{m.right}</code> ({m.right_dtype})
            </div>
          ))}
        </div>
      )}
      {suffixes.length > 0 && (
        <div className="text-xs text-muted-foreground">
          Suffixed columns: {suffixes.map((s) => <code key={s} className="mr-1">{s}</code>)}
        </div>
      )}
    </div>
  );
}

function FilterDetails({ d }: { d: D }) {
  return (
    <div className="space-y-3">
      <SplitBar parts={[
        { label: "kept", value: num(d.rows_out), className: "bg-sky-500" },
        { label: "dropped", value: num(d.rows_dropped), className: "bg-red-400" },
      ]} />
      <div className="grid grid-cols-3 gap-2">
        <Stat label="Rows in" value={nf.format(num(d.rows_in))} />
        <Stat label="Rows out" value={nf.format(num(d.rows_out))} />
        <Stat label="Kept" value={d.pct_kept != null ? `${d.pct_kept}%` : "—"} tone={num(d.pct_kept) < 50 ? "warn" : undefined} />
      </div>
    </div>
  );
}

function GroupDetails({ d }: { d: D }) {
  const hist = (d.group_size_histogram as { start: number; end: number; count: number }[]) ?? [];
  const max = Math.max(1, ...hist.map((h) => h.count));
  return (
    <div className="space-y-4">
      <div className="font-mono text-xs text-muted-foreground">by {String(d.keys)}</div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Groups" value={nf.format(num(d.n_groups))} />
        <Stat label="Min size" value={nf.format(num(d.group_size_min))} />
        <Stat label="Median size" value={nf.format(num(d.group_size_median))} />
        <Stat label="Max size" value={nf.format(num(d.group_size_max))} />
      </div>
      {hist.length > 1 && (
        <div>
          <div className="mb-2 text-xs font-medium">Group size distribution</div>
          <div className="flex h-24 items-end gap-1">
            {hist.map((h) => (
              <div key={h.start} className="flex flex-1 flex-col items-center gap-1" title={`${h.start}–${h.end}: ${h.count} groups`}>
                <div className="w-full rounded-t bg-emerald-500/80" style={{ height: `${(80 * h.count) / max}px` }} />
                <span className="text-[10px] tabular-nums text-muted-foreground">{Math.round(h.start)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ConcatDetails({ d }: { d: D }) {
  const missing = (d.columns_not_in_all_inputs as string[]) ?? [];
  return (
    <div className="space-y-3 text-sm">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {((d.rows_per_input as number[]) ?? []).map((r, i) => (
          <Stat key={i} label={`Input ${i + 1}`} value={`${nf.format(r)} rows`} />
        ))}
        <Stat label="Output" value={`${nf.format(num(d.rows_out))} rows`} />
      </div>
      {missing.length > 0 && (
        <div className="text-xs text-amber-600 dark:text-amber-400">
          Not in every input (filled with nulls): {missing.map((c) => <code key={c} className="mr-1">{c}</code>)}
        </div>
      )}
    </div>
  );
}

function Panel({ node }: { node: TraceNode }) {
  const d = (node.details ?? {}) as D;
  if (node.category === "join" && "how" in d) return <JoinDetails d={d} op={node.op} />;
  if (node.op === "concat") return <ConcatDetails d={d} />;
  if ("n_groups" in d) return <GroupDetails d={d} />;
  if ("rows_dropped" in d) return <FilterDetails d={d} />;
  const entries = Object.entries(d);
  if (!entries.length) {
    return node.examples?.length ? null : (
      <p className="text-sm text-muted-foreground">No operation-specific details for {node.op}.</p>
    );
  }
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted-foreground">{k}</dt>
          <dd className="font-mono text-xs">{JSON.stringify(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

export function OpDetails({ node }: { node: TraceNode }) {
  return (
    <div className="space-y-6">
      <Panel node={node} />
      <ExamplesList examples={node.examples ?? []} />
    </div>
  );
}

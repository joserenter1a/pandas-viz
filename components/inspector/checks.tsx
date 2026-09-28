"use client";

import { CircleCheck, CircleX } from "lucide-react";

import { CopyButton } from "@/components/copy-button";
import type { Check, TraceResult } from "@/lib/api";
import { cn } from "@/lib/utils";

const POSITION_LABEL = { before: "before line", after: "after line", replace: "edit line" } as const;

function Status({ passes }: { passes: boolean }) {
  const Icon = passes ? CircleCheck : CircleX;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-xs font-medium",
        passes ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400",
      )}
    >
      <Icon className="size-3.5" />
      {passes ? "holds now" : "fails now"}
    </span>
  );
}

function CodeBlock({ code }: { code: string }) {
  return (
    <div className="group relative">
      <pre className="overflow-x-auto rounded-md bg-muted p-2 pr-10 font-mono text-xs">{code}</pre>
      <div className="absolute top-1 right-1 opacity-60 group-hover:opacity-100">
        <CopyButton text={code} size="icon-xs" variant="ghost" label={undefined} />
      </div>
    </div>
  );
}

export function NodeChecks({ checks }: { checks: Check[] }) {
  const guards = checks.filter((c) => c.kind !== "pandera");
  const schema = checks.find((c) => c.kind === "pandera");
  if (!guards.length && !schema) {
    return (
      <p className="text-sm text-muted-foreground">
        No checks for this step. Checks are generated for joins, filters, findings and named outputs.
      </p>
    );
  }
  return (
    <div className="space-y-4">
      {guards.map((c, i) => (
        <div key={i} className="space-y-1.5">
          <div className="flex items-center gap-3">
            <Status passes={c.passes} />
            <span className="text-xs text-muted-foreground">
              {POSITION_LABEL[c.position]} {c.line ?? "?"}
            </span>
          </div>
          <CodeBlock code={c.code} />
          <p className="text-xs text-muted-foreground">{c.reason}</p>
        </div>
      ))}
      {schema && (
        <div className="space-y-1.5">
          <div className="text-xs font-medium">pandera schema at this step</div>
          <CodeBlock code={schema.code} />
        </div>
      )}
    </div>
  );
}

export function PipelineChecks({ trace }: { trace: TraceResult }) {
  const guards = (trace.checks ?? []).filter((c) => c.kind !== "pandera");
  const failing = guards.filter((c) => !c.passes).length;
  if (!guards.length) {
    return <p className="text-sm text-muted-foreground">No checks generated for this pipeline yet.</p>;
  }
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 text-sm">
        <span>
          {guards.length} checks ·{" "}
          <span className="text-emerald-600 dark:text-emerald-400">{guards.length - failing} hold now</span>
          {failing > 0 && (
            <>
              {" · "}
              <span className="text-red-600 dark:text-red-400">{failing} fail now</span>
            </>
          )}
        </span>
        <span className="ml-auto">
          <CopyButton text={trace.checks_script ?? ""} label="Copy checks" />
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        Passing checks lock in today&apos;s behaviour. Failing checks are the ones that would have caught the
        findings: fix the data or code, or drop them. Paste into the pipeline or a test.
      </p>
      <pre className="overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs leading-relaxed">
        {trace.checks_script}
      </pre>
    </div>
  );
}

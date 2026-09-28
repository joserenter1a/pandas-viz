"use client";

import { Database, Loader2, Upload, X } from "lucide-react";
import { useRef } from "react";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { deleteDataset, type DatasetInfo } from "@/lib/api";
import { formatBytes, nf } from "@/lib/format";
import { cn } from "@/lib/utils";

export const ACCEPT = ".csv,.tsv,.txt,.parquet,.pq,.json,.jsonl,.ndjson";

type Props = {
  datasets: DatasetInfo[];
  onChange: () => void;
  onInsert: (name: string) => void;
  onError: (message: string | null) => void;
  uploading: boolean;
  onUpload: (files: File[]) => void;
};

export function DatasetBar({ datasets, onChange, onInsert, onError, uploading, onUpload }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);

  const remove = async (d: DatasetInfo) => {
    if (!window.confirm(`Delete dataset "${d.name}" (${d.filename})?`)) return;
    try {
      await deleteDataset(d.name);
      onChange();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <TooltipProvider>
      <div className="flex min-h-10 flex-wrap items-center gap-1.5 border-b px-3 py-1.5">
        <Database className="size-3.5 text-muted-foreground" />
        {datasets.length === 0 && (
          <span className="text-xs text-muted-foreground">
            Drop CSV, Parquet or JSON files here to use them as variables
          </span>
        )}
        {datasets.map((d) => (
          <div
            key={d.name}
            className="group flex items-center rounded-md border bg-muted/40 text-xs hover:bg-muted"
          >
            <Tooltip>
              <TooltipTrigger
                className="flex items-center gap-1.5 py-0.5 pr-1 pl-2 font-mono"
                onClick={() => onInsert(d.name)}
              >
                {d.name}
                <span className="font-sans text-muted-foreground tabular-nums">
                  {nf.format(d.rows)}×{d.cols}
                </span>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="block max-w-sm">
                <div className="font-medium">
                  {d.filename} · {formatBytes(d.size_bytes)}
                </div>
                <div className="mt-1 font-mono opacity-80">
                  {d.columns.slice(0, 12).map((c) => `${c.name}: ${c.dtype}`).join(", ")}
                  {d.columns.length > 12 ? `, … ${d.columns.length - 12} more` : ""}
                </div>
                <div className="mt-1 opacity-70">Click to insert the variable name</div>
              </TooltipContent>
            </Tooltip>
            <button
              type="button"
              onClick={() => remove(d)}
              className="px-1 py-0.5 text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-foreground focus-visible:opacity-100"
              aria-label={`Delete dataset ${d.name}`}
            >
              <X className="size-3" />
            </button>
          </div>
        ))}
        <Button
          size="xs"
          variant="ghost"
          className="ml-auto"
          disabled={uploading}
          onClick={() => inputRef.current?.click()}
        >
          {uploading ? <Loader2 className="animate-spin" /> : <Upload />}
          Upload
        </Button>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            e.target.value = "";
            if (files.length) onUpload(files);
          }}
        />
      </div>
    </TooltipProvider>
  );
}

/** Full-panel overlay shown while files are dragged over the editor side. */
export function DropOverlay({ active }: { active: boolean }) {
  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-0 z-20 flex items-center justify-center border-2 border-dashed border-sky-500 bg-sky-500/10 text-sm font-medium text-sky-700 transition-opacity dark:text-sky-300",
        active ? "opacity-100" : "opacity-0",
      )}
    >
      Drop to add as a dataset
    </div>
  );
}

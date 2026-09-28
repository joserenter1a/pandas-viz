"use client";

import { Loader2, Play } from "lucide-react";
import type { EditorView } from "@codemirror/view";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { CodeEditor } from "@/components/code-editor";
import { CopyButton } from "@/components/copy-button";
import { DatasetBar, DropOverlay } from "@/components/dataset-bar";
import { PipelineGraph } from "@/components/graph/pipeline-graph";
import { Inspector } from "@/components/inspector/inspector";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  fetchDatasets,
  fetchExamples,
  fetchStoredTrace,
  fetchTraces,
  runTrace,
  uploadDataset,
  type DatasetInfo,
  type Example,
  type TraceResult,
  type TraceSummary,
} from "@/lib/api";
import { CATEGORY_COLOR, CATEGORY_LABEL } from "@/lib/format";

const DRAFT_KEY = "pandas-viz:draft";

function usePrefersDark() {
  return useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    },
    () => window.matchMedia("(prefers-color-scheme: dark)").matches,
    () => false,
  );
}

export default function Home() {
  const dark = usePrefersDark();
  const [examples, setExamples] = useState<Example[]>([]);
  const [exampleId, setExampleId] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [trace, setTrace] = useState<TraceResult | null>(null);
  const [running, setRunning] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [compareId, setCompareId] = useState<string | null>(null);
  const [tab, setTab] = useState("overview");
  const [recent, setRecent] = useState<TraceSummary[]>([]);
  const [loaded, setLoaded] = useState<TraceSummary | null>(null);
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragDepth, setDragDepth] = useState(0);
  const editorView = useRef<EditorView | null>(null);

  const refreshDatasets = useCallback(() => {
    fetchDatasets().then(setDatasets).catch(() => {});
  }, []);

  const upload = async (files: File[]) => {
    setUploading(true);
    setRequestError(null);
    const errors: string[] = [];
    for (const file of files) {
      try {
        await uploadDataset(file);
      } catch (e) {
        errors.push(e instanceof Error ? e.message : String(e));
      }
    }
    setUploading(false);
    refreshDatasets();
    if (errors.length) setRequestError(errors.join("\n"));
  };

  const insertAtCursor = (text: string) => {
    const view = editorView.current;
    if (!view) return;
    view.dispatch(view.state.replaceSelection(text));
    view.focus();
  };

  const hasFiles = (e: React.DragEvent) => Array.from(e.dataTransfer.types).includes("Files");

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  const run = useCallback(async (source: string) => {
    setRunning(true);
    setRequestError(null);
    try {
      const result = await runTrace(source);
      setTrace(result);
      setSelectedId(null);
      setCompareId(null);
      setLoaded((prev) => {
        if (prev) window.history.replaceState(null, "", window.location.pathname);
        return null;
      });
    } catch (e) {
      setRequestError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }, []);

  // Traces saved by `pandas-viz run --open`, `%%pandasviz --open` or `Tracer.open()`.
  const loadStored = useCallback(async (id: string) => {
    setRequestError(null);
    try {
      const stored = await fetchStoredTrace(id);
      setCode(stored.code);
      setTrace(stored.result);
      setSelectedId(null);
      setCompareId(null);
      setExampleId(null);
      setLoaded(stored);
      window.history.replaceState(null, "", `?trace=${encodeURIComponent(id)}`);
    } catch (e) {
      setRequestError(`Could not load trace ${id}: ${e instanceof Error ? e.message : e}`);
    }
  }, []);

  useEffect(() => {
    fetchTraces().then(setRecent).catch(() => {});
    refreshDatasets();
    const traceId = new URLSearchParams(window.location.search).get("trace");
    fetchExamples()
      .then((exs) => {
        setExamples(exs);
        if (traceId) {
          loadStored(traceId);
          return;
        }
        let draft: string | null = null;
        try {
          draft = localStorage.getItem(DRAFT_KEY);
        } catch {}
        const initial = draft || exs[0]?.code || "";
        if (!draft && exs[0]) setExampleId(exs[0].id);
        setCode(initial);
        if (initial) run(initial);
      })
      .catch((e) => setRequestError(`Could not reach the pandas-viz API (${e.message}). Is \`pandas-viz serve\` running?`));
  }, [run, loadStored, refreshDatasets]);

  const clearLoaded = () => {
    setLoaded(null);
    window.history.replaceState(null, "", window.location.pathname);
  };

  const onCodeChange = (v: string) => {
    setCode(v);
    try {
      localStorage.setItem(DRAFT_KEY, v);
    } catch {}
  };

  const nodes = useMemo(() => trace?.nodes ?? [], [trace]);
  const selected = nodes.find((n) => n.id === selectedId) ?? null;

  const selectByLine = (line: number) => {
    const atLine = nodes.filter((n) => n.source_line === line);
    if (atLine.length) setSelectedId(atLine[atLine.length - 1].id);
  };

  const counts = { error: 0, warning: 0 };
  for (const f of trace?.findings ?? []) if (f.severity !== "info") counts[f.severity]++;

  return (
    <div className="flex h-dvh flex-col bg-background text-foreground">
      <header className="flex items-center gap-3 border-b px-4 py-2">
        <h1 className="shrink-0 whitespace-nowrap text-sm font-semibold tracking-tight">
          pandas<span className="text-muted-foreground">-viz</span>
        </h1>
        <Select
          value={exampleId}
          onValueChange={(id) => {
            const ex = examples.find((e) => e.id === id);
            if (!ex) return;
            clearLoaded();
            setExampleId(ex.id);
            onCodeChange(ex.code);
            run(ex.code);
          }}
        >
          <SelectTrigger size="sm" className="w-64 shrink-0">
            <SelectValue placeholder="Load an example…">
              {(id: string | null) => examples.find((e) => e.id === id)?.title ?? "Load an example…"}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {examples.map((ex) => (
              <SelectItem key={ex.id} value={ex.id}>
                {ex.title}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {recent.length > 0 && (
          <Select value={loaded?.id ?? null} onValueChange={(id) => id && loadStored(String(id))}>
            <SelectTrigger size="sm" className="w-48 shrink-0">
              <SelectValue placeholder="Recent traces…">
                {(id: string | null) => recent.find((t) => t.id === id)?.title ?? loaded?.title ?? "Recent traces…"}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {recent.map((t) => (
                <SelectItem key={t.id} value={t.id}>
                  <span className="truncate">{t.title}</span>
                  <span className="ml-auto pl-3 text-xs text-muted-foreground">
                    {new Date(t.created_at).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" })}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <Button size="sm" onClick={() => run(code)} disabled={running}>
          {running ? <Loader2 className="animate-spin" /> : <Play />}
          Run
          <kbd className="ml-1 text-[10px] opacity-60">⌘↵</kbd>
        </Button>
        {trace && <CopyButton text={trace.checks_script ?? ""} label="Copy checks" />}
        {loaded && (
          <span
            className="shrink-0 whitespace-nowrap rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground"
            title="Captured outside the server. Run re-executes the code in the server sandbox, where notebook variables and relative paths may differ."
          >
            saved · {new Date(loaded.created_at).toLocaleTimeString(undefined, { timeStyle: "short" })}
          </span>
        )}
        {trace && (
          <div className="flex shrink-0 items-center gap-3 whitespace-nowrap text-xs text-muted-foreground">
            <span>{nodes.length} steps</span>
            {counts.error > 0 && <span className="text-red-600 dark:text-red-400">{counts.error} errors</span>}
            {counts.warning > 0 && <span className="text-amber-600 dark:text-amber-400">{counts.warning} warnings</span>}
          </div>
        )}
        <div className="ml-auto hidden items-center gap-3 2xl:flex">
          {Object.entries(CATEGORY_LABEL).map(([k, label]) => (
            <span key={k} className="flex items-center gap-1 text-[11px] text-muted-foreground">
              <span className="size-2 rounded-full" style={{ background: CATEGORY_COLOR[k as keyof typeof CATEGORY_COLOR] }} />
              {label}
            </span>
          ))}
        </div>
      </header>

      <ResizablePanelGroup orientation="horizontal" className="min-h-0 flex-1">
        <ResizablePanel defaultSize="36%" minSize="20%">
          <div
            className="relative flex h-full flex-col"
            onDragEnter={(e) => hasFiles(e) && setDragDepth((d) => d + 1)}
            onDragLeave={(e) => hasFiles(e) && setDragDepth((d) => Math.max(0, d - 1))}
            onDragOver={(e) => hasFiles(e) && e.preventDefault()}
            onDrop={(e) => {
              if (!hasFiles(e)) return;
              e.preventDefault();
              setDragDepth(0);
              upload(Array.from(e.dataTransfer.files));
            }}
          >
            <DropOverlay active={dragDepth > 0} />
            <DatasetBar
              datasets={datasets}
              onChange={refreshDatasets}
              onInsert={insertAtCursor}
              onError={setRequestError}
              uploading={uploading}
              onUpload={upload}
            />
            <div className="min-h-0 flex-1">
              <CodeEditor
                value={code}
                onChange={onCodeChange}
                onRun={() => run(code)}
                onLineClick={selectByLine}
                selectedLine={selected?.source_line ?? null}
                errorLine={trace?.error?.line ?? null}
                dark={dark}
                onReady={(view) => {
                  editorView.current = view;
                }}
              />
            </div>
            {Boolean(trace?.error || requestError || trace?.stdout || trace?.warnings?.length) && (
              <div className="max-h-[40%] space-y-2 overflow-auto border-t p-3">
                {requestError && (
                  <Alert variant="destructive">
                    <AlertTitle>Request failed</AlertTitle>
                    <AlertDescription className="whitespace-pre-line">{requestError}</AlertDescription>
                  </Alert>
                )}
                {trace?.error && (
                  <Alert variant="destructive">
                    <AlertTitle>
                      {trace.error.type}
                      {trace.error.line ? ` on line ${trace.error.line}` : ""}
                    </AlertTitle>
                    <AlertDescription>
                      <p>{trace.error.message}</p>
                      <p className="text-xs opacity-80">The graph shows every step up to the failure.</p>
                    </AlertDescription>
                  </Alert>
                )}
                {trace?.warnings?.map((w) => (
                  <p key={w} className="text-xs text-amber-600 dark:text-amber-400">{w}</p>
                ))}
                {trace?.stdout && (
                  <div>
                    <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">stdout</div>
                    <pre className="overflow-x-auto font-mono text-xs">{trace.stdout}</pre>
                  </div>
                )}
              </div>
            )}
          </div>
        </ResizablePanel>
        <ResizableHandle withHandle />
        <ResizablePanel defaultSize="64%" minSize="30%">
          <ResizablePanelGroup orientation="vertical">
            <ResizablePanel defaultSize="58%" minSize="20%">
              {trace && nodes.length > 0 ? (
                <PipelineGraph
                  trace={trace}
                  selectedId={selectedId}
                  compareId={compareId}
                  onSelect={(id) => {
                    setSelectedId(id);
                    if (id === null || id === compareId) setCompareId(null);
                  }}
                  onCompare={(id) => {
                    setCompareId(id);
                    setTab("diff");
                  }}
                />
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                  {running ? "Tracing…" : "Run some pandas code to see its pipeline."}
                </div>
              )}
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel defaultSize="42%" minSize="15%">
              {trace && (
                <Inspector
                  trace={trace}
                  node={selected}
                  tab={tab}
                  onTabChange={setTab}
                  onSelect={setSelectedId}
                  compareId={compareId}
                  onCompare={setCompareId}
                />
              )}
            </ResizablePanel>
          </ResizablePanelGroup>
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}

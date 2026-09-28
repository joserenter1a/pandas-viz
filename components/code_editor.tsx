"use client";

import { python } from "@codemirror/lang-python";
import { StateEffect, StateField, type Extension } from "@codemirror/state";
import { Decoration, EditorView, type DecorationSet } from "@codemirror/view";
import CodeMirror from "@uiw/react-codemirror";
import { useEffect, useRef } from "react";

type Marks = { selected: number | null; error: number | null };

const setMarks = StateEffect.define<Marks>();

const marksField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(deco, tr) {
    deco = deco.map(tr.changes);
    for (const e of tr.effects) {
      if (!e.is(setMarks)) continue;
      const ranges = [];
      const doc = tr.state.doc;
      const { selected, error } = e.value;
      if (error && error <= doc.lines)
        ranges.push(
          Decoration.line({ class: "cm-error-line" }).range(
            doc.line(error).from,
          ),
        );
      if (selected && selected <= doc.lines && selected !== error)
        ranges.push(
          Decoration.line({ class: "cm-selected-line" }).range(
            doc.line(selected).from,
          ),
        );
      deco = Decoration.set(ranges.sort((a, b) => a.from - b.from));
    }
    return deco;
  },
  provide: (f) => EditorView.decorations.from(f),
});

const markTheme = EditorView.baseTheme({
  ".cm-selected-line": {
    backgroundColor: "color-mix(in oklab, #0ea5e9 16%, transparent)",
  },
  ".cm-error-line": {
    backgroundColor: "color-mix(in oklab, #ef4444 18%, transparent)",
  },
});

type Props = {
  value: string;
  onChange: (v: string) => void;
  onRun: () => void;
  onLineClick: (line: number) => void;
  selectedLine: number | null;
  errorLine: number | null;
  dark: boolean;
  onReady?: (view: EditorView) => void;
};

const extensions: Extension[] = [python(), marksField, markTheme];

export function CodeEditor({
  value,
  onChange,
  onRun,
  onLineClick,
  selectedLine,
  errorLine,
  dark,
  onReady,
}: Props) {
  const viewRef = useRef<EditorView | null>(null);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    view.dispatch({
      effects: setMarks.of({ selected: selectedLine, error: errorLine }),
    });
    if (selectedLine && selectedLine <= view.state.doc.lines) {
      view.dispatch({
        effects: EditorView.scrollIntoView(
          view.state.doc.line(selectedLine).from,
          { y: "nearest" },
        ),
      });
    }
  }, [selectedLine, errorLine, value]);

  return (
    <div
      className="h-full"
      onKeyDownCapture={(e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
          e.preventDefault();
          onRun();
        }
      }}
    >
      <CodeMirror
        value={value}
        onChange={onChange}
        extensions={extensions}
        theme={dark ? "dark" : "light"}
        height="100%"
        className="h-full text-[13px]"
        basicSetup={{ highlightActiveLine: false }}
        onUpdate={(u) => {
          if (
            u.selectionSet &&
            u.transactions.some((t) => t.isUserEvent("select"))
          ) {
            onLineClick(u.state.doc.lineAt(u.state.selection.main.head).number);
          }
        }}
        onCreateEditor={(view) => {
          viewRef.current = view;
          onReady?.(view);
        }}
      />
    </div>
  );
}

"""Jupyter integration: ``%load_ext pandas_viz`` then ``%%pandasviz`` on a cell.

The cell runs in the notebook's own namespace (through ``shell.run_cell``, so IPython
features and output display work as usual) while the tracer records every pandas step.
An inline summary is shown below the cell's output; ``--open`` opens the full UI.
"""

import html
import os
import traceback
from pathlib import Path

import IPython
from IPython.core.magic import Magics, cell_magic, magics_class
from IPython.core.magic_arguments import argument, magic_arguments, parse_argstring
from IPython.display import HTML, display

from .models import TraceError, TraceResult
from .tracer import Tracer

# Same palette as web/lib/format.ts
CATEGORY_COLOR = {
    "source": "#64748b", "filter": "#0ea5e9", "projection": "#8b5cf6", "join": "#f59e0b",
    "aggregate": "#10b981", "sort": "#6366f1", "limit": "#06b6d4", "reshape": "#ec4899",
    "mutate": "#84cc16", "other": "#94a3b8",
}
_SEVERITY = {"error": ("✖", "#dc2626"), "warning": ("▲", "#d97706"), "info": ("·", "inherit")}

last_result: TraceResult | None = None


@magics_class
class PandasVizMagics(Magics):
    @magic_arguments()
    @argument("--open", action="store_true",
              help="open the trace in the pandas-viz web UI (starts a server if needed)")
    @argument("--port", type=int, default=8000, help="server port for --open")
    @argument("--title", default=None, help="title for the trace in the UI")
    @argument("-o", "--result", default=None, help="store the TraceResult in this variable")
    @argument("-q", "--quiet", action="store_true", help="don't show the inline summary")
    @argument("--checks", action="store_true",
              help="print generated checks (asserts + merge validate=) to paste into the pipeline")
    @cell_magic
    def pandasviz(self, line: str, cell: str):
        """Trace the pandas operations in this cell."""
        global last_result
        args = parse_argstring(self.pandasviz, line)
        title = args.title.strip("\"'") if args.title else "notebook cell"

        with Tracer() as tracer:
            outcome = self.shell.run_cell(cell, store_history=False)
        tracer.assign_var_names()
        tracer.name_from_namespace(self.shell.user_ns)
        result = tracer.result()
        result.error = _error(outcome)
        last_result = result
        if args.result:
            self.shell.user_ns[args.result] = result

        url = None
        if args.open:
            from .server import open_trace

            try:
                url = open_trace(result, code=cell, title=title,
                                 port=args.port, data_dir=Path.cwd())
            except RuntimeError as exc:
                print(f"pandas-viz: {exc}")
        if not args.quiet:
            display(HTML(render_html(result, url)))
        if args.checks:
            print(result.checks_script or "# no checks generated")


_IPYTHON_DIR = os.path.dirname(IPython.__file__)


def _error(outcome) -> TraceError | None:
    exc = outcome.error_in_exec or outcome.error_before_exec
    if exc is None:
        return None
    # The first frame outside IPython's machinery is the cell itself.
    cell = next((f for f in traceback.extract_tb(exc.__traceback__)
                 if not f.filename.startswith(_IPYTHON_DIR)), None)
    return TraceError(
        type=type(exc).__name__,
        message=str(exc),
        line=cell.lineno if cell else getattr(exc, "lineno", None),
        traceback="".join(traceback.format_exception(exc)),
    )


def render_html(result: TraceResult, url: str | None = None) -> str:
    esc = html.escape
    rows = []
    for n in result.nodes:
        delta = ""
        if n.rows_in is not None and n.rows_in != n.profile.rows:
            diff = n.profile.rows - n.rows_in
            color = "#dc2626" if diff < 0 else "#d97706"
            delta = f' <span style="color:{color}">({diff:+,})</span>'
        rows_text = (f"{n.rows_in:,} → {n.profile.rows:,}" if n.rows_in is not None
                     else f"{n.profile.rows:,}")
        rows.append(
            "<tr>"
            f'<td style="opacity:.6">{f"L{n.source_line}" if n.source_line else ""}</td>'
            f'<td><span style="color:{CATEGORY_COLOR[n.category]};font-weight:600">'
            f"{esc(n.category)}</span></td>"
            f'<td><code>{esc(n.var_name or "")}</code></td>'
            f"<td><code>{esc(n.label)}</code></td>"
            f'<td style="text-align:right;white-space:nowrap">{rows_text}{delta}</td>'
            f'<td style="text-align:right">{n.profile.cols}</td>'
            "</tr>"
        )
    parts = [
        '<div style="font-size:13px;line-height:1.4">',
        f"<div style=\"margin:4px 0\"><b>pandas-viz</b> · {len(result.nodes)} steps"
        + (f' · <a href="{esc(url)}" target="_blank">open in pandas-viz ↗</a>' if url else "")
        + "</div>",
    ]
    if rows:
        parts.append(
            '<table style="border-collapse:collapse"><thead><tr style="text-align:left">'
            "<th>line</th><th>step</th><th>var</th><th>operation</th>"
            '<th style="text-align:right">rows</th><th style="text-align:right">cols</th>'
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        )
    if result.findings:
        items = []
        for f in sorted(result.findings, key=lambda f: ("error", "warning", "info").index(f.severity)):
            mark, color = _SEVERITY[f.severity]
            rows = ""
            if ex := result.examples_for(f):
                rows = (f'<details style="margin:2px 0 6px 18px"><summary style="cursor:pointer;opacity:.7">'
                        f"{esc(ex.label.lower())} ({ex.total:,})</summary>{_examples_table(ex)}</details>")
            items.append(f'<li><span style="color:{color}">{mark}</span> {esc(f.message)}{rows}</li>')
        parts.append('<ul style="list-style:none;padding-left:0;margin:6px 0">' + "".join(items) + "</ul>")
    if result.hints:
        items = []
        for h in result.hints:
            code = f'<br><code style="margin-left:18px">{esc(h.suggestion)}</code>' if h.suggestion else ""
            items.append(f'<li><span style="color:#0284c7">→</span> {esc(h.message)}{code}</li>')
        parts.append('<div style="margin-top:6px;opacity:.8">hints (same result, less work)</div>'
                     '<ul style="list-style:none;padding-left:0;margin:2px 0">' + "".join(items) + "</ul>")
    for w in result.warnings:
        parts.append(f'<div style="color:#d97706">{esc(w)}</div>')
    if not url:
        parts.append('<div style="opacity:.6">Tip: <code>%%pandasviz --open</code> explores this '
                     "trace in the web UI.</div>")
    parts.append("</div>")
    return "".join(parts)


def _examples_table(ex) -> str:
    esc = html.escape
    head = "".join(f"<th>{esc(c)}</th>" for c in ["", *ex.columns])
    body = []
    for idx, row in zip(ex.index, ex.rows):
        cells = "".join(
            f'<td style="{"opacity:.5;font-style:italic" if v is None else ""}">'
            f'{"null" if v is None else esc(str(v))}</td>' for v in row)
        body.append(f'<tr><td style="opacity:.6">{esc(str(idx))}</td>{cells}</tr>')
    return (f'<table style="border-collapse:collapse;margin-top:4px"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


def load_ipython_extension(ipython):
    ipython.register_magics(PandasVizMagics)

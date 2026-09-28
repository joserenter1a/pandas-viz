"""Command line: ``pandas-viz serve`` and ``pandas-viz run script.py``."""

import argparse
import json
import os
import sys
from pathlib import Path

from .models import TraceResult

_SEVERITY_MARK = {"error": "✖", "warning": "▲", "info": "·"}


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(prog="pandas-viz")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="start the web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--data-dir", type=Path, default=Path("."),
                       help="working directory for traced code (relative file paths resolve here)")
    serve.add_argument("--reload", action="store_true")

    run = sub.add_parser("run", help="trace a script and print a step-by-step summary")
    run.add_argument("script", type=Path)
    run.add_argument("--json", type=Path, help="also write the full trace JSON here")
    run.add_argument("--open", action="store_true",
                     help="open the trace in the web UI (starts a server if none is running)")
    run.add_argument("--port", type=int, default=8000, help="server port for --open")
    run.add_argument("--diff", nargs=2, metavar=("A", "B"),
                     help="compare two steps, by variable name or node id (e.g. --diff orders revenue)")
    run.add_argument("--checks", nargs="?", const="-", metavar="FILE",
                     help="print generated checks (asserts + merge validate=) or write them to FILE")

    args = parser.parse_args(argv)
    if args.command == "serve":
        import uvicorn
        os.environ["PANDAS_VIZ_DATA_DIR"] = str(args.data_dir.resolve())
        uvicorn.run("pandas_viz.app:app", host=args.host, port=args.port, reload=args.reload)
    elif args.command == "run":
        sys.exit(_run(args.script, args.json, open_ui=args.open, port=args.port, checks=args.checks,
                      diff=args.diff))


def _run(script: Path, json_out: Path | None, *, open_ui: bool = False, port: int = 8000,
         checks: str | None = None, diff: list[str] | None = None) -> int:
    from .worker import run_code

    path = script.resolve()
    code = path.read_text()
    sys.path.insert(0, str(path.parent))
    result = run_code(code, filename=str(path))
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    print(format_summary(result))
    if json_out:
        json_out.write_text(json.dumps(result.model_dump(mode="json"), indent=2))
    if diff:
        from .diff import format_diff

        try:
            print("\n" + format_diff(result.diff(*diff)))
        except KeyError as exc:
            print(f"\npandas-viz: {exc.args[0]}", file=sys.stderr)
            return 2
    if checks == "-":
        print("\n" + (result.checks_script or "# no checks generated"))
    elif checks:
        Path(checks).write_text(result.checks_script)
        print(f"\nwrote {sum(c.kind != 'pandera' for c in result.checks)} checks to {checks}")
    if open_ui:
        from .server import open_trace

        try:
            url = open_trace(result, code=code, title=str(script), port=port, data_dir=path.parent)
        except RuntimeError as exc:
            print(f"pandas-viz: {exc}", file=sys.stderr)
            return 2
        print(f"\nopened {url}")
    return 1 if result.error else 0


def format_summary(result: TraceResult) -> str:
    lines = ["", f"pandas-viz: {len(result.nodes)} steps"]
    for n in result.nodes:
        rows = f"{n.rows_in:,} → {n.profile.rows:,}" if n.rows_in is not None else f"{n.profile.rows:,}"
        where = f"L{n.source_line}" if n.source_line else "   "
        name = f"{n.var_name} = " if n.var_name else ""
        lines.append(f"  {where:>5}  {n.category:<10} {rows:>18} rows × {n.profile.cols:<3} {name}{n.label}")
    if result.findings:
        lines.append("")
        lines.append("findings:")
        for f in result.findings:
            lines.append(f"  {_SEVERITY_MARK[f.severity]} [{f.node_id}] {f.message}")
            if ex := result.examples_for(f):
                lines += _example_lines(ex)
    if result.hints:
        lines.append("")
        lines.append("hints (same result, less work):")
        by_id = {n.id: n for n in result.nodes}
        for h in result.hints:
            n = by_id.get(h.node_id)
            where = f"L{n.source_line}" if n and n.source_line else h.node_id
            lines.append(f"  → [{where}] {h.message}")
            if h.suggestion:
                lines.append(f"      {h.suggestion}")
    if result.error:
        lines.append("")
        lines.append(f"error at line {result.error.line}: {result.error.type}: {result.error.message}")
    return "\n".join(lines)


def _example_lines(ex, limit: int = 3) -> list[str]:
    import pandas as pd

    df = pd.DataFrame(ex.rows[:limit], columns=ex.columns, index=ex.index[:limit])
    more = f" (showing {min(limit, len(ex.rows))} of {ex.total:,})" if ex.total > limit else ""
    table = df.to_string(max_colwidth=24, max_cols=8).splitlines()
    return [f"      {ex.label.lower()}{more}:"] + [f"        {line}" for line in table]


if __name__ == "__main__":
    main()

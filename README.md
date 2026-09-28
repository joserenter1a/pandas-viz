# pandas-viz

See what every step of a pandas pipeline does to your data: a graph of operations with
row counts, schemas, join diagnostics, and findings such as where rows were lost, where
nulls first appeared, and where dtypes silently drifted.

See [design.md](design.md) for the full design and roadmap.

## Quick start

```bash
uv sync
cd web && npm install && npm run build && cd ..   # build the UI once
uv run pandas-viz serve                            # http://127.0.0.1:8000
```

Code you paste runs in a subprocess, and its working directory is `--data-dir` (default:
the current directory), so `pd.read_csv("data/orders.csv")` resolves relative to it.
Only run this locally: the tool executes the code you give it.

### Upload datasets

Drop CSV, TSV, Parquet or JSON/JSONL files on the editor (or use **Upload**). Each file
becomes a variable named after it: `Q3 Orders.csv` → `q3_orders`. Click a dataset chip to
insert its name. Only the datasets your code reads are loaded, and each appears in the
graph as a `dataset` source. Files live in `~/.pandas-viz/datasets/`; uploading a file
with the same name replaces it. The size limit is 500 MB (`PANDAS_VIZ_MAX_UPLOAD_MB`).

### Trace a script from the terminal

```bash
uv run pandas-viz run etl/orders.py            # step-by-step summary + findings
uv run pandas-viz run etl/orders.py --open     # ...and open it in the web UI
uv run pandas-viz run etl/orders.py --json trace.json
```

`--open` saves the trace to `~/.pandas-viz/traces/` (override with `PANDAS_VIZ_HOME`),
starts `pandas-viz serve` in the background if nothing is listening on `--port` (default
8000; its log is `~/.pandas-viz/server.log`), and opens `/?trace=<id>`. Recent traces
are also listed in the UI header.

### Lost-row examples

Findings come with the rows behind them: rows a filter or `dropna` dropped, join rows
with no match, duplicate or null join keys, and rows where a column first became null.
Click **rows** next to a finding, or open a step's **Details** tab. `pandas-viz run`
prints up to 3 rows under each finding, and in notebooks each finding has a collapsible
table.

### Pushdown hints

pandas runs each step eagerly with no query optimizer. The **Hints** tab (also printed
by `pandas-viz run`, and shown in notebooks) suggests rewrites that give the same result
with less work:

- a filter after a join that only uses one side's columns, rewritten to run before the
  join (never suggested where it would change the result, e.g. the right side of a left join);
- a filter after a sort or row-wise step it doesn't depend on;
- columns read from a file that nothing uses (`usecols=` / `columns=`);
- a sort whose order the next step throws away;
- slow row-wise `apply(axis=1)`, the same file read twice, and `inplace=True`.

### Copy as checks

Every trace also produces code that guards the pipeline: `validate=` edits for merges,
and asserts on row counts, join keys, nulls, dtypes and output schemas. Each check is
marked ✓ (holds on the traced data, so it locks in current behaviour) or ✗ (fails on the
traced data, so it would have caught one of the findings). A pandera schema is generated
for each named step.

- Web UI: **Copy checks** in the header, the pipeline **Checks** tab, or a step's **Checks** tab
- CLI: `pandas-viz run etl.py --checks` (print) or `--checks checks.py` (write a file)
- Notebook: `%%pandasviz --checks`, or `result.checks` / `result.checks_script`

### Compare two steps

Every step's **Diff** tab compares it with its input, or with any other step you pick.
Shift+click a second step in the graph to compare with it. The diff shows the row and
column deltas, the path of steps between the two, and every column added, removed,
renamed (a heuristic) or changed in dtype or null count.

- CLI: `pandas-viz run etl.py --diff orders revenue` (variable names or node ids)
- Python / notebook: `result.diff("orders", "revenue")`

### Trace a notebook cell

```python
%load_ext pandas_viz
```

```python
%%pandasviz --open
enriched = orders.merge(users, on="user_id", how="left")
revenue = enriched.groupby("country").agg(total=("amount", "sum"))
```

The cell runs in the notebook's own namespace, and a step table with findings is shown
below its output. Options: `--open` (explore in the web UI), `-o NAME` (store the
`TraceResult` in a variable), `-q` (no inline summary), `--title`, `--port`. Install
the IPython dependency with `uv add 'pandas-viz[notebook]'`.

### Trace from Python

```python
import pandas_viz

with pandas_viz.trace() as t:
    df = orders.merge(users, on="user_id", how="left")

result = t.result()   # nodes, edges, findings
t.open()              # or view it in the web UI
```

## Development

```bash
uv run pandas-viz serve --reload   # API on :8000
cd web && npm run dev              # UI on :3000, proxies /api to :8000
uv run pytest                      # backend tests
cd web && npm run gen:api          # regenerate TS types after changing models.py
```

Layout: `src/pandas_viz/` holds the tracer, profiler, findings, runner, FastAPI app and
CLI. `web/` holds the Next.js + shadcn/ui frontend, which is built as a static export and
served by FastAPI.

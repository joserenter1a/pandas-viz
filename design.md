# pandas-viz — Design Document

**Status:** M0–M2 implemented, plus the Findings panel and join inspector from M3, the M4 entry points (`pandas-viz run --open`, the `%%pandasviz` magic and `Tracer.open()`), all of M5 ("Copy as checks", node diff, dataset upload), and all of M6 (lost-row examples, with D10 decided, and pushdown hints in `lint.py`). Some decisions are still open (see [§11](#11-open-decisions))
**Author:** José Renteria
**Date:** 2026-09-25

**References:**

- [SQL Query Visualizer](https://tinkertools.app/tools/sql-query-visualizer): parses SQL and draws tables as nodes and joins as edges, next to a breakdown panel.
- [DataFusion Plan Visualizer](https://datafusion-plan-visualizer.vercel.app): lets you drop in files to register tables and shows logical, optimized and physical plan tabs, with a diff view and a legend of operator types.

---

## 1. Problem

pandas code is imperative and eager. It gives you no query plan to inspect. When a pipeline like this one produces surprising output, it's hard to tell which step caused it:

```python
orders = pd.read_csv("orders.csv")
users  = pd.read_csv("users.csv")
df = (orders[orders.status == "paid"]
        .merge(users, on="user_id", how="left")
        .groupby("country")
        .agg(revenue=("amount", "sum"), n=("order_id", "count")))
```

Questions like these are hard to answer without scattering `print(df.shape)` through the code:

- How many rows did each step keep or drop?
- Did the merge fan out (many-to-many) or leave unmatched keys?
- Which columns were added or dropped, and which dtypes changed?
- How many groups did the aggregation produce, and how big are they?

## 2. Landscape and demand

*Research done 2026-09-25. Sources are listed at the end of this section.*

### 2.1 Existing tools

No tool combines **visual pipeline graph + real data + real code + engineering-grade diagnostics** for pandas. The closest tools each cover one slice:

| Tool                                                                                                                                                                                                         | What it is                                                                                                                  | Key features                                                                                                                                                                                                                                                   | Gap for data engineers                                                                                                                                                                                                                                                                                                                                                                       |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **[Pandas Tutor](https://pandastutor.com)** (UCSD: Sam Lau, Philip Guo)                                                                                                                                 | **The closest direct comparison.** A browser tool that visualizes how pandas code transforms dataframes, step by step | Step-by-step diagrams linking input rows to output rows for sort, filter, groupby and aggregate. Shareable URLs that embed the CSV. Runs**in the browser through Pyodide**, with a pure-Python tracer shipped as a wheel. Also used as a visual debugger | **Built for teaching.** Code is capped at 5 KB, data must be tiny and pasted inline, and it can't read files or URLs. Only the expression on the **last line** is visualized, and pandas method coverage is limited. It shows a linear sequence of steps rather than a DAG of the whole script, and has no join diagnostics, null or dtype tracking, or notebook/CLI integration |
| **[Tidy Data Tutor](https://tidydatatutor.com)**                                                                                                                                                        | The R/dplyr sibling of Pandas Tutor                                                                                         | Same step-by-step visuals. An R package sends code from RStudio to the site                                                                                                                                                                                    | R only. Shows that "send from my editor" is wanted                                                                                                                                                                                                                                                                                                                                           |
| **[dframe-trace](https://github.com/vimalnakrani08/dframe-trace)** (June 2026, brand new)                                                                                                               | Headless tracer for pandas and Polars                                                                                       | Patches DataFrame methods automatically. Answers queries like`where_null_introduced(col)` and `where_rows_lost()`. Provides CI guards (`assert_no_row_loss`, `assert_no_new_nulls`, `assert_no_silent_casts`). Records metadata only, no row values  | **No UI and no graph.** It confirms the same problem and tracing approach as ours (§5, option B), but gives text output only                                                                                                                                                                                                                                                          |
| **[pandas-log](https://github.com/eyaltrabelsi/pandas-log)**, **[pdlog](https://github.com/DataProphet/pdlog)**                                                                                    | Ports of R's`tidylog`                                                                                                     | Log lines per operation, for example`dropna: dropped 1 row (17%), 5 rows remaining`                                                                                                                                                                          | Text only, and each covers a fixed subset of methods                                                                                                                                                                                                                                                                                                                                         |
| **[pandas-pipeline-graphviz](https://github.com/qchenevier/pandas-pipeline-graphviz)**                                                                                                                  | Decorator that renders a Graphviz diagram of a pipeline                                                                     | Column names on each node, with created columns highlighted                                                                                                                                                                                                    | 11 stars. Works only with decorated single-output functions. Static image, no data stats                                                                                                                                                                                                                                                                                                     |
| **[VS Code Data Wrangler](https://code.visualstudio.com/docs/datascience/data-wrangler)**, **[marimo `mo.ui.dataframe`](https://docs.marimo.io/api/inputs/dataframe/)**, Mito, PyGWalker, D-Tale | Viewers and GUIs for building transforms                                                                                    | Grid view, column stats, point-and-click transforms that**generate pandas code**. Data Wrangler has a "cleaning steps" list that highlights changes                                                                                                      | The direction is reversed: they go from GUI to code. They don't explain**existing** code, and they show one frame at a time rather than a pipeline graph                                                                                                                                                                                                                               |
| **[Polars `show_graph()` / `explain()`](https://docs.pola.rs/user-guide/lazy/query-plan/)**                                                                                                         | Lazy query plan rendering                                                                                                   | Optimized plan with predicate and projection pushdown                                                                                                                                                                                                          | Polars lazy only. Graphviz output is hard to read, with an[open issue on readability](https://github.com/pola-rs/polars/issues/23764). No data stats                                                                                                                                                                                                                                          |
| **[Kedro-Viz](https://github.com/kedro-org/kedro-viz)**, **[Hamilton UI](https://blog.dagworks.io/p/hamilton-and-kedro-for-modular-data)**                                                         | Pipeline DAG and lineage UIs                                                                                                | Rich DAG, metadata panels and column-level lineage (Hamilton)                                                                                                                                                                                                  | You have to adopt the framework. They work at the level of pipeline functions, not individual pandas operations                                                                                                                                                                                                                                                                              |

**Positioning:** *"Pandas Tutor for real pipelines"*: your own code, your own files and whole scripts, plus the diagnostics that dframe-trace and tidylog provide, all in one visual DAG. It adds the plan-style presentation of the DataFusion and SQL visualizers.

**Validation of earlier decisions:** Pandas Tutor and dframe-trace both independently use runtime tracing, which supports D1 = B. Pandas Tutor's move from Docker to Pyodide supports keeping the Pyodide option open in D2.

### 2.2 Demand signals

The evidence is **indirect but consistent**. I didn't find a forum thread asking for exactly this tool. What I did find:

1. **The same tool keeps getting rebuilt.** pandas-log, pdlog, pandas-chained-logging, pandas-pipeline-graphviz and dframe-trace (in 2026) all target "what did each step do to my frame?". Low star counts across all of them point to a **UX and discoverability gap**, not a lack of need. Logs and decorators are too much friction.
2. **Silent merge bugs are a recurring pain.** Blog posts on the topic keep appearing, such as "the join that doubled the revenue" and "why did my DataFrame lose rows?". There are also pandas issues on duplicated merge rows and a long-standing request to [check merge cardinality (#16270)](https://github.com/pandas-dev/pandas/issues/16270). The standard advice is still to print row counts before and after, use `indicator=True`, and always pass `validate=`, which is manual work this tool can do automatically.
3. **Silent null and dtype drift** is the other named category: nulls from lookups or pivots, and ints turning into floats or objects. It is the core pitch of dframe-trace.
4. **Visual step-by-step tools are popular for learning.** Pandas Tutor serves 500+-student lectures, was featured on Talk Python #358 and has a SIGCSE 2025 paper. Tidy Data Tutor exists for R. Pandas Tutor users already use it as a "visual debugger" despite its limits, which is the gap for professionals.
5. **Mixed pandas and Polars stacks are common**: pandas for exploration, Polars for production. The sources here are blog-grade, so treat any specific percentages as soft.

### 2.3 Features data engineers would value (prioritized)

| Pri          | Feature                                                                                                                                                                                         | Why (signal)                                                                                                                      | Section  |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | -------- |
| **P0** | **Row-flow view**: edges sized by row count, with dropped and added rows called out per step                                                                                              | The#1 pain is "where did my rows go?" (§2.2 items 1–2)                                                                          | §8      |
| **P0** | **Join inspector**: cardinality (1:1, 1:m, m:m), match counts per side, explosion factor, key dtype mismatch, `_x`/`_y` collisions, **plus a suggested `validate=` argument** | The#2 pain is silent merge bugs (§2.2 item 2)                                                                                    | §7.1    |
| **P0** | **Null and dtype drift tracking**: "nulls in `col` first appeared at step N", flags for int→float, →object and pandas 3.0 string dtype changes                                        | §2.2 item 3. dframe-trace's`where_null_introduced` as a visual                                                                 | §7.3    |
| **P0** | **Run real code on real files**: whole scripts, any size (with sampled profiling), local files and Parquet                                                                                | Removes Pandas Tutor's main limits (5 KB, last line only, inline CSV)                                                             | §5, §9 |
| **P1** | **Trace from where developers already work**: `with pandas_viz.trace():` context manager, `pandas-viz run script.py` CLI that opens the browser, and a `%%pandasviz` Jupyter magic  | Developers won't paste code into a website. The Tidy Data Tutor R package and dframe-trace's one-line autopatch show this matters | §6.4    |
| **P1** | **"Export as checks"**: turn what was observed into code, such as `validate="m:1"`, `assert len(df) == …`, a pandera schema, or dframe-trace-style guards for CI                     | Moves from "I saw the bug" to "it can't come back". dframe-trace has CI guards but no way to generate them                        | §7.4    |
| **P1** | **Row-level lineage**: click an output row to highlight the source rows that fed it, including every row behind an aggregate                                                              | Pandas Tutor's signature visual, applied to real pipelines                                                                        | §7.5    |
| **P2** | **Polars support** (eager, and lazy through `.collect()`), with the lazy optimized plan in a tab                                                                                        | Mixed stacks (§2.2 item 5). Also delivers the pushdown story in D4                                                               | D4       |
| **P2** | **Run-to-run diff**: edit the code, re-run, and see which nodes changed shape, schema or rows                                                                                             | The equivalent of the DataFusion visualizer's plan diff                                                                           | §7.2    |
| **P2** | **Per-step time and memory**, with slow `apply` and `iterrows` flagged                                                                                                                | Performance is a common pandas complaint                                                                                          | §7      |
| **P2** | **Shareable link or standalone HTML report** of a trace                                                                                                                                   | Pandas Tutor's shareable URLs. Useful in PR reviews                                                                               | —       |

### 2.4 Sources

- Pandas Tutor: [site](https://pandastutor.com/), [Pyodide blog post](https://blog.pyodide.org/posts/pandastutor/), [Talk Python #358](https://talkpython.fm/episodes/show/358/understanding-pandas-visually-with-pandastutor), [limitations write-up](https://ealizadeh.com/blog/pandas-tutor-tool/), [SIGCSE 2025 paper](https://lau.ucsd.edu/pubs/2025_sigcse_pandas_tutor_SIGCSE.pdf)
- [Tidy Data Tutor](https://tidydatatutor.com/), [tidydatatutor R package](https://cran.r-project.org/web/packages/tidydatatutor/index.html)
- dframe-trace: [GitHub](https://github.com/vimalnakrani08/dframe-trace), [DEV article](https://dev.to/vimal_nakrani/why-did-my-dataframe-lose-rows-debugging-silent-pandas-pipeline-failures-4i0)
- [pandas-log](https://github.com/eyaltrabelsi/pandas-log), [pdlog](https://github.com/DataProphet/pdlog), [tidylog (CRAN)](https://cran.r-project.org/package=tidylog), [pandas-pipeline-graphviz](https://github.com/qchenevier/pandas-pipeline-graphviz)
- [VS Code Data Wrangler](https://code.visualstudio.com/docs/datascience/data-wrangler), [marimo dataframe transforms](https://docs.marimo.io/api/inputs/dataframe/), [Show HN: PyGWalker](https://news.ycombinator.com/item?id=34869244), [Show HN: Mito](https://news.ycombinator.com/item?id=26377559)
- Polars: [query plan guide](https://docs.pola.rs/user-guide/lazy/query-plan/), [show_graph readability issue #23764](https://github.com/pola-rs/polars/issues/23764)
- [Kedro-Viz](https://github.com/kedro-org/kedro-viz), [Hamilton + Kedro](https://blog.dagworks.io/p/hamilton-and-kedro-for-modular-data)
- Merge pain: [pandas #16270](https://github.com/pandas-dev/pandas/issues/16270), [pandas #27314](https://github.com/pandas-dev/pandas/issues/27314), [&#34;the one that doubled the revenue&#34;](https://dev.to/michaelnocito/pandas-merge-left-join-inner-join-and-the-one-that-doubled-the-revenue-21lf), [non-unique keys](https://www.bitsfolio.com/pandas-merge-duplicate-rows-non-unique-key/), [validate= guide](https://blog.dailydoseofds.com/p/a-lesser-known-feature-of-the-merge)

## 3. Goals and non-goals

**Goals**

1. Paste pandas code, or load an example, and see the pipeline as a **graph of operations** (DAG).
2. Show the **data at each node**: shape, schema and dtypes, a sample of rows, null counts and memory use.
3. Give **operation-specific insight** for joins, filters, aggregations, reshapes and column changes (see §7).
4. Show a **diff between any two nodes**, covering columns added, removed or changed, row delta and dtype changes. This mirrors the diff view in the DataFusion visualizer.
5. Let users **upload their own data** (CSV, Parquet, JSON) and use it as named inputs.
6. Keep the tool simple: a single FastAPI app, fast to run locally.
7. **Answer "where did it go wrong?" directly**: where rows were lost, which join fanned out, where nulls first appeared and where dtypes drifted (§2.3, P0).
8. **Work on real code and real data**: whole scripts, local files, no size cap beyond sampling. This is the main difference from Pandas Tutor.
9. **Meet developers where they work**: a context manager and a CLI in addition to the paste box (§6.4).

**Non-goals (v1)**

- Full pandas API coverage. We target the roughly 40 most common operations and draw everything else as a generic node.
- Polars support. This is P2, and the tracer's op registry should be designed so a Polars adapter can plug in later.
- Performance profiling beyond per-step wall time.
- Multi-user hosting with auth.

## 4. Reality check on "filters/pushdowns"

pandas has **no query optimizer**, so it never pushes filters or projections down. The only pushdown-like behaviour is at read time: `read_parquet(columns=..., filters=...)` and `read_csv(usecols=...)`.

We can still deliver the insight in two ways:

- **Pushdown hints (cheap)** ✅ implemented in `lint.py`: a lint pass over the traced graph that flags missed opportunities. Hints are only suggested where the rewrite keeps the result the same; for example, a filter on the right side of a left join is never pushed down. Examples:
  - A filter that runs after a merge but only touches columns from one side, so it could run before the merge.
  - Columns read in but never used, which `usecols` or `columns=` could skip.
  - A `sort_values` whose order a later `groupby` throws away.
- **Optimized plan tab (expensive, optional):** translate the traced graph into a lazy engine (Polars `LazyFrame`, DuckDB or Ibis), then show that engine's optimized plan side by side with the eager pandas pipeline. This is the most direct analogue of the DataFusion Logical/Optimized tabs. See decision **D4**.

## 5. Core approach: how we capture the pipeline

This is the most important decision (**D1**). There are three options.

### Option A: Static AST analysis

Parse the code with `ast`, match known pandas calls and build the graph without running anything.

- ✅ Safe, since no code runs, and fast. Works in the browser too.
- ❌ No shapes, no data and no dtypes, which is most of the value. It also breaks on variables, loops and helper functions.

### Option B: Runtime tracing (recommended)

Execute the code in a controlled namespace where `pd.DataFrame` and `pd.Series` methods are **wrapped** (monkeypatched for the duration of the run). Each wrapped call:

1. Looks up the input frame(s) in a registry (`id(obj)` → node id, held through `weakref`) to find parent nodes.
2. Calls the real method and times it.
3. Registers the result as a new node, with the method name, args or kwargs (summarized), source line (from `inspect`/`sys._getframe`) and a **profile** of the output.

This handles method chains, intermediate variables, functions and loops for free, because it observes what actually ran.

- ✅ Real shapes, dtypes, samples and join statistics. Robust to any code style.
- ❌ Runs user code, which has security implications (see §9). Wrapping has to cover dunder paths too: `__getitem__` for boolean masks and column selection, `__setitem__` for `df["x"] = ...`, and `.loc`/`.iloc` indexers.
- Note: pandas 3.0, which the project already pins, has **Copy-on-Write on by default**. Almost every operation returns a new object, which keeps identity-based lineage clean. In-place mutations like `__setitem__` get modelled as a new "version" node of the same variable.

### Option C: Hybrid

Use the AST for structure and variable names, and runtime tracing for data. This is more work and only marginally better than B, since B can recover variable names from frame locals after execution.

**Recommendation:** B, with a small AST pre-pass used only to label nodes with variable names and source lines.

## 6. Architecture

```
┌──────────────────────── Browser ────────────────────────┐
│  Code editor  │  DAG canvas  │  Node inspector / Diff    │
└───────┬───────────────▲──────────────────────────────────┘
        │ POST /api/trace│ JSON graph
┌───────▼───────────────┴──────── FastAPI ─────────────────┐
│  routes  →  sandbox runner (subprocess, timeout, limits) │
│                 └─ tracer (wrap pandas) → profiler       │
│                 └─ linter (pushdown hints)               │
│                 └─ [optional] lazy translator (D4)       │
│  dataset store (uploads, examples)                       │
└──────────────────────────────────────────────────────────┘
```

### 6.1 Backend modules (`src/pandas_viz/`)

| Module          | Responsibility                                                                                             |
| --------------- | ---------------------------------------------------------------------------------------------------------- |
| `app.py`      | FastAPI app, routes, static file serving                                                                   |
| `tracer.py`   | Wrap and unwrap pandas methods, maintain the lineage registry, emit`Node`/`Edge`                       |
| `profiler.py` | Compute`FrameProfile` for a DataFrame or Series (shape, dtypes, nulls, sample, memory), capped by limits |
| `ops/`        | Per-operation enrichers:`merge.py`, `groupby.py`, `filter.py`, `reshape.py`, …                    |
| `runner.py`   | Run a trace in an isolated subprocess with a timeout and memory cap. Return a serialized graph             |
| `lint.py`     | Pushdown and anti-pattern hints over the graph                                                             |
| `datasets.py` | Upload handling, example datasets, loading them into the namespace as named variables                      |
| `models.py`   | Pydantic schemas (below)                                                                                   |

### 6.2 Data model (Pydantic)

```python
class ColumnInfo(BaseModel):
    name: str; dtype: str; null_count: int; n_unique: int | None

class FrameProfile(BaseModel):
    kind: Literal["DataFrame", "Series", "GroupBy", "Scalar"]
    rows: int; cols: int; memory_bytes: int
    columns: list[ColumnInfo]
    index: list[str]                       # index level names/dtypes
    sample: list[dict]                     # head(N), JSON-safe

class Node(BaseModel):
    id: str
    op: str                                # "merge", "filter", "groupby.agg", "read_csv", …
    category: Literal["source","filter","projection","join","aggregate",
                      "sort","reshape","mutate","limit","other"]
    label: str                             # e.g. "orders[orders.status == 'paid']"
    var_name: str | None
    source_line: int | None
    args: dict[str, str]                   # repr-truncated
    profile: FrameProfile
    duration_ms: float
    details: dict                          # op-specific (see §7)
    hints: list[Hint]

class Edge(BaseModel):
    source: str; target: str
    role: Literal["input","left","right","other"] = "input"

class TraceResult(BaseModel):
    nodes: list[Node]; edges: list[Edge]
    stdout: str; error: TraceError | None  # partial graph returned on error
```

### 6.3 API

| Method   | Path              | Purpose                                                                                       |
| -------- | ----------------- | --------------------------------------------------------------------------------------------- |
| `POST` | `/api/trace`    | `{code, dataset_ids, options}` → `TraceResult`                                           |
| `POST` | `/api/datasets` | Upload a file →`{id, name, profile}`                                                       |
| `GET`  | `/api/datasets` | List uploaded and example datasets                                                            |
| `GET`  | `/api/examples` | Built-in example snippets and their datasets                                                  |
| `POST` | `/api/diff`     | `{trace_id, node_a, node_b}` → column, dtype and row diff (could also be done client-side) |
| `POST` | `/api/plan`     | *(D4)* Translated lazy-engine plan for a trace                                              |

On error, the trace still returns the graph **up to the failing node**. The failing node is marked red and carries the traceback. Partial results matter because debugging is the main use case.

### 6.4 Entry points (P1)

The tracer is a standalone library (`pandas_viz.tracer`) that doesn't depend on the web app. There are three ways into it:

```python
# 1. Context manager: in any script or notebook cell
import pandas_viz
with pandas_viz.trace() as t:
    df = run_my_pipeline()
t.open()          # launch or reuse the local UI and show this trace
t.save("trace.json")
```

```bash
# 2. CLI: trace an existing script without editing it
pandas-viz run etl/orders.py --open
pandas-viz serve            # the UI, with the paste box and saved traces
```

```python
# 3. Jupyter / marimo cell magic
%%pandasviz
df = orders.merge(users, on="user_id")
```

The paste-code web flow from §3 stays as the fourth entry point and is the demo path.

## 7. Visualizations per operation

| Category             | Operations                                                                                                   | Node details                                                                                   |
| -------------------- | ------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| **Source**     | `read_csv/parquet/json`, `DataFrame(...)`, uploaded dataset                                              | Schema, rows, file size, columns never used downstream (hint)                                  |
| **Filter**     | boolean`__getitem__`, `query`, `loc[mask]`, `dropna`, `drop_duplicates`, `head/tail`, `sample` | Predicate text,**rows kept/dropped bar**, % selectivity                                  |
| **Projection** | `df[[cols]]`, `drop(columns=)`, `rename`, `filter(items=)`                                           | Column in/out chips (kept / dropped / renamed)                                                 |
| **Join**       | `merge`, `join`, `concat`                                                                              | See 6.1                                                                                        |
| **Aggregate**  | `groupby().agg/sum/mean/size/…`, `pivot_table`, `value_counts`, `describe`                          | Group key(s),**number of groups**, group-size histogram (min/median/max), output columns |
| **Mutate**     | `assign`, `df[c] = …`, `astype`, `fillna`, `apply`, `map`, `where`                            | Columns added or changed, dtype before → after, nulls before → after                         |
| **Sort/Limit** | `sort_values`, `sort_index`, `nlargest`                                                                | Sort keys, whether order is preserved downstream                                               |
| **Reshape**    | `melt`, `pivot`, `stack/unstack`, `explode`, `set_index/reset_index`, `transpose`                | Shape before → after (a "wide ↔ long" glyph), index change                                   |
| **Other**      | Anything else traced                                                                                         | Generic profile                                                                                |

### 7.1 Join inspector (the headline feature)

For `merge`, `join` and `concat`, compute and show:

- **Cardinality:** 1:1, 1:m, m:1 or m:m, computed from key uniqueness on each side. Warn when m:m.
- **Match Venn:** left-only / both / right-only key counts, the same information `indicator=True` gives. Shown as a small Venn or stacked bar.
- **Row explosion factor:** `out_rows / left_rows`, with a warning above 1 for left joins.
- **Key dtype mismatch** (for example `int64` vs `object`) and null keys on either side.
- Suffix collisions (`_x`/`_y` columns created).

### 7.2 Node diff (any two nodes) ✅

- Columns added (green), removed (red), renamed (heuristic) and dtype changed (amber).
- Row count delta and null-count delta per shared column.
- The path of steps between the two nodes, with row counts, and index changes.
- Implemented over profiles only (`diff.py`, `POST /api/diff`, `TraceResult.diff`), so it also works on saved traces.
- *Not done:* a row-level diff when both nodes share an index. Traces keep only a 20-row sample per node, so this needs retained frames (or a keyed row hash per node) at trace time. It belongs with row-level lineage (§7.5 / D10). Lost-row examples cover the most common case: which rows a step dropped.

### 7.3 Pipeline-wide diagnostics (P0)

These are cross-node questions answered in a **"Findings" panel**. Each finding links to its node.

- **Row flow:** a per-step table of rows in → out, with the biggest drops and explosions ranked.
- **Null origin:** for each column, the first node where its null count went up, and by how much.
- **Dtype drift:** every node where a column's dtype changed and the change wasn't asked for, meaning it didn't come from `astype` or `to_*`. Examples: int64 → float64 because of NaN, anything → object, and string-dtype changes in pandas 3.0.

### 7.4 Export as checks (P1)

A **"Copy as checks"** button generates guard code from the observed trace, ready to paste into the pipeline or a pytest file:

```python
df = orders.merge(users, on="user_id", how="left", validate="m:1")   # observed m:1
assert len(df) == len(orders), "left join changed row count"
assert df["country"].isna().sum() == 0                                # was 0 at this step
```

Optional targets are a **pandera** `DataFrameSchema` built from a node's profile and dframe-trace-style guards.

### 7.5 Lost-row examples (M6) and row-level lineage (later)

**Decision (D10):** ship *lost-row examples* first. Row-level lineage comes later, as a differentiator behind a toggle. Full lineage is ruled out.

**Lost-row examples.** Most of lineage's debugging value is answering "which rows did I lose or duplicate?". That can be answered at the operation that lost them, while its inputs are still alive, without tracking anything across steps. Each node keeps up to 5 example rows per category:

- **Filters, `dropna`, `drop_duplicates`, `.loc`/`.iloc`:** rows that were dropped. Uses the boolean mask when there is one, otherwise index alignment, which requires unique labels.
- **Joins:** left and right rows with no match, rows with duplicate keys (right side, or both sides for m:m) and rows with null keys.
- **Any step that introduces nulls:** rows where the column is newly null, for up to 3 columns per step.

Findings link to their examples (`Finding.example_kind`), so the UI can show the offending rows inline. The cost is O(rows) per affected operation and no work at all for unrelated steps.

**Row-level lineage (later).** Clicking a row in a node's sample would highlight the source rows that produced it, including every contributing row for aggregates.

- **Why it's hard:** pandas keeps no provenance, and a provenance column would change the user's data (`df.columns`, aggregations, `to_csv`). Lineage has to be a *side array per live frame* of source-row ids, propagated by a rule per operation:
  - trivial for column-only operations;
  - exact for masks and `concat`;
  - via index for `query`, `dropna`, sorts and `head`, which requires unique labels;
  - formula-based for `melt` and `explode`;
  - a key-only re-merge for `merge`, which roughly doubles its cost;
  - `gb.indices` for aggregates;
  - lineage stops at opaque operations (`groupby().apply`, custom `transform`).
- **Sampled lineage** still needs the side arrays for *every* row of every live frame while tracing, because upstream samples don't contain the rows downstream samples came from. Only what is saved is bounded: source ids and values for each sample row, capped for aggregates. Each node needs a confidence label (*exact* / *via index* / *unavailable*), and each operation needs property tests. Wrong lineage is worse than none.
- **Full lineage** is ruled out. The UI shows about 20 rows per node, so it would only pay off with a paginated data viewer, and it makes traces O(rows × nodes).

## 8. Frontend

**Layout**, modelled on the DataFusion visualizer:

```
┌─────────────────────────────────────────────────────────────┐
│ [Examples ▾] [Datasets ▾ + upload]            [▶ Run] [⟲]  │
├───────────────────┬─────────────────────────────────────────┤
│                   │   DAG canvas (top-down)                 │
│  Code editor      │   nodes coloured by category,           │
│  (CodeMirror)     │   badge = rows × cols, edge width ∝ rows│
│                   │                                         │
│  ─ legend ─       ├─────────────────────────────────────────┤
│                   │ Inspector: [Schema][Sample][Details]    │
│                   │            [Hints][Diff vs …]           │
└───────────────────┴─────────────────────────────────────────┘
```

- Clicking a node highlights its source line, and clicking a line selects its node.
- **Edge width scales with row count**, so drop-offs and explosions stand out at a glance, much like a Sankey diagram.
- History of recent runs in `localStorage`, like the DataFusion history dropdown.

### 8.1 Stack (D3 decided): Next.js + shadcn/ui

| Concern                 | Choice                                                                                                                                 |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| Framework               | **Next.js** (App Router, TypeScript)                                                                                             |
| UI components           | **shadcn/ui** (Radix + Tailwind)                                                                                                 |
| Graph canvas            | **React Flow** (`@xyflow/react`), with auto-layout from **elkjs** (or dagre)                                             |
| Code editor             | **CodeMirror 6** via `@uiw/react-codemirror` with Python highlighting. Lighter than Monaco                                     |
| Charts in the inspector | **shadcn charts** (Recharts) for the group-size histograms, selectivity bars and join match bars                                 |
| API types               | Generate TypeScript types from FastAPI's OpenAPI schema with`openapi-typescript`, so Pydantic models stay the single source of truth |
| Client state            | React state +`localStorage` for run history. No global store needed in v1                                                            |

**Where shadcn components fit in the layout:**

- `ResizablePanelGroup`: the editor, canvas and inspector split
- `Tabs`: the inspector tabs (Schema / Sample / Details / Hints / Diff)
- `Table`: schema and sample rows
- `Badge`: dtype chips, category tags and column in/out chips
- `Select` / `DropdownMenu`: the examples, datasets and history menus
- `Tooltip` / `HoverCard`: quick node previews on the canvas
- `Alert` / `Sonner`: hints and trace errors
- `Card`: the content of each custom React Flow node, so canvas nodes and the rest of the UI look the same

**How Next.js and FastAPI fit together.** The Next.js app is purely a frontend. All pandas work stays in FastAPI, and Next.js route handlers or server actions are not used for data.

| Mode                   | Setup                                                                                                                                                                        |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Dev**          | Run`next dev` on :3000 and `uvicorn` on :8000. A `rewrites()` rule in `next.config.ts` proxies `/api/*` to FastAPI, which avoids CORS                              |
| **Local "prod"** | Use`output: "export"` to build a static site that FastAPI serves through `StaticFiles`. Then one `uv run pandas-viz` command runs everything, with no Node at runtime  |
| **Hosted**       | The Next.js app goes on Vercel and FastAPI goes on a sandboxed host (D2). The Pyodide route in D2 also still works, because a static export can load Pyodide in a Web Worker |

Keeping the app compatible with static export means avoiding features that need a Node server: server components that fetch at request time, middleware and `next/image` optimization. For a client-heavy tool like this, that costs little.

**Repo layout:**

```
pandas-viz/
├── pyproject.toml, uv.lock
├── src/pandas_viz/        # FastAPI + tracer (§6.1)
├── tests/
└── web/                   # Next.js app
    ├── app/               # page.tsx (single-page tool), layout.tsx
    ├── components/ui/     # shadcn-generated
    ├── components/graph/  # React Flow nodes/edges per category
    ├── components/inspector/
    └── lib/api.ts         # typed client (generated types)
```

## 9. Security and limits

Runtime tracing executes arbitrary Python. The mitigations depend on deployment (**D2**):

- **Local-only (default):** bind to `127.0.0.1`, and run each trace in a **subprocess** with a timeout of about 10 seconds, `resource.setrlimit` memory caps and no inherited env secrets. This is adequate for a personal tool.
- **Hosted publicly:** subprocess isolation is not enough. Options are a container per request (for example Fly Machines or Modal), or running pandas **in the browser through Pyodide** (see D2) so no user code ever runs on the server.

**Profiling limits:** sample of at most 20 rows; `n_unique` only when the frame has fewer than 1 million rows (configurable); cap of 500 nodes per trace; long reprs truncated.

## 10. Milestones

| #                           | Scope                                                                                                                                        | Outcome                                                                   |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| **M0**                | Project layout (`src/`, `web/`), FastAPI skeleton, `/api/trace` stub, Next.js + shadcn init, dev proxy, OpenAPI type generation        | `uv run` + `next dev` show a page that calls the API                  |
| **M1**                | Tracer for about 15 core operations (read, filter, select, merge, groupby-agg, assign, sort), profiler, subprocess runner                    | JSON graph with shapes for the example pipeline                           |
| **M2**                | Frontend: editor, DAG, inspector (schema and sample), row-scaled edges                                                                       | End-to-end usable                                                         |
| **M3**                | Join inspector, groupby stats, filter selectivity, error-partial graphs,**Findings panel (row flow, null origin, dtype drift)**        | All P0 features done. This is the minimum release worth announcing        |
| **M4**                | **Entry points**: context manager, `pandas-viz run` CLI, Jupyter magic (§6.4)                                                       | Usable on real projects without pasting code                              |
| **M5**                | Node diff, dataset upload, examples, run history,**"Copy as checks"** (§7.4)                                                          | Parity with the reference tools, plus code to take back into the pipeline |
| **M6**                | **Lost-row examples** (§7.5), pushdown and anti-pattern hints (`lint.py`)                                                           | Deeper insight                                                            |
| **M7** *(optional)* | Sampled row-level lineage behind a toggle (§7.5), Polars adapter and a lazy Optimized-plan tab (D4), run-to-run diff, shareable HTML report | P2 features                                                               |

**Testing:** pytest golden tests. Each test runs a snippet and asserts on the graph structure (ops, edges, shapes). Examples double as fixtures.

## 11. Open decisions

| ID            | Decision                         | Options                                                                                                                                                            | Recommendation                                                                                                                                  |
| ------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| **D1**  | How to capture the pipeline      | A: static AST ·**B: runtime tracing** · C: hybrid                                                                                                          | **B** (§5)                                                                                                                               |
| **D2**  | Where pandas runs / deployment   | **Local FastAPI + subprocess** · hosted FastAPI + container sandbox · **Pyodide in the browser** (static site on Vercel; FastAPI only for local dev) | Local FastAPI first. The tracer is pure Python, so a Pyodide build stays possible later without a rewrite                                       |
| **D3**  | Frontend stack                   | —                                                                                                                                                                 | ✅**Decided:** Next.js + shadcn/ui + React Flow (§8.1)                                                                                   |
| **D9**  | How to ship the frontend locally | Static export served by FastAPI (one process) · separate`next start` server                                                                                     | Static export, which keeps D2's Pyodide and Vercel options open                                                                                 |
| **D4**  | Pushdown / optimized-plan story  | Hints only · + Polars lazy plan · + DuckDB`EXPLAIN` · + Ibis                                                                                                  | Hints only in v1. Add a Polars`LazyFrame` translation in M6 if still wanted (closest to the DataFusion experience)                            |
| **D5**  | Input format                     | Free-form code · method-chain only · also notebook`%%magic` / `.ipynb`                                                                                       | Free-form code,**plus the CLI, context manager and magic in M4**, since research shows developers won't paste code into a website (§2.3) |
| **D6**  | Graph granularity                | Every method call (including`groupby` → `agg` as two nodes) · collapse intermediate objects (GroupBy, `.str`, `.dt`) into the consuming op               | Collapse by default, with a "show all" toggle                                                                                                   |
| **D7**  | Data size target                 | Small (under 100k rows, full stats) · medium (up to 10M, sampled stats)                                                                                           | Small first. Make the profiler cap-aware from day one                                                                                           |
| **D8**  | Series support                   | DataFrames only · DataFrames and Series                                                                                                                           | Both, since Series are needed for boolean masks and column assignments to show up                                                               |
| **D10** | Row-level lineage (§7.5)        | Skip · lost-row examples · sampled lineage · full                                                                                                               | ✅**Decided:** lost-row examples in M6. Sampled lineage later (M7) behind a toggle, with confidence labels. No full lineage               |
| **D11** | Audience framing                 | Learning tool (compete with Pandas Tutor) ·**debugging tool for engineers** · both                                                                         | Debugging for engineers. Pandas Tutor already serves learners well, and the gap is on the professional side (§2.1)                             |
| **D12** | Relationship to dframe-trace     | Ignore · interoperate (import or export its traces) · treat as a competitor                                                                                      | Watch it. It is new and has no UI. If it gains traction, offer to import its traces as another entry point                                      |

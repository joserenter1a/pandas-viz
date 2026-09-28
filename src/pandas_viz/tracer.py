"""Runtime tracing of pandas operations.

While a ``Tracer`` is active, common pandas entry points are wrapped. Every
top-level call (calls made *inside* pandas are ignored via a depth counter)
that produces a DataFrame/Series becomes a ``Node``; its inputs become edges.
Objects are identified by ``id()``, guarded by weakref finalizers so reused ids
never alias. pandas 3.0 Copy-on-Write means nearly every op returns a new
object, which keeps this identity-based lineage clean; in-place mutations
(``df[c] = ...``, ``inplace=True``) become new "version" nodes of the object.
"""

import ast
from contextlib import contextmanager
import functools
import inspect
import linecache
import os
import sys
import time
import weakref
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pandas.core.groupby.generic import DataFrameGroupBy, SeriesGroupBy
from pandas.core.indexing import _LocationIndexer

from . import ops
from .checks import generate_checks, render_script
from .findings import compute_findings
from .lint import compute_hints
from .models import Edge, Node, SchemaChange, TraceResult
from .profiler import examples as profile_examples
from .profiler import profile

MAX_NODES = 500
LABEL_MAX = 90

_PANDAS_DIR = os.path.dirname(pd.__file__)
_THIS_DIR = os.path.dirname(__file__)

DATAFRAME_METHODS = [
    "merge", "join", "query", "dropna", "drop_duplicates", "head", "tail", "sample",
    "drop", "rename", "filter", "assign", "astype", "fillna", "sort_values", "sort_index",
    "nlargest", "nsmallest", "melt", "pivot", "pivot_table", "stack", "unstack", "explode",
    "set_index", "reset_index", "transpose", "apply", "map", "where", "mask", "replace",
    "value_counts", "describe", "copy", "convert_dtypes", "infer_objects", "agg", "aggregate",
    "groupby", "reindex", "isin", "select_dtypes", "rename_axis",
]
SERIES_METHODS = [
    "value_counts", "to_frame", "reset_index", "map", "apply", "astype", "fillna", "dropna",
    "sort_values", "head", "tail", "describe", "drop_duplicates", "replace", "explode",
    "groupby", "rename", "where", "mask", "nlargest", "nsmallest",
]
GROUPBY_METHODS = [
    "agg", "aggregate", "sum", "mean", "median", "min", "max", "count", "size", "nunique",
    "first", "last", "std", "var", "prod", "apply", "transform", "filter", "head", "tail",
    "describe", "cumsum", "cumcount", "rank", "value_counts", "idxmax", "idxmin",
]
PANDAS_FUNCTIONS = [
    "read_csv", "read_parquet", "read_json", "read_excel", "read_table", "read_feather",
    "read_sql", "read_pickle", "merge", "concat", "melt", "pivot_table", "crosstab",
    "get_dummies", "to_datetime", "to_numeric",
]

_ACTIVE: "Tracer | None" = None


@dataclass
class _GroupInfo:
    obj: Any  # strong ref keeps id() stable while pending
    parent: str
    keys: str
    selection: str = ""


@dataclass
class _PendingColumn:
    ref: weakref.ref
    parent: str
    key: Any
    site: "_Site"


@dataclass
class _Site:
    file: str | None = None
    line: int | None = None
    text: str | None = None


@dataclass
class Tracer:
    max_nodes: int = MAX_NODES
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self):
        self._depth = 0
        self._by_id: dict[int, str] = {}
        self._objects: dict[str, weakref.ref] = {}
        self._node_files: dict[str, str | None] = {}
        self._pending_cols: dict[int, _PendingColumn] = {}
        self._pending_gb: dict[int, _GroupInfo] = {}
        self._patches: list[tuple[Any, str, Any, bool]] = []

    # ------------------------------------------------------------------ install

    def __enter__(self) -> "Tracer":
        global _ACTIVE
        if _ACTIVE is not None:
            raise RuntimeError("another pandas_viz trace is already active")
        _ACTIVE = self
        for name in DATAFRAME_METHODS:
            self._patch(pd.DataFrame, name, "method")
        for name in SERIES_METHODS:
            self._patch(pd.Series, name, "method")
        for cls in (DataFrameGroupBy, SeriesGroupBy):
            for name in GROUPBY_METHODS:
                self._patch(cls, name, "groupby")
        self._patch(DataFrameGroupBy, "__getitem__", "groupby_select")
        self._patch(pd.DataFrame, "__getitem__", "getitem")
        self._patch(pd.DataFrame, "__setitem__", "setitem")
        self._patch(_LocationIndexer, "__getitem__", "loc_getitem")
        self._patch(_LocationIndexer, "__setitem__", "loc_setitem")
        for name in PANDAS_FUNCTIONS:
            self._patch(pd, name, "function")
        return self

    def __exit__(self, *exc):
        global _ACTIVE
        for owner, name, orig, owned in reversed(self._patches):
            if owned:
                setattr(owner, name, orig)
            else:
                delattr(owner, name)
        self._patches.clear()
        self._pending_gb.clear()
        _ACTIVE = None
        return False

    def _patch(self, owner, name: str, kind: str):
        if not hasattr(owner, name):
            return
        owned = name in vars(owner)
        orig = vars(owner)[name] if owned else getattr(owner, name)
        setattr(owner, name, _make_wrapper(orig, name, kind))
        self._patches.append((owner, name, orig, owned))

    # ------------------------------------------------------------------ results

    def result(self) -> TraceResult:
        findings = compute_findings(self.nodes, self.edges)
        checks = generate_checks(self.nodes, self.edges, findings)
        return TraceResult(
            nodes=self.nodes,
            edges=self.edges,
            findings=findings,
            hints=compute_hints(self.nodes, self.edges),
            checks=checks,
            checks_script=render_script(checks, len(self.nodes)),
            warnings=self.warnings,
        )

    def assign_var_names(self, code: str | None = None, filename: str | None = None):
        """Name the last node produced by each ``name = ...`` statement.

        With no arguments, every source file that produced a node is parsed (from linecache).
        """
        if code is None or filename is None:
            for file in {f for f in self._node_files.values() if f}:
                lines = linecache.getlines(file)
                if lines:
                    self.assign_var_names("".join(lines), file)
            return
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return
        for stmt in ast.walk(tree):
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                target = stmt.targets[0]
            elif isinstance(stmt, ast.AnnAssign):
                target = stmt.target
            else:
                continue
            if not isinstance(target, ast.Name):
                continue
            inside = [n for n in self.nodes
                      if self._node_files.get(n.id) == filename and n.source_line is not None
                      and stmt.lineno <= n.source_line <= (stmt.end_lineno or stmt.lineno)]
            if inside and inside[-1].var_name is None:
                inside[-1].var_name = target.id

    def source(self) -> tuple[str | None, str]:
        """(filename, text) of the file most nodes came from, for display next to the graph."""
        files = [f for f in self._node_files.values() if f]
        if not files:
            return None, ""
        main = max(set(files), key=files.count)
        return main, "".join(linecache.getlines(main))

    def open(self, title: str | None = None, port: int = 8000) -> str:
        """Save this trace and open it in the pandas-viz UI (starting the server if needed)."""
        from .server import open_trace

        filename, code = self.source()
        return open_trace(self.result(), code=code, title=title or filename or "trace", port=port)

    def name_from_namespace(self, namespace: dict):
        by_id = {n.id: n for n in self.nodes}
        for name, value in namespace.items():
            if name.startswith("_") or not isinstance(value, (pd.DataFrame, pd.Series)):
                continue
            node = by_id.get(self._by_id.get(id(value), ""))
            if node is not None and node.var_name is None:
                node.var_name = name

    # ------------------------------------------------------------------ lineage

    def _full(self) -> bool:
        if len(self.nodes) >= self.max_nodes:
            msg = f"node limit ({self.max_nodes}) reached; later operations were not recorded"
            if msg not in self.warnings:
                self.warnings.append(msg)
            return True
        return False

    def _lookup(self, obj) -> str | None:
        return self._by_id.get(id(obj))

    def _bind(self, obj, node_id: str):
        key = id(obj)
        self._by_id[key] = node_id
        self._objects[node_id] = weakref.ref(obj)
        self._pending_cols.pop(key, None)
        weakref.finalize(obj, self._forget, key, node_id)

    def _forget(self, key: int, node_id: str):
        if self._by_id.get(key) == node_id:
            del self._by_id[key]

    def node_for(self, obj, *, auto_source: bool = True) -> str | None:
        """Node id for ``obj``, materializing pending columns / untracked sources."""
        if (nid := self._lookup(obj)) is not None:
            return nid
        pending = self._pending_cols.get(id(obj))
        if pending is not None and pending.ref() is obj:
            return self._add_node(
                "column", obj, [(pending.parent, "input")], label=f"[{pending.key!r}]",
                site=pending.site, category="projection",
            )
        if auto_source and isinstance(obj, pd.DataFrame):
            return self._add_node(
                "DataFrame", obj, [], label="DataFrame", site=_Site(), category="source",
            )
        return None

    @contextmanager
    def paused(self):
        """Temporarily stop recording (for pandas calls made on the user's behalf)."""
        self._depth += 1
        try:
            yield
        finally:
            self._depth -= 1

    def register_source(self, obj, *, op: str, label: str, var_name: str | None = None,
                        details: dict | None = None) -> str | None:
        """Record a frame created outside the traced code (e.g. an uploaded dataset)."""
        node_id = self._add_node(op, obj, [], label=label, site=_Site(), category="source",
                                 details=details)
        if node_id is not None and var_name:
            self.nodes[-1].var_name = var_name
        return node_id

    def _add_node(self, op: str, out, parents: list[tuple[str, str]], *, label: str, site: "_Site",
                  category: str | None = None, args: dict | None = None, duration_ms: float = 0.0,
                  details: dict | None = None, examples: list | None = None) -> str | None:
        if self._full():
            return None
        node_id = f"n{len(self.nodes)}"
        with self.paused():  # profiling calls pandas; never record those calls
            prof = profile(out)
        parent_node = next((n for n in self.nodes if parents and n.id == parents[0][0]), None)
        rows_in = parent_node.profile.rows if parent_node else None
        change = _schema_change(parent_node.profile, prof) if parent_node else None
        examples = list(examples or [])
        if parent_node is not None:
            with self.paused():
                examples += _null_examples(out, parent_node.profile, prof)
        node = Node(
            id=node_id,
            op=op,
            category=category or ops.category(op, rows_in, prof.rows, change),
            label=_truncate(label),
            source_line=site.line,
            source_text=site.text,
            args=args or {},
            profile=prof,
            duration_ms=round(duration_ms, 3),
            rows_in=rows_in,
            schema_change=change,
            details=details or {},
            examples=examples,
        )
        self.nodes.append(node)
        self._node_files[node_id] = site.file
        for src, role in parents:
            self.edges.append(Edge(source=src, target=node_id, role=role))
        self._bind(out, node_id)
        return node_id

    # ------------------------------------------------------------------ dispatch

    def on_call(self, name: str, kind: str, orig, args, kwargs, result, duration_ms: float):
        handler = getattr(self, f"_on_{kind}")
        handler(name, orig, args, kwargs, result, duration_ms)

    def _on_function(self, name, orig, args, kwargs, result, duration_ms):
        if not isinstance(result, (pd.DataFrame, pd.Series)):
            return
        bound = _bind_args(orig, args, kwargs)
        parents: list[tuple[str, str]] = []
        examples: list = []
        if name == "merge":
            left, right = bound.get("left"), bound.get("right")
            parents = self._parents([(left, "left"), (right, "right")])
            details, examples = ops.merge_details(left, right, bound, result)
        elif name == "concat":
            objs = bound.get("objs") or []
            objs = list(objs.values()) if isinstance(objs, dict) else list(objs)
            parents = self._parents([(o, "input") for o in objs])
            details = ops.concat_details(objs, bound, result)
        else:
            frames = [v for v in bound.values() if isinstance(v, (pd.DataFrame, pd.Series))]
            parents = self._parents([(f, "input") for f in frames])
            if not parents and not name.startswith("read_"):
                return  # e.g. pd.to_numeric on an untracked array
            details = ops.source_details(name, bound) if name.startswith("read_") else {}
        category = "source" if name.startswith("read_") else None
        self._add_node(name, result, parents, label=_label(name, bound), site=_call_site(),
                       category=category, args=_summarize(bound), duration_ms=duration_ms,
                       examples=examples,
                       details=details)

    def _on_method(self, name, orig, args, kwargs, result, duration_ms):
        self_obj = args[0]
        if isinstance(self_obj, pd.Series) and self._lookup(self_obj) is None \
                and id(self_obj) not in self._pending_cols:
            return  # untracked Series (e.g. a boolean mask): too noisy to record
        if name == "groupby":
            parent = self.node_for(self_obj)
            if parent is not None:
                bound = _bind_args(orig, args, kwargs)
                keys = bound.get("by", bound.get("level"))
                self._pending_gb[id(result)] = _GroupInfo(result, parent, _short_repr(keys))
            return
        if result is None:  # inplace=True
            result, name = self_obj, f"{name} (inplace)"
        if not isinstance(result, (pd.DataFrame, pd.Series)):
            return
        bound = _bind_args(orig, args, kwargs)
        bound.pop("self", None)
        parents = self._parents([(self_obj, "left" if name in ("merge", "join") else "input")])
        details: dict = {}
        examples: list = []
        if name in ("merge", "join"):
            other = bound.get("right", bound.get("other"))
            if isinstance(other, (pd.DataFrame, pd.Series)):
                parents += self._parents([(other, "right")])
            if name == "merge":
                details, examples = ops.merge_details(self_obj, other, bound, result)
            else:
                details, examples = ops.join_details(self_obj, other, bound, result)
        elif name.split(" ")[0] in ops.ROW_FILTERS:
            details = ops.filter_details(len(self_obj), len(result))
            if name not in ops.LIMITS and result is not self_obj:
                examples = ops.dropped_examples(self_obj, result)
        self._add_node(name, result, parents, label=_label(name, bound), site=_call_site(),
                       args=_summarize(bound), duration_ms=duration_ms, details=details,
                       examples=examples)

    def _on_groupby(self, name, orig, args, kwargs, result, duration_ms):
        gb = args[0]
        if not isinstance(result, (pd.DataFrame, pd.Series)):
            return
        info = self._pending_gb.get(id(gb))
        if info is None or info.obj is not gb:
            parent = self.node_for(gb.obj)
            if parent is None:
                return
            info = _GroupInfo(gb, parent, "?")
        bound = _bind_args(orig, args, kwargs)
        bound.pop("self", None)
        label = f"groupby({info.keys}){info.selection}.{_label(name, bound)}"
        details = {"keys": info.keys, **ops.group_details(gb)}
        self._add_node(f"groupby.{name}", result, [(info.parent, "input")], label=label,
                       site=_call_site(), category="aggregate", args=_summarize(bound),
                       duration_ms=duration_ms, details=details)

    def _on_groupby_select(self, name, orig, args, kwargs, result, duration_ms):
        gb, key = args[0], args[1]
        info = self._pending_gb.get(id(gb))
        if info is not None and info.obj is gb:
            self._pending_gb[id(result)] = _GroupInfo(result, info.parent, info.keys,
                                                      f"{info.selection}[{key!r}]")

    def _on_getitem(self, name, orig, args, kwargs, result, duration_ms):
        df, key = args[0], args[1]
        if isinstance(result, pd.Series):
            parent = self.node_for(df)
            if parent is not None and _is_label(key):
                self._pending_cols[id(result)] = _PendingColumn(weakref.ref(result), parent, key,
                                                                _call_site())
            return
        if not isinstance(result, pd.DataFrame):
            return
        parents = self._parents([(df, "input")])
        if _is_label_list(key):
            op, details, examples = "select", {}, []
        else:
            op, details = "filter", ops.filter_details(len(df), len(result))
            examples = ops.dropped_examples(df, result, mask=key)
        site = _call_site()
        self._add_node(op, result, parents, label=_subscript_label(site, key), site=site,
                       duration_ms=duration_ms, details=details, examples=examples)

    def _on_setitem(self, name, orig, args, kwargs, result, duration_ms):
        df, key, value = args[0], args[1], args[2]
        self._record_mutation(df, f"[{_short_repr(key)}] = …", duration_ms, "assign column", value)

    def _on_loc_getitem(self, name, orig, args, kwargs, result, duration_ms):
        indexer, key = args[0], args[1]
        obj = indexer.obj
        if not isinstance(result, (pd.DataFrame, pd.Series)):
            return
        if isinstance(obj, pd.Series) and self._lookup(obj) is None:
            return
        which = "iloc" if type(indexer).__name__ == "_iLocIndexer" else "loc"
        parents = self._parents([(obj, "input")])
        site = _call_site()
        details = ops.filter_details(len(obj), len(result))
        examples = ops.dropped_examples(obj, result, mask=key) if len(result) < len(obj) else []
        self._add_node(which, result, parents, label=f".{which}[{_key_text(site, key)}]", site=site,
                       duration_ms=duration_ms, details=details, examples=examples)

    def _on_loc_setitem(self, name, orig, args, kwargs, result, duration_ms):
        indexer, key = args[0], args[1]
        which = "iloc" if type(indexer).__name__ == "_iLocIndexer" else "loc"
        self._record_mutation(indexer.obj, f".{which}[{_short_repr(key)}] = …", duration_ms,
                              f"{which} assign", args[2])

    def _record_mutation(self, obj, label, duration_ms, op, value=None):
        if not isinstance(obj, pd.DataFrame):
            return
        parents = self._parents([(obj, "input")])
        if isinstance(value, (pd.DataFrame, pd.Series)) and (vid := self._lookup(value)):
            parents.append((vid, "other"))  # e.g. df["x"] = pd.to_numeric(df["x"])
        self._add_node(op, obj, parents, label=label, site=_call_site(), category="mutate",
                       duration_ms=duration_ms)

    def _parents(self, objs: list[tuple[Any, str]]) -> list[tuple[str, str]]:
        out = []
        for obj, role in objs:
            if isinstance(obj, (pd.DataFrame, pd.Series)):
                nid = self.node_for(obj)
                if nid is not None:
                    out.append((nid, role))
        return out


def trace(max_nodes: int = MAX_NODES) -> Tracer:
    """Context manager: ``with pandas_viz.trace() as t: ...`` then ``t.result()``."""
    return Tracer(max_nodes=max_nodes)


# ---------------------------------------------------------------------- wrapper


def _make_wrapper(orig, name: str, kind: str):
    target = orig.__func__ if isinstance(orig, (staticmethod, classmethod)) else orig

    @functools.wraps(target)
    def wrapper(*args, **kwargs):
        __tracebackhide__ = True  # keep this frame out of IPython/pytest tracebacks
        tracer = _ACTIVE
        # Skip nested calls, and calls pandas makes internally (e.g. while rendering a repr).
        if tracer is None or tracer._depth or sys._getframe(1).f_code.co_filename.startswith(_PANDAS_DIR):
            return target(*args, **kwargs)
        tracer._depth += 1
        try:
            start = time.perf_counter()
            result = target(*args, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000
            try:
                tracer.on_call(name, kind, target, args, kwargs, result, duration_ms)
            except Exception as exc:  # never break the user's code because of us
                tracer.warnings.append(f"could not record {name}: {exc!r}")
            return result
        finally:
            tracer._depth -= 1

    if isinstance(orig, staticmethod):
        return staticmethod(wrapper)
    return wrapper


# ---------------------------------------------------------------------- helpers


MAX_NULL_EXAMPLE_COLUMNS = 3


def _null_examples(out, before, after) -> list:
    """Rows where a column became null at this step (up to 3 columns)."""
    prior = {c.name: c.null_count for c in before.columns}
    grew = [c.name for c in after.columns if c.null_count > prior.get(c.name, 0)]
    found = []
    for name in grew[:MAX_NULL_EXAMPLE_COLUMNS]:
        if isinstance(out, pd.Series):
            rows = out[out.isna()]
        else:
            matches = [c for c in out.columns if str(c) == name]
            if len(matches) != 1:
                continue
            rows = out[out[matches[0]].isna()]
        ex = profile_examples(rows, kind="nulls", label=f"Rows where '{name}' is null",
                              total=len(rows), column=name)
        if ex:
            found.append(ex)
    return found


def _schema_change(before, after) -> SchemaChange:
    b = {c.name: c.dtype for c in before.columns}
    a = {c.name: c.dtype for c in after.columns}
    return SchemaChange(
        added=[c for c in a if c not in b],
        removed=[c for c in b if c not in a],
        dtype_changed={c: (b[c], a[c]) for c in a if c in b and a[c] != b[c]},
    )


def _bind_args(func, args, kwargs) -> dict:
    try:
        return dict(inspect.signature(func).bind_partial(*args, **kwargs).arguments)
    except (TypeError, ValueError):
        return {f"arg{i}": a for i, a in enumerate(args)} | kwargs


def _short_repr(value, limit: int = 60) -> str:
    if isinstance(value, pd.DataFrame):
        return f"<DataFrame {value.shape[0]}×{value.shape[1]}>"
    if isinstance(value, pd.Series):
        return f"<Series {len(value)}>"
    if callable(value):
        return getattr(value, "__name__", "<callable>")
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _summarize(bound: dict) -> dict[str, str]:
    return {k: _short_repr(v) for k, v in bound.items() if k not in ("self", "kwargs")}


def _truncate(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= LABEL_MAX else text[: LABEL_MAX - 1] + "…"


def _label(name: str, bound: dict) -> str:
    """Prefer the user's own call text; fall back to name(args)."""
    site = _call_site()
    if site.text:
        call = _find_call(site.text, name.split(" ")[0])
        if call is not None:
            return call
    shown = [f"{k}={_short_repr(v, 30)}" for k, v in bound.items()
             if k not in ("self", "kwargs") and not isinstance(v, (pd.DataFrame, pd.Series))]
    return f"{name}({', '.join(shown)})"


def _find_call(text: str, name: str) -> str | None:
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError:
        return None
    node = tree.body
    while True:
        if isinstance(node, ast.Call):
            func = node.func
            fname = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if fname == name:
                parts = [ast.unparse(a) for a in node.args] + [ast.unparse(k) for k in node.keywords]
                return f"{name}({', '.join(parts)})"
            node = func.value if isinstance(func, ast.Attribute) else None
        elif isinstance(node, (ast.Attribute, ast.Subscript)):
            node = node.value
        else:
            return None


def _subscript_label(site: _Site, key) -> str:
    return f"[{_key_text(site, key)}]"


def _key_text(site: _Site, key) -> str:
    if site.text:
        try:
            node = ast.parse(site.text.strip(), mode="eval").body
            while isinstance(node, (ast.Call, ast.Attribute)):
                node = node.func if isinstance(node, ast.Call) else node.value
            if isinstance(node, ast.Subscript):
                if isinstance(node.slice, ast.Tuple):
                    return ", ".join(ast.unparse(e) for e in node.slice.elts)
                return ast.unparse(node.slice)
        except SyntaxError:
            pass
    return _short_repr(key)


def _is_label(key) -> bool:
    try:
        hash(key)
    except TypeError:
        return False
    return not isinstance(key, slice)


def _is_label_list(key) -> bool:
    if isinstance(key, (list, tuple, pd.Index)):
        return len(key) == 0 or not all(isinstance(k, bool) for k in key)
    return False


def _call_site() -> _Site:
    """The innermost frame that belongs to user code, with the exact call text."""
    frame = sys._getframe(1)
    while frame is not None:
        filename = frame.f_code.co_filename
        if not (filename.startswith(_PANDAS_DIR) or filename.startswith(_THIS_DIR)
                or filename.startswith("<frozen")):
            break
        frame = frame.f_back
    if frame is None:
        return _Site()
    filename = frame.f_code.co_filename
    pos = inspect.getframeinfo(frame, context=0).positions
    line = frame.f_lineno
    text = None
    if pos and pos.lineno is not None and pos.col_offset is not None:
        lines = linecache.getlines(filename)
        if pos.lineno <= len(lines):
            line = pos.lineno
            chunk = [ln.encode() for ln in lines[pos.lineno - 1: (pos.end_lineno or pos.lineno)]]
            if chunk:
                if len(chunk) == 1:
                    chunk[0] = chunk[0][pos.col_offset: pos.end_col_offset]
                else:
                    chunk[0] = chunk[0][pos.col_offset:]
                    chunk[-1] = chunk[-1][: pos.end_col_offset]
                text = b"".join(chunk).decode(errors="replace")
    return _Site(file=filename, line=line, text=text)

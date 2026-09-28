"""Pushdown and anti-pattern hints (design §4, M6).

pandas executes eagerly with no optimizer, so work that a query engine would push down
(filters before joins, column pruning at read time) is left to the author. This pass
looks at a finished trace and suggests rewrites that keep the result the same:

- ``filter_before_join``: a filter on one side's columns right after a join.
- ``filter_earlier``: a filter right after a sort or row-wise step it doesn't depend on.
- ``unused_columns``: columns read from a file that nothing downstream touches.
- ``useless_sort``: a sort whose order the next step throws away.
- ``row_apply``, ``duplicate_read``, ``inplace``: common anti-patterns.

Column references are recovered from each step's source text, so hints are conservative:
when a predicate's columns can't be determined, no pushdown is suggested.
"""

import ast
import re

from .models import Edge, Hint, Node

MIN_DROP = 0.10  # only suggest moving filters that drop at least 10% of rows
ROW_APPLY_MIN_MS = 50.0
ROW_APPLY_MIN_ROWS = 1_000

_ROW_WISE = {"apply", "map", "assign", "assign column", "astype", "fillna", "replace", "where",
             "mask", "copy", "convert_dtypes", "infer_objects"}
_SORTS = {"sort_values", "sort_index"}
_ORDER_INSENSITIVE_AGG = {"sum", "mean", "median", "min", "max", "count", "size", "nunique",
                          "std", "var", "prod", "describe", "value_counts"}
# ops that read every column of their input (so none of them is "unused")
_ALL_COLUMNS = {"describe", "apply", "map", "transpose", "stack", "melt", "value_counts",
                "drop_duplicates", "dropna", "fillna", "replace", "where", "mask", "astype",
                "to_frame", "concat", "pivot_table", "agg", "aggregate", "select_dtypes"}


def compute_hints(nodes: list[Node], edges: list[Edge]) -> list[Hint]:
    by_id = {n.id: n for n in nodes}
    parents: dict[str, list[tuple[Node, str]]] = {}
    children: dict[str, list[Node]] = {}
    for e in edges:
        if e.source in by_id and e.target in by_id:
            parents.setdefault(e.target, []).append((by_id[e.source], e.role))
            children.setdefault(e.source, []).append(by_id[e.target])

    def primary(n: Node) -> Node | None:
        return next((p for p, role in parents.get(n.id, []) if role in ("input", "left")), None)

    hints: list[Hint] = []
    for node in nodes:
        parent = primary(node)
        if node.category == "filter" and parent is not None:
            hints += _filter_hints(node, parent, parents.get(parent.id, []))
        if node.op in _SORTS:
            hints += _sort_hints(node, children.get(node.id, []))
        if node.op == "apply" and node.args.get("axis") in ("1", "'columns'") and \
                (node.duration_ms >= ROW_APPLY_MIN_MS or node.profile.rows >= ROW_APPLY_MIN_ROWS):
            hints.append(Hint(
                kind="row_apply", node_id=node.id,
                message=f"row-wise apply over {node.profile.rows:,} rows took {node.duration_ms:,.0f} ms; "
                        "a vectorized column expression is usually 10–100× faster",
                suggestion="# e.g. df.apply(lambda r: r.a + r.b, axis=1)  →  df['a'] + df['b']",
            ))
        if node.op.endswith("(inplace)"):
            hints.append(Hint(
                kind="inplace", node_id=node.id,
                message=f"{node.op.split(' ')[0]}(inplace=True) is discouraged by pandas and rarely "
                        "saves memory under Copy-on-Write; assign the result instead",
            ))
    hints += _unused_column_hints(nodes, parents, children)
    hints += _duplicate_reads(nodes)
    return hints


# ------------------------------------------------------------------------ filters


def _filter_hints(node: Node, parent: Node, grandparents: list[tuple[Node, str]]) -> list[Hint]:
    rows_in, rows_out = parent.profile.rows, node.profile.rows
    if not rows_in or (rows_in - rows_out) / rows_in < MIN_DROP:
        return []
    cols = predicate_columns(node, {c.name for c in parent.profile.columns})
    if not cols:
        return []
    kept = f"it keeps {rows_out:,} of {rows_in:,} rows"

    if parent.category == "join" and "how" in parent.details:
        how = parent.details["how"]
        sides = {role: p for p, role in grandparents if role in ("left", "right")}
        for side in ("left", "right"):
            src = sides.get(side)
            other = sides.get("right" if side == "left" else "left")
            if src is None:
                continue
            # pushing a filter into the non-preserved side of an outer join changes results
            if (how == "left" and side == "right") or (how == "right" and side == "left") \
                    or how in ("outer", "cross"):
                continue
            side_cols = {c.name for c in src.profile.columns}
            other_cols = {c.name for c in other.profile.columns} if other else set()
            keys = set(parent.details.get(f"{side}_on") or [])
            if cols <= side_cols and not (cols & other_cols - keys):
                target = src.var_name or f"the {side} input"
                return [Hint(
                    kind="filter_before_join", node_id=node.id, related=[parent.id, src.id],
                    message=f"this filter only uses {_names(cols)} from {target}; running it on "
                            f"{target} before the {parent.op} means the {parent.op} handles fewer "
                            f"rows ({kept})",
                    suggestion=_filter_on(node, src, parent),
                )]
        return []

    if parent.op in _SORTS or parent.op in _ROW_WISE:
        created = set()
        if parent.schema_change:
            created = set(parent.schema_change.added) | set(parent.schema_change.dtype_changed)
        if parent.op in _SORTS or not (cols & created):
            work = "sorting" if parent.op in _SORTS else f"{parent.op} on"
            return [Hint(
                kind="filter_earlier", node_id=node.id, related=[parent.id],
                message=f"move this filter before {parent.var_name or parent.op} "
                        f"(L{parent.source_line}): it doesn't depend on it, and {kept}, so "
                        f"{work} {rows_in - rows_out:,} rows is wasted work",
            )]
    return []


def predicate_columns(node: Node, available: set[str]) -> set[str]:
    """Columns a filter step reads, recovered from its source text (empty if unknown)."""
    names: set[str] = set()
    if node.op == "query":
        expr = _literal(node.args.get("expr"))
        if isinstance(expr, str):
            names |= set(re.findall(r"`([^`]+)`", expr))
            try:
                names |= {n.id for n in ast.walk(ast.parse(re.sub(r"`[^`]+`", "_", expr), mode="eval"))
                          if isinstance(n, ast.Name)}
            except SyntaxError:
                return set()
    elif node.op in ("dropna", "drop_duplicates"):
        subset = _literal(node.args.get("subset"))
        if subset is None:
            return set()  # all columns
        names |= {subset} if isinstance(subset, str) else set(subset)
    else:
        text = node.source_text or node.label
        try:
            tree = ast.parse(text.strip(), mode="eval")
        except SyntaxError:
            return set()
        names |= _referenced(tree)
    return names & available


def _referenced(tree: ast.AST) -> set[str]:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Subscript):
            s = n.slice
            if isinstance(s, ast.Constant) and isinstance(s.value, str):
                out.add(s.value)
            elif isinstance(s, (ast.List, ast.Tuple)):
                out |= {e.value for e in s.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.add(n.value)  # e.g. by="col", on="key"
    return out


def _filter_on(node: Node, src: Node, joined: Node) -> str | None:
    """The same filter, rewritten to run on the join input ``src``."""
    if not src.var_name:
        return None
    target = src.var_name
    if node.op == "query":
        return f"{target} = {target}.query({node.args.get('expr')})"
    if node.op in ("dropna", "drop_duplicates"):
        return f"{target} = {target}.{node.op}(subset={node.args.get('subset')})"
    try:
        tree = ast.parse((node.source_text or "").strip(), mode="eval")
    except SyntaxError:
        tree = None
    frame = _subscripted_name(tree.body) if tree else None
    if frame and (joined.var_name is None or frame == joined.var_name):
        class Rename(ast.NodeTransformer):
            def visit_Name(self, n):
                return ast.copy_location(ast.Name(id=target, ctx=n.ctx), n) if n.id == frame else n

        return f"{target} = {ast.unparse(Rename().visit(tree).body)}"
    return f"# apply {node.label} to {target} before the {joined.op}"


def _subscripted_name(expr: ast.AST) -> str | None:
    """``df`` for ``df[...]`` / ``df.loc[...]``, else None (e.g. a chained expression)."""
    if isinstance(expr, ast.Subscript):
        value = expr.value
        if isinstance(value, ast.Attribute) and value.attr in ("loc", "iloc"):
            value = value.value
        if isinstance(value, ast.Name):
            return value.id
    return None


# ------------------------------------------------------------------------ sorts


def _sort_hints(node: Node, kids: list[Node]) -> list[Hint]:
    if len(kids) != 1:
        return []  # the sorted frame is used more than once; its order may matter elsewhere
    kid = kids[0]
    method = kid.op.split(".", 1)[1] if kid.op.startswith("groupby.") else None
    if method in _ORDER_INSENSITIVE_AGG or (method in ("agg", "aggregate") and not _order_sensitive(kid)):
        return [Hint(
            kind="useless_sort", node_id=node.id, related=[kid.id],
            message=f"the next step ({kid.label}) aggregates without regard to order, so this "
                    f"sort of {node.profile.rows:,} rows has no effect on the result",
            suggestion="# remove the sort, or sort the aggregated result instead",
        )]
    if kid.op in _SORTS and kid.args.get("kind") not in ("'stable'", "'mergesort'"):
        return [Hint(
            kind="useless_sort", node_id=node.id, related=[kid.id],
            message=f"it is immediately re-sorted by {kid.label} (not a stable sort), which "
                    "discards this order; sort once by both keys instead",
        )]
    return []


def _order_sensitive(node: Node) -> bool:
    text = (node.source_text or node.label).lower()
    return any(k in text for k in ("first", "last", "lambda", "nth", "head", "tail", "cum"))


# ------------------------------------------------------------------------ columns


def _unused_column_hints(nodes: list[Node], parents: dict[str, list[tuple[Node, str]]],
                         children: dict[str, list[Node]]) -> list[Hint]:
    hints = []
    for src in nodes:
        if not (src.op.startswith("read_") or src.op == "dataset"):
            continue
        descendants = _descendants(src.id, children)
        if not descendants:
            continue
        source_cols = [c.name for c in src.profile.columns]
        used: set[str] = set()
        for n in descendants:
            present = {c.name for c in n.profile.columns}
            if not children.get(n.id):  # the pipeline's output keeps these
                used |= present
            base = n.op.split(" ")[0].split(".")[-1]
            text = n.source_text or n.label
            no_subset = n.op in ("dropna", "drop_duplicates") and "subset" not in n.args
            whole_frame_group = n.op.startswith("groupby.") and "[" not in n.label.split(").", 1)[-1]
            if (base in _ALL_COLUMNS and not n.op.startswith("groupby.")) or no_subset or whole_frame_group:
                used |= {c.name for p, _ in parents.get(n.id, []) for c in p.profile.columns}
            try:
                used |= _referenced(ast.parse(text.strip(), mode="eval"))
            except SyntaxError:
                used |= set(re.findall(r"\w+", text))
        unused = [c for c in source_cols if c not in used]
        if unused and len(unused) < len(source_cols):
            keep = [c for c in source_cols if c in used]
            param = "columns" if src.op in ("read_parquet", "read_feather") else "usecols"
            path = src.details.get("path") or src.details.get("filename")
            if src.op.startswith("read_") and path:
                call = f"pd.{src.op}({path!r}, {param}={keep!r})"
            elif src.op.startswith("read_"):
                call = f"pd.{src.op}(..., {param}={keep!r})"
            else:
                call = f"# read only {keep!r}"
            hints.append(Hint(
                kind="unused_columns", node_id=src.id,
                message=f"{len(unused)} of {len(source_cols)} columns read from "
                        f"{src.var_name or src.label} are never used ({_names(unused)}); "
                        f"skipping them at read time saves parsing and memory",
                suggestion=call,
            ))
    return hints


def _descendants(start: str, children: dict[str, list[Node]]) -> list[Node]:
    seen, stack, out = {start}, [start], []
    while stack:
        for kid in children.get(stack.pop(), []):
            if kid.id not in seen:
                seen.add(kid.id)
                out.append(kid)
                stack.append(kid.id)
    return out


def _duplicate_reads(nodes: list[Node]) -> list[Hint]:
    seen: dict[tuple[str, str], Node] = {}
    hints = []
    for n in nodes:
        path = n.details.get("path")
        if not n.op.startswith("read_") or not path:
            continue
        first = seen.setdefault((n.op, path), n)
        if first is not n:
            hints.append(Hint(
                kind="duplicate_read", node_id=n.id, related=[first.id],
                message=f"{path} is read again (first at L{first.source_line}); reuse "
                        f"{first.var_name or 'the first result'} or .copy() it instead",
            ))
    return hints


# ------------------------------------------------------------------------ helpers


def _literal(text: str | None):
    if text is None:
        return None
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None


def _names(cols) -> str:
    cols = sorted(cols)
    shown = ", ".join(f"'{c}'" for c in cols[:4])
    return shown + (f" +{len(cols) - 4} more" if len(cols) > 4 else "")

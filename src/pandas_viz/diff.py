"""Compare any two steps of a trace (design §7.2).

Works on profiles only, so it is available for saved traces and costs nothing extra
at trace time. A row-level diff would need the frames themselves, which traces don't keep.
"""

from collections import deque

from .models import ColumnDiff, ColumnInfo, NodeDiff, PathStep, TraceResult


def diff_nodes(trace: TraceResult, a_id: str, b_id: str) -> NodeDiff:
    nodes = {n.id: n for n in trace.nodes}
    a, b = nodes[a_id], nodes[b_id]

    if a_id == b_id:
        relation, path_ids = "same", [a_id]
    elif (path_ids := _path(trace, a_id, b_id)) is not None:
        relation = "ancestor"
    elif (path_ids := _path(trace, b_id, a_id)) is not None:
        relation = "descendant"
    else:
        relation, path_ids = "unrelated", []

    return NodeDiff(
        a=a_id,
        b=b_id,
        relation=relation,
        path=[PathStep(node_id=n.id, op=n.op, label=n.label, var_name=n.var_name, rows=n.profile.rows)
              for n in (nodes[i] for i in path_ids)],
        rows_a=a.profile.rows,
        rows_b=b.profile.rows,
        cols_a=a.profile.cols,
        cols_b=b.profile.cols,
        memory_a=a.profile.memory_bytes,
        memory_b=b.profile.memory_bytes,
        index_a=a.profile.index,
        index_b=b.profile.index,
        columns=diff_columns(a.profile.columns, b.profile.columns),
    )


def diff_columns(a_cols: list[ColumnInfo], b_cols: list[ColumnInfo]) -> list[ColumnDiff]:
    a_by, b_by = {c.name: c for c in a_cols}, {c.name: c for c in b_cols}
    removed = [c for c in a_cols if c.name not in b_by]
    added = [c for c in b_cols if c.name not in a_by]

    # A removed and an added column with identical stats is most likely a rename.
    renamed: dict[str, str] = {}
    for old in removed:
        matches = [new for new in added if new.name not in renamed.values() and _same_stats(old, new)]
        if len(matches) == 1:
            renamed[old.name] = matches[0].name
    renamed_to = {new: old for old, new in renamed.items()}

    out: list[ColumnDiff] = []
    for c in b_cols:  # output order follows the later frame
        if c.name in a_by:
            o = a_by[c.name]
            changed = o.dtype != c.dtype or o.null_count != c.null_count  # unique counts shift with any filter
            out.append(_col(c.name, "changed" if changed else "same", o, c))
        elif c.name in renamed_to:
            out.append(_col(c.name, "renamed", a_by[renamed_to[c.name]], c, renamed_to[c.name]))
        else:
            out.append(_col(c.name, "added", None, c))
    out += [_col(c.name, "removed", c, None) for c in removed if c.name not in renamed]
    return out


def _same_stats(a: ColumnInfo, b: ColumnInfo) -> bool:
    return a.dtype == b.dtype and a.null_count == b.null_count and a.n_unique == b.n_unique


def _col(name, status, a: ColumnInfo | None, b: ColumnInfo | None, renamed_from=None) -> ColumnDiff:
    return ColumnDiff(
        name=name, status=status, renamed_from=renamed_from,
        dtype_a=a.dtype if a else None, dtype_b=b.dtype if b else None,
        nulls_a=a.null_count if a else None, nulls_b=b.null_count if b else None,
        unique_a=a.n_unique if a else None, unique_b=b.n_unique if b else None,
    )


def _path(trace: TraceResult, start: str, goal: str) -> list[str] | None:
    """Shortest path along edges from ``start`` to ``goal``, or None."""
    children: dict[str, list[str]] = {}
    for e in trace.edges:
        children.setdefault(e.source, []).append(e.target)
    prev: dict[str, str | None] = {start: None}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        if cur == goal:
            path = []
            while cur is not None:
                path.append(cur)
                cur = prev[cur]
            return path[::-1]
        for nxt in children.get(cur, []):
            if nxt not in prev:
                prev[nxt] = cur
                queue.append(nxt)
    return None


def format_diff(d: NodeDiff) -> str:
    """Plain-text rendering for the CLI."""
    def delta(x, y):
        return f"{x:,} → {y:,}" + (f" ({y - x:+,})" if y != x else "")

    lines = [f"diff {d.a} → {d.b} ({d.relation})",
             f"  rows    {delta(d.rows_a, d.rows_b)}",
             f"  columns {delta(d.cols_a, d.cols_b)}"]
    if d.path:
        lines.append("  path    " + " → ".join(f"{s.var_name or s.op} [{s.rows:,}]" for s in d.path))
    marks = {"added": "+", "removed": "-", "renamed": "~", "changed": "*", "same": " "}
    for c in d.columns:
        if c.status == "same":
            continue
        detail = []
        if c.status == "renamed":
            detail.append(f"renamed from {c.renamed_from}")
        if c.dtype_a and c.dtype_b and c.dtype_a != c.dtype_b:
            detail.append(f"dtype {c.dtype_a} → {c.dtype_b}")
        if c.nulls_a is not None and c.nulls_b is not None and c.nulls_a != c.nulls_b:
            detail.append(f"nulls {c.nulls_a:,} → {c.nulls_b:,}")
        if c.status in ("added", "removed"):
            detail.append(c.dtype_b or c.dtype_a or "")
        lines.append(f"  {marks[c.status]} {c.name}  {'; '.join(detail)}")
    return "\n".join(lines)

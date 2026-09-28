"""Pipeline-wide diagnostics: row loss/explosion, null origins, dtype drift, join problems."""

from .models import Edge, Finding, Node
from .ops import DTYPE_OPS


def compute_findings(nodes: list[Node], edges: list[Edge]) -> list[Finding]:
    by_id = {n.id: n for n in nodes}
    primary: dict[str, Node] = {}
    for e in edges:
        if e.role in ("input", "left") and e.target not in primary and e.source in by_id:
            primary[e.target] = by_id[e.source]

    findings: list[Finding] = []
    null_seen: set[str] = set()
    for node in nodes:
        parent = primary.get(node.id)
        findings += _join_findings(node)
        if parent is None:
            continue
        rows_in, rows_out = parent.profile.rows, node.profile.rows
        if rows_in and rows_out == 0:
            findings.append(Finding(kind="row_loss", severity="error", node_id=node.id,
                                    message=f"{node.op} produced 0 rows (from {rows_in:,})",
                                    example_kind=_has(node, "dropped")))
        elif node.category in ("filter", "limit") and rows_out < rows_in:
            pct = 100 * (rows_in - rows_out) / rows_in
            findings.append(Finding(kind="row_loss", severity="warning" if pct >= 50 else "info",
                                    node_id=node.id,
                                    message=f"{node.op} dropped {rows_in - rows_out:,} rows ({pct:.1f}%)",
                                    example_kind=_has(node, "dropped")))

        parent_nulls = {c.name: c.null_count for c in parent.profile.columns}
        # melt/stack etc. move values between columns: only flag them if total nulls grew
        moved_only = node.category == "reshape" and (
            sum(c.null_count for c in node.profile.columns) <= sum(parent_nulls.values()))
        for col in ([] if moved_only else node.profile.columns):
            if col.name in null_seen or col.null_count == 0:
                continue
            before = parent_nulls.get(col.name)
            if before is None and node.op == "concat":
                msg = f"{col.null_count:,} nulls in '{col.name}': not every concat input has this column"
            elif before is None and node.category == "join":
                msg = f"{col.null_count:,} nulls in '{col.name}' after {node.op} (unmatched keys or nulls on the other side)"
            elif before is None:
                msg = f"new column '{col.name}' has {col.null_count:,} nulls"
            elif col.null_count > before:
                msg = f"nulls in '{col.name}' rose {before:,} → {col.null_count:,}"
            else:
                continue
            null_seen.add(col.name)
            findings.append(Finding(kind="null_origin", severity="warning", node_id=node.id,
                                    column=col.name, message=msg,
                                    example_kind=_has(node, "nulls", col.name)))

        if node.schema_change and node.op not in DTYPE_OPS:
            for col, (old, new) in node.schema_change.dtype_changed.items():
                findings.append(Finding(kind="dtype_drift", severity="warning", node_id=node.id,
                                        column=col, example_kind=_has(node, "nulls", col),
                                        message=f"'{col}' changed {old} → {new} without an explicit cast"))
    return findings


def _join_findings(node: Node) -> list[Finding]:
    d = node.details
    if node.category != "join" or "how" not in d:
        return []
    out: list[Finding] = []

    def add(severity, message, kind="join", example=None):
        out.append(Finding(kind=kind, severity=severity, node_id=node.id, message=message,
                           example_kind=example))

    dup = _has(node, "duplicate_keys_right") or _has(node, "duplicate_keys_left")

    how, card = d.get("how"), d.get("cardinality")
    if card == "m:m":
        add("error", f"many-to-many {node.op}: duplicate keys on both sides "
                     f"({d.get('left_duplicate_keys', 0):,} left, {d.get('right_duplicate_keys', 0):,} right)",
            example=dup)
    factor = d.get("explosion_factor")
    if factor and factor > 1 and how in ("left", "inner"):
        add("warning", f"{how} {node.op} grew rows ×{factor:.2f} "
                       f"({d['rows_left']:,} → {d['rows_out']:,})", kind="row_explosion", example=dup)
    if d.get("left_only_rows") and how == "inner":
        add("warning", f"inner {node.op} dropped {d['left_only_rows']:,} left rows with no match",
            kind="row_loss", example=_has(node, "unmatched_left"))
    elif d.get("left_only_rows") and how == "left":
        add("info", f"{d['left_only_rows']:,} left rows had no match in the right side",
            example=_has(node, "unmatched_left"))
    for m in d.get("key_dtype_mismatches", []):
        add("warning", f"key dtype mismatch: {m['left']} ({m['left_dtype']}) vs "
                       f"{m['right']} ({m['right_dtype']})")
    if d.get("suffix_collisions"):
        add("info", f"overlapping columns got suffixes: {', '.join(d['suffix_collisions'])}")
    if d.get("left_null_keys") or d.get("right_null_keys"):
        add("warning", f"null join keys: {d.get('left_null_keys', 0):,} left, "
                       f"{d.get('right_null_keys', 0):,} right (pandas matches null to null)",
            example=_has(node, "null_keys_left") or _has(node, "null_keys_right"))
    return out


def _has(node: Node, kind: str, column: str | None = None) -> str | None:
    """``kind`` if the node kept example rows of that kind (for that column), else None."""
    for ex in node.examples:
        if ex.kind == kind and (column is None or ex.column == column):
            return kind
    return None

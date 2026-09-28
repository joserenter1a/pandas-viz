"""Turn a trace into code that guards the pipeline: "Copy as checks".

Each Check is either an *edit* (add ``validate=`` to a merge call on a line) or an
*assert* to insert after a line. ``passes`` says whether it holds on the traced data:
passing checks lock in current behaviour; failing ones would have caught a finding.
"""

import json
from datetime import date

from .models import Check, Edge, Finding, Node

MAX_SCHEMA_COLUMNS = 40


def _q(value) -> str:
    """Python literal for a column name/string, preferring double quotes."""
    return json.dumps(value) if isinstance(value, str) else repr(value)


def _col(var: str, col: str) -> str:
    return f"{var}[{_q(col)}]"


def generate_checks(nodes: list[Node], edges: list[Edge], findings: list[Finding]) -> list[Check]:
    by_id = {n.id: n for n in nodes}
    parents: dict[str, dict[str, Node]] = {}
    has_children: set[str] = set()
    for e in edges:
        if e.source in by_id:
            parents.setdefault(e.target, {}).setdefault(e.role, by_id[e.source])
            has_children.add(e.source)

    checks: list[Check] = []
    for node in nodes:
        node_parents = parents.get(node.id, {})
        if node.category == "join" and "cardinality" in node.details:
            checks += _join_checks(node, node_parents.get("left") or node_parents.get("input"),
                                   node_parents.get("right"))
        elif node.category in ("filter", "limit") and node.var_name and node.profile.kind == "DataFrame":
            checks.append(Check(
                node_id=node.id, kind="not_empty", line=node.source_line, position="after",
                code=f'assert not {node.var_name}.empty, "{node.var_name} is empty"',
                passes=node.profile.rows > 0,
                reason=f"{node.op} kept {node.profile.rows:,} of {node.rows_in or 0:,} rows",
            ))

    for f in findings:
        node = by_id.get(f.node_id)
        if node is None or not node.var_name or not f.column or node.profile.kind != "DataFrame":
            continue
        var = node.var_name
        if f.kind == "dtype_drift" and node.schema_change and f.column in node.schema_change.dtype_changed:
            before = node.schema_change.dtype_changed[f.column][0]
            checks.append(Check(
                node_id=node.id, kind="dtype", line=node.source_line, position="after",
                code=f'assert {_col(var, f.column)}.dtype == {_q(before)}, '
                     f'"{f.column} is no longer {before}"',
                passes=False, reason=f.message,
            ))
        elif f.kind == "null_origin":
            checks.append(Check(
                node_id=node.id, kind="not_null", line=node.source_line, position="after",
                code=f'assert {_col(var, f.column)}.notna().all(), "nulls in {f.column}"',
                passes=False, reason=f.message,
            ))

    for node in nodes:  # lock in the schema of each named output of the pipeline
        if node.id in has_children or not node.var_name or node.profile.cols > MAX_SCHEMA_COLUMNS:
            continue
        var = node.var_name
        if node.profile.kind == "DataFrame":
            dtypes = "{" + ", ".join(f"{_q(c.name)}: {_q(c.dtype)}" for c in node.profile.columns) + "}"
            code = f'assert {var}.dtypes.astype(str).to_dict() == {dtypes}, "{var} schema changed"'
        else:
            code = f'assert str({var}.dtype) == {_q(node.profile.columns[0].dtype)}, "{var} dtype changed"'
        checks.append(Check(node_id=node.id, kind="schema", line=node.source_line, position="after",
                            code=code, passes=True, reason=f"output schema of {var}"))

    for node in nodes:
        if node.var_name and node.profile.kind == "DataFrame" and node.profile.cols <= MAX_SCHEMA_COLUMNS:
            checks.append(Check(node_id=node.id, kind="pandera", line=node.source_line,
                                position="after", code=pandera_schema(node), passes=True,
                                reason=f"pandera schema observed at {node.var_name}"))

    order = {n.id: i for i, n in enumerate(nodes)}
    checks.sort(key=lambda c: (order[c.node_id], c.position != "before", c.position != "replace"))
    return checks


def _join_checks(node: Node, left: Node | None, right: Node | None) -> list[Check]:
    d = node.details
    how = d.get("how")
    out: list[Check] = []

    if node.op == "merge" and "validate" not in node.args and node.source_text \
            and d.get("suggested_validate"):
        validate, passes = d["suggested_validate"], d["validate_passes"]
        right_name = right.var_name if right and right.var_name else "the right side"
        if passes and validate == "m:1":
            reason = f"{right_name} has unique keys: lock that in"
        elif passes:
            reason = "left keys are unique: lock that in"
        else:
            reason = (f"{right_name} has {d.get('right_duplicate_keys', 0):,} duplicate key(s), "
                      f"so the merge multiplies rows; deduplicate it first")
        edited = _add_kwarg(node.source_text, f'validate="{validate}"')
        if edited:
            out.append(Check(node_id=node.id, kind="merge_validate", line=node.source_line,
                             position="replace", code=edited, passes=passes, reason=reason))

    for side, frame, cols, nulls in (
        ("left", left, d.get("left_on") or [], d.get("left_null_keys")),
        ("right", right, d.get("right_on") or [], d.get("right_null_keys")),
    ):
        if frame and frame.var_name and cols and "(index)" not in cols and nulls == 0:
            keys = f"{frame.var_name}[{_q(cols[0])}]" if len(cols) == 1 else \
                f"{frame.var_name}[[{', '.join(map(_q, cols))}]]"
            test = f"{keys}.notna().all()" + ("" if len(cols) == 1 else ".all()")
            out.append(Check(node_id=node.id, kind="not_null", line=node.source_line,
                             position="before", code=f'assert {test}, "null join keys in {frame.var_name}"',
                             passes=True, reason=f"{side} join keys have no nulls (pandas matches null to null)"))

    if how == "left" and node.var_name and left and left.var_name:
        passes = d.get("rows_out") == d.get("rows_left")
        out.append(Check(
            node_id=node.id, kind="row_count", line=node.source_line, position="after",
            code=f'assert len({node.var_name}) == len({left.var_name}), '
                 f'"left merge changed the row count"',
            passes=passes,
            reason="a left join should keep one row per left row" if passes else
                   f"rows went {d.get('rows_left', 0):,} → {d.get('rows_out', 0):,}",
        ))
    elif how == "inner" and node.var_name:
        out.append(Check(node_id=node.id, kind="not_empty", line=node.source_line, position="after",
                         code=f'assert not {node.var_name}.empty, "inner merge matched nothing"',
                         passes=node.profile.rows > 0, reason="inner merge must match something"))
    return out


def _add_kwarg(call: str, kwarg: str) -> str | None:
    """Insert ``kwarg`` before the final ``)`` of a call expression, keeping formatting."""
    text = call.rstrip()
    if not text.endswith(")"):
        return None
    body = text[:-1].rstrip()
    if body.endswith(","):
        body = body[:-1].rstrip()
    sep = "" if body.endswith("(") else ", "
    return f"{body}{sep}{kwarg})"


def pandera_schema(node: Node) -> str:
    var = node.var_name or "df"
    rows = node.profile.rows
    lines = ["import pandera.pandas as pa", "", f"{var}_schema = pa.DataFrameSchema({{"]
    for c in node.profile.columns:
        opts = [_q(c.dtype), f"nullable={c.null_count > 0}"]
        if rows > 1 and c.n_unique == rows and c.null_count == 0:
            opts.append("unique=True")
        lines.append(f"    {_q(c.name)}: pa.Column({', '.join(opts)}),")
    lines += ["})", f"{var}_schema.validate({var})"]
    return "\n".join(lines)


def render_script(checks: list[Check], n_steps: int) -> str:
    """All non-pandera checks as a paste-ready, commented block."""
    usable = [c for c in checks if c.kind != "pandera"]
    if not usable:
        return ""
    out = [
        f"# pandas-viz checks · {date.today().isoformat()} · traced {n_steps} steps",
        "# ✓ holds on the traced data (locks in current behaviour)",
        "# ✗ fails on the traced data (would have caught a finding): fix the data, or drop it",
    ]
    last = None
    for c in usable:
        where = {"before": "before", "after": "after", "replace": "edit"}[c.position]
        header = (c.line, c.position)
        if header != last:
            out.append("")
            out.append(f"# {where} line {c.line}:" if c.line else f"# {where}:")
            last = header
        mark = "✓" if c.passes else "✗"
        out.append(f"{c.code}  # {mark} {c.reason}")
    return "\n".join(out) + "\n"

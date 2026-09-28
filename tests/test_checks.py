import ast
import textwrap
from collections import defaultdict

import pandas as pd
import pytest

from pandas_viz import run_code
from pandas_viz.checks import _add_kwarg
from pandas_viz.examples import EXAMPLES


def execute_checks(code: str, checks) -> dict[int, bool]:
    """Insert every check at its line in ``code``, run it, and report which ones held."""
    span = {}  # line -> (first, last) line of the top-level statement containing it
    for stmt in ast.parse(code).body:
        for ln in range(stmt.lineno, stmt.end_lineno + 1):
            span[ln] = (stmt.lineno, stmt.end_lineno)
    before, after = defaultdict(list), defaultdict(list)
    for i, c in enumerate(checks):
        if c.kind == "pandera":
            continue
        if c.position == "replace":  # an edited merge call: evaluate it just before the line
            body = f"_ = {' '.join(c.code.split())}"
            errors = "(AssertionError, pd.errors.MergeError)"
        else:
            body, errors = c.code, "AssertionError"
        probe = ["try:", f"    {body}", f"    _held[{i}] = True",
                 f"except {errors}:", f"    _held[{i}] = False"]
        first, last = span[c.line]
        if c.position == "after":
            after[last] += probe
        else:
            before[first] += probe
    out = []
    for n, line in enumerate(code.splitlines(), start=1):
        out += before[n] + [line] + after[n]
    ns = {"pd": pd, "_held": {}}
    exec("\n".join(out), ns)
    return ns["_held"]


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda e: e.id)
def test_checks_hold_or_fail_exactly_as_marked(example):
    result = run_code(example.code)
    held = execute_checks(example.code, result.checks)
    checks = [c for c in result.checks if c.kind != "pandera"]
    assert checks
    assert len(held) == len(checks)
    for i, c in enumerate(result.checks):
        if c.kind != "pandera":
            assert held[i] == c.passes, f"{c.code} expected passes={c.passes}"


def test_revenue_checks():
    result = run_code(EXAMPLES[0].code)
    kinds = {c.kind: c for c in result.checks}
    validate = kinds["merge_validate"]
    assert validate.code == 'paid.merge(users, on="user_id", how="left", validate="m:1")'
    assert validate.passes is False and "duplicate" in validate.reason
    assert kinds["row_count"].code.startswith("assert len(enriched) == len(paid)")
    assert "# edit line 15:" in result.checks_script
    assert "✗" in result.checks_script and "✓" in result.checks_script


def test_passing_merge_suggests_m1():
    code = textwrap.dedent("""
        orders = pd.DataFrame({"uid": [1, 1, 2]})
        users = pd.DataFrame({"uid": [1, 2], "name": ["a", "b"]})
        out = orders.merge(
            users,
            on="uid",
        )
    """)
    result = run_code(code)
    validate = next(c for c in result.checks if c.kind == "merge_validate")
    assert validate.passes
    assert validate.code.endswith('on="uid", validate="m:1")')
    assert all(c.passes for c in result.checks)
    held = execute_checks(code, result.checks)
    assert all(held.values())


def test_existing_validate_is_respected():
    code = 'a = pd.DataFrame({"k": [1]})\nb = a.merge(a, on="k", validate="1:1")\n'
    assert not [c for c in run_code(code).checks if c.kind == "merge_validate"]


def test_pandera_schema_validates_its_own_data():
    pa = pytest.importorskip("pandera.pandas")
    code = 'df = pd.DataFrame({"id": [1, 2], "name": ["a", None], "x": [1.5, 2.5]})\nout = df.head(2)\n'
    result = run_code(code)
    schema_code = next(c.code for c in result.checks if c.kind == "pandera" and "out_schema" in c.code)
    assert '"name": pa.Column("str", nullable=True)' in schema_code
    assert '"id": pa.Column("int64", nullable=False, unique=True)' in schema_code
    ns = {"pd": pd}
    exec(code + schema_code, ns)  # validate() raises if the schema doesn't match
    assert pa  # imported


@pytest.mark.parametrize("call, expected", [
    ("a.merge(b)", "a.merge(b, validate=\"m:1\")"),
    ("a.merge()", "a.merge(validate=\"m:1\")"),
    ("a.merge(b,\n    on='k',\n)", "a.merge(b,\n    on='k', validate=\"m:1\")"),
    ("a.merge(b", None),
])
def test_add_kwarg(call, expected):
    assert _add_kwarg(call, 'validate="m:1"') == expected

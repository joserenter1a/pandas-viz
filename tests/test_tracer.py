import pandas as pd
import pytest

from pandas_viz import run_code, trace
from pandas_viz.examples import EXAMPLES


def ops(result):
    return [n.op for n in result.nodes]


def node(result, op):
    return next(n for n in result.nodes if n.op == op)


def kinds(result, kind):
    return [f for f in result.findings if f.kind == kind]


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda e: e.id)
def test_examples_run_cleanly(example):
    result = run_code(example.code)
    assert result.error is None
    assert result.warnings == []
    assert result.nodes


def test_revenue_pipeline_graph_and_join_stats():
    result = run_code(EXAMPLES[0].code)
    assert ops(result) == ["DataFrame", "filter", "DataFrame", "merge", "groupby.agg", "sort_values"]
    merge = node(result, "merge")
    assert merge.var_name == "enriched"
    assert merge.category == "join"
    assert merge.details["cardinality"] == "1:m"
    assert (merge.details["suggested_validate"], merge.details["validate_passes"]) == ("m:1", False)
    assert merge.details["left_only_rows"] == 3  # users 7, 8, 9
    assert merge.details["rows_out"] == 10  # user 4 duplicated
    roles = {(e.source, e.role) for e in result.edges if e.target == merge.id}
    assert {r for _, r in roles} == {"left", "right"}
    assert kinds(result, "row_explosion")
    agg = node(result, "groupby.agg")
    assert agg.label.startswith("groupby('country').agg(")
    assert agg.details["n_groups"] == 4


def test_filter_label_uses_source_text():
    result = run_code('df = pd.DataFrame({"a": [1, 2, 3]})\nsmall = df[df["a"] < 3]\n')
    f = node(result, "filter")
    assert f.label == "[df['a'] < 3]"
    assert f.source_line == 2
    assert f.details == {"rows_in": 3, "rows_out": 2, "rows_dropped": 1, "pct_kept": 66.67}
    # the mask column access must not show up as a node
    assert ops(result) == ["DataFrame", "filter"]


def test_many_to_many_join_is_an_error():
    code = """
a = pd.DataFrame({"k": [1, 1, 2]})
b = pd.DataFrame({"k": [1, 1, 3], "v": [1, 2, 3]})
m = a.merge(b, on="k")
"""
    result = run_code(code)
    merge = node(result, "merge")
    assert merge.details["cardinality"] == "m:m"
    assert (merge.details["suggested_validate"], merge.details["validate_passes"]) == ("m:1", False)
    assert any(f.severity == "error" and "many-to-many" in f.message for f in result.findings)
    assert any("inner merge dropped 1 left rows" in f.message for f in result.findings)


def test_key_dtype_mismatch_and_suffixes():
    code = """
a = pd.DataFrame({"k": [1, 2], "v": [1, 2]})
b = pd.DataFrame({"k": [1.0, 2.0], "v": [3, 4]})
m = pd.merge(a, b, on="k")
"""
    merge = node(run_code(code), "merge")
    assert merge.details["key_dtype_mismatches"][0]["right_dtype"] == "float64"
    assert merge.details["suffix_collisions"] == ["v_x", "v_y"]


def test_dtype_drift_and_null_origin():
    result = run_code(EXAMPLES[1].code)
    drift = kinds(result, "dtype_drift")
    assert [(d.column, node_op(result, d.node_id)) for d in drift] == [("reading", "reindex")]
    origins = kinds(result, "null_origin")
    assert origins[0].column == "reading"
    # the explicit astype at the end is not drift
    assert all(node_op(result, d.node_id) != "astype" for d in drift)


def node_op(result, node_id):
    return next(n.op for n in result.nodes if n.id == node_id)


def test_setitem_links_value_and_versions_frame():
    code = """
df = pd.DataFrame({"x": ["1", "2", "x"]})
df["x"] = pd.to_numeric(df["x"], errors="coerce")
out = df.dropna()
"""
    result = run_code(code)
    assert ops(result) == ["DataFrame", "column", "to_numeric", "assign column", "dropna"]
    assign = node(result, "assign column")
    sources = {e.source: e.role for e in result.edges if e.target == assign.id}
    assert sorted(sources.values()) == ["input", "other"]
    # dropna hangs off the mutated version, not the original
    dropna = node(result, "dropna")
    assert next(e.source for e in result.edges if e.target == dropna.id) == assign.id


def test_inplace_and_loc():
    code = """
df = pd.DataFrame({"a": [1, None, 3], "b": [4, 5, 6]})
df.dropna(inplace=True)
sub = df.loc[df["b"] > 4, ["a"]]
"""
    result = run_code(code)
    assert ops(result) == ["DataFrame", "dropna (inplace)", "loc"]
    loc = node(result, "loc")
    assert loc.label == """.loc[df['b'] > 4, ['a']]"""
    assert loc.profile.rows == 1


def test_internal_calls_are_not_recorded():
    code = """
df = pd.DataFrame({"k": ["a", "b", "a"], "v": [1, 2, 3]})
p = df.pivot_table(index="k", values="v", aggfunc="sum")
"""
    assert ops(run_code(code)) == ["DataFrame", "pivot_table"]


def test_error_returns_partial_graph():
    code = 'df = pd.DataFrame({"a": [1]})\nx = df.head()\ny = df["missing"]\n'
    result = run_code(code)
    assert result.error is not None
    assert result.error.type == "KeyError"
    assert result.error.line == 3
    assert ops(result) == ["DataFrame", "head"]


def test_patches_are_removed_after_trace():
    before = pd.DataFrame.merge, pd.DataFrame.head, pd.merge
    with trace() as t:
        pd.DataFrame({"a": [1]}).head()
    assert (pd.DataFrame.merge, pd.DataFrame.head, pd.merge) == before
    assert "head" not in vars(pd.DataFrame)
    assert [n.op for n in t.result().nodes] == ["DataFrame", "head"]


def test_node_limit():
    code = "df = pd.DataFrame({'a': [1]})\nfor _ in range(20):\n    df = df.copy()\n"
    with trace(max_nodes=5) as t:
        exec(code, {"pd": pd})
    result = t.result()
    assert len(result.nodes) == 5
    assert any("node limit" in w for w in result.warnings)


def test_groupby_selection_label():
    code = """
df = pd.DataFrame({"k": ["a", "b", "a"], "v": [1, 2, 3]})
s = df.groupby("k")["v"].sum()
"""
    agg = node(run_code(code), "groupby.sum")
    assert agg.label == "groupby('k')['v'].sum()"
    assert agg.details["group_size_max"] == 2

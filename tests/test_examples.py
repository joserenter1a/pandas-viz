"""Lost-row examples (design §7.5): the rows each operation dropped, left unmatched or nulled."""

import pandas as pd

from pandas_viz import run_code
from pandas_viz.examples import EXAMPLES


def node(result, op):
    return next(n for n in result.nodes if n.op == op)


def ex(n, kind, column=None):
    return next(e for e in n.examples if e.kind == kind and (column is None or e.column == column))


def column(e, name):
    i = e.columns.index(name)
    return [row[i] for row in e.rows]


def test_revenue_join_examples_explain_the_bug():
    r = run_code(EXAMPLES[0].code)
    merge = node(r, "merge")
    dup = ex(merge, "duplicate_keys_right")
    assert (dup.total, column(dup, "user_id"), dup.highlight) == (2, [4, 4], ["user_id"])
    unmatched = ex(merge, "unmatched_left")
    assert column(unmatched, "user_id") == [7, 8, 9] and unmatched.total == 3
    nulls = ex(merge, "nulls", "country")
    assert nulls.total == 4 and set(column(nulls, "user_id")) == {6, 7, 8, 9}
    # findings point at the rows that illustrate them
    linked = {f.message.split(" ")[0]: f.example_kind for f in r.findings}
    assert linked["left"] == "duplicate_keys_right"  # "left merge grew rows"
    assert linked["filter"] == "dropped"


def test_filter_examples_use_the_mask_even_with_duplicate_index():
    code = ('df = pd.DataFrame({"a": [1, 2, 3, 4]}, index=[0, 0, 1, 1])\n'
            'kept = df[df["a"] % 2 == 0]\n'
            'q = df.query("a > 2")\n')
    r = run_code(code)
    assert column(ex(node(r, "filter"), "dropped"), "a") == [1, 3]
    # query gives us no mask, and duplicate labels make the index ambiguous: no examples
    assert node(r, "query").examples == []


def test_dropna_dedupe_loc_examples_and_limits_skipped():
    code = ('df = pd.DataFrame({"k": [1, 1, 2, None], "v": [1, 1, 2, 3]})\n'
            'a = df.dropna()\n'
            'b = a.drop_duplicates()\n'
            'c = df.loc[df["v"] > 1, ["k"]]\n'
            'd = df.head(1)\n')
    r = run_code(code)
    assert column(ex(node(r, "dropna"), "dropped"), "v") == [3]
    assert ex(node(r, "drop_duplicates"), "dropped").index == [1]
    assert ex(node(r, "loc"), "dropped").total == 2
    assert node(r, "head").examples == []  # dropping rows is the point of head()


def test_inner_join_null_keys_and_both_sides_unmatched():
    code = ('a = pd.DataFrame({"k": [1, 2, None], "x": [1, 2, 3]})\n'
            'b = pd.DataFrame({"k": [1, 5], "y": [10, 50]})\n'
            'm = a.merge(b, on="k", how="inner")\n')
    merge = node(run_code(code), "merge")
    assert column(ex(merge, "unmatched_right"), "k") == [5]
    assert ex(merge, "null_keys_left").total == 1
    assert "duplicate_keys_right" not in {e.kind for e in merge.examples}


def test_examples_are_capped_and_json_safe():
    df = pd.DataFrame({"t": pd.date_range("2024-01-01", periods=50), "x": range(50)})
    r = run_code("small = df[df['x'] > 100]\n",
                 namespace={"pd": pd, "df": df})
    dropped = ex(node(r, "filter"), "dropped")
    assert dropped.total == 50 and len(dropped.rows) == 5
    assert dropped.rows[0][0].startswith("2024-01-01")
    r.model_dump_json()  # serializable

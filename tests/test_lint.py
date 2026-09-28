"""Pushdown / anti-pattern hints (lint.py): they must be right, and must not change results."""

import io
import textwrap

import pandas as pd
import pytest

from pandas_viz import run_code
from pandas_viz.examples import EXAMPLES

PUSHDOWN = next(e for e in EXAMPLES if e.id == "pushdown")


def kinds(code, **kw):
    return {h.kind: h for h in run_code(textwrap.dedent(code), **kw).hints}


FRAMES = """
orders = pd.DataFrame({"user_id": [1, 2, 2, 3, 4, 5, 1, 3], "amount": [12, 40, 8, 55, 31, 9, 70, 15]})
users = pd.DataFrame({"user_id": [1, 2, 3, 4, 5], "country": ["US", "MX", "US", "CA", "MX"]})
"""


def test_example_triggers_the_three_pushdowns():
    hints = {h.kind: h for h in run_code(PUSHDOWN.code).hints}
    assert set(hints) == {"filter_before_join", "useless_sort", "unused_columns"}
    assert hints["unused_columns"].suggestion == "pd.read_csv(..., usecols=['user_id', 'amount'])"


def test_other_examples_have_no_false_positives():
    for ex in EXAMPLES:
        if ex.id != "pushdown":
            assert run_code(ex.code).hints == [], ex.id


def test_pushed_down_filter_gives_the_same_result():
    code = FRAMES + textwrap.dedent("""
        enriched = orders.merge(users, on="user_id", how="inner")
        large = enriched[enriched["amount"] > 20]
        out = large.groupby("country")["amount"].sum()
    """)
    hint = next(h for h in run_code(code).hints if h.kind == "filter_before_join")
    assert hint.suggestion == "orders = orders[orders['amount'] > 20]"
    rewritten = code.replace('enriched = orders.merge', hint.suggestion + '\nenriched = orders.merge')
    before, after = {"pd": pd}, {"pd": pd}
    exec(code, before)
    exec(rewritten, after)
    pd.testing.assert_series_equal(before["out"], after["out"])


@pytest.mark.parametrize("how, predicate, expected", [
    ("inner", 'enriched["country"] == "US"', True),     # right side of an inner join: fine
    ("left", 'enriched["country"] == "US"', False),     # right side of a left join: changes results
    ("left", 'enriched["amount"] > 20', True),          # left side of a left join: fine
    ("inner", '(enriched["amount"] > 20) & (enriched["country"] == "US")', False),  # both sides
    ("inner", 'enriched["amount"] > 5', False),         # keeps ≥ 90% of rows: not worth it
    ("outer", 'enriched["amount"] > 20', False),
])
def test_filter_before_join_rules(how, predicate, expected):
    code = FRAMES + f'enriched = orders.merge(users, on="user_id", how="{how}")\nx = enriched[{predicate}]\n'
    assert ("filter_before_join" in kinds(code)) is expected


def test_query_predicates_are_parsed():
    code = FRAMES + 'enriched = orders.merge(users, on="user_id")\nx = enriched.query("amount > 20")\n'
    assert kinds(code)["filter_before_join"].suggestion == "orders = orders.query('amount > 20')"


def test_filter_earlier_only_when_independent():
    base = FRAMES + "s = orders.sort_values('amount')\n"
    assert "filter_earlier" in kinds(base + "x = s[s['amount'] > 20]\n")
    mutate = FRAMES + "o = orders.assign(big=orders['amount'] * 2)\n"
    assert "filter_earlier" not in kinds(mutate + "x = o[o['big'] > 40]\n")  # uses the new column
    assert "filter_earlier" in kinds(mutate + "x = o[o['amount'] > 20]\n")


def test_sort_hints():
    s = FRAMES + "s = orders.sort_values('amount')\n"
    assert "useless_sort" in kinds(s + "t = s.groupby('user_id')['amount'].sum()\n")
    assert "useless_sort" not in kinds(s + "t = s.groupby('user_id')['amount'].first()\n")
    assert "useless_sort" not in kinds(s + "t = s.groupby('user_id').agg(top=('amount', 'last'))\n")
    assert "useless_sort" in kinds(s + "t = s.sort_values('user_id')\n")
    assert "useless_sort" not in kinds(s + "t = s.sort_values('user_id', kind='stable')\n")
    # the sorted frame is used twice: its order may matter elsewhere
    assert "useless_sort" not in kinds(s + "t = s.groupby('user_id')['amount'].sum()\nh = s.head(2)\n")


def test_unused_columns(tmp_path):
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4], "c": [5, 6], "d": [None, 1]})
    df.to_csv(tmp_path / "t.csv", index=False)
    df.to_parquet(tmp_path / "t.parquet")
    path = str(tmp_path / "t.csv")
    # 'b' is only used by the filter; 'c' and 'd' never
    h = kinds(f"x = pd.read_csv({path!r})\ny = x[x['b'] > 3][['a']]\n")["unused_columns"]
    assert "'c', 'd'" in h.message and h.suggestion == f"pd.read_csv({path!r}, usecols=['a', 'b'])"
    # dropna() with no subset reads every column
    assert "unused_columns" not in kinds(f"x = pd.read_csv({path!r})\ny = x.dropna()[['a']]\n")
    pq = str(tmp_path / "t.parquet")
    h = kinds(f"x = pd.read_parquet({pq!r})\ny = x[['a']]\n")["unused_columns"]
    assert h.suggestion == f"pd.read_parquet({pq!r}, columns=['a'])"


def test_anti_patterns(tmp_path):
    (tmp_path / "t.csv").write_text("a\n1\n")
    path = str(tmp_path / "t.csv")
    h = kinds(f"x = pd.read_csv({path!r})\ny = pd.read_csv({path!r})\nx.dropna(inplace=True)\n")
    assert {"duplicate_read", "inplace"} <= set(h)
    big = pd.DataFrame({"a": range(2000)})
    assert "row_apply" in kinds("y = df.apply(lambda r: r.a + 1, axis=1)\n", namespace={"pd": pd, "df": big})
    assert "row_apply" not in kinds("y = df.apply(lambda c: c.sum())\n", namespace={"pd": pd, "df": big})

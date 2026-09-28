import pytest
from fastapi.testclient import TestClient

from pandas_viz import run_code
from pandas_viz.app import create_app
from pandas_viz.cli import main
from pandas_viz.examples import EXAMPLES


@pytest.fixture(scope="module")
def revenue():
    return run_code(EXAMPLES[0].code)


def by_name(diff):
    return {c.name: c for c in diff.columns}


def test_diff_along_lineage(revenue):
    d = revenue.diff("paid", "enriched")
    assert d.relation == "ancestor"
    assert [s.var_name or s.op for s in d.path] == ["paid", "enriched"]
    assert (d.rows_a, d.rows_b) == (9, 10)
    cols = by_name(d)
    assert cols["country"].status == "added"
    assert cols["user_id"].status == "same"
    assert d.columns[-1].name == "country"  # later frame's column order


def test_diff_reverse_and_unrelated(revenue):
    assert revenue.diff("enriched", "paid").relation == "descendant"
    assert revenue.diff("enriched", "paid").path[0].var_name == "paid"  # always earlier → later
    unrelated = revenue.diff("users", "paid")
    assert unrelated.relation == "unrelated" and unrelated.path == []
    assert revenue.diff("paid", "paid").relation == "same"


def test_diff_rename_dtype_and_nulls():
    r = run_code('df = pd.DataFrame({"a": [1, 2], "b": [1.0, None], "c": ["x", "y"]})\n'
                 'out = df.rename(columns={"a": "id"}).fillna(0).astype({"c": "category"})\n')
    cols = by_name(r.diff("df", "out"))
    assert cols["id"].status == "renamed" and cols["id"].renamed_from == "a"
    assert "a" not in cols
    assert (cols["b"].status, cols["b"].nulls_a, cols["b"].nulls_b) == ("changed", 1, 0)
    assert (cols["c"].dtype_a, cols["c"].dtype_b) == ("str", "category")


def test_node_lookup(revenue):
    assert revenue.node("n1").var_name == "paid"
    assert revenue.node("revenue").op == "sort_values"  # last node bound to the name
    with pytest.raises(KeyError):
        revenue.node("nope")


def test_diff_api(revenue, tmp_path):
    client = TestClient(create_app(data_dir=tmp_path, static_dir=tmp_path / "none"))
    body = revenue.model_dump(mode="json")
    for n in body["nodes"]:  # the UI strips samples before sending
        n["profile"]["sample"] = []
    resp = client.post("/api/diff", json={"trace": body, "a": "n0", "b": "n5"})
    assert resp.status_code == 200
    assert resp.json()["relation"] == "ancestor"
    assert client.post("/api/diff", json={"trace": body, "a": "n0", "b": "zz"}).status_code == 404


def test_cli_diff(tmp_path, capsys):
    script = tmp_path / "p.py"
    script.write_text("import pandas as pd\ndf = pd.DataFrame({'a': [1, None]})\nout = df.dropna()\n")
    with pytest.raises(SystemExit) as exit_info:
        main(["run", str(script), "--diff", "df", "out"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "rows    2 → 1 (-1)" in out and "* a  nulls 1 → 0" in out
    with pytest.raises(SystemExit) as exit_info:
        main(["run", str(script), "--diff", "df", "missing"])
    assert exit_info.value.code == 2

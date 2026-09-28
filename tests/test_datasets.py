import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from pandas_viz import datasets
from pandas_viz.app import create_app


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PANDAS_VIZ_HOME", str(tmp_path / "home"))


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(data_dir=tmp_path, static_dir=tmp_path / "none"))


CSV = b"user_id,country\n1,US\n2,MX\n"


@pytest.mark.parametrize("stem, expected", [
    ("orders", "orders"),
    ("Q3 Sales-2024", "q3_sales_2024"),
    ("2024_orders", "data_2024_orders"),
    ("class", "class_df"),
    ("pd", "pd_df"),
    ("sum", "sum_df"),
    ("---", "data"),
])
def test_variable_name(stem, expected):
    assert datasets.variable_name(stem) == expected


def test_formats_roundtrip(tmp_path):
    df = pd.DataFrame({"a": [1, 2], "b": ["x", None]})
    files = {
        "t.csv": df.to_csv(index=False).encode(),
        "t.tsv": df.to_csv(index=False, sep="\t").encode(),
        "t.json": df.to_json(orient="records").encode(),
        "t.jsonl": df.to_json(orient="records", lines=True).encode(),
    }
    buf = io.BytesIO()
    df.to_parquet(buf)
    files["t.parquet"] = buf.getvalue()
    for filename, data in files.items():
        info = datasets.save_upload(io.BytesIO(data), filename)
        assert (info.name, info.rows, info.cols) == ("t", 2, 2), filename
        assert [c.null_count for c in info.columns] == [0, 1], filename
    # every upload replaced the previous "t"
    assert [d.name for d in datasets.list_datasets()] == ["t"]
    assert datasets.list_datasets()[0].format == "parquet"


def test_bad_uploads_leave_nothing_behind():
    with pytest.raises(datasets.DatasetError, match="unsupported"):
        datasets.save_upload(io.BytesIO(b"x"), "notes.docx")
    with pytest.raises(datasets.DatasetError, match="could not read"):
        datasets.save_upload(io.BytesIO(b"\x00\x01garbage"), "bad.parquet")
    assert datasets.list_datasets() == []
    assert list(datasets.datasets_dir().iterdir()) == []


def test_upload_size_limit(monkeypatch):
    monkeypatch.setattr(datasets, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(datasets.DatasetError, match="larger than"):
        datasets.save_upload(io.BytesIO(CSV), "users.csv")


@pytest.mark.parametrize("code, expected", [
    ("m = orders.merge(users)", ["users", "orders"]),
    ("orders = pd.read_csv('o.csv')\nm = orders.merge(users)", ["users"]),  # bound first
    ("orders = orders.dropna()", ["orders"]),  # read before it is rebound
    ("x = users.head()\nusers = 1", ["users"]),
    ("def f(events):\n    return events", ["events"]),  # conservative: loading is harmless
    ("import orders", []),
    ("x = 1", []),
    ("def broken(:", []),
])
def test_referenced(code, expected):
    assert datasets.referenced(code, ["users", "orders", "events"]) == expected


def test_get_rejects_path_tricks():
    assert datasets.get("../../etc/passwd") is None
    assert datasets.delete("../x") is False


def test_api_upload_trace_and_delete(client):
    resp = client.post("/api/datasets", files={"file": ("Users.csv", CSV, "text/csv")})
    assert resp.status_code == 200
    assert resp.json()["name"] == "users"
    client.post("/api/datasets", files={"file": ("orders.csv", b"id,user_id\n1,1\n2,3\n", "text/csv")},
                data={"name": "Order Lines"})
    assert [d["name"] for d in client.get("/api/datasets").json()] == ["order_lines", "users"]

    body = client.post("/api/trace", json={
        "code": "m = order_lines.merge(users, on='user_id', how='left')"}).json()
    assert body["error"] is None
    sources = [n for n in body["nodes"] if n["op"] == "dataset"]
    assert [(n["var_name"], n["label"]) for n in sources] == [
        ("order_lines", "dataset orders.csv"), ("users", "dataset Users.csv")]
    assert body["nodes"][-1]["details"]["left_only_rows"] == 1

    # a dataset the code doesn't mention is not loaded
    body = client.post("/api/trace", json={"code": "x = users.head(1)"}).json()
    assert [n["op"] for n in body["nodes"]] == ["dataset", "head"]

    assert client.delete("/api/datasets/users").json() == {"deleted": True}
    assert client.delete("/api/datasets/users").status_code == 404
    body = client.post("/api/trace", json={"code": "x = users.head(1)"}).json()
    assert body["error"]["type"] == "NameError"


def test_api_rejects_bad_file(client):
    resp = client.post("/api/datasets", files={"file": ("x.xlsx", b"PK..", "application/octet-stream")})
    assert resp.status_code == 400 and "unsupported" in resp.json()["detail"]

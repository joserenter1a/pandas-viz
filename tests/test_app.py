from fastapi.testclient import TestClient

from pandas_viz.app import create_app
from pandas_viz.cli import main
from pandas_viz.runner import run_trace


def test_runner_reads_files_relative_to_data_dir(tmp_path):
    (tmp_path / "data.csv").write_text("a,b\n1,2\n3,4\n")
    result = run_trace('df = pd.read_csv("data.csv")\nprint(len(df))', cwd=tmp_path)
    assert result.error is None
    assert result.stdout == "2\n"
    assert result.nodes[0].category == "source"
    assert result.nodes[0].details["path"] == "data.csv"


def test_runner_timeout(tmp_path):
    result = run_trace("while True: pass", cwd=tmp_path, timeout_s=2)
    assert result.error.type == "Timeout"


def test_runner_hides_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "hunter2")
    result = run_trace('import os\nprint(os.environ.get("SECRET_TOKEN"))', cwd=tmp_path)
    assert result.stdout == "None\n"


def test_api(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path, static_dir=tmp_path / "none"))
    examples = client.get("/api/examples").json()
    assert examples[0]["id"] == "revenue"
    body = client.post("/api/trace", json={"code": examples[0]["code"]}).json()
    assert body["error"] is None
    assert len(body["nodes"]) == 6
    assert body["findings"]


def test_cli_run(tmp_path, capsys):
    script = tmp_path / "pipe.py"
    script.write_text("import pandas as pd\ndf = pd.DataFrame({'a': [1, 2]})\nout = df.head(1)\n")
    try:
        main(["run", str(script)])
    except SystemExit as exc:
        assert exc.code == 0
    out = capsys.readouterr().out
    assert "out = head(1)" in out
    assert "2 → 1" in out

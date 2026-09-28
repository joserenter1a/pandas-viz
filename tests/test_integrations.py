import pytest
from fastapi.testclient import TestClient

from pandas_viz import run_code, server
from pandas_viz.app import create_app
from pandas_viz.cli import main
from pandas_viz.store import list_traces, load_trace, save_trace


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PANDAS_VIZ_HOME", str(tmp_path / "home"))


@pytest.fixture
def opened(monkeypatch):
    """Capture browser opens and pretend a server is already running."""
    urls = []
    monkeypatch.setattr(server.webbrowser, "open", urls.append)
    monkeypatch.setattr(server, "ensure_server", lambda port=8000, data_dir=None: {"ui": True})
    return urls


def test_store_roundtrip_and_api(tmp_path):
    result = run_code("df = pd.DataFrame({'a': [1, None]})\nout = df.dropna()\n")
    stored = save_trace(result, code="...", title="demo")
    assert load_trace(stored.id).result.nodes[-1].var_name == "out"
    assert [t.id for t in list_traces()] == [stored.id]
    assert load_trace("../../etc/passwd") is None

    client = TestClient(create_app(data_dir=tmp_path, static_dir=tmp_path / "none"))
    assert client.get("/api/health").json()["app"] == "pandas-viz"
    assert client.get("/api/traces").json()[0]["title"] == "demo"
    body = client.get(f"/api/traces/{stored.id}").json()
    assert body["n_nodes"] == 2 and body["result"]["nodes"][1]["op"] == "dropna"
    assert client.get("/api/traces/20990101-000000-abcdef").status_code == 404


def test_cli_run_open(tmp_path, opened, capsys):
    script = tmp_path / "pipe.py"
    script.write_text("import pandas as pd\ndf = pd.DataFrame({'a': [1, 2]})\nout = df.head(1)\n")
    with pytest.raises(SystemExit) as exit_info:
        main(["run", str(script), "--open", "--port", "8123"])
    assert exit_info.value.code == 0
    assert len(opened) == 1 and opened[0].startswith("http://127.0.0.1:8123/?trace=")
    stored = load_trace(opened[0].split("=")[1])
    assert stored.code == script.read_text()
    assert stored.title == str(script)
    assert "opened http://127.0.0.1:8123/?trace=" in capsys.readouterr().out


def test_ensure_server_rejects_foreign_app(monkeypatch):
    monkeypatch.setattr(server, "health", lambda port, timeout=0.5: {"foreign": True})
    with pytest.raises(RuntimeError, match="another app"):
        server.ensure_server(9999)


# ---------------------------------------------------------------- notebook magic

@pytest.fixture(scope="module")
def ip():
    from IPython.testing.globalipapp import start_ipython

    shell = start_ipython()
    shell.run_cell("import pandas as pd\n%load_ext pandas_viz")
    return shell


def test_magic_traces_cell_in_user_namespace(ip):
    ip.run_cell('users = pd.DataFrame({"k": [1, 1, 2], "x": [1, 2, 3]})')
    ip.run_cell('%%pandasviz -o t -q\n'
                'keys = pd.DataFrame({"k": [1, 3]})\n'
                'm = users.merge(keys, on="k", how="left")\n'
                'm.head()\n')
    t = ip.user_ns["t"]
    assert [(n.op, n.var_name, n.source_line) for n in t.nodes] == [
        ("DataFrame", "users", None),  # defined in an earlier cell: shown as a source
        ("DataFrame", "keys", None),
        ("merge", "m", 2),
        ("head", None, 3),
    ]
    assert t.nodes[2].details["cardinality"] == "m:1"
    assert "m" in ip.user_ns  # assignments persist in the notebook
    assert t.error is None


def test_magic_error_and_repr_not_traced(ip):
    ip.run_cell('%%pandasviz -o t -q\ndf = pd.DataFrame({"a": [1, 2]})\nsmall = df.head(1)\nsmall\n')
    # displaying `small` goes through pandas' repr machinery, which must not add nodes
    assert [n.op for n in ip.user_ns["t"].nodes] == ["DataFrame", "head"]
    ip.run_cell('%%pandasviz -o t -q\nok = df.tail(1)\nx = df["nope"]\n')
    t = ip.user_ns["t"]
    assert [n.op for n in t.nodes] == ["DataFrame", "tail"]  # partial graph up to the failure
    assert (t.error.type, t.error.line) == ("KeyError", 2)


def test_magic_open_and_inline_html(ip, opened):
    from pandas_viz import notebook

    ip.run_cell('%%pandasviz --open --title "cell A"\ns = pd.DataFrame({"a": [3, 1]}).sort_values("a")\n')
    assert len(opened) == 1
    assert load_trace(opened[0].split("=")[1]).title == "cell A"
    html = notebook.render_html(notebook.last_result, opened[0])
    assert "open in pandas-viz" in html and "sort_values(&#x27;a&#x27;)" in html


def test_cli_checks(tmp_path, capsys):
    script = tmp_path / "pipe.py"
    script.write_text("import pandas as pd\n"
                      "a = pd.DataFrame({'k': [1, 2]})\n"
                      "b = pd.DataFrame({'k': [1, 1]})\n"
                      "m = a.merge(b, on='k', how='left')\n")
    with pytest.raises(SystemExit):
        main(["run", str(script), "--checks"])
    assert "a.merge(b, on='k', how='left', validate=\"m:1\")  # ✗" in capsys.readouterr().out
    out = tmp_path / "checks.py"
    with pytest.raises(SystemExit):
        main(["run", str(script), "--checks", str(out)])
    assert "assert len(m) == len(a)" in out.read_text()


def test_magic_checks_flag(ip, capsys):
    ip.run_cell('%%pandasviz -q --checks\nx = pd.DataFrame({"a": [1]}).head(1)\n')
    assert "output schema of x" in capsys.readouterr().out

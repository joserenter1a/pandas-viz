"""Find or start a local pandas-viz server, and open saved traces in the browser."""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from .models import TraceResult
from .store import home, save_trace

HOST = "127.0.0.1"


def health(port: int, timeout: float = 0.5) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/health", timeout=timeout) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return data if data.get("app") == "pandas-viz" else {"foreign": True}


def ensure_server(port: int = 8000, data_dir: Path | None = None, wait_s: float = 15.0) -> dict:
    """Return the running server's health info, starting a detached server if none is up."""
    info = health(port)
    if info and info.get("foreign"):
        raise RuntimeError(f"port {port} is used by another app; pass a different port")
    if info:
        return info
    log = (home() / "server.log").open("ab")
    subprocess.Popen(
        [sys.executable, "-m", "pandas_viz.cli", "serve", "--port", str(port),
         "--data-dir", str((data_dir or Path.cwd()).resolve())],
        stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True,
    )
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if info := health(port):
            return info
        time.sleep(0.2)
    raise RuntimeError(f"pandas-viz server did not start on port {port}; see {home() / 'server.log'}")


def trace_url(trace_id: str, port: int = 8000) -> str:
    return f"http://{HOST}:{port}/?trace={trace_id}"


def open_trace(result: TraceResult, *, code: str, title: str, port: int = 8000,
               data_dir: Path | None = None, browser: bool = True) -> str:
    stored = save_trace(result, code=code, title=title)
    info = ensure_server(port, data_dir)
    url = trace_url(stored.id, port)
    if not info.get("ui"):
        print("pandas-viz: the web UI is not built; run `npm install && npm run build` in web/",
              file=sys.stderr)
    if browser:
        webbrowser.open(url)
    return url

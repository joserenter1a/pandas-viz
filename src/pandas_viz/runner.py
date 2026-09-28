"""Run a trace in an isolated subprocess with a timeout and a scrubbed environment."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .models import TraceError, TraceResult

_ENV_KEEP = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT", "VIRTUAL_ENV")


def run_trace(code: str, *, cwd: Path, timeout_s: float = 30.0,
              datasets: dict[str, dict[str, str]] | None = None) -> TraceResult:
    env = {k: v for k, v in os.environ.items() if k in _ENV_KEEP}
    with tempfile.TemporaryDirectory(prefix="pandas-viz-") as tmp:
        out = Path(tmp) / "result.json"
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pandas_viz.worker", str(out)],
                input=json.dumps({"code": code, "datasets": datasets or {}}),
                capture_output=True,
                text=True,
                cwd=cwd,
                env=env,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return _failed("Timeout", f"trace did not finish within {timeout_s:g}s")
        if out.exists():
            return TraceResult.model_validate_json(out.read_text())
        return _failed("WorkerCrashed", f"worker exited with code {proc.returncode}",
                       proc.stderr[-5000:])


def _failed(kind: str, message: str, tb: str = "") -> TraceResult:
    return TraceResult(error=TraceError(type=kind, message=message, traceback=tb))

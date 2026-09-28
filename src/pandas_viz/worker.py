"""Execute user code under the tracer. Run as a subprocess by ``runner`` for isolation.

Protocol: request JSON ``{"code": ...}`` on stdin; the TraceResult JSON is written to
the file path given as argv[1] (not stdout, which user code may write to).
"""

import io
import json
import linecache
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import numpy as np
import pandas as pd

from .datasets import load as load_dataset
from .models import TraceError, TraceResult
from .tracer import Tracer

STDOUT_LIMIT = 100_000
DEFAULT_FILENAME = "<pandas-viz>"


def run_code(code: str, filename: str = DEFAULT_FILENAME, namespace: dict | None = None,
             datasets: dict[str, dict[str, str]] | None = None) -> TraceResult:
    """Trace ``code``. A given ``namespace`` is used in place (assignments persist in it).

    ``datasets`` maps variable names to ``{path, format, filename}``; each is loaded and
    bound in the namespace before the code runs, as a "dataset" source step.
    """
    linecache.cache[filename] = (len(code), None, code.splitlines(True), filename)
    ns = namespace if namespace is not None else {
        "__name__": "__main__", "__file__": filename, "pd": pd, "np": np,
    }
    buf = io.StringIO()
    error = None
    with Tracer() as tracer, redirect_stdout(buf), redirect_stderr(buf):
        try:
            for name, spec in (datasets or {}).items():
                with tracer.paused():
                    df = load_dataset(Path(spec["path"]), spec["format"])
                tracer.register_source(df, op="dataset", label=f"dataset {spec['filename']}",
                                       var_name=name, details={"dataset": name, **spec})
                ns[name] = df
            exec(compile(code, filename, "exec"), ns)
        except (Exception, SystemExit) as exc:
            error = _error(exc, filename)
    tracer.assign_var_names(code, filename)
    tracer.name_from_namespace(ns)
    result = tracer.result()
    result.stdout = buf.getvalue()[:STDOUT_LIMIT]
    result.error = error
    return result


def _error(exc: BaseException, filename: str) -> TraceError:
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename == filename]
    return TraceError(
        type=type(exc).__name__,
        message=str(exc),
        line=frames[-1].lineno if frames else getattr(exc, "lineno", None),
        traceback="".join(traceback.format_exception(exc)),
    )


def _limit_memory(max_bytes: int):
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (max_bytes, max_bytes))
    except (ImportError, ValueError, OSError):
        pass  # not enforceable on this platform (e.g. macOS)


def main():
    request = json.load(sys.stdin)
    _limit_memory(int(request.get("max_memory_bytes", 4 * 1024**3)))
    result = run_code(request["code"], datasets=request.get("datasets"))
    with open(sys.argv[1], "w") as fh:
        fh.write(result.model_dump_json())


if __name__ == "__main__":
    main()

"""On-disk store for traces produced outside the server (CLI, notebooks, ``Tracer.open``).

Traces live in ``$PANDAS_VIZ_HOME/traces`` (default ``~/.pandas-viz/traces``) so any
process can write one and the server can serve it at ``/?trace=<id>``.
"""

import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from .models import StoredTrace, TraceResult, TraceSummary

MAX_TRACES = 200
_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")


def home() -> Path:
    return Path(os.environ.get("PANDAS_VIZ_HOME", Path.home() / ".pandas-viz"))


def traces_dir() -> Path:
    path = home() / "traces"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_trace(result: TraceResult, *, code: str, title: str) -> StoredTrace:
    now = datetime.now(timezone.utc)
    stored = StoredTrace(
        id=f"{now:%Y%m%d-%H%M%S}-{secrets.token_hex(3)}",
        title=title,
        created_at=now.isoformat(timespec="seconds"),
        n_nodes=len(result.nodes),
        n_findings=len(result.findings),
        has_error=result.error is not None,
        code=code,
        result=result,
    )
    (traces_dir() / f"{stored.id}.json").write_text(stored.model_dump_json())
    _prune()
    return stored


def load_trace(trace_id: str) -> StoredTrace | None:
    if not _ID.match(trace_id):
        return None
    path = traces_dir() / f"{trace_id}.json"
    return StoredTrace.model_validate_json(path.read_text()) if path.exists() else None


def list_traces(limit: int = 30) -> list[TraceSummary]:
    out = []
    for path in sorted(traces_dir().glob("*.json"), reverse=True)[:limit]:
        try:
            out.append(TraceSummary.model_validate_json(path.read_text()))
        except ValueError:
            continue
    return out


def _prune():
    for path in sorted(traces_dir().glob("*.json"), reverse=True)[MAX_TRACES:]:
        path.unlink(missing_ok=True)

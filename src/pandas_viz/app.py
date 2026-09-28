"""FastAPI app: trace API plus (when built) the static Next.js frontend."""

import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles

from .examples import EXAMPLES
from . import datasets
from .diff import diff_nodes
from .models import (
    DatasetInfo, DiffRequest, Example, NodeDiff, StoredTrace, TraceRequest, TraceResult, TraceSummary,
)
from .runner import run_trace
from .store import list_traces, load_trace

_DEFAULT_STATIC = Path(__file__).resolve().parents[2] / "web" / "out"


def create_app(data_dir: Path | None = None, static_dir: Path | None = None) -> FastAPI:
    data_dir = (data_dir or Path(os.environ.get("PANDAS_VIZ_DATA_DIR", "."))).resolve()
    static_dir = static_dir or Path(os.environ.get("PANDAS_VIZ_STATIC_DIR", _DEFAULT_STATIC))

    app = FastAPI(title="pandas-viz", version="0.1.0")

    @app.get("/api/health")
    def health() -> dict[str, str | bool]:
        return {"status": "ok", "app": "pandas-viz", "ui": static_dir.is_dir(),
                "data_dir": str(data_dir)}

    @app.get("/api/examples")
    def examples() -> list[Example]:
        return EXAMPLES

    @app.post("/api/trace")
    async def trace(req: TraceRequest) -> TraceResult:
        names = datasets.referenced(req.code, [d.name for d in datasets.list_datasets()])
        return await run_in_threadpool(run_trace, req.code, cwd=data_dir,
                                       timeout_s=min(req.timeout_s, 120.0),
                                       datasets=datasets.resolve(names))

    @app.get("/api/datasets")
    def list_datasets() -> list[DatasetInfo]:
        return datasets.list_datasets()

    @app.post("/api/datasets")
    def upload_dataset(file: UploadFile = File(...), name: str | None = Form(None)) -> DatasetInfo:
        try:
            return datasets.save_upload(file.file, file.filename or "upload", name)
        except datasets.DatasetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/datasets/{name}")
    def delete_dataset(name: str) -> dict[str, bool]:
        if not datasets.delete(name):
            raise HTTPException(status_code=404, detail="dataset not found")
        return {"deleted": True}

    @app.post("/api/diff")
    def diff(req: DiffRequest) -> NodeDiff:
        ids = {n.id for n in req.trace.nodes}
        if req.a not in ids or req.b not in ids:
            raise HTTPException(status_code=404, detail="unknown node id")
        return diff_nodes(req.trace, req.a, req.b)

    @app.get("/api/traces")
    def traces() -> list[TraceSummary]:
        return list_traces()

    @app.get("/api/traces/{trace_id}")
    def stored_trace(trace_id: str) -> StoredTrace:
        stored = load_trace(trace_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="trace not found")
        return stored

    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")

    return app


app = create_app()

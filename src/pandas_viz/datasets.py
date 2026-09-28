"""Uploaded datasets: stored under ``$PANDAS_VIZ_HOME/datasets`` and exposed to traced
code as named inputs (``orders.csv`` → the variable ``orders``).

Only datasets that the code references (and doesn't assign itself) are loaded, so
uploading a large file costs nothing until it is used.
"""

import ast
import builtins
import keyword
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from .models import DatasetInfo
from .profiler import profile
from .store import home

MAX_UPLOAD_BYTES = int(os.environ.get("PANDAS_VIZ_MAX_UPLOAD_MB", "500")) * 1024 * 1024
FORMATS = {".csv": "csv", ".tsv": "tsv", ".txt": "csv", ".parquet": "parquet", ".pq": "parquet",
           ".json": "json", ".jsonl": "jsonl", ".ndjson": "jsonl"}
_RESERVED = {"pd", "np"} | set(dir(builtins))


class DatasetError(ValueError):
    pass


def datasets_dir() -> Path:
    path = home() / "datasets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def variable_name(stem: str) -> str:
    """A valid, non-clashing Python identifier for a file stem: ``Q3 sales-2024`` → ``q3_sales_2024``."""
    name = re.sub(r"\W+", "_", stem.strip().lower()).strip("_") or "data"
    if name[0].isdigit():
        name = f"data_{name}"
    if keyword.iskeyword(name) or name in _RESERVED:
        name = f"{name}_df"
    return name


def load(path: Path, fmt: str) -> pd.DataFrame:
    if fmt == "csv":
        return pd.read_csv(path)
    if fmt == "tsv":
        return pd.read_csv(path, sep="\t")
    if fmt == "parquet":
        return pd.read_parquet(path)
    if fmt == "jsonl":
        return pd.read_json(path, lines=True)
    try:
        return pd.read_json(path)
    except ValueError:  # newline-delimited JSON saved as .json
        return pd.read_json(path, lines=True)


def save_upload(stream: BinaryIO, filename: str, name: str | None = None) -> DatasetInfo:
    suffix = Path(filename).suffix.lower()
    fmt = FORMATS.get(suffix)
    if fmt is None:
        raise DatasetError(f"unsupported file type {suffix or '(none)'}; "
                           f"use one of {', '.join(sorted(set(FORMATS)))}")
    var = variable_name(name or Path(filename).stem)
    target = datasets_dir() / f"{var}{suffix}"
    tmp = target.with_suffix(target.suffix + ".part")
    size = 0
    with tmp.open("wb") as out:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                tmp.unlink(missing_ok=True)
                raise DatasetError(f"file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
            out.write(chunk)
    try:
        df = load(tmp, fmt)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise DatasetError(f"could not read {filename} as {fmt}: {exc}") from exc

    delete(var)  # replacing a dataset of the same name (possibly another format)
    tmp.replace(target)
    prof = profile(df)
    info = DatasetInfo(
        name=var, filename=filename, format=fmt, size_bytes=size, rows=prof.rows, cols=prof.cols,
        columns=prof.columns, uploaded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    _meta_path(var).write_text(info.model_dump_json())
    return info


def list_datasets() -> list[DatasetInfo]:
    out = []
    for meta in sorted(datasets_dir().glob("*.meta.json")):
        try:
            out.append(DatasetInfo.model_validate_json(meta.read_text()))
        except ValueError:
            continue
    return out


def get(name: str) -> tuple[DatasetInfo, Path] | None:
    if variable_name(name) != name or not _meta_path(name).exists():
        return None
    info = DatasetInfo.model_validate_json(_meta_path(name).read_text())
    return info, datasets_dir() / f"{name}{Path(info.filename).suffix.lower()}"


def delete(name: str) -> bool:
    found = get(name)
    if found is None:
        return False
    _, path = found
    path.unlink(missing_ok=True)
    _meta_path(name).unlink(missing_ok=True)
    return True


def _meta_path(name: str) -> Path:
    return datasets_dir() / f"{name}.meta.json"


def referenced(code: str, available: list[str]) -> list[str]:
    """Dataset names the code reads before (or without) binding them at module level.

    Errs toward loading: a missed dataset is a NameError, an extra one only costs a read.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    first_load: dict[str, tuple[int, int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            pos = (node.lineno, node.col_offset)
            first_load[node.id] = min(pos, first_load.get(node.id, pos))
    first_bind: dict[str, tuple[int, int]] = {}
    for name, pos in _module_bindings(tree.body):
        first_bind[name] = min(pos, first_bind.get(name, pos))
    return [n for n in available
            if n in first_load and (n not in first_bind or first_load[n] < first_bind[n])]


def _module_bindings(stmts):
    """(name, position) for names bound at module scope (not inside functions/classes)."""
    for stmt in stmts:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield stmt.name, (stmt.lineno, stmt.col_offset)
            continue
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for alias in stmt.names:
                yield (alias.asname or alias.name).split(".")[0], (stmt.lineno, stmt.col_offset)
            continue
        # the value is evaluated before the target is bound: place bindings at the statement end
        end = (stmt.end_lineno or stmt.lineno, stmt.end_col_offset or 0)
        for node in ast.walk(stmt):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                break
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                yield node.id, end
        for field in ("body", "orelse", "finalbody", "handlers"):
            yield from _module_bindings([s for s in getattr(stmt, field, []) if isinstance(s, ast.stmt)])


def resolve(names: list[str]) -> dict[str, dict[str, str]]:
    """{name: {path, format, filename}} for the worker to preload."""
    out = {}
    for name in names:
        if found := get(name):
            info, path = found
            out[name] = {"path": str(path), "format": info.format, "filename": info.filename}
    return out

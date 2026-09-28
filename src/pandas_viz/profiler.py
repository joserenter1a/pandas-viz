"""Summarize a DataFrame/Series into a JSON-safe FrameProfile, with bounded cost."""

import json

import pandas as pd

from .models import ColumnInfo, FrameProfile, RowExamples

SAMPLE_ROWS = 20
EXAMPLE_ROWS = 5
N_UNIQUE_MAX_ROWS = 1_000_000


def profile(obj: pd.DataFrame | pd.Series) -> FrameProfile:
    kind = "Series" if isinstance(obj, pd.Series) else "DataFrame"
    df = obj.to_frame(name=obj.name if obj.name is not None else 0) if kind == "Series" else obj
    rows, cols = df.shape

    nulls = df.isna().sum().tolist()
    columns = []
    for i, (name, dtype) in enumerate(zip(df.columns, df.dtypes)):
        n_unique = None
        if rows <= N_UNIQUE_MAX_ROWS:
            try:
                n_unique = int(df.iloc[:, i].nunique(dropna=True))
            except TypeError:  # unhashable values, e.g. lists
                pass
        columns.append(ColumnInfo(name=str(name), dtype=str(dtype), null_count=int(nulls[i]), n_unique=n_unique))

    head = _rows(df.head(SAMPLE_ROWS))
    index = [f"{n if n is not None else '(index)'}: {df.index.get_level_values(i).dtype}"
             for i, n in enumerate(df.index.names)]

    return FrameProfile(
        kind=kind,
        rows=rows,
        cols=cols,
        memory_bytes=int(df.memory_usage(index=True, deep=False).sum()),
        columns=columns,
        index=index,
        sample_columns=[str(c) for c in df.columns],
        sample=head["data"],
        sample_index=head["index"],
    )


def _rows(df: pd.DataFrame) -> dict:
    return json.loads(df.to_json(orient="split", date_format="iso", default_handler=str))


def examples(obj: pd.DataFrame | pd.Series, *, kind: str, label: str, total: int,
             column: str | None = None, highlight: list | None = None,
             limit: int = EXAMPLE_ROWS) -> RowExamples | None:
    """Up to ``limit`` rows of ``obj`` as a RowExamples, or None if there are none."""
    if total <= 0 or len(obj) == 0:
        return None
    df = obj.to_frame() if isinstance(obj, pd.Series) else obj
    payload = _rows(df.head(limit))
    return RowExamples(
        kind=kind, label=label, total=total, column=column,
        highlight=[str(h) for h in highlight or []],
        columns=[str(c) for c in df.columns], index=payload["index"], rows=payload["data"],
    )

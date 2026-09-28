"""Per-operation categories and enrichers (join stats, filter selectivity, group sizes)."""

from typing import Any

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_list_like

from .models import RowExamples, SchemaChange
from .profiler import EXAMPLE_ROWS, examples

LIMITS = {"head", "tail", "sample", "nlargest", "nsmallest"}  # dropping rows is the point
ROW_FILTERS = {"query", "dropna", "drop_duplicates", "head", "tail", "sample", "nlargest",
               "nsmallest", "filter"}

_CATEGORIES = {
    "source": {"DataFrame"},
    "filter": {"filter", "query", "dropna", "drop_duplicates", "loc", "iloc"},
    "limit": {"head", "tail", "sample", "nlargest", "nsmallest"},
    "projection": {"select", "column", "drop", "rename", "select_dtypes", "rename_axis"},
    "join": {"merge", "join", "concat"},
    "aggregate": {"agg", "aggregate", "pivot_table", "value_counts", "describe", "crosstab"},
    "sort": {"sort_values", "sort_index"},
    "reshape": {"melt", "pivot", "stack", "unstack", "explode", "set_index", "reset_index",
                "transpose", "to_frame", "get_dummies", "reindex"},
    "mutate": {"assign", "astype", "fillna", "apply", "map", "where", "mask", "replace", "copy",
               "convert_dtypes", "infer_objects", "to_datetime", "to_numeric", "isin"},
}
_OP_TO_CATEGORY = {op: cat for cat, names in _CATEGORIES.items() for op in names}

# Ops whose purpose is to change dtypes: a dtype change here is intended, not drift.
DTYPE_OPS = {"astype", "convert_dtypes", "infer_objects", "to_datetime", "to_numeric",
             "assign column", "loc assign", "iloc assign", "assign", "apply", "map"}


def category(op: str, rows_in: int | None, rows_out: int, change: SchemaChange | None) -> str:
    base = op.split(" ")[0]
    if base.startswith("read_"):
        return "source"
    if base in ("loc", "iloc", "filter") and rows_in is not None and rows_in == rows_out \
            and change and (change.removed or change.added):
        return "projection"
    return _OP_TO_CATEGORY.get(base, "other")


def dropped_examples(inp, out, mask=None) -> list[RowExamples]:
    """Example rows that ``inp`` had and ``out`` doesn't (row-subset operations only)."""
    total = len(inp) - len(out)
    if total <= 0:
        return []
    keep = _as_mask(mask, inp)
    if keep is not None:
        dropped = inp[~keep]
    elif inp.index.is_unique:
        dropped = inp[~inp.index.isin(out.index)]
    else:
        return []  # can't tell which of the duplicate labels survived
    ex = examples(dropped, kind="dropped", label="Dropped rows", total=total)
    return [ex] if ex else []


def _as_mask(mask, inp) -> np.ndarray | None:
    if isinstance(mask, tuple) and mask:  # .loc[rows, cols]
        mask = mask[0]
    if isinstance(mask, pd.Series) and is_bool_dtype(mask.dtype):
        if not mask.index.equals(inp.index):
            if not mask.index.is_unique:
                return None
            mask = mask.reindex(inp.index, fill_value=False)
        return mask.fillna(False).to_numpy(dtype=bool)
    if isinstance(mask, (np.ndarray, list)) and len(mask) == len(inp):
        arr = np.asarray(mask)
        return arr if arr.dtype == bool else None
    return None


def filter_details(rows_in: int, rows_out: int) -> dict[str, Any]:
    return {
        "rows_in": rows_in,
        "rows_out": rows_out,
        "rows_dropped": rows_in - rows_out,
        "pct_kept": round(100 * rows_out / rows_in, 2) if rows_in else None,
    }


def source_details(name: str, bound: dict) -> dict[str, Any]:
    path = bound.get("filepath_or_buffer", bound.get("path", bound.get("io")))
    return {"reader": name, "path": str(path) if isinstance(path, str) else None}


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _keys(df: pd.DataFrame, cols: list, use_index: bool) -> pd.Index | None:
    if use_index:
        return df.index
    if not cols or not all(isinstance(c, str) or not is_list_like(c) for c in cols):
        return None  # array-like keys: can't attribute to columns
    if any(c not in df.columns for c in cols):
        # a key may name an index level
        df = df.reset_index()
        if any(c not in df.columns for c in cols):
            return None
    if len(cols) == 1:
        return pd.Index(df[cols[0]])
    return pd.MultiIndex.from_frame(df[cols])


def _key_nulls(df: pd.DataFrame, cols: list, use_index: bool) -> int:
    try:
        if use_index:
            return int(pd.Series(df.index.isna() if df.index.nlevels == 1 else False).sum())
        return int(df[cols].isna().any(axis=1).sum())
    except (KeyError, TypeError, NotImplementedError):
        return 0


def join_stats(left: pd.DataFrame, right: pd.DataFrame, left_cols: list, right_cols: list,
               left_index: bool, right_index: bool, how: str, result: pd.DataFrame,
               suffixes: tuple[str, str]) -> tuple[dict[str, Any], list[RowExamples]]:
    details: dict[str, Any] = {
        "how": how,
        "left_on": [str(c) for c in left_cols] or (["(index)"] if left_index else []),
        "right_on": [str(c) for c in right_cols] or (["(index)"] if right_index else []),
        "rows_left": len(left),
        "rows_right": len(right),
        "rows_out": len(result),
        "explosion_factor": round(len(result) / len(left), 4) if len(left) else None,
    }
    lk, rk = _keys(left, left_cols, left_index), _keys(right, right_cols, right_index)
    if lk is not None and rk is not None:
        left_unique, right_unique = lk.is_unique, rk.is_unique
        cardinality = f"{'1' if left_unique else 'm'}:{'1' if right_unique else 'm'}"
        left_matched = lk.isin(rk)
        right_matched = rk.isin(lk)
        validate, passes = suggest_validate(left_unique, right_unique, how)
        details.update(
            cardinality=cardinality,
            suggested_validate=validate,
            validate_passes=passes,
            left_matched_rows=int(left_matched.sum()),
            left_only_rows=int((~left_matched).sum()),
            right_matched_rows=int(right_matched.sum()),
            right_only_rows=int((~right_matched).sum()),
            left_duplicate_keys=int(lk.duplicated().sum()),
            right_duplicate_keys=int(rk.duplicated().sum()),
            left_null_keys=_key_nulls(left, left_cols, left_index),
            right_null_keys=_key_nulls(right, right_cols, right_index),
        )
        found = _join_examples(left, right, left_cols, right_cols, lk, rk, left_matched,
                               right_matched, details)
    else:
        found = []
    mismatches = []
    for lc, rc in zip(left_cols, right_cols):
        try:
            ld, rd = str(left[lc].dtype), str(right[rc].dtype)
        except KeyError:
            continue
        if ld != rd:
            mismatches.append({"left": str(lc), "right": str(rc), "left_dtype": ld, "right_dtype": rd})
    details["key_dtype_mismatches"] = mismatches
    inputs = set(map(str, left.columns)) | set(map(str, right.columns))
    details["suffix_collisions"] = [
        str(c) for c in result.columns
        if str(c) not in inputs and any(s and str(c).endswith(s) for s in suffixes)
    ]
    return details, found


def suggest_validate(left_unique: bool, right_unique: bool, how: str) -> tuple[str, bool]:
    """The ``validate=`` a merge *should* have, and whether the traced data satisfies it.

    Lookup-style joins should have unique keys on the right ("m:1"); the observed
    cardinality is not suggested when it is the bug (duplicate lookup keys).
    """
    if right_unique:
        return "m:1", True
    if left_unique and how in ("right", "outer"):
        return "1:m", True
    return "m:1", False


def _join_examples(left, right, left_cols, right_cols, lk, rk, left_matched, right_matched,
                   d: dict) -> list[RowExamples]:
    out: list[RowExamples | None] = []
    for side, frame, cols, keys, matched in (("left", left, left_cols, lk, left_matched),
                                             ("right", right, right_cols, rk, right_matched)):
        unmatched = np.flatnonzero(~np.asarray(matched))
        out.append(examples(frame.iloc[unmatched[:EXAMPLE_ROWS]], kind=f"unmatched_{side}",
                            label=f"{side.title()} rows with no match", total=len(unmatched),
                            highlight=cols))
        # Duplicate keys on the lookup (right) side multiply rows; on the left side they are
        # normal (many orders per user) unless both sides have them (m:m).
        if not keys.is_unique and (side == "right" or d.get("cardinality") == "m:m"):
            dup = np.flatnonzero(keys.duplicated(keep=False))
            rows = frame.iloc[dup]
            rows = rows.sort_values(cols, kind="stable") if cols else rows.sort_index(kind="stable")
            out.append(examples(rows, kind=f"duplicate_keys_{side}",
                                label=f"{side.title()} rows sharing a key", total=len(dup),
                                highlight=cols, limit=EXAMPLE_ROWS + 1))
        if d.get(f"{side}_null_keys") and cols:
            nulls = frame[frame[cols].isna().any(axis=1)]
            out.append(examples(nulls, kind=f"null_keys_{side}", label=f"{side.title()} rows with null keys",
                                total=len(nulls), highlight=cols))
    return [e for e in out if e]


def merge_details(left, right, bound: dict, result) -> tuple[dict[str, Any], list[RowExamples]]:
    if isinstance(right, pd.Series):
        right = right.to_frame()
    if not isinstance(left, pd.DataFrame) or not isinstance(right, pd.DataFrame):
        return {}, []
    on = _as_list(bound.get("on"))
    left_on = _as_list(bound.get("left_on")) or on
    right_on = _as_list(bound.get("right_on")) or on
    left_index, right_index = bool(bound.get("left_index")), bool(bound.get("right_index"))
    how = bound.get("how", "inner")
    if how == "cross":
        return {"how": "cross", "rows_left": len(left), "rows_right": len(right),
                "rows_out": len(result)}, []
    if not left_on and not right_on and not left_index and not right_index:
        left_on = right_on = [c for c in left.columns if c in set(right.columns)]
    suffixes = tuple(bound.get("suffixes") or ("_x", "_y"))
    return join_stats(left, right, left_on if not left_index else [],
                      right_on if not right_index else [], left_index, right_index, how, result,
                      suffixes)


def join_details(left, other, bound: dict, result) -> tuple[dict[str, Any], list[RowExamples]]:
    if isinstance(other, pd.Series):
        other = other.to_frame()
    if not isinstance(left, pd.DataFrame) or not isinstance(other, pd.DataFrame):
        return {}, []
    on = _as_list(bound.get("on"))
    suffixes = (bound.get("lsuffix", ""), bound.get("rsuffix", ""))
    return join_stats(left, other, on, [], not on, True, bound.get("how", "left"), result, suffixes)


def concat_details(objs: list, bound: dict, result) -> dict[str, Any]:
    frames = [o for o in objs if isinstance(o, (pd.DataFrame, pd.Series))]
    axis = bound.get("axis", 0)
    details: dict[str, Any] = {
        "axis": axis,
        "inputs": len(frames),
        "rows_per_input": [len(f) for f in frames],
        "rows_out": len(result),
    }
    if axis in (0, "index"):
        cols = [set(map(str, f.columns)) if isinstance(f, pd.DataFrame) else {str(f.name)}
                for f in frames]
        union = set().union(*cols) if cols else set()
        details["columns_not_in_all_inputs"] = sorted(union - set.intersection(*cols)) if cols else []
    return details


def group_details(gb) -> dict[str, Any]:
    try:
        sizes = gb.size()
        if isinstance(sizes, pd.DataFrame):
            sizes = sizes["size"]
        return {
            "n_groups": int(gb.ngroups),
            "group_size_min": int(sizes.min()) if len(sizes) else 0,
            "group_size_median": float(sizes.median()) if len(sizes) else 0,
            "group_size_max": int(sizes.max()) if len(sizes) else 0,
            "group_size_histogram": _histogram(sizes),
        }
    except Exception:  # exotic groupers; stats are best-effort
        return {}


def _histogram(values: pd.Series, bins: int = 10) -> list[dict[str, Any]]:
    if values.empty:
        return []
    lo, hi = int(values.min()), int(values.max())
    if lo == hi:
        return [{"start": lo, "end": hi, "count": int(len(values))}]
    counts = pd.cut(values, bins=min(bins, hi - lo + 1), include_lowest=True).value_counts(sort=False)
    return [{"start": round(float(iv.left), 2), "end": round(float(iv.right), 2), "count": int(c)}
            for iv, c in counts.items()]

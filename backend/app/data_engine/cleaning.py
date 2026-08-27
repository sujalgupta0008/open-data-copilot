import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple
import re

def get_version_path(dataset_id: str, version_number: int, ext: str, storage_base: str, user_id: str):
    import os
    dir_path = os.path.join(storage_base, user_id, dataset_id)
    os.makedirs(dir_path, exist_ok=True)
    return os.path.join(dir_path, f"v{version_number}{ext}")

def save_dataframe(df: pd.DataFrame, path: str, file_type: str):
    import os
    ext = os.path.splitext(path)[1].lower()
    if ext in [".xlsx", ".xls"]:
        df.to_excel(path, index=False)
    elif ext == ".parquet":
        df.to_parquet(path, index=False)
    elif ext == ".json":
        df.to_json(path, orient="records", indent=2)
    else:
        df.to_csv(path, index=False)

def _is_effectively_numeric(s: pd.Series) -> bool:
    """Return True if series is numeric dtype or can be safely coerced with at least one valid number."""
    if pd.api.types.is_numeric_dtype(s):
        return True
    # try to coerce a small sample to avoid expensive full conversion on large columns
    try:
        coerced = pd.to_numeric(s.dropna().head(20), errors="coerce")
        if coerced.notna().any():
            # at least some values look numeric
            full = pd.to_numeric(s, errors="coerce")
            return full.notna().any()
    except Exception:
        pass
    return False

def _safe_quantile(s: pd.Series, q: float) -> float | None:
    """Return quantile or None if not computable (all-NaN, empty)."""
    try:
        if s.isnull().all() or len(s.dropna()) == 0:
            return None
        # ensure numeric for quantile; coerce if needed
        if not pd.api.types.is_numeric_dtype(s):
            s = pd.to_numeric(s, errors="coerce")
            if s.isnull().all():
                return None
        val = s.quantile(q)
        if pd.isna(val):
            return None
        return float(val)
    except Exception:
        return None

def apply_missing_value(df: pd.DataFrame, column: str, method: str, custom_value: Any = None) -> Tuple[pd.DataFrame, Dict]:
    before_missing = int(df[column].isnull().sum()) if column in df.columns else int(df.isnull().sum().sum())
    before_rows = len(df)
    new_df = df.copy()
    affected = 0
    if method == "drop_rows":
        # if column specified, drop rows where that column is null, else drop any null
        if column and column in df.columns:
            affected = int(new_df[column].isnull().sum())
            new_df = new_df.dropna(subset=[column])
        else:
            affected = int(new_df.isnull().any(axis=1).sum())
            new_df = new_df.dropna()
    elif method == "fill_mean":
        if column in df.columns:
            if not _is_effectively_numeric(new_df[column]):
                raise ValueError(f"Cannot apply fill_mean to non-numeric column '{column}'")
            val = new_df[column].mean(skipna=True)
            if pd.isna(val):
                # all-NaN column: nothing to fill with
                affected = 0
            else:
                affected = int(new_df[column].isnull().sum())
                new_df[column] = new_df[column].fillna(val)
    elif method == "fill_median":
        if column in df.columns:
            if not _is_effectively_numeric(new_df[column]):
                raise ValueError(f"Cannot apply fill_median to non-numeric column '{column}'")
            val = new_df[column].median(skipna=True)
            if pd.isna(val):
                affected = 0
            else:
                affected = int(new_df[column].isnull().sum())
                new_df[column] = new_df[column].fillna(val)
    elif method == "fill_mode":
        if column in df.columns:
            mode = new_df[column].mode(dropna=True)
            val = mode.iloc[0] if not mode.empty else None
            affected = int(new_df[column].isnull().sum())
            if val is not None:
                new_df[column] = new_df[column].fillna(val)
    elif method == "forward_fill":
        if column and column in df.columns:
            affected = int(new_df[column].isnull().sum())
            new_df[column] = new_df[column].ffill()
        else:
            affected = int(new_df.isnull().sum().sum())
            new_df = new_df.ffill()
    elif method == "backward_fill":
        if column and column in df.columns:
            affected = int(new_df[column].isnull().sum())
            new_df[column] = new_df[column].bfill()
        else:
            affected = int(new_df.isnull().sum().sum())
            new_df = new_df.bfill()
    elif method == "custom_value":
        if column in df.columns:
            affected = int(new_df[column].isnull().sum())
            new_df[column] = new_df[column].fillna(custom_value)
        else:
            affected = int(new_df.isnull().sum().sum())
            new_df = new_df.fillna(custom_value)
    else:
        raise ValueError(f"Unknown missing method {method}")
    after_missing = int(new_df[column].isnull().sum()) if column in new_df.columns else int(new_df.isnull().sum().sum())
    return new_df, {"before_missing": before_missing, "after_missing": after_missing, "affected_rows": affected, "before_rows": before_rows, "after_rows": len(new_df)}

def remove_duplicates(df: pd.DataFrame, subset: List[str] = None) -> Tuple[pd.DataFrame, Dict]:
    before = len(df)
    dup_count = int(df.duplicated(subset=subset).sum())
    new_df = df.drop_duplicates(subset=subset)
    after = len(new_df)
    return new_df, {"duplicates_found": dup_count, "before_rows": before, "after_rows": after, "removed": before - after}

def column_operations(df: pd.DataFrame, operation: str, **kwargs) -> Tuple[pd.DataFrame, Dict]:
    new_df = df.copy()
    if operation == "rename":
        old = kwargs.get("old_name")
        new = kwargs.get("new_name")
        if old in new_df.columns:
            new_df = new_df.rename(columns={old: new})
        return new_df, {"renamed": f"{old} -> {new}"}
    elif operation == "remove":
        col = kwargs.get("column")
        if col in new_df.columns:
            new_df = new_df.drop(columns=[col])
        return new_df, {"removed": col}
    elif operation == "reorder":
        order = kwargs.get("order")  # list
        if order:
            # validate all columns present
            existing = [c for c in order if c in new_df.columns]
            remaining = [c for c in new_df.columns if c not in existing]
            new_df = new_df[existing + remaining]
        return new_df, {"new_order": list(new_df.columns)}
    elif operation == "change_type":
        col = kwargs.get("column")
        dtype = kwargs.get("dtype")
        if col in new_df.columns:
            try:
                if dtype == "numeric":
                    new_df[col] = pd.to_numeric(new_df[col], errors="coerce")
                elif dtype == "datetime":
                    new_df[col] = pd.to_datetime(new_df[col], errors="coerce")
                elif dtype == "string":
                    new_df[col] = new_df[col].astype(str)
                elif dtype == "int":
                    new_df[col] = pd.to_numeric(new_df[col], errors="coerce").astype("Int64")
                elif dtype == "float":
                    new_df[col] = pd.to_numeric(new_df[col], errors="coerce").astype(float)
                else:
                    new_df[col] = new_df[col].astype(dtype)
            except Exception as e:
                raise ValueError(f"Failed to convert {col} to {dtype}: {e}")
        return new_df, {"converted": f"{col} -> {dtype}"}
    else:
        raise ValueError(f"Unknown column op {operation}")

def text_cleaning(df: pd.DataFrame, column: str, operation: str, **kwargs) -> Tuple[pd.DataFrame, Dict]:
    new_df = df.copy()
    if column not in new_df.columns:
        raise ValueError(f"Column {column} not found")
    s = new_df[column].astype(object)
    before_unique = int(s.nunique(dropna=False))
    affected = 0
    if operation == "trim":
        new_df[column] = new_df[column].astype(str).str.strip()
        # preserve nulls? If original null, str conversion gives 'nan' -> restore
        mask_null = df[column].isnull()
        new_df.loc[mask_null, column] = None
        affected = int((df[column].astype(str) != new_df[column].astype(str)).sum())
    elif operation == "lowercase":
        new_df[column] = new_df[column].astype(str).str.lower()
        mask_null = df[column].isnull()
        new_df.loc[mask_null, column] = None
        affected = int((df[column].astype(str).str.lower() != df[column].astype(str)).sum()) if not mask_null.all() else 0
    elif operation == "uppercase":
        new_df[column] = new_df[column].astype(str).str.upper()
        mask_null = df[column].isnull()
        new_df.loc[mask_null, column] = None
    elif operation == "title_case":
        new_df[column] = new_df[column].astype(str).str.title()
        mask_null = df[column].isnull()
        new_df.loc[mask_null, column] = None
    elif operation == "find_replace":
        find = kwargs.get("find")
        replace = kwargs.get("replace", "")
        regex = kwargs.get("regex", False)
        if regex:
            new_df[column] = new_df[column].astype(str).str.replace(find, replace, regex=True)
        else:
            new_df[column] = new_df[column].astype(str).str.replace(find, replace, regex=False)
        mask_null = df[column].isnull()
        new_df.loc[mask_null, column] = None
    elif operation == "standardize":
        mapping = kwargs.get("mapping")  # dict e.g., {" indigo ": "IndiGo", "indigo": "IndiGo"}
        if mapping:
            # apply mapping after stripping
            def std(v):
                if pd.isna(v):
                    return v
                vs = str(v).strip()
                # case-insensitive lookup
                for k, mv in mapping.items():
                    if vs.lower() == str(k).strip().lower():
                        return mv
                return vs
            new_df[column] = new_df[column].apply(std)
    else:
        raise ValueError(f"Unknown text op {operation}")
    after_unique = int(new_df[column].nunique(dropna=False))
    return new_df, {"before_unique": before_unique, "after_unique": after_unique, "affected_rows": affected if affected else int((df[column].astype(str)!=new_df[column].astype(str)).sum())}

def numeric_cleaning(df: pd.DataFrame, column: str, operation: str, **kwargs) -> Tuple[pd.DataFrame, Dict]:
    # Guard: exclude identifier columns from winsorization/IQR operations
    try:
        from app.data_engine.profiler import _is_identifier_column
        if column in df.columns and _is_identifier_column(column, df[column], len(df)):
            if operation in ["handle_outliers", "winsorize"]:
                return df.copy(), {"outliers": 0, "skipped": f"identifier column '{column}' excluded from IQR/winsorization", "lower": None, "upper": None}
    except Exception:
        pass
    new_df = df.copy()
    if column not in new_df.columns:
        raise ValueError(f"Column {column} not found")
    if operation == "convert_to_numeric":
        before_invalid = int(pd.to_numeric(df[column], errors="coerce").isnull().sum() - df[column].isnull().sum())
        new_df[column] = pd.to_numeric(new_df[column], errors="coerce")
        after_valid = int(new_df[column].notnull().sum())
        invalid_left = int(new_df[column].isnull().sum())
        return new_df, {"converted": column, "before_invalid": max(0, before_invalid), "after_valid": after_valid, "invalid_remaining": invalid_left}
    elif operation == "handle_outliers":
        method = kwargs.get("method", "winsorize")  # winsorize or remove
        q1 = _safe_quantile(new_df[column], 0.25)
        q3 = _safe_quantile(new_df[column], 0.75)
        if q1 is None or q3 is None:
            return new_df, {"outliers": 0, "skipped": "empty/all-NaN or non-numeric column", "lower": None, "upper": None}
        iqr = q3 - q1
        if pd.isna(iqr) or iqr == 0:
            # constant or single-value column -> no outliers
            return new_df, {"outliers": 0, "skipped": "IQR is 0 or NaN", "lower": float(q1), "upper": float(q3)}
        lower = q1 - 1.5*iqr
        upper = q3 + 1.5*iqr
        if pd.isna(lower) or pd.isna(upper):
            return new_df, {"outliers": 0, "skipped": "bounds are NaN", "lower": None, "upper": None}
        # coerce column to numeric for comparison if needed
        series_for_outliers = pd.to_numeric(new_df[column], errors="coerce") if not pd.api.types.is_numeric_dtype(new_df[column]) else new_df[column]
        outliers = ((series_for_outliers < lower) | (series_for_outliers > upper)).sum()
        if method == "remove":
            before = len(new_df)
            mask_keep = (series_for_outliers >= lower) & (series_for_outliers <= upper) | new_df[column].isnull()
            new_df = new_df[mask_keep]
            after = len(new_df)
            return new_df, {"outliers": int(outliers), "removed": before-after, "lower": float(lower), "upper": float(upper)}
        elif method == "winsorize":
            new_df[column] = pd.to_numeric(new_df[column], errors="coerce").clip(lower=lower, upper=upper) if not pd.api.types.is_numeric_dtype(new_df[column]) else new_df[column].clip(lower=lower, upper=upper)
            return new_df, {"outliers": int(outliers), "winsorized": int(outliers), "lower": float(lower), "upper": float(upper)}
        elif method == "flag":
            new_df[f"{column}_is_outlier"] = ((series_for_outliers < lower) | (series_for_outliers > upper))
            return new_df, {"outliers": int(outliers), "flagged_column": f"{column}_is_outlier"}
    elif operation == "winsorize":
        lower_p = kwargs.get("lower_percentile", 0.01)
        upper_p = kwargs.get("upper_percentile", 0.99)
        lower = _safe_quantile(new_df[column], lower_p)
        upper = _safe_quantile(new_df[column], upper_p)
        if lower is None or upper is None:
            return new_df, {"lower": None, "upper": None, "winsorized": False, "skipped": "empty/all-NaN column"}
        if pd.isna(lower) or pd.isna(upper) or lower == upper:
            return new_df, {"lower": float(lower) if lower is not None else None, "upper": float(upper) if upper is not None else None, "winsorized": False, "skipped": "bounds invalid or equal"}
        new_df[column] = pd.to_numeric(new_df[column], errors="coerce").clip(lower=lower, upper=upper) if not pd.api.types.is_numeric_dtype(new_df[column]) else new_df[column].clip(lower=lower, upper=upper)
        return new_df, {"lower": float(lower), "upper": float(upper), "winsorized": True}
    else:
        raise ValueError(f"Unknown numeric op {operation}")

def date_cleaning(df: pd.DataFrame, column: str, operation: str, **kwargs) -> Tuple[pd.DataFrame, Dict]:
    new_df = df.copy()
    if column not in new_df.columns:
        raise ValueError(f"Column {column} not found")
    if operation == "convert_to_datetime":
        fmt = kwargs.get("format")
        before_invalid = int(pd.to_datetime(df[column], errors="coerce").isnull().sum() - df[column].isnull().sum())
        if fmt:
            new_df[column] = pd.to_datetime(new_df[column], format=fmt, errors="coerce")
        else:
            new_df[column] = pd.to_datetime(new_df[column], errors="coerce")
        after_invalid = int(new_df[column].isnull().sum() - df[column].isnull().sum())
        return new_df, {"before_invalid_dates": max(0, before_invalid), "after_invalid_dates": max(0, after_invalid), "converted": column}
    elif operation == "standardize_format":
        fmt = kwargs.get("output_format", "%Y-%m-%d")
        # first ensure datetime
        s = pd.to_datetime(new_df[column], errors="coerce")
        invalid = int(s.isnull().sum() - df[column].isnull().sum())
        new_df[column] = s.dt.strftime(fmt)
        # restore nulls where parse failed? keep as null
        new_df.loc[s.isnull() & df[column].notnull(), column] = None
        return new_df, {"standardized": column, "format": fmt, "invalid_dates": invalid}
    elif operation == "identify_invalid":
        s = pd.to_datetime(new_df[column], errors="coerce")
        invalid_mask = s.isnull() & df[column].notnull()
        invalid_count = int(invalid_mask.sum())
        invalid_rows = df[invalid_mask].head(10).to_dict(orient="records")
        return new_df, {"invalid_count": invalid_count, "invalid_rows": invalid_rows}
    else:
        raise ValueError(f"Unknown date op {operation}")

def row_filtering(df: pd.DataFrame, operation: str, **kwargs) -> Tuple[pd.DataFrame, Dict]:
    new_df = df.copy()
    before = len(new_df)
    if operation == "filter_by_value":
        column = kwargs.get("column")
        value = kwargs.get("value")
        keep = kwargs.get("keep", True)  # if False, remove matching
        if column not in new_df.columns:
            raise ValueError(f"Column {column} not found")
        if keep:
            filtered = new_df[new_df[column].astype(str) == str(value)]
        else:
            filtered = new_df[new_df[column].astype(str) != str(value)]
        # For preview we don't auto apply removal? But this function handles removal
        # If keep is True, this is "keep only matching" -> others removed
        # If keep is False, remove matching
        new_df = filtered if kwargs.get("apply", True) else df  # ambiguous
        # Actually we want to support removing filtered rows: so caller specifies filter then remove
        # Simplify: if keep=False we removed rows equal value
        # For general, just filter
        after = len(new_df)
        return new_df, {"before": before, "after": after, "removed": before - after, "filter": f"{column} == {value}"}
    elif operation == "filter_by_numeric_range":
        column = kwargs.get("column")
        min_val = kwargs.get("min")
        max_val = kwargs.get("max")
        remove = kwargs.get("remove", True)
        mask = pd.Series([True]*len(new_df))
        if min_val is not None:
            mask = mask & (pd.to_numeric(new_df[column], errors="coerce") >= float(min_val))
        if max_val is not None:
            mask = mask & (pd.to_numeric(new_df[column], errors="coerce") <= float(max_val))
        if remove:
            # remove rows outside range? Or remove matched?
            # Interpret: filter by numeric range then remove filtered rows = keep outside?
            # We'll implement as: if remove=True, drop rows that match range
            new_df = new_df[~mask]
        else:
            new_df = new_df[mask]
        after = len(new_df)
        return new_df, {"before": before, "after": after, "removed": before - after}
    elif operation == "filter_by_date":
        column = kwargs.get("column")
        start = kwargs.get("start")
        end = kwargs.get("end")
        s = pd.to_datetime(new_df[column], errors="coerce")
        mask = pd.Series([True]*len(new_df))
        if start:
            mask = mask & (s >= pd.to_datetime(start))
        if end:
            mask = mask & (s <= pd.to_datetime(end))
        new_df = new_df[mask]
        after = len(new_df)
        return new_df, {"before": before, "after": after, "filtered": after}
    elif operation == "remove_filtered":
        # expects indices to remove
        indices = kwargs.get("indices", [])
        new_df = new_df.drop(index=indices, errors="ignore")
        after = len(new_df)
        return new_df, {"before": before, "after": after, "removed": before - after}
    else:
        raise ValueError(f"Unknown row filter op {operation}")

def apply_operation(df: pd.DataFrame, op: str, params: Dict) -> Tuple[pd.DataFrame, Dict]:
    # Unified dispatch - avoid duplicate kwargs
    if op == "missing":
        return apply_missing_value(df, params.get("column"), params.get("method"), params.get("custom_value"))
    elif op == "remove_duplicates":
        return remove_duplicates(df, params.get("subset"))
    elif op == "column":
        sub = params.get("sub_operation")
        # filter out sub_operation to avoid duplicate, but keep other keys for operation
        filtered = {k:v for k,v in params.items() if k != "sub_operation"}
        return column_operations(df, sub, **filtered)
    elif op == "text":
        col = params.get("column")
        sub = params.get("sub_operation")
        filtered = {k:v for k,v in params.items() if k not in ("column","sub_operation")}
        return text_cleaning(df, col, sub, **filtered)
    elif op == "numeric":
        col = params.get("column")
        sub = params.get("sub_operation")
        filtered = {k:v for k,v in params.items() if k not in ("column","sub_operation")}
        return numeric_cleaning(df, col, sub, **filtered)
    elif op == "date":
        col = params.get("column")
        sub = params.get("sub_operation")
        filtered = {k:v for k,v in params.items() if k not in ("column","sub_operation")}
        return date_cleaning(df, col, sub, **filtered)
    elif op == "row_filter":
        sub = params.get("sub_operation")
        filtered = {k:v for k,v in params.items() if k != "sub_operation"}
        return row_filtering(df, sub, **filtered)
    else:
        raise ValueError(f"Unknown operation {op}")

def preview_operation(df: pd.DataFrame, op: str, params: Dict, n: int = 5) -> Dict:
    new_df, stats = apply_operation(df, op, params)
    # generate preview diff: show changed rows sample
    # For simplicity, show before and after head
    before_head = df.head(n).replace({np.nan: None}).to_dict(orient="records")
    after_head = new_df.head(n).replace({np.nan: None}).to_dict(orient="records")
    return {"stats": stats, "before_rows": before_head, "after_rows": after_head, "before_shape": df.shape, "after_shape": new_df.shape}

def compute_diff_stats(before_df: pd.DataFrame, after_df: pd.DataFrame) -> Dict:
    before_rows, before_cols = before_df.shape
    after_rows, after_cols = after_df.shape
    before_missing = int(before_df.isnull().sum().sum())
    after_missing = int(after_df.isnull().sum().sum())
    before_dup = int(before_df.duplicated().sum())
    after_dup = int(after_df.duplicated().sum())
    # dtypes
    before_dtypes = {c: str(t) for c, t in before_df.dtypes.items()}
    after_dtypes = {c: str(t) for c, t in after_df.dtypes.items()}
    dtype_changes = {c: {"before": before_dtypes.get(c), "after": after_dtypes.get(c)} for c in set(list(before_dtypes.keys())+list(after_dtypes.keys())) if before_dtypes.get(c)!=after_dtypes.get(c)}
    # unique values for categorical sample
    unique_changes = {}
    for col in before_df.columns:
        if col in after_df.columns and before_df[col].dtype == object:
            bu = before_df[col].nunique(dropna=False)
            au = after_df[col].nunique(dropna=False)
            if bu != au:
                unique_changes[col] = {"before_unique": int(bu), "after_unique": int(au)}
    return {
        "rows": {"before": before_rows, "after": after_rows, "delta": after_rows - before_rows},
        "columns": {"before": before_cols, "after": after_cols, "delta": after_cols - before_cols},
        "missing_cells": {"before": before_missing, "after": after_missing, "delta": after_missing - before_missing},
        "duplicates": {"before": before_dup, "after": after_dup, "delta": after_dup - before_dup},
        "dtype_changes": dtype_changes,
        "unique_changes": unique_changes
    }

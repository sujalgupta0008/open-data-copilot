import pandas as pd
import numpy as np
from typing import List, Dict, Any, Tuple
import os
import re
import datetime as dt
import warnings
import time

# PERFORMANCE: In-memory LRU/dict cache for dataset metadata & DataFrames
# Caches DataFrames by storage_path + mtime to avoid re-reading CSV on every Copilot query
_DF_CACHE: Dict[str, tuple] = {}
_DF_CACHE_TTL = 300

def _get_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except:
        return 0.0

IDENTIFIER_REGEX = re.compile(r'(?i).*(id|code|key|account|number|no|uuid|hash).*')

def load_dataframe(storage_path: str) -> pd.DataFrame:
    # PERFORMANCE: LRU cache — avoid re-reading CSV on every query (saves ~2s)
    try:
        mtime = _get_mtime(storage_path)
        key = os.path.abspath(storage_path)
        if key in _DF_CACHE:
            cm, cdf, ts = _DF_CACHE[key]
            if cm == mtime and (time.time() - ts) < _DF_CACHE_TTL:
                return cdf.copy()
    except:
        pass
    ext = os.path.splitext(storage_path)[1].lower()
    if ext == ".csv":
        df = pd.read_csv(storage_path)
    elif ext in [".xlsx", ".xls"]:
        df = pd.read_excel(storage_path)
    elif ext == ".json":
        df = pd.read_json(storage_path)
    elif ext == ".parquet":
        df = pd.read_parquet(storage_path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")
    try:
        if len(_DF_CACHE) >= 16:
            oldest = min(_DF_CACHE, key=lambda k: _DF_CACHE[k][2])
            _DF_CACHE.pop(oldest, None)
        _DF_CACHE[key] = (mtime, df.copy(), time.time())
    except:
        pass
    return df

def robust_datetime_parse(series: pd.Series) -> Dict[str, Any]:
    """
    Robust datetime parsing: handle Unix timestamps, ISO 8601, mixed strings, timezone-aware.
    Returns dict with parse_success_rate, min_date, max_date, invalid_date_count, parsed series
    PERFORMANCE: for large series (>2000 rows) we sample 1000 rows for bulk parsing and skip
    the expensive element-wise fallback, avoiding 30s+ stalls on historical_data-style datasets
    that caused the Copilot 30s timeout (Image 1).
    """
    n = len(series)
    if n == 0:
        return {"parse_success_rate": 0.0, "min_date": None, "max_date": None, "invalid_date_count": 0, "parsed": pd.Series(dtype='datetime64[ns]')}
    # PERFORMANCE: sampling for very large series — keep full length for final parsed length, but evaluate success on sample
    _LARGE_N = 2000
    _SAMPLE_N = 1000
    is_large = n > _LARGE_N
    # Drop nulls for parsing evaluation
    non_null = series.dropna()
    non_null_count = len(non_null)
    if non_null_count == 0:
        return {"parse_success_rate": 0.0, "min_date": None, "max_date": None, "invalid_date_count": 0, "parsed": pd.Series([pd.NaT]*n)}

    # Try to detect Unix timestamps: numeric with large values
    parsed = None
    invalid = 0
    success_rate = 0.0
    min_date = None
    max_date = None

    # Strategy 1: Unix timestamp numeric detection
    try:
        numeric = pd.to_numeric(series, errors='coerce')
        # If majority convertible to numeric and values look like timestamps (1e9 to 2e9 seconds or 1e12 to 2e13 ms)
        numeric_valid = numeric.dropna()
        if len(numeric_valid) > 0 and numeric_valid.notna().mean() > 0.5:
            # Check ranges: seconds 946684800 (2000) to 4102444800 (2100); ms 946684800000 to 4102444800000
            vals = numeric_valid.astype(float)
            # Heuristic: if median > 1e12 => ms, elif >1e9 => seconds
            median_val = float(vals.median())
            if 1e9 <= median_val <= 4102444800:
                # seconds
                try:
                    parsed_ts = pd.to_datetime(vals, unit='s', errors='coerce', utc=True)
                    # Convert back to series alignment
                    parsed = pd.to_datetime(numeric, unit='s', errors='coerce', utc=True)
                    # Validate success
                    success_rate = float(parsed.notna().sum() / n)
                    if success_rate > 0.5:
                        valid = parsed.dropna()
                        if not valid.empty:
                            min_date = str(valid.min().isoformat())
                            max_date = str(valid.max().isoformat())
                        invalid = int(parsed.isna().sum() - series.isna().sum())
                        return {"parse_success_rate": round(success_rate*100,1), "min_date": min_date, "max_date": max_date, "invalid_date_count": max(0, invalid), "parsed": parsed}
                except Exception:
                    pass
            elif 1e12 <= median_val <= 4102444800000:
                try:
                    parsed = pd.to_datetime(numeric, unit='ms', errors='coerce', utc=True)
                    success_rate = float(parsed.notna().sum() / n)
                    if success_rate > 0.5:
                        valid = parsed.dropna()
                        if not valid.empty:
                            min_date = str(valid.min().isoformat())
                            max_date = str(valid.max().isoformat())
                        invalid = int(parsed.isna().sum() - series.isna().sum())
                        return {"parse_success_rate": round(success_rate*100,1), "min_date": min_date, "max_date": max_date, "invalid_date_count": max(0, invalid), "parsed": parsed}
                except Exception:
                    pass
    except Exception:
        pass

    # Guard: purely numeric columns that are not unix timestamps should not be treated as datetime (prevents price-like measures being misclassified)
    if pd.api.types.is_numeric_dtype(series):
        # Already handled unix timestamps above; if we reach here, not a timestamp -> not datetime
        return {"parse_success_rate": 0.0, "min_date": None, "max_date": None, "invalid_date_count": int(non_null_count), "parsed": pd.Series([pd.NaT]*n)}

    # Strategy 2: Generic ISO 8601 / mixed strings / timezone-aware via pd.to_datetime with utc (only for object/string)
    # PERFORMANCE: for large series, evaluate on a deterministic 1000-row sample to avoid O(n) stalls
    _eval_series = series
    _eval_non_null_count = non_null_count
    if is_large and non_null_count > _SAMPLE_N:
        # Use first _SAMPLE_N non-nulls for the heavy parsing probe; deterministic and fast
        _eval_series = non_null.head(_SAMPLE_N)
        _eval_non_null_count = len(_eval_series)
    # Try both utc=True and utc=False to handle date-only strings
    parsed = None
    best_success = 0
    best_parsed = None
    for use_utc in [True, False]:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=UserWarning)
                p = pd.to_datetime(_eval_series, errors='coerce', utc=use_utc, format='mixed')
            succ = int(p.notna().sum())
            if succ > best_success:
                best_success = succ
                best_parsed = p
        except Exception:
            continue
    # Fallback for mixed timezones + date-only: element-wise parsing often succeeds where bulk fails
    # Skip this expensive fallback for large series — sample already representative; avoids 15s+ on 50k rows
    if not is_large and best_success < _eval_non_null_count:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=UserWarning)
                elem_parsed = _eval_series.apply(lambda x: pd.to_datetime(x, errors='coerce', utc=True, format='mixed') if pd.notna(x) else pd.NaT)
                # elem_parsed may be object dtype with Timestamps; convert to Series with datetime
                elem_parsed = pd.to_datetime(elem_parsed, errors='coerce', utc=True, format='mixed')
            succ_elem = int(elem_parsed.notna().sum())
            if succ_elem > best_success:
                best_success = succ_elem
                best_parsed = elem_parsed
        except Exception:
            pass
    # For large series we estimated success on sample; extrapolate to full and build a lightweight parsed proxy
    if is_large:
        # Estimate success_rate from sample; don't materialize full parsed array (saves memory/time)
        # Build parsed as sampled result expanded with NaT for remainder — min/max derived from sample
        sampled_success_rate = float(best_success / _eval_non_null_count) if _eval_non_null_count else 0.0
        # If sample success was high, do a single bulk parse of full series only for min/max (fast path)
        if sampled_success_rate > 0.5 and best_parsed is not None and best_success > 0:
            try:
                # Light full parse just to capture min/max without element-wise fallback
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=UserWarning)
                    full_p = pd.to_datetime(series, errors='coerce', utc=True, format='mixed')
                parsed = full_p
                best_success = int(parsed.notna().sum())
            except Exception:
                parsed = best_parsed
        else:
            # Low success — treat as non-datetime; return lightweight NaT series
            parsed = pd.Series([pd.NaT]*n)
            best_success = 0
        # Recompute success for rate if we fell back to sampled estimate
        if parsed is not None and len(parsed) == n and best_success == 0 and sampled_success_rate == 0:
            # keep as is
            pass
    else:
        parsed = best_parsed if best_parsed is not None else pd.Series([pd.NaT]*n)
    parsed = best_parsed if best_parsed is not None else pd.Series([pd.NaT]*n)
    # Normalize to UTC for consistency if not already
    if parsed is not None and not parsed.empty:
        try:
            if parsed.dt.tz is None:
                parsed = parsed.dt.tz_localize('UTC')
            else:
                parsed = parsed.dt.tz_convert('UTC')
        except Exception:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=UserWarning)
                    parsed = pd.to_datetime(parsed, errors='coerce', utc=True, format='mixed')
            except Exception:
                pass

    success = int(parsed.notna().sum())
    # parse_success_rate relative to non-null values? spec says overall rate; we use non-null base for min/max but rate over total rows
    # Provide both perspectives: use total rows denominator; also ensure at least fallback
    total_for_rate = n
    if success == 0:
        success_rate = 0.0
    else:
        # If series has many nulls, rate over non-null is more meaningful; spec says calculate and record parse_success_rate
        # We'll compute over non-null count to reflect parsing of present values
        if non_null_count > 0:
            success_rate = float(success / non_null_count)
        else:
            success_rate = 0.0
    # Alternative also compute overall
    # Keep success_rate as proportion of non-null that parsed
    success_rate_pct = round(success_rate*100,1)
    # invalid_date_count: non-null values that failed to parse
    invalid = int(non_null_count - success) if non_null_count else 0
    if success > 0:
        valid = parsed.dropna()
        try:
            min_date = str(valid.min().isoformat()) if not valid.empty else None
            max_date = str(valid.max().isoformat()) if not valid.empty else None
        except Exception:
            min_date = str(valid.min()) if not valid.empty else None
            max_date = str(valid.max()) if not valid.empty else None
    else:
        min_date = None
        max_date = None

    return {"parse_success_rate": success_rate_pct, "min_date": min_date, "max_date": max_date, "invalid_date_count": max(0, invalid), "parsed": parsed}

def _is_identifier_column(col_name: str, series: pd.Series, row_count: int) -> bool:
    """
    Identify identifier columns using heuristics:
    - high cardinality (>95% unique)
    - non-sequential integer steps
    - regex pattern matching (?i).*(id|code|key|account|number|no|uuid|hash).*
    """
    if row_count <= 10:
        # For small datasets, rely primarily on regex, not cardinality
        return bool(IDENTIFIER_REGEX.search(col_name))
    unique_count = int(series.nunique(dropna=False))
    unique_ratio = unique_count / row_count if row_count else 0
    high_card = unique_ratio > 0.95

    regex_match = bool(IDENTIFIER_REGEX.search(col_name))

    # Non-sequential integer steps detection
    non_sequential = False
    try:
        # Only for integer-like columns
        # Dropna and try numeric conversion
        numeric = pd.to_numeric(series.dropna(), errors='coerce')
        # Check if majority are integer-like
        if len(numeric) > 0:
            # proportion that are integers (within tolerance)
            int_like = numeric.dropna().apply(lambda x: float(x).is_integer() if pd.notna(x) else False)
            if int_like.mean() > 0.8:
                vals = numeric[int_like].astype(int).sort_values().unique()
                if len(vals) > 5:
                    diffs = np.diff(vals)
                    # Sequential would be all diffs ==1 and consecutive from min to max
                    if not np.all(diffs == 1):
                        non_sequential = True
                    else:
                        # Check if starts at 1 or 0 and goes to n -> likely sequential id but still identifier? spec says non-sequential steps => identifier, sequential would not be identifier by this heuristic
                        # So sequential => non_sequential stays False
                        non_sequential = False
                elif len(vals) > 1:
                    # Small set but gap not 1?
                    diffs = np.diff(vals) if len(vals) >1 else []
                    if len(diffs) >0 and not np.all(diffs == 1):
                        non_sequential = True
    except Exception:
        non_sequential = False

    # Guard: long free-text columns (avg len >30) with high cardinality are TEXT not identifiers, even if 100% unique
    if series.dtype == object or pd.api.types.is_string_dtype(series):
        try:
            lens = series.dropna().astype(str).str.len()
            if not lens.empty and float(lens.mean()) > 30:
                return False
        except Exception:
            pass
    # Combined heuristic: as per spec, OR logic but guarded to avoid over-flagging numeric measures
    # If high_card alone without regex nor non_sequential could still be identifier (e.g., uuid strings with 100% unique but column named transaction_id regex would catch)
    # For generic numeric measures like price with high cardinality but not identifier, we should NOT flag if regex false and non_sequential false
    # So require at least one of regex or non_sequential when high_card, OR high_card alone if string type with no numeric pattern?
    # Implementation: identifier if (high_card and (regex_match or non_sequential)) OR (regex_match and unique_ratio > 0.5) OR (non_sequential and regex_match) OR (high_card and series.dtype == object and unique_ratio>0.95)
    # Simpler: OR logic as stated: high_card OR non_sequential OR regex_match => identifier. But spec explicitly says using heuristics: high cardinality (>95% unique), non-sequential integer steps, OR regex patterns. That reads as OR.
    # To balance false positives, we apply OR but with additional check: datetime-like columns (parse_success >50%) are never identifiers
    try:
        # Quick datetime check to avoid marking dates as identifiers even if high cardinality
        if series.dtype == object:
            dt_info = robust_datetime_parse(series)
            if dt_info["parse_success_rate"] > 50:
                return False
        else:
            # also check if numeric but is actually date-like integer (unix timestamps) - don't mark as identifier if datetime parsable as timestamp with high success
            pass
    except Exception:
        pass

    # If column name suggests datetime, don't mark as identifier even if high cardinality
    if 'date' in col_name.lower() or 'time' in col_name.lower():
        # Check parse success: if high, not identifier
        try:
            dt_info = robust_datetime_parse(series)
            if dt_info["parse_success_rate"] > 50:
                return False
        except:
            pass

    # Refined logic to avoid over-flagging numeric measures:
    # - regex alone with sufficient uniqueness (>0.5) => identifier
    # - high_card + regex => identifier
    # - high_card + non_sequential => identifier (covers integer IDs with gaps)
    # - high_card + short string (avg len <30) => identifier (covers uuid-like)
    # Bare high_card for long text already guarded above; bare non_sequential alone does NOT trigger for numeric measures with outliers
    if regex_match and unique_ratio > 0.5:
        return True
    if high_card and regex_match:
        return True
    if high_card and non_sequential:
        return True
    if high_card and series.dtype == object:
        try:
            avg_len = float(series.dropna().astype(str).str.len().mean()) if not series.dropna().empty else 0
            if avg_len < 30:
                return True
        except Exception:
            return True
    # Also high cardinality alone for integer-like with high cardinality short? already covered by high_card+non_sequential
    return False

def classify_semantic_type(col_name: str, series: pd.Series, row_count: int, dt_info: Dict[str,Any], is_identifier: bool) -> str:
    """
    Classify into: identifier, categorical, numeric_measure, datetime, boolean, text, derived
    """
    # Check identifier first
    if is_identifier:
        return "identifier"
    # Boolean: 2 unique values and dtype bool or values in boolean set
    unique_vals = series.dropna().unique()
    if len(unique_vals) == 2:
        # Normalize to string lower
        low_vals = set([str(v).strip().lower() for v in unique_vals])
        bool_sets = [{"true","false"}, {"0","1"}, {"y","n"}, {"yes","no"}, {"t","f"}]
        if low_vals in bool_sets or low_vals.issubset({"true","false","0","1","y","n","yes","no","t","f"}):
            return "boolean"
        # Also if dtype is bool
        if pd.api.types.is_bool_dtype(series):
            return "boolean"
    # Datetime: check parse_success_rate > threshold or already datetime dtype
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if dt_info.get("parse_success_rate",0) >= 50:
        # If majority parses as datetime and column name suggests date/time or success >80% even without name
        if dt_info["parse_success_rate"] >= 80 or ('date' in col_name.lower() or 'time' in col_name.lower()):
            return "datetime"
        # Also if success >= 50 and original dtype is object, classify as datetime
        # But avoid misclassifying duration "4h 7m" - that has low parse success typically <50
        if dt_info["parse_success_rate"] >= 50:
            return "datetime"
    # Numeric measure: numeric dtype and not identifier
    if pd.api.types.is_numeric_dtype(series):
        # Check if integer with low cardinality maybe categorical? but numeric_measure takes precedence if not identifier and not boolean
        # We distinguish categorical numeric like 0/1 already handled as boolean, small int categories
        # For numeric categorical (e.g., 1-5 rating with 5 unique), could be categorical, but treat as numeric_measure if many distinct values
        # Use threshold: if unique <10 and row_count >50 maybe categorical; but spec categorization expects categorical vs numeric_measure separation
        # Let's use cardinality: if unique <= 10 and row_count>20, treat as categorical
        if len(unique_vals) <= 10 and row_count > 20:
            # Could be categorical numeric code; but if not identifier, we classify as categorical
            # Check if column name suggests category
            if any(k in col_name.lower() for k in ["category","type","status","level","rating"]):
                return "categorical"
        return "numeric_measure"
    # Text vs categorical vs derived
    # For object / string columns that are not datetime/identifier
    if series.dtype == object or pd.api.types.is_string_dtype(series):
        # Check average string length
        try:
            str_lens = series.dropna().astype(str).str.len()
            avg_len = float(str_lens.mean()) if not str_lens.empty else 0
            unique_ratio = len(unique_vals)/row_count if row_count else 0
            # Text: long strings, high variability, free text
            if avg_len > 30 or (avg_len > 20 and unique_ratio > 0.8):
                return "text"
            # Derived: heuristic if column name contains computed-like terms or contains formula pattern?
            if any(k in col_name.lower() for k in ["derived","computed","calc","total","amount"]):
                # But total could be numeric_measure; we already handled numeric
                pass
            # Categorical: low cardinality
            if len(unique_vals) < max(20, row_count*0.2) and unique_ratio < 0.5:
                return "categorical"
            elif unique_ratio > 0.95:
                # High cardinality string not identifier (regex didn't match) but still high unique -> text
                return "text"
            else:
                return "categorical"
        except Exception:
            return "categorical"
    # Derived fallback: if column was computed from others (can't detect without lineage), mark as derived if name suggests formula
    if "derived" in col_name.lower() or "calc" in col_name.lower():
        return "derived"
    # Fallback
    if pd.api.types.is_numeric_dtype(series):
        return "numeric_measure"
    return "categorical"


def profile_dataframe(df: pd.DataFrame) -> Dict[str, Any]:
    row_count = len(df)
    col_count = len(df.columns)
    duplicates = int(df.duplicated().sum())
    missing_total = int(df.isnull().sum().sum())
    total_cells = row_count * col_count if row_count*col_count>0 else 1
    missing_pct = missing_total / total_cells
    duplicate_pct = duplicates / row_count if row_count>0 else 0

    constant_cols = 0
    high_card_cols = 0
    columns_info = []
    insights = []
    identifier_cols = []

    # Precompute correlation exclusion list later

    for col in df.columns:
        s = df[col]
        dtype = str(s.dtype)
        null_count = int(s.isnull().sum())
        null_pct = float(null_count / row_count * 100) if row_count>0 else 0
        unique_count = int(s.nunique(dropna=False))
        min_val = None
        max_val = None
        mean_val = None
        median_val = None
        std_val = None

        # Robust datetime parsing for every column (records parse stats)
        dt_info = robust_datetime_parse(s)
        parse_success_rate = dt_info["parse_success_rate"]
        min_date = dt_info["min_date"]
        max_date = dt_info["max_date"]
        invalid_date_count = dt_info["invalid_date_count"]

        # Identifier detection
        is_identifier = _is_identifier_column(col, s, row_count)
        if is_identifier:
            identifier_cols.append(col)

        # Semantic classification
        semantic_type = classify_semantic_type(col, s, row_count, dt_info, is_identifier)

        # Handle metrics: EXCLUDE identifier columns from mean, median, winsorization, IQR, correlation
        try:
            if is_identifier:
                # For identifier, do NOT compute mean/median/std/outliers even if numeric
                # Keep min/max as string representation if possible but skip aggregates
                if pd.api.types.is_numeric_dtype(s):
                    try:
                        min_val = str(s.min(skipna=True))
                        max_val = str(s.max(skipna=True))
                    except:
                        pass
                elif pd.api.types.is_datetime64_any_dtype(s):
                    try:
                        min_val = str(s.min(skipna=True))
                        max_val = str(s.max(skipna=True))
                    except:
                        pass
                else:
                    # For identifier that is datetime-parsable, use min_date/max_date
                    if semantic_type == "datetime":
                        min_val = min_date
                        max_val = max_date
                # Skip mean/median/std
                mean_val = None
                median_val = None
                std_val = None
            else:
                # Non-identifier: original logic plus enhanced datetime
                if pd.api.types.is_numeric_dtype(s):
                    min_val = str(s.min(skipna=True))
                    max_val = str(s.max(skipna=True))
                    mean_val = float(s.mean(skipna=True)) if not s.isnull().all() else None
                    median_val = float(s.median(skipna=True)) if not s.isnull().all() else None
                    std_val = float(s.std(skipna=True)) if not s.isnull().all() else None
                elif pd.api.types.is_datetime64_any_dtype(s):
                    min_val = str(s.min(skipna=True))
                    max_val = str(s.max(skipna=True))
                else:
                    # Attempt datetime detection for non-identifier
                    if semantic_type == "datetime":
                        dtype = "datetime"
                        min_val = min_date
                        max_val = max_date
                    else:
                        # For categorical, keep min_max as first/last? skip
                        pass
        except Exception:
            pass

        if unique_count == 1:
            constant_cols += 1
            insights.append(f"Column '{col}' is constant (only one unique value).")
        if unique_count > row_count * 0.9 and row_count>10:
            high_card_cols += 1

        if null_pct > 20:
            insights.append(f"Column '{col}' has high missing values: {null_pct:.1f}%.")

        # outlier detection for numeric_measure ONLY, exclude identifiers
        if not is_identifier and pd.api.types.is_numeric_dtype(s) and semantic_type == "numeric_measure" and row_count>10:
            try:
                q1 = s.quantile(0.25)
                q3 = s.quantile(0.75)
                iqr = q3 - q1
                lower = q1 - 1.5*iqr
                upper = q3 + 1.5*iqr
                outliers = ((s < lower) | (s > upper)).sum()
                if outliers >0 and outliers / row_count <0.3:
                    insights.append(f"Column '{col}' has {outliers} potential outliers.")
            except Exception:
                pass

        # For identifier, add insight about identifier detection but not outlier
        if is_identifier and "date" not in col.lower():
            # Optionally note identifier classification for lineage, but not as quality issue
            pass

        col_info = {
            "name": col,
            "data_type": dtype,
            "semantic_type": semantic_type,
            "is_identifier": is_identifier,
            "null_count": null_count,
            "null_percentage": null_pct,
            "unique_count": unique_count,
            "min_value": min_val,
            "max_value": max_val,
            "mean_value": mean_val,
            "median_value": median_val,
            "std_value": std_val,
            # Robust datetime parsing fields
            "parse_success_rate": parse_success_rate,
            "min_date": min_date,
            "max_date": max_date,
            "invalid_date_count": invalid_date_count,
        }
        columns_info.append(col_info)

    # Quality scoring (unchanged but consider identifiers not penalized as high cardinality?)
    if duplicates>0:
        insights.append(f"Dataset has {duplicates} duplicate rows ({duplicate_pct*100:.1f}%).")
    if missing_pct>0:
        insights.append(f"Overall missing data: {missing_pct*100:.1f}% of cells.")
    if constant_cols>0:
        insights.append(f"{constant_cols} constant columns detected.")
    if high_card_cols>0:
        insights.append(f"{high_card_cols} high-cardinality columns detected.")

    score = 100
    score -= missing_pct*50
    score -= duplicate_pct*30
    score -= constant_cols * 5
    score -= min(high_card_cols*2, 10)
    score = max(0, min(100, round(score, 1)))

    quality_details = {
        "score": score,
        "factors": {
            "missing_percentage": round(missing_pct*100,2),
            "duplicate_percentage": round(duplicate_pct*100,2),
            "constant_columns": constant_cols,
            "high_cardinality_columns": high_card_cols,
            "total_missing_cells": missing_total,
            "duplicate_rows": duplicates,
            "identifier_columns": identifier_cols
        }
    }

    if not insights:
        insights.append("Dataset looks clean with no major quality issues detected.")
    insights.insert(0, f"Dataset has {row_count} rows and {col_count} columns.")

    return {
        "row_count": row_count,
        "column_count": col_count,
        "duplicates": duplicates,
        "columns_info": columns_info,
        "quality_details": quality_details,
        "insights": insights,
        "quality_score": score,
        "identifier_columns": identifier_cols
    }

def get_sample_rows(df: pd.DataFrame, n=5) -> List[dict]:
    return df.head(n).replace({np.nan: None}).to_dict(orient="records")

def compute_preview(df: pd.DataFrame, page: int=1, page_size: int=20, search: str=None, sort_by: str=None, sort_dir: str="asc"):
    filtered = df
    if search:
        mask = pd.Series([False]*len(df))
        for col in df.columns:
            mask = mask | df[col].astype(str).str.contains(search, case=False, na=False)
        filtered = df[mask]
    if sort_by and sort_by in df.columns:
        filtered = filtered.sort_values(by=sort_by, ascending=(sort_dir=="asc"))
    total = len(filtered)
    start = (page-1)*page_size
    end = start + page_size
    page_df = filtered.iloc[start:end].replace({np.nan: None})
    return page_df.to_dict(orient="records"), total

def get_correlation_matrix(df: pd.DataFrame, exclude_identifiers: bool = True) -> Dict[str, Any]:
    """
    Compute correlation matrix excluding identifier columns.
    """
    if df.empty:
        return {"matrix": {}, "excluded": []}
    # Determine identifier columns via same heuristic
    identifier_cols = []
    for col in df.columns:
        if _is_identifier_column(col, df[col], len(df)):
            identifier_cols.append(col)
    # Select numeric_measure columns only
    numeric_cols = []
    for col in df.columns:
        if col in identifier_cols and exclude_identifiers:
            continue
        s = df[col]
        # Robust check: numeric and not identifier
        dt_info = robust_datetime_parse(s)
        is_id = col in identifier_cols
        sem = classify_semantic_type(col, s, len(df), dt_info, is_id)
        if sem == "numeric_measure":
            # Ensure numeric dtype
            if pd.api.types.is_numeric_dtype(s):
                numeric_cols.append(col)
            else:
                # Try coercion
                try:
                    conv = pd.to_numeric(s, errors='coerce')
                    if conv.notna().mean() > 0.8:
                        numeric_cols.append(col)
                except:
                    pass
    if len(numeric_cols) < 2:
        return {"matrix": {}, "excluded": identifier_cols, "numeric_columns": numeric_cols}
    sub = df[numeric_cols].apply(pd.to_numeric, errors='coerce')
    corr = sub.corr(numeric_only=True)
    # Convert to dict, handling NaN
    matrix = corr.replace({np.nan: None}).to_dict()
    return {"matrix": matrix, "excluded": identifier_cols, "numeric_columns": numeric_cols}

def winsorize_series(series: pd.Series, col_name: str, row_count: int) -> pd.Series:
    """
    Winsorization helper that respects identifier exclusion.
    Returns original series if identifier, else winsorized.
    """
    if _is_identifier_column(col_name, series, row_count):
        return series
    # Otherwise perform winsorization clip via IQR
    try:
        if not pd.api.types.is_numeric_dtype(series):
            series = pd.to_numeric(series, errors='coerce')
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        lower = q1 - 1.5*iqr
        upper = q3 + 1.5*iqr
        return series.clip(lower=lower, upper=upper)
    except Exception:
        return series

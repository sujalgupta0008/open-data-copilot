import os
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User, Dataset, DatasetColumn, AnalysisSession, AnalysisMessage, AnalysisResult, Chart
from app.schemas.schemas import QueryRequest, PythonRequest, SessionOut
from app.data_engine.profiler import load_dataframe, profile_dataframe
from app.ai.provider import get_ai_provider
from app.execution.sql import execute_sql, validate_sql
from app.execution.python_exec import execute_python
import pandas as pd
import re
import json as _json
import secrets
from datetime import datetime, timezone, timedelta
from app.ai.provider import classify_intent
from app.data_engine.statistical import validate_result, assumptions_and_limitations
from app.data_engine.recommendation import build_recommendation

router = APIRouter(prefix="/api", tags=["analysis"])
shared_analysis_router = APIRouter(prefix="/api/shared", tags=["shared"])

# --- Intent and metric helpers for QA routing ---
def _has_usable_date_column(df: pd.DataFrame) -> tuple[bool, str | None]:
    for c in df.columns:
        if "date" in c.lower() or "time" in c.lower():
            try:
                s = pd.to_datetime(df[c], errors='coerce')
                if s.notna().mean() > 0.5:
                    return True, c
            except:
                continue
        try:
            if pd.api.types.is_datetime64_any_dtype(df[c]):
                return True, c
        except:
            pass
    return False, None

def _available_metrics_list(df: pd.DataFrame, saved_metrics) -> list[str]:
    cols = [str(c) for c in df.columns]
    saved = [m.name for m in saved_metrics]
    # Combine column names that are business-like and saved metrics
    business_cols = [c for c in cols if any(k in c.lower() for k in ["revenue","profit","sales","amount","price","quantity","fare","cost","margin","aov","loan_amount"])]
    return saved + business_cols

def _metric_exists(term: str, df: pd.DataFrame, saved_metrics) -> bool:
    term_low = term.lower()
    # Special case: approval rate is via Loan_Status, not a column named approval
    if "approval" in term_low:
        return any(c.lower() == "loan_status" for c in df.columns)
    # Check saved metrics
    for m in saved_metrics:
        if term_low in m.name.lower() or m.name.lower() in term_low:
            return True
    # Check column names
    for c in df.columns:
        cl = c.lower()
        if term_low == cl or term_low in cl or cl in term_low:
            # avoid partial like "rev" matching revenue? Use word boundary
            if term_low in cl:
                return True
    # Also check if term is generic like revenue but column is exactly revenue
    return False

def _extract_requested_terms(question: str) -> list[str]:
    q = question.lower()
    business_terms = ["revenue", "profit", "margin", "aov", "average order value", "conversion rate", "conversion", "approval rate", "approval", "churn", "retention", "sales", "orders", "price", "fare", "cost", "quantity", "amount", "loan_amount"]
    found = []
    for term in business_terms:
        if term in q:
            found.append(term)
    return found

def _is_trend_question(question: str) -> bool:
    q = question.lower()
    time_terms = ["latest month", "previous month", "month-over-month", "month over month", "mom", "latest", "previous month"]
    change_terms = ["decreased", "increased", "decline", "growth", "trend", "decline started", "when the decline"]
    has_time = any(t in q for t in time_terms)
    has_change = any(c in q for c in change_terms)
    # Require time term or change with revenue/month context to avoid misclassifying approval questions
    if has_time:
        return True
    if has_change and any(k in q for k in ["revenue", "sales", "profit", "month"]):
        return True
    return False

def _is_causal_question(question: str) -> bool:
    q = question.lower()
    if "root cause" in q:
        return False
    if any(p in q for p in [" cause", " causes", " caused", " causal"]):
        return True
    if re.search(r"does\s+.+\s+cause", q):
        return True
    if re.search(r"impact\s+of\s+.+\s+on\s+", q):
        return True
    if re.search(r"effect\s+of\s+.+\s+on\s+", q):
        return True
    return False

# BUG2: Revenue computed metric helper (shared with report_pipeline)
def _get_revenue_computed_expr(df: pd.DataFrame):
    cols_lower = {c.lower(): c for c in df.columns}
    qty_col = cols_lower.get("quantity")
    price_col = cols_lower.get("unit_price")
    if not qty_col or not price_col:
        return None
    disc_col = cols_lower.get("discount_applied")
    if not disc_col:
        for c in df.columns:
            if "discount" in c.lower():
                disc_col = c
                break
    if disc_col:
        return f'"{qty_col}" * "{price_col}" * (1 - COALESCE("{disc_col}",0)/100.0)'
    else:
        return f'"{qty_col}" * "{price_col}"'

def _is_revenue_confirmation(question: str, history) -> bool:
    q = (question or "").lower().strip()
    affirm = ["yes", "y", "confirm", "use computed", "use_computed", "computed", "proceed", "ok", "go ahead", "use it", "quantity"]
    is_affirm = any(k in q for k in affirm) or q in ["yes", "y", "yeah", "ok", "use_computed_revenue"]
    has_history_suggestion = False
    if history:
        for h in history[-5:]:
            content = (h.get("content") or "").lower()
            if "quantity" in content and "unit_price" in content and "revenue" in content:
                has_history_suggestion = True
                break
    if has_history_suggestion and is_affirm:
        return True
    if "quantity" in q and "unit_price" in q:
        return True
    if "computed" in q:
        return True
    return False

# --- Deterministic insight helpers (grounded in actual DuckDB result) ---

def _format_value(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        # format with 2 decimals, strip trailing zeros
        s = f"{v:.2f}"
        # if original had more precision, keep 2 decimals; avoid scientific
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s
    if isinstance(v, int):
        return str(v)
    # for numpy types
    try:
        # handle numpy int/float
        import numpy as np
        if isinstance(v, (np.integer,)):
            return str(int(v))
        if isinstance(v, (np.floating,)):
            fv = float(v)
            if fv.is_integer():
                return str(int(fv))
            s = f"{fv:.2f}"
            if "." in s:
                s = s.rstrip("0").rstrip(".")
            return s
    except:
        pass
    return str(v)

def _readable_metric(alias: str) -> str:
    # Convert alias like average_price, total_LoanAmount, count, max_price
    if not alias:
        return "value"
    low = alias.lower()
    if low == "count":
        return "count"
    # replace underscores with space
    readable = alias.replace("_", " ")
    return readable

def generate_deterministic_insight(question: str, sql: str, columns: list, rows: list, dataset_name: str, total_rows: int, overall_rate: float = None):
    """
    Generate human-readable summary grounded in actual returned evidence.
    Returns (summary, takeaway)
    Never fabricates numbers; uses only provided rows/columns.
    Summary 2-4 sentences, takeaway one short highlighted sentence.
    """
    q_clean = (question or "").strip()
    q_clean_nq = q_clean.rstrip("?").rstrip(".")
    if not rows:
        summary = f"The analysis executed your question \"{q_clean}\" on {total_rows} records and returned no matching rows."
        takeaway = "No results matched the criteria."
        return summary, takeaway

    # --- Approval rate segment handling (multi-dimensional) ---
    lower_cols = [c.lower() for c in columns]
    if "approval_rate" in lower_cols:
        approval_col = next(c for c in columns if c.lower() == "approval_rate")
        # Identify segment dimensions (exclude counts and rates)
        seg_dims = [c for c in columns if c.lower() not in ["application_count","approved_count","approval_rate"]]
        # Sort rows already DESC by approval_rate (as per SQL)
        strongest = rows[0]
        weakest = rows[-1] if len(rows) > 1 else rows[0]
        strongest_rate = float(strongest.get(approval_col)) if strongest.get(approval_col) is not None else 0.0
        weakest_rate = float(weakest.get(approval_col)) if weakest.get(approval_col) is not None else 0.0
        # Build segment description with Missing handling and readable Credit_History
        def seg_val(v):
            if v is None or (isinstance(v, str) and v.strip() == ""):
                return "Missing"
            return str(v)
        def seg_desc(row):
            parts=[]
            for d in seg_dims:
                v=row.get(d)
                sv=seg_val(v)
                if d.lower()=="credit_history":
                    parts.append(f"Credit History {sv}")
                else:
                    parts.append(sv)
            return ", ".join(parts)
        strongest_desc = seg_desc(strongest)
        weakest_desc = seg_desc(weakest)
        # Counts for insight
        def approved_app_str(row):
            app=row.get("application_count")
            appr=row.get("approved_count")
            if app is not None and appr is not None:
                try:
                    return f"{int(float(appr))} of {int(float(app))} applications"
                except:
                    return f"{_format_value(appr)} of {_format_value(app)}"
            elif app is not None:
                return f"{int(float(app))} applications"
            else:
                return ""
        strongest_counts = approved_app_str(strongest)
        weakest_counts = approved_app_str(weakest)
        # Overall rate
        if overall_rate is not None:
            diff_pp = strongest_rate - float(overall_rate)
            diff_str = f"{diff_pp:+.1f} percentage points"
            s1 = f"Among {total_rows} applications, approval rate was analyzed across {', '.join(seg_dims)} segments with at least 10 applications."
            s2 = f"{strongest_desc} has the highest approval rate at {_format_value(strongest_rate)}% ({strongest_counts}), compared with the overall rate of {_format_value(float(overall_rate))}%, a difference of {diff_str}."
            s3 = f"{weakest_desc} has the lowest approval rate at {_format_value(weakest_rate)}% ({weakest_counts}). This indicates variation in approval rates across segments."
            # Caveat: association vs causation
            s4 = "These differences are associated with the examined dimensions and warrant further investigation, not proven causation."
            summary = f"{s1} {s2} {s3} {s4}"
            takeaway = f"Strongest segment {strongest_rate:.1f}% vs overall {float(overall_rate):.1f}% ({diff_str})."
            return summary, takeaway
        else:
            s1 = f"Approval rate was analyzed across {', '.join(seg_dims)} segments (>=10 applications)."
            s2 = f"Strongest segment {strongest_desc} has {_format_value(strongest_rate)}% approval ({strongest_counts}), weakest {weakest_desc} has {_format_value(weakest_rate)}% ({weakest_counts}) among {len(rows)} segments."
            summary = f"{s1} {s2}"
            takeaway = f"Strongest {strongest_rate:.1f}% vs weakest {weakest_rate:.1f}%."
            return summary, takeaway

    # scalar: single row single column
    if len(rows) == 1 and len(columns) == 1:
        col = columns[0]
        val = rows[0].get(col)
        val_str = _format_value(val)
        readable = _readable_metric(col)
        if total_rows:
            s1 = f'Among {total_rows} records in the "{dataset_name}" dataset, the analysis evaluated "{q_clean_nq}".'
        else:
            s1 = f'The analysis evaluated "{q_clean_nq}" and returned a single aggregated result.'
        s2 = f"The computed {readable} is {val_str}."
        s3 = "This value reflects the aggregation over the dataset and is directly derived from the executed SQL result."
        summary = f"{s1} {s2} {s3}"
        takeaway = f"{readable} is {val_str}."
        return summary, takeaway

    # Check for time-series (date/month/year)
    group_col = columns[0] if columns else ""
    is_time = False
    if group_col:
        gc_low = group_col.lower()
        if any(k in gc_low for k in ["date","month","year","time"]):
            is_time = True
        # also check sql for month extraction pattern
        if "month" in (sql or "").lower() and "substr" in (sql or "").lower():
            is_time = True

    if is_time and len(columns) >= 2:
        # Handle multi-metric time-series (e.g., month, transaction_volume, average_unit_price)
        # For len==2 keep old single-metric behavior but with fixed wording
        # For len>=3 generate joint insight
        if len(columns) >= 3:
            # Check if we have multiple metrics (all non-time columns are metrics)
            metrics_cols = columns[1:]
            try:
                # Compute strongest/weakest per metric and endpoint change
                parts = []
                takeaways = []
                for metric_col in metrics_cols:
                    readable_metric = _readable_metric(metric_col)
                    vals = []
                    for r in rows:
                        try:
                            vals.append(float(r.get(metric_col)) if r.get(metric_col) is not None else None)
                        except:
                            vals.append(None)
                    clean_vals = [v for v in vals if v is not None]
                    if not clean_vals:
                        continue
                    min_val = min(clean_vals)
                    max_val = max(clean_vals)
                    min_row = next((r for r in rows if r.get(metric_col) is not None and float(r.get(metric_col)) == min_val), rows[0])
                    max_row = next((r for r in rows if r.get(metric_col) is not None and float(r.get(metric_col)) == max_val), rows[0])
                    parts.append(f"For {readable_metric}, the strongest month is {max_row.get(group_col)} ({_format_value(max_val)}) and the weakest is {min_row.get(group_col)} ({_format_value(min_val)}).")
                    takeaways.append(f"Peak {readable_metric} is {_format_value(max_val)} in {max_row.get(group_col)}")
                s1 = f"The analysis tracked {', '.join([_readable_metric(c) for c in metrics_cols])} over {group_col} across {len(rows)} periods to answer \"{q_clean_nq}\"."
                # Endpoint change distinguished from trend
                endpoint_parts = []
                if len(rows) >= 2:
                    for metric_col in metrics_cols:
                        readable_metric = _readable_metric(metric_col)
                        fv = rows[0].get(metric_col)
                        lv = rows[-1].get(metric_col)
                        try:
                            fv_f = float(fv)
                            lv_f = float(lv)
                            change = lv_f - fv_f
                            pct = (change/fv_f*100) if fv_f !=0 else 0
                            endpoint_parts.append(f"Endpoint change for {readable_metric}: {rows[0].get(group_col)} ({_format_value(fv_f)}) → {rows[-1].get(group_col)} ({_format_value(lv_f)}) — change {change:+.1f} ({pct:+.1f}%)")
                        except:
                            pass
                    if endpoint_parts:
                        parts.extend(endpoint_parts)
                        parts.append("Endpoint change is descriptive of first-to-latest difference, not a statistically inferred trend; volatility and peak/trough are noted separately. No time-series trend significance is claimed without additional assumptions.")
                summary = f"{s1} " + " ".join(parts)
                takeaway = "; ".join(takeaways) + "."
                return summary, takeaway
            except Exception:
                pass
        # Single-metric time-series (len==2) with fixed wording
        metric_col = columns[1]
        readable_metric = _readable_metric(metric_col)
        try:
            values = [r.get(metric_col) for r in rows if isinstance(r.get(metric_col), (int,float)) or (hasattr(r.get(metric_col), "__float__"))]
            numeric_vals = []
            for v in values:
                try:
                    numeric_vals.append(float(v))
                except:
                    pass
            if numeric_vals and len(rows) >= 1:
                min_val = min(numeric_vals)
                max_val = max(numeric_vals)
                min_row = next((r for r in rows if r.get(metric_col) is not None and float(r.get(metric_col)) == min_val), rows[0])
                max_row = next((r for r in rows if r.get(metric_col) is not None and float(r.get(metric_col)) == max_val), rows[0])
                s1 = f"The analysis tracked {readable_metric} over {group_col} across {len(rows)} periods to answer \"{q_clean_nq}\"."
                s2 = f"It ranges from {_format_value(min_val)} in {min_row.get(group_col)} to {_format_value(max_val)} in {max_row.get(group_col)}."
                if len(rows) >= 2:
                    first_val = rows[0].get(metric_col)
                    last_val = rows[-1].get(metric_col)
                    try:
                        fv = float(first_val)
                        lv = float(last_val)
                        change = lv - fv
                        pct = (change/fv*100) if fv !=0 else 0
                        if change > 0:
                            s3 = f"Endpoint change: {rows[0].get(group_col)} ({_format_value(fv)}) → {rows[-1].get(group_col)} ({_format_value(lv)}) — increase of {change:+.1f} ({pct:+.1f}%). This is endpoint difference, not a statistically inferred trend."
                        elif change < 0:
                            s3 = f"Endpoint change: {rows[0].get(group_col)} ({_format_value(fv)}) → {rows[-1].get(group_col)} ({_format_value(lv)}) — decrease of {abs(change):.1f} ({abs(pct):.1f}%). This is endpoint difference, not a statistically inferred trend."
                        else:
                            s3 = f"The series starts and ends at {_format_value(fv)}, with fluctuations in between (peak {max_row.get(group_col)}, trough {min_row.get(group_col)})."
                        summary = f"{s1} {s2} {s3}"
                    except:
                        summary = f"{s1} {s2} This shows the distribution of {readable_metric} over time."
                else:
                    summary = f"{s1} {s2}"
                takeaway = f"Peak {readable_metric} is {_format_value(max_val)} in {max_row.get(group_col)}."
                return summary, takeaway
        except Exception:
            pass

    # General grouped (2+ columns, first categorical, second metric)
    if len(columns) >= 2:
        group_col = columns[0]
        metric_col = columns[1]
        readable_group = str(group_col)
        readable_metric = _readable_metric(metric_col)
        top = rows[0]
        top_group_val = top.get(group_col)
        top_metric_val = top.get(metric_col)
        top_metric_str = _format_value(top_metric_val)

        # Detect sort direction from SQL
        is_asc = False
        try:
            upper_sql = (sql or "").upper()
            if "ORDER BY" in upper_sql:
                order_part = upper_sql.split("ORDER BY")[-1]
                # check presence of ASC vs DESC after ORDER BY
                # If ASC appears and DESC not, it's ASC; if both, compare positions
                has_asc = "ASC" in order_part
                has_desc = "DESC" in order_part
                if has_asc and not has_desc:
                    is_asc = True
                elif has_asc and has_desc:
                    is_asc = order_part.rfind("ASC") > order_part.rfind("DESC")
        except:
            pass
        extreme = "lowest" if is_asc else "highest"

        # Sentence 1
        if total_rows:
            s1 = f'Among {total_rows} records, the analysis compared {readable_metric} across {readable_group} groups to answer "{q_clean_nq}".'
        else:
            s1 = f'The analysis compared {readable_metric} across {readable_group} groups.'

        # Sentence 2 - key result with actual values
        s2 = f"The {extreme} value is {top_group_val} with {top_metric_str} for {readable_metric}."
        if len(rows) > 1:
            second = rows[1]
            sec_group_val = second.get(group_col)
            sec_metric_val = second.get(metric_col)
            sec_metric_str = _format_value(sec_metric_val)
            s2 += f" It is followed by {sec_group_val} at {sec_metric_str}."
            if len(rows) > 2:
                s2 += f" The ranking continues across {len(rows)} groups in the result set."
        # Sentence 3 - indication
        is_top_n = "top" in (question or "").lower() or ("limit" in (sql or "").lower())
        if is_top_n and len(rows) >= 3:
            s3 = f"This highlights the leading {readable_group} values by {readable_metric} in the dataset."
        else:
            s3 = f"This comparison shows the variation in {readable_metric} across {readable_group} categories."
        summary = f"{s1} {s2} {s3}"
        takeaway = f"{top_group_val} leads with {top_metric_str} for {readable_metric}."
        return summary, takeaway

    # Fallback for other shapes (e.g., many columns, sample data)
    summary = f'The analysis executed "{q_clean_nq}" and returned {len(rows)} rows with columns {", ".join(columns)}.'
    first = rows[0]
    vals = ", ".join([f"{k}={_format_value(v)}" for k, v in list(first.items())[:3]])
    summary += f" The first result is {vals}."
    takeaway = f"Returned {len(rows)} rows; first row: {vals}."
    return summary, takeaway

def build_context(dataset: Dataset, columns, df: pd.DataFrame):
    # Build minimal context
    sample = df.head(3).replace({pd.NA: None}).to_dict(orient="records")
    stats = {}
    for c in columns:
        stats[c.name] = {
            "data_type": c.data_type,
            "null_percentage": c.null_percentage,
            "unique_count": c.unique_count,
            "mean": c.mean_value,
            "median": c.median_value
        }
    return {
        "dataset_name": dataset.name,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "columns": [{"name": c.name, "data_type": c.data_type} for c in columns],
        "stats": stats,
        "sample_rows": sample
    }

def infer_chart_type(data: list, columns: list, requested: str = None) -> str:
    if requested and requested != "none":
        return requested
    if not data or not columns or len(columns)<2:
        return "none"
    # heuristics
    # if columns contain date/month -> line
    col_names = [c.lower() for c in columns]
    if any("date" in c or "month" in c or "year" in c for c in col_names):
        return "line"
    # if one categorical + one numeric -> bar
    # assume first is cat, second numeric
    if len(columns)==2:
        return "bar"
    if len(columns)>2 and "correlation" in str(data).lower():
        return "heatmap"
    return "bar"

def build_chart_config(data: list, columns: list, chart_type: str):
    if chart_type=="none" or not data or not columns:
        return None
    lower_cols = [c.lower() for c in columns]
    # Special handling for approval_rate multi-dim segment: readable ranked horizontal bar with segment label
    if "approval_rate" in lower_cols:
        dims = [c for c in columns if c.lower() not in ["application_count","approved_count","approval_rate"]]
        # Build segment label for each row, handling missing as "Missing"
        chart_data=[]
        for row in data[:50]:
            parts=[]
            for d in dims:
                v=row.get(d)
                if v is None or (isinstance(v,str) and v.strip()==""):
                    parts.append("Missing")
                else:
                    # Pretty Credit_History
                    if d.lower()=="credit_history":
                        parts.append(f"Credit History {v}")
                    else:
                        parts.append(str(v))
            seg_label=" | ".join(parts) if parts else "Segment"
            new_row=dict(row)
            new_row["segment"]=seg_label
            chart_data.append(new_row)
        return {"xKey": "segment", "yKey": "approval_rate", "data": chart_data}
    # Simple config
    if chart_type in ["bar","line"]:
        x = columns[0]
        # y is numeric column (last)
        y = columns[1] if len(columns)>1 else columns[0]
        # Detect numeric y
        # try to find numeric
        config = {"xKey": x, "yKey": y, "data": data[:50]}
        return config
    if chart_type=="scatter" and len(columns)>=2:
        return {"xKey": columns[0], "yKey": columns[1], "data": data[:100]}
    if chart_type=="pie" and len(columns)>=2:
        return {"xKey": columns[0], "yKey": columns[1], "data": data[:10]}
    return {"data": data[:50]}

@router.post("/datasets/{dataset_id}/analyze")
async def analyze_dataset(dataset_id: str, payload: QueryRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds or ds.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Dataset not found")
    # Delegate to shared pipeline (single source of truth)
    from app.data_engine.report_pipeline import execute_analysis_pipeline
    try:
        result = await execute_analysis_pipeline(db, current_user, ds, payload.question, payload.session_id)
    except Exception as e:
        # Handle session not found etc as 404
        if "Session not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    # Adapt helper result to legacy response shape for backward compatibility
    # Helper already returns session_id, message, intent, execution_result, provider_metadata, statistical_validation, recommendation, etc.
    # Add legacy top-level ai_* fields
    pm = result.get("provider_metadata", {})
    result["ai_provider"] = pm.get("provider")
    result["ai_model"] = pm.get("model")
    result["ai_mode"] = pm.get("mode")
    result["is_fallback"] = pm.get("is_fallback", False)
    # Ensure analysis.py legacy fields are present
    return result

@router.post("/datasets/{dataset_id}/query")
async def query_sql(dataset_id: str, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Legacy direct SQL execution endpoint
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds or ds.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Dataset not found")
    sql = payload.get("sql") or payload.get("code") or ""
    try:
        from app.models.models import DatasetVersion, Transformation
        from app.data_engine.cleaning import apply_operation
        cv = db.query(DatasetVersion).filter(DatasetVersion.dataset_id==dataset_id, DatasetVersion.is_current==True).first()
        if cv and os.path.exists(cv.storage_path):
            df = load_dataframe(cv.storage_path)
        else:
            df = load_dataframe(ds.storage_path)
            trans = db.query(Transformation).filter(Transformation.dataset_id==dataset_id, Transformation.undone==False).order_by(Transformation.created_at.asc()).all()
            for t in trans:
                try:
                    df, _ = apply_operation(df, t.operation, t.params or {})
                except:
                    continue
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    res = execute_sql(df, sql)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res

@router.post("/datasets/{dataset_id}/python")
async def run_python(dataset_id: str, payload: PythonRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds or ds.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Dataset not found")
    code = payload.code
    try:
        from app.models.models import DatasetVersion, Transformation
        from app.data_engine.cleaning import apply_operation
        cv = db.query(DatasetVersion).filter(DatasetVersion.dataset_id==dataset_id, DatasetVersion.is_current==True).first()
        if cv and os.path.exists(cv.storage_path):
            df = load_dataframe(cv.storage_path)
        else:
            df = load_dataframe(ds.storage_path)
            trans = db.query(Transformation).filter(Transformation.dataset_id==dataset_id, Transformation.undone==False).order_by(Transformation.created_at.asc()).all()
            for t in trans:
                try:
                    df, _ = apply_operation(df, t.operation, t.params or {})
                except:
                    continue
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not code and payload.question:
        # generate via AI
        columns = db.query(DatasetColumn).filter(DatasetColumn.dataset_id == dataset_id).all()
        context = build_context(ds, columns, df)
        provider = get_ai_provider()
        ai = await provider.generate(context, payload.question)
        code = ai.get("code", "")
    if not code:
        raise HTTPException(status_code=400, detail="No code provided")
    res = execute_python(df, code)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res

@router.get("/analysis")
def list_sessions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sessions = db.query(AnalysisSession).filter(AnalysisSession.user_id == current_user.id).order_by(AnalysisSession.updated_at.desc()).all()
    out=[]
    for s in sessions:
        count = db.query(AnalysisMessage).filter(AnalysisMessage.session_id==s.id).count()
        ds = db.query(Dataset).filter(Dataset.id==s.dataset_id).first()
        out.append({"id": s.id, "title": s.title, "dataset_id": s.dataset_id, "dataset_name": ds.name if ds else "Unknown", "created_at": s.created_at, "updated_at": s.updated_at, "message_count": count})
    return out

@router.get("/analysis/{session_id}")
def get_session(session_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.query(AnalysisSession).filter(AnalysisSession.id==session_id).first()
    if not s or s.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    msgs = db.query(AnalysisMessage).filter(AnalysisMessage.session_id==s.id).order_by(AnalysisMessage.created_at.asc()).all()
    out_msgs=[]
    for m in msgs:
        out_msgs.append({
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "generated_code": m.generated_code,
            "execution_status": m.execution_status,
            "created_at": m.created_at,
            "results": [{"id": r.id, "result_type": r.result_type, "result_data": r.result_data} for r in m.results],
            "charts": [{"id": c.id, "chart_type": c.chart_type, "configuration": c.configuration} for c in m.charts]
        })
    ds = db.query(Dataset).filter(Dataset.id==s.dataset_id).first()
    return {"id": s.id, "title": s.title, "dataset_id": s.dataset_id, "dataset_name": ds.name if ds else "", "created_at": s.created_at, "updated_at": s.updated_at, "messages": out_msgs}

@router.delete("/analysis/{session_id}")
def delete_session(session_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.query(AnalysisSession).filter(AnalysisSession.id==session_id).first()
    if not s or s.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    db.delete(s)
    db.commit()
    return {"message":"deleted"}

@router.post("/analysis/{session_id}/share")
def create_analysis_share(session_id: str, payload: dict = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models.models import ShareToken
    s = db.query(AnalysisSession).filter(AnalysisSession.id==session_id).first()
    if not s or s.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    expires_in_days = 30
    if payload and isinstance(payload, dict):
        try:
            expires_in_days = int(payload.get("expires_in_days", 30))
        except:
            expires_in_days = 30
    if expires_in_days < 1: expires_in_days = 1
    if expires_in_days > 90: expires_in_days = 90
    token_str = secrets.token_urlsafe(32)
    now_dt = datetime.now(timezone.utc)
    expires_at = now_dt + timedelta(days=expires_in_days)
    st = ShareToken(resource_type="analysis", resource_id=session_id, token=token_str, created_by=current_user.id, role="viewer", expires_at=expires_at, is_active=True, created_at=now_dt, view_count=0)
    db.add(st)
    db.commit()
    db.refresh(st)
    share_url = f"https://app/shared/a/{token_str}"
    return {"share_url": share_url, "token": token_str, "expires_at": st.expires_at.isoformat(), "role": "viewer", "id": st.id}

@shared_analysis_router.get("/a/{token}")
def get_shared_analysis(token: str, db: Session = Depends(get_db)):
    from app.models.models import ShareToken
    now_dt = datetime.now(timezone.utc)
    t = db.query(ShareToken).filter(ShareToken.token==token, ShareToken.resource_type=="analysis", ShareToken.is_active==True).first()
    if not t:
        raise HTTPException(status_code=404, detail="Share link not found or inactive")
    exp = t.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < now_dt:
        raise HTTPException(status_code=404, detail="Share link expired")
    s = db.query(AnalysisSession).filter(AnalysisSession.id==t.resource_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    t.view_count = (t.view_count or 0) + 1
    db.commit()
    msgs = db.query(AnalysisMessage).filter(AnalysisMessage.session_id==s.id).order_by(AnalysisMessage.created_at.asc()).all()
    out_msgs=[]
    for m in msgs:
        out_msgs.append({"id": m.id, "role": m.role, "content": m.content, "generated_code": m.generated_code, "execution_status": m.execution_status, "created_at": m.created_at.isoformat() if m.created_at else None, "results": [{"id": r.id, "result_type": r.result_type, "result_data": r.result_data} for r in m.results], "charts": [{"id": c.id, "chart_type": c.chart_type, "configuration": c.configuration} for c in m.charts]})
    # Never reveal owner info
    return {"id": s.id, "title": s.title, "dataset_id": s.dataset_id, "created_at": s.created_at.isoformat() if s.created_at else None, "messages": out_msgs}

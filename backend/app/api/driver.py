from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import duckdb
import pandas as pd
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User, Dataset, AnalysisMessage, AnalysisSession, Metric
from app.execution.sql import validate_sql, execute_sql

router = APIRouter(prefix="/api/datasets", tags=["driver"])

def ensure_user_dataset(dataset_id: str, user: User, db: Session):
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds or ds.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return ds

def _get_df(dataset: Dataset, db: Session):
    from app.api.cleaning import _get_current_df_and_version
    df, _ = _get_current_df_and_version(dataset, db)
    return df

@router.post("/{dataset_id}/root-cause")
def root_cause(dataset_id: str, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Investigate why a metric changed.
    Payload: {message_id, dimension, metric_col, metric_expression, compare: "previous_period"|"category"}
    If message_id given, we use its executed SQL/result to infer metric.
    Otherwise, metric_expression or metric_col is used.
    Returns drivers ranked by contribution.
    """
    ds = ensure_user_dataset(dataset_id, current_user, db)
    df = _get_df(ds, db)
    message_id = payload.get("message_id")
    dimension = payload.get("dimension")  # column to break down
    metric_col = payload.get("metric_col")
    metric_expression = payload.get("metric_expression")
    # Try to infer from message
    _code = None
    if message_id:
        msg = db.query(AnalysisMessage).filter(AnalysisMessage.id==message_id).first()
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found")
        # Check session belongs to user/dataset
        sess = db.query(AnalysisSession).filter(AnalysisSession.id==msg.session_id).first()
        if not sess or sess.dataset_id != dataset_id or sess.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Not found")
        # Use generated_code to infer metric
        _code = msg.generated_code or ""
        if msg.results and msg.results[0].result_data.get("columns"):
            cols = msg.results[0].result_data.get("columns")
            lower_cols = [c.lower() for c in cols]
            # Special handling for approval_rate multi-dim
            if "approval_rate" in lower_cols:
                # Approval rate segment: use Loan_Status expression and first dimension
                loan_status_col = next((c for c in df.columns if c.lower() == "loan_status"), "Loan_Status")
                metric_expression = metric_expression or f'SUM(CASE WHEN LOWER(TRIM(CAST("{loan_status_col}" AS VARCHAR))) IN (\'y\',\'yes\',\'approved\',\'1\',\'true\') THEN 1 ELSE 0 END) * 100.0 / COUNT(*)'
                # Dimension is first dim if not specified
                dimension = dimension or cols[0]
                # Ensure metric_col not used as alias
                metric_col = metric_col or "approval_rate"
            elif len(cols)>=2:
                dimension = dimension or cols[0]
                metric_col = metric_col or cols[1]
                # Try to extract original aggregation expression from code, not just alias
                if not metric_expression and _code:
                    import re as _re2
                    # Robust extraction: find all alias expressions `expr as alias`
                    # Use pattern that correctly handles commas inside substr etc. by finding the last `, expr as alias` before FROM
                    # Simplify: extract the aggregation by looking for SUM/AVG/COUNT in _code and take the first occurrence with quoted column
                    agg_match = _re2.search(r'(SUM|AVG|COUNT|MIN|MAX|MEDIAN)\s*\(\s*"?([^")]+)"?\s*\)', _code, flags=_re2.IGNORECASE)
                    if agg_match:
                        # Reconstruct correctly quoted expression
                        func = agg_match.group(1).upper()
                        col_inner = agg_match.group(2).strip().strip('"').strip("'")
                        # Verify col_inner is actual column in df, else fallback
                        if col_inner in df.columns:
                            # Preserve original quoting style
                            # Find exact quoted col from _code if possible
                            q_col = f'"{col_inner}"'
                            candidate = f'{func}({q_col})'
                            if func == "COUNT":
                                candidate = "COUNT(*)" if "*" in agg_match.group(0) else candidate
                            metric_expression = candidate
                        else:
                            # col_inner is alias like total_revenue -> try to map alias to real column
                            # Look for real column via searching for SUM("real") before alias
                            # Try alternative: find second aggregation more specifically
                            # Fallback to searching for any quoted column that is in df.columns
                            found = False
                            for c in df.columns:
                                if f'"{c}"' in _code or f"'{c}'" in _code:
                                    # check if this column appears inside an aggregation
                                    if _re2.search(rf'(SUM|AVG|COUNT|MIN|MAX|MEDIAN)\s*\(\s*"{_re2.escape(c)}"\s*\)', _code, flags=_re2.IGNORECASE):
                                        # reconstruct
                                        fm = _re2.search(rf'(SUM|AVG|COUNT|MIN|MAX|MEDIAN)\s*\(\s*"{_re2.escape(c)}"\s*\)', _code, flags=_re2.IGNORECASE)
                                        if fm:
                                            func2 = fm.group(1).upper()
                                            candidate2 = f'{func2}("{c}")' if func2 != "COUNT" else fm.group(0)
                                            metric_expression = candidate2
                                            found = True
                                            break
                            if not found:
                                metric_expression = f'SUM("{metric_col}")' if metric_col in df.columns else f'SUM("{col_inner}")'
                        # Also handle COUNT(*)
                        if "COUNT(*)" in _code.upper():
                            # If metric is count, keep COUNT(*)
                            if metric_col.lower() in ["count","total","cnt"]:
                                metric_expression = "COUNT(*)"
                    else:
                        # No aggregation found, fallback to column sum
                        if metric_col in df.columns:
                            metric_expression = f'SUM("{metric_col}")'
                        else:
                            # try to find any numeric column
                            numeric_cols_tmp = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
                            fallback_col = numeric_cols_tmp[0] if numeric_cols_tmp else metric_col
                            metric_expression = f'SUM("{fallback_col}")'
                elif not metric_expression:
                    if metric_col in df.columns:
                        metric_expression = f'SUM("{metric_col}")'
                    else:
                        # Alias not in df -> try to map to real numeric column
                        numeric_cols_tmp = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
                        fallback_col = numeric_cols_tmp[0] if numeric_cols_tmp else metric_col
                        metric_expression = f'SUM("{fallback_col}")'
            elif len(cols)==1:
                metric_col = cols[0]
                metric_expression = metric_expression or metric_col
    # Need dimension and metric
    if not dimension or not metric_col:
        # Auto-detect: pick first categorical and first numeric
        cols = list(df.columns)
        # numeric
        numeric_cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
        cat_cols = [c for c in cols if c not in numeric_cols]
        if not dimension and cat_cols:
            dimension = cat_cols[0]
        if not metric_col and numeric_cols:
            metric_col = numeric_cols[0]
            metric_expression = f"SUM(\"{metric_col}\")"
        if not dimension or not metric_col:
            raise HTTPException(status_code=400, detail="Could not determine dimension or metric for driver analysis")
    if dimension not in df.columns:
        # Derived alias like month — do not treat as physical column. Prefer existing trend results, otherwise fallback to real dimension.
        # First, check if this is a trend with derived month and we can reuse existing table data
        if dimension.lower() == "month" and _code and "substr" in _code.lower():
            try:
                if msg and msg.results and msg.results[0].result_data.get("columns"):
                    cols_msg = msg.results[0].result_data.get("columns")
                    rows_msg = msg.results[0].result_data.get("rows", [])
                    if any(c.lower() == "month" for c in cols_msg) and len(rows_msg) >= 1:
                        # Build trend-based Why? deterministically from existing results (no SQL regen)
                        import pandas as _pd_trend
                        df_trend = _pd_trend.DataFrame(rows_msg)
                        # Find metric column (first non-month)
                        metric_col_trend = next((c for c in cols_msg if c.lower() != "month"), cols_msg[0])
                        # Ensure sorted by month
                        try:
                            df_trend_sorted = df_trend.sort_values("month")
                        except:
                            df_trend_sorted = df_trend
                        # Strongest/weakest
                        try:
                            max_idx = df_trend[metric_col_trend].astype(float).idxmax()
                            min_idx = df_trend[metric_col_trend].astype(float).idxmin()
                            max_row = df_trend.loc[max_idx]
                            min_row = df_trend.loc[min_idx]
                            strongest_month = str(max_row["month"])
                            strongest_val = float(max_row[metric_col_trend])
                            weakest_month = str(min_row["month"])
                            weakest_val = float(min_row[metric_col_trend])
                            # Latest change
                            if len(df_trend_sorted) >= 2:
                                latest = df_trend_sorted.iloc[-1]
                                prev = df_trend_sorted.iloc[-2]
                                latest_val = float(latest[metric_col_trend])
                                prev_val = float(prev[metric_col_trend])
                                change = latest_val - prev_val
                                pct = (change / prev_val * 100) if prev_val != 0 else 0
                                # Build fallback drivers for real dimension to explain why revenue changed (not just month)
                                fallback_drivers = []
                                fallback_dim = None
                                try:
                                    # Find real categorical dimension
                                    cats = [c for c in df.columns if df[c].dtype == object or str(df[c].dtype) == 'category']
                                    cats = [c for c in cats if "date" not in c.lower() and "time" not in c.lower()]
                                    for cand in ["region","product_id","product","customer_id","customer","category"]:
                                        for c in df.columns:
                                            if c.lower() == cand.lower() or cand.lower() in c.lower():
                                                fallback_dim = c
                                                break
                                        if fallback_dim:
                                            break
                                    if not fallback_dim and cats:
                                        fallback_dim = cats[0]
                                    if fallback_dim:
                                        # Map alias total_revenue -> real column revenue
                                        real_col = None
                                        # Try to find real column that matches metric alias
                                        for c in df.columns:
                                            if c.lower() in metric_col_trend.lower() or metric_col_trend.lower() in c.lower():
                                                real_col = c
                                                break
                                        if not real_col:
                                            for c in df.columns:
                                                if "revenue" in c.lower() or "price" in c.lower() or "amount" in c.lower():
                                                    real_col = c
                                                    break
                                        if real_col:
                                            # Try period contribution for fallback dim
                                            fallback_expr = f'SUM("{real_col}")'
                                            try:
                                                period_res, _ = _try_period_contribution(df, fallback_dim, fallback_expr, "metric_value")
                                                if period_res and period_res.get("per_dimension"):
                                                    for r in period_res["per_dimension"][:3]:
                                                        fallback_drivers.append({
                                                            "dimension_value": r["dimension_value"],
                                                            "metric_value": r["current_value"],
                                                            "contribution_percent": r.get("contribution_pp", r.get("contribution_percent")),
                                                            "previous_value": r.get("previous_value"),
                                                            "absolute_change": r.get("absolute_change")
                                                        })
                                                else:
                                                    sql_fb = f'SELECT "{fallback_dim}", SUM("{real_col}") as metric_value FROM df GROUP BY "{fallback_dim}" ORDER BY metric_value DESC'
                                                    res_fb = execute_sql(df, sql_fb)
                                                    if res_fb.get("success"):
                                                        total_fb = sum(float(x["metric_value"]) for x in res_fb["data"] if x["metric_value"] is not None) or 1
                                                        for x in res_fb["data"][:3]:
                                                            val = float(x["metric_value"]) if x["metric_value"] is not None else 0
                                                            fallback_drivers.append({"dimension_value": str(x[fallback_dim]), "metric_value": val, "contribution_percent": round(val/total_fb*100,1)})
                                            except:
                                                pass
                                except:
                                    pass
                                summary = f"Monthly {metric_col_trend} trend across {len(df_trend)} months. Strongest month is {strongest_month} ({strongest_val}), weakest is {weakest_month} ({weakest_val}). Latest change: {prev['month']} ({prev_val}) → {latest['month']} ({latest_val}) — change {change:+.1f} ({pct:+.1f}% MoM). Peak/trough show volatility, not a statistically inferred trend."
                            else:
                                summary = f"Monthly {metric_col_trend} trend with {len(df_trend)} period(s). Strongest {strongest_month} ({strongest_val}), weakest {weakest_month} ({weakest_val}). Only one period — MoM not applicable."
                            return {
                                "dimension": fallback_dim or "month",
                                "metric": metric_col_trend,
                                "summary": summary,
                                "drivers": fallback_drivers,
                                "primary_drivers": fallback_drivers[:3],
                                "period_info": None,
                                "method": "trend_reuse_existing_with_fallback",
                                "disclaimer": "Trend explanation reused from existing monthly aggregation; drivers show contribution of real dimensions (e.g., region/product) to the metric, association not proven causation.",
                                "sql": _code,
                                "is_trend_reuse": True,
                                "strongest_month": strongest_month,
                                "weakest_month": weakest_month,
                                "fallback_dimension": fallback_dim
                            }
                        except Exception as e:
                            pass
            except Exception:
                pass
        # Fallback to real categorical dimension for driver analysis
        categorical_cols = [c for c in df.columns if df[c].dtype == object or str(df[c].dtype) == 'category']
        categorical_cols = [c for c in categorical_cols if "date" not in c.lower() and "time" not in c.lower()]
        fallback = None
        for cand in ["product_id","product","region","customer_id","customer","category","segment"]:
            for c in df.columns:
                if c.lower() == cand.lower() or cand.lower() in c.lower():
                    if c in df.columns:
                        fallback = c
                        break
            if fallback:
                break
        if not fallback and categorical_cols:
            fallback = categorical_cols[0]
        if fallback:
            dimension = fallback
        else:
            fallback_cols = [c for c in df.columns if c.lower() != dimension.lower() and "date" not in c.lower()]
            if fallback_cols:
                dimension = fallback_cols[0]
            else:
                raise HTTPException(status_code=400, detail=f"Dimension '{dimension}' not found and no fallback categorical available")
    if metric_col not in df.columns and not metric_expression:
        raise HTTPException(status_code=400, detail=f"Metric column '{metric_col}' not found")
    # Determine metric expression if not given: assume SUM(metric_col)
    if not metric_expression:
        metric_expression = f"SUM(\"{metric_col}\")"
    # Route ratio/rate metrics through ratio-aware logic (do not use contribution share)
    lower_expr = metric_expression.lower()
    lower_col = (metric_col or "").lower()
    is_rate = any(kw in lower_expr for kw in ["approval_rate","conversion","retention","churn","margin"]) or "* 100.0 / count" in lower_expr or "approval_rate" in lower_col
    if is_rate:
        # Ratio-aware: compare approval/rate per dimension, not contribution share
        # Determine relevant dimensions
        candidates = ["Gender","Education","Credit_History","Property_Area"]
        dims_actual=[]
        for cand in candidates:
            for col in df.columns:
                if col.lower()==cand.lower():
                    dims_actual.append(col)
                    break
        if not dims_actual:
            dims_actual=[dimension] if dimension in df.columns else []
        loan_status_col = next((c for c in df.columns if c.lower()=="loan_status"), "Loan_Status")
        dimensions_result=[]
        largest_diff=-1
        largest_dim=None
        for dim in dims_actual:
            sql_r = f'SELECT "{dim}", COUNT(*) as n, SUM(CASE WHEN LOWER(TRIM(CAST("{loan_status_col}" AS VARCHAR))) IN (\'y\',\'yes\',\'approved\',\'1\',\'true\') THEN 1 ELSE 0 END) as approved, SUM(CASE WHEN LOWER(TRIM(CAST("{loan_status_col}" AS VARCHAR))) IN (\'y\',\'yes\',\'approved\',\'1\',\'true\') THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as rate FROM df GROUP BY "{dim}" ORDER BY rate DESC'
            valid_r, _ = validate_sql(sql_r)
            if not valid_r:
                continue
            res_r = execute_sql(df, sql_r)
            if not res_r.get("success"):
                continue
            groups=[]
            for r in res_r["data"]:
                v=r[dim]
                if v is None or (isinstance(v,str) and v.strip()==""):
                    label="Missing"
                else:
                    label=str(v)
                    if dim.lower()=="credit_history":
                        label=f"Credit History {label}"
                groups.append({"value":label, "raw_value": v if v is not None else "Missing", "rate": float(r["rate"]) if r["rate"] is not None else 0, "n": int(r["n"]), "approved": int(float(r["approved"])) if r["approved"] is not None else 0})
            if len(groups)>=2:
                diff = groups[0]["rate"] - groups[-1]["rate"]
                dimensions_result.append({"dimension": dim, "groups": groups, "difference_pp": round(diff,1), "largest": False})
                if abs(diff) > largest_diff:
                    largest_diff=abs(diff)
                    largest_dim=dim
        for d in dimensions_result:
            if d["dimension"]==largest_dim:
                d["largest"]=True
        # Build summary with largest observed difference
        if largest_dim and largest_diff>=0:
            summary = f"Approval rates compared across {', '.join(dims_actual)}; largest observed difference is {largest_diff:.1f} percentage points in {largest_dim} (associated, not proven causation)."
        else:
            summary = f"Approval rates compared across {', '.join(dims_actual)} (associated, not causal)."
        return {
            "dimension": largest_dim or (dims_actual[0] if dims_actual else dimension),
            "metric": metric_expression,
            "dimensions": dimensions_result,
            "largest_difference": {"dimension": largest_dim, "difference_pp": round(largest_diff,1)} if largest_dim else None,
            "drivers": [],  # no contribution share for rates
            "primary_drivers": [],
            "summary": summary,
            "sql": f"Rate per dimension for {', '.join(dims_actual)}",
            "disclaimer": "Drivers show observed differences in approval rates by dimension, association not proven causation."
        }
    # Attempt period-over-period contribution if date column exists and payload asks for period logic
    # Helper to compute period contribution
    def _try_period_contribution(df_inner, dim, expr_inner, metric_alias_inner):
        # Detect date column
        date_col = None
        for c in df_inner.columns:
            if "date" in c.lower() or "time" in c.lower():
                try:
                    # check if parseable as datetime for at least 50% rows
                    s = pd.to_datetime(df_inner[c], errors='coerce')
                    if s.notna().mean() > 0.5:
                        date_col = c
                        break
                except:
                    continue
            # also check dtype datetime
            try:
                if pd.api.types.is_datetime64_any_dtype(df_inner[c]):
                    date_col = c
                    break
            except:
                pass
        # payload may contain explicit period info
        period_start = payload.get("period_start")
        period_end = payload.get("period_end")
        prev_start = payload.get("prev_period_start") or payload.get("previous_period_start")
        prev_end = payload.get("prev_period_end") or payload.get("previous_period_end")
        # If no date column, cannot do period
        if not date_col:
            return None, "No date column for period comparison"
        # Try to derive periods
        try:
            df_tmp = df_inner.copy()
            df_tmp["_pd_date"] = pd.to_datetime(df_tmp[date_col], errors='coerce')
            df_tmp = df_tmp.dropna(subset=["_pd_date"])
            if df_tmp.empty or len(df_tmp) < 10:
                return None, "Insufficient dated rows"
            max_date = df_tmp["_pd_date"].max()
            min_date = df_tmp["_pd_date"].min()
            span_days = (max_date - min_date).days
            # Decide period length: if span > 60 days -> month, else week, else days
            if span_days >= 60:
                # month-over-month: current month vs previous month
                current_start = max_date.replace(day=1)
                # previous month start
                if current_start.month == 1:
                    prev_start_dt = current_start.replace(year=current_start.year-1, month=12, day=1)
                else:
                    prev_start_dt = current_start.replace(month=current_start.month-1, day=1)
                # end = last day of month: approximate by current_start - 1 day and prev_start's month end
                import calendar
                curr_end_day = calendar.monthrange(current_start.year, current_start.month)[1]
                current_end = current_start.replace(day=curr_end_day)
                prev_end_day = calendar.monthrange(prev_start_dt.year, prev_start_dt.month)[1]
                prev_end_dt = prev_start_dt.replace(day=prev_end_day)
            elif span_days >= 14:
                # week-over-week: last 7 days vs previous 7 days
                current_start = max_date - pd.Timedelta(days=6)
                current_end = max_date
                prev_start_dt = current_start - pd.Timedelta(days=7)
                prev_end_dt = current_start - pd.Timedelta(days=1)
            else:
                # day-over-day or split half
                mid = len(df_tmp) // 2
                # Use median date as split if span small
                sorted_dates = df_tmp["_pd_date"].sort_values()
                mid_date = sorted_dates.iloc[mid]
                current_start = mid_date
                current_end = max_date
                prev_start_dt = min_date
                prev_end_dt = mid_date - pd.Timedelta(days=1) if mid_date > min_date else mid_date

            # Override if payload provides explicit
            if period_start and period_end:
                try:
                    current_start = pd.to_datetime(period_start)
                    current_end = pd.to_datetime(period_end)
                except:
                    pass
            if prev_start and prev_end:
                try:
                    prev_start_dt = pd.to_datetime(prev_start)
                    prev_end_dt = pd.to_datetime(prev_end)
                except:
                    pass

            # Build filtered dfs
            curr_df = df_tmp[(df_tmp["_pd_date"] >= current_start) & (df_tmp["_pd_date"] <= current_end)]
            prev_df = df_tmp[(df_tmp["_pd_date"] >= prev_start_dt) & (df_tmp["_pd_date"] <= prev_end_dt)]
            if curr_df.empty or prev_df.empty:
                return None, "Period split produced empty segment"
            # Compute overall totals for both periods
            def _compute_total(sub_df):
                try:
                    con = duckdb.connect(":memory:")
                    con.register("df", sub_df.drop(columns=["_pd_date"]))
                    # Need to handle expr: ensure it works on sub_df
                    test_sql = f"SELECT {expr_inner} as metric_value FROM df"
                    # if expr is aggregation, it will return single row; else sum
                    res_df = con.execute(test_sql).fetchdf()
                    con.close()
                    if len(res_df)==0:
                        return 0.0
                    if len(res_df)==1:
                        v = res_df.iloc[0]["metric_value"]
                        return float(v) if v is not None else 0.0
                    else:
                        return float(res_df["metric_value"].sum())
                except:
                    return 0.0
            curr_total = _compute_total(curr_df)
            prev_total = _compute_total(prev_df)
            if prev_total == 0:
                return None, "Previous period total is zero"
            overall_change = curr_total - prev_total
            overall_change_pct = overall_change / abs(prev_total) * 100 if prev_total else 0
            # For each dimension value, compute contribution
            # Need unique dimension values union
            if dim not in df_inner.columns:
                return None, f"Dimension {dim} not found"
            # Compute per-dimension period totals
            per_dim = []
            uniq_vals = pd.concat([curr_df[dim], prev_df[dim]]).dropna().unique()
            # limit to top 20
            per_dim_map = {}
            for val in uniq_vals[:20]:
                # Filter per val
                cv = curr_df[curr_df[dim].astype(str)==str(val)]
                pv = prev_df[prev_df[dim].astype(str)==str(val)]
                cv_total = _compute_total(cv) if not cv.empty else 0.0
                pv_total = _compute_total(pv) if not pv.empty else 0.0
                change = cv_total - pv_total
                # contribution in percentage points of overall change relative to prev_total? Spec: "East contributed 8.2 percentage points of overall decline"
                # Compute contribution_pp = change / abs(prev_total) *100
                contrib_pp = change / abs(prev_total) * 100 if prev_total else 0
                # Also percent change per dimension
                pct_change = change / abs(pv_total) * 100 if pv_total else 0
                per_dim.append({
                    "dimension_value": str(val) if not (pd.isna(val) or str(val).strip()=="") else "Missing",
                    "current_value": float(cv_total),
                    "previous_value": float(pv_total),
                    "absolute_change": round(float(change),2),
                    "percent_change": round(float(pct_change),1) if pv_total else None,
                    "contribution_pp": round(float(contrib_pp),1),
                    "contribution_percent": round(float(contrib_pp),1)
                })
            # Sort by absolute contribution magnitude descending
            per_dim_sorted = sorted(per_dim, key=lambda x: abs(x["contribution_pp"]), reverse=True)
            return {
                "period_info": {
                    "date_column": date_col,
                    "current_period": {"start": str(current_start.date()), "end": str(current_end.date()), "total": round(curr_total,2)},
                    "previous_period": {"start": str(prev_start_dt.date()), "end": str(prev_end_dt.date()), "total": round(prev_total,2)},
                    "overall_change": round(overall_change,2),
                    "overall_change_percent": round(overall_change_pct,1)
                },
                "per_dimension": per_dim_sorted,
                "disclaimer": "Period-over-period attribution; association not proven causation."
            }, None
        except Exception as e:
            return None, f"Period calculation failed: {str(e)[:120]}"

    # Build metric expression safe initialization before period logic (fix UnboundLocalError)
    metric_alias = "metric_value"
    expr = (metric_expression or "").strip()
    if expr and not any(kw in expr.upper() for kw in ["SUM(", "AVG(", "COUNT", "MIN(", "MAX(", "MEDIAN("]):
        # bare column name -> assume SUM
        if expr.strip().startswith('"') or expr.strip().startswith("'"):
            pass
        else:
            # check if it's a column reference
            if expr.strip().lower() in [c.lower() for c in df.columns]:
                expr = f'SUM("{expr.strip().strip(chr(34)).strip(chr(39))}")'
            elif expr:
                expr = f"SUM(\"{expr}\")" if not expr.upper().startswith("SUM") else expr
    # Ensure expr and alias initialized for period path
    # Try period contribution first if requested or if date column exists and metric is additive
    prefer_period = payload.get("prefer_period") is not False  # default prefer
    period_result = None
    period_error = None
    if prefer_period and expr and not is_rate:
        try:
            period_result, period_error = _try_period_contribution(df, dimension, expr, metric_alias)
        except Exception as e:
            period_result = None
            period_error = str(e)

    if period_result is not None:
        # Use period result as primary
        per_dim = period_result["per_dimension"]
        period_info = period_result["period_info"]
        overall_change = period_info["overall_change"]
        overall_change_pct = period_info["overall_change_percent"]
        # Build drivers with period contribution
        drivers=[]
        for r in per_dim:
            drivers.append({
                "dimension_value": r["dimension_value"],
                "metric_value": r["current_value"],
                "previous_value": r["previous_value"],
                "contribution_percent": r["contribution_pp"],
                "contribution_pp": r["contribution_pp"],
                "absolute_change": r["absolute_change"],
                "percent_change": r["percent_change"]
            })
        primary = drivers[:3]
        summary = f"Revenue changed {overall_change_pct:+.1f}% ({period_info['previous_period']['total']:.2f} → {period_info['current_period']['total']:.2f}). " + \
                  f"{primary[0]['dimension_value']} contributed {primary[0]['contribution_pp']:+.1f} percentage points of the overall change." if primary else f"Overall change {overall_change_pct:+.1f}%."
        return {
            "dimension": dimension,
            "metric": metric_expression,
            "total": period_info["current_period"]["total"],
            "previous_total": period_info["previous_period"]["total"],
            "overall_change": overall_change,
            "overall_change_percent": overall_change_pct,
            "period_info": period_info,
            "drivers": drivers,
            "primary_drivers": primary,
            "summary": summary,
            "sql": f"Period-over-period contribution for {dimension} using {metric_expression} grouped by period {period_info['current_period']['start']} vs {period_info['previous_period']['start']}",
            "columns": ["dimension_value","current_value","previous_value","contribution_pp"],
            "disclaimer": "Period-over-period contribution; association not proven causation.",
            "method": "period_over_period"
        }

    # Fallback to contribution share (existing)
    # Build driver SQL: total per dimension (for additive metrics)
    # Use DuckDB to compute: SELECT "dimension", <metric_expression> as metric_value FROM df GROUP BY "dimension" ORDER BY metric_value DESC
    # expr and metric_alias already initialized safely above for period path
    sql = f'SELECT "{dimension}", {expr} as {metric_alias} FROM df GROUP BY "{dimension}" ORDER BY {metric_alias} DESC'
    valid, msg = validate_sql(sql)
    if not valid:
        raise HTTPException(status_code=400, detail=f"Driver SQL invalid: {msg}")
    res = execute_sql(df, sql)
    if not res.get("success"):
        raise HTTPException(status_code=500, detail=res.get("error"))
    data = res["data"]
    columns = res["columns"]
    if not data:
        return {"drivers": [], "message": "No data for driver analysis"}
    total = sum(float(r[metric_alias]) for r in data if r[metric_alias] is not None)
    if total == 0:
        total = 1
    drivers=[]
    # Handle missing label for additive driver as well
    for r in data:
        val = float(r[metric_alias]) if r[metric_alias] is not None else 0.0
        contribution = val / total * 100 if total else 0
        dv=r[dimension]
        if dv is None or (isinstance(dv,str) and dv.strip()==""):
            dv="Missing"
        else:
            dv=str(dv)
        drivers.append({
            "dimension_value": dv,
            "metric_value": val,
            "contribution_percent": round(contribution,1),
            "absolute_change": None,
            "percent_change": None
        })
    primary = drivers[:3]
    summary = f"Among {len(drivers)} {dimension} groups, the largest contributors to {metric_expression} are ranked by share of total."
    if prefer_period and period_error:
        summary += f" (Period-over-period attribution not available: {period_error} — showing contribution analysis, not period-over-period change attribution.)"
    return {
        "dimension": dimension,
        "metric": metric_expression,
        "total": total,
        "drivers": drivers,
        "primary_drivers": primary,
        "summary": summary,
        "sql": sql,
        "columns": columns,
        "disclaimer": "Drivers show contribution/association, not proven causation." if not period_error else "Contribution analysis, not period-over-period change attribution. Association not proven causation.",
        "method": "contribution_share",
        "fallback_reason": period_error
    }

@router.post("/{dataset_id}/root-cause/{message_id}")
def root_cause_by_message(dataset_id: str, message_id: str, payload: dict = {}, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Delegates to main endpoint with message_id
    payload = dict(payload or {})
    payload["message_id"] = message_id
    return root_cause(dataset_id, payload, current_user, db)

# Also support Why? via existing challenge? Keep challenge separate.


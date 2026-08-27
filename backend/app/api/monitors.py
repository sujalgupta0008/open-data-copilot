import duckdb
import pandas as pd
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User, Dataset, Metric, Monitor, AnalysisSession, AnalysisMessage, AnalysisResult
from app.execution.sql import validate_sql

router = APIRouter(prefix="/api/datasets", tags=["monitors"])

def ensure_user_dataset(dataset_id: str, user: User, db: Session):
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds or ds.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return ds

def _detect_time_column(df: pd.DataFrame):
    for c in df.columns:
        if "date" in c.lower() or "time" in c.lower():
            try:
                s = pd.to_datetime(df[c], errors='coerce')
                if s.notna().mean() > 0.5:
                    return c
            except:
                continue
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            return c
    return None

def _execute_metric_value_with_period(dataset: Dataset, metric: Metric, db: Session, monitor: Monitor = None):
    from app.api.cleaning import _get_current_df_and_version
    df, version = _get_current_df_and_version(dataset, db)
    time_col = _detect_time_column(df)
    sql = f"SELECT {metric.sql_expression} as metric_value FROM df"
    # Check if time-aware_period: if time_col exists and monitor comparison is previous_period
    use_period = False
    period_info = {}
    if time_col and monitor is not None:
        # Try period-aware computation
        try:
            df_tmp = df.copy()
            df_tmp["_pd_date"] = pd.to_datetime(df_tmp[time_col], errors='coerce')
            df_tmp = df_tmp.dropna(subset=["_pd_date"])
            if not df_tmp.empty and len(df_tmp) >= 4:
                max_date = df_tmp["_pd_date"].max()
                min_date = df_tmp["_pd_date"].min()
                span_days = (max_date - min_date).days
                # Decide period
                if span_days >= 60:
                    # month-over-month
                    current_start = max_date.replace(day=1)
                    import calendar
                    curr_end_day = calendar.monthrange(current_start.year, current_start.month)[1]
                    current_end = current_start.replace(day=curr_end_day, hour=23, minute=59, second=59)
                    if current_start.month == 1:
                        prev_start = current_start.replace(year=current_start.year-1, month=12, day=1)
                    else:
                        prev_start = current_start.replace(month=current_start.month-1, day=1)
                    prev_end_day = calendar.monthrange(prev_start.year, prev_start.month)[1]
                    prev_end = prev_start.replace(day=prev_end_day, hour=23, minute=59, second=59)
                elif span_days >= 14:
                    current_start = max_date - pd.Timedelta(days=6)
                    current_end = max_date
                    prev_start = current_start - pd.Timedelta(days=7)
                    prev_end = current_start - pd.Timedelta(days=1)
                else:
                    # split half by row order
                    sorted_dates = df_tmp["_pd_date"].sort_values()
                    mid_idx = len(sorted_dates)//2
                    mid_date = sorted_dates.iloc[mid_idx]
                    current_start = mid_date
                    current_end = max_date
                    prev_start = min_date
                    prev_end = mid_date - pd.Timedelta(days=1) if mid_date > min_date else mid_date
                # Ensure not empty
                curr_mask = (df_tmp["_pd_date"] >= current_start) & (df_tmp["_pd_date"] <= current_end)
                prev_mask = (df_tmp["_pd_date"] >= prev_start) & (df_tmp["_pd_date"] <= prev_end)
                curr_df = df_tmp[curr_mask].drop(columns=["_pd_date"])
                prev_df = df_tmp[prev_mask].drop(columns=["_pd_date"])
                if not curr_df.empty and not prev_df.empty:
                    use_period = True
                    # Compute metric for both periods (P1: cleanup + timeout)
                    def _compute(sub):
                        valid, msg = validate_sql(f"SELECT {metric.sql_expression} as metric_value FROM df")
                        if not valid:
                            return 0.0
                        con = None
                        try:
                            con = duckdb.connect(":memory:")
                            try:
                                con.execute("SET statement_timeout='10s'")
                            except Exception:
                                pass
                            con.register("df", sub)
                            res = con.execute(f"SELECT {metric.sql_expression} as metric_value FROM df").fetchdf()
                            if len(res)==0:
                                return 0.0
                            if len(res)==1:
                                v = res.iloc[0]["metric_value"]
                                return float(v) if v is not None else 0.0
                            else:
                                return float(res["metric_value"].sum())
                        except Exception:
                            return 0.0
                        finally:
                            if con is not None:
                                try:
                                    con.close()
                                except Exception:
                                    pass
                    curr_val = _compute(curr_df)
                    prev_val = _compute(prev_df)
                    period_info = {
                        "time_column": time_col,
                        "current_period": {"start": current_start, "end": current_end, "value": curr_val},
                        "previous_period": {"start": prev_start, "end": prev_end, "value": prev_val},
                        "is_time_aware": True
                    }
                    return curr_val, prev_val, period_info, time_col
        except:
            pass
    # Fallback to simple total
    valid, msg = validate_sql(sql)
    if not valid:
        raise HTTPException(status_code=400, detail=f"Invalid metric SQL: {msg}")
    con = None
    try:
        con = duckdb.connect(":memory:")
        try:
            con.execute("SET statement_timeout='10s'")
        except Exception:
            pass
        con.register("df", df)
        res = con.execute(sql).fetchdf()
        if len(res)==0:
            cur = 0.0
        elif len(res)==1:
            cur = float(res.iloc[0]["metric_value"]) if res.iloc[0]["metric_value"] is not None else 0.0
        else:
            cur = float(res["metric_value"].sum())
        # period fallback: use last_value as previous if monitor provided
        prev = monitor.last_value if monitor and monitor.last_value is not None else None
        period_info = {"time_column": time_col, "is_time_aware": False, "note": "Comparison is based on monitor check history." if not time_col else "Insufficient dated rows for period comparison"}
        return cur, prev, period_info, time_col
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to execute metric: {str(e)}")
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass

def _execute_metric_value(dataset: Dataset, metric: Metric, db: Session):
    cur, prev, info, tc = _execute_metric_value_with_period(dataset, metric, db, None)
    return cur

@router.post("/{dataset_id}/monitors")
def create_monitor(dataset_id: str, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    metric_id = payload.get("metric_id")
    if not metric_id:
        raise HTTPException(status_code=400, detail="metric_id required")
    metric = db.query(Metric).filter(Metric.id==metric_id, Metric.dataset_id==dataset_id).first()
    if not metric or metric.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Metric not found")
    threshold = float(payload.get("threshold_percent") or payload.get("threshold") or 10.0)
    frequency = payload.get("frequency") or "daily"
    comparison = payload.get("comparison") or "previous_period"
    if frequency not in ["daily","weekly","manual"]:
        frequency = "daily"
    # New fields
    check_interval_hours = payload.get("check_interval_hours")
    if check_interval_hours is None:
        # map frequency to interval
        freq_map = {"daily":24, "weekly":168, "manual":24}
        check_interval_hours = freq_map.get(frequency, 24)
        # allow explicit interval payload values like 6,12,48
        if payload.get("check_interval") is not None:
            try: check_interval_hours = int(payload.get("check_interval"))
            except: pass
    try:
        check_interval_hours = int(check_interval_hours)
    except:
        check_interval_hours = 24
    if check_interval_hours < 1: check_interval_hours = 1
    if check_interval_hours > 168: check_interval_hours = 168
    notify_email = payload.get("notify_email")
    if notify_email:
        notify_email = notify_email.strip()
        if notify_email and "@" not in notify_email:
            raise HTTPException(status_code=400, detail="Invalid email format")
        if notify_email == "": notify_email = None
    notify_slack = payload.get("notify_slack_webhook") or payload.get("notify_slack") or payload.get("slack_webhook")
    if notify_slack:
        notify_slack = notify_slack.strip()
        if notify_slack and not notify_slack.startswith("https://hooks.slack.com/"):
            raise HTTPException(status_code=400, detail="Invalid slack webhook: must start with https://hooks.slack.com/")
        if notify_slack == "": notify_slack = None
    notify_on_recovery = payload.get("notify_on_recovery")
    if notify_on_recovery is None:
        notify_on_recovery = True
    else:
        notify_on_recovery = bool(notify_on_recovery)
    existing = db.query(Monitor).filter(Monitor.metric_id==metric_id, Monitor.dataset_id==dataset_id, Monitor.user_id==current_user.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Monitor already exists for this metric")
    # Detect time column for storing
    from app.api.cleaning import _get_current_df_and_version
    try:
        df, _ = _get_current_df_and_version(ds, db)
        tc = _detect_time_column(df)
    except:
        tc = None
    monitor = Monitor(user_id=current_user.id, dataset_id=dataset_id, metric_id=metric_id, threshold_percent=threshold, frequency=frequency, comparison=comparison, time_column=tc, check_interval_hours=check_interval_hours, notify_email=notify_email, notify_slack_webhook=notify_slack, notify_on_recovery=notify_on_recovery)
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    return {"id": monitor.id, "metric_id": monitor.metric_id, "threshold_percent": monitor.threshold_percent, "frequency": monitor.frequency, "check_interval_hours": monitor.check_interval_hours, "status": monitor.status, "created_at": monitor.created_at, "time_column": tc, "notify_email": monitor.notify_email, "notify_slack_webhook": monitor.notify_slack_webhook, "notify_on_recovery": monitor.notify_on_recovery}

@router.get("/{dataset_id}/monitors")
def list_monitors(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    monitors = db.query(Monitor).filter(Monitor.dataset_id==dataset_id, Monitor.user_id==current_user.id).order_by(Monitor.created_at.desc()).all()
    out=[]
    for m in monitors:
        metric = db.query(Metric).filter(Metric.id==m.metric_id).first()
        out.append({
            "id": m.id,
            "metric_id": m.metric_id,
            "metric_name": metric.name if metric else None,
            "metric_sql": metric.sql_expression if metric else None,
            "threshold_percent": m.threshold_percent,
            "frequency": m.frequency,
            "check_interval_hours": getattr(m, 'check_interval_hours', 24),
            "comparison": m.comparison,
            "status": m.status,
            "last_status": getattr(m, 'last_status', None),
            "last_value": m.last_value,
            "last_previous_value": m.last_previous_value,
            "last_change_percent": m.last_change_percent,
            "last_checked_at": m.last_checked_at,
            "period_start": m.period_start,
            "period_end": m.period_end,
            "previous_period_start": m.previous_period_start,
            "previous_period_end": m.previous_period_end,
            "time_column": m.time_column,
            "created_at": m.created_at,
            "alert_count": getattr(m, 'alert_count', 0),
            "alert_sent_at": getattr(m, 'alert_sent_at', None),
            "notify_email": getattr(m, 'notify_email', None),
            "notify_slack_webhook": getattr(m, 'notify_slack_webhook', None),
            "notify_on_recovery": getattr(m, 'notify_on_recovery', True)
        })
    return out

@router.get("/{dataset_id}/monitors/{monitor_id}/history")
def get_monitor_history(dataset_id: str, monitor_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models.models import MonitorAlertLog
    ds = ensure_user_dataset(dataset_id, current_user, db)
    monitor = db.query(Monitor).filter(Monitor.id==monitor_id, Monitor.dataset_id==dataset_id).first()
    if not monitor or monitor.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Monitor not found")
    logs = db.query(MonitorAlertLog).filter(MonitorAlertLog.monitor_id==monitor_id).order_by(MonitorAlertLog.checked_at.desc()).limit(50).all()
    out=[]
    for l in logs:
        out.append({"id": l.id, "checked_at": l.checked_at, "status": l.status, "metric_value": l.metric_value, "threshold_value": l.threshold_value, "alert_sent": l.alert_sent, "alert_channels": l.alert_channels, "error_message": l.error_message})
    return out

@router.post("/{dataset_id}/monitors/{monitor_id}/check")
async def run_monitor_check(dataset_id: str, monitor_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    monitor = db.query(Monitor).filter(Monitor.id==monitor_id, Monitor.dataset_id==dataset_id).first()
    if not monitor or monitor.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Monitor not found")
    metric = db.query(Metric).filter(Metric.id==monitor.metric_id).first()
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")
    current_value, previous_period_value, period_info, time_col = _execute_metric_value_with_period(ds, metric, db, monitor)
    # Determine previous value: if time-aware, use previous period value; else use last_value history
    is_time_aware = period_info.get("is_time_aware", False)
    if is_time_aware:
        previous = previous_period_value
        period_start = period_info["current_period"]["start"]
        period_end = period_info["current_period"]["end"]
        prev_start = period_info["previous_period"]["start"]
        prev_end = period_info["previous_period"]["end"]
    else:
        previous = monitor.last_value
        period_start = None
        period_end = None
        prev_start = None
        prev_end = None
    change_pct = None
    status = "healthy"
    if previous is not None and previous != 0:
        change_pct = (current_value - previous) / abs(previous) * 100
        if change_pct < -abs(monitor.threshold_percent):
            status = "alert"
        # Also alert if big increase? Spec focuses on decrease but we alert on absolute exceed? Use decrease only for alert per spec, else healthy
        # Keep alert only for decrease beyond threshold to match spec
        if change_pct < -abs(monitor.threshold_percent):
            status = "alert"
        else:
            status = "healthy"
    # For first run with time-aware, previous may be set so we can still compute
    previous_status = getattr(monitor, 'last_status', None) or monitor.status
    monitor.last_previous_value = previous
    monitor.last_value = current_value
    monitor.last_change_percent = change_pct if change_pct is not None else 0.0
    monitor.status = status
    monitor.last_status = status
    monitor.last_checked_at = datetime.now(timezone.utc)
    if is_time_aware:
        monitor.period_start = period_start
        monitor.period_end = period_end
        monitor.previous_period_start = prev_start
        monitor.previous_period_end = prev_end
        monitor.time_column = time_col
        # store dataset version
        from app.api.cleaning import _get_current_df_and_version
        try:
            _, ver = _get_current_df_and_version(ds, db)
            monitor.dataset_version = ver.id if ver else None
        except:
            pass
    else:
        # Still store dataset version
        from app.api.cleaning import _get_current_df_and_version
        try:
            _, ver = _get_current_df_and_version(ds, db)
            monitor.dataset_version = ver.id if ver else None
        except:
            pass
    db.commit()
    db.refresh(monitor)
    # Alert handling and history log
    from app.models.models import MonitorAlertLog
    import os
    is_recovery = previous_status == "alert" and status == "healthy" and getattr(monitor, 'notify_on_recovery', True)
    log_status = "recovery" if is_recovery else status
    should_alert = status == "alert" or is_recovery
    alert_sent = False
    channels = []
    if should_alert:
        if getattr(monitor, 'notify_email', None):
            email = monitor.notify_email
            if email and "@" in email and "." in email.split("@")[-1]:
                try:
                    from app.services.email_service import send_alert_email, build_alert_email
                    subject, html = build_alert_email(metric.name, ds.name, current_value, monitor.threshold_percent, log_status, datetime.now(timezone.utc).isoformat(), os.getenv("APP_URL", "https://app"))
                    sent = await send_alert_email(email, subject, html)
                    if sent:
                        alert_sent = True
                        channels.append("email")
                except Exception:
                    pass
        if getattr(monitor, 'notify_slack_webhook', None):
            webhook = monitor.notify_slack_webhook
            if webhook and webhook.startswith("https://hooks.slack.com/"):
                try:
                    from app.services.slack_service import send_monitor_alert_slack
                    sent = await send_monitor_alert_slack(webhook, {"dataset_name": ds.name, "metric_name": metric.name, "current_value": current_value, "threshold": monitor.threshold_percent, "status": log_status, "app_url": os.getenv("APP_URL", "https://app"), "dataset_id": ds.id})
                    if sent:
                        alert_sent = True
                        channels.append("slack")
                except Exception:
                    pass
        if status == "alert":
            try:
                monitor.alert_sent_at = datetime.now(timezone.utc)
                monitor.alert_count = (getattr(monitor, 'alert_count', 0) or 0) + 1
                db.commit()
                db.refresh(monitor)
            except:
                pass
    # Create alert log
    try:
        log = MonitorAlertLog(monitor_id=monitor.id, dataset_id=monitor.dataset_id, user_id=monitor.user_id, checked_at=datetime.now(timezone.utc), status=log_status, metric_value=current_value, threshold_value=monitor.threshold_percent, alert_sent=alert_sent, alert_channels=channels, error_message=None)
        db.add(log)
        db.commit()
    except Exception:
        try: db.rollback()
        except: pass
    alert_msg = None
    if status=="alert":
        if is_time_aware:
            alert_msg = f"{metric.name} decreased {abs(change_pct):.1f}% since the previous period ({previous:.2f} → {current_value:.2f})."
        else:
            alert_msg = f"{metric.name} decreased {abs(change_pct):.1f}% compared with the previous period ({previous:.2f} → {current_value:.2f})."
    # Build response with period info
    resp = {
        "monitor_id": monitor.id,
        "metric_name": metric.name,
        "status": monitor.status,
        "current_value": current_value,
        "previous_value": previous,
        "change_percent": change_pct,
        "threshold_percent": monitor.threshold_percent,
        "last_checked_at": monitor.last_checked_at,
        "alert": alert_msg,
        "is_time_aware": is_time_aware,
        "period_start": str(period_start) if period_start else None,
        "period_end": str(period_end) if period_end else None,
        "previous_period_start": str(prev_start) if prev_start else None,
        "previous_period_end": str(prev_end) if prev_end else None,
        "time_column": time_col,
        "dataset_version": monitor.dataset_version,
        "comparison_note": "Time-aware period comparison" if is_time_aware else "Comparison is based on monitor check history."
    }
    return resp

@router.post("/{dataset_id}/monitors/{monitor_id}/investigate")
def investigate_monitor(dataset_id: str, monitor_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    monitor = db.query(Monitor).filter(Monitor.id==monitor_id, Monitor.dataset_id==dataset_id).first()
    if not monitor or monitor.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Monitor not found")
    metric = db.query(Metric).filter(Metric.id==monitor.metric_id).first()
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")
    # Need at least one check run
    if monitor.last_value is None:
        raise HTTPException(status_code=400, detail="Run a check before investigating")
    # Build investigation context
    from app.api.cleaning import _get_current_df_and_version
    df, version = _get_current_df_and_version(ds, db)
    time_col = monitor.time_column or _detect_time_column(df)
    # Determine relevant dimensions from metric
    dimensions = metric.dimensions or []
    if not dimensions:
        # Use categorical columns
        dims = [c for c in df.columns if df[c].dtype == object][:3]
        dimensions = dims
    context = {
        "metric_name": metric.name,
        "metric_definition": metric.sql_expression,
        "previous_value": monitor.last_previous_value,
        "current_value": monitor.last_value,
        "change_percent": monitor.last_change_percent,
        "change_detected": monitor.status == "alert",
        "threshold_percent": monitor.threshold_percent,
        "relevant_dimensions": dimensions,
        "dataset_version": monitor.dataset_version or (version.id if version else None),
        "time_column": time_col,
        "period_start": str(monitor.period_start) if monitor.period_start else None,
        "period_end": str(monitor.period_end) if monitor.period_end else None,
        "previous_period_start": str(monitor.previous_period_start) if monitor.previous_period_start else None,
        "previous_period_end": str(monitor.previous_period_end) if monitor.previous_period_end else None,
        "is_time_aware": bool(monitor.period_start),
        "dataset_id": dataset_id,
        "monitor_id": monitor_id,
        "available_historical_context": {
            "last_checked_at": str(monitor.last_checked_at) if monitor.last_checked_at else None,
            "status": monitor.status
        }
    }
    # Run driver analysis for each dimension (period-aware)
    drivers_results = []
    for dim in dimensions[:3]:
        if dim not in df.columns:
            continue
        try:
            from app.api.driver import root_cause as _rc
            # Build payload with period info for period-over-period
            payload = {
                "dimension": dim,
                "metric_col": None,
                "metric_expression": metric.sql_expression,
                "prefer_period": True,
                "period_start": context["period_start"],
                "period_end": context["period_end"],
                "prev_period_start": context["previous_period_start"],
                "prev_period_end": context["previous_period_end"]
            }
            # Call root_cause internal without HTTP: reuse logic via direct function call? We'll simulate by calling same logic using df
            # For simplicity, call via internal helper: we duplicate period logic - use driver endpoint logic by calling function directly with mocked request
            # Instead, we will call the driver function directly via import and pass dataset
            # Create a synthetic call
            from fastapi.testclient import TestClient
            # Instead of HTTP, we manually compute using same helper as monitors period contribution
            # Use fallback: call root_cause via direct logic by constructing a mini driver computation
            # For now, we attempt to use the driver's period contribution directly
            drv = None
            try:
                # Directly compute via driver's internal _try_period_contribution by invoking root_cause logic
                # We'll instantiate a temporary call to driver root_cause with current_user and db but need to mock payload
                # Simpler: directly call the driver's business: we will compute period contribution similar to driver
                from app.execution.sql import execute_sql, validate_sql
                # Use driver's method: we'll call the endpoint function with proper dataset
                drv = _rc(dataset_id, {"dimension": dim, "metric_expression": metric.sql_expression, "period_start": context["period_start"], "period_end": context["period_end"], "prev_period_start": context["previous_period_start"], "prev_period_end": context["previous_period_end"]}, current_user, db)
            except Exception as e:
                drv = {"dimension": dim, "error": str(e)[:200], "drivers": []}
            drivers_results.append(drv)
        except Exception as e:
            drivers_results.append({"dimension": dim, "error": str(e)[:200]})

    # Pick primary drivers (largest absolute contribution)
    primary_dim = None
    if drivers_results:
        # Find the one with largest contribution_pp
        best = None
        best_val = 0
        for dr in drivers_results:
            if dr.get("primary_drivers"):
                val = abs(dr["primary_drivers"][0].get("contribution_pp") or dr["primary_drivers"][0].get("contribution_percent",0))
                if val > best_val:
                    best_val = val
                    best = dr
        primary_dim = best

    # Statistical validation where applicable: try to run a proportion or mean test on metric change?
    # For generic metric, we can attempt to validate change significance by treating values as sample? We skip if not applicable.
    statistical_validation = {"applicable": False, "reason": "Monitor metric change is time-series; significance requires underlying row-level distribution"}
    # If metric is rate-like (approval), we could validate
    if "approval" in metric.name.lower() or "rate" in metric.name.lower():
        try:
            from app.data_engine.statistical import validate_result
            # Build synthetic rows for validation: need to simulate approval rate comparison between periods
            # Approximate by using df filtered to periods
            if time_col and context["period_start"]:
                df_tmp = df.copy()
                df_tmp["_pd_date"] = pd.to_datetime(df_tmp[time_col], errors='coerce')
                curr_mask = (df_tmp["_pd_date"] >= pd.to_datetime(context["period_start"])) & (df_tmp["_pd_date"] <= pd.to_datetime(context["period_end"]))
                prev_mask = (df_tmp["_pd_date"] >= pd.to_datetime(context["previous_period_start"])) & (df_tmp["_pd_date"] <= pd.to_datetime(context["previous_period_end"]))
                curr_df = df_tmp[curr_mask]
                prev_df = df_tmp[prev_mask]
                # Compute rates if Loan_Status exists
                loan_col = next((c for c in df.columns if c.lower()=="loan_status"), None)
                if loan_col:
                    def _rate(sub):
                        n = len(sub)
                        if n==0:
                            return 0
                        approved = sub[loan_col].astype(str).str.strip().str.lower().isin(['y','yes','approved','1','true']).sum()
                        return approved / n
                    curr_p = _rate(curr_df)
                    prev_p = _rate(prev_df)
                    # Build validation input as two rows
                    rows_synth = [{"approval_rate": curr_p*100, "application_count": len(curr_df)}, {"approval_rate": prev_p*100, "application_count": len(prev_df)}]
                    statistical_validation = validate_result(df, f"Approval rate change {prev_p*100:.1f}% vs {curr_p*100:.1f}%", "SELECT approval_rate", ["approval_rate","application_count"], rows_synth, len(df))
        except:
            pass

    # Build insight (handle None previous)
    change_pct = monitor.last_change_percent or 0
    direction = "decreased" if change_pct <0 else "increased"
    prev_str = f"{monitor.last_previous_value:.2f}" if monitor.last_previous_value is not None else "—"
    curr_str = f"{monitor.last_value:.2f}" if monitor.last_value is not None else "—"
    insight = f"{metric.name} {direction} {abs(change_pct):.1f}% since previous check ({prev_str} -> {curr_str})."
    if primary_dim and primary_dim.get("primary_drivers"):
        top = primary_dim["primary_drivers"][0]
        insight += f" Primary driver: {top.get('dimension_value')} contributed {top.get('contribution_pp', top.get('contribution_percent')):+.1f} pp."

    # Recommendation
    from app.data_engine.recommendation import recommendation_for_monitor
    recommendation = recommendation_for_monitor({
        "metric_name": metric.name,
        "current_value": monitor.last_value,
        "previous_value": monitor.last_previous_value,
        "change_percent": monitor.last_change_percent,
        "threshold_percent": monitor.threshold_percent,
        "status": monitor.status,
        "period_start": context["period_start"],
        "period_end": context["period_end"],
        "time_column": time_col
    }, statistical_validation, primary_dim)

    # Save investigation to Analysis History (create session)
    try:
        session = AnalysisSession(user_id=current_user.id, dataset_id=dataset_id, title=f"Investigation: {metric.name} {direction} {abs(change_pct):.1f}%")
        db.add(session)
        db.flush()
        user_msg_content = f"Investigate why {metric.name} {direction} {abs(change_pct):.1f}% (threshold {monitor.threshold_percent}%). Metric: {metric.sql_expression} Time-aware: {context['is_time_aware']}"
        user_msg = AnalysisMessage(session_id=session.id, role="user", content=user_msg_content, generated_code=f"SELECT {metric.sql_expression} FROM df", execution_status="success")
        db.add(user_msg)
        db.flush()
        assistant_content = insight + f"\n\nRecommendation: {recommendation['recommendation']}\n\nRationale: {recommendation['rationale']}"
        assistant_msg = AnalysisMessage(session_id=session.id, role="assistant", content=assistant_content, generated_code=f"SELECT {metric.sql_expression} as metric_value FROM df -- investigation", execution_status="success")
        db.add(assistant_msg)
        db.flush()
        # Save evidence as results
        ev_data = {
            "metric_name": metric.name,
            "metric_definition": metric.sql_expression,
            "current_value": monitor.last_value,
            "previous_value": monitor.last_previous_value,
            "change_percent": monitor.last_change_percent,
            "period_start": context["period_start"],
            "period_end": context["period_end"],
            "drivers": drivers_results,
            "statistical_validation": statistical_validation,
            "recommendation": recommendation,
            "context": context
        }
        res = AnalysisResult(message_id=assistant_msg.id, result_type="table", result_data={"columns": ["metric","current","previous","change_pct"], "rows": [{"metric": metric.name, "current": monitor.last_value, "previous": monitor.last_previous_value, "change_pct": monitor.last_change_percent}], "investigation_context": ev_data})
        db.add(res)
        # Store statistical and recommendation as separate types
        stat_res = AnalysisResult(message_id=assistant_msg.id, result_type="statistical_validation", result_data=statistical_validation)
        db.add(stat_res)
        rec_res = AnalysisResult(message_id=assistant_msg.id, result_type="recommendation", result_data=recommendation)
        db.add(rec_res)
        db.commit()
        db.refresh(session)
        session_id = session.id
        message_id = assistant_msg.id
    except Exception as e:
        db.rollback()
        session_id = None
        message_id = None

    return {
        "investigation_context": context,
        "change_detected": context["change_detected"],
        "drivers": drivers_results,
        "primary_driver": primary_dim,
        "statistical_validation": statistical_validation,
        "insight": insight,
        "recommendation": recommendation,
        "history": {"session_id": session_id, "message_id": message_id},
        "alert": f"{metric.name} {direction} {abs(change_pct):.1f}% since previous check."
    }

@router.delete("/{dataset_id}/monitors/{monitor_id}")
def delete_monitor(dataset_id: str, monitor_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    m = db.query(Monitor).filter(Monitor.id==monitor_id, Monitor.dataset_id==dataset_id).first()
    if not m or m.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Monitor not found")
    db.delete(m)
    db.commit()
    return {"message": "Monitor deleted"}

@router.get("/{dataset_id}/monitors/{monitor_id}")
def get_monitor(dataset_id: str, monitor_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    m = db.query(Monitor).filter(Monitor.id==monitor_id, Monitor.dataset_id==dataset_id).first()
    if not m or m.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Monitor not found")
    metric = db.query(Metric).filter(Metric.id==m.metric_id).first()
    return {
        "id": m.id,
        "metric_name": metric.name if metric else None,
        "threshold_percent": m.threshold_percent,
        "status": m.status,
        "last_value": m.last_value,
        "last_change_percent": m.last_change_percent,
        "last_checked_at": m.last_checked_at,
        "period_start": m.period_start,
        "period_end": m.period_end,
        "previous_period_start": m.previous_period_start,
        "previous_period_end": m.previous_period_end,
        "time_column": m.time_column,
        "dataset_version": m.dataset_version
    }

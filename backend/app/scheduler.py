import os
import logging
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.models import Monitor, Dataset, Metric, MonitorAlertLog
from app.services.email_service import send_alert_email, build_alert_email
from app.services.slack_service import send_monitor_alert_slack

logger = logging.getLogger("scheduler")
scheduler = AsyncIOScheduler(timezone="UTC")

async def run_single_monitor_check(monitor_id: str):
    db: Session = SessionLocal()
    try:
        monitor = db.query(Monitor).filter(Monitor.id == monitor_id).first()
        if not monitor:
            return
        dataset = db.query(Dataset).filter(Dataset.id == monitor.dataset_id).first()
        metric = db.query(Metric).filter(Metric.id == monitor.metric_id).first()
        if not dataset or not metric:
            logger.warning(f"Monitor {monitor_id} missing dataset/metric")
            return
        # reuse monitor check logic
        from app.api.monitors import _execute_metric_value_with_period
        try:
            current_value, previous_value, period_info, time_col = _execute_metric_value_with_period(dataset, metric, db, monitor)
        except Exception as e:
            # log error
            log = MonitorAlertLog(monitor_id=monitor.id, dataset_id=monitor.dataset_id, user_id=monitor.user_id, checked_at=datetime.now(timezone.utc), status="error", metric_value=None, threshold_value=monitor.threshold_percent, alert_sent=False, alert_channels=[], error_message=str(e)[:500])
            db.add(log)
            monitor.last_checked_at = datetime.now(timezone.utc)
            monitor.last_status = "error"
            db.commit()
            logger.info(f"Monitor {monitor.id}: error {e}")
            return

        is_time_aware = period_info.get("is_time_aware", False)
        if is_time_aware:
            previous = previous_value
            current = current_value
        else:
            previous = monitor.last_value
            current = current_value

        change_pct = None
        status = "healthy"
        if previous is not None and previous != 0:
            try:
                change_pct = (current - previous) / abs(previous) * 100
                if change_pct < -abs(monitor.threshold_percent):
                    status = "alert"
                else:
                    status = "healthy"
            except:
                status = "healthy"
        else:
            # first run, no previous, treat as healthy unless we have time-aware previous
            if is_time_aware and previous is not None:
                # already computed
                pass
            else:
                status = "healthy"

        previous_status = monitor.last_status or monitor.status
        # Determine if recovery
        is_recovery = False
        if previous_status == "alert" and status == "healthy" and monitor.notify_on_recovery:
            is_recovery = True
            log_status = "recovery"
        else:
            log_status = status

        # Update monitor fields
        monitor.last_checked_at = datetime.now(timezone.utc)
        monitor.last_status = status
        monitor.status = status
        monitor.last_value = current
        if previous is not None:
            monitor.last_previous_value = previous
            monitor.last_change_percent = change_pct if change_pct is not None else 0.0
        # For time-aware, also update period fields
        if is_time_aware:
            try:
                monitor.period_start = period_info["current_period"]["start"]
                monitor.period_end = period_info["current_period"]["end"]
                monitor.previous_period_start = period_info["previous_period"]["start"]
                monitor.previous_period_end = period_info["previous_period"]["end"]
                monitor.time_column = time_col
            except:
                pass

        alert_sent = False
        channels = []
        should_alert = status == "alert" or is_recovery
        if should_alert:
            # Email
            if monitor.notify_email:
                try:
                    # validate email basic
                    if "@" in monitor.notify_email and "." in monitor.notify_email.split("@")[-1]:
                        app_url = os.getenv("APP_URL", "https://app")
                        subject, html = build_alert_email(metric.name, dataset.name, current, monitor.threshold_percent, log_status, datetime.now(timezone.utc).isoformat(), app_url)
                        sent = await send_alert_email(monitor.notify_email, subject, html)
                        if sent:
                            alert_sent = True
                            channels.append("email")
                    else:
                        logger.warning(f"Invalid email {monitor.notify_email} for monitor {monitor.id}")
                except Exception as e:
                    logger.warning(f"Email alert failed for {monitor.id}: {e}")
            # Slack
            if monitor.notify_slack_webhook:
                try:
                    if monitor.notify_slack_webhook.startswith("https://hooks.slack.com/"):
                        app_url = os.getenv("APP_URL", "https://app")
                        sent = await send_monitor_alert_slack(monitor.notify_slack_webhook, {
                            "dataset_name": dataset.name,
                            "metric_name": metric.name,
                            "current_value": current,
                            "threshold": monitor.threshold_percent,
                            "status": log_status,
                            "app_url": app_url,
                            "dataset_id": dataset.id
                        })
                        if sent:
                            alert_sent = True
                            channels.append("slack")
                    else:
                        logger.warning(f"Invalid slack webhook for monitor {monitor.id}")
                except Exception as e:
                    logger.warning(f"Slack alert failed for {monitor.id}: {e}")
            if status == "alert":
                monitor.alert_sent_at = datetime.now(timezone.utc)
                monitor.alert_count = (monitor.alert_count or 0) + 1

        # Log
        log = MonitorAlertLog(
            monitor_id=monitor.id,
            dataset_id=monitor.dataset_id,
            user_id=monitor.user_id,
            checked_at=datetime.now(timezone.utc),
            status=log_status,
            metric_value=current,
            threshold_value=monitor.threshold_percent,
            alert_sent=alert_sent,
            alert_channels=channels,
            error_message=None
        )
        db.add(log)
        db.commit()
        logger.info(f"Monitor {monitor.id}: {log_status} value={current} threshold={monitor.threshold_percent} alert_sent={alert_sent}")
    except Exception as e:
        logger.warning(f"Scheduler error for monitor {monitor_id}: {e}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        try:
            db.close()
        except Exception:
            pass

async def run_all_monitor_checks():
    # P1: proper session lifecycle — open, fetch ids, close in finally before fan-out
    db: Session = SessionLocal()
    ids: list[str] = []
    try:
        monitors = db.query(Monitor).all()
        ids = [m.id for m in monitors]
    except Exception as e:
        logger.warning(f"Failed to fetch monitors for cron: {e}")
        ids = []
    finally:
        try:
            db.close()
        except Exception:
            pass
    # Each monitor check opens/closes its own session (run_single_monitor_check) to avoid
    # long-lived session across async boundaries and to ensure isolation per monitor.
    for mid in ids:
        try:
            await run_single_monitor_check(mid)
        except Exception as e:
            logger.warning(f"Failed monitor {mid}: {e}")
            continue

def start_scheduler():
    if scheduler.running:
        return
    interval = int(os.getenv("MONITOR_CHECK_INTERVAL_HOURS", "24"))
    if interval < 1: interval = 1
    if interval > 168: interval = 168
    scheduler.add_job(run_all_monitor_checks, IntervalTrigger(hours=interval, timezone="UTC"), id="monitor_checks", replace_existing=True, max_instances=1, coalesce=True)
    try:
        scheduler.start()
        logger.info(f"Scheduler started with interval {interval}h")
    except Exception as e:
        logger.warning(f"Scheduler start failed: {e}")

def shutdown_scheduler():
    try:
        if scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("Scheduler shutdown")
    except:
        pass

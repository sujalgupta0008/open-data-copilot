from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User, Dataset, Metric, Monitor, Report, AnalysisSession, Transformation, DatasetVersion
from app.data_engine.profiler import load_dataframe, profile_dataframe

router = APIRouter(prefix="/api/datasets", tags=["workflow"])

def ensure_user_dataset(dataset_id: str, user: User, db: Session):
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds or ds.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return ds

@router.get("/{dataset_id}/workflow")
def get_workflow(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    # Determine states
    versions = db.query(DatasetVersion).filter(DatasetVersion.dataset_id==dataset_id).all()
    transformations = db.query(Transformation).filter(Transformation.dataset_id==dataset_id, Transformation.undone==False).count()
    metrics = db.query(Metric).filter(Metric.dataset_id==dataset_id, Metric.user_id==current_user.id).count()
    sessions = db.query(AnalysisSession).filter(AnalysisSession.dataset_id==dataset_id, AnalysisSession.user_id==current_user.id).count()
    from app.models.models import AnalysisMessage
    # count assistant messages
    analysis_count = db.query(AnalysisMessage).join(AnalysisSession, AnalysisMessage.session_id==AnalysisSession.id).filter(AnalysisSession.dataset_id==dataset_id, AnalysisSession.user_id==current_user.id, AnalysisMessage.role=="assistant").count()
    reports = db.query(Report).filter(Report.dataset_id==dataset_id, Report.user_id==current_user.id).count()
    monitors = db.query(Monitor).filter(Monitor.dataset_id==dataset_id, Monitor.user_id==current_user.id).count()
    # Profile for health
    try:
        from app.api.cleaning import _get_current_df_and_version
        df, _ = _get_current_df_and_version(ds, db)
        prof = profile_dataframe(df)
        quality = prof["quality_score"]
        row_count = prof["row_count"]
    except:
        quality = ds.quality_score or 0
        row_count = ds.row_count or 0
    uploaded = True
    profiled = True
    data_health = True
    cleaned = transformations > 0 or len(versions) > 1
    insights = sessions > 0
    has_analysis = analysis_count > 0
    has_reports = reports > 0
    has_monitoring = monitors > 0
    return {
        "dataset_id": dataset_id,
        "steps": {
            "uploaded": {"completed": uploaded, "detail": f"{row_count} rows"},
            "profiled": {"completed": profiled, "detail": f"{quality}/100"},
            "data_health": {"completed": data_health, "detail": f"Quality {quality}/100"},
            "cleaned": {"completed": cleaned, "detail": f"{transformations} transformations, {len(versions)} versions"},
            "metrics": {"completed": metrics>0, "count": metrics, "detail": f"{metrics} defined"},
            "insights": {"completed": insights, "count": sessions, "detail": f"{sessions} sessions"},
            "analysis": {"completed": has_analysis, "count": analysis_count, "detail": f"{analysis_count} completed"},
            "reports": {"completed": has_reports, "count": reports, "detail": f"{reports} generated"},
            "monitoring": {"completed": has_monitoring, "count": monitors, "detail": f"{monitors} active"}
        },
        "quality_score": quality,
        "row_count": row_count
    }

@router.get("/{dataset_id}/next-action")
def get_next_action(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    wf = get_workflow(dataset_id, current_user, db)
    steps = wf["steps"]
    # Determine next action based on state - contextual
    # Priority order
    if not steps["cleaned"]["completed"] and wf["quality_score"] < 90:
        return {"action": "review_data_health", "title": "Your data has quality issues", "description": f"Quality {wf['quality_score']}/100 —  Review Data Health", "cta": "Open Cleaning Studio", "href": f"/datasets/{dataset_id}/clean", "priority": "high"}
    if steps["cleaned"]["completed"] and not steps["metrics"]["completed"] and not steps["insights"]["completed"]:
        return {"action": "explore", "title": f"Quality improved to {wf['quality_score']}/100", "description": "Recommended: Explore your dataset", "cta": "Open Copilot", "href": f"/datasets/{dataset_id}/copilot", "priority": "medium"}
    if steps["metrics"]["count"]==0 and steps["analysis"]["count"]>0:
        # after insight, suggest metric
        return {"action": "define_metric", "title": "Save important metrics", "description": "Recommended: Define a metric like Revenue for reuse", "cta": "Define Metric", "href": f"/datasets/{dataset_id}#metrics", "priority": "medium"}
    if steps["analysis"]["count"]>0 and not steps["reports"]["completed"]:
        return {"action": "create_report", "title": "Analysis completed", "description": "Recommended: Create a report", "cta": "Create Report", "href": "/reports", "priority": "medium"}
    if steps["monitoring"]["count"]>0:
        # check if any monitor alert
        monitors = db.query(Monitor).filter(Monitor.dataset_id==dataset_id, Monitor.user_id==current_user.id, Monitor.status=="alert").first()
        if monitors:
            metric = db.query(Metric).filter(Metric.id==monitors.metric_id).first()
            return {"action": "investigate_alert", "title": f"{metric.name} changed significantly" if metric else "Monitor alert", "description": "Recommended: Investigate drivers", "cta": "Investigate Why", "href": f"/datasets/{dataset_id}/copilot", "priority": "high"}
    if not steps["insights"]["completed"]:
        return {"action": "explore", "title": "No insights yet", "description": "Recommended: Ask Copilot a question", "cta": "Ask Copilot", "href": f"/datasets/{dataset_id}/copilot", "priority": "medium"}
    if steps["metrics"]["completed"] and not steps["monitoring"]["completed"]:
        return {"action": "monitor", "title": "Metric saved", "description": "Recommended: Monitor an important metric", "cta": "Monitor Metric", "href": f"/datasets/{dataset_id}#monitors", "priority": "low"}
    return {"action": "ask_copilot", "title": "Ready for next question", "description": "Ask Copilot what you want to know", "cta": "Open Copilot", "href": f"/datasets/{dataset_id}/copilot", "priority": "low"}


from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User, Dataset, AnalysisSession, Report, Transformation, DatasetVersion

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

@router.get("/stats")
def get_stats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    total_datasets = db.query(func.count(Dataset.id)).filter(Dataset.user_id==current_user.id).scalar() or 0
    total_analyses = db.query(func.count(AnalysisSession.id)).filter(AnalysisSession.user_id==current_user.id).scalar() or 0
    total_reports = db.query(func.count(Report.id)).filter(Report.user_id==current_user.id).scalar() or 0
    avg_quality = db.query(func.avg(Dataset.quality_score)).filter(Dataset.user_id==current_user.id).scalar() or 0
    # cleaning operations count
    total_cleaning_ops = db.query(func.count(Transformation.id)).join(Dataset, Transformation.dataset_id==Dataset.id).filter(Dataset.user_id==current_user.id).scalar() or 0
    # dataset health breakdown
    healthy = db.query(func.count(Dataset.id)).filter(Dataset.user_id==current_user.id, Dataset.quality_score>=80).scalar() or 0
    attention = db.query(func.count(Dataset.id)).filter(Dataset.user_id==current_user.id, Dataset.quality_score>=50, Dataset.quality_score<80).scalar() or 0
    critical = db.query(func.count(Dataset.id)).filter(Dataset.user_id==current_user.id, Dataset.quality_score<50).scalar() or 0
    recent_datasets = db.query(Dataset).filter(Dataset.user_id==current_user.id).order_by(Dataset.created_at.desc()).limit(5).all()
    recent_sessions = db.query(AnalysisSession).filter(AnalysisSession.user_id==current_user.id).order_by(AnalysisSession.updated_at.desc()).limit(5).all()
    # recent activity timeline
    recent_activities = []
    for d in recent_datasets[:3]:
        recent_activities.append({"type": "dataset_upload", "title": f"Uploaded {d.name}", "timestamp": d.created_at, "dataset_id": d.id})
    for s in recent_sessions[:3]:
        recent_activities.append({"type": "analysis", "title": s.title, "timestamp": s.updated_at, "session_id": s.id})
    recent_activities = sorted(recent_activities, key=lambda x: x["timestamp"], reverse=True)[:5]
    return {
        "total_datasets": total_datasets,
        "total_analyses": total_analyses,
        "total_reports": total_reports,
        "avg_quality": round(float(avg_quality),1) if avg_quality else 0,
        "total_cleaning_ops": total_cleaning_ops,
        "dataset_health": {"healthy": healthy, "attention": attention, "critical": critical},
        "recent_datasets": recent_datasets,
        "recent_analyses": [{"id": s.id, "title": s.title, "dataset_id": s.dataset_id, "updated_at": s.updated_at} for s in recent_sessions],
        "recent_activity": recent_activities
    }

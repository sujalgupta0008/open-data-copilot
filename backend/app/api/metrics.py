import re
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User, Dataset, Metric
from app.data_engine.profiler import load_dataframe
from app.execution.sql import validate_sql

router = APIRouter(prefix="/api/datasets", tags=["metrics"])

def ensure_user_dataset(dataset_id: str, user: User, db: Session):
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds or ds.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return ds

def _validate_metric_sql(dataset: Dataset, sql_expression: str, db: Session):
    # Try to validate by constructing SELECT
    if not sql_expression or not sql_expression.strip():
        raise HTTPException(status_code=400, detail="sql_expression required")
    # Basic forbidden check
    forbidden = ["DROP","DELETE","UPDATE","INSERT","ALTER","TRUNCATE","CREATE","GRANT","REVOKE","ATTACH","DETACH","COPY","PRAGMA"]
    up = sql_expression.upper()
    for kw in forbidden:
        if re.search(rf"\b{kw}\b", up):
            raise HTTPException(status_code=400, detail=f"Forbidden operation in metric: {kw}")
    # Try DuckDB execution on current df
    try:
        from app.api.cleaning import _get_current_df_and_version
        df, _ = _get_current_df_and_version(dataset, db)
        # wrap
        test_sql = f"SELECT {sql_expression} as metric_value FROM df LIMIT 1"
        valid, msg = validate_sql(test_sql)
        if not valid:
            raise HTTPException(status_code=400, detail=f"Invalid metric expression: {msg}")
        import duckdb
        con = duckdb.connect(":memory:")
        con.register("df", df)
        con.execute(test_sql).fetchdf()
        con.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Metric expression failed on dataset: {str(e)}")

@router.post("/{dataset_id}/metrics")
def create_metric(dataset_id: str, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    name = (payload.get("name") or "").strip()
    sql_expression = (payload.get("sql_expression") or payload.get("formula") or "").strip()
    description = payload.get("description") or payload.get("Definition") or ""
    dimensions = payload.get("dimensions") or []
    time_grain = payload.get("time_grain")
    filters = payload.get("filters")
    if not name:
        raise HTTPException(status_code=400, detail="Metric name required")
    if not sql_expression:
        raise HTTPException(status_code=400, detail="sql_expression required")
    # uniqueness per dataset
    existing = db.query(Metric).filter(Metric.dataset_id==dataset_id, Metric.name.ilike(name)).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Metric '{name}' already exists for this dataset")
    _validate_metric_sql(ds, sql_expression, db)
    metric = Metric(user_id=current_user.id, dataset_id=dataset_id, name=name, description=description, sql_expression=sql_expression, dimensions=dimensions, time_grain=time_grain, filters=filters, created_by=current_user.email)
    db.add(metric)
    db.commit()
    db.refresh(metric)
    return {"id": metric.id, "name": metric.name, "description": metric.description, "sql_expression": metric.sql_expression, "dimensions": metric.dimensions, "time_grain": metric.time_grain, "filters": metric.filters, "version": metric.version, "created_at": metric.created_at, "updated_at": metric.updated_at}

@router.get("/{dataset_id}/metrics")
def list_metrics(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    metrics = db.query(Metric).filter(Metric.dataset_id==dataset_id).order_by(Metric.created_at.desc()).all()
    return [{"id": m.id, "name": m.name, "description": m.description, "sql_expression": m.sql_expression, "dimensions": m.dimensions, "time_grain": m.time_grain, "filters": m.filters, "version": m.version, "created_at": m.created_at, "updated_at": m.updated_at, "created_by": m.created_by} for m in metrics]

@router.get("/{dataset_id}/metrics/{metric_id}")
def get_metric(dataset_id: str, metric_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    m = db.query(Metric).filter(Metric.id==metric_id, Metric.dataset_id==dataset_id).first()
    if not m or m.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Metric not found")
    return {"id": m.id, "name": m.name, "description": m.description, "sql_expression": m.sql_expression, "dimensions": m.dimensions, "time_grain": m.time_grain, "filters": m.filters, "version": m.version, "created_at": m.created_at, "updated_at": m.updated_at}

@router.put("/{dataset_id}/metrics/{metric_id}")
def update_metric(dataset_id: str, metric_id: str, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    m = db.query(Metric).filter(Metric.id==metric_id, Metric.dataset_id==dataset_id).first()
    if not m or m.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Metric not found")
    if "name" in payload and payload["name"] != m.name:
        # check uniqueness
        existing = db.query(Metric).filter(Metric.dataset_id==dataset_id, Metric.name.ilike(payload["name"]), Metric.id != metric_id).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Metric '{payload['name']}' already exists")
        m.name = payload["name"].strip()
    if "description" in payload:
        m.description = payload["description"]
    if "sql_expression" in payload or "formula" in payload:
        expr = (payload.get("sql_expression") or payload.get("formula") or "").strip()
        if expr and expr != m.sql_expression:
            _validate_metric_sql(ds, expr, db)
            m.sql_expression = expr
            m.version += 1
    if "dimensions" in payload:
        m.dimensions = payload["dimensions"]
    if "time_grain" in payload:
        m.time_grain = payload["time_grain"]
    if "filters" in payload:
        m.filters = payload["filters"]
    db.commit()
    db.refresh(m)
    return {"id": m.id, "name": m.name, "description": m.description, "sql_expression": m.sql_expression, "dimensions": m.dimensions, "time_grain": m.time_grain, "filters": m.filters, "version": m.version, "created_at": m.created_at, "updated_at": m.updated_at}

@router.delete("/{dataset_id}/metrics/{metric_id}")
def delete_metric(dataset_id: str, metric_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    m = db.query(Metric).filter(Metric.id==metric_id, Metric.dataset_id==dataset_id).first()
    if not m or m.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Metric not found")
    db.delete(m)
    db.commit()
    return {"message": "Metric deleted"}


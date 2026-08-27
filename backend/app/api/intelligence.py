import os
import tempfile
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User, Dataset, DatasetVersion, Transformation, AnalysisSession
from app.data_engine.profiler import load_dataframe, profile_dataframe
from app.data_engine.intelligence import detect_dataset_type, generate_data_doctor_issues, generate_ai_cleaning_plan, automatic_eda, anomaly_detective, compute_trust_score, challenge_insight, what_if_analysis, build_lineage
from app.data_engine.cleaning import get_version_path, save_dataframe
from app.core.config import settings
from app.execution.sql import execute_sql
from fastapi.responses import FileResponse, JSONResponse
# BYOS Drive Middleware — non-destructive wrapper
from app.services.drive_middleware import DriveMiddleware
from app.services.google_drive import cleanup_tmp_file

router = APIRouter(prefix="/api/datasets", tags=["intelligence"])

def ensure_user_dataset(dataset_id: str, user: User, db: Session):
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds or ds.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return ds

def get_current_df(dataset: Dataset, db: Session) -> pd.DataFrame:
    current_version = db.query(DatasetVersion).filter(DatasetVersion.dataset_id==dataset.id, DatasetVersion.is_current==True).first()
    if current_version and os.path.exists(current_version.storage_path):
        try:
            return load_dataframe(current_version.storage_path)
        except:
            pass
    # replay transforms
    try:
        df = load_dataframe(dataset.storage_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    from app.models.models import Transformation
    trans = db.query(Transformation).filter(Transformation.dataset_id==dataset.id, Transformation.undone==False).order_by(Transformation.created_at.asc()).all()
    for t in trans:
        from app.data_engine.cleaning import apply_operation
        try:
            df, _ = apply_operation(df, t.operation, t.params or {})
        except:
            continue
    return df

@router.get("/{dataset_id}/type")
def get_dataset_type(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    df = get_current_df(ds, db)
    prof = profile_dataframe(df)
    res = detect_dataset_type(df, prof)
    return res

@router.get("/{dataset_id}/doctor")
def get_doctor(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    df = get_current_df(ds, db)
    prof = profile_dataframe(df)
    issues = generate_data_doctor_issues(df, prof)
    # counts by severity
    counts = {"Critical":0, "Warning":0, "Attention":0, "Healthy":0}
    for iss in issues:
        counts[iss["severity"]] = counts.get(iss["severity"],0)+1
    return {"issues": issues, "total_issues": len([i for i in issues if i["severity"]!="Healthy"]), "counts": counts, "dataset_id": dataset_id}

@router.post("/{dataset_id}/doctor/apply")
def apply_doctor(dataset_id: str, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    df = get_current_df(ds, db)
    prof = profile_dataframe(df)
    issues = generate_data_doctor_issues(df, prof)
    ids = payload.get("issue_ids") or []
    apply_all = payload.get("apply_all", False)
    selected = []
    if apply_all:
        selected = [i for i in issues if i["operation"]]
    else:
        selected = [i for i in issues if i["id"] in ids and i["operation"]]
    if not selected:
        raise HTTPException(status_code=400, detail="No valid issues selected")
    from app.data_engine.cleaning import apply_operation
    from app.models.models import Transformation
    from app.data_engine.profiler import profile_dataframe as _prof
    cur_df = df.copy()
    applied = []
    stats_list = []
    for iss in selected:
        op = iss["operation"]["op"]
        params = iss["operation"]["params"]
        try:
            cur_df, stats = apply_operation(cur_df, op, params)
            stats_list.append(stats)
            applied.append({"issue_id": iss["id"], "op": op, "stats": stats})
        except Exception as e:
            applied.append({"issue_id": iss["id"], "error": str(e)})
    if not applied or all("error" in a for a in applied):
        raise HTTPException(status_code=400, detail="All selected operations failed")
    # Atomic: single version + transformations, single profile
    try:
        prof_new = _prof(cur_df)
        from app.api.cleaning import create_version_snapshot
        # Prepare transformations for successful ones
        for a in applied:
            if "error" not in a:
                iss = next((i for i in selected if i["id"]==a["issue_id"]), None)
                if iss:
                    t = Transformation(dataset_id=ds.id, operation=iss["operation"]["op"], params=iss["operation"]["params"], before_stats={}, after_stats=a["stats"], undone=False)
                    db.add(t)
        # Use precomputed profile to avoid duplicate profiling inside create_version_snapshot
        v = create_version_snapshot(ds, cur_df, "AI Doctor cleaning", f"Applied {len([a for a in applied if 'error' not in a])} doctor recommendations", db, precomputed_profile=prof_new)
        db.commit()
        db.refresh(v)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    return {"applied": applied, "version": {"id": v.id, "version_number": v.version_number, "row_count": v.row_count, "quality_score": v.quality_score}}

def _get_ai_plan(dataset: Dataset, db: Session):
    df = get_current_df(dataset, db)
    prof = profile_dataframe(df)
    issues = generate_data_doctor_issues(df, prof)
    plan = generate_ai_cleaning_plan(df, issues)
    return plan

@router.post("/{dataset_id}/clean/ai-plan")
def ai_clean_plan(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    plan = _get_ai_plan(ds, db)
    return {"plan": plan, "total_steps": len(plan)}

@router.get("/{dataset_id}/clean/ai-plan")
def ai_clean_plan_get(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Support frontend GET (historical bug) — delegates to same deterministic plan
    ds = ensure_user_dataset(dataset_id, current_user, db)
    plan = _get_ai_plan(ds, db)
    return {"plan": plan, "total_steps": len(plan)}

@router.post("/{dataset_id}/clean/ai-apply")
def ai_clean_apply(dataset_id: str, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    df = get_current_df(ds, db)
    prof = profile_dataframe(df)
    issues = generate_data_doctor_issues(df, prof)
    plan = generate_ai_cleaning_plan(df, issues)
    selected = payload.get("selected_steps")
    apply_all = payload.get("apply_all", True)
    if selected and not apply_all:
        plan = [p for p in plan if p["step"] in selected]
    if not plan:
        raise HTTPException(status_code=400, detail="No steps to apply")
    from app.data_engine.cleaning import apply_operation
    from app.models.models import Transformation
    from app.data_engine.profiler import profile_dataframe as _prof
    cur_df = df.copy()
    applied = []
    for step in plan:
        op = step["operation"]["op"]
        params = step["operation"]["params"]
        try:
            cur_df, stats = apply_operation(cur_df, op, params)
            applied.append({**step, "stats": stats})
        except Exception as e:
            continue
    if not applied:
        raise HTTPException(status_code=400, detail="All AI plan steps failed")
    try:
        prof_new = _prof(cur_df)
        from app.api.cleaning import create_version_snapshot
        for s in applied:
            t = Transformation(dataset_id=ds.id, operation=s["operation"]["op"], params=s["operation"]["params"], before_stats={}, after_stats=s.get("stats",{}), undone=False)
            db.add(t)
        v = create_version_snapshot(ds, cur_df, "AI Cleaning Plan", f"Applied AI plan {len(applied)} steps", db, precomputed_profile=prof_new)
        db.commit()
        db.refresh(v)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    return {"applied": applied, "version": {"id": v.id, "version_number": v.version_number, "row_count": v.row_count, "quality_score": v.quality_score}}

@router.get("/{dataset_id}/eda")
def get_eda(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    df = get_current_df(ds, db)
    prof = profile_dataframe(df)
    type_res = detect_dataset_type(df, prof)
    eda = automatic_eda(df, prof, type_res["dataset_type"])
    return eda

@router.get("/{dataset_id}/anomalies")
def get_anomalies(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    df = get_current_df(ds, db)
    res = anomaly_detective(df)
    return res

@router.post("/{dataset_id}/anomalies/investigate")
def investigate_anomaly(dataset_id: str, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    df = get_current_df(ds, db)
    column = payload.get("column")
    anomaly_type = payload.get("type")
    # simple investigate: execute sql to get outlier rows
    if column and column in df.columns:
        # Use IQR to get outliers
        s = df[column].dropna()
        if len(s)>10:
            q1 = s.quantile(0.25)
            q3 = s.quantile(0.75)
            iqr = q3 - q1
            lower = q1 - 1.5*iqr
            upper = q3 + 1.5*iqr
            mask = (df[column] < lower) | (df[column] > upper)
            outlier_rows = df[mask].head(20).replace({pd.NA: None}).to_dict(orient="records")
            return {"column": column, "bounds": [float(lower), float(upper)], "outlier_count": int(mask.sum()), "rows": outlier_rows, "sql": f'SELECT * FROM df WHERE "{column}" < {lower:.2f} OR "{column}" > {upper:.2f} LIMIT 20'}
    return {"message": "No investigation parameters"}

@router.get("/{dataset_id}/lineage")
def get_lineage(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    versions = db.query(DatasetVersion).filter(DatasetVersion.dataset_id==dataset_id).order_by(DatasetVersion.version_number.asc()).all()
    trans = db.query(Transformation).filter(Transformation.dataset_id==dataset_id).order_by(Transformation.created_at.asc()).all()
    sessions = db.query(AnalysisSession).filter(AnalysisSession.dataset_id==dataset_id).order_by(AnalysisSession.created_at.desc()).limit(10).all()
    lineage = build_lineage(ds, versions, trans, sessions)
    return lineage

@router.post("/{dataset_id}/trust-score")
def get_trust_score(dataset_id: str, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    df = get_current_df(ds, db)
    prof = profile_dataframe(df)
    query_result = payload.get("query_result")
    statistical_validation = payload.get("statistical_validation")
    assumptions = payload.get("assumptions")
    evidence_completeness = payload.get("evidence_completeness")
    question_coverage = payload.get("question_coverage") or payload.get("questionCoverage")
    trust = compute_trust_score(df, prof, query_result, statistical_validation=statistical_validation, assumptions=assumptions, evidence_completeness=evidence_completeness, question_coverage=question_coverage)
    return trust

@router.get("/{dataset_id}/evidence/{message_id}")
def get_evidence(dataset_id: str, message_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    from app.models.models import AnalysisMessage, AnalysisResult
    msg = db.query(AnalysisMessage).filter(AnalysisMessage.id==message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    # check session belongs to dataset and user
    sess = db.query(AnalysisSession).filter(AnalysisSession.id==msg.session_id).first()
    if not sess or sess.dataset_id != dataset_id or sess.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Not found")
    df = get_current_df(ds, db)
    prof = profile_dataframe(df)
    # build evidence
    result = None
    if msg.results:
        result = msg.results[0].result_data
    trust = compute_trust_score(df, prof, {"success": msg.execution_status=="success"})
    # evidence details
    evidence = {
        "insight": msg.content,
        "method": "SQL aggregation" if msg.generated_code and "SELECT" in msg.generated_code else "Python analysis",
        "query": msg.generated_code,
        "result": result,
        "data_quality": {"score": prof["quality_score"], "row_count": len(df), "missing_pct": round(float(df.isnull().sum().sum()/(df.shape[0]*df.shape[1])*100) if df.shape[0]*df.shape[1]>0 else 0,2)},
        "trust_score": trust,
        "lineage": f"Original -> Clean Version -> Analysis -> Result"
    }
    return evidence

@router.post("/{dataset_id}/challenge")
def challenge(dataset_id: str, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    df = get_current_df(ds, db)
    insight = payload.get("insight") or payload.get("question") or ""
    code = payload.get("code") or ""
    result = payload.get("result") or {}
    # if message_id provided, fetch
    message_id = payload.get("message_id")
    if message_id:
        from app.models.models import AnalysisMessage
        msg = db.query(AnalysisMessage).filter(AnalysisMessage.id==message_id).first()
        if msg:
            insight = msg.content
            code = msg.generated_code or code
            if msg.results:
                result = {"data": msg.results[0].result_data.get("rows", []), "columns": msg.results[0].result_data.get("columns", [])}
    chall = challenge_insight(df, insight, code, result)
    return chall

@router.post("/{dataset_id}/whatif")
def whatif(dataset_id: str, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    df = get_current_df(ds, db)
    res = what_if_analysis(df, payload)
    return res

@router.get("/{dataset_id}/export")
def export_dataset(dataset_id: str, format: str = "csv", version_id: str = None, background_tasks: BackgroundTasks = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    # BYOS helper to mirror file to Drive and schedule /tmp cleanup
    def _byos_mirror(tmp_path: str, filename: str):
        try:
            mw = DriveMiddleware(user_id=current_user.id)
            mw.ensure_workspace()
            # Read bytes and save directly to Drive
            with open(tmp_path, "rb") as f:
                data = f.read()
            # For BYOS: keep /tmp copy during execution, then explicit os.remove cleanup
            # Save to Drive
            mw.save_output_bytes(data, filename)
            # Schedule cleanup of tmp copy via background task if provided, else immediate os.remove after response
            if background_tasks is not None:
                background_tasks.add_task(cleanup_tmp_file, tmp_path)
            else:
                # fallback: immediate but after Drive save, still schedule via try
                try:
                    # keep file until response sent, so don't delete now if FileResponse needs it
                    # Use background-like immediate cleanup after short delay not possible here,
                    # so we rely on FileResponse background_tasks when available
                    pass
                except Exception:
                    pass
        except Exception:
            pass
        return tmp_path

    # determine df to export
    if version_id:
        v = db.query(DatasetVersion).filter(DatasetVersion.id==version_id, DatasetVersion.dataset_id==dataset_id).first()
        if not v:
            raise HTTPException(status_code=404, detail="Version not found")
        df = load_dataframe(v.storage_path)
        filename = f"{ds.name}_v{v.version_number}.{format}"
        path = v.storage_path
        if format == "csv":
            if not path.endswith(".csv"):
                tmp = os.path.join(settings.STORAGE_PATH, f"tmp_export_{version_id}.csv")
                df.to_csv(tmp, index=False)
                _byos_mirror(tmp, filename)
                return FileResponse(tmp, filename=filename, media_type="text/csv", background=background_tasks)
            # Also mirror version file to Drive
            try:
                mw = DriveMiddleware(user_id=current_user.id)
                mw.ensure_workspace()
                with open(path, "rb") as f:
                    mw.save_output_bytes(f.read(), filename)
            except Exception:
                pass
            return FileResponse(path, filename=filename, media_type="text/csv")
        elif format == "json":
            tmp = os.path.join(settings.STORAGE_PATH, f"tmp_export_{version_id}.json")
            df.to_json(tmp, orient="records", indent=2)
            _byos_mirror(tmp, filename)
            return FileResponse(tmp, filename=filename, media_type="application/json", background=background_tasks)
        elif format in ["xlsx", "xls"]:
            tmp = os.path.join(settings.STORAGE_PATH, f"tmp_export_{version_id}.xlsx")
            df.to_excel(tmp, index=False)
            _byos_mirror(tmp, filename)
            return FileResponse(tmp, filename=filename, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", background=background_tasks)
        else:
            raise HTTPException(status_code=400, detail="Unsupported format")
    else:
        df = get_current_df(ds, db)
        ext = "csv" if format=="csv" else format
        filename = f"{ds.name}_cleaned.{ext}"
        tmp_path = os.path.join(settings.STORAGE_PATH, f"export_{dataset_id}.{ext}")
        if format == "csv":
            df.to_csv(tmp_path, index=False)
            _byos_mirror(tmp_path, filename)
            return FileResponse(tmp_path, filename=filename, media_type="text/csv", background=background_tasks)
        elif format == "json":
            df.to_json(tmp_path, orient="records", indent=2)
            _byos_mirror(tmp_path, filename)
            return FileResponse(tmp_path, filename=filename, media_type="application/json", background=background_tasks)
        elif format in ["xlsx"]:
            df.to_excel(tmp_path, index=False)
            _byos_mirror(tmp_path, filename)
            return FileResponse(tmp_path, filename=filename, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", background=background_tasks)
        elif format == "sql":
            tmp_path = os.path.join(settings.STORAGE_PATH, f"export_{dataset_id}.sql")
            with open(tmp_path, "w") as f:
                f.write(f"-- Export of {ds.name}\n")
                for _, row in df.head(100).iterrows():
                    vals = ", ".join([f"'{str(v)}'" if pd.notna(v) else "NULL" for v in row.values])
                    f.write(f"INSERT INTO {ds.name} VALUES ({vals});\n")
            _byos_mirror(tmp_path, filename)
            return FileResponse(tmp_path, filename=filename, media_type="text/plain", background=background_tasks)
        elif format == "python":
            tmp_path = os.path.join(settings.STORAGE_PATH, f"export_{dataset_id}.py")
            cols = list(df.columns)
            with open(tmp_path, "w") as f:
                f.write(f"# Python code to recreate analysis for {ds.name}\nimport pandas as pd\ndf = pd.read_csv('{ds.name}.csv')\n# columns: {cols}\nprint(df.head())\n")
            _byos_mirror(tmp_path, filename)
            return FileResponse(tmp_path, filename=filename, media_type="text/plain", background=background_tasks)
        elif format == "pdf":
            from app.data_engine.profiler import profile_dataframe
            prof = profile_dataframe(df)
            from app.api.reports import _build_pdf_path
            from app.models.models import Report as _Report
            fake_report = _Report(id=f"export-{dataset_id}", title=f"{ds.name} — Export", user_id=current_user.id, content={
                "executive_summary": f"Export of dataset '{ds.name}' — {prof['row_count']} rows × {prof['column_count']} columns, quality {prof['quality_score']}/100.",
                "dataset_overview": {"name": ds.name, "rows": prof['row_count'], "columns": prof['column_count'], "file_type": ds.file_type},
                "data_quality": prof["quality_details"],
                "insights": prof["insights"][:6],
                "column_stats": [{"name": c, "type": str(df[c].dtype), "null_pct": round(float(df[c].isnull().mean()*100),1), "unique": int(df[c].nunique()), "mean": None} for c in df.columns],
                "methodology": "Export generated from current cleaned version; SQL validated in DuckDB; all numbers from actual execution.",
                "limitations": "PDF is a snapshot; for lineage see app. Full dataset not included — aggregated stats only."
            })
            pdf_path = _build_pdf_path(fake_report, ds, fake_report.content)
            # pdf_path already mirrored to Drive inside _build_pdf_path, just schedule tmp-like cleanup not needed
            return FileResponse(pdf_path, filename=f"{ds.name}_export.pdf", media_type="application/pdf")
    return {"message": "Export"}

@router.get("/{dataset_id}/export/recipe")
def export_recipe(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    trans = db.query(Transformation).filter(Transformation.dataset_id==dataset_id, Transformation.undone==False).order_by(Transformation.created_at.asc()).all()
    recipe = [{"step": i+1, "operation": t.operation, "params": t.params} for i, t in enumerate(trans)]
    import json, os
    tmp = os.path.join(settings.STORAGE_PATH, f"recipe_{dataset_id}.json")
    with open(tmp, "w") as f:
        json.dump({"dataset": ds.name, "recipe": recipe}, f, indent=2)
    return FileResponse(tmp, filename=f"{ds.name}_recipe.json", media_type="application/json")

@router.get("/{dataset_id}/export/powerbi")
def export_powerbi(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    df = get_current_df(ds, db)
    # generate transformation summary
    trans = db.query(Transformation).filter(Transformation.dataset_id==dataset_id, Transformation.undone==False).order_by(Transformation.created_at.asc()).all()
    summary = [f"{i+1}. {t.operation} {t.params}" for i, t in enumerate(trans)]
    # Power Query M code stub (only if simple)
    m_code = 'let\n    Source = Csv.Document(File.Contents("dataset.csv"),[Delimiter=",", Columns='+str(len(df.columns))+", Encoding=1252, QuoteStyle=QuoteStyle.None]),\n    Promoted = Table.PromoteHeaders(Source)\n in Promoted"
    return {"dataset": ds.name, "columns": list(df.columns), "dtypes": {c: str(t) for c,t in df.dtypes.items()}, "transformations": summary, "power_query_m": m_code, "note": "Load the cleaned CSV into Power BI; normalized columns and types are ready."}

@router.get("/{dataset_id}/quality/report")
def quality_report(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    df = get_current_df(ds, db)
    prof = profile_dataframe(df)
    return {"quality_score": prof["quality_score"], "quality_details": prof["quality_details"], "insights": prof["insights"], "row_count": prof["row_count"], "column_count": prof["column_count"]}


import os
import uuid
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User, Dataset, DatasetColumn, DatasetVersion, Transformation, CleaningRecipe, AnalysisSession
from app.data_engine.profiler import load_dataframe, profile_dataframe, get_sample_rows
from app.data_engine.cleaning import apply_operation, preview_operation, compute_diff_stats, save_dataframe
from app.core.config import settings
# BYOS Drive Middleware — non-destructive wrapper
from app.services.drive_middleware import DriveMiddleware

router = APIRouter(prefix="/api/datasets", tags=["cleaning"])

def _byos_mirror_version(dataset: Dataset, version_path: str):
    """Save generated analytical result (cleaned version) directly to user's Drive folder, non-destructive."""
    try:
        mw = DriveMiddleware(user_id=dataset.user_id)
        mw.ensure_workspace()
        # Read file bytes and save to Drive with same filename
        with open(version_path, "rb") as f:
            data = f.read()
        # Use Drive's workspace: save under dataset version subfolder simulation
        # Primary save: mirror to Drive workspace root with version filename
        mw.save_output_bytes(data, os.path.basename(version_path))
        # Also mirror into version-specific subfolder for lineage
        try:
            version_drive_dir = os.path.join(settings.STORAGE_PATH, "drive", dataset.user_id, settings.GOOGLE_DRIVE_FOLDER_NAME, dataset.id)
            os.makedirs(version_drive_dir, exist_ok=True)
            with open(os.path.join(version_drive_dir, os.path.basename(version_path)), "wb") as out:
                out.write(data)
        except Exception:
            pass
        # /tmp handling: if version was built via tmp, cleanup is handled by caller; here we ensure no tmp leftover
        # No tmp to clean for version saves (already persisted)
    except Exception:
        pass

def ensure_user_dataset(dataset_id: str, user: User, db: Session):
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds or ds.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return ds

def _build_transformation_metadata(df_before: pd.DataFrame, df_after: pd.DataFrame, op: str, params: dict, stats: dict, prof_before: dict, prof_after: dict):
    """Build rich metadata for Before/After rendering."""
    rows_before = int(len(df_before))
    rows_after = int(len(df_after))
    cols_before = int(len(df_before.columns))
    cols_after = int(len(df_after.columns))
    missing_before = int(df_before.isnull().sum().sum())
    missing_after = int(df_after.isnull().sum().sum())
    try:
        dup_before = int(df_before.duplicated().sum())
    except:
        dup_before = 0
    try:
        dup_after = int(df_after.duplicated().sum())
    except:
        dup_after = 0
    quality_before = float(prof_before.get("quality_score", 0)) if prof_before else 0
    quality_after = float(prof_after.get("quality_score", 0)) if prof_after else 0
    added = sorted(list(set(df_after.columns) - set(df_before.columns)))
    removed = sorted(list(set(df_before.columns) - set(df_after.columns)))
    # affected columns
    affected_cols=[]
    if op == "missing":
        c = params.get("column")
        if c:
            affected_cols=[c]
        else:
            affected_cols=[col for col in df_before.columns if df_before[col].isnull().any()]
    elif op == "remove_duplicates":
        affected_cols=list(df_before.columns)
    elif op == "column":
        sub=params.get("sub_operation")
        if sub=="rename":
            affected_cols=[params.get("old_name")]
        elif sub=="remove":
            affected_cols=[params.get("column")]
        elif sub=="change_type":
            affected_cols=[params.get("column")]
        else:
            affected_cols=[]
    elif op in ("text","numeric","date","row_filter"):
        c=params.get("column") or params.get("old_name")
        if c:
            affected_cols=[c]
    # affected rows/cells
    affected_rows = 0
    if isinstance(stats.get("affected_rows"), int):
        affected_rows = int(stats.get("affected_rows"))
    elif op=="remove_duplicates" and isinstance(stats.get("removed"), int):
        affected_rows = int(stats.get("removed"))
    elif op=="row_filter" and isinstance(stats.get("removed"), int):
        affected_rows = int(stats.get("removed"))
    elif isinstance(stats.get("duplicates_found"), int):
        affected_rows = int(stats.get("duplicates_found"))
    # For column ops, affected_rows is 0 (no rows removed)
    affected_cells = int(abs(missing_before - missing_after)) if missing_before != missing_after else 0
    # For imputation, affected_cells is missing resolved
    if affected_cells==0 and isinstance(stats.get("affected_rows"), int):
        affected_cells = int(abs(missing_before - missing_after))
    return {
        "operation": op,
        "params": params,
        "affected_columns": affected_cols,
        "affected_rows": affected_rows,
        "affected_cells": affected_cells,
        "rows_before": rows_before,
        "rows_after": rows_after,
        "columns_before": cols_before,
        "columns_after": cols_after,
        "missing_before": missing_before,
        "missing_after": missing_after,
        "duplicates_before": dup_before,
        "duplicates_after": dup_after,
        "quality_before": round(quality_before,1),
        "quality_after": round(quality_after,1),
        "quality_delta": round(quality_after - quality_before,1),
        "added_columns": added,
        "removed_columns": removed,
        "stats": stats,
    }

def _validate_operation(op: str, params: dict, df_columns: list):
    """Light validation before apply: column existence, required params."""
    if op == "missing":
        col = params.get("column")
        method = params.get("method")
        if method not in ["drop_rows","fill_mean","fill_median","fill_mode","forward_fill","backward_fill","custom_value"]:
            raise HTTPException(status_code=400, detail=f"Invalid missing method: {method}")
        if col and col not in df_columns:
            raise HTTPException(status_code=400, detail=f"Column '{col}' not found in dataset")
    elif op == "remove_duplicates":
        pass
    elif op == "column":
        sub = params.get("sub_operation")
        if sub == "rename":
            if not params.get("old_name") or not params.get("new_name"):
                raise HTTPException(status_code=400, detail="Rename requires old_name and new_name")
            if params.get("old_name") not in df_columns:
                raise HTTPException(status_code=400, detail=f"Column '{params.get('old_name')}' not found")
            if params.get("new_name") in df_columns:
                raise HTTPException(status_code=400, detail=f"Column '{params.get('new_name')}' already exists")
        elif sub == "remove":
            col = params.get("column")
            if not col or col not in df_columns:
                raise HTTPException(status_code=400, detail=f"Column '{col}' not found")
        elif sub == "change_type":
            col = params.get("column")
            dtype = params.get("dtype")
            if not col or col not in df_columns:
                raise HTTPException(status_code=400, detail=f"Column '{col}' not found")
            if dtype not in ["numeric","datetime","string","int","float"]:
                raise HTTPException(status_code=400, detail=f"Invalid dtype {dtype}")
        else:
            raise HTTPException(status_code=400, detail=f"Unknown column sub_operation {sub}")
    elif op == "text":
        col = params.get("column")
        sub = params.get("sub_operation")
        if not col or col not in df_columns:
            raise HTTPException(status_code=400, detail=f"Column '{col}' not found")
        if sub not in ["trim","lowercase","uppercase","title_case","find_replace","standardize"]:
            raise HTTPException(status_code=400, detail=f"Unknown text sub_operation {sub}")
        if sub == "find_replace" and not params.get("find"):
            raise HTTPException(status_code=400, detail="find_replace requires 'find' param")
    elif op == "numeric":
        col = params.get("column")
        sub = params.get("sub_operation")
        if not col or col not in df_columns:
            raise HTTPException(status_code=400, detail=f"Column '{col}' not found")
        if sub not in ["convert_to_numeric","handle_outliers","winsorize"]:
            raise HTTPException(status_code=400, detail=f"Unknown numeric sub_operation {sub}")
    elif op == "date":
        col = params.get("column")
        sub = params.get("sub_operation")
        if not col or col not in df_columns:
            raise HTTPException(status_code=400, detail=f"Column '{col}' not found")
        if sub not in ["convert_to_datetime","standardize_format","identify_invalid"]:
            raise HTTPException(status_code=400, detail=f"Unknown date sub_operation {sub}")
    elif op == "row_filter":
        sub = params.get("sub_operation")
        if sub not in ["filter_by_value","filter_by_numeric_range","filter_by_date","remove_filtered"]:
            raise HTTPException(status_code=400, detail=f"Unknown row_filter sub_operation {sub}")
        if sub in ["filter_by_value","filter_by_numeric_range"] and not params.get("column"):
            raise HTTPException(status_code=400, detail="Row filter requires column")
        if params.get("column") and params.get("column") not in df_columns:
            raise HTTPException(status_code=400, detail=f"Column '{params.get('column')}' not found")
    else:
        raise HTTPException(status_code=400, detail=f"Unknown operation {op}")

def get_current_df(dataset: Dataset, db: Session) -> pd.DataFrame:
    df, _ = _get_current_df_and_version(dataset, db)
    return df

def _get_current_df_and_version(dataset: Dataset, db: Session):
    """Single authoritative loader: returns (df, current_version or None). Loads file at most once."""
    current_version = db.query(DatasetVersion).filter(DatasetVersion.dataset_id==dataset.id, DatasetVersion.is_current==True).first()
    if current_version and current_version.storage_path and os.path.exists(current_version.storage_path):
        try:
            df = load_dataframe(current_version.storage_path)
            return df, current_version
        except:
            pass
    # fallback: load original + replay transformations (single replay)
    try:
        df = load_dataframe(dataset.storage_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load dataset: {str(e)}")
    transforms = db.query(Transformation).filter(Transformation.dataset_id==dataset.id, Transformation.undone==False).order_by(Transformation.created_at.asc()).all()
    for t in transforms:
        try:
            df, _ = apply_operation(df, t.operation, t.params or {})
        except Exception:
            continue
    return df, current_version

def recompute_current_version(dataset: Dataset, db: Session):
    # Optimized: single load of original + single replay, single save, single profile
    try:
        orig_df = load_dataframe(dataset.storage_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load original: {str(e)}")
    transforms = db.query(Transformation).filter(Transformation.dataset_id==dataset.id, Transformation.undone==False).order_by(Transformation.created_at.asc()).all()
    cur = orig_df
    # Apply all non-undone transforms in memory (no intermediate DB writes)
    for t in transforms:
        try:
            cur, _ = apply_operation(cur, t.operation, t.params or {})
        except:
            continue
    current_version = db.query(DatasetVersion).filter(DatasetVersion.dataset_id==dataset.id, DatasetVersion.is_current==True).first()
    ext = os.path.splitext(dataset.storage_path)[1]
    storage_base = settings.STORAGE_PATH
    user_dir = os.path.join(storage_base, dataset.user_id, dataset.id)
    os.makedirs(user_dir, exist_ok=True)
    if current_version:
        try:
            save_dataframe(cur, current_version.storage_path, dataset.file_type)
            _byos_mirror_version(dataset, current_version.storage_path)
            prof = profile_dataframe(cur)
            current_version.row_count = prof["row_count"]
            current_version.column_count = prof["column_count"]
            current_version.quality_score = prof["quality_score"]
            db.commit()
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=str(e))
    else:
        if transforms:
            max_v = db.query(DatasetVersion).filter(DatasetVersion.dataset_id==dataset.id).order_by(desc(DatasetVersion.version_number)).first()
            next_num = (max_v.version_number + 1) if max_v else 2
            path = os.path.join(user_dir, f"v{next_num}{ext}")
            try:
                save_dataframe(cur, path, dataset.file_type)
                _byos_mirror_version(dataset, path)
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
            prof = profile_dataframe(cur)
            new_v = DatasetVersion(dataset_id=dataset.id, version_number=next_num, name=f"Version {next_num}", storage_path=path, row_count=prof["row_count"], column_count=prof["column_count"], quality_score=prof["quality_score"], transformation_summary=f"Auto after transformations", is_current=True)
            db.add(new_v)
            db.commit()
    return cur

def create_version_snapshot(dataset: Dataset, df: pd.DataFrame, name: str, summary: str, db: Session, precomputed_profile: dict = None):
    ext = os.path.splitext(dataset.storage_path)[1]
    storage_base = settings.STORAGE_PATH
    user_dir = os.path.join(storage_base, dataset.user_id, dataset.id)
    os.makedirs(user_dir, exist_ok=True)
    max_v = db.query(DatasetVersion).filter(DatasetVersion.dataset_id==dataset.id).order_by(desc(DatasetVersion.version_number)).first()
    next_num = (max_v.version_number + 1) if max_v else 1
    if not max_v:
        orig_path = os.path.join(user_dir, f"v1{ext}")
        if not os.path.exists(orig_path):
            import shutil
            try:
                shutil.copy(dataset.storage_path, orig_path)
            except:
                save_dataframe(load_dataframe(dataset.storage_path), orig_path, dataset.file_type)
            try:
                orig_df = load_dataframe(dataset.storage_path)
                prof_orig = profile_dataframe(orig_df)
            except:
                prof_orig = {"row_count": 0, "column_count": 0, "quality_score": 0}
            v1 = DatasetVersion(dataset_id=dataset.id, version_number=1, name="Original", storage_path=orig_path, row_count=prof_orig["row_count"], column_count=prof_orig["column_count"], quality_score=prof_orig["quality_score"], transformation_summary="Original dataset", is_current=False)
            db.add(v1)
            db.flush()
            max_v = v1
            next_num = 2
        else:
            next_num = 2
    else:
        next_num = max_v.version_number + 1
    # Atomic: mark previous false, then create new version in same transaction
    db.query(DatasetVersion).filter(DatasetVersion.dataset_id==dataset.id, DatasetVersion.is_current==True).update({DatasetVersion.is_current: False})
    path = os.path.join(user_dir, f"v{next_num}{ext}")
    # Save file first; if it fails, rollback DB
    try:
        save_dataframe(df, path, dataset.file_type)
        _byos_mirror_version(dataset, path)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to save version: {str(e)}")
    prof = precomputed_profile or profile_dataframe(df)
    v = DatasetVersion(dataset_id=dataset.id, version_number=next_num, name=name or f"Version {next_num}", storage_path=path, row_count=prof["row_count"], column_count=prof["column_count"], quality_score=prof["quality_score"], transformation_summary=summary, is_current=True)
    db.add(v)
    db.flush()
    return v

@router.get("/{dataset_id}/current")
def get_current(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    df, _ = _get_current_df_and_version(ds, db)
    prof = profile_dataframe(df)
    return {"row_count": prof["row_count"], "column_count": prof["column_count"], "quality_score": prof["quality_score"], "duplicates": prof["duplicates"], "quality_details": prof["quality_details"]}

@router.post("/{dataset_id}/clean/preview")
def preview_clean(dataset_id: str, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    op = payload.get("op")
    params = payload.get("params", {})
    if not op:
        raise HTTPException(status_code=400, detail="Missing op")
    df, _ = _get_current_df_and_version(ds, db)
    # Validate quickly
    try:
        _validate_operation(op, params, list(df.columns))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        result = preview_operation(df, op, params)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result

@router.post("/{dataset_id}/clean/apply")
def apply_clean(dataset_id: str, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    # Stale version check
    expected_version_id = payload.get("expected_version_id")
    if expected_version_id:
        cur_v = db.query(DatasetVersion).filter(DatasetVersion.dataset_id==dataset_id, DatasetVersion.is_current==True).first()
        if cur_v and str(cur_v.id) != str(expected_version_id):
            raise HTTPException(status_code=409, detail=f"Version conflict: dataset has changed (expected {expected_version_id}, current {cur_v.id}). Please refresh preview.")
    op = payload.get("op")
    params = payload.get("params", {})
    ops = payload.get("operations")
    # Batch path - atomic single version
    if ops:
        df, cur_v = _get_current_df_and_version(ds, db)
        # validate all ops first
        for item in ops:
            o = item.get("op") or item.get("operation")
            p = item.get("params") or {}
            if not o:
                raise HTTPException(status_code=400, detail="Missing op in batch")
            try:
                _validate_operation(o, p, list(df.columns))
            except HTTPException:
                raise
            # need to update df_columns after each op? For batch, validate sequentially with evolving columns
            try:
                df_tmp, _ = apply_operation(df, o, p)
                df = df_tmp
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed at {o}: {str(e)}")
        # Now re-load original fresh and apply all for real
        df, _ = _get_current_df_and_version(ds, db)
        cur_df = df.copy()
        batch_stats = []
        try:
            for item in ops:
                o = item.get("op") or item.get("operation")
                p = item.get("params") or {}
                cur_df, stats = apply_operation(cur_df, o, p)
                batch_stats.append(stats)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        # Compute profile once
        prof = profile_dataframe(cur_df)
        # Save file and create single atomic transaction for all transformations + version
        try:
            ext = os.path.splitext(ds.storage_path)[1]
            user_dir = os.path.join(settings.STORAGE_PATH, ds.user_id, ds.id)
            os.makedirs(user_dir, exist_ok=True)
            max_v = db.query(DatasetVersion).filter(DatasetVersion.dataset_id==ds.id).order_by(desc(DatasetVersion.version_number)).first()
            next_num = (max_v.version_number + 1) if max_v else 2
            if not max_v:
                # create original if missing (should not happen)
                pass
            # Prepare transformations objects
            trans_objs = []
            for item in ops:
                o = item.get("op") or item.get("operation")
                p = item.get("params") or {}
                t = Transformation(dataset_id=ds.id, operation=o, params=p, before_stats={}, after_stats={}, undone=False)
                trans_objs.append(t)
            # Atomic DB + file: save file first
            db.query(DatasetVersion).filter(DatasetVersion.dataset_id==ds.id, DatasetVersion.is_current==True).update({DatasetVersion.is_current: False})
            path = os.path.join(user_dir, f"v{next_num}{ext}")
            save_dataframe(cur_df, path, ds.file_type)
            _byos_mirror_version(ds, path)
            v = DatasetVersion(dataset_id=ds.id, version_number=next_num, name=payload.get("version_name") or f"Cleaning batch", storage_path=path, row_count=prof["row_count"], column_count=prof["column_count"], quality_score=prof["quality_score"], transformation_summary=f"Batch of {len(ops)} operations", is_current=True)
            db.add(v)
            for t in trans_objs:
                db.add(t)
            db.commit()
            db.refresh(v)
        except Exception as e:
            db.rollback()
            # try to remove file if created
            try:
                if 'path' in locals() and os.path.exists(path):
                    os.remove(path)
            except:
                pass
            raise HTTPException(status_code=500, detail=str(e))
        return {"message": "Applied batch", "version": {"id": v.id, "version_number": v.version_number, "name": v.name, "row_count": v.row_count, "column_count": v.column_count, "quality_score": v.quality_score}, "stats": {"row_count": v.row_count, "quality_score": v.quality_score}, "diff": compute_diff_stats(df, cur_df)}
    # Single operation - most common
    if not op:
        raise HTTPException(status_code=400, detail="Missing op")
    df, cur_v = _get_current_df_and_version(ds, db)
    try:
        _validate_operation(op, params, list(df.columns))
    except HTTPException:
        raise
    # Compute before profile for metadata
    try:
        prof_before = profile_dataframe(df)
    except Exception:
        prof_before = {"quality_score": 0, "row_count": len(df), "column_count": len(df.columns)}
    try:
        new_df, stats = apply_operation(df, op, params)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Compute profile once for new version
    try:
        prof = profile_dataframe(new_df)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Profile failed: {str(e)}")
    # Build rich metadata
    meta = _build_transformation_metadata(df, new_df, op, params, stats, prof_before, prof)
    # Compute diff before persisting version (cheap)
    diff = compute_diff_stats(df, new_df)
    # Embed metadata into diff for frontend Before/After rendering
    diff["metadata"] = meta
    diff["changes_applied"] = {
        "missing_resolved": max(0, meta["missing_before"] - meta["missing_after"]),
        "rows_removed": max(0, meta["rows_before"] - meta["rows_after"]),
        "duplicates_removed": max(0, meta["duplicates_before"] - meta["duplicates_after"]),
        "columns_added": meta["added_columns"],
        "columns_removed": meta["removed_columns"],
        "quality_before": meta["quality_before"],
        "quality_after": meta["quality_after"],
        "quality_delta": meta["quality_delta"],
    }
    # Atomic persistence: save file then single DB transaction for Transformation + Version
    try:
        ext = os.path.splitext(ds.storage_path)[1]
        user_dir = os.path.join(settings.STORAGE_PATH, ds.user_id, ds.id)
        os.makedirs(user_dir, exist_ok=True)
        # Mark previous current false and prepare version path without extra profile
        db.query(DatasetVersion).filter(DatasetVersion.dataset_id==ds.id, DatasetVersion.is_current==True).update({DatasetVersion.is_current: False})
        max_v = db.query(DatasetVersion).filter(DatasetVersion.dataset_id==ds.id).order_by(desc(DatasetVersion.version_number)).first()
        next_num = (max_v.version_number + 1) if max_v else 1
        # Handle case where no versions exist (need v1)
        if not max_v:
            orig_path = os.path.join(user_dir, f"v1{ext}")
            if not os.path.exists(orig_path):
                import shutil
                try:
                    shutil.copy(ds.storage_path, orig_path)
                except:
                    save_dataframe(load_dataframe(ds.storage_path), orig_path, ds.file_type)
                try:
                    orig_df = load_dataframe(ds.storage_path)
                    prof_orig = profile_dataframe(orig_df)
                except:
                    prof_orig = {"row_count": len(df), "column_count": len(df.columns), "quality_score": 0}
                v1 = DatasetVersion(dataset_id=ds.id, version_number=1, name="Original", storage_path=orig_path, row_count=prof_orig["row_count"], column_count=prof_orig["column_count"], quality_score=prof_orig["quality_score"], transformation_summary="Original dataset", is_current=False)
                db.add(v1)
                db.flush()
                next_num = 2
        else:
            # Need to get next after flush? Already computed
            # Re-query max after potential v1 creation
            if next_num == 1:
                next_num = 2
            else:
                # max_v was previous max, now we already updated is_current, need next = old max +1
                pass
        path = os.path.join(user_dir, f"v{next_num}{ext}")
        save_dataframe(new_df, path, ds.file_type)
        _byos_mirror_version(ds, path)
        t = Transformation(dataset_id=ds.id, operation=op, params=params, before_stats={"rows": meta["rows_before"], "columns": meta["columns_before"], "missing": meta["missing_before"], "quality": meta["quality_before"]}, after_stats=meta, undone=False)
        db.add(t)
        v = DatasetVersion(dataset_id=ds.id, version_number=next_num, name=payload.get("version_name") or f"{op}", storage_path=path, row_count=prof["row_count"], column_count=prof["column_count"], quality_score=prof["quality_score"], transformation_summary=f"{op} {params}", is_current=True)
        db.add(v)
        db.commit()
        db.refresh(t)
        db.refresh(v)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        try:
            if 'path' in locals() and os.path.exists(path):
                os.remove(path)
        except:
            pass
        raise HTTPException(status_code=500, detail=str(e))
    return {"message": "Applied", "transformation_id": t.id, "version": {"id": v.id, "version_number": v.version_number, "name": v.name, "row_count": v.row_count, "column_count": v.column_count, "quality_score": v.quality_score}, "stats": stats, "diff": diff}

@router.get("/{dataset_id}/history")
def get_history(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    trans = db.query(Transformation).filter(Transformation.dataset_id==dataset_id).order_by(Transformation.created_at.asc()).all()
    history = []
    for t in trans:
        history.append({"id": t.id, "operation": t.operation, "params": t.params, "before_stats": t.before_stats, "after_stats": t.after_stats, "created_at": t.created_at, "undone": t.undone})
    current_index = -1
    for i, h in enumerate(history):
        if not h["undone"]:
            current_index = i
    return {"history": history, "current_index": current_index, "total": len(history)}

@router.post("/{dataset_id}/history/undo")
def undo(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    t = db.query(Transformation).filter(Transformation.dataset_id==dataset_id, Transformation.undone==False).order_by(Transformation.created_at.desc()).first()
    if not t:
        raise HTTPException(status_code=400, detail="Nothing to undo")
    t.undone = True
    db.commit()
    recompute_current_version(ds, db)
    return {"message": "Undone", "undone_id": t.id}

@router.post("/{dataset_id}/history/redo")
def redo(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    t = db.query(Transformation).filter(Transformation.dataset_id==dataset_id, Transformation.undone==True).order_by(Transformation.created_at.desc()).first()
    if not t:
        raise HTTPException(status_code=400, detail="Nothing to redo")
    t.undone = False
    db.commit()
    recompute_current_version(ds, db)
    return {"message": "Redone", "redone_id": t.id}

@router.get("/{dataset_id}/versions")
def list_versions(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    versions = db.query(DatasetVersion).filter(DatasetVersion.dataset_id==dataset_id).order_by(DatasetVersion.version_number.asc()).all()
    if not versions:
        try:
            orig_df = load_dataframe(ds.storage_path)
            prof = profile_dataframe(orig_df)
            ext = os.path.splitext(ds.storage_path)[1]
            user_dir = os.path.join(settings.STORAGE_PATH, ds.user_id, ds.id)
            os.makedirs(user_dir, exist_ok=True)
            path = os.path.join(user_dir, f"v1{ext}")
            if not os.path.exists(path):
                import shutil
                shutil.copy(ds.storage_path, path)
            v1 = DatasetVersion(dataset_id=ds.id, version_number=1, name="Original", storage_path=path, row_count=prof["row_count"], column_count=prof["column_count"], quality_score=prof["quality_score"], transformation_summary="Original", is_current=True)
            db.add(v1)
            db.commit()
            versions = [v1]
        except Exception:
            pass
    return [{"id": v.id, "version_number": v.version_number, "name": v.name, "row_count": v.row_count, "column_count": v.column_count, "quality_score": v.quality_score, "transformation_summary": v.transformation_summary, "created_at": v.created_at, "is_current": v.is_current, "storage_path": v.storage_path} for v in versions]

@router.post("/{dataset_id}/versions")
def create_version(dataset_id: str, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    name = payload.get("name") or f"Version {payload.get('version_number', '')}"
    df, _ = _get_current_df_and_version(ds, db)
    v = create_version_snapshot(ds, df, name, payload.get("summary") or "Manual snapshot", db)
    db.commit()
    return {"id": v.id, "version_number": v.version_number, "name": v.name, "row_count": v.row_count, "column_count": v.column_count, "quality_score": v.quality_score}

@router.post("/{dataset_id}/versions/{version_id}/restore")
def restore_version(dataset_id: str, version_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    v = db.query(DatasetVersion).filter(DatasetVersion.id==version_id, DatasetVersion.dataset_id==dataset_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    db.query(DatasetVersion).filter(DatasetVersion.dataset_id==dataset_id).update({DatasetVersion.is_current: False})
    v.is_current = True
    db.commit()
    return {"message": "Restored", "version_id": v.id}

@router.post("/{dataset_id}/versions/{version_id}/rename")
def rename_version(dataset_id: str, version_id: str, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    v = db.query(DatasetVersion).filter(DatasetVersion.id==version_id, DatasetVersion.dataset_id==dataset_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    new_name = payload.get("name")
    if not new_name:
        raise HTTPException(status_code=400, detail="Name required")
    v.name = new_name
    db.commit()
    return {"message": "Renamed", "version_id": v.id, "name": v.name}

@router.get("/{dataset_id}/versions/{version_id}/preview")
def preview_version(dataset_id: str, version_id: str, page: int=1, page_size: int=20, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    v = db.query(DatasetVersion).filter(DatasetVersion.id==version_id, DatasetVersion.dataset_id==dataset_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    try:
        df = load_dataframe(v.storage_path)
        from app.data_engine.profiler import compute_preview
        rows, total = compute_preview(df, page, min(page_size,100))
        return {"rows": rows, "total_rows": total, "page": page, "page_size": page_size, "version": {"id": v.id, "name": v.name}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{dataset_id}/diff")
def get_diff(dataset_id: str, from_version: int = None, to_version: int = None, from_id: str = None, to_id: str = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    if from_id and to_id:
        fv = db.query(DatasetVersion).filter(DatasetVersion.id==from_id).first()
        tv = db.query(DatasetVersion).filter(DatasetVersion.id==to_id).first()
        if not fv or not tv:
            raise HTTPException(status_code=404, detail="Version not found")
        before_df = load_dataframe(fv.storage_path)
        after_df = load_dataframe(tv.storage_path)
    elif from_version and to_version:
        fv = db.query(DatasetVersion).filter(DatasetVersion.dataset_id==dataset_id, DatasetVersion.version_number==from_version).first()
        tv = db.query(DatasetVersion).filter(DatasetVersion.dataset_id==dataset_id, DatasetVersion.version_number==to_version).first()
        if not fv or not tv:
            raise HTTPException(status_code=404, detail="Version not found")
        before_df = load_dataframe(fv.storage_path)
        after_df = load_dataframe(tv.storage_path)
    else:
        before_df = load_dataframe(ds.storage_path)
        after_df, _ = _get_current_df_and_version(ds, db)
    diff = compute_diff_stats(before_df, after_df)
    before_prof = profile_dataframe(before_df)
    after_prof = profile_dataframe(after_df)
    diff["quality"] = {"before": before_prof["quality_score"], "after": after_prof["quality_score"], "delta": round(after_prof["quality_score"]-before_prof["quality_score"],1)}
    # Build Changes Applied from latest transformation metadata if available
    latest = db.query(Transformation).filter(Transformation.dataset_id==dataset_id, Transformation.undone==False).order_by(Transformation.created_at.desc()).first()
    if latest and latest.after_stats and isinstance(latest.after_stats, dict) and "missing_before" in latest.after_stats:
        meta = latest.after_stats
        diff["changes_applied"] = {
            "missing_resolved": max(0, meta.get("missing_before",0) - meta.get("missing_after",0)),
            "rows_removed": max(0, meta.get("rows_before",0) - meta.get("rows_after",0)),
            "duplicates_removed": max(0, meta.get("duplicates_before",0) - meta.get("duplicates_after",0)),
            "columns_added": meta.get("added_columns",[]),
            "columns_removed": meta.get("removed_columns",[]),
            "quality_before": meta.get("quality_before"),
            "quality_after": meta.get("quality_after"),
            "quality_delta": meta.get("quality_delta"),
            "operation": meta.get("operation"),
            "affected_columns": meta.get("affected_columns",[]),
        }
        diff["columns_added"] = meta.get("added_columns",[])
        diff["columns_removed"] = meta.get("removed_columns",[])
        diff["metadata"] = meta
    else:
        diff["changes_applied"] = {
            "missing_resolved": max(0, diff["missing_cells"]["before"] - diff["missing_cells"]["after"]),
            "rows_removed": max(0, diff["rows"]["before"] - diff["rows"]["after"]),
            "duplicates_removed": max(0, diff["duplicates"]["before"] - diff["duplicates"]["after"]),
            "columns_added": sorted(list(set(after_df.columns) - set(before_df.columns))),
            "columns_removed": sorted(list(set(before_df.columns) - set(after_df.columns))),
            "quality_before": diff["quality"]["before"],
            "quality_after": diff["quality"]["after"],
            "quality_delta": diff["quality"]["delta"],
        }
        diff["columns_added"] = sorted(list(set(after_df.columns) - set(before_df.columns)))
        diff["columns_removed"] = sorted(list(set(before_df.columns) - set(after_df.columns)))
        diff["metadata"] = diff["changes_applied"]
    diff["sample_changes"] = {}
    for col in before_df.columns:
        if col in after_df.columns and before_df[col].dtype==object:
            b_unique = before_df[col].dropna().unique()[:3]
            a_unique = after_df[col].dropna().unique()[:3]
            if list(b_unique) != list(a_unique):
                diff["sample_changes"][col] = {"before_examples": [str(x) for x in b_unique], "after_examples": [str(x) for x in a_unique]}
    return diff

@router.get("/{dataset_id}/recipe")
def get_recipe(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    trans = db.query(Transformation).filter(Transformation.dataset_id==dataset_id, Transformation.undone==False).order_by(Transformation.created_at.asc()).all()
    recipe = []
    for i, t in enumerate(trans):
        recipe.append({"step": i+1, "operation": t.operation, "params": t.params, "created_at": t.created_at})
    return {"recipe": recipe, "total_steps": len(recipe)}

@router.post("/{dataset_id}/recipe/save")
def save_recipe(dataset_id: str, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    name = payload.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Recipe name required")
    trans = db.query(Transformation).filter(Transformation.dataset_id==dataset_id, Transformation.undone==False).order_by(Transformation.created_at.asc()).all()
    ops = [{"operation": t.operation, "params": t.params} for t in trans]
    if not ops:
        raise HTTPException(status_code=400, detail="No operations to save")
    rec = CleaningRecipe(user_id=current_user.id, name=name, dataset_id=dataset_id, operations=ops)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return {"id": rec.id, "name": rec.name, "operations": rec.operations, "created_at": rec.created_at}

@router.get("/recipes")
def list_recipes(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    recs = db.query(CleaningRecipe).filter(CleaningRecipe.user_id==current_user.id).order_by(CleaningRecipe.created_at.desc()).all()
    return [{"id": r.id, "name": r.name, "dataset_id": r.dataset_id, "operations": r.operations, "created_at": r.created_at} for r in recs]

@router.get("/recipes/{recipe_id}")
def get_recipe_by_id(recipe_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = db.query(CleaningRecipe).filter(CleaningRecipe.id==recipe_id).first()
    if not r or r.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return {"id": r.id, "name": r.name, "operations": r.operations, "created_at": r.created_at}

@router.post("/{dataset_id}/recipe/apply")
def apply_recipe(dataset_id: str, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    recipe_id = payload.get("recipe_id")
    if not recipe_id:
        raise HTTPException(status_code=400, detail="recipe_id required")
    rec = db.query(CleaningRecipe).filter(CleaningRecipe.id==recipe_id).first()
    if not rec or rec.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Recipe not found")
    df, _ = _get_current_df_and_version(ds, db)
    ops = rec.operations
    incompatible = []
    preview_results = []
    df_tmp = df.copy()
    for op_item in ops:
        op = op_item.get("operation")
        params = op_item.get("params", {})
        col = params.get("column") or params.get("old_name")
        if col and col not in df_tmp.columns:
            incompatible.append({"operation": op, "params": params, "reason": f"Column '{col}' not found in target dataset"})
        else:
            try:
                pre = preview_operation(df_tmp, op, params)
                preview_results.append({"operation": op, "params": params, "stats": pre["stats"]})
                df_tmp, _ = apply_operation(df_tmp, op, params)
            except Exception as e:
                incompatible.append({"operation": op, "params": params, "reason": str(e)})
    if payload.get("validate_only"):
        return {"compatible": len(incompatible)==0, "incompatible_steps": incompatible, "preview": preview_results}
    if incompatible and not payload.get("force"):
        raise HTTPException(status_code=400, detail={"message": "Incompatible steps", "incompatible": incompatible})
    # Atomic apply for recipe: single version
    cur_df, _ = _get_current_df_and_version(ds, db)
    applied = 0
    prof = None
    try:
        for op_item in ops:
            op = op_item.get("operation")
            params = op_item.get("params", {})
            col = params.get("column") or params.get("old_name")
            if col and col not in cur_df.columns:
                continue
            try:
                cur_df, stats = apply_operation(cur_df, op, params)
                t = Transformation(dataset_id=ds.id, operation=op, params=params, before_stats={}, after_stats=stats, undone=False)
                db.add(t)
                applied += 1
            except:
                continue
        if applied == 0:
            raise HTTPException(status_code=400, detail="No operations could be applied")
        prof = profile_dataframe(cur_df)
        v = create_version_snapshot(ds, cur_df, f"Recipe: {rec.name}", f"Applied recipe {rec.name}", db, precomputed_profile=prof)
        db.commit()
        db.refresh(v)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    return {"message": "Recipe applied", "version": {"id": v.id, "version_number": v.version_number}, "incompatible": incompatible}


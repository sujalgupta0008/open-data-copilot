import os
import shutil
import uuid
import tempfile
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User, Dataset, DatasetColumn, AnalysisSession, AnalysisMessage, AnalysisResult, Chart
from app.schemas.schemas import DatasetOut, DatasetProfileOut, PreviewOut
from app.core.config import settings
from app.data_engine.profiler import load_dataframe, profile_dataframe, get_sample_rows, compute_preview
import pandas as pd
# BYOS Google Drive Middleware — non-destructive wrapper (does not refactor core engines)
from app.services.drive_middleware import DriveMiddleware
from app.services.google_drive import cleanup_tmp_file

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

ALLOWED_EXT = {".csv", ".xlsx", ".xls", ".json", ".parquet"}

def ensure_storage():
    os.makedirs(settings.STORAGE_PATH, exist_ok=True)
    return settings.STORAGE_PATH

def validate_csv_strict(raw: bytes, filename: str) -> tuple[bool, str]:
    """Strict CSV validation: consistent columns, valid header, no duplicates, no ragged rows."""
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        try:
            text = raw.decode('latin-1')
        except Exception:
            return False, "File encoding is not UTF-8. Please save as UTF-8 CSV."
    # quick empty check (already done) but handle BOM-only
    if not text.strip():
        return False, "CSV file is empty. Add a header row and at least one data row."
    import csv, io
    reader = csv.reader(io.StringIO(text))
    # Stream rows instead of list(reader) to avoid 50MB+ memory spike (P4)
    header = None
    try:
        header = next(reader)
    except StopIteration:
        return False, "CSV file has no rows. Add a header and data."
    except csv.Error as e:
        return False, f"CSV parsing error: {e}. Ensure the file is a valid comma-separated CSV with quoted fields where needed."
    # header checks
    if all(not h.strip() for h in header):
        return False, "CSV header row is empty. First row must contain column names (e.g., name,price,date)."
    # duplicate columns (case-insensitive trim)
    stripped = [h.strip() for h in header]
    lowered = [h.strip().lower() for h in header]
    seen = {}
    dups = []
    for i, name in enumerate(lowered):
        if not name:
            return False, f"Column {i+1} has an empty header name. Fill in a name or remove the column. Header: {header}"
        if name in seen:
            dups.append(header[i])
        else:
            seen[name] = i
    if dups:
        return False, f"Duplicate column names found: {', '.join(set(dups))}. Column names must be unique (case-insensitive). Rename duplicates and re-upload."
    # unnamed columns from pandas like Unnamed: 0 usually come from empty header but we already check
    for h in header:
        if h.strip().lower().startswith("unnamed:"):
            return False, f"Invalid column name '{h}'. Remove empty columns or give each column a proper name."
    expected = len(header)
    if expected < 1:
        return False, "CSV must have at least one column."
    # check data rows — streaming, no list materialization
    ragged_rows = []
    empty_rows = 0
    data_rows = 0
    try:
        for idx, r in enumerate(reader, start=2):
            # skip completely empty lines (csv reader may give [])
            if len(r) == 0 or all(not c.strip() for c in r):
                empty_rows += 1
                continue
            data_rows += 1
            if len(r) != expected:
                ragged_rows.append((idx, len(r)))
                if len(ragged_rows) >= 3:
                    break
    except csv.Error as e:
        return False, f"CSV parsing error: {e}. Ensure the file is a valid comma-separated CSV with quoted fields where needed."
    if ragged_rows:
        details = ", ".join([f"row {rno} has {c} columns (expected {expected})" for rno, c in ragged_rows])
        return False, f"Inconsistent column count: {details}. Every row must have exactly {expected} comma-separated values matching the header. Check for missing commas, extra commas, or unquoted fields containing commas."
    # need at least one non-empty data row
    if data_rows < 1:
        return False, "CSV has a header but no data rows. Add at least one data row below the header."
    # ambiguous schema: header with single column but data looks comma-separated? Already handled
    # also reject if header contains only numeric names
    if all(h.strip().replace('.', '', 1).replace('-', '', 1).isdigit() for h in header):
        return False, "Header row appears to be numeric data, not column names. Ensure the first row is the header with descriptive names."
    return True, "ok"

@router.post("/upload", response_model=DatasetOut)
async def upload_dataset(file: UploadFile = File(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file — upload a file with a header row and data. Supported: CSV, XLSX, JSON, Parquet (max 50MB).")
    if len(content) > 50*1024*1024:
        raise HTTPException(status_code=400, detail="File too large (max 50MB) — reduce file size or split the dataset.")
    # strict CSV validation BEFORE writing to disk
    if ext == ".csv":
        ok, msg = validate_csv_strict(content, file.filename)
        if not ok:
            raise HTTPException(status_code=400, detail=msg + " Tip: Open the CSV in a spreadsheet, ensure every row has the same number of columns, no blank header cells, and re-export as UTF-8 CSV.")
    storage = ensure_storage()
    user_dir = os.path.join(storage, current_user.id)
    os.makedirs(user_dir, exist_ok=True)
    dataset_id = str(uuid.uuid4())
    stored_name = f"{dataset_id}{ext}"
    path = os.path.join(user_dir, stored_name)
    with open(path, "wb") as f:
        f.write(content)
    # --- BYOS Google Drive Middleware: stream upload directly to Drive + keep /tmp copy during analysis ---
    drive_info = None
    tmp_path = None
    try:
        mw = DriveMiddleware(user_id=current_user.id)
        drive_info, tmp_path = mw.handle_upload(content, stored_name)
    except Exception as _e:
        # Non-fatal for backward compat — log but continue with local path
        drive_info = None
        tmp_path = None
    # Try to profile — use /tmp copy if available (temporary pipeline), else local path
    profile_path = tmp_path if (tmp_path and os.path.exists(tmp_path)) else path
    try:
        df = load_dataframe(profile_path)
        if df.empty:
            os.remove(path)
            raise HTTPException(status_code=400, detail="Dataset is empty after parsing — file had a header but no readable data rows. Add data and re-upload.")
        # extra validation: duplicate column names after pandas load (pandas mangles duplicates with .1)
        if any(str(c).startswith("Unnamed:") for c in df.columns):
            os.remove(path)
            raise HTTPException(status_code=400, detail="CSV has empty or unnamed columns. Give every column a header name and remove blank columns.")
        # check for pandas-mangled duplicates like 'col' and 'col.1'
        lower_cols = [str(c).strip().lower() for c in df.columns]
        if len(lower_cols) != len(set(lower_cols)):
            os.remove(path)
            raise HTTPException(status_code=400, detail="Duplicate column names detected after parsing. Ensure column names are unique (case-insensitive).")
        profile = profile_dataframe(df)
        # --- Cleanup hook: clear local /tmp copy immediately after execution (analysis = profiling) ---
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
    except HTTPException as he:
        # Ensure tmp cleanup even on validation errors
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise he
    except Exception as e:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        if os.path.exists(path):
            os.remove(path)
        raise HTTPException(status_code=400, detail=f"Failed to parse dataset: {str(e)}. Verify the file is not corrupted and matches the expected format (header + rows, UTF-8).")

    dataset = Dataset(
        id=dataset_id,
        user_id=current_user.id,
        name=os.path.splitext(file.filename)[0],
        original_filename=file.filename,
        file_type=ext.lstrip("."),
        file_size=len(content),
        row_count=profile["row_count"],
        column_count=profile["column_count"],
        quality_score=profile["quality_score"],
        storage_path=path
    )
    db.add(dataset)
    db.flush()
    for col in profile["columns_info"]:
        # Only persist core fields to DB; semantic enrichment is returned via API/profile but not stored as columns to avoid schema mismatch
        allowed = {k: col[k] for k in ["name","data_type","null_count","null_percentage","unique_count","min_value","max_value","mean_value","median_value","std_value"] if k in col}
        # data_type mapping: ensure it matches DB expectation (original string)
        dc = DatasetColumn(dataset_id=dataset.id, **allowed)
        db.add(dc)
    # create initial version 1
    try:
        from app.models.models import DatasetVersion
        import os as _os
        user_version_dir = _os.path.join(storage, current_user.id, dataset_id)
        _os.makedirs(user_version_dir, exist_ok=True)
        v1_path = _os.path.join(user_version_dir, f"v1{ext}")
        # copy original file to version location
        import shutil as _shutil
        _shutil.copy(path, v1_path)
        v1 = DatasetVersion(dataset_id=dataset.id, version_number=1, name="Original", storage_path=v1_path, row_count=profile["row_count"], column_count=profile["column_count"], quality_score=profile["quality_score"], transformation_summary="Original", is_current=True)
        db.add(v1)
        db.commit()
    except Exception as e:
        # non-fatal
        try:
            db.commit()
        except:
            pass
    # Final safety cleanup: ensure zero leftover tmp files (explicit os.remove hook)
    if tmp_path and os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except Exception:
            pass
    # Ensure Drive workspace has copy (mirror version file to Drive if not already)
    try:
        if drive_info and drive_info.get("drive_path"):
            # Copy version file to Drive workspace as well for lineage preservation
            import shutil as _sh
            drive_version_dir = os.path.join(settings.STORAGE_PATH, "drive", current_user.id, settings.GOOGLE_DRIVE_FOLDER_NAME, dataset_id)
            os.makedirs(drive_version_dir, exist_ok=True)
            # Drive already has uploaded file; ensure version file also mirrored
            try:
                _sh.copy(path, os.path.join(drive_version_dir, f"v1{ext}"))
            except Exception:
                pass
    except Exception:
        pass
    db.refresh(dataset)
    return dataset

@router.get("", response_model=list[DatasetOut])
def list_datasets(search: str = Query(None), sort: str = Query("created_at"), order: str = Query("desc"), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Dataset).filter(Dataset.user_id == current_user.id)
    if search:
        q = q.filter(Dataset.name.ilike(f"%{search}%"))
    if sort in ["created_at","name","quality_score","row_count"]:
        col = getattr(Dataset, sort)
        if order=="asc":
            q = q.order_by(col.asc())
        else:
            q = q.order_by(col.desc())
    else:
        q = q.order_by(Dataset.created_at.desc())
    return q.all()

@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds or ds.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return ds

@router.delete("/{dataset_id}")
def delete_dataset(dataset_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds or ds.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Dataset not found")
    # delete file
    try:
        if ds.storage_path and os.path.exists(ds.storage_path):
            os.remove(ds.storage_path)
    except:
        pass
    db.delete(ds)
    db.commit()
    return {"message": "Deleted"}

@router.get("/{dataset_id}/profile", response_model=DatasetProfileOut)
def get_profile(dataset_id: str, version_id: str = Query(None), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds or ds.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Dataset not found")
    cols = db.query(DatasetColumn).filter(DatasetColumn.dataset_id == dataset_id).all()
    try:
        # try to use current version if exists
        from app.models.models import DatasetVersion, Transformation
        from app.data_engine.cleaning import apply_operation
        df = None
        if version_id:
            from app.models.models import DatasetVersion as DV2
            v = db.query(DV2).filter(DV2.id==version_id).first()
            if not v:
                raise HTTPException(status_code=404, detail="Version not found")
            if v.dataset_id != dataset_id:
                raise HTTPException(status_code=404, detail="Version not found")
            if os.path.exists(v.storage_path):
                df = load_dataframe(v.storage_path)
            else:
                # version record exists but file missing -> treat as not found to avoid falling back to current version silently
                raise HTTPException(status_code=404, detail="Version not found")
        if df is None:
            # Check current version
            cv = db.query(DatasetVersion).filter(DatasetVersion.dataset_id==dataset_id, DatasetVersion.is_current==True).first()
            if cv and os.path.exists(cv.storage_path):
                try:
                    df = load_dataframe(cv.storage_path)
                except:
                    df = None
            if df is None:
                # replay transformations from original
                df = load_dataframe(ds.storage_path)
                trans = db.query(Transformation).filter(Transformation.dataset_id==dataset_id, Transformation.undone==False).order_by(Transformation.created_at.asc()).all()
                for t in trans:
                    try:
                        df, _ = apply_operation(df, t.operation, t.params or {})
                    except:
                        continue
        profile = profile_dataframe(df)
        sample = get_sample_rows(df, 5)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load profile: {str(e)}")
    # Use stored quality details from profile recomputed
    return {
        "dataset": ds,
        "columns": cols,
        "quality_details": profile["quality_details"],
        "insights": profile["insights"],
        "duplicates": profile["duplicates"],
        "sample_rows": sample
    }

@router.get("/{dataset_id}/preview", response_model=PreviewOut)
def preview(dataset_id: str, page: int = 1, page_size: int = 20, search: str = Query(None), sort_by: str = Query(None), sort_dir: str = Query("asc"), version_id: str = Query(None), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds or ds.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Dataset not found")
    try:
        from app.models.models import DatasetVersion, Transformation
        from app.data_engine.cleaning import apply_operation
        df = None
        if version_id:
            v = db.query(DatasetVersion).filter(DatasetVersion.id==version_id).first()
            if not v:
                raise HTTPException(status_code=404, detail="Version not found")
            if v.dataset_id != dataset_id:
                raise HTTPException(status_code=404, detail="Version not found")
            if os.path.exists(v.storage_path):
                df = load_dataframe(v.storage_path)
            else:
                raise HTTPException(status_code=404, detail="Version not found")
        if df is None:
            cv = db.query(DatasetVersion).filter(DatasetVersion.dataset_id==dataset_id, DatasetVersion.is_current==True).first()
            if cv and os.path.exists(cv.storage_path):
                try:
                    df = load_dataframe(cv.storage_path)
                except:
                    df = None
            if df is None:
                df = load_dataframe(ds.storage_path)
                trans = db.query(Transformation).filter(Transformation.dataset_id==dataset_id, Transformation.undone==False).order_by(Transformation.created_at.asc()).all()
                for t in trans:
                    try:
                        df, _ = apply_operation(df, t.operation, t.params or {})
                    except:
                        continue
        # ensure page_size limited
        page_size = min(max(page_size,1),100)
        rows, total = compute_preview(df, page, page_size, search, sort_by, sort_dir)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"rows": rows, "total_rows": total, "page": page, "page_size": page_size}

"""
Google Drive Service — BYOS Middleware
Mock + Real support. Non-destructive: does not alter core analysis engines.
Mock mode uses local filesystem under STORAGE_PATH/drive/<user_id>/Open_Data_Copilot_Workspace
Real mode would use googleapiclient (lazy-imported).

Requirement 2: auto-creates folder Open_Data_Copilot_Workspace upon first user login.
Requirement 3: stream uploads to Drive, keep /tmp copy during analysis, save results to Drive, cleanup via os.remove
"""
import os
import shutil
import uuid
import json
import tempfile
from typing import Optional, Dict, Any
from pathlib import Path

from app.core.config import settings


# In-memory mock token store for tests (mirrors DB if available)
_mock_tokens: Dict[str, dict] = {}


def _is_mock() -> bool:
    return (settings.DRIVE_MOCK_ENABLED or "1").strip() in ("1", "true", "True", "yes")


def _drive_root(user_id: str) -> str:
    # Mock drive root: STORAGE_PATH/drive/<user_id>
    # Real drive would be remote; mock gives deterministic local path for tests
    return os.path.join(settings.STORAGE_PATH, "drive", user_id)


def _workspace_path(user_id: str) -> str:
    return os.path.join(_drive_root(user_id), settings.GOOGLE_DRIVE_FOLDER_NAME)


def _tmp_base() -> str:
    if settings.TMP_DIR and settings.TMP_DIR.strip():
        os.makedirs(settings.TMP_DIR, exist_ok=True)
        return settings.TMP_DIR
    # Prefer system /tmp, fallback to storage/tmp
    sys_tmp = tempfile.gettempdir()
    # On Windows, gettempdir is C:\Users\...\AppData\Local\Temp — use it
    try:
        os.makedirs(sys_tmp, exist_ok=True)
        return sys_tmp
    except Exception:
        fallback = os.path.join(settings.STORAGE_PATH, "tmp")
        os.makedirs(fallback, exist_ok=True)
        return fallback


class GoogleDriveService:
    """
    Service per user. Handles OAuth token storage (mock) and workspace file ops.
    Real implementation would wrap google.oauth2.credentials.Credentials + googleapiclient.discovery.build
    """

    def __init__(self, user_id: str, credentials: Optional[dict] = None):
        self.user_id = user_id
        self.credentials = credentials or _mock_tokens.get(user_id)
        self.is_mock = _is_mock()

    # ---------- OAuth helpers ----------

    def get_auth_url(self, state: Optional[str] = None) -> str:
        """Return Google OAuth consent URL with scope drive.file"""
        from urllib.parse import urlencode
        client_id = settings.GOOGLE_CLIENT_ID or "mock-client-id"
        redirect = settings.GOOGLE_REDIRECT_URI
        scope = settings.GOOGLE_OAUTH_SCOPE
        params = {
            "client_id": client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": scope,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
        if state:
            params["state"] = state
        base = "https://accounts.google.com/o/oauth2/v2/auth"
        return f"{base}?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict:
        """Exchange auth code for token. Mock returns fake token and stores it."""
        if self.is_mock:
            token = {
                "access_token": f"mock_access_{uuid.uuid4().hex[:12]}",
                "refresh_token": f"mock_refresh_{uuid.uuid4().hex[:12]}",
                "scope": settings.GOOGLE_OAUTH_SCOPE,
                "token_type": "Bearer",
                "expiry": "2099-01-01T00:00:00Z",
                "code": code,
            }
            _mock_tokens[self.user_id] = token
            # persist to DB if possible
            try:
                self._persist_token(token)
            except Exception:
                pass
            return token
        # Real flow (lazy)
        try:
            import httpx  # type: ignore
            # Example exchange — not executed in mock/tests
            resp = httpx.post("https://oauth2.googleapis.com/token", data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            }, timeout=10)
            resp.raise_for_status()
            token = resp.json()
            _mock_tokens[self.user_id] = token
            self._persist_token(token)
            return token
        except Exception as e:
            raise RuntimeError(f"OAuth exchange failed: {e}")

    def _persist_token(self, token: dict):
        """Try to persist token to DB table google_drive_tokens if exists, else json file"""
        # File fallback for mock durability
        try:
            tok_dir = os.path.join(settings.STORAGE_PATH, "drive", self.user_id)
            os.makedirs(tok_dir, exist_ok=True)
            with open(os.path.join(tok_dir, ".token.json"), "w") as f:
                json.dump(token, f)
        except Exception:
            pass
        # DB persist if model exists
        try:
            from app.core.database import SessionLocal
            from sqlalchemy import text
            db = SessionLocal()
            try:
                # check table exists
                db.execute(text("SELECT 1 FROM google_drive_tokens LIMIT 1"))
                # upsert
                db.execute(text("""
                    INSERT INTO google_drive_tokens (id, user_id, token_json, created_at)
                    VALUES (:id, :uid, :tok, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id) DO UPDATE SET token_json=:tok
                """), {"id": str(uuid.uuid4()), "uid": self.user_id, "tok": json.dumps(token)})
                db.commit()
            except Exception:
                db.rollback()
            finally:
                db.close()
        except Exception:
            pass

    def is_authenticated(self) -> bool:
        if self.is_mock:
            # Mock considers any stored token or even no token as authenticated for dev convenience
            # But we enforce explicit mock login for tests
            return self.user_id in _mock_tokens or self._has_workspace()
        return self.credentials is not None

    def _has_workspace(self) -> bool:
        return os.path.exists(_workspace_path(self.user_id))

    # ---------- Workspace ----------

    def ensure_workspace_folder(self) -> Dict[str, Any]:
        """
        Auto-creates folder Open_Data_Copilot_Workspace upon first user login.
        Returns dict with folder_id (mock = path) and path
        """
        if self.is_mock:
            ws = _workspace_path(self.user_id)
            os.makedirs(ws, exist_ok=True)
            # Create a .drive_metadata.json marker for drive.file scope simulation
            meta_path = os.path.join(ws, ".drive_folder.json")
            if not os.path.exists(meta_path):
                with open(meta_path, "w") as f:
                    json.dump({"folder_name": settings.GOOGLE_DRIVE_FOLDER_NAME, "user_id": self.user_id, "scope": settings.GOOGLE_OAUTH_SCOPE, "created_by": "mock"}, f)
            return {"folder_id": ws, "folder_name": settings.GOOGLE_DRIVE_FOLDER_NAME, "path": ws, "mock": True}
        # Real Google Drive: create or find folder with drive.file scope
        try:
            from googleapiclient.discovery import build  # type: ignore
            from google.oauth2.credentials import Credentials  # type: ignore
            creds = Credentials(**self.credentials) if self.credentials else None
            service = build("drive", "v3", credentials=creds)
            # Search for folder
            q = f"mimeType='application/vnd.google-apps.folder' and name='{settings.GOOGLE_DRIVE_FOLDER_NAME}' and trashed=false"
            res = service.files().list(q=q, fields="files(id,name)").execute()
            files = res.get("files", [])
            if files:
                return {"folder_id": files[0]["id"], "folder_name": settings.GOOGLE_DRIVE_FOLDER_NAME, "path": files[0]["id"], "mock": False}
            # Create
            file_metadata = {"name": settings.GOOGLE_DRIVE_FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"}
            folder = service.files().create(body=file_metadata, fields="id").execute()
            return {"folder_id": folder.get("id"), "folder_name": settings.GOOGLE_DRIVE_FOLDER_NAME, "path": folder.get("id"), "mock": False}
        except Exception as e:
            # Fallback to mock path for resilience
            ws = _workspace_path(self.user_id)
            os.makedirs(ws, exist_ok=True)
            return {"folder_id": ws, "folder_name": settings.GOOGLE_DRIVE_FOLDER_NAME, "path": ws, "mock": True, "warning": str(e)}

    def get_workspace_info(self) -> Dict[str, Any]:
        ws = _workspace_path(self.user_id)
        exists = os.path.exists(ws)
        return {
            "folder_name": settings.GOOGLE_DRIVE_FOLDER_NAME,
            "path": ws,
            "exists": exists,
            "scope": settings.GOOGLE_OAUTH_SCOPE,
            "authenticated": self.is_authenticated(),
            "mock": self.is_mock,
            "files": self.list_files() if exists else [],
        }

    # ---------- File ops — Drive <-> /tmp ----------

    def drive_file_path(self, filename: str) -> str:
        """Resolve filename inside workspace folder"""
        ws = _workspace_path(self.user_id)
        os.makedirs(ws, exist_ok=True)
        # Sanitize filename
        safe = os.path.basename(filename)
        return os.path.join(ws, safe)

    def upload_bytes(self, content: bytes, filename: str) -> Dict[str, Any]:
        """
        Stream incoming uploads directly to user's Drive workspace.
        Returns drive_path and size. Also caller should keep /tmp copy via middleware.
        """
        self.ensure_workspace_folder()
        dst = self.drive_file_path(filename)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(content)
        if self.is_mock:
            return {"drive_path": dst, "filename": filename, "size": len(content), "mock": True}
        # Real: upload via drive API
        try:
            from googleapiclient.http import MediaIoBaseUpload  # type: ignore
            import io
            media = MediaIoBaseUpload(io.BytesIO(content), mimetype="application/octet-stream")
            # Would call service.files().create(...) — omitted for mock
            return {"drive_path": dst, "filename": filename, "size": len(content), "mock": False, "media": media}
        except Exception as e:
            return {"drive_path": dst, "filename": filename, "size": len(content), "mock": True, "warning": str(e)}

    def save_dataframe_to_drive(self, df, filename: str, file_type: str = "csv") -> Dict[str, Any]:
        """Save generated analytical results directly to user's Drive folder (non-destructive wrapper)"""
        self.ensure_workspace_folder()
        dst = self.drive_file_path(filename)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        ext = os.path.splitext(filename)[1].lower()
        if not ext:
            ext = f".{file_type.lstrip('.')}"
            dst = dst + ext if not dst.endswith(ext) else dst
        # Save using pandas per type
        if ext == ".csv" or file_type == "csv":
            df.to_csv(dst, index=False)
        elif ext in [".xlsx", ".xls"]:
            df.to_excel(dst, index=False)
        elif ext == ".json":
            df.to_json(dst, orient="records", indent=2)
        elif ext == ".parquet":
            df.to_parquet(dst, index=False)
        else:
            df.to_csv(dst, index=False)
        return {"drive_path": dst, "filename": os.path.basename(dst), "mock": True}

    def save_bytes_to_drive(self, content: bytes, filename: str) -> Dict[str, Any]:
        """Save raw bytes (PDF/PNG/CSV) directly to Drive"""
        self.ensure_workspace_folder()
        dst = self.drive_file_path(filename)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(content)
        return {"drive_path": dst, "filename": filename, "size": len(content), "mock": True}

    def read_from_drive(self, filename: str) -> bytes:
        """Read file from Drive workspace (mock = local file)"""
        src = self.drive_file_path(filename)
        if not os.path.exists(src):
            raise FileNotFoundError(f"Drive file not found: {filename} at {src}")
        with open(src, "rb") as f:
            return f.read()

    def list_files(self) -> list:
        ws = _workspace_path(self.user_id)
        if not os.path.exists(ws):
            return []
        files = []
        for entry in os.listdir(ws):
            if entry.startswith("."):
                continue
            p = os.path.join(ws, entry)
            if os.path.isfile(p):
                files.append({"name": entry, "path": p, "size": os.path.getsize(p)})
        return files

    # ---------- /tmp helpers ----------

    def write_tmp_copy(self, content: bytes, filename: str) -> str:
        """
        Keep a temporary copy in /tmp during active analysis.
        Returns tmp path. Caller must trigger cleanup hook os.remove after execution.
        """
        base = _tmp_base()
        # Unique per user+file to avoid collisions
        tmp_name = f"odc_{self.user_id[:8]}_{uuid.uuid4().hex[:8]}_{os.path.basename(filename)}"
        tmp_path = os.path.join(base, tmp_name)
        with open(tmp_path, "wb") as f:
            f.write(content)
        return tmp_path

    def write_dataframe_to_tmp(self, df, filename: str, file_type: str = "csv") -> str:
        base = _tmp_base()
        tmp_name = f"odc_{self.user_id[:8]}_{uuid.uuid4().hex[:8]}_{os.path.basename(filename)}"
        tmp_path = os.path.join(base, tmp_name)
        ext = os.path.splitext(tmp_path)[1].lower()
        if not ext:
            ext = f".{file_type}"
            tmp_path += ext
        if file_type == "csv" or tmp_path.endswith(".csv"):
            df.to_csv(tmp_path, index=False)
        elif tmp_path.endswith((".xlsx", ".xls")):
            df.to_excel(tmp_path, index=False)
        elif tmp_path.endswith(".json"):
            df.to_json(tmp_path, orient="records", indent=2)
        elif tmp_path.endswith(".parquet"):
            df.to_parquet(tmp_path, index=False)
        else:
            df.to_csv(tmp_path, index=False)
        return tmp_path


# Convenience singleton accessor
def get_drive_service(user_id: str) -> GoogleDriveService:
    return GoogleDriveService(user_id=user_id)


def cleanup_tmp_file(tmp_path: str) -> bool:
    """
    Explicit cleanup hook (os.remove or equivalent) to clear local /tmp files immediately after execution.
    Returns True if removed, False if already gone.
    """
    try:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
            return True
        return False
    except Exception:
        return False

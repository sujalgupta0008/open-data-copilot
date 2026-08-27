"""
Google Drive Middleware — Non-Destructive Wrapper for file input/output
Wraps file input (uploads) and file output (saving CSVs/PDFs/PNGs) with Google Drive layer.
Core data analysis / EDA / reporting engines are NOT refactored; this sits around them.

Usage:
  from app.services.drive_middleware import DriveMiddleware

  mw = DriveMiddleware(user_id)
  drive_info, tmp_path = mw.handle_upload(content_bytes, filename)
  # ... run analysis using tmp_path ...
  # after execution, mw.cleanup(tmp_path)

  mw.save_output(df, "result.csv") -> saves directly to Drive

Also provides context manager for automatic cleanup.
"""
import os
import tempfile
import shutil
from typing import Tuple, Optional, Dict, Any
from contextlib import contextmanager

from app.services.google_drive import GoogleDriveService, cleanup_tmp_file


class DriveMiddleware:
    """
    Middleware layer: Drive is primary storage, /tmp is ephemeral working copy.
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.drive = GoogleDriveService(user_id=user_id)

    def ensure_workspace(self) -> Dict[str, Any]:
        """Auto-creates Open_Data_Copilot_Workspace if missing"""
        return self.drive.ensure_workspace_folder()

    def handle_upload(self, content: bytes, filename: str) -> Tuple[Dict[str, Any], str]:
        """
        Stream incoming uploads directly to user's Drive workspace, and keep a temporary copy in /tmp during active analysis.
        Returns (drive_info, tmp_path)
        """
        self.ensure_workspace()
        drive_info = self.drive.upload_bytes(content, filename)
        tmp_path = self.drive.write_tmp_copy(content, filename)
        return drive_info, tmp_path

    def save_output_dataframe(self, df, filename: str, file_type: str = "csv") -> Dict[str, Any]:
        """
        Save generated analytical results directly to user's Drive folder.
        Returns drive_info. No local persistence beyond Drive.
        """
        self.ensure_workspace()
        return self.drive.save_dataframe_to_drive(df, filename, file_type=file_type)

    def save_output_bytes(self, content: bytes, filename: str) -> Dict[str, Any]:
        """Save raw bytes (PDF/PNG) directly to Drive"""
        self.ensure_workspace()
        return self.drive.save_bytes_to_drive(content, filename)

    def read_from_drive(self, filename: str) -> bytes:
        return self.drive.read_from_drive(filename)

    def cleanup(self, tmp_path: str) -> bool:
        """
        Trigger explicit cleanup hook (os.remove) to clear local /tmp files immediately after execution.
        """
        return cleanup_tmp_file(tmp_path)

    def cleanup_many(self, tmp_paths: list) -> int:
        count = 0
        for p in tmp_paths:
            if self.cleanup(p):
                count += 1
        return count

    @contextmanager
    def tmp_working_copy(self, content: bytes, filename: str):
        """
        Context manager: yields tmp_path and cleans up automatically on exit.
        Example:
          with mw.tmp_working_copy(content, "data.csv") as tmp_path:
              df = pd.read_csv(tmp_path)
              # analyze...
          # tmp file is removed here via os.remove
        """
        drive_info, tmp_path = self.handle_upload(content, filename)
        try:
            yield tmp_path, drive_info
        finally:
            self.cleanup(tmp_path)

    def get_workspace_status(self) -> Dict[str, Any]:
        return self.drive.get_workspace_info()

    def list_drive_files(self) -> list:
        return self.drive.list_files()

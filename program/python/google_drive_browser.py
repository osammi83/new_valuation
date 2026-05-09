from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
except Exception:
    service_account = None
    build = None
    MediaIoBaseDownload = None


SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def load_service_account_info(raw: str) -> dict[str, Any]:
    candidate = Path(raw)
    if candidate.exists():
        return json.loads(candidate.read_text(encoding="utf-8"))
    return json.loads(raw)


def build_drive_service(service_account_raw: str):
    if service_account is None or build is None:
        raise ModuleNotFoundError("googleapiclient")
    info = load_service_account_info(service_account_raw)
    credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=credentials)


def list_files(service, folder_id: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        response = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                pageSize=1000,
                pageToken=page_token,
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return files


def download_file_bytes(service, file_id: str) -> bytes:
    if MediaIoBaseDownload is None:
        raise ModuleNotFoundError("googleapiclient")

    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except Exception:
    service_account = None
    build = None
    MediaFileUpload = None


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _load_service_account_info(raw: str) -> dict:
    candidate = Path(raw)
    if candidate.exists():
        with open(candidate, "r", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(raw)


def _build_drive_service(sa_json_raw: str):
    if service_account is None or build is None:
        raise ModuleNotFoundError("googleapiclient")
    info = _load_service_account_info(sa_json_raw)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def _collect_targets(output_dir: Path, report_date: str) -> list[Path]:
    if not output_dir.exists():
        return []

    targets: list[Path] = []
    for p in output_dir.glob("*.csv"):
        name = p.name
        if "_locked_" in name:
            continue
        if f"_{report_date}.csv" in name or f"_{report_date}_" in name:
            targets.append(p)
    return sorted(targets)


def _append_publish_history(history_path: Path, row: dict[str, object]) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "timestamp",
        "report_date",
        "output_dir",
        "folder_id",
        "status",
        "created",
        "updated",
        "total",
        "target_files",
        "message",
    ]
    file_exists = history_path.exists()
    with history_path.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in fieldnames})


def _find_existing_file_id(service, folder_id: str, file_name: str) -> Optional[str]:
    q = (
        f"name = '{file_name}' and '{folder_id}' in parents and trashed = false"
    )
    res = (
        service.files()
        .list(q=q, fields="files(id,name)", pageSize=5, supportsAllDrives=True, includeItemsFromAllDrives=True)
        .execute()
    )
    files = res.get("files", [])
    if not files:
        return None
    return files[0].get("id")


def _upload_files(service, folder_id: str, files: Iterable[Path]) -> tuple[int, int]:
    created = 0
    updated = 0
    for f in files:
        if MediaFileUpload is None:
            raise ModuleNotFoundError("googleapiclient")
        media = MediaFileUpload(str(f), mimetype="text/csv", resumable=False)
        existing_id = _find_existing_file_id(service, folder_id, f.name)
        if existing_id:
            service.files().update(
                fileId=existing_id,
                media_body=media,
                supportsAllDrives=True,
            ).execute()
            updated += 1
            print(f"[Drive Updated] {f.name}")
        else:
            meta = {"name": f.name, "parents": [folder_id]}
            service.files().create(
                body=meta,
                media_body=media,
                fields="id,name",
                supportsAllDrives=True,
            ).execute()
            created += 1
            print(f"[Drive Uploaded] {f.name}")
    return created, updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload daily output CSV files to Google Drive")
    parser.add_argument("--date", type=str, default=datetime.now().strftime("%Y-%m-%d"), help="Report date (YYYY-MM-DD)")
    parser.add_argument("--output-dir", type=str, default=str(OUTPUT_DIR), help="Output directory path")
    parser.add_argument("--folder-id", type=str, default=os.environ.get("GOOGLE_DRIVE_FOLDER_ID", ""), help="Google Drive target folder ID")
    parser.add_argument("--history-path", type=str, default=str(OUTPUT_DIR / "publish_history.csv"), help="Publish history CSV path")
    parser.add_argument(
        "--service-account-json",
        type=str,
        default=os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", ""),
        help="Service account JSON raw text or file path",
    )
    args = parser.parse_args()

    folder_id = (args.folder_id or "").strip()
    service_account_json = (args.service_account_json or "").strip()
    history_path = Path(args.history_path)

    if not folder_id or not service_account_json:
        print("[Drive] Skipped: GOOGLE_DRIVE_FOLDER_ID or GOOGLE_SERVICE_ACCOUNT_JSON is not set.")
        _append_publish_history(
            history_path,
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "report_date": args.date,
                "output_dir": str(Path(args.output_dir)),
                "folder_id": folder_id,
                "status": "skipped",
                "created": 0,
                "updated": 0,
                "total": 0,
                "target_files": "",
                "message": "missing_config",
            },
        )
        return

    targets = _collect_targets(Path(args.output_dir), args.date)
    if not targets:
        print(f"[Drive] No CSV files found for date {args.date}.")
        _append_publish_history(
            history_path,
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "report_date": args.date,
                "output_dir": str(Path(args.output_dir)),
                "folder_id": folder_id,
                "status": "skipped",
                "created": 0,
                "updated": 0,
                "total": 0,
                "target_files": "",
                "message": "no_targets",
            },
        )
        return

    try:
        service = _build_drive_service(service_account_json)
        created, updated = _upload_files(service, folder_id, targets)
    except Exception as exc:
        _append_publish_history(
            history_path,
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "report_date": args.date,
                "output_dir": str(Path(args.output_dir)),
                "folder_id": folder_id,
                "status": "failed",
                "created": 0,
                "updated": 0,
                "total": len(targets),
                "target_files": ";".join(p.name for p in targets),
                "message": type(exc).__name__,
            },
        )
        raise

    _append_publish_history(
        history_path,
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "report_date": args.date,
            "output_dir": str(Path(args.output_dir)),
            "folder_id": folder_id,
            "status": "success",
            "created": created,
            "updated": updated,
            "total": len(targets),
            "target_files": ";".join(p.name for p in targets),
            "message": "",
        },
    )
    print(f"[Drive] Completed: created={created}, updated={updated}, total={len(targets)}")


if __name__ == "__main__":
    main()

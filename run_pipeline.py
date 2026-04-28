from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "up_valuation_config.json"


def _load_config_value(key: str) -> str | None:
    try:
        import json

        if not CONFIG_PATH.exists():
            return None
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        value = data.get(key)
        if value is None:
            return None
        text = str(value).strip()
        return text or None
    except Exception:
        return None


def _load_user_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        text = value.strip()
        if text:
            return text

    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"[Environment]::GetEnvironmentVariable('{name}', 'User')",
            ],
            capture_output=True,
            text=True,
            cwd=BASE_DIR,
            check=False,
        )
        text = (result.stdout or "").strip()
        return text or None
    except Exception:
        return None


def _prepare_environment() -> None:
    dart_key = _load_user_env("DART_API_KEY") or _load_config_value("dartApiKey")
    if dart_key:
        os.environ["DART_API_KEY"] = dart_key

    krx_id = _load_user_env("KRX_ID") or _load_config_value("krxId")
    if krx_id:
        os.environ["KRX_ID"] = krx_id

    krx_pw = _load_user_env("KRX_PW") or _load_config_value("krxPw")
    if krx_pw:
        os.environ["KRX_PW"] = krx_pw

    google_drive_folder = _load_config_value("googleDriveFolderId")
    if google_drive_folder and not os.environ.get("GOOGLE_DRIVE_FOLDER_ID"):
        os.environ["GOOGLE_DRIVE_FOLDER_ID"] = google_drive_folder

    google_service_account = _load_config_value("googleServiceAccountJsonPath")
    if google_service_account and not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = google_service_account


def _run_step(label: str, command: list[str]) -> None:
    print(f"[Pipeline] {label}...")
    result = subprocess.run(command, cwd=BASE_DIR, check=False)
    if result.returncode != 0:
        raise SystemExit(f"[Pipeline] {label} failed with exit code {result.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the daily valuation pipeline")
    parser.add_argument("--limit", type=int, default=None, help="Optional row limit for downstream steps")
    parser.add_argument("--days-back", type=int, default=1, help="How many days back the preprocess step should scan")
    parser.add_argument("--period", default="1y", help="Price history period passed to build_daily_report")
    parser.add_argument("--output-mode", default="compact", help="Output mode for build_daily_report")
    args = parser.parse_args()

    _prepare_environment()

    python_exe = sys.executable
    print("[Pipeline] Daily run uses existing eps_cache.csv. Refresh separately via run_eps_cache_refresh.ps1.")

    _run_step(
        "Step 1/4 preprocess_daily_updates.py",
        [python_exe, str(BASE_DIR / "preprocess_daily_updates.py"), "--days-back", str(args.days_back)],
    )
    _run_step(
        "Step 2/4 refresh_assumptions.py",
        [python_exe, str(BASE_DIR / "refresh_assumptions.py")],
    )

    market_command = [python_exe, str(BASE_DIR / "ingest_market_data.py"), "--period", args.period]
    if args.limit is not None:
        market_command.extend(["--limit", str(args.limit)])
    _run_step("Step 3/8 ingest_market_data.py", market_command)

    feature_command = [python_exe, str(BASE_DIR / "build_features_daily.py"), "--period", args.period]
    if args.limit is not None:
        feature_command.extend(["--limit", str(args.limit)])
    _run_step("Step 4/8 build_features_daily.py", feature_command)

    signal_command = [python_exe, str(BASE_DIR / "score_daily_signals.py")]
    _run_step("Step 5/8 score_daily_signals.py", signal_command)

    _run_step("Step 6/8 manage_positions.py", [python_exe, str(BASE_DIR / "manage_positions.py")])

    build_command = [python_exe, str(BASE_DIR / "build_daily_report.py"), "--period", args.period, "--output-mode", args.output_mode]
    if args.limit is not None:
        build_command.extend(["--limit", str(args.limit)])
    _run_step("Step 7/8 build_daily_report.py", build_command)

    _run_step(
        "Step 8/9 validate_outputs.py",
        [python_exe, str(BASE_DIR / "validate_outputs.py")],
    )

    _run_step(
        "Step 9/9 validate_csv_contracts.py",
        [python_exe, str(BASE_DIR / "validate_csv_contracts.py")],
    )

    drive_enabled = str(_load_config_value("enableGoogleDriveUpload") or "").strip().lower() in {"1", "true", "t", "y", "yes", "on"}
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()
    service_account = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if drive_enabled or (folder_id and service_account):
        print("[Pipeline] Uploading daily outputs to Google Drive...")
        subprocess.run([python_exe, str(BASE_DIR / "publish_to_drive.py")], cwd=BASE_DIR, check=False)
    else:
        print("[Pipeline] Google Drive upload skipped.")

    print("[Pipeline] Daily pipeline completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
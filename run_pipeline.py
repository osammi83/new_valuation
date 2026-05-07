from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import uuid
from pathlib import Path
from datetime import datetime


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
CONFIG_PATH = BASE_DIR / "up_valuation_config.json"
RUN_HISTORY_PATH = BASE_DIR / "run_history.csv"
ERROR_LOG_PATH = BASE_DIR / "error_log.csv"


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


def _append_csv_row(path: Path, fieldnames: list[str], row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in fieldnames})


def _record_run_history(
    *,
    run_id: str,
    run_type: str,
    as_of_date: str,
    status: str,
    started_at: str,
    finished_at: str,
    warning_count: int,
    error_count: int,
    code_version: str,
) -> None:
    _append_csv_row(
        RUN_HISTORY_PATH,
        ["run_id", "run_type", "as_of_date", "status", "started_at", "finished_at", "warning_count", "error_count", "code_version"],
        {
            "run_id": run_id,
            "run_type": run_type,
            "as_of_date": as_of_date,
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "warning_count": warning_count,
            "error_count": error_count,
            "code_version": code_version,
        },
    )


def _record_error(run_id: str, program_name: str, severity: str, error_code: str, message: str) -> None:
    _append_csv_row(
        ERROR_LOG_PATH,
        ["event_ts", "run_id", "program_name", "severity", "error_code", "ticker", "message"],
        {
            "event_ts": datetime.now().isoformat(timespec="seconds"),
            "run_id": run_id,
            "program_name": program_name,
            "severity": severity,
            "error_code": error_code,
            "ticker": "",
            "message": message,
        },
    )


def _cleanup_locked_outputs(today: str) -> list[Path]:
    removed: list[Path] = []
    for locked_path in OUTPUT_DIR.glob(f"*_{today}_locked_*.csv"):
        if not locked_path.is_file():
            continue
        canonical_name = locked_path.name.split("_locked_", 1)[0] + locked_path.suffix
        canonical_path = locked_path.with_name(canonical_name)
        if canonical_path.exists():
            try:
                locked_path.unlink()
                removed.append(locked_path)
            except OSError:
                continue
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the daily valuation pipeline")
    subparsers = parser.add_subparsers(dest="command")

    daily_parser = subparsers.add_parser("daily", help="Run the daily valuation pipeline")
    daily_parser.add_argument("--limit", type=int, default=None, help="Optional row limit for downstream steps")
    daily_parser.add_argument("--days-back", type=int, default=1, help="How many days back the preprocess step should scan")
    daily_parser.add_argument("--period", default="1y", help="Price history period passed to build_daily_report")
    daily_parser.add_argument("--output-mode", default="compact", help="Output mode for build_daily_report")

    backtest_parser = subparsers.add_parser("backtest", help="Run the walk-forward backtest pipeline")
    backtest_parser.add_argument("--horizons", default="1,2,3", help="Comma-separated forward holding periods in trading days")
    backtest_parser.add_argument("--thresholds", default="50,55,60,65,70,75,80,85,90", help="Comma-separated score thresholds")
    backtest_parser.add_argument("--ks-side-bps", type=float, default=15.0, help="Roundtrip side cost basis points for KS")
    backtest_parser.add_argument("--kq-side-bps", type=float, default=20.0, help="Roundtrip side cost basis points for KQ")
    backtest_parser.add_argument("--output-prefix", type=str, default="", help="Optional output prefix override")

    train_parser = subparsers.add_parser("train", help="Train baseline models from daily outputs")
    train_parser.add_argument("--task", choices=["alpha", "entry", "both"], default="both", help="Which model task to train")

    parser.set_defaults(command="daily")
    args = parser.parse_args()

    daily_limit = getattr(args, "limit", None)
    daily_days_back = getattr(args, "days_back", 1)
    daily_period = getattr(args, "period", "1y")
    daily_output_mode = getattr(args, "output_mode", "compact")

    _prepare_environment()

    if args.command == "backtest":
        backtest_command = [
            sys.executable,
            str(BASE_DIR / "backtest_walkforward.py"),
            "--horizons",
            str(args.horizons),
            "--thresholds",
            str(args.thresholds),
            "--ks-side-bps",
            str(args.ks_side_bps),
            "--kq-side-bps",
            str(args.kq_side_bps),
        ]
        if args.output_prefix:
            backtest_command.extend(["--output-prefix", str(args.output_prefix)])
        _run_step("Backtest walk-forward", backtest_command)
        print("[Pipeline] Backtest pipeline completed successfully.")
        return 0

    if args.command == "train":
        train_command = [
            sys.executable,
            str(BASE_DIR / "train_models.py"),
            "--task",
            str(args.task),
        ]
        _run_step("Train models", train_command)
        print("[Pipeline] Training pipeline completed successfully.")
        return 0

    python_exe = sys.executable
    run_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    started_at = datetime.now().isoformat(timespec="seconds")
    finished_at = started_at
    status = "running"
    warning_count = 0
    error_count = 0

    try:
        _record_run_history(
            run_id=run_id,
            run_type="daily",
            as_of_date=datetime.now().strftime("%Y-%m-%d"),
            status=status,
            started_at=started_at,
            finished_at="",
            warning_count=warning_count,
            error_count=error_count,
            code_version="pipeline-v1",
        )

        print(f"[Pipeline] Run ID: {run_id}")
        print("[Pipeline] Daily run uses existing eps_cache.csv. Refresh separately via run_eps_cache_refresh.ps1.")

        _run_step(
            "Daily 1/7 preprocess_daily_updates.py",
            [python_exe, str(BASE_DIR / "preprocess_daily_updates.py"), "--days-back", str(daily_days_back)],
        )
        _run_step(
            "Daily 2/7 refresh_assumptions.py",
            [python_exe, str(BASE_DIR / "refresh_assumptions.py")],
        )

        market_command = [python_exe, str(BASE_DIR / "ingest_market_data.py"), "--period", daily_period]
        if daily_limit is not None:
            market_command.extend(["--limit", str(daily_limit)])
        _run_step("Daily 3/7 ingest_market_data.py", market_command)

        feature_command = [python_exe, str(BASE_DIR / "build_features_daily.py"), "--period", daily_period]
        if daily_limit is not None:
            feature_command.extend(["--limit", str(daily_limit)])
        _run_step("Daily 4/7 build_features_daily.py", feature_command)

        signal_command = [python_exe, str(BASE_DIR / "score_daily_signals.py")]
        _run_step("Daily 5/7 score_daily_signals.py", signal_command)

        _run_step("Daily 6/7 manage_positions.py", [python_exe, str(BASE_DIR / "manage_positions.py")])

        build_command = [python_exe, str(BASE_DIR / "build_daily_report.py"), "--period", daily_period, "--output-mode", daily_output_mode]
        if daily_limit is not None:
            build_command.extend(["--limit", str(daily_limit)])
        _run_step("Daily 7/7 build_daily_report.py", build_command)

        _run_step(
            "Validation 1/2 validate_outputs.py",
            [python_exe, str(BASE_DIR / "validate_outputs.py")] + (["--allow-empty-core-selection"] if daily_limit is not None else []),
        )

        _run_step(
            "Validation 2/2 validate_csv_contracts.py",
            [python_exe, str(BASE_DIR / "validate_csv_contracts.py")],
        )

        drive_enabled = str(_load_config_value("enableGoogleDriveUpload") or "").strip().lower() in {"1", "true", "t", "y", "yes", "on"}
        folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()
        service_account = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if drive_enabled or (folder_id and service_account):
            print("[Pipeline] Uploading daily outputs to Google Drive...")
            drive_result = subprocess.run([python_exe, str(BASE_DIR / "publish_to_drive.py")], cwd=BASE_DIR, check=False)
            if drive_result.returncode != 0:
                warning_count += 1
                _record_error(run_id, "publish_to_drive.py", "WARNING", "DRIVE_UPLOAD_FAILED", f"exit_code={drive_result.returncode}")
        else:
            print("[Pipeline] Google Drive upload skipped.")

        status = "success"
        finished_at = datetime.now().isoformat(timespec="seconds")
        _record_run_history(
            run_id=run_id,
            run_type="daily",
            as_of_date=datetime.now().strftime("%Y-%m-%d"),
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            warning_count=warning_count,
            error_count=error_count,
            code_version="pipeline-v1",
        )

        removed_locked = _cleanup_locked_outputs(datetime.now().strftime("%Y-%m-%d"))
        if removed_locked:
            print(f"[Pipeline] Cleaned locked outputs: {len(removed_locked)} file(s)")

        print("[Pipeline] Daily pipeline completed successfully.")
        return 0
    except BaseException as exc:
        status = "failed"
        finished_at = datetime.now().isoformat(timespec="seconds")
        error_count = 1
        _record_error(run_id, "run_pipeline.py", "ERROR", "PIPELINE_FAILED", str(exc))
        _record_run_history(
            run_id=run_id,
            run_type="daily",
            as_of_date=datetime.now().strftime("%Y-%m-%d"),
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            warning_count=warning_count,
            error_count=error_count,
            code_version="pipeline-v1",
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
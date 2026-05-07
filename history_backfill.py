from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
BUILD_SCRIPT = BASE_DIR / "build_daily_report.py"
MANIFEST_PATH = OUTPUT_DIR / "history_backfill_runs.csv"


def _business_dates(start_date: str, end_date: str) -> list[str]:
    dates = pd.bdate_range(start=pd.Timestamp(start_date), end=pd.Timestamp(end_date))
    return [date.strftime("%Y-%m-%d") for date in dates]


def _report_path(as_of: str) -> Path:
    return OUTPUT_DIR / f"상세리포트_{as_of}.csv"


def _append_manifest(row: dict[str, object]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "as_of",
        "status",
        "returncode",
        "started_at",
        "finished_at",
        "report_path",
        "message",
    ]
    write_header = not MANIFEST_PATH.exists() or MANIFEST_PATH.stat().st_size == 0
    with MANIFEST_PATH.open("a", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow({name: row.get(name, "") for name in fieldnames})


def _run_single_date(as_of: str, args: argparse.Namespace) -> tuple[str, int]:
    report_path = _report_path(as_of)
    if report_path.exists() and not args.force:
        _append_manifest(
            {
                "as_of": as_of,
                "status": "skipped",
                "returncode": 0,
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "report_path": str(report_path),
                "message": "report already exists",
            }
        )
        print(f"[Skip] {as_of} already exists: {report_path.name}")
        return "skipped", 0

    started_at = datetime.now()
    command = [
        sys.executable,
        str(BUILD_SCRIPT),
        "--as-of",
        as_of,
        "--period",
        args.period,
        "--output-mode",
        args.output_mode,
    ]
    if args.limit and args.limit > 0:
        command.extend(["--limit", str(args.limit)])

    print(f"[Run] {as_of}")
    completed = subprocess.run(command, cwd=BASE_DIR, check=False)
    finished_at = datetime.now()
    status = "success" if completed.returncode == 0 else "failed"
    _append_manifest(
        {
            "as_of": as_of,
            "status": status,
            "returncode": completed.returncode,
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "report_path": str(report_path),
            "message": "",
        }
    )
    return status, completed.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate historical daily valuation snapshots")
    parser.add_argument("--start", default="", help="Start date in YYYY-MM-DD. Defaults to 5 years before end date.")
    parser.add_argument("--end", default="", help="End date in YYYY-MM-DD. Defaults to today.")
    parser.add_argument("--years", type=int, default=5, help="Historical range in years when start is omitted.")
    parser.add_argument("--period", default="1y", help="yfinance period passed to build_daily_report.py")
    parser.add_argument("--output-mode", default="compact", choices=["compact", "full"], help="Report output mode")
    parser.add_argument("--limit", type=int, default=0, help="Optional ticker limit for quick testing")
    parser.add_argument("--max-days", type=int, default=0, help="Optional cap on the number of business days to process")
    parser.add_argument("--force", action="store_true", help="Regenerate dates even if report files already exist")
    parser.add_argument("--stop-on-error", action="store_true", help="Stop when a backfill day fails")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    end_date = args.end or datetime.now().strftime("%Y-%m-%d")
    if args.start:
        start_date = args.start
    else:
        start_date = (pd.Timestamp(end_date) - pd.DateOffset(years=int(args.years))).strftime("%Y-%m-%d")

    dates = _business_dates(start_date, end_date)
    if args.max_days and args.max_days > 0:
        dates = dates[-int(args.max_days) :]

    if not dates:
        print("No business dates found for the requested range.")
        return 0

    print(f"[Backfill] range={start_date}..{end_date} days={len(dates)}")
    successes = 0
    failures = 0
    skipped = 0
    for as_of in dates:
        status, returncode = _run_single_date(as_of, args)
        if status == "skipped":
            skipped += 1
        elif returncode == 0:
            successes += 1
        else:
            failures += 1
            if args.stop_on_error:
                break

    print(f"[Backfill] success={successes} skipped={skipped} failed={failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Lightweight validation of pipeline outputs: existence and non-empty checks."""
from __future__ import annotations
from pathlib import Path
import argparse
import sys
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "output"


def _latest_file(pattern: str) -> Path | None:
    candidates = [p for p in OUTPUT_DIR.glob(pattern) if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, keep_default_na=False)
    except Exception:
        return pd.DataFrame()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate generated valuation outputs (basic checks)")
    parser.add_argument("--root", default=str(BASE_DIR))
    args = parser.parse_args()

    report_path = _latest_file("scored_report_*.csv")
    core_path = _latest_file("core_selection_*.csv")
    positions_path = _latest_file("positions_*.csv")

    issues = []

    if report_path is None:
        issues.append("scored_report: not found")
    else:
        df = _read_csv(report_path)
        if df.empty:
            issues.append(f"{report_path.name}: empty or unreadable")

    if core_path is None:
        issues.append("core_selection: not found")
    else:
        df = _read_csv(core_path)
        if df.empty:
            issues.append(f"{core_path.name}: empty or unreadable")

    if positions_path is None:
        issues.append("positions: not found")
    else:
        df = _read_csv(positions_path)
        if df.empty:
            issues.append(f"{positions_path.name}: empty or unreadable")

    if issues:
        print("[Outputs] validation failed")
        for it in issues:
            print(f"[Outputs] {it}")
        return 1

    print(f"[Outputs] validation passed for {report_path.name}, {core_path.name}, {positions_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


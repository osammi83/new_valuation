from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
ALLOWED_REGIMES = {"BULL", "NEUTRAL", "BEAR"}
ALLOWED_DIFF_STATUS = {"유지", "상승", "하락", "신규", "이탈"}


def _latest_file(pattern: str) -> Path | None:
    candidates = [path for path in OUTPUT_DIR.glob(pattern) if path.is_file() and "_locked_" not in path.name]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _to_float(value: str | None) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _validate_daily_report(path: Path) -> list[str]:
    issues: list[str] = []
    df = _read_csv(path)
    required = ["기준일", "종목코드", "종합점수", "결합액션", "권장비중(%)", "마켓레짐"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        issues.append(f"{path.name}: missing columns {', '.join(missing)}")
        return issues

    if df.empty:
        issues.append(f"{path.name}: empty report")
        return issues

    invalid_regimes = sorted({value for value in df["마켓레짐"].astype(str).str.strip().unique() if value and value not in ALLOWED_REGIMES})
    if invalid_regimes:
        issues.append(f"{path.name}: invalid regimes {', '.join(invalid_regimes)}")

    excluded_with_weight = df[(df["결합액션"].astype(str).str.strip() == "제외") & (df["권장비중(%)"].map(_to_float) > 0)]
    if not excluded_with_weight.empty:
        issues.append(f"{path.name}: excluded rows with positive weight={len(excluded_with_weight)}")

    duplicate_keys = df[["기준일", "종목코드"]].duplicated(keep=False)
    if duplicate_keys.any():
        issues.append(f"{path.name}: duplicate 기준일+종목코드 rows={int(duplicate_keys.sum())}")

    return issues


def _validate_core_selection(path: Path) -> list[str]:
    issues: list[str] = []
    df = _read_csv(path)
    required = ["기준일", "종목코드", "추천순위", "종합점수"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        issues.append(f"{path.name}: missing columns {', '.join(missing)}")
        return issues

    if df.empty:
        issues.append(f"{path.name}: empty report")
        return issues

    duplicate_tickers = df["종목코드"].duplicated(keep=False)
    if duplicate_tickers.any():
        issues.append(f"{path.name}: duplicate 종목코드 rows={int(duplicate_tickers.sum())}")

    return issues


def _validate_diff_report(path: Path) -> list[str]:
    issues: list[str] = []
    df = _read_csv(path)
    required = ["당일기준일", "전일기준일", "변화상태", "종목코드"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        issues.append(f"{path.name}: missing columns {', '.join(missing)}")
        return issues

    invalid_status = sorted({value for value in df["변화상태"].astype(str).str.strip().unique() if value and value not in ALLOWED_DIFF_STATUS})
    if invalid_status:
        issues.append(f"{path.name}: invalid 변화상태 {', '.join(invalid_status)}")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate generated valuation outputs")
    parser.add_argument("--root", default=str(BASE_DIR), help="Workspace root")
    args = parser.parse_args()

    _ = Path(args.root)
    report_path = _latest_file("상세리포트_*.csv")
    core_path = _latest_file("종목선정_핵심근거_*.csv")
    diff_path = _latest_file("최종매수_전일비교_*.csv")

    issues: list[str] = []
    if report_path is None:
        issues.append("상세리포트: no file found")
    else:
        issues.extend(_validate_daily_report(report_path))

    if core_path is None:
        issues.append("종목선정_핵심근거: no file found")
    else:
        issues.extend(_validate_core_selection(core_path))

    if diff_path is None:
        issues.append("최종매수_전일비교: no file found")
    else:
        issues.extend(_validate_diff_report(diff_path))

    if issues:
        print("[Outputs] validation failed")
        for issue in issues:
            print(f"[Outputs] {issue}")
        return 1

    print(
        f"[Outputs] validation passed for {report_path.name if report_path else 'n/a'}, "
        f"{core_path.name if core_path else 'n/a'}, {diff_path.name if diff_path else 'n/a'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
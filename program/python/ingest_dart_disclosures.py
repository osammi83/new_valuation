from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import os

import pandas as pd
import requests


TIMEOUT_SEC = 10
BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "output"


def fetch_todays_dart_provisional_stock_codes(api_key: str, date_yyyymmdd: str) -> set[str]:
    found: set[str] = set()
    page_no = 1
    while True:
        params = {
            "crtfc_key": api_key,
            "bgn_de": date_yyyymmdd,
            "end_de": date_yyyymmdd,
            "last_reprt_at": "Y",
            "page_no": str(page_no),
            "page_count": "100",
        }
        url = "https://opendart.fss.or.kr/api/list.json"
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT_SEC)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            break

        if str(data.get("status")) not in {"000", "013"}:
            break

        items = data.get("list") or []
        if not items:
            break

        for it in items:
            report_nm = str(it.get("report_nm") or "")
            stock_code = str(it.get("stock_code") or "").strip().zfill(6)
            if (
                stock_code
                and stock_code != "000000"
                and (
                    "연결재무제표기준영업(잠정)실적(공정공시)" in report_nm
                    or "정정공시" in report_nm
                    or "영업(잠정)실적" in report_nm
                    or "매출액또는손익구조30%이상변경" in report_nm
                )
            ):
                found.add(stock_code)

        total_page = int(data.get("total_page", 1) or 1)
        if page_no >= total_page:
            break
        page_no += 1

    return found


def scan_dart_disclosures(api_key: str, days_back: int = 1) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for d in range(max(1, int(days_back))):
        disclosure_date = (datetime.now().date() - pd.Timedelta(days=d)).strftime("%Y%m%d")
        tickers = sorted(fetch_todays_dart_provisional_stock_codes(api_key, disclosure_date))
        for ticker in tickers:
            rows.append({"disclosure_date": disclosure_date, "ticker": ticker})
    return pd.DataFrame(rows, columns=["disclosure_date", "ticker"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan DART provisional disclosures")
    parser.add_argument("--days-back", type=int, default=1, help="How many recent days to scan")
    parser.add_argument("--output", default="", help="Optional output CSV path")
    args = parser.parse_args()

    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        print("[DART] DART_API_KEY not set; nothing to scan.")
        return 0

    df = scan_dart_disclosures(api_key=api_key, days_back=args.days_back)
    output_path = Path(args.output) if args.output else OUTPUT_DIR / f"dart_disclosures_{datetime.now().strftime('%Y-%m-%d')}.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"[DART] Saved: {output_path} ({len(df)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

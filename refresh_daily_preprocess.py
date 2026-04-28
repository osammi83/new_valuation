from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import os
import re
from typing import Optional

import numpy as np
import pandas as pd
import requests
import urllib3
import yfinance as yf

try:
    from pykrx import stock as krx_stock
except Exception:
    krx_stock = None

from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parent
UNIVERSE_PATH = BASE_DIR / "universe.csv"
ASSUMPTIONS_PATH = BASE_DIR / "assumptions.csv"
EPS_CACHE_PATH = BASE_DIR / "eps_cache.csv"
MARKET_REGIME_PATH = BASE_DIR / "market_regime.csv"
OUTPUT_DIR = BASE_DIR / "output"
TIMEOUT_SEC = 10

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DART_DISCLOSURE_KEYWORDS = [
    "연결재무제표기준영업(잠정)실적(공정공시)",
    "잠정실적",
    "영업(잠정)실적",
    "공정공시",
]


def safe_float(v: object) -> float:
    try:
        if v is None:
            return np.nan
        return float(v)
    except Exception:
        return np.nan


def parse_number(value: object) -> float:
    if value is None:
        return np.nan
    cleaned = str(value).replace(",", "").replace("원", "").replace("배", "").strip()
    if cleaned in {"", "-", "N/A"}:
        return np.nan
    try:
        return float(cleaned)
    except Exception:
        return np.nan


def _zfill6(v: object) -> str:
    return str(v or "").strip().zfill(6)


def maybe_rebuild_universe_csv(top_n_kospi: int = 400, top_n_kosdaq: int = 400) -> Optional[pd.DataFrame]:
    if krx_stock is None:
        return None

    trade_date = None
    try:
        if hasattr(krx_stock, "get_nearest_business_day_in_a_week"):
            trade_date = krx_stock.get_nearest_business_day_in_a_week()
    except Exception:
        trade_date = None
    if not trade_date:
        trade_date = datetime.now().strftime("%Y%m%d")

    try:
        kospi = krx_stock.get_market_cap_by_ticker(date=trade_date, market="KOSPI")
        kosdaq = krx_stock.get_market_cap_by_ticker(date=trade_date, market="KOSDAQ")
    except Exception:
        return None

    def _build(df: pd.DataFrame, market_code: str, n: int) -> pd.DataFrame:
        df = df.copy()
        df["ticker"] = df.index.astype(str).str.zfill(6)
        cap_col = None
        for c in ["시가총액", "Market Cap", "market_cap"]:
            if c in df.columns:
                cap_col = c
                break
        if cap_col is None:
            cap_col = df.columns[0]
        df = df.sort_values(by=cap_col, ascending=False).head(n)
        names = []
        for t in df["ticker"].tolist():
            try:
                names.append(krx_stock.get_market_ticker_name(t))
            except Exception:
                names.append("")
        return pd.DataFrame({"name": names, "ticker": df["ticker"].tolist(), "market": market_code})

    u1 = _build(kospi, "KS", top_n_kospi)
    u2 = _build(kosdaq, "KQ", top_n_kosdaq)
    universe = pd.concat([u1, u2], ignore_index=True)
    pat = re.compile(r"(우$|\(우\)|스팩|SPAC|ETF|ETN)", re.IGNORECASE)
    universe = universe.loc[~universe["name"].astype(str).str.contains(pat, na=False)].copy()
    universe["ticker"] = universe["ticker"].astype(str).str.zfill(6)
    universe.to_csv(UNIVERSE_PATH, index=False, encoding="utf-8-sig")
    return universe


def _dart_get_corp_code(api_key: str, stock_code: str) -> Optional[str]:
    url = "https://opendart.fss.or.kr/api/company.json"
    params = {"crtfc_key": api_key, "stock_code": str(stock_code).zfill(6)}
    resp = requests.get(url, params=params, timeout=TIMEOUT_SEC)
    resp.raise_for_status()
    data = resp.json()
    if str(data.get("status")) != "000":
        return None
    corp_code = str(data.get("corp_code") or "").strip()
    return corp_code or None


def _dart_fetch_eps_by_year(api_key: str, stock_code: str, year: int) -> float:
    corp_code = _dart_get_corp_code(api_key, stock_code)
    if not corp_code:
        return np.nan

    url = "https://opendart.fss.or.kr/api/fnlttSinglAcnt.json"
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": "11011",
    }
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT_SEC)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return np.nan

    if str(data.get("status")) != "000":
        return np.nan

    items = data.get("list") or []
    if not items:
        return np.nan

    candidates = []
    for it in items:
        account_nm = str(it.get("account_nm") or "").strip()
        fs_div = str(it.get("fs_div") or "").strip()
        amount = it.get("thstrm_amount")
        if not account_nm:
            continue
        if ("주당" in account_nm and "이익" in account_nm) or ("EPS" in account_nm.upper()):
            v = parse_number(amount)
            if not np.isnan(v):
                candidates.append((0 if fs_div == "CFS" else 1, v, account_nm))

    if candidates:
        candidates.sort(key=lambda x: x[0])
        return float(candidates[0][1])
    return np.nan


def _dart_fetch_eps_history(api_key: str, stock_code: str, years: int = 3) -> list[float]:
    cur_year = datetime.now().year - 1
    hist = []
    for y in range(cur_year, cur_year - years, -1):
        hist.append(_dart_fetch_eps_by_year(api_key, stock_code, y))
    return hist


def _dart_scan_daily_disclosures(api_key: str, date_str: str) -> set[str]:
    url = "https://opendart.fss.or.kr/api/list.json"
    stock_codes: set[str] = set()
    for page_no in range(1, 4):
        params = {
            "crtfc_key": api_key,
            "bgn_de": date_str,
            "end_de": date_str,
            "page_no": str(page_no),
            "page_count": "100",
        }
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT_SEC)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            continue

        if str(data.get("status")) != "000":
            continue
        for item in data.get("list") or []:
            report_nm = str(item.get("report_nm") or "")
            stock_code = str(item.get("stock_code") or "").strip().zfill(6)
            if not stock_code:
                continue
            if any(keyword in report_nm for keyword in DART_DISCLOSURE_KEYWORDS):
                stock_codes.add(stock_code)
    return stock_codes


def _naver_scrape_eps(stock_code: str) -> tuple[float, float, str]:
    url = f"http://finance.naver.com/item/main.naver?code={str(stock_code).zfill(6)}"
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=TIMEOUT_SEC, verify=False)
    resp.raise_for_status()
    html = resp.text

    trailing_eps = np.nan
    consensus_eps = np.nan
    naver_sector = ""

    m_eps = re.search(r'id="_eps">\s*([0-9,\.\-]+)\s*</em>', html)
    if m_eps:
        trailing_eps = parse_number(m_eps.group(1))

    m_cns_eps = re.search(r'id="_cns_eps">\s*([0-9,\.\-]+)\s*</em>', html)
    if m_cns_eps:
        consensus_eps = parse_number(m_cns_eps.group(1))

    try:
        soup = BeautifulSoup(html, "html.parser")
        a_upjong = soup.select_one("a[href*='type=upjong']")
        if a_upjong:
            naver_sector = a_upjong.get_text(strip=True)
    except Exception:
        naver_sector = ""

    return float(trailing_eps), float(consensus_eps), str(naver_sector or "").strip()


def _infer_shares_outstanding(stock_code: str, close: float) -> float:
    if krx_stock is None or close <= 0:
        return np.nan
    try:
        trade_date = datetime.now().strftime("%Y%m%d")
        market = "KOSPI" if stock_code.startswith(("0", "1", "2", "3", "5")) else "KOSDAQ"
        cap_df = krx_stock.get_market_cap_by_ticker(date=trade_date, market=market)
        if cap_df is None or cap_df.empty:
            return np.nan
        cap_df.index = cap_df.index.astype(str).str.zfill(6)
        row = cap_df.loc[stock_code]
        cap_col = None
        for c in ["시가총액", "Market Cap", "market_cap"]:
            if c in cap_df.columns:
                cap_col = c
                break
        if cap_col is None:
            cap_col = cap_df.columns[0]
        market_cap = safe_float(row.get(cap_col))
        if np.isnan(market_cap) or market_cap <= 0:
            return np.nan
        return float(market_cap / close)
    except Exception:
        return np.nan


def _refresh_market_regime() -> pd.DataFrame:
    rows = []
    index_map = {
        "KOSPI": "^KS11",
        "KOSDAQ": "^KQ11",
    }
    for market, yfticker in index_map.items():
        try:
            hist = yf.Ticker(yfticker).history(period="6mo", auto_adjust=False)
        except Exception:
            hist = pd.DataFrame()
        if hist is None or hist.empty or "Close" not in hist.columns:
            continue
        close = safe_float(hist["Close"].dropna().iloc[-1])
        ma20 = safe_float(hist["Close"].dropna().rolling(20).mean().iloc[-1])
        factor = 1.0
        state = "neutral"
        if not np.isnan(close) and not np.isnan(ma20) and ma20 > 0 and close < ma20:
            factor = 0.5
            state = "bear"
        rows.append({
            "market": market,
            "ticker": yfticker,
            "close": close,
            "ma20": ma20,
            "regime_factor": factor,
            "regime_state": state,
            "asof_date": datetime.now().strftime("%Y-%m-%d"),
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        out.to_csv(MARKET_REGIME_PATH, index=False, encoding="utf-8-sig")
    return out


def main(limit: int | None = None, force: bool = False, period: str = "1y") -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    api_key = os.environ.get("DART_API_KEY", "").strip()

    if not UNIVERSE_PATH.exists():
        rebuilt = maybe_rebuild_universe_csv()
        if rebuilt is not None:
            print(f"[Universe] Auto rebuilt: {len(rebuilt)} rows")
    if not UNIVERSE_PATH.exists():
        raise FileNotFoundError(f"Missing universe.csv: {UNIVERSE_PATH}")

    universe = pd.read_csv(UNIVERSE_PATH, dtype={"ticker": str})
    universe["ticker"] = universe["ticker"].astype(str).str.zfill(6)
    if limit is not None and limit > 0:
        universe = universe.head(int(limit)).copy()

    # 1) Market regime snapshot
    regime = _refresh_market_regime()
    if not regime.empty:
        print(f"[Regime] Saved: {MARKET_REGIME_PATH}")

    # 2) Existing EPS cache
    if EPS_CACHE_PATH.exists():
        cache = pd.read_csv(EPS_CACHE_PATH, dtype={"ticker": str})
    else:
        cache = pd.DataFrame(columns=[
            "asof_date",
            "ticker",
            "trailing_eps_dart",
            "trailing_eps_scrape",
            "consensus_eps_scrape",
            "forward_eps_auto",
            "cagr_eps_3y_pct",
            "naver_sector",
            "source_primary",
            "shares_outstanding",
            "corp_action_flag",
            "daily_dart_disclosure_flag",
        ])
    if not cache.empty and "ticker" in cache.columns:
        cache["ticker"] = cache["ticker"].astype(str).str.zfill(6)

    if not api_key:
        print("[Warn] DART_API_KEY env var not set. DART-based updates will be skipped.")

    if not api_key and not force:
        print("[Info] Skipping DART disclosure/EPS refresh due to missing key.")

    today = datetime.now().strftime("%Y-%m-%d")
    today_compact = datetime.now().strftime("%Y%m%d")

    disclosure_hits: set[str] = set()
    if api_key:
        try:
            disclosure_hits = _dart_scan_daily_disclosures(api_key, today_compact)
        except Exception:
            disclosure_hits = set()
        print(f"[DART] disclosure hits: {len(disclosure_hits)}")

    rows = []
    for _, u in universe.iterrows():
        ticker = _zfill6(u.get("ticker"))
        name = str(u.get("name") or "").strip()

        cache_row = cache.loc[cache["ticker"].astype(str).str.zfill(6) == ticker]
        prev = cache_row.iloc[0] if not cache_row.empty else pd.Series(dtype=object)

        trailing_eps_dart = safe_float(prev.get("trailing_eps_dart", np.nan))
        trailing_eps_scrape = safe_float(prev.get("trailing_eps_scrape", np.nan))
        consensus_eps_scrape = safe_float(prev.get("consensus_eps_scrape", np.nan))
        naver_sector = str(prev.get("naver_sector", "") or "").strip()
        shares_outstanding = safe_float(prev.get("shares_outstanding", np.nan))
        source_primary = str(prev.get("source_primary", "") or "").strip()

        if api_key and (ticker in disclosure_hits or force or np.isnan(trailing_eps_dart)):
            try:
                hist = []
                for y in [datetime.now().year - 1, datetime.now().year - 2, datetime.now().year - 3]:
                    hist.append(_dart_fetch_eps_by_year(api_key, ticker, y))
                hist_series = [x for x in hist if not np.isnan(x)]
                if hist_series:
                    trailing_eps_dart = float(hist_series[0])
                    source_primary = "DART"

                # CAGR from up to 3 years of EPS if available
                cagr_eps_3y_pct = np.nan
                if len(hist_series) >= 3 and hist_series[-1] > 0 and hist_series[0] > 0:
                    try:
                        cagr = (hist_series[0] / hist_series[-1]) ** (1 / max(len(hist_series) - 1, 1)) - 1.0
                        cagr_eps_3y_pct = float(cagr * 100.0)
                    except Exception:
                        cagr_eps_3y_pct = np.nan
                else:
                    cagr_eps_3y_pct = np.nan
            except Exception:
                cagr_eps_3y_pct = np.nan
        else:
            cagr_eps_3y_pct = safe_float(prev.get("cagr_eps_3y_pct", np.nan))

        try:
            trailing_eps_scrape2, consensus_eps_scrape2, sector2 = _naver_scrape_eps(ticker)
            if not np.isnan(trailing_eps_scrape2):
                trailing_eps_scrape = trailing_eps_scrape2
            if not np.isnan(consensus_eps_scrape2):
                consensus_eps_scrape = consensus_eps_scrape2
            if sector2:
                naver_sector = sector2
            if not source_primary:
                source_primary = "SCRAPE" if (not np.isnan(consensus_eps_scrape) or not np.isnan(trailing_eps_scrape)) else "EMPTY"
        except Exception:
            pass

        # Forward EPS auto-generation.
        # Priority: DART-derived forward if CAGR available -> consensus -> trailing * growth assumption.
        forward_eps_auto = np.nan
        growth_assumption = 0.0
        try:
            # fallback growth based on CAGR if it is sane, else use 10% default
            if not np.isnan(cagr_eps_3y_pct):
                growth_assumption = float(np.clip(cagr_eps_3y_pct, -50.0, 50.0)) / 100.0
            else:
                growth_assumption = 0.10
        except Exception:
            growth_assumption = 0.10

        if not np.isnan(consensus_eps_scrape) and consensus_eps_scrape > 0:
            forward_eps_auto = float(consensus_eps_scrape)
        elif not np.isnan(trailing_eps_dart) and trailing_eps_dart > 0:
            forward_eps_auto = float(trailing_eps_dart * (1.0 + growth_assumption))
        elif not np.isnan(trailing_eps_scrape) and trailing_eps_scrape > 0:
            forward_eps_auto = float(trailing_eps_scrape * (1.0 + growth_assumption))

        close = np.nan
        try:
            yfticker = f"{ticker}.KS"
            if str(u.get("market") or "").strip() == "KQ":
                yfticker = f"{ticker}.KQ"
            hist_px = yf.Ticker(yfticker).history(period=period or "1y", auto_adjust=False)
            if hist_px is not None and not hist_px.empty and "Close" in hist_px.columns:
                close = safe_float(hist_px["Close"].dropna().iloc[-1])
        except Exception:
            close = np.nan

        inferred_shares = _infer_shares_outstanding(ticker, close) if not np.isnan(close) else np.nan
        corp_action_flag = 0
        if not np.isnan(inferred_shares):
            prev_sh = safe_float(prev.get("shares_outstanding", np.nan))
            if not np.isnan(prev_sh) and prev_sh > 0:
                if abs(inferred_shares - prev_sh) / prev_sh >= 0.10:
                    corp_action_flag = 1
            shares_outstanding = inferred_shares

        if np.isnan(cagr_eps_3y_pct):
            cagr_eps_3y_pct = safe_float(prev.get("cagr_eps_3y_pct", np.nan))

        rows.append({
            "asof_date": today,
            "ticker": ticker,
            "name": name,
            "trailing_eps_dart": safe_float(trailing_eps_dart),
            "trailing_eps_scrape": safe_float(trailing_eps_scrape),
            "consensus_eps_scrape": safe_float(consensus_eps_scrape),
            "forward_eps_auto": safe_float(forward_eps_auto),
            "cagr_eps_3y_pct": safe_float(cagr_eps_3y_pct),
            "naver_sector": str(naver_sector or "").strip(),
            "source_primary": source_primary if source_primary else ("DART" if not np.isnan(trailing_eps_dart) else ("SCRAPE" if not np.isnan(trailing_eps_scrape) or not np.isnan(consensus_eps_scrape) else "EMPTY")),
            "shares_outstanding": safe_float(shares_outstanding),
            "corp_action_flag": int(corp_action_flag),
            "daily_dart_disclosure_flag": int(ticker in disclosure_hits),
        })

    out = pd.DataFrame(rows)
    out.to_csv(EPS_CACHE_PATH, index=False, encoding="utf-8-sig")

    print(f"[Saved] {EPS_CACHE_PATH} ({len(out)} rows)")
    if not regime.empty:
        print(f"[Saved] {MARKET_REGIME_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily preprocessing: DART disclosure scan, forward EPS auto, corporate action proxy, market regime")
    parser.add_argument("--limit", type=int, default=0, help="Optional ticker limit for quick test")
    parser.add_argument("--force", action="store_true", help="Force refresh")
    parser.add_argument("--period", type=str, default="6mo", help="Price history period for market regime and share inference")
    args = parser.parse_args()
    main(limit=(args.limit if args.limit and args.limit > 0 else None), force=bool(args.force), period=str(args.period or "6mo"))

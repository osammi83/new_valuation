from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
import io
from pathlib import Path
import os
import re
from typing import Optional
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import pandas as pd
import requests
import urllib3

try:
    import FinanceDataReader as fdr
except Exception:
    fdr = None

if os.environ.get("KRX_ID", "").strip() and os.environ.get("KRX_PW", "").strip():
    try:
        from pykrx import stock as krx_stock
    except Exception:
        krx_stock = None
else:
    krx_stock = None


BASE_DIR = Path(__file__).resolve().parents[2]
UNIVERSE_PATH = BASE_DIR / "universe.csv"
OUTPUT_DIR = BASE_DIR / "output"
CACHE_PATH = BASE_DIR / "eps_cache.csv"
CORPCODE_CACHE_PATH = BASE_DIR / "dart_corp_code_cache.csv"
REFRESH_DAYS = 30
TIMEOUT_SEC = 10
_DART_CORP_MAP_CACHE: dict[str, str] | None = None
_SHARES_OUTSTANDING_CACHE: dict[str, float] | None = None
EXCLUDE_NAME_PAT = re.compile(r"(由ъ툩|REIT)", re.IGNORECASE)


def _can_use_pykrx() -> bool:
    if krx_stock is None:
        return False
    # In this environment, pykrx endpoints may require KRX auth env vars.
    # If absent, skip pykrx and use other data sources to avoid noisy errors.
    return bool(os.environ.get("KRX_ID", "").strip() and os.environ.get("KRX_PW", "").strip())


def _get_trade_date() -> str:
    if _can_use_pykrx() and hasattr(krx_stock, "get_nearest_business_day_in_a_week"):
        try:
            d = krx_stock.get_nearest_business_day_in_a_week()
            if d:
                return str(d)
        except Exception:
            pass
    return datetime.now().strftime("%Y%m%d")


def _load_shares_outstanding_map() -> dict[str, float]:
    global _SHARES_OUTSTANDING_CACHE
    if _SHARES_OUTSTANDING_CACHE is not None:
        return _SHARES_OUTSTANDING_CACHE

    out: dict[str, float] = {}
    if _can_use_pykrx():
        trade_date = _get_trade_date()
        for mkt in ["KOSPI", "KOSDAQ"]:
            try:
                cap_df = krx_stock.get_market_cap_by_ticker(date=trade_date, market=mkt)
            except Exception:
                cap_df = pd.DataFrame()
            if cap_df is None or cap_df.empty:
                continue

            w = cap_df.copy()
            w["ticker"] = w.index.astype(str).str.zfill(6)
            share_col = None
            for c in ["상장주식수", "Listed Shares", "shares_outstanding"]:
                if c in w.columns:
                    share_col = c
                    break
            if share_col is None:
                continue

            for _, r in w.iterrows():
                t = str(r.get("ticker") or "").zfill(6)
                s = safe_float(r.get(share_col))
                if t and not np.isnan(s) and s > 0:
                    out[t] = float(s)

    # Fallback to FinanceDataReader listing when pykrx is unavailable or unstable.
    if not out and fdr is not None:
        try:
            listing = fdr.StockListing("KRX")
            listing = listing.copy()
            listing["Code"] = listing["Code"].astype(str).str.zfill(6)

            share_col = "Stocks" if "Stocks" in listing.columns else None
            if share_col is None and {"Marcap", "Close"}.issubset(set(listing.columns)):
                listing["Stocks"] = pd.to_numeric(listing["Marcap"], errors="coerce") / pd.to_numeric(
                    listing["Close"], errors="coerce"
                )
                share_col = "Stocks"

            if share_col is not None:
                for _, r in listing.iterrows():
                    t = str(r.get("Code") or "").zfill(6)
                    s = safe_float(r.get(share_col))
                    if t and not np.isnan(s) and s > 0:
                        out[t] = float(s)
        except Exception:
            pass

    _SHARES_OUTSTANDING_CACHE = out
    return out

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _zfill6(v: object) -> str:
    return str(v or "").strip().zfill(6)


def is_excluded_instrument(name: object) -> bool:
    return bool(EXCLUDE_NAME_PAT.search(str(name or "").strip()))


def maybe_rebuild_universe_csv(top_n_kospi: int = 400, top_n_kosdaq: int = 400) -> Optional[pd.DataFrame]:
    """Build universe.csv (KOSPI 400 + KOSDAQ 400) if pykrx is available."""

    if krx_stock is None and fdr is None:
        return None

    trade_date = None
    try:
        if _can_use_pykrx() and hasattr(krx_stock, "get_nearest_business_day_in_a_week"):
            trade_date = krx_stock.get_nearest_business_day_in_a_week()
    except Exception:
        trade_date = None
    if not trade_date:
        trade_date = datetime.now().strftime("%Y%m%d")

    kospi = pd.DataFrame()
    kosdaq = pd.DataFrame()
    if _can_use_pykrx():
        try:
            kospi = krx_stock.get_market_cap_by_ticker(date=trade_date, market="KOSPI")
            kosdaq = krx_stock.get_market_cap_by_ticker(date=trade_date, market="KOSDAQ")
        except Exception:
            kospi = pd.DataFrame()
            kosdaq = pd.DataFrame()

    # Fallback path using FinanceDataReader listing.
    if (kospi.empty or kosdaq.empty) and fdr is not None:
        try:
            listing = fdr.StockListing("KRX")
            listing = listing.copy()
            listing["Code"] = listing["Code"].astype(str).str.zfill(6)
            if "Marcap" in listing.columns:
                listing["Marcap"] = pd.to_numeric(listing["Marcap"], errors="coerce")
            else:
                listing["Marcap"] = np.nan

            if "Market" not in listing.columns:
                listing["Market"] = ""

            ks = listing.loc[listing["Market"].astype(str).str.contains("KOSPI", case=False, na=False)].copy()
            kq = listing.loc[listing["Market"].astype(str).str.contains("KOSDAQ", case=False, na=False)].copy()

            ks = ks.sort_values(by="Marcap", ascending=False).head(top_n_kospi)
            kq = kq.sort_values(by="Marcap", ascending=False).head(top_n_kosdaq)

            universe = pd.concat(
                [
                    pd.DataFrame({"name": ks.get("Name", ""), "ticker": ks["Code"], "market": "KS"}),
                    pd.DataFrame({"name": kq.get("Name", ""), "ticker": kq["Code"], "market": "KQ"}),
                ],
                ignore_index=True,
            )
            pat = re.compile(r"(??|\(??)|?ㅽ뙥|SPAC|ETF|ETN|由ъ툩|REIT)", re.IGNORECASE)
            universe = universe.loc[~universe["name"].astype(str).str.contains(pat, na=False)].copy()
            universe["ticker"] = universe["ticker"].astype(str).str.zfill(6)
            universe.to_csv(UNIVERSE_PATH, index=False, encoding="utf-8-sig")
            return universe
        except Exception:
            pass

    if kospi.empty or kosdaq.empty:
        return None

    def _build(df: pd.DataFrame, market_code: str, n: int) -> pd.DataFrame:
        df = df.copy()
        df["ticker"] = df.index.astype(str).str.zfill(6)
        cap_col = None
        for c in ["?쒓?珥앹븸", "Market Cap", "market_cap"]:
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

    pat = re.compile(r"(??|\(??)|?ㅽ뙥|SPAC|ETF|ETN|由ъ툩|REIT)", re.IGNORECASE)
    universe = universe.loc[~universe["name"].astype(str).str.contains(pat, na=False)].copy()
    universe["ticker"] = universe["ticker"].astype(str).str.zfill(6)

    universe.to_csv(UNIVERSE_PATH, index=False, encoding="utf-8-sig")
    return universe


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
    cleaned = str(value).replace(",", "").replace("%", "").replace("배", "").strip()
    if cleaned in {"", "-", "N/A"}:
        return np.nan
    try:
        return float(cleaned)
    except Exception:
        return np.nan


def should_refresh(cache_path: Path, refresh_days: int = REFRESH_DAYS) -> bool:
    if not cache_path.exists():
        return True
    try:
        df = pd.read_csv(cache_path)
        if df.empty:
            return True
        if "asof_date" in df.columns:
            d = pd.to_datetime(df["asof_date"], errors="coerce").max()
            if pd.isna(d):
                return True
            age = datetime.now().date() - d.date()
            return age.days >= refresh_days
        mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
        age = datetime.now().date() - mtime.date()
        return age.days >= refresh_days
    except Exception:
        return True


def _load_dart_corp_code_map(api_key: str) -> dict[str, str]:
    # Reuse local cache if present.
    if CORPCODE_CACHE_PATH.exists():
        try:
            c = pd.read_csv(CORPCODE_CACHE_PATH, dtype={"stock_code": str, "corp_code": str})
            c["stock_code"] = c["stock_code"].astype(str).str.zfill(6)
            c["corp_code"] = c["corp_code"].astype(str).str.strip()
            c = c.loc[c["stock_code"].str.fullmatch(r"\d{6}", na=False) & (c["corp_code"] != "")]
            if not c.empty:
                return dict(zip(c["stock_code"], c["corp_code"]))
        except Exception:
            pass

    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    params = {"crtfc_key": api_key}
    resp = requests.get(url, params=params, timeout=TIMEOUT_SEC)
    resp.raise_for_status()

    mapping: dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        xml_name = None
        for n in zf.namelist():
            if n.lower().endswith(".xml"):
                xml_name = n
                break
        if xml_name is None:
            return mapping

        with zf.open(xml_name) as fp:
            root = ET.parse(fp).getroot()
            for item in root.findall("list"):
                corp_code = str(item.findtext("corp_code") or "").strip()
                stock_code = str(item.findtext("stock_code") or "").strip()
                if stock_code and stock_code != " " and re.fullmatch(r"\d{6}", stock_code):
                    mapping[stock_code] = corp_code

    if mapping:
        pd.DataFrame(
            [{"stock_code": k, "corp_code": v} for k, v in mapping.items()]
        ).to_csv(CORPCODE_CACHE_PATH, index=False, encoding="utf-8-sig")

    return mapping


def _dart_get_corp_code(api_key: str, stock_code: str) -> Optional[str]:
    global _DART_CORP_MAP_CACHE
    if _DART_CORP_MAP_CACHE is None:
        _DART_CORP_MAP_CACHE = _load_dart_corp_code_map(api_key)
    m = _DART_CORP_MAP_CACHE or {}
    return m.get(str(stock_code).zfill(6))


def _dart_fetch_eps(api_key: str, stock_code: str) -> float:
    corp_code = _dart_get_corp_code(api_key, stock_code)
    if not corp_code:
        return np.nan

    url = "https://opendart.fss.or.kr/api/fnlttSinglAcnt.json"
    # Try latest 3 business years.
    years = [datetime.now().year - 1, datetime.now().year - 2, datetime.now().year - 3]
    for year in years:
        params = {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": "11011",  # annual
        }
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT_SEC)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            continue

        if str(data.get("status")) != "000":
            continue

        items = data.get("list") or []
        if not items:
            continue

        # Prefer consolidated(CFS) if present.
        candidates = []
        for it in items:
            account_nm = str(it.get("account_nm") or "").strip()
            account_id = str(it.get("account_id") or "").strip()
            fs_div = str(it.get("fs_div") or "").strip()
            amount = it.get("thstrm_amount")
            if not account_nm:
                continue

            # DART account names vary; keep it robust.
            if (
                ("당기순이익" in account_nm)
                or ("EPS" in account_nm.upper())
                or ("BASICEARNINGSLOSSPERSHARE" in account_id.upper())
                or ("DILUTEDEARNINGSLOSSPERSHARE" in account_id.upper())
                or ("EARNINGSPERSHARE" in account_id.upper())
            ):
                v = parse_number(amount)
                if not np.isnan(v):
                    candidates.append((0 if fs_div == "CFS" else 1, v, account_nm))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            return float(candidates[0][1])

        # Fallback: derive EPS from net income / shares outstanding.
        # EPS accounts are often absent in fnlttSinglAcnt, but net income is usually available.
        ni_candidates = []
        for it in items:
            account_nm = str(it.get("account_nm") or "").strip()
            fs_div = str(it.get("fs_div") or "").strip()
            amount = parse_number(it.get("thstrm_amount"))
            if not account_nm or np.isnan(amount):
                continue
            if "당기순이익" in account_nm:
                ni_candidates.append((0 if fs_div == "CFS" else 1, amount, account_nm))

        if ni_candidates:
            ni_candidates.sort(key=lambda x: x[0])
            net_income = float(ni_candidates[0][1])
            shares_map = _load_shares_outstanding_map()
            shares = safe_float(shares_map.get(str(stock_code).zfill(6), np.nan))
            if not np.isnan(shares) and shares > 0:
                return float(net_income / shares)

    return np.nan


def _naver_scrape_eps(stock_code: str) -> tuple[float, float, str]:
    """Fallback scraping for EPS/consensus/sector.

    Returns: trailing_eps, consensus_eps, naver_sector
    """
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

    # Prefer lightweight regex extraction to avoid heavy HTML parser failures
    # during long unattended refresh jobs.
    m_sector = re.search(r"type=upjong[^>]*>([^<]+)</a>", html, flags=re.IGNORECASE)
    if m_sector:
        naver_sector = str(m_sector.group(1) or "").strip()

    return float(trailing_eps), float(consensus_eps), str(naver_sector or "").strip()


@dataclass
class CacheRow:
    asof_date: str
    ticker: str
    trailing_eps_dart: float
    trailing_eps_scrape: float
    consensus_eps_scrape: float
    naver_sector: str
    source_primary: str


def main(force: bool = False, limit: int | None = None) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if (not force) and (not should_refresh(CACHE_PATH, REFRESH_DAYS)):
        print(f"[EPS Cache] Skip refresh: {CACHE_PATH.name} is newer than {REFRESH_DAYS} days")
        return

    if not UNIVERSE_PATH.exists():
        rebuilt = maybe_rebuild_universe_csv()
        if rebuilt is not None:
            print(f"[Universe] Auto rebuilt: {len(rebuilt)} rows")

    if not UNIVERSE_PATH.exists():
        raise FileNotFoundError(f"Missing universe.csv: {UNIVERSE_PATH}")

    universe = pd.read_csv(UNIVERSE_PATH, dtype={"ticker": str})
    universe["ticker"] = universe["ticker"].astype(str).str.zfill(6)
    if "name" in universe.columns:
        universe = universe.loc[~universe["name"].apply(is_excluded_instrument)].copy()
    allowed_all_tickers = set(universe["ticker"].dropna().astype(str).str.zfill(6).unique().tolist())
    tickers = universe["ticker"].dropna().unique().tolist()
    if limit is not None and limit > 0:
        tickers = tickers[: int(limit)]

    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        print("[Warn] DART_API_KEY env var not set. DART-based EPS will be empty; using scraping fallback only.")

    rows: list[CacheRow] = []
    total = len(tickers)
    started = datetime.now()
    today = datetime.now().strftime("%Y-%m-%d")

    print(f"[EPS Cache] Refresh start: {total} tickers")

    for i, t in enumerate(tickers, start=1):
        dart_eps = np.nan
        trailing_eps_scrape = np.nan
        consensus_eps_scrape = np.nan
        sector = ""
        source = ""

        if api_key:
            try:
                dart_eps = _dart_fetch_eps(api_key, t)
            except Exception:
                dart_eps = np.nan

        try:
            trailing_eps_scrape, consensus_eps_scrape, sector = _naver_scrape_eps(t)
        except BaseException:
            trailing_eps_scrape, consensus_eps_scrape, sector = np.nan, np.nan, ""

        if not np.isnan(dart_eps):
            source = "DART"
        elif not np.isnan(consensus_eps_scrape) or not np.isnan(trailing_eps_scrape):
            source = "SCRAPE"
        else:
            source = "EMPTY"

        rows.append(
            CacheRow(
                asof_date=today,
                ticker=str(t).zfill(6),
                trailing_eps_dart=safe_float(dart_eps),
                trailing_eps_scrape=safe_float(trailing_eps_scrape),
                consensus_eps_scrape=safe_float(consensus_eps_scrape),
                naver_sector=str(sector or "").strip(),
                source_primary=source,
            )
        )

        if i == 1 or i % 50 == 0 or i == total:
            elapsed = (datetime.now() - started).total_seconds()
            pace = elapsed / i if i > 0 else np.nan
            eta = pace * (total - i) if i > 0 else np.nan
            eta_text = f"{eta/60:.1f}m" if not np.isnan(eta) else "N/A"
            print(f"[EPS Cache] {i}/{total} done | elapsed {elapsed/60:.1f}m | eta {eta_text}")

    out = pd.DataFrame([r.__dict__ for r in rows])

    # If a limited refresh is requested, do not truncate existing cache.
    # Merge refreshed rows into existing cache so untouched tickers remain.
    allowed_tickers = set(allowed_all_tickers)

    if limit is not None and limit > 0 and CACHE_PATH.exists():
        try:
            prev = pd.read_csv(CACHE_PATH, dtype={"ticker": str})
            prev["ticker"] = prev["ticker"].astype(str).str.zfill(6)
            out["ticker"] = out["ticker"].astype(str).str.zfill(6)

            keep_prev = prev.loc[prev["ticker"].isin(allowed_tickers)].copy()
            keep_prev = keep_prev.loc[~keep_prev["ticker"].isin(set(out["ticker"].tolist()))].copy()
            out = pd.concat([keep_prev, out], ignore_index=True)
            out = out.drop_duplicates(subset=["ticker"], keep="last")
            out = out.sort_values(by=["ticker"]).reset_index(drop=True)
        except Exception:
            # If merge fails for any reason, fall back to writing refreshed rows only.
            pass

    # Always keep cache aligned to currently allowed universe tickers.
    out["ticker"] = out["ticker"].astype(str).str.zfill(6)
    out = out.loc[out["ticker"].isin(allowed_tickers)].copy()

    out.to_csv(CACHE_PATH, index=False, encoding="utf-8-sig")

    dart_nonblank = int(out["trailing_eps_dart"].notna().sum())
    scrape_nonblank = int(out[["trailing_eps_scrape", "consensus_eps_scrape"]].notna().any(axis=1).sum())
    print(f"[EPS Cache] Saved: {CACHE_PATH}")
    print(f"[EPS Cache] DART eps nonblank: {dart_nonblank}/{len(out)}")
    print(f"[EPS Cache] Scrape eps nonblank: {scrape_nonblank}/{len(out)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh EPS cache (DART first, scrape fallback)")
    parser.add_argument("--force", action="store_true", help="Force refresh")
    parser.add_argument("--limit", type=int, default=0, help="Optional ticker limit for quick test")
    args = parser.parse_args()
    main(force=bool(args.force), limit=(args.limit if args.limit and args.limit > 0 else None))


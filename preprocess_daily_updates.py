from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path
import os
from typing import Optional
import re

import numpy as np
import pandas as pd
import requests

if os.environ.get("KRX_ID", "").strip() and os.environ.get("KRX_PW", "").strip():
    try:
        from pykrx import stock as krx_stock
    except Exception:
        krx_stock = None
else:
    krx_stock = None

from ingest_dart_disclosures import fetch_todays_dart_provisional_stock_codes
from refresh_eps_cache import _dart_fetch_eps, safe_float


BASE_DIR = Path(__file__).resolve().parent
UNIVERSE_PATH = BASE_DIR / "universe.csv"
EPS_CACHE_PATH = BASE_DIR / "eps_cache.csv"
ASSUMPTIONS_PATH = BASE_DIR / "assumptions.csv"
SHARES_SNAPSHOT_PATH = BASE_DIR / "shares_snapshot.csv"
TIMEOUT_SEC = 10
EXCLUDE_NAME_PAT = re.compile(r"(리츠|REIT)", re.IGNORECASE)


def _can_use_pykrx() -> bool:
    if krx_stock is None:
        return False
    return bool(os.environ.get("KRX_ID", "").strip() and os.environ.get("KRX_PW", "").strip())


def _zfill6(v: object) -> str:
    return str(v or "").strip().zfill(6)


def is_excluded_instrument(name: object) -> bool:
    return bool(EXCLUDE_NAME_PAT.search(str(name or "").strip()))


def get_trade_date() -> str:
    if _can_use_pykrx() and hasattr(krx_stock, "get_nearest_business_day_in_a_week"):
        try:
            d = krx_stock.get_nearest_business_day_in_a_week()
            if d:
                return str(d)
        except Exception:
            pass
    return datetime.now().strftime("%Y%m%d")


def get_outstanding_shares_snapshot(tickers: list[str], trade_date: str) -> pd.DataFrame:
    if not _can_use_pykrx():
        return pd.DataFrame(columns=["ticker", "asof_trade_date", "shares_outstanding"])

    snap_rows: list[dict[str, object]] = []

    # Fetch by market once for speed.
    market_frames: list[pd.DataFrame] = []
    for mkt in ["KOSPI", "KOSDAQ"]:
        try:
            cap_df = krx_stock.get_market_cap_by_ticker(date=trade_date, market=mkt)
        except Exception:
            cap_df = pd.DataFrame()
        if cap_df is not None and (not cap_df.empty):
            work = cap_df.copy()
            work["ticker"] = work.index.astype(str).str.zfill(6)
            share_col = None
            for c in ["상장주식수", "Listed Shares", "shares_outstanding"]:
                if c in work.columns:
                    share_col = c
                    break
            if share_col is None:
                continue
            market_frames.append(work[["ticker", share_col]].rename(columns={share_col: "shares_outstanding"}))

    if market_frames:
        all_df = pd.concat(market_frames, ignore_index=True)
        all_df = all_df.drop_duplicates(subset=["ticker"]).set_index("ticker")
        for t in tickers:
            if t in all_df.index:
                shares = safe_float(all_df.loc[t, "shares_outstanding"])
                snap_rows.append({"ticker": t, "asof_trade_date": trade_date, "shares_outstanding": shares})

    return pd.DataFrame(snap_rows)


def apply_share_change_rebalance(cache: pd.DataFrame, prev_snap: pd.DataFrame, cur_snap: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if cache.empty or prev_snap.empty or cur_snap.empty:
        return cache, 0

    prev = prev_snap.set_index("ticker")
    cur = cur_snap.set_index("ticker")
    common = sorted(set(prev.index).intersection(set(cur.index)).intersection(set(cache["ticker"].tolist())))

    changed = 0
    out = cache.copy()
    for t in common:
        old_shares = safe_float(prev.loc[t, "shares_outstanding"])
        new_shares = safe_float(cur.loc[t, "shares_outstanding"])
        if old_shares <= 0 or new_shares <= 0:
            continue
        ratio = old_shares / new_shares
        if np.isfinite(ratio) and abs(ratio - 1.0) > 0.01:
            m = out["ticker"] == t
            for col in ["trailing_eps_dart", "trailing_eps_scrape", "consensus_eps_scrape", "forward_eps_auto"]:
                if col in out.columns:
                    out.loc[m, col] = pd.to_numeric(out.loc[m, col], errors="coerce") * ratio
            out.loc[m, "source_primary"] = out.loc[m, "source_primary"].astype(str).str.replace("$", "|SHARE_REBAL", regex=True)
            changed += 1

    return out, changed


def fill_forward_eps_auto(cache: pd.DataFrame, assumptions: pd.DataFrame) -> pd.DataFrame:
    if cache.empty:
        return cache

    out = cache.copy()
    if "forward_eps_auto" not in out.columns:
        out["forward_eps_auto"] = np.nan
    if "eps_growth_auto_pct" not in out.columns:
        out["eps_growth_auto_pct"] = np.nan

    growth_map: dict[str, float] = {}
    if assumptions is not None and (not assumptions.empty) and ("ticker" in assumptions.columns):
        w = assumptions.copy()
        w["ticker"] = w["ticker"].astype(str).str.zfill(6)
        if "eps_growth_3y_pct" in w.columns:
            growth_map = dict(zip(w["ticker"], pd.to_numeric(w["eps_growth_3y_pct"], errors="coerce")))

    out["ticker"] = out["ticker"].astype(str).str.zfill(6)
    for idx, row in out.iterrows():
        cur_forward = safe_float(row.get("forward_eps_auto", np.nan))
        if not np.isnan(cur_forward):
            continue

        cns = safe_float(row.get("consensus_eps_scrape", np.nan))
        if not np.isnan(cns):
            out.at[idx, "forward_eps_auto"] = cns
            out.at[idx, "eps_growth_auto_pct"] = np.nan
            continue

        trailing = safe_float(row.get("trailing_eps_dart", np.nan))
        if np.isnan(trailing):
            trailing = safe_float(row.get("trailing_eps_scrape", np.nan))
        if np.isnan(trailing):
            continue

        growth_pct = safe_float(growth_map.get(str(row.get("ticker") or ""), 10.0))
        if np.isnan(growth_pct):
            growth_pct = 10.0
        growth = float(np.clip(growth_pct / 100.0, -0.5, 0.8))
        out.at[idx, "forward_eps_auto"] = trailing * (1.0 + growth)
        out.at[idx, "eps_growth_auto_pct"] = growth * 100.0

    return out


def main(limit: int | None = None, days_back: int = 1) -> None:
    if not UNIVERSE_PATH.exists() or not EPS_CACHE_PATH.exists():
        raise FileNotFoundError("universe.csv and eps_cache.csv are required before preprocess_daily_updates")

    universe = pd.read_csv(UNIVERSE_PATH, dtype={"ticker": str})
    universe["ticker"] = universe["ticker"].astype(str).str.zfill(6)
    if "name" in universe.columns:
        universe = universe.loc[~universe["name"].apply(is_excluded_instrument)].copy()
    tickers = universe["ticker"].dropna().unique().tolist()
    if limit is not None and limit > 0:
        tickers = tickers[: int(limit)]

    cache = pd.read_csv(EPS_CACHE_PATH, dtype={"ticker": str})
    cache["ticker"] = cache["ticker"].astype(str).str.zfill(6)

    assumptions = pd.DataFrame()
    if ASSUMPTIONS_PATH.exists():
        assumptions = pd.read_csv(ASSUMPTIONS_PATH, dtype={"ticker": str})

    # 1) DART provisional daily parse and selective EPS refresh.
    api_key = os.environ.get("DART_API_KEY", "").strip()
    refreshed_tickers: set[str] = set()
    if api_key:
        for d in range(max(1, int(days_back))):
            day = (datetime.now().date() - timedelta(days=d)).strftime("%Y%m%d")
            refreshed_tickers |= fetch_todays_dart_provisional_stock_codes(api_key, day)

        refreshed_tickers = {t for t in refreshed_tickers if t in set(tickers)}
        if refreshed_tickers:
            for t in sorted(refreshed_tickers):
                try:
                    eps = _dart_fetch_eps(api_key, t)
                except Exception:
                    eps = np.nan
                if not np.isnan(eps):
                    m = cache["ticker"] == t
                    if m.any():
                        cache.loc[m, "trailing_eps_dart"] = eps
                        cache.loc[m, "source_primary"] = "DART|DAILY_DISC"
                    else:
                        cache = pd.concat(
                            [
                                cache,
                                pd.DataFrame(
                                    [
                                        {
                                            "asof_date": datetime.now().strftime("%Y-%m-%d"),
                                            "ticker": t,
                                            "trailing_eps_dart": eps,
                                            "trailing_eps_scrape": np.nan,
                                            "consensus_eps_scrape": np.nan,
                                            "naver_sector": "",
                                            "source_primary": "DART|DAILY_DISC",
                                        }
                                    ]
                                ),
                            ],
                            ignore_index=True,
                        )

    # 2) Corporate action: shares outstanding change rebalance.
    trade_date = get_trade_date()
    cur_snap = get_outstanding_shares_snapshot(tickers=tickers, trade_date=trade_date)
    prev_snap = pd.DataFrame(columns=["ticker", "asof_trade_date", "shares_outstanding"])
    if SHARES_SNAPSHOT_PATH.exists():
        try:
            prev_snap = pd.read_csv(SHARES_SNAPSHOT_PATH, dtype={"ticker": str, "asof_trade_date": str})
            prev_snap["ticker"] = prev_snap["ticker"].astype(str).str.zfill(6)
        except Exception:
            prev_snap = pd.DataFrame(columns=["ticker", "asof_trade_date", "shares_outstanding"])

    cache, changed_count = apply_share_change_rebalance(cache=cache, prev_snap=prev_snap, cur_snap=cur_snap)

    # 3) Forward EPS auto fill.
    cache = fill_forward_eps_auto(cache=cache, assumptions=assumptions)

    cache["asof_date"] = datetime.now().strftime("%Y-%m-%d")
    cache = cache.sort_values(by=["ticker"]).reset_index(drop=True)
    cache.to_csv(EPS_CACHE_PATH, index=False, encoding="utf-8-sig")
    if not cur_snap.empty:
        cur_snap.to_csv(SHARES_SNAPSHOT_PATH, index=False, encoding="utf-8-sig")

    print(f"[Preprocess] Updated eps_cache: {EPS_CACHE_PATH}")
    print(f"[Preprocess] DART daily disclosure refresh count: {len(refreshed_tickers)}")
    print(f"[Preprocess] Shares change rebalance count: {changed_count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily preprocess for EPS cache (DART disclosure + share-change + forward fill)")
    parser.add_argument("--limit", type=int, default=0, help="Optional ticker limit for quick test")
    parser.add_argument("--days-back", type=int, default=1, help="How many recent days to scan for DART disclosures")
    args, _unknown = parser.parse_known_args()
    main(
        limit=(args.limit if args.limit and args.limit > 0 else None),
        days_back=(args.days_back if args.days_back and args.days_back > 0 else 1),
    )

from __future__ import annotations

import argparse
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

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
EXCLUDE_NAME_PAT = re.compile(r"(由ъ툩|REIT)", re.IGNORECASE)


def _can_use_pykrx() -> bool:
    if krx_stock is None:
        return False
    return bool(os.environ.get("KRX_ID", "").strip() and os.environ.get("KRX_PW", "").strip())


def _zfill6(value: object) -> str:
    return str(value or "").strip().zfill(6)


def _is_excluded_instrument(name: object) -> bool:
    return bool(EXCLUDE_NAME_PAT.search(str(name or "").strip()))


def _load_universe() -> pd.DataFrame:
    if not UNIVERSE_PATH.exists():
        raise FileNotFoundError(f"Missing universe.csv: {UNIVERSE_PATH}")
    universe = pd.read_csv(UNIVERSE_PATH, dtype={"ticker": str}, keep_default_na=True)
    if universe.empty:
        raise RuntimeError("universe.csv is empty")
    universe["ticker"] = universe["ticker"].astype(str).str.zfill(6)
    if "name" in universe.columns:
        universe = universe.loc[~universe["name"].apply(_is_excluded_instrument)].copy()
    return universe.reset_index(drop=True)


def _nearest_business_day() -> str:
    if _can_use_pykrx() and hasattr(krx_stock, "get_nearest_business_day_in_a_week"):
        try:
            value = krx_stock.get_nearest_business_day_in_a_week()
            if value:
                return str(value)
        except Exception:
            pass
    return datetime.now().strftime("%Y%m%d")


def _normalize_ohlcv_frame(frame: pd.DataFrame, ticker: str, market: str, data_source: str, trade_date: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["trade_date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "value_traded", "data_source", "market", "stale_flag"])

    work = frame.copy()
    if isinstance(work.index, pd.DatetimeIndex):
        work = work.reset_index()
    if "Date" in work.columns:
        work = work.rename(columns={"Date": "trade_date"})
    elif "Datetime" in work.columns:
        work = work.rename(columns={"Datetime": "trade_date"})
    elif "index" in work.columns and "trade_date" not in work.columns:
        work = work.rename(columns={"index": "trade_date"})

    rename_map = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close", "Volume": "volume"}
    for src, dst in rename_map.items():
        if src in work.columns:
            work = work.rename(columns={src: dst})

    if "adj_close" not in work.columns and "close" in work.columns:
        work["adj_close"] = work["close"]

    for col in ["open", "high", "low", "close", "adj_close", "volume"]:
        if col not in work.columns:
            work[col] = np.nan
        work[col] = pd.to_numeric(work[col], errors="coerce")

    if "trade_date" in work.columns:
        work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.strftime("%Y%m%d")
    else:
        work["trade_date"] = trade_date

    work = work.dropna(subset=["trade_date"]).copy()
    work = work.loc[work["trade_date"] <= trade_date].copy()
    work["ticker"] = ticker
    work["market"] = market
    work["data_source"] = data_source
    work["stale_flag"] = np.where(work["trade_date"] < trade_date, 1, 0)
    work["value_traded"] = np.where(
        pd.notna(work["close"]) & pd.notna(work["volume"]),
        pd.to_numeric(work["close"], errors="coerce") * pd.to_numeric(work["volume"], errors="coerce"),
        np.nan,
    )
    work = work.drop_duplicates(subset=["trade_date", "ticker"], keep="last").sort_values(by="trade_date")
    return work[["trade_date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "value_traded", "data_source", "market", "stale_flag"]]


def _fetch_krx_history(ticker: str, market: str, trade_date: str) -> pd.DataFrame:
    if not _can_use_pykrx():
        return pd.DataFrame()
    try:
        start = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=120)).strftime("%Y%m%d")
        hist = krx_stock.get_market_ohlcv_by_date(start, trade_date, ticker)
        if hist is None or hist.empty:
            return pd.DataFrame()
        return _normalize_ohlcv_frame(hist, ticker=ticker, market=market, data_source="pykrx", trade_date=trade_date)
    except Exception:
        return pd.DataFrame()


def _fetch_yfinance_history(ticker: str, market: str, period: str) -> pd.DataFrame:
    suffix = ".KS" if market == "KS" else ".KQ"
    symbol = f"{ticker}{suffix}"
    try:
        hist = yf.Ticker(symbol).history(period=period, auto_adjust=False)
    except Exception:
        return pd.DataFrame()
    return _normalize_ohlcv_frame(hist, ticker=ticker, market=market, data_source="yfinance", trade_date=datetime.now().strftime("%Y%m%d"))


def _fetch_index_history(index_code: str, trade_date: str, period: str) -> pd.DataFrame:
    symbol = "^KS11" if index_code == "KOSPI" else "^KQ11"
    try:
        hist = yf.Ticker(symbol).history(period=period, auto_adjust=False)
    except Exception:
        return pd.DataFrame()
    if hist is None or hist.empty:
        return pd.DataFrame()

    work = hist.copy().reset_index()
    if "Date" in work.columns:
        work = work.rename(columns={"Date": "trade_date"})
    rename_map = {"Close": "close", "Volume": "volume"}
    for src, dst in rename_map.items():
        if src in work.columns:
            work = work.rename(columns={src: dst})
    for col in ["close", "volume"]:
        if col not in work.columns:
            work[col] = np.nan
        work[col] = pd.to_numeric(work[col], errors="coerce")
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.strftime("%Y%m%d")
    work = work.dropna(subset=["trade_date"]).copy()
    work = work.loc[work["trade_date"] <= trade_date].copy()
    work["index_code"] = index_code
    work["advance_count"] = np.nan
    work["decline_count"] = np.nan
    work["data_source"] = "yfinance"
    return work[["trade_date", "index_code", "close", "volume", "advance_count", "decline_count", "data_source"]]


def _index_breadth_from_prices(price_daily: pd.DataFrame) -> pd.DataFrame:
    if price_daily.empty:
        return pd.DataFrame(columns=["trade_date", "index_code", "close", "volume", "advance_count", "decline_count", "data_source"])

    work = price_daily.copy()
    work["trade_date"] = work["trade_date"].astype(str)
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    work = work.sort_values(by=["ticker", "trade_date"])
    work["prev_close"] = work.groupby("ticker")["close"].shift(1)
    work["adv"] = (work["close"] > work["prev_close"]).astype(float)
    work["dec"] = (work["close"] < work["prev_close"]).astype(float)
    breadth = work.groupby("trade_date", as_index=False).agg(advance_count=("adv", "sum"), decline_count=("dec", "sum"))
    return breadth


def ingest_market_data(limit: int | None = None, period: str = "1y") -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    universe = _load_universe()
    if limit is not None and limit > 0:
        universe = universe.head(int(limit)).copy()

    trade_date = _nearest_business_day()
    price_frames: list[pd.DataFrame] = []
    source_rows: list[dict[str, object]] = []

    for _, row in universe.iterrows():
        ticker = _zfill6(row.get("ticker"))
        market = str(row.get("market", "KS") or "KS").strip() or "KS"

        krx_frame = _fetch_krx_history(ticker, market, trade_date)
        if not krx_frame.empty:
            frame = krx_frame
            source = "pykrx"
        else:
            frame = _fetch_yfinance_history(ticker, market, period=period)
            source = "yfinance" if not frame.empty else "missing"

        if frame.empty:
            source_rows.append({"ticker": ticker, "market": market, "data_source": "missing", "row_count": 0, "latest_trade_date": "", "stale_flag": 1})
            continue

        frame["ticker"] = frame["ticker"].astype(str).str.zfill(6)
        frame["trade_date"] = frame["trade_date"].astype(str)
        frame["stale_flag"] = np.where(frame["trade_date"] < trade_date, 1, 0)
        price_frames.append(frame)

        latest_date = frame["trade_date"].max()
        latest_row = frame.loc[frame["trade_date"] == latest_date].tail(1)
        latest_close = float(pd.to_numeric(latest_row["close"], errors="coerce").iloc[0]) if not latest_row.empty else np.nan
        source_rows.append(
            {
                "ticker": ticker,
                "market": market,
                "data_source": source,
                "row_count": int(len(frame)),
                "latest_trade_date": latest_date,
                "stale_flag": int(1 if latest_date != trade_date else 0),
                "latest_close": latest_close,
            }
        )

    price_daily = pd.concat(price_frames, ignore_index=True) if price_frames else pd.DataFrame(
        columns=["trade_date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "value_traded", "data_source", "market", "stale_flag"]
    )

    if not price_daily.empty:
        price_daily["trade_date"] = price_daily["trade_date"].astype(str)
        price_daily = price_daily.drop_duplicates(subset=["trade_date", "ticker"], keep="last").reset_index(drop=True)
        for col in ["open", "high", "low", "close", "adj_close", "volume", "value_traded"]:
            price_daily[col] = pd.to_numeric(price_daily[col], errors="coerce")
        price_daily["stale_flag"] = pd.to_numeric(price_daily["stale_flag"], errors="coerce").fillna(0).astype(int)

    market_frames: list[pd.DataFrame] = []
    for index_code in ["KOSPI", "KOSDAQ"]:
        idx_frame = _fetch_index_history(index_code, trade_date, period=period)
        if idx_frame.empty:
            idx_frame = pd.DataFrame(
                {
                    "trade_date": [trade_date],
                    "index_code": [index_code],
                    "close": [np.nan],
                    "volume": [np.nan],
                    "advance_count": [np.nan],
                    "decline_count": [np.nan],
                    "data_source": ["missing"],
                }
            )
        market_frames.append(idx_frame.drop_duplicates(subset=["trade_date", "index_code"], keep="last"))

    market_index_daily = pd.concat(market_frames, ignore_index=True) if market_frames else pd.DataFrame(
        columns=["trade_date", "index_code", "close", "volume", "advance_count", "decline_count", "data_source"]
    )
    if not price_daily.empty and not market_index_daily.empty:
        breadth = _index_breadth_from_prices(price_daily)
        market_index_daily = market_index_daily.merge(breadth, on="trade_date", how="left", suffixes=("", "_breadth"))
        if "advance_count_breadth" in market_index_daily.columns:
            market_index_daily["advance_count"] = market_index_daily["advance_count_breadth"].combine_first(market_index_daily["advance_count"])
            market_index_daily["decline_count"] = market_index_daily["decline_count_breadth"].combine_first(market_index_daily["decline_count"])
            market_index_daily = market_index_daily.drop(columns=["advance_count_breadth", "decline_count_breadth"])

    source_health = pd.DataFrame(source_rows)
    if not source_health.empty:
        source_health = source_health.sort_values(by=["stale_flag", "row_count", "ticker"], ascending=[False, False, True]).reset_index(drop=True)

    return price_daily, market_index_daily, source_health


def _write_outputs(price_daily: pd.DataFrame, market_index_daily: pd.DataFrame, source_health: pd.DataFrame, output_prefix: str | None = None) -> tuple[Path, Path, Path]:
    today = datetime.now().strftime("%Y-%m-%d")
    suffix = output_prefix or today
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    price_path = OUTPUT_DIR / f"price_daily_{suffix}.csv"
    market_path = OUTPUT_DIR / f"market_index_daily_{suffix}.csv"
    health_path = OUTPUT_DIR / f"source_health_{suffix}.csv"

    price_daily.to_csv(price_path, index=False, encoding="utf-8-sig")
    market_index_daily.to_csv(market_path, index=False, encoding="utf-8-sig")
    source_health.to_csv(health_path, index=False, encoding="utf-8-sig")

    price_daily.to_csv(OUTPUT_DIR / "price_daily.csv", index=False, encoding="utf-8-sig")
    market_index_daily.to_csv(OUTPUT_DIR / "market_index_daily.csv", index=False, encoding="utf-8-sig")
    source_health.to_csv(OUTPUT_DIR / "source_health.csv", index=False, encoding="utf-8-sig")
    return price_path, market_path, health_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest daily market data into canonical CSVs")
    parser.add_argument("--limit", type=int, default=0, help="Optional ticker limit for quick test")
    parser.add_argument("--period", type=str, default="1y", help="history period for yfinance fallback")
    parser.add_argument("--output-prefix", type=str, default="", help="Optional file suffix")
    args = parser.parse_args()

    limit = args.limit if args.limit and args.limit > 0 else None
    price_daily, market_index_daily, source_health = ingest_market_data(limit=limit, period=str(args.period or "1y"))
    price_path, market_path, health_path = _write_outputs(price_daily, market_index_daily, source_health, output_prefix=args.output_prefix or None)

    print(f"[Market] Saved: {price_path} ({len(price_daily)} rows)")
    print(f"[Market] Saved: {market_path} ({len(market_index_daily)} rows)")
    print(f"[Market] Saved: {health_path} ({len(source_health)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


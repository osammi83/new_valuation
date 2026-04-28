from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import build_daily_report as report


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
PRICE_DAILY_PATH = OUTPUT_DIR / "price_daily.csv"
MARKET_INDEX_DAILY_PATH = OUTPUT_DIR / "market_index_daily.csv"


def _prepare_inputs(limit: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not report.UNIVERSE_PATH.exists():
        raise FileNotFoundError(f"Missing universe.csv: {report.UNIVERSE_PATH}")

    universe = pd.read_csv(report.UNIVERSE_PATH, dtype={"ticker": str})
    universe["ticker"] = universe["ticker"].astype(str).str.zfill(6)
    if "name" in universe.columns:
        universe = universe.loc[~universe["name"].apply(report.is_excluded_instrument)].copy()
    if limit is not None and limit > 0:
        universe = universe.head(int(limit)).copy()

    assumptions = pd.DataFrame({"ticker": []})
    if report.ASSUMPTIONS_PATH.exists():
        assumptions = pd.read_csv(report.ASSUMPTIONS_PATH, dtype={"ticker": str})

    eps_cache = pd.DataFrame({"ticker": []})
    if report.EPS_CACHE_PATH.exists():
        eps_cache = pd.read_csv(report.EPS_CACHE_PATH, dtype={"ticker": str})

    return universe, assumptions, eps_cache


def _load_price_history() -> pd.DataFrame:
    if not PRICE_DAILY_PATH.exists():
        return pd.DataFrame()
    price_daily = pd.read_csv(PRICE_DAILY_PATH, dtype={"ticker": str, "trade_date": str}, keep_default_na=True)
    if price_daily.empty:
        return pd.DataFrame()
    price_daily["ticker"] = price_daily["ticker"].astype(str).str.zfill(6)
    price_daily["trade_date"] = price_daily["trade_date"].astype(str)
    for col in ["open", "high", "low", "close", "adj_close", "volume", "value_traded"]:
        if col in price_daily.columns:
            price_daily[col] = pd.to_numeric(price_daily[col], errors="coerce")
    return price_daily


def _load_market_index_history() -> pd.DataFrame:
    if not MARKET_INDEX_DAILY_PATH.exists():
        return pd.DataFrame()
    market_index = pd.read_csv(MARKET_INDEX_DAILY_PATH, dtype={"trade_date": str}, keep_default_na=True)
    if market_index.empty:
        return pd.DataFrame()
    market_index["trade_date"] = market_index["trade_date"].astype(str)
    for col in ["close", "volume", "advance_count", "decline_count"]:
        if col in market_index.columns:
            market_index[col] = pd.to_numeric(market_index[col], errors="coerce")
    return market_index


def build_features(limit: int | None = None, period: str = "1y") -> pd.DataFrame:
    universe, assumptions, eps_cache = _prepare_inputs(limit=limit)
    price_daily = _load_price_history()
    market_index_daily = _load_market_index_history()
    market_regime, regime_mult = report.calc_market_regime_and_multiplier(period="6mo")

    rows: list[dict[str, object]] = []
    for _, u in universe.iterrows():
        ticker = report._zfill6(u.get("ticker"))
        name = str(u.get("name") or "").strip()
        market = str(u.get("market") or "").strip() or "KS"

        hist = price_daily.loc[price_daily["ticker"].astype(str).str.zfill(6) == ticker].copy()
        if hist.empty or "close" not in hist.columns:
            continue

        hist = hist.sort_values(by="trade_date")
        close_series = pd.to_numeric(hist["close"], errors="coerce").dropna()
        if close_series.empty:
            continue

        close = report.safe_float(close_series.iloc[-1])
        ma20 = report.safe_float(close_series.rolling(20).mean().iloc[-1])
        ma60 = report.safe_float(close_series.rolling(60).mean().iloc[-1])
        ma120 = report.safe_float(close_series.rolling(120).mean().iloc[-1])
        ma200 = report.safe_float(close_series.rolling(200).mean().iloc[-1])
        above_ma200 = int(close > ma200) if ma200 and ma200 > 0 else 0

        rsi14 = report.calc_rsi(close_series)
        macd_hist = report.calc_macd_hist(close_series)
        volume_ratio_20d = report.calc_volume_ratio(hist.get("volume"))
        breakout_20d_high = report.calc_breakout_20d_high(close_series)
        return_5d = report.calc_returns(close_series, 5)
        return_20d = report.calc_returns(close_series, 20)

        if not market_index_daily.empty:
            idx_row = market_index_daily.loc[market_index_daily["index_code"].astype(str).str.upper() == ("KOSPI" if market == "KS" else "KOSDAQ")]
            if not idx_row.empty:
                idx_row = idx_row.sort_values(by="trade_date")
                _ = idx_row.tail(1)

        arow = assumptions.loc[assumptions["ticker"].astype(str).str.zfill(6) == ticker]
        if arow.empty:
            a = pd.Series(report.DEFAULT_ASSUMPTION)
        else:
            a = arow.iloc[0]

        cache_row = eps_cache.loc[eps_cache["ticker"].astype(str).str.zfill(6) == ticker]
        trailing_eps_dart = np.nan
        consensus_eps_scrape = np.nan
        forward_eps_auto = np.nan
        source_primary = ""
        if not cache_row.empty:
            trailing_eps_dart = report.safe_float(cache_row.iloc[0].get("trailing_eps_dart", np.nan))
            consensus_eps_scrape = report.safe_float(cache_row.iloc[0].get("consensus_eps_scrape", np.nan))
            forward_eps_auto = report.safe_float(cache_row.iloc[0].get("forward_eps_auto", np.nan))
            source_primary = str(cache_row.iloc[0].get("source_primary", "") or "").strip()

        manual_forward_eps = report.safe_float(a.get("manual_forward_eps", np.nan))
        expected_eps = manual_forward_eps
        eps_source_used = "MANUAL_FORWARD_EPS"
        if np.isnan(expected_eps):
            expected_eps = trailing_eps_dart
            eps_source_used = "TRAILING_DART"
        if np.isnan(expected_eps):
            expected_eps = consensus_eps_scrape
            eps_source_used = "CONSENSUS_SCRAPE"
        if np.isnan(expected_eps):
            expected_eps = forward_eps_auto
            eps_source_used = "FORWARD_AUTO"

        if np.isnan(expected_eps) and (not np.isnan(trailing_eps_dart)):
            growth_pct = report.safe_float(a.get("eps_growth_3y_pct", 10.0))
            growth = growth_pct / 100.0 if not np.isnan(growth_pct) else 0.10
            growth = float(np.clip(growth, -0.5, 0.8))
            expected_eps = trailing_eps_dart * (1.0 + growth)
            eps_source_used = "GROWTH_AUTO"

        target_pe_base = report.safe_float(a.get("target_pe_base", 12.0))
        fair_price_base = expected_eps * target_pe_base if (not np.isnan(expected_eps) and close > 0) else np.nan
        upside_base_pct = ((fair_price_base / close) - 1.0) * 100.0 if (not np.isnan(fair_price_base) and close > 0) else np.nan
        pe_now = close / expected_eps if (close > 0 and expected_eps and not np.isnan(expected_eps) and expected_eps != 0) else np.nan

        row = {
            "기준일": datetime.now().strftime("%Y-%m-%d"),
            "종목명": name,
            "종목코드": ticker,
            "시장": market,
            "섹터그룹": str(a.get("sector_group", "기타")),
            "종가": close,
            "20일이평": ma20,
            "60일이평": ma60,
            "120일이평": ma120,
            "200일이평": ma200,
            "200일선상단여부": above_ma200,
            "RSI14": rsi14,
            "MACD히스토그램": macd_hist,
            "거래량비율20일": volume_ratio_20d,
            "20일돌파": breakout_20d_high,
            "5일수익률(%)": return_5d,
            "20일수익률(%)": return_20d,
            "후행EPS(DART)": trailing_eps_dart,
            "컨센서스EPS(스크랩)": consensus_eps_scrape,
            "자동선행EPS": forward_eps_auto,
            "원본EPS출처": source_primary,
            "EPS소스": eps_source_used,
            "수동선행EPS": manual_forward_eps,
            "모델EPS": expected_eps,
            "현재PER": pe_now,
            "적정주가_기준": fair_price_base,
            "상승여력(%)": upside_base_pct,
            "밸류점수": report.calc_valuation_score(report.safe_float(upside_base_pct)),
            "기술점수": report.calc_technical_score(pd.Series({
                "close": close,
                "ma20": ma20,
                "ma60": ma60,
                "ma200": ma200,
                "rsi14": rsi14,
                "macd_hist": macd_hist,
                "volume_ratio_20d": volume_ratio_20d,
                "breakout_20d_high": breakout_20d_high,
            })),
            "시장상태": market_regime,
            "레짐비중배수": regime_mult,
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("No features produced. Data collection failed.")

    df["date"] = df["기준일"]
    df["market_regime"] = df["시장상태"]
    df["regime_weight_multiplier"] = df["레짐비중배수"]
    df["sector_group"] = df["섹터그룹"].astype(str)
    return df


def main() -> int:
    parser = argparse.ArgumentParser(description="Build daily feature table")
    parser.add_argument("--limit", type=int, default=0, help="Optional ticker limit for quick test")
    parser.add_argument("--period", type=str, default="1y", help="yfinance history period")
    parser.add_argument("--output", type=str, default="", help="Optional explicit output CSV path")
    args = parser.parse_args()

    limit = args.limit if args.limit and args.limit > 0 else None
    df = build_features(limit=limit, period=str(args.period or "1y"))

    output_path = Path(args.output) if args.output else OUTPUT_DIR / f"기본피처_{datetime.now().strftime('%Y-%m-%d')}.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"[Features] Saved: {output_path} ({len(df)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
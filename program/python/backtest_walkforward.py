from __future__ import annotations

import argparse
import os
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "output"
PRICE_DAILY_PATH = OUTPUT_DIR / "price_daily.csv"


def _latest_price_path() -> Path:
    dated_files = [path for path in OUTPUT_DIR.glob("price_daily_*.csv") if path.is_file()]
    if dated_files:
        return max(dated_files, key=lambda path: path.stat().st_mtime)
    return PRICE_DAILY_PATH


def _atomic_write_csv(df: pd.DataFrame, path: Path) -> Path:
    tmp_path = path.with_name(f"{path.stem}.tmp{path.suffix}")
    df.to_csv(tmp_path, index=False, encoding="utf-8-sig")
    os.replace(tmp_path, path)
    return path


def _extract_date_from_name(path: Path) -> str | None:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    return match.group(1) if match else None


def _latest_reports() -> list[Path]:
    candidates: dict[str, Path] = {}
    for path in OUTPUT_DIR.glob("?곸꽭由ы룷??*.csv"):
        if not path.is_file():
            continue
        report_date = _extract_date_from_name(path)
        if not report_date:
            continue
        current = candidates.get(report_date)
        if current is None or path.stat().st_mtime > current.stat().st_mtime:
            candidates[report_date] = path
    return [candidates[key] for key in sorted(candidates.keys())]


def _load_reports() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in _latest_reports():
        report_date = _extract_date_from_name(path)
        if report_date is None:
            continue
        frame = pd.read_csv(path, keep_default_na=True)
        frame["report_date"] = report_date
        frame["report_source"] = path.name
        if "醫낅ぉ肄붾뱶" in frame.columns:
            frame["醫낅ぉ肄붾뱶"] = frame["醫낅ぉ肄붾뱶"].astype(str).str.zfill(6)
        frames.append(frame)
    if not frames:
        raise FileNotFoundError(f"No detailed report CSVs found in {OUTPUT_DIR}")
    return pd.concat(frames, ignore_index=True)


def _load_price_history() -> pd.DataFrame:
    price_path = _latest_price_path()
    if not price_path.exists():
        raise FileNotFoundError(f"Missing price history: {price_path}")
    price = pd.read_csv(price_path, dtype={"ticker": str}, keep_default_na=True)
    if price.empty:
        raise RuntimeError("price_daily.csv is empty")
    price["ticker"] = price["ticker"].astype(str).str.zfill(6)
    price["trade_date"] = pd.to_datetime(price["trade_date"].astype(str), errors="coerce")
    price = price.dropna(subset=["trade_date", "close"]).copy()
    price["close"] = pd.to_numeric(price["close"], errors="coerce")
    if "volume" in price.columns:
        price["volume"] = pd.to_numeric(price["volume"], errors="coerce")
    return price.sort_values(["ticker", "trade_date"]).reset_index(drop=True)


def _parse_csv_list(raw: str, default: list[int]) -> list[int]:
    if not raw.strip():
        return default
    values: list[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        values.append(int(token))
    return values or default


def _forward_return(group: pd.DataFrame, report_date: pd.Timestamp, horizon_days: int) -> dict[str, float] | None:
    report_date = pd.Timestamp(report_date).normalize()
    dates = group["trade_date"].reset_index(drop=True)
    closes = group["close"].reset_index(drop=True)
    idx = int(dates.searchsorted(report_date, side="right") - 1)
    if idx < 0 or idx + horizon_days >= len(group):
        return None
    current_date = dates.iloc[idx]
    current_close = float(closes.iloc[idx])
    future_close = float(closes.iloc[idx + horizon_days])
    if not np.isfinite(current_close) or current_close <= 0 or not np.isfinite(future_close):
        return None
    return {
        "current_trade_date": current_date.strftime("%Y-%m-%d"),
        "current_close": current_close,
        "future_close": future_close,
        "gross_return_pct": (future_close / current_close - 1.0) * 100.0,
    }


def _cost_bps_for_market(market: str, ks_side_bps: float, kq_side_bps: float) -> float:
    return ks_side_bps if str(market).strip().upper() == "KS" else kq_side_bps


def _build_trade_rows(reports: pd.DataFrame, price: pd.DataFrame, horizons: list[int], ks_side_bps: float, kq_side_bps: float) -> pd.DataFrame:
    grouped_price = {ticker: frame.reset_index(drop=True) for ticker, frame in price.groupby("ticker", sort=False)}
    rows: list[dict[str, object]] = []

    for _, row in reports.iterrows():
        ticker = str(row.get("醫낅ぉ肄붾뱶", "") or "").zfill(6)
        if not ticker or ticker not in grouped_price:
            continue
        group = grouped_price[ticker]
        report_date = pd.to_datetime(str(row.get("report_date", "")), errors="coerce")
        if pd.isna(report_date):
            continue

        base = _forward_return(group, report_date, 1)
        if base is None:
            continue

        combined_action = str(row.get("寃고빀?≪뀡", "") or "").strip()
        signal_score = pd.to_numeric(row.get("醫낇빀?먯닔", np.nan), errors="coerce")
        signal_weight = pd.to_numeric(row.get("沅뚯옣鍮꾩쨷(%)", np.nan), errors="coerce")
        market = str(row.get("?쒖옣", "") or "").strip()
        cost_bps = _cost_bps_for_market(market, ks_side_bps, kq_side_bps)
        is_signal = combined_action != "?쒖쇅"

        for horizon_days in horizons:
            horizon_result = _forward_return(group, report_date, horizon_days)
            if horizon_result is None:
                continue
            roundtrip_cost_pct = (cost_bps * 2.0) / 100.0
            net_return_pct = horizon_result["gross_return_pct"] - roundtrip_cost_pct
            rows.append(
                {
                    "report_date": report_date.strftime("%Y-%m-%d"),
                    "ticker": ticker,
                    "name": str(row.get("醫낅ぉ紐?, "") or "").strip(),
                    "market": market,
                    "combined_action": combined_action,
                    "signal_score": float(signal_score) if pd.notna(signal_score) else np.nan,
                    "signal_weight_pct": float(signal_weight) if pd.notna(signal_weight) else np.nan,
                    "forward_horizon_days": int(horizon_days),
                    "current_trade_date": horizon_result["current_trade_date"],
                    "current_close": horizon_result["current_close"],
                    "future_close": horizon_result["future_close"],
                    "gross_return_pct": horizon_result["gross_return_pct"],
                    "net_return_pct": net_return_pct,
                    "cost_bps": cost_bps,
                    "is_signal": int(is_signal),
                }
            )

    if not rows:
        raise RuntimeError("No backtest rows could be constructed from the available reports and price history")
    return pd.DataFrame(rows)


def _summary_rows(trades: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    def summarize(group: pd.DataFrame, scope: str, group_value: str) -> dict[str, object]:
        return {
            "scope": scope,
            "group_value": group_value,
            "trade_count": int(len(group)),
            "avg_gross_return_pct": float(group["gross_return_pct"].mean()),
            "avg_net_return_pct": float(group["net_return_pct"].mean()),
            "win_rate_pct": float((group["net_return_pct"] > 0).mean() * 100.0),
            "median_net_return_pct": float(group["net_return_pct"].median()),
            "avg_score": float(group["signal_score"].mean()),
            "avg_weight_pct": float(group["signal_weight_pct"].mean()),
        }

    frames.append(pd.DataFrame([summarize(trades, "overall", "ALL")]))
    frames.append(
        pd.DataFrame(
            [summarize(group, "action", str(name)) for name, group in trades.groupby("combined_action", dropna=False)]
        )
    )
    frames.append(
        pd.DataFrame(
            [summarize(group, "report_date", str(name)) for name, group in trades.groupby("report_date", dropna=False)]
        )
    )
    return pd.concat(frames, ignore_index=True)


def _threshold_grid(trades: pd.DataFrame, thresholds: list[int]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    signal_rows = trades.loc[trades["is_signal"] == 1].copy()
    for horizon_days, horizon_group in signal_rows.groupby("forward_horizon_days", dropna=False):
        for threshold in thresholds:
            selected = horizon_group.loc[horizon_group["signal_score"] >= threshold]
            if selected.empty:
                rows.append(
                    {
                        "forward_horizon_days": int(horizon_days),
                        "score_threshold": int(threshold),
                        "selected_count": 0,
                        "avg_net_return_pct": np.nan,
                        "win_rate_pct": np.nan,
                        "avg_score": np.nan,
                        "avg_weight_pct": np.nan,
                    }
                )
                continue
            rows.append(
                {
                    "forward_horizon_days": int(horizon_days),
                    "score_threshold": int(threshold),
                    "selected_count": int(len(selected)),
                    "avg_net_return_pct": float(selected["net_return_pct"].mean()),
                    "win_rate_pct": float((selected["net_return_pct"] > 0).mean() * 100.0),
                    "avg_score": float(selected["signal_score"].mean()),
                    "avg_weight_pct": float(selected["signal_weight_pct"].mean()),
                }
            )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run walk-forward backtest on daily report snapshots")
    parser.add_argument("--horizons", default="1,2,3", help="Comma-separated forward holding periods in trading days")
    parser.add_argument("--thresholds", default="50,55,60,65,70,75,80,85,90", help="Comma-separated score thresholds")
    parser.add_argument("--ks-side-bps", type=float, default=15.0, help="Roundtrip side cost basis points for KS")
    parser.add_argument("--kq-side-bps", type=float, default=20.0, help="Roundtrip side cost basis points for KQ")
    parser.add_argument("--output-prefix", type=str, default="", help="Optional output prefix override")
    args = parser.parse_args()

    horizons = _parse_csv_list(args.horizons, [5, 20])
    thresholds = _parse_csv_list(args.thresholds, [50, 55, 60, 65, 70, 75, 80, 85, 90])

    reports = _load_reports()
    price = _load_price_history()
    trades = _build_trade_rows(reports, price, horizons, args.ks_side_bps, args.kq_side_bps)
    summary = _summary_rows(trades)
    threshold_grid = _threshold_grid(trades, thresholds)

    run_date = datetime.now().strftime("%Y-%m-%d")
    prefix = args.output_prefix.strip() or run_date
    summary_path = OUTPUT_DIR / f"backtest_summary_{prefix}.csv"
    trades_path = OUTPUT_DIR / f"backtest_trades_{prefix}.csv"
    grid_path = OUTPUT_DIR / f"threshold_grid_results_{prefix}.csv"

    _atomic_write_csv(summary, summary_path)
    _atomic_write_csv(trades, trades_path)
    _atomic_write_csv(threshold_grid, grid_path)

    print(f"[Backtest] Saved: {summary_path} ({len(summary)} rows)")
    print(f"[Backtest] Saved: {trades_path} ({len(trades)} rows)")
    print(f"[Backtest] Saved: {grid_path} ({len(threshold_grid)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

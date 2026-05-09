"""Score daily signals from feature data."""
from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.errors import EmptyDataError

import build_daily_report as report


BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "output"


def _latest_file(pattern: str) -> Path | None:
    candidates = [path for path in OUTPUT_DIR.glob(pattern) if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, keep_default_na=True)
    except EmptyDataError:
        return pd.DataFrame()


def _safe_write_csv(df: pd.DataFrame, path: Path) -> Path:
    tmp_path = path.with_name(f"{path.stem}.tmp{path.suffix}")
    try:
        df.to_csv(tmp_path, index=False, encoding="utf-8-sig")
        os.replace(tmp_path, path)
        return path
    except PermissionError:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        fallback = path.with_name(f"{path.stem}_locked_{datetime.now().strftime('%H%M%S')}{path.suffix}")
        fallback_tmp = fallback.with_name(f"{fallback.stem}.tmp{fallback.suffix}")
        df.to_csv(fallback_tmp, index=False, encoding="utf-8-sig")
        os.replace(fallback_tmp, fallback)
        return fallback


def _load_inputs(input_path: str | None = None) -> pd.DataFrame:
    if input_path:
        path = Path(input_path)
    else:
        path = _latest_file("feature_daily_*.csv")
        if path is None:
            raise FileNotFoundError(f"Missing feature file in {OUTPUT_DIR}")
    if not path.exists():
        raise FileNotFoundError(f"Missing feature file: {path}")
    return _read_csv(path)


def _load_assumptions() -> pd.DataFrame:
    if not report.ASSUMPTIONS_PATH.exists():
        return pd.DataFrame({"ticker": []})
    assumptions = _read_csv(report.ASSUMPTIONS_PATH)
    assumptions["ticker"] = assumptions["ticker"].astype(str).str.zfill(6)
    return assumptions


def _row_assumption(assumptions: pd.DataFrame, ticker: str) -> pd.Series:
    match = assumptions.loc[assumptions["ticker"].astype(str).str.zfill(6) == ticker]
    if match.empty:
        return pd.Series(report.DEFAULT_ASSUMPTION)
    return match.iloc[0]


def _to_float(value: object) -> float:
    return report.safe_float(value)


def _build_scored_frame(features: pd.DataFrame) -> pd.DataFrame:
    """Build scored frame with decision logic."""
    assumptions = _load_assumptions()
    today = datetime.now().strftime("%Y-%m-%d")

    rows: list[dict[str, object]] = []
    
    for _, src in features.iterrows():
        ticker = str(src.get("ticker", "") or "").zfill(6)
        assumption = _row_assumption(assumptions, ticker)

        # Extract values using English column names
        close = _to_float(src.get("close", np.nan))
        ma200 = _to_float(src.get("ma200", np.nan))
        above_ma200 = int(src.get("above_ma200", 0) or 0)
        breakout = int(src.get("breakout_20d_high", 0) or 0)
        volume_ratio = _to_float(src.get("volume_ratio_20d", np.nan))
        rsi14 = _to_float(src.get("rsi14", np.nan))
        macd_hist = _to_float(src.get("macd_hist", np.nan))

        trailing_eps_dart = _to_float(src.get("trailing_eps_dart", np.nan))
        consensus_eps_scrape = _to_float(src.get("consensus_eps_scrape", np.nan))
        forward_eps_auto = _to_float(src.get("forward_eps_auto", np.nan))
        expected_eps = _to_float(src.get("expected_eps", np.nan))
        eps_source_used = str(src.get("eps_source_used", "") or "").strip()

        target_pe_base = _to_float(assumption.get("target_pe_base", 12.0))
        max_position_pct = _to_float(assumption.get("max_position_pct", 3.0))
        if not np.isfinite(max_position_pct) or max_position_pct <= 0:
            max_position_pct = 3.0

        fair_price_base = expected_eps * target_pe_base if (not np.isnan(expected_eps) and close > 0) else np.nan
        upside_base_pct = ((fair_price_base / close) - 1.0) * 100.0 if (not np.isnan(fair_price_base) and close > 0) else np.nan

        # Get valuation and technical scores from features
        valuation_score = _to_float(src.get("valuation_score", np.nan))
        technical_score = _to_float(src.get("technical_score", np.nan))
        
        # Calculate total score
        total_score = technical_score if np.isnan(valuation_score) else (0.5 * valuation_score + 0.5 * technical_score if not np.isnan(technical_score) else valuation_score)

        # Decision logic
        has_eps = not np.isnan(expected_eps)
        if has_eps and total_score >= 75 and above_ma200 == 1 and breakout == 1:
            combined_action = "추천_매수진입"
        elif has_eps and total_score >= 65 and above_ma200 == 1:
            combined_action = "진입_관심"
        elif has_eps and total_score >= 50:
            combined_action = "관심종목"
        elif not has_eps:
            combined_action = "관심종목"
        else:
            combined_action = "제외"

        suggested_weight_pct = report.calc_weight(total_score, max_position_pct)
        if not has_eps or combined_action == "제외":
            suggested_weight_pct = 0.0

        regime_multiplier = _to_float(src.get("regime_weight_multiplier", 1.0))
        if not np.isfinite(regime_multiplier) or regime_multiplier <= 0:
            regime_multiplier = 1.0
        suggested_weight_pct = float(suggested_weight_pct * regime_multiplier)

        brief_reason, warn_flags = report._compose_brief_reason_and_warn(src)
        if not brief_reason:
            brief_reason = "추천사유미확인"

        is_loss_making = int(_to_float(assumption.get("is_loss_making", 0)) or 0)
        if is_loss_making == 0 and ((not np.isnan(expected_eps) and expected_eps < 0) or (not np.isnan(trailing_eps_dart) and trailing_eps_dart < 0)):
            is_loss_making = 1

        rows.append({
            "date": today,
            "name": str(src.get("name", "") or "").strip(),
            "ticker": ticker,
            "market": str(src.get("market", "") or "").strip(),
            "sector_group": str(src.get("sector_group", assumption.get("sector_group", "기타")) or "기타"),
            "close": close,
            "ma200": ma200,
            "above_ma200": above_ma200,
            "rsi14": rsi14,
            "macd_hist": macd_hist,
            "volume_ratio_20d": volume_ratio,
            "breakout_20d_high": breakout,
            "trailing_eps_dart": trailing_eps_dart,
            "consensus_eps_scrape": consensus_eps_scrape,
            "forward_eps_auto": forward_eps_auto,
            "eps_source_used": eps_source_used,
            "expected_eps": expected_eps,
            "fair_price_base": fair_price_base,
            "upside_base_pct": upside_base_pct,
            "valuation_score": valuation_score,
            "technical_score": technical_score,
            "total_score": total_score,
            "is_loss_making": is_loss_making,
            "max_position_pct": max_position_pct,
            "combined_action": combined_action,
            "suggested_weight_pct": suggested_weight_pct,
            "market_regime": str(src.get("market_regime", "NEUTRAL") or "NEUTRAL"),
            "regime_weight_multiplier": regime_multiplier,
            "brief_reason": brief_reason,
            "warn_flags": warn_flags,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("No rows produced from feature input.")

    # Sort by total score
    df = df.sort_values(by=["total_score", "technical_score", "upside_base_pct"], ascending=False).reset_index(drop=True)
    df.insert(0, "suggested_rank", np.arange(1, len(df) + 1))
    df.insert(1, "combined_rank", np.arange(1, len(df) + 1))

    return df


def _build_core_selection(df: pd.DataFrame) -> pd.DataFrame:
    """Build core selection subset."""
    selected = df[df["combined_action"].isin(["추천_매수진입", "진입_관심"])].copy()
    
    if selected.empty:
        selected = df.sort_values(by=["total_score", "technical_score", "upside_base_pct"], ascending=False).head(10).copy()
        if selected.empty:
            return pd.DataFrame(columns=["date", "suggested_rank", "name", "ticker", "market", "combined_action", "brief_reason", "total_score"])

    selected = selected.sort_values(by=["suggested_rank", "total_score"], ascending=[True, False]).reset_index(drop=True)
    
    cols = [
        "date",
        "suggested_rank",
        "name",
        "ticker",
        "market",
        "combined_action",
        "brief_reason",
        "volume_ratio_20d",
        "breakout_20d_high",
        "above_ma200",
        "rsi14",
        "total_score",
        "warn_flags",
    ]
    available_cols = [c for c in cols if c in selected.columns]
    return selected[available_cols].copy()


def main() -> int:
    parser = argparse.ArgumentParser(description="Score daily signals from the feature table")
    parser.add_argument("--input", type=str, default="", help="Optional input feature CSV path")
    parser.add_argument("--output", type=str, default="", help="Optional explicit detailed report path")
    parser.add_argument("--core-output", type=str, default="", help="Optional explicit core selection path")
    args = parser.parse_args()

    features = _load_inputs(args.input or None)
    scored = _build_scored_frame(features)

    # Determine output paths
    today = datetime.now().strftime("%Y-%m-%d")
    report_path = Path(args.output) if args.output else OUTPUT_DIR / f"scored_report_{today}.csv"
    core_path = Path(args.core_output) if args.core_output else OUTPUT_DIR / f"core_selection_{today}.csv"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    # Save scored report with bilingual headers
    report_df = scored.copy()
    report_ko = report_df.copy()
    report_ko.columns = report.make_bilingual_headers(list(report_ko.columns))
    report_path = _safe_write_csv(report_ko, report_path)

    # Save core selection with bilingual headers
    core_df = _build_core_selection(scored)
    core_ko = core_df.copy()
    core_ko.columns = report.make_bilingual_headers(list(core_ko.columns))
    core_path = _safe_write_csv(core_ko, core_path)

    print(f"[Score] Saved: {report_path} ({len(report_ko)} rows)")
    print(f"[Score] Saved: {core_path} ({len(core_ko)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

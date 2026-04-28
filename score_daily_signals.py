from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import build_daily_report as report


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"


def _latest_file(pattern: str) -> Path | None:
    candidates = [path for path in OUTPUT_DIR.glob(pattern) if path.is_file() and "_locked_" not in path.name]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _load_inputs(input_path: str | None = None) -> pd.DataFrame:
    if input_path:
        path = Path(input_path)
    else:
        path = _latest_file("기본피처_*.csv")
        if path is None:
            raise FileNotFoundError(f"Missing feature file in {OUTPUT_DIR}")
    if not path.exists():
        raise FileNotFoundError(f"Missing feature file: {path}")
    return pd.read_csv(path, dtype={"종목코드": str, "ticker": str}, keep_default_na=True)


def _load_assumptions() -> pd.DataFrame:
    if not report.ASSUMPTIONS_PATH.exists():
        return pd.DataFrame({"ticker": []})
    assumptions = pd.read_csv(report.ASSUMPTIONS_PATH, dtype={"ticker": str}, keep_default_na=True)
    assumptions["ticker"] = assumptions["ticker"].astype(str).str.zfill(6)
    return assumptions


def _row_assumption(assumptions: pd.DataFrame, ticker: str) -> pd.Series:
    match = assumptions.loc[assumptions["ticker"].astype(str).str.zfill(6) == ticker]
    if match.empty:
        return pd.Series(report.DEFAULT_ASSUMPTION)
    return match.iloc[0]


def _to_float(value: object) -> float:
    return report.safe_float(value)


def _safe_write_csv(df: pd.DataFrame, path: Path) -> Path:
    try:
        df.to_csv(path, index=False, encoding="utf-8-sig")
        return path
    except PermissionError:
        fallback = path.with_name(f"{path.stem}_locked_{datetime.now().strftime('%H%M%S')}{path.suffix}")
        df.to_csv(fallback, index=False, encoding="utf-8-sig")
        return fallback


def _compose_score_reason(row: pd.Series) -> tuple[str, str]:
    reasons: list[str] = []
    warns: list[str] = []

    upside = _to_float(row.get("상승여력(%)", np.nan))
    if not np.isnan(upside) and upside >= 10:
        reasons.append(f"상승여력 {upside:.0f}%")

    close = _to_float(row.get("종가", np.nan))
    ma200 = _to_float(row.get("200일이평", np.nan))
    if close > 0 and ma200 > 0 and close > ma200:
        reasons.append("200일↑")

    breakout = int(_to_float(row.get("20일돌파", 0)) or 0)
    if breakout == 1:
        reasons.append("20일돌파")

    vol_ratio = _to_float(row.get("거래량비율20일", np.nan))
    if not np.isnan(vol_ratio) and vol_ratio >= 1.5:
        reasons.append(f"거래량x{vol_ratio:.1f}")

    rsi = _to_float(row.get("RSI14", np.nan))
    if not np.isnan(rsi) and 45 <= rsi <= 70:
        reasons.append("RSI우호")

    macd_hist = _to_float(row.get("MACD히스토그램", np.nan))
    if not np.isnan(macd_hist) and macd_hist > 0:
        reasons.append("MACD+")

    if str(row.get("원본EPS출처", "") or "").strip() and str(row.get("원본EPS출처", "")).strip() != "DART":
        warns.append("EPS스크랩")

    if str(row.get("EPS소스", "")).strip() == "GROWTH_AUTO":
        warns.append("성장률추정")

    if str(row.get("마켓레짐", "")).strip() == "BEAR":
        warns.append("하락장비중축소")

    if pd.isna(_to_float(row.get("모델EPS", np.nan))):
        warns.append("EPS없음")
        reasons.append("비밸류평가")

    is_loss = int(_to_float(row.get("적자여부", 0)) or 0)
    if is_loss == 1:
        warns.append("적자")

    return " | ".join(reasons[:6]), ",".join(warns)


def _selection_opinion(total_score: float, action: str, risk: float) -> str:
    if total_score >= 62 and action != "제외" and risk <= 12:
        return "우선검토"
    if total_score >= 50 and action in {"최종매수후보", "진입대기", "관찰"}:
        return "관찰후진입"
    return "관망"


def _judgement_comment(action: str, score: float, risk: float) -> str:
    if action == "최종매수후보":
        return "점수와 추세가 양호합니다. 분할 접근을 고려할 수 있습니다."
    if action == "진입대기":
        return "추세는 양호하지만 확인이 더 필요합니다."
    if action == "관찰":
        if risk <= 12:
            return "신호는 있으나 추가 확인이 필요합니다."
        return "리스크가 높아 비중을 낮게 유지하는 편이 좋습니다."
    return "현재 강한 매수 신호는 없습니다. 관망이 적절합니다."


def _build_scored_frame(features: pd.DataFrame) -> pd.DataFrame:
    assumptions = _load_assumptions()
    today = datetime.now().strftime("%Y-%m-%d")

    rows: list[dict[str, object]] = []
    for _, src in features.iterrows():
        ticker = str(src.get("종목코드", src.get("ticker", "")) or "").zfill(6)
        assumption = _row_assumption(assumptions, ticker)

        close = _to_float(src.get("종가", np.nan))
        ma20 = _to_float(src.get("20일이평", np.nan))
        ma60 = _to_float(src.get("60일이평", np.nan))
        ma120 = _to_float(src.get("120일이평", np.nan))
        ma200 = _to_float(src.get("200일이평", np.nan))
        rsi14 = _to_float(src.get("RSI14", np.nan))
        macd_hist = _to_float(src.get("MACD히스토그램", np.nan))
        volume_ratio = _to_float(src.get("거래량비율20일", np.nan))
        breakout = int(_to_float(src.get("20일돌파", 0)) or 0)
        return_5d = _to_float(src.get("5일수익률(%)", np.nan))
        return_20d = _to_float(src.get("20일수익률(%)", np.nan))

        trailing_eps_dart = _to_float(src.get("후행EPS(DART)", np.nan))
        consensus_eps_scrape = _to_float(src.get("컨센서스EPS(스크랩)", np.nan))
        forward_eps_auto = _to_float(src.get("자동선행EPS", np.nan))
        source_primary = str(src.get("원본EPS출처", "") or "").strip()
        eps_source_used = str(src.get("EPS소스", "") or "").strip()

        manual_forward_eps = _to_float(assumption.get("manual_forward_eps", np.nan))
        expected_eps = _to_float(src.get("모델EPS", np.nan))
        if np.isnan(expected_eps):
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
            growth_pct = _to_float(assumption.get("eps_growth_3y_pct", 10.0))
            growth = growth_pct / 100.0 if not np.isnan(growth_pct) else 0.10
            growth = float(np.clip(growth, -0.5, 0.8))
            expected_eps = trailing_eps_dart * (1.0 + growth)
            eps_source_used = "GROWTH_AUTO"

        target_pe_base = _to_float(assumption.get("target_pe_base", 12.0))
        max_position_pct = _to_float(assumption.get("max_position_pct", 3.0))
        if not np.isfinite(max_position_pct) or max_position_pct <= 0:
            max_position_pct = 3.0

        fair_price_base = expected_eps * target_pe_base if (not np.isnan(expected_eps) and close > 0) else np.nan
        upside_base_pct = ((fair_price_base / close) - 1.0) * 100.0 if (not np.isnan(fair_price_base) and close > 0) else np.nan
        valuation_score = report.calc_valuation_score(upside_base_pct)

        score_row = pd.Series(
            {
                "close": close,
                "ma20": ma20,
                "ma60": ma60,
                "ma200": ma200,
                "rsi14": rsi14,
                "macd_hist": macd_hist,
                "volume_ratio_20d": volume_ratio,
                "breakout_20d_high": breakout,
            }
        )
        technical_score = report.calc_technical_score(score_row)
        total_score = float(technical_score) if np.isnan(valuation_score) else float(0.5 * valuation_score + 0.5 * technical_score)

        has_eps = not np.isnan(expected_eps)
        above_ma200 = 1 if (close > 0 and ma200 > 0 and close > ma200) else 0
        if has_eps and total_score >= 75 and above_ma200 == 1 and breakout == 1:
            combined_action = "최종매수후보"
        elif has_eps and total_score >= 65 and above_ma200 == 1:
            combined_action = "진입대기"
        elif has_eps and total_score >= 50:
            combined_action = "관찰"
        elif not has_eps:
            combined_action = "관찰"
        else:
            combined_action = "제외"

        suggested_weight_pct = report.calc_weight(total_score, max_position_pct)
        if not has_eps or combined_action == "제외":
            suggested_weight_pct = 0.0

        regime_multiplier = _to_float(src.get("레짐비중배수", 1.0))
        if not np.isfinite(regime_multiplier) or regime_multiplier <= 0:
            regime_multiplier = 1.0
        suggested_weight_pct = float(suggested_weight_pct * regime_multiplier)

        brief_reason, warn_flags = _compose_score_reason(src)
        if not brief_reason:
            brief_reason = "추세/밸류 확인"

        is_loss_making = int(_to_float(assumption.get("is_loss_making", 0)) or 0)
        if is_loss_making == 0 and ((not np.isnan(expected_eps) and expected_eps < 0) or (trailing_eps_dart < 0)):
            is_loss_making = 1

        rows.append(
            {
                "기준일": today,
                "종목명": str(src.get("종목명", "") or "").strip(),
                "종목코드": ticker,
                "시장": str(src.get("시장", "") or "").strip(),
                "섹터그룹": str(src.get("섹터그룹", assumption.get("sector_group", "기타")) or "기타"),
                "종가": close,
                "20일이평": ma20,
                "60일이평": ma60,
                "120일이평": ma120,
                "200일이평": ma200,
                "200일선상단여부": above_ma200,
                "RSI14": rsi14,
                "MACD히스토그램": macd_hist,
                "거래량비율20일": volume_ratio,
                "20일돌파": breakout,
                "5일수익률(%)": return_5d,
                "20일수익률(%)": return_20d,
                "후행EPS(DART)": trailing_eps_dart,
                "컨센서스EPS(스크랩)": consensus_eps_scrape,
                "자동선행EPS": forward_eps_auto,
                "원본EPS출처": source_primary,
                "EPS소스": eps_source_used,
                "수동선행EPS": manual_forward_eps,
                "모델EPS": expected_eps,
                "현재PER": _to_float(src.get("현재PER", np.nan)),
                "적정주가_기준": fair_price_base,
                "상승여력(%)": upside_base_pct,
                "밸류점수": valuation_score,
                "적자여부": is_loss_making,
                "최대비중(%)": max_position_pct,
                "기술점수": technical_score,
                "종합점수": total_score,
                "결합액션": combined_action,
                "권장비중(%)": suggested_weight_pct,
                "마켓레짐": str(src.get("market_regime", src.get("시장상태", "NEUTRAL")) or "NEUTRAL"),
                "레짐비중배수": regime_multiplier,
                "섹터PER상한": np.nan,
                "핵심요약": brief_reason,
                "주의표시": warn_flags,
                "volume_ratio_pct_rank": np.nan,
                "선정의견": _selection_opinion(total_score, combined_action, 12.0 if not np.isnan(volume_ratio) else 99.0),
                "판단코멘트": _judgement_comment(combined_action, total_score, 12.0 if not np.isnan(volume_ratio) else 99.0),
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("No rows produced from feature input.")

    df["sector_pe_cap"] = df.groupby("섹터그룹")["현재PER"].transform(report._safe_nanmedian)
    df["sector_pe_cap"] = pd.to_numeric(df["sector_pe_cap"], errors="coerce").clip(lower=5.0, upper=30.0)
    use_cap = df["EPS소스"].isin(["FORWARD_AUTO", "GROWTH_AUTO"])
    eff_pe = np.where(use_cap, np.minimum(df["sector_pe_cap"], 25.0), np.nan)
    cap_price = pd.to_numeric(df["모델EPS"], errors="coerce") * pd.to_numeric(eff_pe, errors="coerce")
    cap_upside = ((cap_price / pd.to_numeric(df["종가"], errors="coerce")) - 1.0) * 100.0
    overwrite_mask = use_cap & cap_price.notna()
    df.loc[overwrite_mask, "적정주가_기준"] = cap_price[overwrite_mask]
    df.loc[overwrite_mask, "상승여력(%)"] = cap_upside[overwrite_mask]
    df.loc[overwrite_mask, "밸류점수"] = df.loc[overwrite_mask, "상승여력(%)"].apply(report.calc_valuation_score)

    df["종합점수"] = np.where(
        pd.to_numeric(df["밸류점수"], errors="coerce").isna(),
        pd.to_numeric(df["기술점수"], errors="coerce"),
        0.5 * pd.to_numeric(df["밸류점수"], errors="coerce") + 0.5 * pd.to_numeric(df["기술점수"], errors="coerce"),
    )
    df = df.sort_values(by=["종합점수", "기술점수", "상승여력(%)"], ascending=False).reset_index(drop=True)
    df.insert(0, "추천순위", np.arange(1, len(df) + 1))
    df.insert(1, "결합순위", np.arange(1, len(df) + 1))

    reasons = df.apply(lambda r: pd.Series(report._compose_brief_reason_and_warn(r), index=["핵심요약", "주의표시"]), axis=1)
    df["핵심요약"] = reasons["핵심요약"]
    df["주의표시"] = reasons["주의표시"]

    df["volume_ratio_pct_rank"] = pd.to_numeric(df["거래량비율20일"], errors="coerce").rank(pct=True) * 100.0
    df = df.drop(columns=["sector_pe_cap"], errors="ignore")
    return df


def _build_core_selection(df: pd.DataFrame) -> pd.DataFrame:
    selected = df[df["결합액션"].isin(["최종매수후보", "진입대기"])].copy()
    if selected.empty:
        selected = df.sort_values(by=["종합점수", "기술점수", "상승여력(%)"], ascending=False).head(10).copy()
        if selected.empty:
            return pd.DataFrame(columns=["기준일", "추천순위", "종목명", "종목코드", "시장", "선정의견", "선정핵심근거", "판단코멘트"])

    selected = selected.sort_values(by=["추천순위", "종합점수"], ascending=[True, False]).reset_index(drop=True)
    selected["선정의견"] = selected.apply(lambda row: _selection_opinion(_to_float(row.get("종합점수", np.nan)), str(row.get("결합액션", "")), 12.0), axis=1)
    selected["선정핵심근거"] = selected["핵심요약"].replace("", "추세/밸류 확인")
    selected["판단코멘트"] = selected.apply(lambda row: _judgement_comment(str(row.get("결합액션", "")), _to_float(row.get("종합점수", np.nan)), 12.0), axis=1)

    cols = [
        "기준일",
        "추천순위",
        "종목명",
        "종목코드",
        "시장",
        "선정의견",
        "선정핵심근거",
        "결합액션",
        "거래량비율20일",
        "20일돌파",
        "200일선상단여부",
        "RSI14",
        "종합점수",
        "판단코멘트",
    ]
    return selected[cols].copy()


def main() -> int:
    parser = argparse.ArgumentParser(description="Score daily signals from the feature table")
    parser.add_argument("--input", type=str, default="", help="Optional input feature CSV path")
    parser.add_argument("--output", type=str, default="", help="Optional explicit detailed report path")
    parser.add_argument("--core-output", type=str, default="", help="Optional explicit core selection path")
    args = parser.parse_args()

    features = _load_inputs(args.input or None)
    scored = _build_scored_frame(features)

    report_path = Path(args.output) if args.output else OUTPUT_DIR / f"상세리포트_{datetime.now().strftime('%Y-%m-%d')}.csv"
    core_path = Path(args.core_output) if args.core_output else OUTPUT_DIR / f"종목선정_핵심근거_{datetime.now().strftime('%Y-%m-%d')}.csv"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report_df = scored.copy()
    report_ko = report_df.copy()
    report_ko.columns = report.make_bilingual_headers(list(report_ko.columns))
    report_path = _safe_write_csv(report_ko, report_path)

    core_df = _build_core_selection(scored)
    core_ko = core_df.copy()
    core_ko.columns = report.make_bilingual_headers(list(core_ko.columns))
    core_path = _safe_write_csv(core_ko, core_path)

    print(f"[Score] Saved: {report_path} ({len(report_ko)} rows)")
    print(f"[Score] Saved: {core_path} ({len(core_ko)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
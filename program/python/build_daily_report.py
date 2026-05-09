"""
Utility module for daily valuation report generation.
Contains shared constants, helper functions, and scoring logic.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ============================================================
# PATHS & CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[2]
UNIVERSE_PATH = BASE_DIR / "universe.csv"
ASSUMPTIONS_PATH = BASE_DIR / "assumptions.csv"
EPS_CACHE_PATH = BASE_DIR / "eps_cache.csv"
OUTPUT_DIR = BASE_DIR / "output"


DEFAULT_ASSUMPTION = {
    "is_loss_making": 0,
    "eps_growth_3y_pct": 10.0,
    "target_pe_bear": 8.0,
    "target_pe_base": 12.0,
    "target_pe_bull": 16.0,
    "manual_forward_eps": np.nan,
    "max_position_pct": 3.0,
    "sector_group": "기타",
}


# English-Korean mapping for bilingual output
COLUMN_KO_MAP: dict[str, tuple[str, str]] = {
    "date": ("날짜", "리포트 작성 기준일"),
    "suggested_rank": ("추천순위", "최신 신호 기준 순위"),
    "combined_rank": ("결합순위", "기본값과 결합 신호 순위"),
    "name": ("종목명", "회사명"),
    "ticker": ("종목코드", "6자리 종목코드"),
    "market": ("시장", "KS(코스피)/KQ(코스닥)"),
    "sector_group": ("섹터그룹", "분류/섹터 그룹"),
    "close": ("종가", "최근 종가"),
    "ma20": ("20일이평", "20일 이동평균"),
    "ma60": ("60일이평", "60일 이동평균"),
    "ma120": ("120일이평", "120일 이동평균"),
    "ma200": ("200일이평", "200일 이동평균"),
    "above_ma200": ("200일선상단여부", "종가가 200일선 상단 1"),
    "rsi14": ("RSI14", "14일 RSI"),
    "macd_hist": ("MACD히스토그램", "MACD-신호선"),
    "volume_ratio_20d": ("거래량비율20일", "최근 거래량 / 20일평균"),
    "breakout_20d_high": ("20일돌파", "20일 고점 돌파 여부"),
    "return_5d": ("5일수익률(%)", "최근 5일 수익률"),
    "return_20d": ("20일수익률(%)", "최근 20일 수익률"),
    "relative_strength_20d": ("상대강도20일", "종목-지수 20일 상대강도"),
    "trailing_eps_dart": ("최근EPS(DART)", "DART 기준 EPS (캐시)"),
    "consensus_eps_scrape": ("컨센서스EPS(스크래)", "스크래핑된 기준/컨센서스 EPS"),
    "forward_eps_auto": ("향후예상EPS", "장기추세 기준 향후 예상 EPS"),
    "source_primary": ("선택EPS출처", "캐시 우선 출처"),
    "eps_source_used": ("EPS출처", "최신 EPS 출처"),
    "manual_forward_eps": ("수동예상EPS", "사용자 수동 입력 EPS"),
    "expected_eps": ("모델EPS", "발휘 계산에 사용 EPS"),
    "pe_now": ("현재PER", "현재가 / EPS"),
    "fair_price_base": ("정정가_기본", "expected_eps * target_pe_base"),
    "upside_base_pct": ("상승잠재(%)", "(fair_price_base/close-1)*100"),
    "valuation_score": ("발휘지수", "상승잠재 기준 0~100 지수"),
    "technical_score": ("기술지수", "기술 지표 기준 0~100 지수"),
    "total_score": ("종합지수", "발휘+기술 결합 지수"),
    "is_loss_making": ("적자여부", "최근 영업 기준 적자 여부(1=적자)"),
    "max_position_pct": ("최대비중(%)", "종목별 최대 사용 비중"),
    "combined_action": ("결합액션", "최신신호/진입-매도 조정/제외"),
    "suggested_weight_pct": ("포트비중(%)", "최신 지수 기준 비중(%)"),
    "market_regime": ("마켓레짐", "지표 상태(BULL/NEUTRAL/BEAR)"),
    "regime_weight_multiplier": ("레짐비중배수", "수정된 비중 배수 계산 배수"),
    "sector_pe_cap": ("섹터PER상한", "섹터 기준 PER 상한값"),
    "brief_reason": ("투자사유약", "요약 추천 이유"),
    "warn_flags": ("주의사항", "주의 플래그"),
}


# ============================================================
# BASIC UTILITIES
# ============================================================

def safe_float(v: object) -> float:
    """Safely convert value to float, returns NaN on failure."""
    try:
        if v is None:
            return np.nan
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def _zfill6(v: object) -> str:
    """Pad value to 6-digit string."""
    return str(v or "").strip().zfill(6)


def is_excluded_instrument(name: str) -> bool:
    """Check if instrument should be excluded (e.g., ETF, REIT)."""
    if not isinstance(name, str):
        return False
    name_upper = name.upper()
    excluded_keywords = ["REIT", "ETF", "펀드"]
    return any(kw in name_upper for kw in excluded_keywords)


def _safe_nanmedian(series: pd.Series) -> float:
    """Calculate median ignoring NaN values."""
    valid = pd.to_numeric(series, errors="coerce").dropna()
    if valid.empty:
        return np.nan
    return float(valid.median())


# ============================================================
# TECHNICAL INDICATOR FUNCTIONS
# ============================================================

def calc_rsi(close_series: pd.Series, period: int = 14) -> float:
    """Calculate RSI (Relative Strength Index)."""
    if close_series.empty or len(close_series) < period + 1:
        return np.nan
    
    close_series = pd.to_numeric(close_series, errors="coerce").dropna()
    if len(close_series) < period + 1:
        return np.nan
    
    delta = close_series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    return float(rsi.iloc[-1]) if not rsi.empty else np.nan


def calc_macd_hist(close_series: pd.Series) -> float:
    """Calculate MACD histogram (MACD line - Signal line)."""
    if close_series.empty or len(close_series) < 26:
        return np.nan
    
    close_series = pd.to_numeric(close_series, errors="coerce").dropna()
    if len(close_series) < 26:
        return np.nan
    
    ema12 = close_series.ewm(span=12, adjust=False).mean()
    ema26 = close_series.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - signal_line
    
    return float(macd_hist.iloc[-1]) if not macd_hist.empty else np.nan


def calc_volume_ratio(volume_series: pd.Series | dict | None) -> float:
    """Calculate 20-day volume ratio."""
    if volume_series is None:
        return np.nan
    
    if isinstance(volume_series, dict):
        volume_series = pd.Series(volume_series)
    
    volume_series = pd.to_numeric(volume_series, errors="coerce").dropna()
    if len(volume_series) < 20:
        return np.nan
    
    recent_volume = float(volume_series.iloc[-1])
    ma_volume = float(volume_series.tail(20).mean())
    
    if ma_volume <= 0:
        return np.nan
    
    return float(recent_volume / ma_volume)


def calc_breakout_20d_high(close_series: pd.Series) -> int:
    """Check if current close is at or above 20-day high."""
    close_series = pd.to_numeric(close_series, errors="coerce").dropna()
    if len(close_series) < 20:
        return 0
    
    recent_close = float(close_series.iloc[-1])
    high_20d = float(close_series.tail(20).max())
    
    return 1 if recent_close >= high_20d * 0.99 else 0


def calc_returns(close_series: pd.Series, periods: int) -> float:
    """Calculate returns over specified periods."""
    close_series = pd.to_numeric(close_series, errors="coerce").dropna()
    if len(close_series) < periods + 1:
        return np.nan
    
    current = float(close_series.iloc[-1])
    past = float(close_series.iloc[-(periods + 1)])
    
    if past <= 0:
        return np.nan
    
    return float((current / past - 1.0) * 100.0)


# ============================================================
# SCORING FUNCTIONS
# ============================================================

def calc_valuation_score(upside_pct: float) -> float:
    """Convert upside percentage to 0-100 valuation score."""
    upside = safe_float(upside_pct)
    if np.isnan(upside):
        return np.nan
    
    # Scale: -20% -> 0, 0% -> 50, 20% -> 100
    if upside <= -20:
        return 0.0
    elif upside >= 20:
        return 100.0
    else:
        return float(50.0 + (upside / 0.4))


def calc_technical_score(score_row: pd.Series) -> float:
    """Calculate technical score from indicator values."""
    close = safe_float(score_row.get("close", np.nan))
    ma20 = safe_float(score_row.get("ma20", np.nan))
    ma60 = safe_float(score_row.get("ma60", np.nan))
    ma120 = safe_float(score_row.get("ma120", np.nan))
    ma200 = safe_float(score_row.get("ma200", np.nan))
    rsi14 = safe_float(score_row.get("rsi14", np.nan))
    macd_hist = safe_float(score_row.get("macd_hist", np.nan))
    volume_ratio_20d = safe_float(score_row.get("volume_ratio_20d", np.nan))
    breakout_20d_high = safe_float(score_row.get("breakout_20d_high", np.nan))
    
    score = 50.0  # Base score
    
    # Moving average positions
    if close > 0:
        if ma200 > 0 and close > ma200:
            score += 15.0
        if ma120 > 0 and close > ma120:
            score += 5.0
        if ma60 > 0 and close > ma60:
            score += 5.0
        if ma20 > 0 and close > ma20:
            score += 5.0
    
    # RSI
    if not np.isnan(rsi14):
        if 45 <= rsi14 <= 70:
            score += 10.0
    
    # MACD
    if not np.isnan(macd_hist):
        if macd_hist > 0:
            score += 10.0
    
    # Volume ratio
    if not np.isnan(volume_ratio_20d):
        if volume_ratio_20d >= 1.5:
            score += 10.0
        elif volume_ratio_20d >= 1.0:
            score += 5.0
    
    # Breakout
    if not np.isnan(breakout_20d_high):
        if breakout_20d_high == 1:
            score += 10.0
    
    return float(np.clip(score, 0.0, 100.0))


def calc_weight(total_score: float, max_position_pct: float) -> float:
    """Calculate portfolio weight from score."""
    total_score = safe_float(total_score)
    max_position_pct = safe_float(max_position_pct)
    
    if np.isnan(total_score) or np.isnan(max_position_pct):
        return 0.0
    
    if max_position_pct <= 0:
        max_position_pct = 3.0
    
    # Scale score to weight
    # 0-30: 0%, 30-50: 25% of max, 50-70: 50% of max, 70-100: 100% of max
    if total_score < 30:
        weight_factor = 0.0
    elif total_score < 50:
        weight_factor = (total_score - 30) / 20.0 * 0.25
    elif total_score < 70:
        weight_factor = 0.25 + (total_score - 50) / 20.0 * 0.25
    else:
        weight_factor = 0.5 + (min(total_score, 100) - 70) / 30.0 * 0.5
    
    return float(max_position_pct * weight_factor)


def calc_market_regime_and_multiplier(period: str = "6mo") -> tuple[str, float]:
    """Calculate market regime (simplified version - returns NEUTRAL/BULL by default)."""
    # Placeholder: actual implementation would analyze market indices
    # For now, return neutral regime with 1.0 multiplier
    return "NEUTRAL", 1.0


def _compose_brief_reason_and_warn(row: pd.Series) -> tuple[str, str]:
    """Compose brief investment reason and warning flags."""
    reasons: list[str] = []
    warns: list[str] = []
    
    upside = safe_float(row.get("upside_base_pct", np.nan))
    if not np.isnan(upside) and upside >= 10:
        reasons.append(f"상승잠재 {upside:.0f}%")
    
    close = safe_float(row.get("close", np.nan))
    ma200 = safe_float(row.get("ma200", np.nan))
    if close > 0 and ma200 > 0 and close > ma200:
        reasons.append("200일선상단")
    
    breakout = int(safe_float(row.get("breakout_20d_high", 0)) or 0)
    if breakout == 1:
        reasons.append("20일돌파")
    
    vol_ratio = safe_float(row.get("volume_ratio_20d", np.nan))
    if not np.isnan(vol_ratio) and vol_ratio >= 1.5:
        reasons.append(f"거래량상승{vol_ratio:.1f}x")
    
    rsi = safe_float(row.get("rsi14", np.nan))
    if not np.isnan(rsi) and 45 <= rsi <= 70:
        reasons.append("RSI신호")
    
    macd_hist = safe_float(row.get("macd_hist", np.nan))
    if not np.isnan(macd_hist) and macd_hist > 0:
        reasons.append("MACD+")
    
    eps_source = str(row.get("eps_source_used", "") or "").strip()
    if eps_source and eps_source != "DART":
        warns.append("EPS스크래핑")
    
    if eps_source == "GROWTH_AUTO":
        warns.append("장기추세예측")
    
    market_regime = str(row.get("market_regime", "NEUTRAL") or "NEUTRAL").strip()
    if market_regime == "BEAR":
        warns.append("약세레짐주의")
    
    expected_eps = safe_float(row.get("expected_eps", np.nan))
    if np.isnan(expected_eps):
        warns.append("EPS미확보")
        reasons.append("비교차부여")
    
    is_loss = int(safe_float(row.get("is_loss_making", 0)) or 0)
    if is_loss == 1:
        warns.append("적자")
    
    return " | ".join(reasons[:6]), ",".join(warns)


# ============================================================
# OUTPUT HELPERS
# ============================================================

def make_bilingual_headers(columns: list[str]) -> list[str]:
    """Convert English column names to Korean."""
    out: list[str] = []
    for c in columns:
        ko = COLUMN_KO_MAP.get(c, (c, ""))[0]
        out.append(ko)
    return out

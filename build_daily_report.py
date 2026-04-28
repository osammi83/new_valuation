from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import re
from typing import Optional

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


BASE_DIR = Path(__file__).resolve().parent
UNIVERSE_PATH = BASE_DIR / "universe.csv"
ASSUMPTIONS_PATH = BASE_DIR / "assumptions.csv"
EPS_CACHE_PATH = BASE_DIR / "eps_cache.csv"
OUTPUT_DIR = BASE_DIR / "output"
DOCS_DIR = BASE_DIR / "문서"
COLUMN_DICT_DOC_PATH = DOCS_DIR / "up_column_dictionary_ko.csv"

AUTO_BUILD_UNIVERSE = True
TOP_N_KOSPI = 400
TOP_N_KOSDAQ = 400

EXCLUDE_NAME_PAT = re.compile(r"(리츠|REIT)", re.IGNORECASE)


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


COLUMN_KO_MAP: dict[str, tuple[str, str]] = {
    "date": ("기준일", "리포트 생성 날짜"),
    "suggested_rank": ("추천순위", "최종 점수 기준 순위"),
    "combined_rank": ("결합순위", "기본면+기술 결합 기준 순위"),
    "name": ("종목명", "회사명"),
    "ticker": ("종목코드", "6자리 종목코드"),
    "market": ("시장", "KS(코스피)/KQ(코스닥)"),
    "sector_group": ("섹터그룹", "분석용 섹터 그룹"),
    "close": ("종가", "최근 종가"),
    "ma20": ("20일이평", "20일 이동평균"),
    "ma60": ("60일이평", "60일 이동평균"),
    "ma120": ("120일이평", "120일 이동평균"),
    "ma200": ("200일이평", "200일 이동평균"),
    "above_ma200": ("200일선상단여부", "종가가 200일선 위면 1"),
    "rsi14": ("RSI14", "14일 RSI"),
    "macd_hist": ("MACD히스토그램", "MACD-시그널"),
    "volume_ratio_20d": ("거래량비율20일", "최근 거래량 / 20일 평균"),
    "breakout_20d_high": ("20일돌파", "20일 신고가 돌파 여부"),
    "return_5d": ("5일수익률(%)", "최근 5거래일 수익률"),
    "return_20d": ("20일수익률(%)", "최근 20거래일 수익률"),
    "relative_strength_20d": ("상대강도20일", "종목-시장 20일 수익률"),
    "trailing_eps_dart": ("후행EPS(DART)", "DART 기반 EPS 프록시(캐시)"),
    "consensus_eps_scrape": ("컨센서스EPS(스크랩)", "스크래핑 기반 선행/컨센서스 EPS"),
    "forward_eps_auto": ("자동선행EPS", "성장률 기반 자동 산출 EPS"),
    "source_primary": ("원본EPS출처", "캐시 원천 데이터 출처"),
    "eps_source_used": ("EPS소스", "최종 EPS 선택 소스"),
    "manual_forward_eps": ("수동선행EPS", "사용자 수동 입력 EPS"),
    "expected_eps": ("모델EPS", "밸류 계산에 사용한 EPS"),
    "pe_now": ("현재PER", "현재가 / EPS"),
    "fair_price_base": ("적정주가_기준", "expected_eps * target_pe_base"),
    "upside_base_pct": ("상승여력(%)", "(fair_price_base/close-1)*100"),
    "valuation_score": ("밸류점수", "상승여력 기반 0~100 점수"),
    "technical_score": ("기술점수", "기술 지표 기반 0~100 점수"),
    "total_score": ("종합점수", "밸류+기술 결합 점수"),
    "is_loss_making": ("적자여부", "최근 손익 기준 적자 여부(1=적자)"),
    "max_position_pct": ("최대비중(%)", "종목별 최대 허용 비중"),
    "combined_action": ("결합액션", "최종매수후보/진입대기/관찰/제외"),
    "suggested_weight_pct": ("권장비중(%)", "최종 점수 기반 비중(%)"),
    "market_regime": ("마켓레짐", "시장 상태(BULL/NEUTRAL/BEAR)"),
    "regime_weight_multiplier": ("레짐비중배수", "하락장 비중 감산 배수"),
    "sector_pe_cap": ("섹터PER상한", "섹터 기반 PER 상한값"),
    "brief_reason": ("핵심요약", "한 줄 근거 요약"),
    "warn_flags": ("주의표시", "주의 플래그"),
}

KO_TO_EN_MAP: dict[str, str] = {v[0]: k for k, v in COLUMN_KO_MAP.items()}

REPORT_FILE_PREFIX = "상세리포트"
WATCH_FILE_PREFIX = "관심종목요약"
ENTRY_FILE_PREFIX = "진입후보요약"
TIMELINE_FILE_PREFIX = "최종매수_30일타임라인"
DIFF_FILE_PREFIX = "최종매수_전일비교"
SIGNAL_SUMMARY_FILE_PREFIX = "신호성과요약"
SIGNAL_EVENTS_FILE_PREFIX = "신호발생상세"
SELECTION_GUIDE_FILE_PREFIX = "종목선정_판단보조"
SIGNAL_INDICATOR_GUIDE_FILE_PREFIX = "신호지표_초보자가이드"
SELECTION_PRIORITY_FILE_PREFIX = "종목선정_우선검토"
CORE_SELECTION_FILE_PREFIX = "종목선정_핵심근거"
MIN_SIGNAL_SAMPLE_COUNT = 30
DEFAULT_OUTPUT_MODE = "compact"


def make_bilingual_headers(columns: list[str]) -> list[str]:
    out: list[str] = []
    for c in columns:
        ko = COLUMN_KO_MAP.get(c, (c, ""))[0]
        out.append(ko)
    return out


def safe_float(v: object) -> float:
    try:
        if v is None:
            return np.nan
        return float(v)
    except Exception:
        return np.nan


def _clamp(v: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, v)))


def _lin_scale(v: float, lo: float, hi: float) -> float:
    if np.isnan(v):
        return np.nan
    if hi <= lo:
        return np.nan
    return _clamp((v - lo) / (hi - lo), 0.0, 1.0)


def _zfill6(v: object) -> str:
    return str(v or "").strip().zfill(6)


def _find_prev_output_date(prefix: str, today: str) -> Optional[str]:
    pat = re.compile(rf"^{re.escape(prefix)}_(\d{{4}}-\d{{2}}-\d{{2}})\.csv$")
    dates: list[str] = []
    for p in OUTPUT_DIR.glob(f"{prefix}_*.csv"):
        m = pat.match(p.name)
        if not m:
            continue
        d = m.group(1)
        if d < today:
            dates.append(d)
    if not dates:
        return None
    return sorted(dates)[-1]


def _make_bilingual_with_extra(columns: list[str], extra_ko: dict[str, str]) -> list[str]:
    out: list[str] = []
    for c in columns:
        if c in COLUMN_KO_MAP:
            ko = COLUMN_KO_MAP[c][0]
        else:
            ko = extra_ko.get(c, c)
        out.append(ko)
    return out


def _safe_write_csv(df: pd.DataFrame, out_path: Path) -> Path:
    try:
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
        return out_path
    except PermissionError:
        alt = out_path.with_name(f"{out_path.stem}_locked_{datetime.now().strftime('%H%M%S')}{out_path.suffix}")
        df.to_csv(alt, index=False, encoding="utf-8-sig")
        print(f"[Warn] File is locked, saved to fallback: {alt}")
        return alt


def cleanup_legacy_outputs(today: str) -> list[Path]:
    removed: list[Path] = []
    patterns = [
        f"up_valuation_report_{today}.csv",
        f"up_final_buy_timeline_10d_{today}.csv",
        f"up_final_buy_timeline_30d_{today}.csv",
        f"up_final_buy_timeline_30d_ko_{today}.csv",
        f"up_watchlist_brief_ko_{today}.csv",
        f"up_entry_candidates_brief_ko_{today}.csv",
    ]
    for pat in patterns:
        for p in OUTPUT_DIR.glob(pat):
            try:
                p.unlink(missing_ok=True)
                removed.append(p)
            except Exception:
                continue
    return removed


def cleanup_redundant_outputs(today: str) -> list[Path]:
    removed: list[Path] = []
    patterns = [
        f"{WATCH_FILE_PREFIX}_{today}.csv",
        f"{ENTRY_FILE_PREFIX}_{today}.csv",
        f"{SIGNAL_SUMMARY_FILE_PREFIX}_{today}.csv",
        f"{SIGNAL_EVENTS_FILE_PREFIX}_{today}.csv",
        f"{SELECTION_GUIDE_FILE_PREFIX}_{today}.csv",
        f"{SELECTION_PRIORITY_FILE_PREFIX}_{today}.csv",
        f"{SIGNAL_INDICATOR_GUIDE_FILE_PREFIX}_{today}.csv",
    ]
    for pat in patterns:
        for p in OUTPUT_DIR.glob(pat):
            try:
                p.unlink(missing_ok=True)
                removed.append(p)
            except Exception:
                continue
    return removed


def ensure_column_dictionary_doc(df_sorted: pd.DataFrame) -> Optional[Path]:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    if COLUMN_DICT_DOC_PATH.exists():
        return None

    meta_rows = []
    for c in list(df_sorted.columns):
        ko_name, ko_desc = COLUMN_KO_MAP.get(c, (c, "설명 미정의 컬럼"))
        meta_rows.append({"column_en": c, "column_ko": ko_name, "description_ko": ko_desc})
    _safe_write_csv(pd.DataFrame(meta_rows), COLUMN_DICT_DOC_PATH)
    return COLUMN_DICT_DOC_PATH


def is_excluded_instrument(name: object) -> bool:
    return bool(EXCLUDE_NAME_PAT.search(str(name or "").strip()))


def maybe_rebuild_universe_csv(top_n_kospi: int, top_n_kosdaq: int) -> Optional[pd.DataFrame]:
    if krx_stock is None and fdr is None:
        return None

    # pykrx expects YYYYMMDD.
    trade_date = None
    try:
        if hasattr(krx_stock, "get_nearest_business_day_in_a_week"):
            trade_date = krx_stock.get_nearest_business_day_in_a_week()
    except Exception:
        trade_date = None
    if not trade_date:
        trade_date = datetime.now().strftime("%Y%m%d")

    kospi = pd.DataFrame()
    kosdaq = pd.DataFrame()
    if krx_stock is not None:
        try:
            kospi = krx_stock.get_market_cap_by_ticker(date=trade_date, market="KOSPI")
            kosdaq = krx_stock.get_market_cap_by_ticker(date=trade_date, market="KOSDAQ")
        except Exception:
            kospi = pd.DataFrame()
            kosdaq = pd.DataFrame()

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
            pat = re.compile(r"(우$|\(우\)|스팩|SPAC|ETF|ETN|리츠|REIT)", re.IGNORECASE)
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
        # Market cap column name differs by pykrx version.
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
        out = pd.DataFrame({"name": names, "ticker": df["ticker"].tolist(), "market": market_code})
        return out

    u1 = _build(kospi, "KS", top_n_kospi)
    u2 = _build(kosdaq, "KQ", top_n_kosdaq)
    universe = pd.concat([u1, u2], ignore_index=True)

    # Filter obvious non-common-stock items by name.
    pat = re.compile(r"(우$|\(우\)|스팩|SPAC|ETF|ETN|리츠|REIT)", re.IGNORECASE)
    universe = universe.loc[~universe["name"].astype(str).str.contains(pat, na=False)].copy()
    universe["ticker"] = universe["ticker"].astype(str).str.zfill(6)

    universe.to_csv(UNIVERSE_PATH, index=False, encoding="utf-8-sig")
    return universe


def load_eps_cache(cache_path: Path) -> pd.DataFrame:
    if not cache_path.exists():
        return pd.DataFrame(columns=["ticker", "trailing_eps_dart", "consensus_eps_scrape"])
    df = pd.read_csv(cache_path, dtype={"ticker": str})
    df["ticker"] = df["ticker"].astype(str).str.zfill(6)
    return df


def sync_assumptions_with_universe(universe: pd.DataFrame, assumptions: pd.DataFrame) -> pd.DataFrame:
    assumptions = assumptions.copy()
    if "ticker" not in assumptions.columns:
        assumptions["ticker"] = ""
    assumptions["ticker"] = assumptions["ticker"].astype(str).str.zfill(6)

    base = pd.DataFrame({"ticker": universe["ticker"].astype(str).str.zfill(6)})
    merged = base.merge(assumptions, on="ticker", how="left", suffixes=("", "_old"))

    for k, v in DEFAULT_ASSUMPTION.items():
        if k not in merged.columns:
            merged[k] = v
        merged[k] = merged[k].where(~merged[k].isna(), v)

    merged.to_csv(ASSUMPTIONS_PATH, index=False, encoding="utf-8-sig")
    return merged


def calc_rsi(close: pd.Series, period: int = 14) -> float:
    if close is None or close.dropna().shape[0] < period + 2:
        return np.nan
    delta = close.diff()
    up = delta.clip(lower=0)
    down = (-delta).clip(lower=0)
    roll_up = up.ewm(alpha=1 / period, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / period, adjust=False).mean()
    rs = roll_up / roll_down
    rsi = 100 - (100 / (1 + rs))
    return safe_float(rsi.iloc[-1])


def calc_macd_hist(close: pd.Series) -> float:
    if close is None or close.dropna().shape[0] < 35:
        return np.nan
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return safe_float(hist.iloc[-1])


def calc_volume_ratio(volume: pd.Series, window: int = 20) -> float:
    if volume is None or volume.dropna().shape[0] < window + 2:
        return np.nan
    avg = volume.rolling(window).mean().iloc[-2]
    cur = volume.iloc[-1]
    if avg and avg > 0:
        return safe_float(cur / avg)
    return np.nan


def calc_breakout_20d_high(close: pd.Series) -> int:
    if close is None or close.dropna().shape[0] < 22:
        return 0
    prev_high = safe_float(close.iloc[-21:-1].max())
    cur = safe_float(close.iloc[-1])
    return 1 if (cur > 0 and prev_high > 0 and cur >= prev_high) else 0


def calc_returns(close: pd.Series, n: int) -> float:
    if close is None or close.dropna().shape[0] < n + 1:
        return np.nan
    cur = safe_float(close.iloc[-1])
    past = safe_float(close.iloc[-(n + 1)])
    if past > 0:
        return (cur / past - 1.0) * 100.0
    return np.nan


def calc_technical_score(row: pd.Series) -> float:
    close = safe_float(row.get("close"))
    ma20 = safe_float(row.get("ma20"))
    ma60 = safe_float(row.get("ma60"))
    ma200 = safe_float(row.get("ma200"))
    rsi = safe_float(row.get("rsi14"))
    macd = safe_float(row.get("macd_hist"))
    vol = safe_float(row.get("volume_ratio_20d"))
    breakout = int(row.get("breakout_20d_high", 0) or 0)

    score = 0.0

    # Trend strength (55 points): make score continuous instead of step jumps.
    if close > 0 and ma200 > 0:
        rel = (close / ma200) - 1.0
        score += 30.0 * _lin_scale(rel, -0.12, 0.18)
    if close > 0 and ma60 > 0:
        rel = (close / ma60) - 1.0
        score += 15.0 * _lin_scale(rel, -0.10, 0.12)
    if ma20 > 0 and ma60 > 0:
        rel = (ma20 / ma60) - 1.0
        score += 10.0 * _lin_scale(rel, -0.06, 0.08)

    # RSI quality (15 points): 58 근처를 최고점으로 두고 과열/침체는 감점.
    if not np.isnan(rsi):
        rsi_score = 1.0 - min(abs(rsi - 58.0) / 42.0, 1.0)
        score += 15.0 * _clamp(rsi_score, 0.0, 1.0)

    # MACD momentum (10 points): absolute value by close for cross-ticker comparability.
    if (not np.isnan(macd)) and close > 0:
        macd_pct = (macd / close) * 100.0
        score += 10.0 * _lin_scale(macd_pct, -1.0, 1.5)

    # Volume + breakout (20 points).
    if not np.isnan(vol):
        score += 10.0 * _lin_scale(vol, 0.6, 2.5)
    if breakout == 1:
        score += 10.0

    return _clamp(score, 0.0, 100.0)


def calc_valuation_score(upside_pct: float) -> float:
    if np.isnan(upside_pct):
        return np.nan
    # Continuous mapping for finer stock-by-stock separation.
    if upside_pct <= -40:
        return 5.0
    if upside_pct < 0:
        return 5.0 + 35.0 * _lin_scale(upside_pct, -40.0, 0.0)
    if upside_pct <= 80:
        return 40.0 + 52.0 * _lin_scale(upside_pct, 0.0, 80.0)
    extra = _clamp((upside_pct - 80.0) / 80.0, 0.0, 1.0)
    return 92.0 + 8.0 * extra


def _safe_nanmedian(series: pd.Series) -> float:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return float("nan")
    return float(np.median(numeric.to_numpy(dtype=float)))


def calc_weight(total_score: float, max_position_pct: float) -> float:
    if np.isnan(total_score):
        return 0.0
    if total_score >= 80:
        return float(max_position_pct)
    if total_score >= 65:
        return float(min(max_position_pct, max_position_pct * 0.75))
    if total_score >= 50:
        return float(min(max_position_pct, max_position_pct * 0.5))
    if total_score >= 35:
        return float(min(max_position_pct, max_position_pct * 0.25))
    return 0.0


def _calc_rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    close = pd.to_numeric(close, errors="coerce")
    delta = close.diff()
    up = delta.clip(lower=0)
    down = (-delta).clip(lower=0)
    roll_up = up.ewm(alpha=1 / period, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / period, adjust=False).mean()
    rs = roll_up / roll_down
    rsi = 100 - (100 / (1 + rs))
    return pd.to_numeric(rsi, errors="coerce")


def _calc_macd_hist_series(close: pd.Series) -> pd.Series:
    close = pd.to_numeric(close, errors="coerce")
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return pd.to_numeric(hist, errors="coerce")


def _build_signal_event_rows(name: str, ticker: str, market: str, hist: pd.DataFrame) -> list[dict[str, object]]:
    if hist is None or hist.empty:
        return []
    if "Close" not in hist.columns or "Volume" not in hist.columns:
        return []

    close = pd.to_numeric(hist["Close"], errors="coerce")
    volume = pd.to_numeric(hist["Volume"], errors="coerce")
    if close.dropna().shape[0] < 230:
        return []

    ma200 = close.rolling(200).mean()
    above_ma200 = (close > ma200).astype(int)
    prev20_high = close.shift(1).rolling(20).max()
    breakout = ((close > 0) & (prev20_high > 0) & (close >= prev20_high)).astype(int)
    vol_ratio_20d = volume / volume.rolling(20).mean()
    rsi14 = _calc_rsi_series(close)
    macd_hist = _calc_macd_hist_series(close)

    # forward returns
    fwd1 = (close.shift(-1) / close - 1.0) * 100.0
    fwd3 = (close.shift(-3) / close - 1.0) * 100.0
    fwd5 = (close.shift(-5) / close - 1.0) * 100.0
    fwd10 = (close.shift(-10) / close - 1.0) * 100.0
    fwd20 = (close.shift(-20) / close - 1.0) * 100.0

    signals = {
        "거래량급증_1.8배": vol_ratio_20d >= 1.8,
        "거래량급증_2.5배": vol_ratio_20d >= 2.5,
        "돌파+거래량_1.5배": (breakout == 1) & (vol_ratio_20d >= 1.5) & (above_ma200 == 1),
        "돌파실패_1일내": (breakout.shift(1) == 1) & (breakout == 0),
        "돌파+거래량+RSI안전": (breakout == 1) & (vol_ratio_20d >= 1.5) & (above_ma200 == 1) & (rsi14 <= 75),
    }

    # Use past-complete samples only (need at least +20d future path)
    valid_sample = close.notna() & fwd20.notna()
    dates = pd.to_datetime(close.index).tz_localize(None)
    close_np = close.to_numpy(dtype=float)

    rows: list[dict[str, object]] = []
    for sig_name, mask in signals.items():
        idxs = np.where((mask.fillna(False) & valid_sample).to_numpy())[0]
        for i in idxs:
            # MFE/MAE over next 10 trading days
            future = close_np[i + 1 : i + 11]
            if future.size == 0:
                continue
            cur = close_np[i]
            if not np.isfinite(cur) or cur <= 0:
                continue
            mfe_10d = (np.nanmax(future) / cur - 1.0) * 100.0
            mae_10d = (np.nanmin(future) / cur - 1.0) * 100.0

            rows.append(
                {
                    "기준일": dates[i].strftime("%Y-%m-%d"),
                    "종목명": name,
                    "종목코드": ticker,
                    "시장": market,
                    "신호명": sig_name,
                    "종가": cur,
                    "거래량비율20일": float(vol_ratio_20d.iloc[i]) if pd.notna(vol_ratio_20d.iloc[i]) else np.nan,
                    "20일돌파": int(breakout.iloc[i]) if pd.notna(breakout.iloc[i]) else 0,
                    "200일선상단": int(above_ma200.iloc[i]) if pd.notna(above_ma200.iloc[i]) else 0,
                    "RSI14": float(rsi14.iloc[i]) if pd.notna(rsi14.iloc[i]) else np.nan,
                    "MACD히스토그램": float(macd_hist.iloc[i]) if pd.notna(macd_hist.iloc[i]) else np.nan,
                    "선행1일수익률(%)": float(fwd1.iloc[i]) if pd.notna(fwd1.iloc[i]) else np.nan,
                    "선행3일수익률(%)": float(fwd3.iloc[i]) if pd.notna(fwd3.iloc[i]) else np.nan,
                    "선행5일수익률(%)": float(fwd5.iloc[i]) if pd.notna(fwd5.iloc[i]) else np.nan,
                    "선행10일수익률(%)": float(fwd10.iloc[i]) if pd.notna(fwd10.iloc[i]) else np.nan,
                    "선행20일수익률(%)": float(fwd20.iloc[i]) if pd.notna(fwd20.iloc[i]) else np.nan,
                    "최대상승폭10일(%)": float(mfe_10d),
                    "최대하락폭10일(%)": float(mae_10d),
                }
            )

    return rows


def _build_signal_summary(events_df: pd.DataFrame, today: str) -> pd.DataFrame:
    if events_df.empty:
        return pd.DataFrame(
            columns=[
                "기준일",
                "신호명",
                "발생건수",
                "5일승률(%)",
                "평균1일수익률(%)",
                "평균3일수익률(%)",
                "평균5일수익률(%)",
                "평균10일수익률(%)",
                "평균20일수익률(%)",
                "중앙값5일수익률(%)",
                "중앙값10일수익률(%)",
                "평균최대상승폭10일(%)",
                "평균최대하락폭10일(%)",
                "기대값5일(%)",
            ]
        )

    out_rows = []
    for sig_name, g in events_df.groupby("신호명"):
        ret5 = pd.to_numeric(g["선행5일수익률(%)"], errors="coerce")
        wins = ret5 > 0
        win_rate = float(wins.mean() * 100.0) if ret5.notna().any() else np.nan
        avg_win = float(ret5[wins].mean()) if wins.any() else 0.0
        lose_mask = (ret5 <= 0) & ret5.notna()
        lose_rate = float(lose_mask.mean()) if ret5.notna().any() else 0.0
        avg_loss = float(ret5[lose_mask].mean()) if lose_mask.any() else 0.0
        expectancy = (float(wins.mean()) * avg_win) + (lose_rate * avg_loss) if ret5.notna().any() else np.nan

        out_rows.append(
            {
                "기준일": today,
                "신호명": sig_name,
                "발생건수": int(len(g)),
                "5일승률(%)": win_rate,
                "평균1일수익률(%)": float(pd.to_numeric(g["선행1일수익률(%)"], errors="coerce").mean()),
                "평균3일수익률(%)": float(pd.to_numeric(g["선행3일수익률(%)"], errors="coerce").mean()),
                "평균5일수익률(%)": float(ret5.mean()),
                "평균10일수익률(%)": float(pd.to_numeric(g["선행10일수익률(%)"], errors="coerce").mean()),
                "평균20일수익률(%)": float(pd.to_numeric(g["선행20일수익률(%)"], errors="coerce").mean()),
                "중앙값5일수익률(%)": float(ret5.median()),
                "중앙값10일수익률(%)": float(pd.to_numeric(g["선행10일수익률(%)"], errors="coerce").median()),
                "평균최대상승폭10일(%)": float(pd.to_numeric(g["최대상승폭10일(%)"], errors="coerce").mean()),
                "평균최대하락폭10일(%)": float(pd.to_numeric(g["최대하락폭10일(%)"], errors="coerce").mean()),
                "기대값5일(%)": float(expectancy),
            }
        )

    out = pd.DataFrame(out_rows)
    return out.sort_values(by=["기대값5일(%)", "평균5일수익률(%)"], ascending=False).reset_index(drop=True)


def _build_selection_guide(
    df_sorted: pd.DataFrame,
    signal_summary_df: pd.DataFrame,
    today: str,
) -> pd.DataFrame:
    cols = [
        "기준일",
        "추천순위",
        "종목명",
        "종목코드",
        "시장",
        "결합액션",
        "종합점수",
        "기술점수",
        "밸류점수",
        "상승여력(%)",
        "거래량비율20일",
        "거래량신호점수",
        "거래량백분위(시장내%)",
        "거래량판정",
        "과거거래량신호_5일승률(%)",
        "과거거래량신호_기대값5일(%)",
        "20일돌파",
        "200일선상단여부",
        "RSI14",
        "EPS소스",
        "선택신호",
        "선택신호_기대값5일(%)",
        "선택신호_평균5일수익률(%)",
        "선택신호_5일승률(%)",
        "선택신호_발생건수",
        "선택신호_성과순위",
        "선택신호_신뢰도",
        "현재신호목록",
        "신호강도",
        "신호등급",
        "초보자체크",
        "초보자설명",
        "선정의견",
        "점수_신호매력도",
        "점수_리스크",
        "최종판단점수",
        "선정핵심근거",
        "판단코멘트",
    ]

    entry = df_sorted.loc[df_sorted["combined_action"].isin(["최종매수후보", "진입대기"])].copy()
    if entry.empty:
        return pd.DataFrame(columns=cols)

    sig_map: dict[str, dict[str, float]] = {}
    sig_rank_map: dict[str, int] = {}
    if signal_summary_df is not None and not signal_summary_df.empty:
        ranked = signal_summary_df.sort_values(by=["기대값5일(%)", "평균5일수익률(%)"], ascending=False).reset_index(drop=True)
        for i, rr in ranked.iterrows():
            nm = str(rr.get("신호명", "") or "").strip()
            if nm:
                sig_rank_map[nm] = int(i + 1)
        for _, r in signal_summary_df.iterrows():
            sig_name = str(r.get("신호명", "") or "").strip()
            if not sig_name:
                continue
            sig_map[sig_name] = {
                "expectancy": float(pd.to_numeric(r.get("기대값5일(%)", np.nan), errors="coerce")),
                "avg5": float(pd.to_numeric(r.get("평균5일수익률(%)", np.nan), errors="coerce")),
                "win5": float(pd.to_numeric(r.get("5일승률(%)", np.nan), errors="coerce")),
                "count": float(pd.to_numeric(r.get("발생건수", np.nan), errors="coerce")),
            }

    def _vol_state(vol: float) -> str:
        if not np.isfinite(vol):
            return "확인불가"
        if vol >= 2.5:
            return "매우강함"
        if vol >= 1.8:
            return "강함"
        if vol >= 1.2:
            return "관심증가"
        if vol >= 0.8:
            return "보통"
        return "약함"

    def _rsi_state(rsi: float) -> str:
        if not np.isfinite(rsi):
            return "확인불가"
        if rsi >= 75:
            return "과열주의"
        if rsi >= 60:
            return "상승탄력"
        if rsi >= 45:
            return "중립"
        return "약세"

    def _signal_note(sig_name: str, expectancy: float, win5: float, count: float) -> str:
        if sig_name == "해당없음":
            return "현재 강한 매수신호는 없습니다. 추세와 거래량이 함께 확인될 때까지 관찰이 유리합니다."
        if np.isfinite(count) and count < MIN_SIGNAL_SAMPLE_COUNT:
            return "신호는 발생했지만 과거 표본이 적어 신뢰도는 낮습니다. 소액/분할 접근이 유리합니다."
        if np.isfinite(expectancy) and np.isfinite(win5):
            if expectancy >= 2.0 and win5 >= 55:
                return "과거 통계상 상대적으로 유리한 신호입니다. 분할진입을 고려할 수 있습니다."
            if expectancy >= 0.5:
                return "성과는 플러스 구간이지만 변동성이 있습니다. 비중을 낮춰 접근이 좋습니다."
            return "과거 통계상 기대수익이 낮거나 음수입니다. 추격매수는 피하는 편이 좋습니다."
        if np.isfinite(count) and count < 20:
            return "발생 사례가 적어 신뢰도가 낮습니다. 참고 신호로만 활용하세요."
        return "과거 통계가 충분하지 않습니다. 보조지표로만 참고하세요."

    def _selection_opinion(final_score: float, chosen: str, expectancy: float, risk: float) -> str:
        if final_score >= 62 and chosen != "해당없음" and (not np.isfinite(expectancy) or expectancy >= 1.0):
            return "우선검토"
        if final_score >= 50 and risk <= 12:
            return "관찰후진입"
        return "관망"

    def _signal_reliability(count: float) -> str:
        if not np.isfinite(count):
            return "통계없음"
        if count >= 200:
            return "높음"
        if count >= MIN_SIGNAL_SAMPLE_COUNT:
            return "보통"
        return "낮음"

    def _grade_color(final_score: float, opinion: str, risk: float) -> str:
        if opinion == "우선검토" and final_score >= 62 and risk <= 12:
            return "상(초록)"
        if opinion == "관찰후진입" and final_score >= 50:
            return "중(노랑)"
        return "하(빨강)"

    def _active_signals(r: pd.Series) -> list[str]:
        vol = float(pd.to_numeric(r.get("volume_ratio_20d", np.nan), errors="coerce"))
        brk = int(pd.to_numeric(r.get("breakout_20d_high", 0), errors="coerce") or 0)
        up200 = int(pd.to_numeric(r.get("above_ma200", 0), errors="coerce") or 0)
        rsi = float(pd.to_numeric(r.get("rsi14", np.nan), errors="coerce"))
        out: list[str] = []
        if np.isfinite(vol) and vol >= 1.8:
            out.append("거래량급증_1.8배")
        if np.isfinite(vol) and vol >= 2.5:
            out.append("거래량급증_2.5배")
        if brk == 1 and up200 == 1 and np.isfinite(vol) and vol >= 1.5:
            out.append("돌파+거래량_1.5배")
        if brk == 1 and up200 == 1 and np.isfinite(vol) and vol >= 1.5 and np.isfinite(rsi) and rsi <= 75:
            out.append("돌파+거래량+RSI안전")
        return out

    rows: list[dict[str, object]] = []
    for _, r in entry.iterrows():
        active = _active_signals(r)
        chosen = "해당없음"
        chosen_stats = {"expectancy": np.nan, "avg5": np.nan, "win5": np.nan, "count": np.nan}
        if active:
            best_sig = None
            best_exp = -1e18
            for s in active:
                exp = sig_map.get(s, {}).get("expectancy", np.nan)
                if pd.notna(exp) and exp > best_exp:
                    best_exp = float(exp)
                    best_sig = s
            if best_sig is not None:
                chosen = best_sig
                chosen_stats = sig_map.get(best_sig, chosen_stats)
            else:
                chosen = active[0]

        total_score = float(pd.to_numeric(r.get("total_score", np.nan), errors="coerce"))
        signal_attract = float(chosen_stats.get("expectancy", np.nan)) if pd.notna(chosen_stats.get("expectancy", np.nan)) else 0.0
        signal_count = float(chosen_stats.get("count", np.nan)) if pd.notna(chosen_stats.get("count", np.nan)) else np.nan
        if np.isfinite(signal_count) and signal_count < MIN_SIGNAL_SAMPLE_COUNT:
            signal_attract = signal_attract * 0.5

        risk = 0.0
        rsi = float(pd.to_numeric(r.get("rsi14", np.nan), errors="coerce"))
        if np.isfinite(rsi) and rsi >= 75:
            risk += 12.0
        if int(pd.to_numeric(r.get("above_ma200", 0), errors="coerce") or 0) == 0:
            risk += 10.0
        if str(r.get("eps_source_used", "") or "") in {"FORWARD_AUTO", "GROWTH_AUTO"}:
            risk += 6.0
        if str(r.get("market_regime", "") or "") == "BEAR":
            risk += 6.0

        final_score = (0.7 * total_score) + (0.4 * signal_attract) - risk
        vol = float(pd.to_numeric(r.get("volume_ratio_20d", np.nan), errors="coerce"))
        vol_pct_rank = float(pd.to_numeric(r.get("volume_ratio_pct_rank", np.nan), errors="coerce"))
        vol_signal_score = _clamp((vol - 0.8) / (2.5 - 0.8), 0.0, 1.0) * 100.0 if np.isfinite(vol) else np.nan
        brk = int(pd.to_numeric(r.get("breakout_20d_high", 0), errors="coerce") or 0)
        up200 = int(pd.to_numeric(r.get("above_ma200", 0), errors="coerce") or 0)
        sig_list = ",".join(active) if active else "없음"
        sig_strength = _vol_state(vol)

        vol_related = [s for s in active if "거래량" in s]
        vol_hist_win = np.nan
        vol_hist_exp = np.nan
        if vol_related:
            best_vol_sig = None
            best_vol_exp = -1e18
            for s in vol_related:
                exp = sig_map.get(s, {}).get("expectancy", np.nan)
                if pd.notna(exp) and exp > best_vol_exp:
                    best_vol_exp = float(exp)
                    best_vol_sig = s
            if best_vol_sig is not None:
                vol_hist_win = float(sig_map.get(best_vol_sig, {}).get("win5", np.nan))
                vol_hist_exp = float(sig_map.get(best_vol_sig, {}).get("expectancy", np.nan))

        beginner_check = f"거래량:{sig_strength} / 돌파:{'O' if brk == 1 else 'X'} / 추세:{'상단' if up200 == 1 else '하단'} / RSI:{_rsi_state(rsi)}"
        beginner_note = _signal_note(
            sig_name=chosen,
            expectancy=float(chosen_stats.get("expectancy", np.nan)),
            win5=float(chosen_stats.get("win5", np.nan)),
            count=float(chosen_stats.get("count", np.nan)),
        )
        opinion = _selection_opinion(
            final_score=final_score,
            chosen=chosen,
            expectancy=float(chosen_stats.get("expectancy", np.nan)),
            risk=risk,
        )
        signal_reliability = _signal_reliability(signal_count)
        grade_color = _grade_color(final_score=final_score, opinion=opinion, risk=risk)

        comment_parts = []
        if chosen != "해당없음":
            comment_parts.append(f"신호:{chosen}")
        else:
            comment_parts.append("신호부재")
        if np.isfinite(rsi) and rsi >= 75:
            comment_parts.append("RSI과열")
        if int(pd.to_numeric(r.get("above_ma200", 0), errors="coerce") or 0) == 0:
            comment_parts.append("200일선하단")
        if str(r.get("eps_source_used", "") or "") in {"FORWARD_AUTO", "GROWTH_AUTO"}:
            comment_parts.append("EPS추정치의존")
        if not comment_parts:
            comment_parts.append("기본조건양호")

        sig_win_txt = (
            f"{float(chosen_stats.get('win5', np.nan)):.1f}%"
            if pd.notna(chosen_stats.get("win5", np.nan))
            else "통계부족"
        )
        sig_exp_txt = (
            f"{float(chosen_stats.get('expectancy', np.nan)):.2f}%"
            if pd.notna(chosen_stats.get("expectancy", np.nan))
            else "통계부족"
        )
        vol_pct_txt = f"{vol_pct_rank:.0f}%" if np.isfinite(vol_pct_rank) else "확인불가"
        core_reason = (
            f"신호:{chosen} (과거5일 승률 {sig_win_txt}, 기대값 {sig_exp_txt}) | "
            f"거래량:{vol:.2f}배({sig_strength}, 시장내 상위 {vol_pct_txt}) | "
            f"추세:{'200일선 상단' if up200 == 1 else '200일선 하단'} / 돌파:{'있음' if brk == 1 else '없음'}"
        )

        rows.append(
            {
                "기준일": today,
                "추천순위": int(pd.to_numeric(r.get("suggested_rank", np.nan), errors="coerce"))
                if pd.notna(pd.to_numeric(r.get("suggested_rank", np.nan), errors="coerce"))
                else np.nan,
                "종목명": r.get("name"),
                "종목코드": r.get("ticker"),
                "시장": r.get("market"),
                "결합액션": r.get("combined_action"),
                "종합점수": total_score,
                "기술점수": float(pd.to_numeric(r.get("technical_score", np.nan), errors="coerce")),
                "밸류점수": float(pd.to_numeric(r.get("valuation_score", np.nan), errors="coerce")),
                "상승여력(%)": float(pd.to_numeric(r.get("upside_base_pct", np.nan), errors="coerce")),
                "거래량비율20일": float(pd.to_numeric(r.get("volume_ratio_20d", np.nan), errors="coerce")),
                "거래량신호점수": float(vol_signal_score),
                "거래량백분위(시장내%)": float(vol_pct_rank) if np.isfinite(vol_pct_rank) else np.nan,
                "거래량판정": sig_strength,
                "과거거래량신호_5일승률(%)": vol_hist_win,
                "과거거래량신호_기대값5일(%)": vol_hist_exp,
                "20일돌파": int(pd.to_numeric(r.get("breakout_20d_high", 0), errors="coerce") or 0),
                "200일선상단여부": int(pd.to_numeric(r.get("above_ma200", 0), errors="coerce") or 0),
                "RSI14": rsi,
                "EPS소스": r.get("eps_source_used"),
                "선택신호": chosen,
                "선택신호_기대값5일(%)": float(chosen_stats.get("expectancy", np.nan)),
                "선택신호_평균5일수익률(%)": float(chosen_stats.get("avg5", np.nan)),
                "선택신호_5일승률(%)": float(chosen_stats.get("win5", np.nan)),
                "선택신호_발생건수": float(chosen_stats.get("count", np.nan)),
                "선택신호_성과순위": sig_rank_map.get(chosen, np.nan),
                "선택신호_신뢰도": signal_reliability,
                "현재신호목록": sig_list,
                "신호강도": sig_strength,
                "신호등급": grade_color,
                "초보자체크": beginner_check,
                "초보자설명": beginner_note,
                "선정의견": opinion,
                "점수_신호매력도": signal_attract,
                "점수_리스크": risk,
                "최종판단점수": float(final_score),
                "선정핵심근거": core_reason,
                "판단코멘트": "|".join(comment_parts),
            }
        )

    out = pd.DataFrame(rows)
    return out.sort_values(by=["최종판단점수", "종합점수"], ascending=False).reset_index(drop=True)


def _build_signal_indicator_guide(signal_summary_df: pd.DataFrame, today: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = [
        {
            "기준일": today,
            "구분": "지표설명",
            "항목": "거래량비율20일",
            "기준": "1.0=평균, 1.8이상=강한수급, 2.5이상=매우강한수급",
            "초보자해설": "값이 클수록 시장 관심이 커졌다는 뜻입니다. 돌파 신호와 함께 나오면 의미가 커집니다.",
            "주의": "거래량만 크고 종가가 밀리면 실패 가능성이 큽니다.",
            "과거5일기대값(%)": np.nan,
            "과거5일승률(%)": np.nan,
            "발생건수": np.nan,
            "해석": "돌파/추세와 결합 확인",
        },
        {
            "기준일": today,
            "구분": "지표설명",
            "항목": "20일돌파",
            "기준": "1=직전20일 고가 돌파, 0=비돌파",
            "초보자해설": "최근 박스권 상단을 넘겼는지 보여줍니다.",
            "주의": "다음날 재하락하면 돌파실패일 수 있습니다.",
            "과거5일기대값(%)": np.nan,
            "과거5일승률(%)": np.nan,
            "발생건수": np.nan,
            "해석": "거래량 동반 돌파 우선",
        },
        {
            "기준일": today,
            "구분": "지표설명",
            "항목": "200일선상단여부",
            "기준": "1=장기추세 상방, 0=장기추세 하방",
            "초보자해설": "장기 추세가 위쪽인지 아래쪽인지 보여줍니다.",
            "주의": "하방 구간에서는 같은 신호도 실패율이 높아질 수 있습니다.",
            "과거5일기대값(%)": np.nan,
            "과거5일승률(%)": np.nan,
            "발생건수": np.nan,
            "해석": "가능하면 상단 종목 우선",
        },
        {
            "기준일": today,
            "구분": "지표설명",
            "항목": "RSI14",
            "기준": "75이상 과열주의, 60~75 상승탄력, 45~60 중립",
            "초보자해설": "최근 상승 속도가 과열인지 확인합니다.",
            "주의": "과열 구간 추격매수는 변동성 리스크가 큽니다.",
            "과거5일기대값(%)": np.nan,
            "과거5일승률(%)": np.nan,
            "발생건수": np.nan,
            "해석": "과열이면 분할진입",
        },
    ]

    if signal_summary_df is not None and not signal_summary_df.empty:
        ranked = signal_summary_df.sort_values(by=["기대값5일(%)", "평균5일수익률(%)"], ascending=False).reset_index(drop=True)
        for i, r in ranked.iterrows():
            expectancy = float(pd.to_numeric(r.get("기대값5일(%)", np.nan), errors="coerce"))
            win5 = float(pd.to_numeric(r.get("5일승률(%)", np.nan), errors="coerce"))
            count = float(pd.to_numeric(r.get("발생건수", np.nan), errors="coerce"))
            if np.isfinite(expectancy) and expectancy >= 2.0 and np.isfinite(win5) and win5 >= 55:
                interp = "우선관찰 신호"
            elif np.isfinite(expectancy) and expectancy >= 0:
                interp = "보통 신호"
            else:
                interp = "주의 신호"

            rows.append(
                {
                    "기준일": today,
                    "구분": "과거신호통계",
                    "항목": str(r.get("신호명", "")),
                    "기준": f"성과순위 {i + 1}",
                    "초보자해설": "이 신호가 과거에 얼마나 유리했는지 통계로 보여줍니다.",
                    "주의": "과거 통계는 미래 수익을 보장하지 않습니다.",
                    "과거5일기대값(%)": expectancy,
                    "과거5일승률(%)": win5,
                    "발생건수": count,
                    "해석": interp,
                }
            )

    return pd.DataFrame(rows)


def _build_core_selection_output(selection_guide_df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "기준일",
        "추천순위",
        "종목명",
        "종목코드",
        "시장",
        "선정의견",
        "선정핵심근거",
        "선택신호",
        "선택신호_신뢰도",
        "선택신호_5일승률(%)",
        "선택신호_기대값5일(%)",
        "선택신호_발생건수",
        "거래량비율20일",
        "거래량신호점수",
        "거래량백분위(시장내%)",
        "거래량판정",
        "과거거래량신호_5일승률(%)",
        "과거거래량신호_기대값5일(%)",
        "20일돌파",
        "200일선상단여부",
        "RSI14",
        "종합점수",
        "최종판단점수",
        "초보자설명",
        "판단코멘트",
    ]
    if selection_guide_df is None or selection_guide_df.empty:
        return pd.DataFrame(columns=cols)

    core = selection_guide_df.copy()
    core = core.loc[core["선정의견"].isin(["우선검토", "관찰후진입"])].copy()
    if core.empty:
        core = selection_guide_df.copy()
    keep = [c for c in cols if c in core.columns]
    return core[keep].sort_values(by=["최종판단점수", "종합점수"], ascending=False).reset_index(drop=True)


def build_final_buy_timeline_30d(df_sorted: pd.DataFrame, today: str) -> Optional[Path]:
    out_path = OUTPUT_DIR / f"{TIMELINE_FILE_PREFIX}_{today}.csv"
    final_buy = df_sorted.loc[df_sorted["combined_action"] == "최종매수후보", ["name", "ticker", "market"]].copy()
    if final_buy.empty:
        empty = pd.DataFrame(
            columns=["date", "name", "ticker", "market", "close", "prev20_high", "breakout_20d_high", "volume_ratio_20d"]
        )
        timeline_extra_ko = {
            "prev20_high": "직전20일고가",
        }
        empty_ko = empty.copy()
        empty_ko.columns = _make_bilingual_with_extra(list(empty_ko.columns), timeline_extra_ko)
        saved = _safe_write_csv(empty_ko, out_path)
        return saved

    rows: list[pd.DataFrame] = []
    for _, r in final_buy.iterrows():
        ticker = _zfill6(r.get("ticker"))
        market = str(r.get("market") or "KS").strip() or "KS"
        name = str(r.get("name") or "").strip()
        yf_ticker = f"{ticker}.KS" if market == "KS" else f"{ticker}.KQ"

        try:
            hist = yf.Ticker(yf_ticker).history(period="6mo", auto_adjust=False)
        except Exception:
            continue
        if hist is None or hist.empty:
            continue

        close = pd.to_numeric(hist.get("Close"), errors="coerce")
        volume = pd.to_numeric(hist.get("Volume"), errors="coerce")
        if close is None or close.dropna().empty:
            continue

        prev20_high = close.shift(1).rolling(20).max()
        breakout = ((close > 0) & (prev20_high > 0) & (close >= prev20_high)).astype(int)
        vol20 = volume.rolling(20).mean()
        vol_ratio = volume / vol20

        d = pd.DataFrame(
            {
                "date": pd.to_datetime(close.index).tz_localize(None).date.astype(str),
                "name": name,
                "ticker": ticker,
                "market": market,
                "close": close.values,
                "prev20_high": prev20_high.values,
                "breakout_20d_high": breakout.values,
                "volume_ratio_20d": vol_ratio.values,
            }
        )
        d = d.dropna(subset=["prev20_high"]).tail(30)
        rows.append(d)

    if not rows:
        return None

    out = pd.concat(rows, ignore_index=True)
    out["close"] = pd.to_numeric(out["close"], errors="coerce").round(2)
    out["prev20_high"] = pd.to_numeric(out["prev20_high"], errors="coerce").round(2)
    out["volume_ratio_20d"] = pd.to_numeric(out["volume_ratio_20d"], errors="coerce").round(2)
    out["breakout_20d_high"] = pd.to_numeric(out["breakout_20d_high"], errors="coerce").fillna(0).astype(int)

    timeline_extra_ko = {
        "prev20_high": "직전20일고가",
    }
    out_ko = out.copy()
    out_ko.columns = _make_bilingual_with_extra(list(out_ko.columns), timeline_extra_ko)
    saved = _safe_write_csv(out_ko, out_path)
    return saved


def build_final_buy_diff(df_sorted: pd.DataFrame, today: str) -> Optional[Path]:
    prev_date = _find_prev_output_date(REPORT_FILE_PREFIX, today)
    prev_prefix = REPORT_FILE_PREFIX
    if not prev_date:
        prev_date = _find_prev_output_date("up_valuation_report", today)
        prev_prefix = "up_valuation_report"
    if not prev_date:
        return None

    prev_path = OUTPUT_DIR / f"{prev_prefix}_{prev_date}.csv"
    if not prev_path.exists():
        return None

    try:
        prev_df = pd.read_csv(prev_path, dtype={"ticker": str})
    except Exception:
        return None

    cur = df_sorted.copy()
    prev = prev_df.copy()
    prev.columns = [KO_TO_EN_MAP.get(str(c), str(c)) for c in list(prev.columns)]
    cur["ticker"] = cur["ticker"].astype(str).str.zfill(6)
    prev["ticker"] = prev["ticker"].astype(str).str.zfill(6)

    cur_buy = cur.loc[cur["combined_action"] == "최종매수후보"].copy()
    prev_buy = prev.loc[prev["combined_action"] == "최종매수후보"].copy()

    wanted = [
        "ticker",
        "name",
        "suggested_rank",
        "combined_action",
        "total_score",
        "technical_score",
        "valuation_score",
        "breakout_20d_high",
        "volume_ratio_20d",
        "upside_base_pct",
    ]
    for c in wanted:
        if c not in cur_buy.columns:
            cur_buy[c] = np.nan
        if c not in prev_buy.columns:
            prev_buy[c] = np.nan

    cur_buy = cur_buy[wanted]
    prev_buy = prev_buy[wanted]

    merged = prev_buy.merge(cur_buy, on="ticker", how="outer", suffixes=("_prev", "_today"))
    if merged.empty:
        return None

    def _status(row: pd.Series) -> str:
        in_prev = pd.notna(row.get("name_prev"))
        in_today = pd.notna(row.get("name_today"))
        if in_prev and in_today:
            return "유지"
        if in_prev and (not in_today):
            return "이탈"
        return "신규"

    merged["status"] = merged.apply(_status, axis=1)
    merged["name"] = merged["name_today"].where(merged["name_today"].notna(), merged["name_prev"])

    for c in ["suggested_rank_prev", "suggested_rank_today"]:
        merged[c] = pd.to_numeric(merged[c], errors="coerce")
    for c in [
        "total_score_prev",
        "total_score_today",
        "technical_score_prev",
        "technical_score_today",
        "valuation_score_prev",
        "valuation_score_today",
        "breakout_20d_high_prev",
        "breakout_20d_high_today",
        "volume_ratio_20d_prev",
        "volume_ratio_20d_today",
        "upside_base_pct_prev",
        "upside_base_pct_today",
    ]:
        merged[c] = pd.to_numeric(merged[c], errors="coerce")

    merged["delta_rank"] = merged["suggested_rank_today"] - merged["suggested_rank_prev"]
    merged["delta_total_score"] = merged["total_score_today"] - merged["total_score_prev"]
    merged["delta_technical_score"] = merged["technical_score_today"] - merged["technical_score_prev"]
    merged["delta_valuation_score"] = merged["valuation_score_today"] - merged["valuation_score_prev"]
    merged["delta_volume_ratio_20d"] = merged["volume_ratio_20d_today"] - merged["volume_ratio_20d_prev"]
    merged["delta_upside_base_pct"] = merged["upside_base_pct_today"] - merged["upside_base_pct_prev"]

    merged.insert(0, "date_today", today)
    merged.insert(1, "date_prev", prev_date)

    keep_cols = [
        "date_today",
        "date_prev",
        "status",
        "name",
        "ticker",
        "suggested_rank_prev",
        "suggested_rank_today",
        "delta_rank",
        "combined_action_prev",
        "combined_action_today",
        "total_score_prev",
        "total_score_today",
        "delta_total_score",
        "technical_score_prev",
        "technical_score_today",
        "delta_technical_score",
        "valuation_score_prev",
        "valuation_score_today",
        "delta_valuation_score",
        "breakout_20d_high_prev",
        "breakout_20d_high_today",
        "volume_ratio_20d_prev",
        "volume_ratio_20d_today",
        "delta_volume_ratio_20d",
        "upside_base_pct_prev",
        "upside_base_pct_today",
        "delta_upside_base_pct",
    ]
    out = merged[keep_cols].copy()
    out = out.sort_values(by=["status", "delta_total_score"], ascending=[True, True], na_position="last")

    out_path = OUTPUT_DIR / f"{DIFF_FILE_PREFIX}_{today}_vs_{prev_date}.csv"

    diff_extra_ko = {
        "date_today": "당일기준일",
        "date_prev": "전일기준일",
        "status": "변화상태",
        "name": "종목명",
        "ticker": "종목코드",
        "suggested_rank_prev": "전일추천순위",
        "suggested_rank_today": "당일추천순위",
        "delta_rank": "순위변화",
        "combined_action_prev": "전일결합액션",
        "combined_action_today": "당일결합액션",
        "total_score_prev": "전일종합점수",
        "total_score_today": "당일종합점수",
        "delta_total_score": "종합점수변화",
        "technical_score_prev": "전일기술점수",
        "technical_score_today": "당일기술점수",
        "delta_technical_score": "기술점수변화",
        "valuation_score_prev": "전일밸류점수",
        "valuation_score_today": "당일밸류점수",
        "delta_valuation_score": "밸류점수변화",
        "breakout_20d_high_prev": "전일20일돌파",
        "breakout_20d_high_today": "당일20일돌파",
        "volume_ratio_20d_prev": "전일거래량비율20일",
        "volume_ratio_20d_today": "당일거래량비율20일",
        "delta_volume_ratio_20d": "거래량비율20일변화",
        "upside_base_pct_prev": "전일상승여력(%)",
        "upside_base_pct_today": "당일상승여력(%)",
        "delta_upside_base_pct": "상승여력변화(%)",
    }
    out_ko = out.copy()
    out_ko.columns = _make_bilingual_with_extra(list(out_ko.columns), diff_extra_ko)
    saved = _safe_write_csv(out_ko, out_path)
    return saved


def _calc_market_regime_meta(period: str = "6mo") -> dict[str, object]:
    """Calculate market regime diagnostics and return metadata.

    Multi-signal regime rule:
    - MA signal: close < MA20
    - Volatility signal: HV20 percentile >= 60%
    - Momentum signal: ROC60 < 0

    Aggregate each signal across KOSPI/KOSDAQ with a simple majority vote.
    If 2+ signals are BEAR -> BEAR, 1 signal -> NEUTRAL, else BULL.
    """
    tickers = ["^KS11", "^KQ11"]
    signal_bear = {"ma": 0, "hv": 0, "roc": 0}
    signal_valid = {"ma": 0, "hv": 0, "roc": 0}
    ticker_meta: dict[str, dict[str, object]] = {}

    for t in tickers:
        row_meta: dict[str, object] = {
            "ma_bear": None,
            "hv_bear": None,
            "roc_bear": None,
            "close": np.nan,
            "ma20": np.nan,
            "hv20_pct": np.nan,
            "roc60": np.nan,
        }
        try:
            hist = yf.Ticker(t).history(period=period, auto_adjust=False)
        except Exception:
            hist = None
        if hist is None or hist.empty or "Close" not in hist.columns:
            ticker_meta[t] = row_meta
            continue

        close = hist["Close"].dropna()
        if close.empty:
            ticker_meta[t] = row_meta
            continue
        row_meta["close"] = float(pd.to_numeric(close.iloc[-1], errors="coerce"))

        # MA20 signal
        if close.shape[0] >= 25:
            signal_valid["ma"] += 1
            ma20 = pd.to_numeric(close.rolling(20).mean().iloc[-1], errors="coerce")
            cur = pd.to_numeric(close.iloc[-1], errors="coerce")
            row_meta["ma20"] = float(ma20) if pd.notna(ma20) else np.nan
            if pd.notna(cur) and pd.notna(ma20) and float(cur) > 0 and float(ma20) > 0 and float(cur) < float(ma20):
                signal_bear["ma"] += 1
                row_meta["ma_bear"] = 1
            else:
                row_meta["ma_bear"] = 0

        # HV20 percentile signal
        ret = close.pct_change().dropna()
        hv20 = ret.rolling(20).std() * np.sqrt(252)
        hv20 = pd.to_numeric(hv20, errors="coerce").dropna()
        if hv20.shape[0] >= 20:
            signal_valid["hv"] += 1
            hv_cur = float(hv20.iloc[-1])
            hv_hist = hv20.tail(252)
            hv_pct = float((hv_hist <= hv_cur).mean()) if hv_hist.shape[0] > 0 else np.nan
            row_meta["hv20_pct"] = hv_pct
            if np.isfinite(hv_pct) and hv_pct >= 0.60:
                signal_bear["hv"] += 1
                row_meta["hv_bear"] = 1
            else:
                row_meta["hv_bear"] = 0

        # ROC60 signal
        if close.shape[0] >= 61:
            signal_valid["roc"] += 1
            cur = pd.to_numeric(close.iloc[-1], errors="coerce")
            prev60 = pd.to_numeric(close.iloc[-61], errors="coerce")
            if pd.notna(cur) and pd.notna(prev60) and float(prev60) > 0:
                roc60 = (float(cur) / float(prev60)) - 1.0
                row_meta["roc60"] = roc60
                if np.isfinite(roc60) and roc60 < 0:
                    signal_bear["roc"] += 1
                    row_meta["roc_bear"] = 1
                else:
                    row_meta["roc_bear"] = 0

        ticker_meta[t] = row_meta

    total_valid_signals = sum(signal_valid.values())
    if total_valid_signals == 0:
        return {
            "regime": "UNKNOWN",
            "multiplier": 1.0,
            "bear_votes": 0,
            "signal_bear": signal_bear,
            "signal_valid": signal_valid,
            "ticker_meta": ticker_meta,
        }

    bear_votes = 0
    for key in ("ma", "hv", "roc"):
        valid = int(signal_valid[key])
        if valid <= 0:
            continue
        if float(signal_bear[key]) / float(valid) >= 0.5:
            bear_votes += 1

    regime = "BULL"
    multiplier = 1.0
    if bear_votes >= 2:
        regime = "BEAR"
        multiplier = 0.5
    elif bear_votes == 1:
        regime = "NEUTRAL"
        multiplier = 0.8

    return {
        "regime": regime,
        "multiplier": multiplier,
        "bear_votes": bear_votes,
        "signal_bear": signal_bear,
        "signal_valid": signal_valid,
        "ticker_meta": ticker_meta,
    }


def calc_market_regime_and_multiplier(period: str = "6mo") -> tuple[str, float]:
    """Return market regime and weight multiplier."""
    meta = _calc_market_regime_meta(period=period)
    return str(meta["regime"]), float(meta["multiplier"])


def _compose_brief_reason_and_warn(row: pd.Series) -> tuple[str, str]:
    reasons: list[str] = []
    warns: list[str] = []

    upside = pd.to_numeric(row.get("upside_base_pct", np.nan), errors="coerce")
    if not pd.isna(upside) and upside >= 10:
        reasons.append(f"상승여력 {upside:.0f}%")

    close = pd.to_numeric(row.get("close", np.nan), errors="coerce")
    ma200 = pd.to_numeric(row.get("ma200", np.nan), errors="coerce")
    if (not pd.isna(close)) and (not pd.isna(ma200)) and ma200 > 0 and close > ma200:
        reasons.append("200일↑")

    breakout = row.get("breakout_20d_high", 0)
    try:
        breakout = int(breakout)
    except Exception:
        breakout = 0
    if breakout == 1:
        reasons.append("20일돌파")

    vol_ratio = pd.to_numeric(row.get("volume_ratio_20d", np.nan), errors="coerce")
    if (not pd.isna(vol_ratio)) and vol_ratio >= 1.5:
        reasons.append(f"거래량x{vol_ratio:.1f}")

    rsi = pd.to_numeric(row.get("rsi14", np.nan), errors="coerce")
    if (not pd.isna(rsi)) and 45 <= rsi <= 70:
        reasons.append("RSI우호")

    macd_hist = pd.to_numeric(row.get("macd_hist", np.nan), errors="coerce")
    if (not pd.isna(macd_hist)) and macd_hist > 0:
        reasons.append("MACD+")

    if str(row.get("source_primary", "") or "").strip() and str(row.get("source_primary")).strip() != "DART":
        warns.append("EPS스크랩")

    if str(row.get("eps_source_used", "")).strip() == "GROWTH_AUTO":
        warns.append("성장률추정")

    if str(row.get("market_regime", "")).strip() == "BEAR":
        warns.append("하락장비중축소")

    if pd.isna(pd.to_numeric(row.get("expected_eps", np.nan), errors="coerce")):
        warns.append("EPS없음")
        reasons.append("비밸류평가")

    is_loss = row.get("is_loss_making", 0)
    try:
        is_loss = int(is_loss)
    except Exception:
        is_loss = 0
    if is_loss == 1:
        warns.append("적자")

    return " | ".join(reasons[:6]), ",".join(warns)


def main(limit: int | None = None, period: str = "1y", output_mode: str = DEFAULT_OUTPUT_MODE) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if AUTO_BUILD_UNIVERSE and (not UNIVERSE_PATH.exists()):
        rebuilt = maybe_rebuild_universe_csv(TOP_N_KOSPI, TOP_N_KOSDAQ)
        if rebuilt is not None:
            print(f"[Universe] Auto rebuilt: {len(rebuilt)} rows")

    if not UNIVERSE_PATH.exists():
        raise FileNotFoundError(f"Missing universe.csv: {UNIVERSE_PATH}")

    universe = pd.read_csv(UNIVERSE_PATH, dtype={"ticker": str, "market": str})
    universe["ticker"] = universe["ticker"].astype(str).str.zfill(6)
    if "name" in universe.columns:
        universe = universe.loc[~universe["name"].apply(is_excluded_instrument)].copy()
    if limit is not None and limit > 0:
        universe = universe.head(int(limit)).copy()

    assumptions = pd.DataFrame({"ticker": []})
    if ASSUMPTIONS_PATH.exists():
        assumptions = pd.read_csv(ASSUMPTIONS_PATH, dtype={"ticker": str})
    assumptions = sync_assumptions_with_universe(universe, assumptions)

    eps_cache = load_eps_cache(EPS_CACHE_PATH)

    today = datetime.now().strftime("%Y-%m-%d")
    regime_meta = _calc_market_regime_meta(period="6mo")
    market_regime = str(regime_meta["regime"])
    regime_mult = float(regime_meta["multiplier"])
    signal_bear = regime_meta["signal_bear"]
    signal_valid = regime_meta["signal_valid"]
    bear_votes = int(regime_meta["bear_votes"])
    print(
        f"[Regime] regime={market_regime}, multiplier={regime_mult:.2f}, votes={bear_votes}/3 "
        f"(ma={signal_bear['ma']}/{signal_valid['ma']}, hv={signal_bear['hv']}/{signal_valid['hv']}, roc={signal_bear['roc']}/{signal_valid['roc']})"
    )
    ticker_meta = regime_meta["ticker_meta"]
    for t in ("^KS11", "^KQ11"):
        tm = ticker_meta.get(t, {})
        close = pd.to_numeric(tm.get("close", np.nan), errors="coerce")
        ma20 = pd.to_numeric(tm.get("ma20", np.nan), errors="coerce")
        hv_pct = pd.to_numeric(tm.get("hv20_pct", np.nan), errors="coerce")
        roc60 = pd.to_numeric(tm.get("roc60", np.nan), errors="coerce")
        ma_flag = tm.get("ma_bear")
        hv_flag = tm.get("hv_bear")
        roc_flag = tm.get("roc_bear")
        print(
            f"[Regime:{t}] close={close:.2f} ma20={ma20:.2f} hv20_pct={hv_pct:.2%} roc60={roc60:.2%} "
            f"flags(ma/hv/roc)={ma_flag}/{hv_flag}/{roc_flag}"
        )

    # Pre-compute simple market return proxy (average of all symbols 20d)
    market_return_20d = 0.0

    rows = []
    signal_event_rows: list[dict[str, object]] = []
    for _, u in universe.iterrows():
        ticker = _zfill6(u.get("ticker"))
        name = str(u.get("name") or "").strip()
        market = str(u.get("market") or "").strip() or "KS"

        yf_ticker = f"{ticker}.KS" if market == "KS" else f"{ticker}.KQ"
        tk = yf.Ticker(yf_ticker)
        try:
            hist = tk.history(period=str(period), auto_adjust=False)
        except Exception:
            continue
        if hist is None or hist.empty:
            continue

        close_series = hist["Close"].dropna()
        if close_series.empty:
            continue

        signal_event_rows.extend(_build_signal_event_rows(name=name, ticker=ticker, market=market, hist=hist))

        close = safe_float(close_series.iloc[-1])
        ma20 = safe_float(close_series.rolling(20).mean().iloc[-1])
        ma60 = safe_float(close_series.rolling(60).mean().iloc[-1])
        ma120 = safe_float(close_series.rolling(120).mean().iloc[-1])
        ma200 = safe_float(close_series.rolling(200).mean().iloc[-1])
        above_ma200 = int(close > ma200) if ma200 and ma200 > 0 else 0

        rsi14 = calc_rsi(close_series)
        macd_hist = calc_macd_hist(close_series)
        volume_ratio_20d = calc_volume_ratio(hist.get("Volume"))
        breakout_20d_high = calc_breakout_20d_high(close_series)

        ret_5d = calc_returns(close_series, 5)
        ret_20d = calc_returns(close_series, 20)
        rs_20d = ret_20d - market_return_20d if not np.isnan(ret_20d) else np.nan

        arow = assumptions.loc[assumptions["ticker"].astype(str).str.zfill(6) == ticker]
        if arow.empty:
            a = pd.Series(DEFAULT_ASSUMPTION)
        else:
            a = arow.iloc[0]

        cache_row = eps_cache.loc[eps_cache["ticker"].astype(str).str.zfill(6) == ticker]
        trailing_eps_dart = np.nan
        consensus_eps_scrape = np.nan
        forward_eps_auto = np.nan
        source_primary = ""
        if not cache_row.empty:
            trailing_eps_dart = safe_float(cache_row.iloc[0].get("trailing_eps_dart", np.nan))
            consensus_eps_scrape = safe_float(cache_row.iloc[0].get("consensus_eps_scrape", np.nan))
            forward_eps_auto = safe_float(cache_row.iloc[0].get("forward_eps_auto", np.nan))
            source_primary = str(cache_row.iloc[0].get("source_primary", "") or "").strip()

        manual_forward_eps = safe_float(a.get("manual_forward_eps", np.nan))
        expected_eps = manual_forward_eps
        eps_source_used = "MANUAL_FORWARD_EPS"
        # Priority changed per request: Manual > DART > Consensus > Forward Auto.
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
            # Forward fallback using user assumption growth when consensus is missing.
            growth_pct = safe_float(a.get("eps_growth_3y_pct", 10.0))
            growth = growth_pct / 100.0 if not np.isnan(growth_pct) else 0.10
            growth = float(np.clip(growth, -0.5, 0.8))
            expected_eps = trailing_eps_dart * (1.0 + growth)
            eps_source_used = "GROWTH_AUTO"

        target_pe_base = safe_float(a.get("target_pe_base", 12.0))

        fair_price_base = expected_eps * target_pe_base if (not np.isnan(expected_eps) and close > 0) else np.nan
        upside_base_pct = ((fair_price_base / close) - 1.0) * 100.0 if (not np.isnan(fair_price_base) and close > 0) else np.nan
        pe_now = close / expected_eps if (close > 0 and expected_eps and not np.isnan(expected_eps) and expected_eps != 0) else np.nan

        valuation_score = calc_valuation_score(safe_float(upside_base_pct))

        row = {
            "name": name,
            "ticker": ticker,
            "market": market,
            "sector_group": str(a.get("sector_group", "기타")),
            "close": close,
            "ma20": ma20,
            "ma60": ma60,
            "ma120": ma120,
            "ma200": ma200,
            "above_ma200": above_ma200,
            "rsi14": rsi14,
            "macd_hist": macd_hist,
            "volume_ratio_20d": volume_ratio_20d,
            "breakout_20d_high": breakout_20d_high,
            "return_5d": ret_5d,
            "return_20d": ret_20d,
            "relative_strength_20d": rs_20d,
            "trailing_eps_dart": trailing_eps_dart,
            "consensus_eps_scrape": consensus_eps_scrape,
            "forward_eps_auto": forward_eps_auto,
            "source_primary": source_primary,
            "eps_source_used": eps_source_used,
            "manual_forward_eps": manual_forward_eps,
            "expected_eps": expected_eps,
            "pe_now": pe_now,
            "fair_price_base": fair_price_base,
            "upside_base_pct": upside_base_pct,
            "valuation_score": valuation_score,
            "is_loss_making": 1 if ((expected_eps < 0) or (trailing_eps_dart < 0)) else int(safe_float(a.get("is_loss_making", 0)) or 0),
            "max_position_pct": safe_float(a.get("max_position_pct", 3.0)),
        }

        row["technical_score"] = calc_technical_score(pd.Series(row))

        # total_score: valuation(50%) + technical(50%) if valuation exists, else technical only
        if np.isnan(row["valuation_score"]):
            row["total_score"] = float(row["technical_score"])
        else:
            row["total_score"] = float(0.5 * row["valuation_score"] + 0.5 * row["technical_score"])

        # action
        has_eps = not np.isnan(pd.to_numeric(row.get("expected_eps", np.nan), errors="coerce"))
        cond_buy = has_eps and (row["total_score"] >= 75) and (above_ma200 == 1) and (breakout_20d_high == 1)
        cond_wait = has_eps and (row["total_score"] >= 65) and (above_ma200 == 1)
        cond_watch = has_eps and (row["total_score"] >= 50)

        if cond_buy:
            row["combined_action"] = "최종매수후보"
        elif cond_wait:
            row["combined_action"] = "진입대기"
        elif cond_watch:
            row["combined_action"] = "관찰"
        elif not has_eps:
            # EPS 결측 종목은 밸류 판단을 보류하되 관찰군에 남긴다.
            # 자동 비중은 0%로 유지해 리스크를 통제한다.
            row["combined_action"] = "관찰"
        else:
            row["combined_action"] = "제외"

        row["suggested_weight_pct"] = calc_weight(row["total_score"], row["max_position_pct"])
        if not has_eps:
            row["suggested_weight_pct"] = 0.0
        
        # Action-weight consistency check (NEW in v1.1.0): force 0% weight if excluded
        if row["combined_action"] == "제외":
            row["suggested_weight_pct"] = 0.0
        
        row["market_regime"] = market_regime
        row["regime_weight_multiplier"] = regime_mult
        row["suggested_weight_pct"] = float(row["suggested_weight_pct"] * regime_mult)

        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("No rows produced. Data collection failed.")

    df_sorted = df.sort_values(by=["total_score", "technical_score", "upside_base_pct"], ascending=False).reset_index(drop=True)

    # Sector PE cap: prevent fair value explosion when EPS estimate is unstable.
    df_sorted["sector_pe_cap"] = df_sorted.groupby("sector_group")["pe_now"].transform(_safe_nanmedian)
    df_sorted["sector_pe_cap"] = pd.to_numeric(df_sorted["sector_pe_cap"], errors="coerce").clip(lower=5.0, upper=30.0)
    use_cap = df_sorted["eps_source_used"].isin(["FORWARD_AUTO", "GROWTH_AUTO"])
    eff_pe = np.where(use_cap, np.minimum(df_sorted["sector_pe_cap"], 25.0), np.nan)
    eff_pe = np.where(np.isnan(eff_pe), np.nan, eff_pe)
    cap_price = pd.to_numeric(df_sorted["expected_eps"], errors="coerce") * pd.to_numeric(eff_pe, errors="coerce")
    cap_upside = ((cap_price / pd.to_numeric(df_sorted["close"], errors="coerce")) - 1.0) * 100.0
    overwrite_mask = use_cap & cap_price.notna()
    df_sorted.loc[overwrite_mask, "fair_price_base"] = cap_price[overwrite_mask]
    df_sorted.loc[overwrite_mask, "upside_base_pct"] = cap_upside[overwrite_mask]
    df_sorted.loc[overwrite_mask, "valuation_score"] = df_sorted.loc[overwrite_mask, "upside_base_pct"].apply(calc_valuation_score)
    # Recompute total_score after valuation overwrite.
    df_sorted["total_score"] = np.where(
        pd.to_numeric(df_sorted["valuation_score"], errors="coerce").isna(),
        pd.to_numeric(df_sorted["technical_score"], errors="coerce"),
        0.5 * pd.to_numeric(df_sorted["valuation_score"], errors="coerce")
        + 0.5 * pd.to_numeric(df_sorted["technical_score"], errors="coerce"),
    )

    # Re-rank after overwrite.
    df_sorted = df_sorted.sort_values(by=["total_score", "technical_score", "upside_base_pct"], ascending=False).reset_index(drop=True)
    df_sorted.insert(0, "suggested_rank", np.arange(1, len(df_sorted) + 1))
    df_sorted.insert(1, "combined_rank", np.arange(1, len(df_sorted) + 1))
    df_sorted.insert(0, "date", today)

    # add brief reason/warn
    pair = df_sorted.apply(_compose_brief_reason_and_warn, axis=1, result_type="expand")
    pair.columns = ["brief_reason", "warn_flags"]
    df_sorted = df_sorted.join(pair)

    # Relative volume percentile in today's universe (0~100).
    df_sorted["volume_ratio_pct_rank"] = pd.to_numeric(df_sorted["volume_ratio_20d"], errors="coerce").rank(pct=True) * 100.0

    out_full = OUTPUT_DIR / f"{REPORT_FILE_PREFIX}_{today}.csv"
    report_ko = df_sorted.copy()
    report_ko.columns = make_bilingual_headers(list(report_ko.columns))
    out_full = _safe_write_csv(report_ko, out_full)

    # Watchlist (human-friendly)
    watch_cols = [
        "date",
        "suggested_rank",
        "combined_rank",
        "name",
        "ticker",
        "market",
        "sector_group",
        "close",
        "upside_base_pct",
        "valuation_score",
        "technical_score",
        "total_score",
        "combined_action",
        "suggested_weight_pct",
        "brief_reason",
        "warn_flags",
    ]
    watch = df_sorted[watch_cols].copy()
    watch_ko = watch.copy()
    watch_ko.columns = make_bilingual_headers(list(watch_ko.columns))
    out_watch = OUTPUT_DIR / f"{WATCH_FILE_PREFIX}_{today}.csv"
    out_watch = _safe_write_csv(watch_ko, out_watch)

    # Entry candidates
    entry = df_sorted.loc[df_sorted["combined_action"].isin(["최종매수후보", "진입대기"])].copy()
    entry_cols = watch_cols
    entry = entry[entry_cols]
    entry_ko = entry.copy()
    entry_ko.columns = make_bilingual_headers(list(entry_ko.columns))
    out_entry = OUTPUT_DIR / f"{ENTRY_FILE_PREFIX}_{today}.csv"
    out_entry = _safe_write_csv(entry_ko, out_entry)

    signal_events_df = pd.DataFrame(signal_event_rows)
    signal_summary_df = _build_signal_summary(signal_events_df, today=today)
    selection_guide_df = _build_selection_guide(df_sorted=df_sorted, signal_summary_df=signal_summary_df, today=today)
    signal_indicator_guide_df = _build_signal_indicator_guide(signal_summary_df=signal_summary_df, today=today)
    core_selection_df = _build_core_selection_output(selection_guide_df=selection_guide_df)

    out_core_selection = OUTPUT_DIR / f"{CORE_SELECTION_FILE_PREFIX}_{today}.csv"
    out_core_selection = _safe_write_csv(core_selection_df, out_core_selection)

    out_signal_summary = None
    out_signal_events = None
    out_selection_guide = None
    out_selection_priority = None
    out_signal_indicator_guide = None
    out_watch_saved = None
    out_entry_saved = None

    if output_mode == "full":
        out_watch_saved = out_watch
        out_entry_saved = out_entry

        out_signal_summary = OUTPUT_DIR / f"{SIGNAL_SUMMARY_FILE_PREFIX}_{today}.csv"
        out_signal_summary = _safe_write_csv(signal_summary_df, out_signal_summary)

        out_signal_events = OUTPUT_DIR / f"{SIGNAL_EVENTS_FILE_PREFIX}_{today}.csv"
        out_signal_events = _safe_write_csv(signal_events_df, out_signal_events)

        out_selection_guide = OUTPUT_DIR / f"{SELECTION_GUIDE_FILE_PREFIX}_{today}.csv"
        out_selection_guide = _safe_write_csv(selection_guide_df, out_selection_guide)

        priority_df = selection_guide_df.loc[selection_guide_df["선정의견"] == "우선검토"].copy()
        out_selection_priority = OUTPUT_DIR / f"{SELECTION_PRIORITY_FILE_PREFIX}_{today}.csv"
        out_selection_priority = _safe_write_csv(priority_df, out_selection_priority)

        out_signal_indicator_guide = OUTPUT_DIR / f"{SIGNAL_INDICATOR_GUIDE_FILE_PREFIX}_{today}.csv"
        out_signal_indicator_guide = _safe_write_csv(signal_indicator_guide_df, out_signal_indicator_guide)
    else:
        cleanup_redundant_outputs(today=today)

    # Column dictionary is managed as a documentation asset.
    created_column_doc = ensure_column_dictionary_doc(df_sorted=df_sorted)

    out_timeline = build_final_buy_timeline_30d(df_sorted=df_sorted, today=today)
    out_diff = build_final_buy_diff(df_sorted=df_sorted, today=today)
    removed_legacy = cleanup_legacy_outputs(today=today)

    print("[Saved]", out_full)
    print("[Saved]", out_core_selection)
    if out_watch_saved is not None:
        print("[Saved]", out_watch_saved)
    if out_entry_saved is not None:
        print("[Saved]", out_entry_saved)
    if out_signal_summary is not None:
        print("[Saved]", out_signal_summary)
    if out_signal_events is not None:
        print("[Saved]", out_signal_events)
    if out_selection_guide is not None:
        print("[Saved]", out_selection_guide)
    if out_selection_priority is not None:
        print("[Saved]", out_selection_priority)
    if out_signal_indicator_guide is not None:
        print("[Saved]", out_signal_indicator_guide)
    if out_timeline is not None:
        print("[Saved]", out_timeline)
    if out_diff is not None:
        print("[Saved]", out_diff)
    if created_column_doc is not None:
        print("[Saved]", created_column_doc)
    for p in removed_legacy:
        print("[Removed Legacy]", p)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build UP daily valuation report (brief outputs included)")
    parser.add_argument("--limit", type=int, default=0, help="Optional ticker limit for quick test")
    parser.add_argument("--period", type=str, default="1y", help="yfinance history period (e.g., 6mo, 1y, 2y)")
    parser.add_argument(
        "--output-mode",
        type=str,
        default=DEFAULT_OUTPUT_MODE,
        choices=["compact", "full"],
        help="compact: 핵심 파일만 생성(기본), full: 모든 상세 파일 생성",
    )
    args = parser.parse_args()
    main(
        limit=(args.limit if args.limit and args.limit > 0 else None),
        period=str(args.period or "1y"),
        output_mode=str(args.output_mode or DEFAULT_OUTPUT_MODE),
    )

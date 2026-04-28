from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.errors import EmptyDataError

import build_daily_report as report


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"


def _latest_file(pattern: str) -> Path | None:
    candidates = [path for path in OUTPUT_DIR.glob(pattern) if path.is_file() and "_locked_" not in path.name]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, keep_default_na=True)
    except EmptyDataError:
        return pd.DataFrame()


def _pick_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for name in candidates:
        if name in df.columns:
            return name
    return None


def _load_signal_frame(input_path: str | None = None) -> pd.DataFrame:
    if input_path:
        path = Path(input_path)
    else:
        path = _latest_file("상세리포트_*.csv")
        if path is None:
            raise FileNotFoundError(f"Missing detailed report in {OUTPUT_DIR}")
    if not path.exists():
        raise FileNotFoundError(f"Missing detailed report: {path}")
    return _read_csv(path)


def _load_positions() -> pd.DataFrame:
    candidates = [
        OUTPUT_DIR / "positions.csv",
        _latest_file("positions_*.csv"),
    ]
    for path in candidates:
        if path is not None and path.exists():
            return _read_csv(path)
    return pd.DataFrame()


def _to_float(value: object) -> float:
    return report.safe_float(value)


def _trade_date_text() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _normalise_signals(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    colmap = {
        "기준일": "trade_date",
        "추천순위": "rank",
        "종목명": "name",
        "종목코드": "ticker",
        "시장": "market",
        "섹터그룹": "sector_group",
        "종가": "close",
        "상승여력(%)": "upside_pct",
        "밸류점수": "valuation_score",
        "기술점수": "technical_score",
        "종합점수": "total_score",
        "결합액션": "action",
        "권장비중(%)": "target_weight_pct",
        "마켓레짐": "market_regime",
        "레짐비중배수": "regime_weight_multiplier",
        "핵심요약": "brief_reason",
        "주의표시": "warn_flags",
        "20일돌파": "breakout_20d_high",
        "200일선상단여부": "above_ma200",
        "RSI14": "rsi14",
        "최대비중(%)": "max_position_pct",
    }
    rename_map = {src: dst for src, dst in colmap.items() if src in out.columns}
    out = out.rename(columns=rename_map)
    if "ticker" in out.columns:
        out["ticker"] = out["ticker"].astype(str).str.zfill(6)
    return out


def _normalise_positions(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[
            "as_of_date",
            "ticker",
            "position_status",
            "entry_date",
            "entry_price",
            "current_weight_pct",
            "initial_stop_price",
            "trailing_stop_price",
            "days_held",
        ])

    out = df.copy()
    rename_candidates = {
        "기준일": "as_of_date",
        "as_of_date": "as_of_date",
        "종목코드": "ticker",
        "ticker": "ticker",
        "포지션상태": "position_status",
        "position_status": "position_status",
        "편입일": "entry_date",
        "entry_date": "entry_date",
        "편입가": "entry_price",
        "entry_price": "entry_price",
        "현재비중(%)": "current_weight_pct",
        "current_weight_pct": "current_weight_pct",
        "초기손절가": "initial_stop_price",
        "initial_stop_price": "initial_stop_price",
        "트레일링손절가": "trailing_stop_price",
        "trailing_stop_price": "trailing_stop_price",
        "보유일수": "days_held",
        "days_held": "days_held",
    }
    rename_map = {src: dst for src, dst in rename_candidates.items() if src in out.columns}
    out = out.rename(columns=rename_map)
    if "ticker" in out.columns:
        out["ticker"] = out["ticker"].astype(str).str.zfill(6)
    return out


def _current_position_map(positions: pd.DataFrame) -> dict[str, pd.Series]:
    if positions.empty or "ticker" not in positions.columns:
        return {}
    current = positions.copy()
    current["ticker"] = current["ticker"].astype(str).str.zfill(6)
    current = current.sort_values(by=[c for c in ["as_of_date", "entry_date"] if c in current.columns], ascending=False)
    latest: dict[str, pd.Series] = {}
    for _, row in current.iterrows():
        ticker = str(row.get("ticker", "") or "").zfill(6)
        if ticker and ticker not in latest:
            latest[ticker] = row
    return latest


def _scale_weights(rows: list[dict[str, object]], total_cap: float = 90.0) -> list[dict[str, object]]:
    positive = [row for row in rows if _to_float(row.get("target_weight_pct", 0.0)) > 0 and str(row.get("side", "")) == "BUY"]
    total = sum(_to_float(row.get("target_weight_pct", 0.0)) for row in positive)
    if total <= 0 or total <= total_cap:
        return rows
    scale = total_cap / total
    for row in positive:
        row["target_weight_pct"] = float(_to_float(row.get("target_weight_pct", 0.0)) * scale)
    return rows


def _build_position_plan(signals: pd.DataFrame, positions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    today = _trade_date_text()
    latest_positions = _current_position_map(positions)

    if "ticker" not in signals.columns:
        raise ValueError("Signal input missing ticker column")

    signals = signals.copy()
    signals["ticker"] = signals["ticker"].astype(str).str.zfill(6)

    rows: list[dict[str, object]] = []
    order_rows: list[dict[str, object]] = []
    event_rows: list[dict[str, object]] = []

    sector_weight_sum: dict[str, float] = {}
    processed_tickers: set[str] = set()

    signal_lookup = {str(row.get("ticker", "") or "").zfill(6): row for _, row in signals.iterrows()}

    buy_candidates = signals.loc[signals["action"].isin(["최종매수후보", "진입대기"])].copy()
    buy_candidates = buy_candidates.sort_values(by=["total_score", "technical_score", "upside_pct"], ascending=False).reset_index(drop=True)

    for _, row in buy_candidates.iterrows():
        ticker = str(row.get("ticker", "") or "").zfill(6)
        sector = str(row.get("sector_group", "기타") or "기타")
        current_close = _to_float(row.get("close", np.nan))
        target_weight_pct = _to_float(row.get("target_weight_pct", 0.0))
        if not np.isfinite(target_weight_pct):
            target_weight_pct = 0.0

        sector_total = sector_weight_sum.get(sector, 0.0)
        sector_cap = 12.0
        if sector_total + target_weight_pct > sector_cap:
            target_weight_pct = max(0.0, sector_cap - sector_total)
        sector_weight_sum[sector] = sector_total + target_weight_pct

        current_pos = latest_positions.get(ticker)
        if current_pos is None:
            position_status = "신규편입대기"
            entry_date = today
            entry_price = current_close
            initial_stop_pct = 8.0 if _to_float(row.get("total_score", 0.0)) >= 75 else 10.0
            initial_stop_price = current_close * (1.0 - initial_stop_pct / 100.0) if current_close > 0 else np.nan
            trailing_stop_price = initial_stop_price
            days_held = 0
            order_side = "BUY"
            order_type = "MKT"
            reason_code = "NEW_ENTRY"
            event = "신규편입"
        else:
            position_status = str(current_pos.get("position_status", "보유") or "보유")
            entry_date = str(current_pos.get("entry_date", today) or today)
            entry_price = _to_float(current_pos.get("entry_price", current_close))
            current_weight_pct = _to_float(current_pos.get("current_weight_pct", 0.0))
            initial_stop_price = _to_float(current_pos.get("initial_stop_price", np.nan))
            trailing_stop_price = _to_float(current_pos.get("trailing_stop_price", np.nan))
            days_held = int(_to_float(current_pos.get("days_held", 0.0)) or 0)

            trail_pct = 10.0 if _to_float(row.get("total_score", 0.0)) >= 70 else 12.0
            new_trailing = current_close * (1.0 - trail_pct / 100.0) if current_close > 0 else trailing_stop_price
            if np.isfinite(trailing_stop_price):
                trailing_stop_price = max(trailing_stop_price, new_trailing)
            else:
                trailing_stop_price = new_trailing

            if current_close > 0 and np.isfinite(initial_stop_price) and current_close <= initial_stop_price:
                position_status = "청산"
                target_weight_pct = 0.0
                order_side = "SELL"
                order_type = "MKT"
                reason_code = "STOP_LOSS"
                event = "초기손절"
            elif current_close > 0 and np.isfinite(trailing_stop_price) and current_close <= trailing_stop_price:
                position_status = "청산"
                target_weight_pct = 0.0
                order_side = "SELL"
                order_type = "MKT"
                reason_code = "TRAIL_STOP"
                event = "트레일링손절"
            elif days_held >= 20 and _to_float(row.get("total_score", 0.0)) < 65:
                position_status = "청산"
                target_weight_pct = 0.0
                order_side = "SELL"
                order_type = "MKT"
                reason_code = "TIME_EXIT"
                event = "시간종료"
            elif str(row.get("action", "")) == "제외":
                position_status = "청산"
                target_weight_pct = 0.0
                order_side = "SELL"
                order_type = "MKT"
                reason_code = "MODEL_EXIT"
                event = "가설붕괴"
            else:
                position_status = "보유"
                order_side = "HOLD"
                order_type = "NONE"
                reason_code = "KEEP"
                event = "유지"

        if current_pos is None:
            current_weight_pct = 0.0
        else:
            current_weight_pct = _to_float(current_pos.get("current_weight_pct", 0.0))
            if position_status == "보유" and target_weight_pct <= 0:
                target_weight_pct = current_weight_pct

        processed_tickers.add(ticker)

        row_out = {
            "as_of_date": today,
            "ticker": ticker,
            "name": str(row.get("name", row.get("종목명", "")) or "").strip(),
            "market": str(row.get("market", row.get("시장", "")) or "").strip(),
            "sector_group": sector,
            "position_status": position_status,
            "entry_date": entry_date,
            "entry_price": entry_price,
            "current_price": current_close,
            "current_weight_pct": current_weight_pct,
            "target_weight_pct": target_weight_pct,
            "initial_stop_price": initial_stop_price,
            "trailing_stop_price": trailing_stop_price,
            "days_held": days_held,
            "total_score": _to_float(row.get("total_score", np.nan)),
            "combined_action": str(row.get("action", "") or ""),
            "reason_code": reason_code,
            "brief_reason": str(row.get("brief_reason", "") or "").strip(),
            "warn_flags": str(row.get("warn_flags", "") or "").strip(),
        }
        rows.append(row_out)

        if order_side != "HOLD":
            order_rows.append(
                {
                    "order_id": f"{today.replace('-', '')}-{ticker}-{order_side}",
                    "trade_date": today,
                    "ticker": ticker,
                    "side": order_side,
                    "order_type": order_type,
                    "target_weight_pct": target_weight_pct,
                    "reason_code": reason_code,
                    "status": "제안",
                }
            )

        event_rows.append(
            {
                "event_ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "trade_date": today,
                "ticker": ticker,
                "event": event,
                "position_status": position_status,
                "current_weight_pct": current_weight_pct,
                "target_weight_pct": target_weight_pct,
                "reason_code": reason_code,
            }
        )

    for ticker, current_pos in latest_positions.items():
        if ticker in processed_tickers:
            continue

        signal_row = signal_lookup.get(ticker)
        current_weight_pct = _to_float(current_pos.get("current_weight_pct", 0.0))
        current_close = _to_float(signal_row.get("close", np.nan)) if signal_row is not None else np.nan
        entry_price = _to_float(current_pos.get("entry_price", current_close))
        initial_stop_price = _to_float(current_pos.get("initial_stop_price", np.nan))
        trailing_stop_price = _to_float(current_pos.get("trailing_stop_price", np.nan))
        days_held = int(_to_float(current_pos.get("days_held", 0.0)) or 0)
        sector = str(current_pos.get("sector_group", "기타") or "기타")
        position_status = str(current_pos.get("position_status", "보유") or "보유")

        if signal_row is None:
            reason_code = "NO_SIGNAL"
            event = "신호없음동결"
            target_weight_pct = current_weight_pct
            order_side = "HOLD"
            order_type = "NONE"
        else:
            combined_action = str(signal_row.get("action", "") or "")
            total_score = _to_float(signal_row.get("total_score", np.nan))
            breakout = int(_to_float(signal_row.get("breakout_20d_high", 0)) or 0)
            above_ma200 = int(_to_float(signal_row.get("above_ma200", 0)) or 0)
            if current_close > 0 and np.isfinite(initial_stop_price) and current_close <= initial_stop_price:
                position_status = "청산"
                target_weight_pct = 0.0
                order_side = "SELL"
                order_type = "MKT"
                reason_code = "STOP_LOSS"
                event = "초기손절"
            elif current_close > 0 and np.isfinite(trailing_stop_price) and current_close <= trailing_stop_price:
                position_status = "청산"
                target_weight_pct = 0.0
                order_side = "SELL"
                order_type = "MKT"
                reason_code = "TRAIL_STOP"
                event = "트레일링손절"
            elif days_held >= 20 and total_score < 65:
                position_status = "청산"
                target_weight_pct = 0.0
                order_side = "SELL"
                order_type = "MKT"
                reason_code = "TIME_EXIT"
                event = "시간종료"
            elif combined_action == "제외":
                position_status = "청산"
                target_weight_pct = 0.0
                order_side = "SELL"
                order_type = "MKT"
                reason_code = "MODEL_EXIT"
                event = "가설붕괴"
            else:
                if current_close > 0:
                    trail_pct = 10.0 if total_score >= 70 else 12.0
                    new_trailing = current_close * (1.0 - trail_pct / 100.0)
                    if np.isfinite(trailing_stop_price):
                        trailing_stop_price = max(trailing_stop_price, new_trailing)
                    else:
                        trailing_stop_price = new_trailing
                position_status = "보유"
                target_weight_pct = current_weight_pct
                order_side = "HOLD"
                order_type = "NONE"
                if combined_action == "최종매수후보" and breakout == 1 and above_ma200 == 1:
                    reason_code = "KEEP_BUY"
                    event = "보유강화"
                else:
                    reason_code = "KEEP"
                    event = "유지"

        rows.append(
            {
                "as_of_date": today,
                "ticker": ticker,
                "name": str(current_pos.get("name", "") or "").strip(),
                "market": str(current_pos.get("market", "") or "").strip(),
                "sector_group": sector,
                "position_status": position_status,
                "entry_date": str(current_pos.get("entry_date", today) or today),
                "entry_price": entry_price,
                "current_price": current_close,
                "current_weight_pct": current_weight_pct,
                "target_weight_pct": target_weight_pct,
                "initial_stop_price": initial_stop_price,
                "trailing_stop_price": trailing_stop_price,
                "days_held": days_held,
                "total_score": _to_float(signal_row.get("total_score", np.nan)) if signal_row is not None else np.nan,
                "combined_action": str(signal_row.get("action", "") or "") if signal_row is not None else "",
                "reason_code": reason_code,
                "brief_reason": str(signal_row.get("brief_reason", "") or "") if signal_row is not None else "보유중",
                "warn_flags": str(signal_row.get("warn_flags", "") or "") if signal_row is not None else "",
            }
        )

        if order_side != "HOLD":
            order_rows.append(
                {
                    "order_id": f"{today.replace('-', '')}-{ticker}-{order_side}",
                    "trade_date": today,
                    "ticker": ticker,
                    "side": order_side,
                    "order_type": order_type,
                    "target_weight_pct": target_weight_pct,
                    "reason_code": reason_code,
                    "status": "제안",
                }
            )

        event_rows.append(
            {
                "event_ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "trade_date": today,
                "ticker": ticker,
                "event": event,
                "position_status": position_status,
                "current_weight_pct": current_weight_pct,
                "target_weight_pct": target_weight_pct,
                "reason_code": reason_code,
            }
        )

    position_df = pd.DataFrame(rows)
    if position_df.empty:
        position_df = pd.DataFrame(columns=[
            "as_of_date",
            "ticker",
            "name",
            "market",
            "sector_group",
            "position_status",
            "entry_date",
            "entry_price",
            "current_price",
            "current_weight_pct",
            "target_weight_pct",
            "initial_stop_price",
            "trailing_stop_price",
            "days_held",
            "total_score",
            "combined_action",
            "reason_code",
            "brief_reason",
            "warn_flags",
        ])

    position_df = position_df.sort_values(by=["target_weight_pct", "total_score"], ascending=False).reset_index(drop=True)
    position_df = position_df.reset_index(drop=True)
    position_df["target_weight_pct"] = position_df["target_weight_pct"].fillna(0.0).astype(float)
    position_df = pd.DataFrame(_scale_weights(position_df.to_dict("records")))

    if not position_df.empty:
        position_df["portfolio_weight_pct"] = position_df["target_weight_pct"].astype(float)

    order_df = pd.DataFrame(order_rows)
    event_df = pd.DataFrame(event_rows)
    return position_df, order_df, event_df


def _write_outputs(position_df: pd.DataFrame, order_df: pd.DataFrame, event_df: pd.DataFrame, output_prefix: str | None = None) -> tuple[Path, Path, Path]:
    today = _trade_date_text()
    suffix = output_prefix or today

    position_path = OUTPUT_DIR / f"positions_{suffix}.csv"
    order_path = OUTPUT_DIR / f"orders_{suffix}.csv"
    event_path = OUTPUT_DIR / f"position_events_{suffix}.csv"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    position_df.to_csv(position_path, index=False, encoding="utf-8-sig")
    order_df.to_csv(order_path, index=False, encoding="utf-8-sig")
    event_df.to_csv(event_path, index=False, encoding="utf-8-sig")

    position_df.to_csv(OUTPUT_DIR / "positions.csv", index=False, encoding="utf-8-sig")
    order_df.to_csv(OUTPUT_DIR / "orders.csv", index=False, encoding="utf-8-sig")
    event_df.to_csv(OUTPUT_DIR / "position_events.csv", index=False, encoding="utf-8-sig")
    return position_path, order_path, event_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage positions from the latest detailed report")
    parser.add_argument("--signals", type=str, default="", help="Optional detailed report CSV path")
    parser.add_argument("--positions", type=str, default="", help="Optional existing positions CSV path")
    parser.add_argument("--output-prefix", type=str, default="", help="Optional output file suffix")
    args = parser.parse_args()

    signals = _load_signal_frame(args.signals or None)
    current_positions = _read_csv(Path(args.positions)) if args.positions and Path(args.positions).exists() else _load_positions()
    signals = _normalise_signals(signals)
    current_positions = _normalise_positions(current_positions)

    position_df, order_df, event_df = _build_position_plan(signals, current_positions)
    position_path, order_path, event_path = _write_outputs(position_df, order_df, event_df, output_prefix=args.output_prefix or None)

    print(f"[Positions] Saved: {position_path} ({len(position_df)} rows)")
    print(f"[Positions] Saved: {order_path} ({len(order_df)} rows)")
    print(f"[Positions] Saved: {event_path} ({len(event_df)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())